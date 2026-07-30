"""Global, non-secret application constants.

Per the architecture documents, this module is the single home for two
kinds of fixed values:

1. **Environment variable names** — the exact names specified in the
   Deployment Guide's Environment Variables table (DG Section 8), defined
   here once so that ``settings.py`` never spells out a raw string
   literal for a variable name, and so a rename is a one-line change in
   exactly one place.
2. **Default values and fixed limits** — defaults matching
   ``.env.example`` and limits already fixed by the API Design Document
   (pagination, rate limiting) and Database Schema Design Document
   (workflow escalation), defined here once rather than repeated at every
   call site that needs one.

This module defines no business enum (those belong exclusively to
``app.models.enums``) and performs no I/O of any kind.
"""

from __future__ import annotations

from typing import Final

# ---------------------------------------------------------------------------
# Application identity
# ---------------------------------------------------------------------------

APP_NAME: Final[str] = "Enterprise Automation Hub"
APP_SHORT_NAME: Final[str] = "EAH"

# ---------------------------------------------------------------------------
# API contract constants (API-ADD Sections 5, 9, 12)
# ---------------------------------------------------------------------------

API_VERSION_PREFIX: Final[str] = "/api/v1"
DEFAULT_PAGE_SIZE: Final[int] = 20
MAX_PAGE_SIZE: Final[int] = 100

# ---------------------------------------------------------------------------
# Environment variable names (DG Section 8)
# ---------------------------------------------------------------------------

ENV_APP_ENVIRONMENT: Final[str] = "APP_ENVIRONMENT"

ENV_SUPABASE_URL: Final[str] = "SUPABASE_URL"
ENV_SUPABASE_ANON_KEY: Final[str] = "SUPABASE_ANON_KEY"
ENV_SUPABASE_SERVICE_ROLE_KEY: Final[str] = "SUPABASE_SERVICE_ROLE_KEY"
ENV_DATABASE_URL: Final[str] = "DATABASE_URL"

ENV_SMTP_HOST: Final[str] = "SMTP_HOST"
ENV_SMTP_PORT: Final[str] = "SMTP_PORT"
ENV_SMTP_USERNAME: Final[str] = "SMTP_USERNAME"
ENV_SMTP_PASSWORD: Final[str] = "SMTP_PASSWORD"
ENV_SMTP_FROM_ADDRESS: Final[str] = "SMTP_FROM_ADDRESS"

ENV_SCHEDULER_LEADER: Final[str] = "SCHEDULER_LEADER"
ENV_SCHEDULER_ESCALATION_INTERVAL_MINUTES: Final[str] = "SCHEDULER_ESCALATION_INTERVAL_MINUTES"
ENV_SCHEDULER_REMINDER_INTERVAL_HOURS: Final[str] = "SCHEDULER_REMINDER_INTERVAL_HOURS"
ENV_SCHEDULER_ANALYTICS_INTERVAL_HOURS: Final[str] = "SCHEDULER_ANALYTICS_INTERVAL_HOURS"
#: Distributed Scheduler coordination (see
#: ``app.scheduler.leader_election``/``app.scheduler.distributed_lock``,
#: ``docs/scheduler_distributed_coordination.md``). Only meaningful when
#: ``REDIS_URL`` is set — absent Redis, ``SCHEDULER_LEADER`` above remains
#: the sole, static, single-instance mechanism, unchanged.
#: How long the Redis-backed Scheduler leader lock is held before it
#: expires if never renewed — the window a crashed leader's claim
#: disappears within, letting another instance take over automatically.
ENV_SCHEDULER_LEADER_LOCK_TTL_SECONDS: Final[str] = "SCHEDULER_LEADER_LOCK_TTL_SECONDS"
#: How long a single job's distributed execution lock is held before it
#: expires if never released — bounds how long a crashed instance can
#: block another instance from picking up that job's next tick. Should be
#: set comfortably above the slowest realistic execution time for any
#: registered job in this deployment.
ENV_SCHEDULER_JOB_LOCK_TTL_SECONDS: Final[str] = "SCHEDULER_JOB_LOCK_TTL_SECONDS"

ENV_LOG_LEVEL: Final[str] = "LOG_LEVEL"

ENV_RATE_LIMIT_READ_PER_MINUTE: Final[str] = "RATE_LIMIT_READ_PER_MINUTE"
ENV_RATE_LIMIT_WRITE_PER_MINUTE: Final[str] = "RATE_LIMIT_WRITE_PER_MINUTE"
ENV_RATE_LIMIT_UPLOAD_PER_MINUTE: Final[str] = "RATE_LIMIT_UPLOAD_PER_MINUTE"
ENV_RATE_LIMIT_LOGIN_PER_5_MINUTES: Final[str] = "RATE_LIMIT_LOGIN_PER_5_MINUTES"
ENV_RATE_LIMIT_NOTIFICATION_POLL_PER_MINUTE: Final[str] = "RATE_LIMIT_NOTIFICATION_POLL_PER_MINUTE"
ENV_RATE_LIMIT_SEARCH_PER_MINUTE: Final[str] = "RATE_LIMIT_SEARCH_PER_MINUTE"
#: Milestone 9 hardening — the first *enforced* rate limit in this
#: codebase (see ``app.api.rate_limiting``'s module docstring for why the
#: five settings above have never had an enforcement point, and why this
#: one, uniquely, is IP-based rather than keyed on ``profiles.id``).
#: Shared by both public invitation endpoints (``GET
#: /invitations/validate``, ``POST /invitations/accept``) — one budget
#: per caller IP across the pair, not a separate limit per route.
ENV_RATE_LIMIT_INVITATION_PUBLIC_PER_5_MINUTES: Final[str] = (
    "RATE_LIMIT_INVITATION_PUBLIC_PER_5_MINUTES"
)
ENV_RATE_LIMIT_AI_PER_MINUTE: Final[str] = "RATE_LIMIT_AI_PER_MINUTE"

ENV_AI_PROVIDER: Final[str] = "AI_PROVIDER"
ENV_AI_API_KEY: Final[str] = "AI_API_KEY"
ENV_AI_MODEL: Final[str] = "AI_MODEL"
ENV_AI_TIMEOUT_SECONDS: Final[str] = "AI_TIMEOUT_SECONDS"
ENV_AI_MAX_OUTPUT_TOKENS: Final[str] = "AI_MAX_OUTPUT_TOKENS"

ENV_WORKFLOW_DEFAULT_ESCALATION_HOURS: Final[str] = "WORKFLOW_DEFAULT_ESCALATION_HOURS"

ENV_APP_BASE_URL: Final[str] = "APP_BASE_URL"
ENV_INVITATION_EXPIRY_HOURS: Final[str] = "INVITATION_EXPIRY_HOURS"
ENV_INVITATION_ACCEPT_PATH: Final[str] = "INVITATION_ACCEPT_PATH"

#: Production infrastructure layer (Redis + observability). ``REDIS_URL``
#: absent (the default in every environment until now) means every
#: Redis-backed component described in ``app.bootstrap`` falls back to
#: its existing in-process implementation, unchanged — Redis is strictly
#: opt-in, never required for local development, testing, or CI.
ENV_REDIS_URL: Final[str] = "REDIS_URL"
#: Selects how ``NotificationService``'s (and ``InvitationService``'s)
#: email dispatch actually delivers mail: ``"direct"`` (default;
#: synchronous SMTP-via-thread-pool) or ``"queue"`` (enqueues onto
#: ``app.jobs`` for a separate ``app.jobs.worker`` process to deliver —
#: requires ``REDIS_URL``). See ``app.bootstrap``'s ``_build_email_sender``.
ENV_EMAIL_DISPATCH_MODE: Final[str] = "EMAIL_DISPATCH_MODE"
ENV_METRICS_ENABLED: Final[str] = "METRICS_ENABLED"

#: Production-grade job system (``app.jobs``). All optional, with
#: defaults matching a single-worker, five-attempt, ten-minute-stuck-
#: threshold reference deployment — see ``.env.example``.
ENV_JOB_DEFAULT_MAX_ATTEMPTS: Final[str] = "JOB_DEFAULT_MAX_ATTEMPTS"
#: Which ``queue_name``(s) ``app.jobs.worker`` consumes: ``"default"``,
#: ``"escalation"``, or ``"all"`` (both). Overridable per-invocation via
#: the worker's own ``--role`` CLI flag; this env var is the Docker
#: Compose-friendly equivalent for a container that just runs
#: ``python -m app.jobs.worker`` with no arguments.
ENV_WORKER_ROLE: Final[str] = "WORKER_ROLE"
#: The port each worker process's own Prometheus metrics HTTP server
#: listens on (workers have no other HTTP server — see
#: ``app.jobs.worker``'s module docstring for why worker-local metrics
#: can't be scraped through the backend's ``/metrics`` instead).
ENV_WORKER_METRICS_PORT: Final[str] = "WORKER_METRICS_PORT"
#: How long a job may sit in ``status="running"`` with no corresponding
#: Redis entry (its worker crashed or was killed ungracefully) before
#: ``app.scheduler.stuck_job_reaper_job.StuckJobReaperJob`` recovers it.
ENV_STUCK_JOB_THRESHOLD_MINUTES: Final[str] = "STUCK_JOB_THRESHOLD_MINUTES"
ENV_STUCK_JOB_REAPER_INTERVAL_MINUTES: Final[str] = "STUCK_JOB_REAPER_INTERVAL_MINUTES"

# ---------------------------------------------------------------------------
# Default values (matching .env.example; used only when a variable is
# genuinely optional per the Deployment Guide, never as a silent
# substitute for a required secret)
# ---------------------------------------------------------------------------

DEFAULT_LOG_LEVEL: Final[str] = "INFO"

DEFAULT_SCHEDULER_LEADER: Final[bool] = False
DEFAULT_SCHEDULER_ESCALATION_INTERVAL_MINUTES: Final[int] = 60
DEFAULT_SCHEDULER_REMINDER_INTERVAL_HOURS: Final[int] = 24
DEFAULT_SCHEDULER_ANALYTICS_INTERVAL_HOURS: Final[int] = 24
#: Renewed roughly every ttl/3 seconds (`app.scheduler.leader_election.
#: LeaderElection`) — three renewal attempts fit inside one TTL window
#: before a live leader's claim could lapse from ordinary jitter alone.
DEFAULT_SCHEDULER_LEADER_LOCK_TTL_SECONDS: Final[float] = 30.0
#: Comfortably above the discovery-and-enqueue work Escalation
#: Check/Reminder Dispatch actually perform (seconds, in the reference
#: deployment) while still recovering a crashed instance's lock well
#: within a single ordinary escalation/reminder interval.
DEFAULT_SCHEDULER_JOB_LOCK_TTL_SECONDS: Final[float] = 300.0

DEFAULT_RATE_LIMIT_READ_PER_MINUTE: Final[int] = 300
DEFAULT_RATE_LIMIT_WRITE_PER_MINUTE: Final[int] = 60
DEFAULT_RATE_LIMIT_UPLOAD_PER_MINUTE: Final[int] = 20
DEFAULT_RATE_LIMIT_LOGIN_PER_5_MINUTES: Final[int] = 10
DEFAULT_RATE_LIMIT_NOTIFICATION_POLL_PER_MINUTE: Final[int] = 30
#: Generous enough for sustained typeahead (a debounced keystroke every
#: ~300ms while actively typing a query) without falling back to
#: ``read_per_minute``'s much higher, general-purpose budget.
DEFAULT_RATE_LIMIT_SEARCH_PER_MINUTE: Final[int] = 120
#: Generous enough for a legitimate accept-invitation flow (one
#: validate on page load, an occasional retry, one accept submission,
#: perhaps a mistyped-password resubmission) while still bounding a
#: single source's token-guessing/brute-force attempts — a secondary,
#: defense-in-depth layer under the token's own 256-bit entropy, not the
#: sole protection against it.
DEFAULT_RATE_LIMIT_INVITATION_PUBLIC_PER_5_MINUTES: Final[int] = 20
#: Deliberately tighter than every other per-minute budget above — each
#: request may invoke a paid, multi-second external AI provider call rather
#: than a local database query.
DEFAULT_RATE_LIMIT_AI_PER_MINUTE: Final[int] = 20

DEFAULT_WORKFLOW_ESCALATION_HOURS: Final[float] = 48.0

DEFAULT_AI_TIMEOUT_SECONDS: Final[float] = 20.0
DEFAULT_AI_MAX_OUTPUT_TOKENS: Final[int] = 600

#: The frontend origin used to build invitation-acceptance links when
#: ``APP_BASE_URL`` is not set — the local Next.js dev server's default
#: origin, matching every other "optional in Development" default in this
#: module.
DEFAULT_APP_BASE_URL: Final[str] = "http://localhost:3000"
#: Matches ``app.services.invitation_service.DEFAULT_INVITATION_EXPIRY_HOURS``
#: — kept as a separate constant (rather than importing across the
#: config/services boundary) since it serves a different purpose here: the
#: fallback used when ``INVITATION_EXPIRY_HOURS`` is unset, versus that
#: module's fallback used when ``InvitationService`` is constructed
#: directly (e.g. in tests) without an explicit value.
DEFAULT_INVITATION_EXPIRY_HOURS: Final[float] = 72.0
DEFAULT_INVITATION_ACCEPT_PATH: Final[str] = "/accept-invite"

DEFAULT_EMAIL_DISPATCH_MODE: Final[str] = "direct"
DEFAULT_METRICS_ENABLED: Final[bool] = True

DEFAULT_JOB_MAX_ATTEMPTS: Final[int] = 5
DEFAULT_WORKER_ROLE: Final[str] = "all"
DEFAULT_WORKER_METRICS_PORT: Final[int] = 9100
DEFAULT_STUCK_JOB_THRESHOLD_MINUTES: Final[int] = 10
DEFAULT_STUCK_JOB_REAPER_INTERVAL_MINUTES: Final[int] = 5

# ---------------------------------------------------------------------------
# Valid values
# ---------------------------------------------------------------------------

#: The set of log level names ``logging_config.py`` accepts, matching
#: Python's standard library logging level names exactly.
VALID_LOG_LEVELS: Final[frozenset[str]] = frozenset(
    {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
)

#: The set of recognized ``EMAIL_DISPATCH_MODE`` values.
VALID_EMAIL_DISPATCH_MODES: Final[frozenset[str]] = frozenset({"direct", "queue"})

#: The set of recognized ``WORKER_ROLE`` values (``app.jobs.worker``).
VALID_WORKER_ROLES: Final[frozenset[str]] = frozenset({"default", "escalation", "all"})

#: The set of recognized ``AI_PROVIDER`` values (``app.ai.providers``).
VALID_AI_PROVIDERS: Final[frozenset[str]] = frozenset({"openai", "anthropic", "groq"})
