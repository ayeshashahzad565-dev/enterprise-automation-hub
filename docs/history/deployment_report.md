# Enterprise Automation Hub — Production Infrastructure Layer Deployment Report

**Generated:** 2026-07-25
**Scope:** Adds a containerized, horizontally-scalable production infrastructure layer to the existing FastAPI + Next.js + Supabase application, without changing its existing architecture, API contract, or default (no-Docker, no-Redis) local development/CI behavior.

---

## 1. What Was Added

### Backend (all additive, opt-in via configuration)

| Capability | Files | Default behavior (no config) | Opt-in behavior |
|---|---|---|---|
| Redis client/settings | `app/utils/redis_client.py`, `app/config/settings.py` (`RedisSettings`) | Unused | `REDIS_URL` set → shared client constructed once in `app.bootstrap` |
| Redis-backed rate limiting | `app/utils/redis_rate_limiter.py` | `InMemoryRateLimiter` (unchanged) | Every rate limiter (read/write/upload/notification-poll/invitation) becomes Redis-backed, multi-instance-safe |
| Redis-backed analytics cache | `app/utils/redis_cache.py`, edits to `app/analytics/analytics_engine.py` / `operational_engine.py` | Private in-process `TTLCache` per engine (unchanged) | One shared `RedisCache` per engine (distinct namespaces), so a multi-instance deployment shares one analytics cache instead of N independently-stale copies |
| Redis-backed background email queue | `app/queue/` (new package: `redis_task_queue.py`, `jobs.py`, `redis_email_sender.py`, `worker.py`) | `ThreadPoolEmailDispatchExecutor` + synchronous SMTP send (unchanged) | `EMAIL_DISPATCH_MODE=queue` → email enqueued to Redis, delivered by a separate `worker` container reusing the existing `SmtpEmailProvider` |
| Correlation IDs | `app/api/middleware.py` (`CorrelationIdMiddleware`) | N/A — always on | `X-Correlation-Id` echoed/generated, logged alongside the existing `request_id` |
| Prometheus metrics | `app/observability/metrics.py`, `app/api/middleware.py` (`MetricsMiddleware`), `app/api/routers/metrics.py` | `GET /metrics` mounted by default (`METRICS_ENABLED=true`) | `METRICS_ENABLED=false` disables the endpoint |
| Liveness/readiness split | `app/api/routers/health.py` | `GET /api/v1/health` unchanged | `GET /api/v1/health/live`, `GET /api/v1/health/ready` added |

**Zero breaking changes**: every new capability defaults to today's exact behavior. `pytest` (631 tests), `ruff check .`, `mypy app`, and `bandit -r app -ll -ii` all pass clean with no `REDIS_URL` configured, proving the default path is unaffected.

### Containerization

- `Dockerfile` — multi-stage backend image (builder → slim runtime), non-root `appuser`, `HEALTHCHECK` against `/api/v1/health/live`.
- `frontend/Dockerfile` — three-stage frontend image (`deps` → `builder` → `runner`), Next.js `output: "standalone"`, non-root `node` user, `HEALTHCHECK` against a new `GET /api/health` route.
- `.dockerignore`, `frontend/.dockerignore`.
- `docker-compose.production.yml` — `backend`, `worker`, `frontend`, `redis`, `prometheus`, `grafana`.
- `docker-compose.development.yml` — hot-reload backend/frontend (bind-mounted, targeting the `builder`/`deps` image stages), `redis`.

### Observability

- `deploy/prometheus/prometheus.yml` — scrapes `backend:8000/metrics`.
- `deploy/grafana/provisioning/` — auto-provisioned Prometheus datasource + dashboard registration.
- `deploy/grafana/dashboards/eah-overview.json` — request rate, p95 latency, error rate, rate-limit rejections.

### CI/CD

- `.github/workflows/cd.yml` — builds and pushes both images to GHCR on push to `main`/`v*` tags, using the auto-provisioned `GITHUB_TOKEN` (no new secrets). Deliberately stops at "image published" — see `docs/docker_deployment.md` Section 12 for why an actual deploy-to-host step isn't scripted (no real target host/credentials exist in this repository).

### Documentation

- `docs/deployment.md` — updated to Version 2.0: replaced the (stale, pre-dating the Streamlit removal) Section 6 "Streamlit Deployment" with "Application Deployment: FastAPI + Next.js + Docker"; updated Sections 1.4, 2, 4, 8, 13 (new 13.6), 15 (new 15.6), 16 (new 16.5), and 20 for the new infrastructure.
- `docs/docker_deployment.md` (new) — command-level operational guide.
- `README.md` — new "Running with Docker" section, documentation index updated.
- `.env.example` — `REDIS_URL`, `EMAIL_DISPATCH_MODE`, `METRICS_ENABLED`, Grafana admin password, frontend Docker build-arg values documented.

### Tests

New: `tests/unit/test_redis_rate_limiter.py`, `test_redis_cache.py`, `test_redis_task_queue.py`, `test_correlation_id_middleware.py`, `test_metrics_endpoint.py` (all against `fakeredis`, no real Redis required). Extended: `tests/unit/test_api_health.py` (liveness/readiness cases).

---

## 2. A Real Bug Found and Fixed Along the Way

While wiring `CorrelationIdMiddleware`, a genuine pre-existing inaccuracy surfaced in `app/api/main.py`'s middleware-ordering comment: Starlette's `add_middleware` *prepends* to its internal list and then builds the ASGI stack in reverse, so the **last**-added middleware ends up outermost — not the first, as the comment claimed. This never caused a visible bug in the four pre-existing middleware (`RequestLogging` reads `request.state` only *after* `call_next` returns, which works regardless of ordering), but it did break `CorrelationIdMiddleware`'s state read initially. Fixed by reordering `RequestIDMiddleware`/`CorrelationIdMiddleware`'s registration and correcting the comment to describe Starlette's actual behavior — verified with a minimal reproduction against the installed Starlette version before and after the fix.

---

## 3. Verification Performed

| Check | Result |
|---|---|
| `pytest` (full suite) | 631 passed, 67 skipped (integration tests requiring a real Supabase project — unchanged, pre-existing skip condition) |
| `ruff check .` | All checks passed |
| `mypy app` | Success: no issues found in 188 source files |
| `bandit -r app -ll -ii` | No issues identified (one justified `# nosec B301` for the internal-only Redis cache's `pickle` use, documented in-code) |
| `docker build -f Dockerfile .` | Succeeded — 389MB |
| `docker build -f frontend/Dockerfile frontend` | Succeeded — 380MB |
| `docker compose -f docker-compose.production.yml config` | Validates cleanly |
| `docker compose -f docker-compose.development.yml config` | Validates cleanly |
| Redis-backed rate limiter/cache/task queue against a **real** `redis:7-alpine` container (not just `fakeredis`) | All three verified working end-to-end (rate limiting, cache round-trip, enqueue/dequeue) |
| `docker compose -f docker-compose.production.yml up -d` (full stack: backend, worker, frontend, redis, prometheus, grafana) | All 6 containers started; `backend`/`frontend`/`redis` reported `(healthy)`; see endpoint checks below |
| `GET http://localhost:8000/api/v1/health/live` | `{"status":"alive"}` |
| `GET http://localhost:8000/api/v1/health/ready` | `{"status":"degraded","database":"unreachable","scheduler_active":true,"redis":"ok"}` — `database: unreachable` is correct/expected (`.env` held placeholder Supabase credentials, no real project configured for this smoke test); `redis: ok` and `scheduler_active: true` confirm both new wiring paths work against a real container |
| `GET http://localhost:8000/metrics` | Returned Prometheus text format; `eah_http_requests_total{method="GET",path_template="/health/live",...}` present with correctly-templated (non-raw-id) path labels |
| `GET http://localhost:3000/api/health` (frontend container) | `{"status":"ok"}` |
| Prometheus `/api/v1/targets` | `eah-backend` target `health: "up"`, scraping `backend:8000/metrics` |
| Grafana `/api/search` (authenticated) | "Enterprise Automation Hub — Overview" dashboard present, auto-provisioned, no manual setup |

**One real bug found and fixed during this stack-level verification** (not caught by unit tests, since it only manifests when the `worker` container actually runs): the `worker` service inherited the backend image's `HEALTHCHECK`, which probes `http://localhost:8000/api/v1/health/live` — but the worker runs `python -m app.queue.worker`, not Uvicorn, and never binds port 8000, so that healthcheck would always fail and the container would be reported unhealthy indefinitely. Fixed by disabling the inherited healthcheck for the `worker` service in `docker-compose.production.yml` (`healthcheck: {disable: true}`), with `docker compose logs worker` documented as this service's actual liveness signal instead.

After verification, the stack was torn down (`docker compose down`) and the ad hoc test images/`.env` files created for this pass were removed; nothing from this verification run is left running.

---

## 4. Explicitly Out of Scope

- **Other design documents** (`docs/architecture.md`, `docs/api_design.md`, `docs/requirements.md`, etc.) still describe the removed Streamlit UI as current — a pre-existing gap already flagged in `PROJECT_SUMMARY.md` §12, predating this pass. Rewriting them is a separate, much larger documentation effort unrelated to the production infrastructure layer and was not attempted here.
- **A real production deploy target.** No hosting provider, domain, or TLS certificate is assumed or configured — `cd.yml` publishes images; pointing them at an actual host is a deliberately manual/pluggable operator step (`docs/docker_deployment.md` §12).
- **Kubernetes/full container orchestration.** Docker Compose is this layer's orchestration ceiling, matching the existing Deployment Guide's stated scope discipline.
- **Migrating the invitation email path to the Redis queue.** Only `NotificationService`'s email dispatch was wired to the optional queue; `InvitationService`'s SMTP sending is untouched, noted as a documented future extension rather than silently expanded scope.
