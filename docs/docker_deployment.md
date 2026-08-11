# Docker Deployment Guide

Practical, command-level companion to `docs/deployment.md` Sections 4, 6,
13.6, and 15.6 — this document covers *how* to build, run, and operate
the containerized stack; the sections referenced above cover *why* it's
shaped this way. If something here and `docs/deployment.md` ever
disagree, `docs/deployment.md` is the architectural source of truth and
this document should be corrected to match it.

## Table of Contents

1. Prerequisites
2. Repository Layout
3. Environment Files
4. Local Development (Docker Compose)
5. Production Stack (Docker Compose)
6. Database Migrations
7. Building and Running Images Directly (no Compose)
8. The Job System (Background Workers)
9. Prometheus and Grafana
10. Health and Readiness Probes
11. CD Pipeline (GitHub Actions → GHCR)
12. Deploying a New Image
13. Scaling
14. Troubleshooting

---

## 1. Prerequisites

- Docker Engine 24+ and Docker Compose v2 (`docker compose`, not the legacy standalone `docker-compose`).
- A Supabase project (URL, anon key, service-role key, direct Postgres connection string) — Supabase itself is never containerized here; it's an external managed dependency in every environment (`docs/deployment.md` Section 7).
- Redis is **optional**. Every Redis-backed feature (shared rate limiting, shared analytics cache, the job system's live dispatch layer) degrades to its original single-process/synchronous behavior when `REDIS_URL` is unset — nothing in this stack requires Redis to run.

## 2. Repository Layout

| Path | Purpose |
|---|---|
| `Dockerfile` | Backend (FastAPI) production image — multi-stage, non-root, `HEALTHCHECK` against `/api/v1/health/live` |
| `frontend/Dockerfile` | Frontend (Next.js) production image — multi-stage, non-root, `HEALTHCHECK` against `/api/health` |
| `docker-compose.production.yml` | backend, worker-default, worker-escalation, frontend, redis, prometheus, grafana |
| `docker-compose.development.yml` | backend (hot-reload, bind-mounted), frontend (`next dev`, bind-mounted), redis |
| `deploy/prometheus/prometheus.yml` | Prometheus scrape config |
| `deploy/grafana/provisioning/` | Auto-provisioned datasource + dashboard registration |
| `deploy/grafana/dashboards/eah-overview.json` | The starter Grafana dashboard |
| `.github/workflows/cd.yml` | Builds and pushes both images to GHCR |

## 3. Environment Files

```bash
cp .env.example .env                                  # backend + compose interpolation
cp frontend/.env.local.example frontend/.env.local     # frontend (NEXT_PUBLIC_*, API base URL)
```

Fill in real Supabase values in both files. `.env.example`'s "Frontend Docker build args" section explains why `NEXT_PUBLIC_SUPABASE_URL`/`NEXT_PUBLIC_SUPABASE_ANON_KEY` need to be set in the **root** `.env` too (not only `frontend/.env.local`) for `docker compose build` to bake them into the frontend image correctly — Next.js inlines `NEXT_PUBLIC_*` values at build time, and Compose's `${...}` substitution in `docker-compose.production.yml` reads only the root `.env`.

Never commit a populated `.env` or `.env.local` — both are already covered by the standard `.gitignore` entries this repository has always had.

**Using a managed Redis instead of the bundled `redis` Compose service** — on a host that doesn't run `docker-compose.production.yml` itself (e.g. a single-container PaaS like Back4App/Render/Railway), there's no `redis` service alongside `backend` to point `REDIS_URL` at. A managed provider such as [Upstash](https://upstash.com) works as a drop-in replacement: create a database, copy the connection string from its dashboard, and set it as `REDIS_URL` in that platform's environment variables. No code or Compose changes needed — `app.utils.redis_client.create_redis_client` builds the client via `redis.Redis.from_url`, which handles `rediss://` (TLS) the same as plain `redis://`. See the `REDIS_URL` entry in `.env.example` for the expected URL shape.

## 4. Local Development (Docker Compose)

```bash
docker compose -f docker-compose.development.yml up --build
```

- Backend: `http://localhost:8000` (Uvicorn `--reload`, bind-mounted `./app`)
- Frontend: `http://localhost:3000` (`next dev`, bind-mounted `./frontend`)
- Redis: `localhost:6379` (published for local debugging with `redis-cli`)

Edits to `app/` or `frontend/src/` take effect without rebuilding — this is an alternative to running `uvicorn`/`next dev` directly on the host, not a replacement; both workflows remain fully supported.

## 5. Production Stack (Docker Compose)

```bash
docker compose -f docker-compose.production.yml up -d --build
```

Brings up `redis`, `backend` (Scheduler leader by default), `worker-default`, `worker-escalation`, `frontend`, `prometheus`, and `grafana`. Check status:

```bash
docker compose -f docker-compose.production.yml ps
docker compose -f docker-compose.production.yml logs -f backend
```

Tear down (keeping volumes — Redis/Prometheus/Grafana data survives):

```bash
docker compose -f docker-compose.production.yml down
```

Add `-v` to also remove the named volumes (`redis_data`, `prometheus_data`, `grafana_data`) — do this deliberately, not as a routine step (`docs/deployment.md` Section 16.5 on why this is safe for Redis specifically, but Prometheus/Grafana history is still lost).

## 6. Database Migrations

Migrations are **not** run automatically by any container's `CMD` — per `docs/deployment.md` Section 11.2, migrations must be applied and confirmed *before* new application code starts serving traffic, never as an implicit side effect of a container starting. Run them as a one-off task using the backend image (which already contains `alembic.ini` and `app/database/migrations`):

```bash
docker compose -f docker-compose.production.yml run --rm backend \
  alembic upgrade head
```

## 7. Building and Running Images Directly (no Compose)

```bash
# Backend
docker build -t eah-backend .
docker run -p 8000:8000 --env-file .env eah-backend

# Frontend
cd frontend
docker build -t eah-frontend .
docker run -p 3000:3000 --env-file .env.local eah-frontend
```

## 8. The Job System (Background Workers)

`docker-compose.production.yml` runs two worker roles from the same backend image, differing only in `command`/environment (`docs/deployment.md` Section 13.7):

- **`worker-default`** — `python -m app.jobs.worker --role default` — delivers `send_email`/`send_invitation_email` jobs. Only does anything once `EMAIL_DISPATCH_MODE=queue` is set (requires `REDIS_URL`); with the default `direct` mode, email/invitation dispatch is synchronous and this container simply idles.
- **`worker-escalation`** — `python -m app.jobs.worker --role escalation` — delivers `escalate_stage`/`send_reminder` jobs, enqueued by the Scheduler leader's Escalation Check/Reminder Dispatch jobs whenever `REDIS_URL` is set. Unlike email, this doesn't need `EMAIL_DISPATCH_MODE=queue` — escalation/reminder execution goes through the job system automatically once Redis is configured, and falls back to running synchronously on the Scheduler leader's own thread when it isn't (no `worker-escalation` container needed in that case).

Neither role has a leader/singleton constraint — running more than one replica of either is safe and only increases delivery throughput.

```bash
docker compose -f docker-compose.production.yml logs -f worker-default
docker compose -f docker-compose.production.yml logs -f worker-escalation
```

Inspect job status/history, retry a dead-lettered job, or manage scheduled jobs from the command line via the admin API (requires an admin bearer token):

```bash
curl -H "Authorization: Bearer <admin-token>" http://localhost:8000/api/v1/admin/jobs/dead-letter
curl -H "Authorization: Bearer <admin-token>" http://localhost:8000/api/v1/admin/jobs/stats/summary
curl -H "Authorization: Bearer <admin-token>" -X POST http://localhost:8000/api/v1/admin/jobs/<job-id>/retry
```

Or use the frontend admin page at `/admin/jobs`. See `docs/job_system_migration.md` for what changes when upgrading an existing deployment.

## 9. Prometheus and Grafana

- Prometheus UI: `http://localhost:9090` — confirm the `eah-backend` and `eah-worker` targets are `UP` under Status → Targets.
- Grafana UI: `http://localhost:3001` — log in with `admin` / `${GRAFANA_ADMIN_PASSWORD}` (set this in `.env`; required — `docker compose up` refuses to start this stack if it's unset or empty, rather than silently falling back to Grafana's well-known `admin` default password). The "Enterprise Automation Hub" folder's "Enterprise Automation Hub — Overview" dashboard is auto-provisioned — no manual data source or dashboard import needed.
- Raw metrics: `curl http://localhost:8000/metrics`.

**On a real host, do not leave ports 9090 (Prometheus) and 3001 (Grafana) reachable from the public internet.** `docker-compose.production.yml` publishes both directly via `ports:`, intended for access from behind a load balancer or over an operator VPN/tunnel — Prometheus itself has no authentication of its own (Grafana's password requirement, enforced above, does not cover it). Note that Docker manipulates `iptables` directly to publish container ports, which is well known to bypass a host firewall (`ufw`/`firewalld`) rule that appears to block them — restricting these at the cloud security-group/network-ACL layer (not just the host firewall) is the reliable way to keep them private.

## 10. Health and Readiness Probes

| Endpoint | Checks | Used by |
|---|---|---|
| `GET /api/v1/health/live` | Nothing (process-up only) | Backend container `HEALTHCHECK` |
| `GET /api/v1/health/ready` | Supabase reachability, Redis reachability (if configured) | An orchestrator's readiness probe |
| `GET /api/v1/health` | Same as `/health/ready` (kept for backward compatibility) | Load balancer |
| `GET /api/health` (frontend) | Nothing (process-up only) | Frontend container `HEALTHCHECK` |

```bash
docker inspect --format='{{json .State.Health}}' <container-id>
```

## 11. CD Pipeline (GitHub Actions → GHCR)

`.github/workflows/cd.yml` runs on every push to `main` and on `v*` tags: builds both images and pushes to `ghcr.io/<owner>/<repo>-backend` and `ghcr.io/<owner>/<repo>-frontend`, tagged with the full commit SHA and `latest` (plus the tag name for a `v*` push). No repository secrets are required — it authenticates with the automatically-provisioned `GITHUB_TOKEN`.

Pull a specific build:

```bash
docker pull ghcr.io/<owner>/<repo>-backend:<commit-sha>
```

## 12. Deploying a New Image

This repository does not assume a specific production host, so the "deploy" step is intentionally left as an operator runbook rather than a scripted CD job with fabricated credentials. The common pattern, once a target Docker host exists:

```bash
# On the target host, with docker-compose.production.yml and .env already present:
docker compose -f docker-compose.production.yml pull
docker compose -f docker-compose.production.yml up -d
```

Point `docker-compose.production.yml`'s `backend`/`frontend` services at `image: ghcr.io/<owner>/<repo>-backend:<tag>` (instead of `build:`) once you're deploying published images rather than building locally. Wiring an SSH or webhook-triggered deploy job into `cd.yml` is a natural next step once a real target host/credentials exist — deliberately not added here.

## 13. Scaling

```bash
docker compose -f docker-compose.production.yml up -d --scale backend=3
```

Every backend container is stateless (`docs/deployment.md` Section 2). `SCHEDULER_LEADER=true` means an instance participates in the Scheduler pool (`docs/deployment.md` Section 13.2) — with `REDIS_URL` set (the reference production config), every `backend` replica may safely run with `SCHEDULER_LEADER=true`; Redis-backed leader election ensures only one is ever actually executing scheduled jobs at a time, with automatic failover (`docs/scheduler_distributed_coordination.md`). Only without Redis configured must exactly one replica run with `SCHEDULER_LEADER=true`, unchanged from before this layer existed. Scaling `worker-default`/`worker-escalation` has no leader constraint at all (Section 13.7) — each may be scaled independently. Don't scale `frontend` and `backend` replicas past what your load balancer/Supabase project's connection limits support.

## 14. Troubleshooting

| Symptom | Likely Cause | Resolution |
|---|---|---|
| `backend` container unhealthy | Bad `SUPABASE_*` credentials, or Supabase unreachable from the container network | `docker compose logs backend`; confirm `.env` values; the healthcheck hits `/health/live` (no dependency check) so an unhealthy status here means the *process itself* crashed, not just a Supabase blip — check readiness (`/health/ready`) separately for dependency status |
| `frontend` build fails on `npm run build` | Missing/placeholder `NEXT_PUBLIC_SUPABASE_URL`/`ANON_KEY` build args | Confirm the root `.env` has real values (Section 3) — the module-load-time validation in `src/lib/supabase/env.ts` fails the build otherwise |
| `worker-default` logs nothing / emails never deliver in queue mode | `REDIS_URL` not set on the `worker-default` service, or no `worker-default` container running at all | Confirm `EMAIL_DISPATCH_MODE=queue` and `REDIS_URL` are set identically on `backend` and `worker-default`; confirm at least one `worker-default` container is up |
| `worker-escalation` unhealthy | `app.jobs.healthcheck` can't reach Redis, or the container's heartbeat expired (worker hung/crashed) | `docker compose logs worker-escalation`; confirm `REDIS_URL` matches `backend`'s; a healthy worker refreshes its heartbeat every loop iteration (~5s) |
| A job stuck in `dead_lettered` | The handler failed on every attempt (SMTP down, a genuine bug) | Inspect `last_error`/`error_history` via `GET /admin/jobs/{id}` or the `/admin/jobs` frontend page; fix the underlying cause, then `POST /admin/jobs/{id}/retry` |
| Prometheus target `eah-backend`/`eah-worker` is `DOWN` | `METRICS_ENABLED=false` (backend only), or the service name/port in `deploy/prometheus/prometheus.yml` doesn't match the compose network | Confirm `METRICS_ENABLED` is unset/`true`; confirm `backend:8000`/`worker-default:9100`/`worker-escalation:9100` resolve inside the `eah` Docker network |
| Grafana shows no data | Prometheus datasource not reachable, or the dashboard's PromQL doesn't match your metric names | Confirm Prometheus itself has data (`curl http://localhost:9090/api/v1/query?query=up`); confirm `deploy/grafana/provisioning/datasources/datasource.yml`'s URL (`http://prometheus:9090`) is reachable from the Grafana container |
| Alembic migration fails inside `docker compose run backend alembic upgrade head` | `DATABASE_URL` misconfigured, or a genuine migration/schema conflict | See `docs/deployment.md` Section 11.5 — halt, do not proceed with the application deployment, author a corrective forward migration |
