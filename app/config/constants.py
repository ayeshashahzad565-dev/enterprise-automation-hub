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

ENV_STREAMLIT_SERVER_ADDRESS: Final[str] = "STREAMLIT_SERVER_ADDRESS"
ENV_STREAMLIT_SERVER_PORT: Final[str] = "STREAMLIT_SERVER_PORT"

ENV_LOG_LEVEL: Final[str] = "LOG_LEVEL"

ENV_RATE_LIMIT_READ_PER_MINUTE: Final[str] = "RATE_LIMIT_READ_PER_MINUTE"
ENV_RATE_LIMIT_WRITE_PER_MINUTE: Final[str] = "RATE_LIMIT_WRITE_PER_MINUTE"
ENV_RATE_LIMIT_UPLOAD_PER_MINUTE: Final[str] = "RATE_LIMIT_UPLOAD_PER_MINUTE"
ENV_RATE_LIMIT_LOGIN_PER_5_MINUTES: Final[str] = "RATE_LIMIT_LOGIN_PER_5_MINUTES"
ENV_RATE_LIMIT_NOTIFICATION_POLL_PER_MINUTE: Final[str] = "RATE_LIMIT_NOTIFICATION_POLL_PER_MINUTE"

ENV_WORKFLOW_DEFAULT_ESCALATION_HOURS: Final[str] = "WORKFLOW_DEFAULT_ESCALATION_HOURS"

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

DEFAULT_STREAMLIT_SERVER_ADDRESS: Final[str] = "0.0.0.0"  # noqa: S104 - bind-all is the documented default
DEFAULT_STREAMLIT_SERVER_PORT: Final[int] = 8501

DEFAULT_RATE_LIMIT_READ_PER_MINUTE: Final[int] = 300
DEFAULT_RATE_LIMIT_WRITE_PER_MINUTE: Final[int] = 60
DEFAULT_RATE_LIMIT_UPLOAD_PER_MINUTE: Final[int] = 20
DEFAULT_RATE_LIMIT_LOGIN_PER_5_MINUTES: Final[int] = 10
DEFAULT_RATE_LIMIT_NOTIFICATION_POLL_PER_MINUTE: Final[int] = 30

DEFAULT_WORKFLOW_ESCALATION_HOURS: Final[float] = 48.0

# ---------------------------------------------------------------------------
# Valid values
# ---------------------------------------------------------------------------

#: The set of log level names ``logging_config.py`` accepts, matching
#: Python's standard library logging level names exactly.
VALID_LOG_LEVELS: Final[frozenset[str]] = frozenset(
    {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
)