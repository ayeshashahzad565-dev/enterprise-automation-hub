# Job System Migration Notes

This document is for an operator upgrading an **existing** Enterprise
Automation Hub deployment to the version that introduces the
production-grade job system (`app.jobs`), replacing the earlier, minimal
`app.queue` package. If you are standing up a brand-new deployment, this
document is not necessary reading — `docs/deployment.md` Section 13.7 and
`docs/docker_deployment.md` Section 8 already describe the current
system directly.

## What changed, at a glance

| Before | Now |
|---|---|
| `app.queue` — one shared Redis list, one task type (`send_email`), no retry/priority/history | `app.jobs` — per-queue/per-priority Redis ready lists, a delayed/retry set, four task types, exponential backoff, dead-letter, and a durable Postgres `jobs` table recording every job's full status/history |
| One `worker` container (`python -m app.queue.worker`) | Two worker roles from the same image: `worker-default` (email/invitation) and `worker-escalation` (escalation/reminder) — `python -m app.jobs.worker --role ...` |
| Escalation/reminder execution always ran inline, synchronously, in the Scheduler leader's own thread | Still runs inline/synchronously when Redis is not configured (byte-for-byte the same behavior); when Redis **is** configured, execution moves to `worker-escalation` with retry/backoff/dead-letter |
| Invitation email always dispatched synchronously, regardless of `EMAIL_DISPATCH_MODE` | Now queues through the job system when `EMAIL_DISPATCH_MODE=queue` (and Redis is configured), matching `NotificationService`'s existing email leg |
| No admin visibility into queued/failed background work | `GET /admin/jobs`, `/admin/jobs/dead-letter`, `/admin/jobs/stats/summary`, `/admin/scheduled-jobs`, and the `/admin/jobs` frontend page |

## Required step: run the new migration

The `jobs` table (migration `0015_jobs`) must exist before deploying the new backend/worker images — both the backend and any worker will fail at the point they first try to read/write it if the table is missing.

```bash
docker compose -f docker-compose.production.yml run --rm backend alembic upgrade head
```

(Or your existing migration procedure — see `docs/docker_deployment.md` Section 6 / `docs/deployment.md` Section 11.)

## Required step: update your Compose topology

The single `worker` service is replaced by `worker-default` and `worker-escalation` in the reference `docker-compose.production.yml`. If you run a customized override or a hand-maintained equivalent (Kubernetes manifests, systemd units, etc.) rather than the file as shipped, update it to match:

- Both roles build from the same backend image, differing only in `command` (`python -m app.jobs.worker --role default` / `--role escalation`) and a couple of environment variables — see the reference compose file for the exact shape.
- Both need a **real** healthcheck now (`python -m app.jobs.healthcheck`), replacing the old worker's `healthcheck: {disable: true}` — the old worker had no way to signal liveness at all; the new one refreshes a Redis heartbeat key every loop iteration.
- If you scrape Prometheus metrics, add the `eah-worker` job to your `prometheus.yml` (targets: `worker-default:9100`, `worker-escalation:9100`) — each worker now runs its own tiny metrics HTTP server, since it has no other HTTP server to expose job-processing metrics through.

## No new required environment variables

Every new setting (`WORKER_ROLE`, `WORKER_METRICS_PORT`, `JOB_DEFAULT_MAX_ATTEMPTS`, `STUCK_JOB_THRESHOLD_MINUTES`, `STUCK_JOB_REAPER_INTERVAL_MINUTES`) is optional with a sensible default — see `.env.example`. `REDIS_URL` and `EMAIL_DISPATCH_MODE` keep their existing meaning; nothing about how you set them today needs to change.

If you were already running `EMAIL_DISPATCH_MODE=queue`, that continues to work exactly as before, with retry/backoff/dead-letter as a strict improvement over the old queue's "no retry at all" behavior.

## Behavior changes to be aware of

### Old Redis queue key (`eah:tasks`) is abandoned, not migrated

Anything sitting in the old `app.queue` list at the moment you cut over is **never consumed** by the new worker — it reads from a different set of Redis keys entirely (`eah:jobs:ready:*`). In practice this means:

- A handful of very recently queued emails, in flight at the exact moment of cutover, may be dropped.
- This is consistent with this system's existing "email dispatch is best-effort, never guaranteed" contract (`docs/deployment.md` Section 16.5) — the notification's own record (the `notifications` row) is unaffected; only the best-effort email side-channel is at risk, and only for jobs enqueued in roughly the last few seconds before cutover.
- If you need zero loss for a specific deployment, drain `eah:tasks` manually before cutover (pop every entry and re-enqueue via the old code path, or simply accept the entries and let them expire — they're harmless left in place, just permanently unconsumed).
- Deploying during a low-traffic window is the simplest mitigation and is sufficient for the vast majority of deployments.

### Invitation emails now queue in `EMAIL_DISPATCH_MODE=queue`

This is a **real behavior change**, not just an internal implementation detail, for any operator already running `EMAIL_DISPATCH_MODE=queue`: invitation creation/resend previously always sent synchronously (a documented gap), and now follows the same queued path email already did. Two things follow from this:

1. **Latency**: an admin's "create invitation" API call now returns as soon as the job is durably recorded, before the email is actually sent — the same "dispatch succeeded, not delivery confirmed" contract every other queued email already has.
2. **A short-lived security-relevant retention window**: the raw (unhashed) invitation token — never persisted anywhere before this change — now briefly exists in the `jobs` table's `payload` column and in Redis for the job's lifetime. A scheduled sweep removes `succeeded`/`dead_lettered` `send_invitation_email` job rows well before the invitation link itself would normally expire, and no log line anywhere logs the raw token. If your organization's threat model treats "raw token transiently present in an internal database table, readable only by the service-role credential" as materially different from "never persisted at all," factor that into your review before enabling `EMAIL_DISPATCH_MODE=queue` for invitations specifically.

### No new permission model

`/admin/jobs` and `/admin/scheduled-jobs` reuse the existing `UserRole.ADMIN` gate — no new role, permission, or database grant is introduced.

## Rollback

If you need to roll back to the pre-job-system version: redeploy the prior image tags, then run `alembic downgrade -1` (or target the prior revision explicitly) to drop the `jobs` table — this is safe since, per the design above, `jobs` is never a source of truth for anything else in the schema (no other table has a foreign key pointing *into* it). Any job rows not yet processed at rollback time are simply lost, the same class of best-effort loss described above for the old queue's abandoned keys.
