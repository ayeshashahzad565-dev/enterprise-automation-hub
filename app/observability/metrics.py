"""Prometheus metric definitions.

Every metric here is process-global (module-level), matching
``prometheus_client``'s own idiom — a metric object is a singleton
registered once against the library's default registry at import time,
and every subsequent call just increments/observes it. No metric is ever
labeled with a raw, high-cardinality value (a user id, a request id, a
literal ``/requests/<uuid>`` path) — only the *route template* (e.g.
``/requests/{request_id}``), HTTP method, and status code, keeping the
label cardinality bounded regardless of traffic volume.
"""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

__all__ = [
    "REQUEST_COUNT",
    "REQUEST_LATENCY_SECONDS",
    "RATE_LIMIT_REJECTIONS_TOTAL",
    "JOB_QUEUE_DEPTH",
    "JOB_DELAYED_COUNT",
    "JOB_DEAD_LETTER_COUNT",
    "JOB_DURATION_SECONDS",
    "JOBS_PROCESSED_TOTAL",
    "WORKER_UP",
]

REQUEST_COUNT = Counter(
    "eah_http_requests_total",
    "Total HTTP requests processed, by method, route template, and status code.",
    ["method", "path_template", "status_code"],
)

REQUEST_LATENCY_SECONDS = Histogram(
    "eah_http_request_duration_seconds",
    "HTTP request duration in seconds, by method and route template.",
    ["method", "path_template"],
)

RATE_LIMIT_REJECTIONS_TOTAL = Counter(
    "eah_rate_limit_rejections_total",
    "Total requests rejected for exceeding a configured rate limit.",
)

# --- Job system (app.jobs) ---------------------------------------------
#
# The three gauges below reflect *external* (Redis/Postgres) state, not
# something this process counts incrementally — they are refreshed at
# scrape time (app.api.routers.metrics.get_metrics, reading via the
# backend's own resources.redis_job_queue/job_repository), the standard
# Prometheus pattern for "current state of an external system," rather
# than being set/incremented from request-handling code.
JOB_QUEUE_DEPTH = Gauge(
    "eah_job_queue_depth",
    "Number of jobs currently ready (not delayed) for one (queue_name, priority) pair.",
    ["queue_name", "priority"],
)
JOB_DELAYED_COUNT = Gauge(
    "eah_job_delayed_count",
    "Number of jobs currently waiting in the delayed/retry set for one queue.",
    ["queue_name"],
)
JOB_DEAD_LETTER_COUNT = Gauge(
    "eah_job_dead_letter_count",
    "Number of dead-lettered jobs currently in one queue.",
    ["queue_name"],
)

# The three below are worker-local: incremented directly by
# app.jobs.worker as jobs are processed, exposed via each worker
# process's own small metrics HTTP server (WORKER_METRICS_PORT) — see
# that module's docstring for why they cannot be exposed through the
# backend's /metrics instead (workers have no HTTP server of their own
# otherwise).
JOB_DURATION_SECONDS = Histogram(
    "eah_job_duration_seconds",
    "Job execution duration in seconds, by task_type.",
    ["task_type"],
)
JOBS_PROCESSED_TOTAL = Counter(
    "eah_jobs_processed_total",
    "Total jobs processed, by task_type and outcome (succeeded, retrying, dead_lettered).",
    ["task_type", "outcome"],
)
WORKER_UP = Gauge(
    "eah_worker_up",
    "Always 1 while a worker process is running; present per worker_id/role.",
    ["worker_id", "role"],
)
