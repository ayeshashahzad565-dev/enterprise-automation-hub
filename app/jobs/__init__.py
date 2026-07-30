"""The production-grade background job system.

Supersedes the earlier, minimal ``app.queue`` package (a single Redis
list, one task type, no retry/priority/history). This package splits the
same responsibility across two tiers, matching the codebase's existing
"Postgres is truth, Redis is acceleration" convention (see
``docs/deployment.md`` Section 16.5):

- **Redis** (``app.jobs.redis_queue``) is the *live dispatch mechanism*
  only: per-``queue_name``, per-``priority`` ready lists a worker
  ``BRPOP``s from, plus a delayed sorted set used for both scheduled
  retries and starvation-free promotion back to a ready list. A job's
  Redis footprint is an ephemeral ``{"job_id", "priority"}`` pointer with
  no independent meaning — losing it (a Redis restart with no
  persistence, say) loses only *scheduling*, never the job's own record.
- **Postgres** (``app.database.repositories.job_repository.JobRepository``,
  table ``jobs``, migration ``0015_jobs``) is the durable system of
  record: every job's full status, payload, attempt history, and
  eventual outcome. This is what the admin dashboard
  (``app.api.routers.admin_jobs``) actually queries, and what survives a
  worker crash or a Redis restart intact.

``app.jobs.job_service.JobService`` is the single choke point that writes
both — no other code path creates a job. ``app.jobs.worker`` is the
consumer process (run as ``python -m app.jobs.worker``, in one of several
roles — see its own docstring); ``app.jobs.handlers`` holds the
per-``task_type`` dispatch table it consumes.
"""

from __future__ import annotations
