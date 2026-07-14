"""Centralized application settings, loaded from environment variables.

Per the ADD's description of the Configuration Loader — "a small, focused
module responsible for loading environment variables... into typed
Pydantic settings objects at startup. All other components read
configuration exclusively through this loader; no component reads
`os.environ` directly" — this module is that Configuration Loader.

``AppSettings`` and its nested settings groups are implemented as frozen
``dataclasses`` rather than Pydantic models. This is a deliberate,
narrow exception to the project's general preference for Pydantic v2
(used throughout ``app.models`` for domain data): configuration values are
not domain entities validated against business rules, they are typed,
environment-sourced parameters read exactly once at process startup, and
a plain frozen dataclass expresses that intent directly without pulling
the Domain Layer's validation machinery into a concern that is really
about environment-variable parsing. Every value is still fully type-hinted
and validated during loading (see ``load_settings`` below); no less
rigor is applied than a Pydantic model would provide.

This module is the only place in ``app.config`` that reads ``os.environ``
(via ``load_settings``'s ``env`` parameter, which defaults to it) — every
other module in this package is a pure, environment-independent utility.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping
from pathlib import Path
from dotenv import load_dotenv

from app.config import constants
from app.config.environment import Environment, detect_environment
from app.config.exceptions import (
    InvalidConfigurationValueError,
    MissingEnvironmentVariableError,
)
from app.database.client import SupabaseConnectionSettings

# Load environment variables from a .env file if it exists
load_dotenv()

@dataclass(frozen=True, slots=True)
class SmtpSettings:
    """Email dispatch configuration for the Notification Service.

    Per the ADD's Notification Service description, every notification is
    dispatched as an email as part of the baseline; per DG Section 8.1,
    Development and Testing environments may disable this, in which case
    every field here is ``None`` and calling code is expected to skip
    email dispatch entirely rather than attempt it with empty credentials.

    Attributes:
        host: The SMTP server hostname.
        port: The SMTP server port.
        username: The SMTP authentication username.
        password: The SMTP authentication password.
        from_address: The address notifications are sent from.
    """

    host: str | None
    port: int | None
    username: str | None
    password: str | None
    from_address: str | None

    @property
    def is_enabled(self) -> bool:
        """Whether email dispatch is configured and should be attempted."""
        return self.host is not None


@dataclass(frozen=True, slots=True)
class SchedulerSettings:
    """APScheduler configuration, per WEDD Section 8 and DG Section 13.

    Attributes:
        is_leader: Whether this instance registers Scheduler jobs.
            Exactly one running instance per environment should have this
            set to ``True`` (DG Section 13.2); this dataclass does not,
            and cannot, enforce that uniqueness across instances itself —
            that is an operational deployment discipline, not something a
            single process's own configuration can verify.
        escalation_interval_minutes: How often the Escalation Check job
            runs.
        reminder_interval_hours: How often the Reminder Dispatch job runs.
        analytics_interval_hours: How often the Nightly Analytics
            Aggregation job runs.
    """

    is_leader: bool
    escalation_interval_minutes: int
    reminder_interval_hours: int
    analytics_interval_hours: int


@dataclass(frozen=True, slots=True)
class StreamlitSettings:
    """Streamlit server bind configuration, per DG Section 6.

    Attributes:
        server_address: The address the Streamlit server binds to.
        server_port: The port the Streamlit server binds to.
    """

    server_address: str
    server_port: int


@dataclass(frozen=True, slots=True)
class LoggingSettings:
    """Logging configuration, per DG Section 14.

    Attributes:
        level: The minimum log level to emit, as a standard logging level
            name.
    """

    level: str


@dataclass(frozen=True, slots=True)
class RateLimitSettings:
    """Per-endpoint-category rate limits, per API-ADD Section 15.

    Attributes:
        read_per_minute: Limit for ``GET`` endpoints.
        write_per_minute: Limit for ``POST``/``PATCH``/``DELETE``
            endpoints, general case.
        upload_per_minute: Limit for the attachment upload endpoint.
        login_per_5_minutes: Limit for the login endpoint, per email
            address.
        notification_poll_per_minute: Limit for the unread-count polling
            endpoint.
    """

    read_per_minute: int
    write_per_minute: int
    upload_per_minute: int
    login_per_5_minutes: int
    notification_poll_per_minute: int


@dataclass(frozen=True, slots=True)
class WorkflowSettings:
    """Workflow-related configuration defaults, per DSD Section 5.

    Attributes:
        default_escalation_hours: The default escalation duration used
            where a workflow stage definition does not specify its own
            ``escalation_hours`` (WEDD Section 3.7). Individual stage
            configurations may always override this value; it is a
            fallback, not a ceiling or floor.
    """

    default_escalation_hours: float


@dataclass(frozen=True, slots=True)
class AppSettings:
    """The complete, validated application configuration.

    A single instance of this class is constructed once at process
    startup (via ``load_settings``) and passed by dependency injection to
    every component that needs configuration — no component downstream of
    this module reads an environment variable itself.

    Attributes:
        environment: The detected running environment.
        supabase: Connection settings for the Supabase project, ready to
            be passed directly to
            ``app.database.client.SupabaseClientFactory``.
        database_url: The direct PostgreSQL connection string used only
            by Alembic at migration time (DG Section 11); never used by
            application request-handling code, which exclusively uses
            ``supabase`` above.
        smtp: Email dispatch configuration.
        scheduler: APScheduler configuration.
        streamlit: Streamlit server configuration.
        logging: Logging configuration.
        rate_limits: Rate limiting configuration.
        workflow: Workflow-related configuration defaults.
    """

    environment: Environment
    supabase: SupabaseConnectionSettings
    database_url: str
    smtp: SmtpSettings
    scheduler: SchedulerSettings
    streamlit: StreamlitSettings
    logging: LoggingSettings
    rate_limits: RateLimitSettings
    workflow: WorkflowSettings


def _read_required(env: Mapping[str, str], name: str) -> str:
    """Read a required environment variable, raising if absent or empty.

    Args:
        env: The environment mapping to read from.
        name: The variable name.

    Returns:
        The variable's value, stripped of surrounding whitespace.

    Raises:
        MissingEnvironmentVariableError: If the variable is absent or
            empty after stripping.
    """
    value = env.get(name)
    if value is None or not value.strip():
        raise MissingEnvironmentVariableError(name)
    return value.strip()


def _read_optional(env: Mapping[str, str], name: str, default: str | None = None) -> str | None:
    """Read an optional environment variable.

    Args:
        env: The environment mapping to read from.
        name: The variable name.
        default: The value to return if the variable is absent or empty.

    Returns:
        The variable's stripped value, or ``default``.
    """
    value = env.get(name)
    if value is None or not value.strip():
        return default
    return value.strip()


def _read_int(env: Mapping[str, str], name: str, default: int) -> int:
    """Read an optional integer-valued environment variable.

    Args:
        env: The environment mapping to read from.
        name: The variable name.
        default: The value to return if the variable is absent or empty.

    Returns:
        The parsed integer, or ``default``.

    Raises:
        InvalidConfigurationValueError: If the variable is present but
            cannot be parsed as an integer.
    """
    raw_value = _read_optional(env, name)
    if raw_value is None:
        return default
    try:
        return int(raw_value)
    except ValueError as exc:
        raise InvalidConfigurationValueError(
            name, f"expected an integer, got {raw_value!r}"
        ) from exc


def _read_float(env: Mapping[str, str], name: str, default: float) -> float:
    """Read an optional float-valued environment variable.

    Args:
        env: The environment mapping to read from.
        name: The variable name.
        default: The value to return if the variable is absent or empty.

    Returns:
        The parsed float, or ``default``.

    Raises:
        InvalidConfigurationValueError: If the variable is present but
            cannot be parsed as a float.
    """
    raw_value = _read_optional(env, name)
    if raw_value is None:
        return default
    try:
        return float(raw_value)
    except ValueError as exc:
        raise InvalidConfigurationValueError(
            name, f"expected a number, got {raw_value!r}"
        ) from exc


def _read_bool(env: Mapping[str, str], name: str, default: bool) -> bool:
    """Read an optional boolean-valued environment variable.

    Accepts ``"true"``/``"false"`` case-insensitively, as well as
    ``"1"``/``"0"``, matching common ``.env`` file conventions.

    Args:
        env: The environment mapping to read from.
        name: The variable name.
        default: The value to return if the variable is absent or empty.

    Returns:
        The parsed boolean, or ``default``.

    Raises:
        InvalidConfigurationValueError: If the variable is present but
            does not match a recognized boolean representation.
    """
    raw_value = _read_optional(env, name)
    if raw_value is None:
        return default
    normalized = raw_value.strip().lower()
    if normalized in ("true", "1", "yes"):
        return True
    if normalized in ("false", "0", "no"):
        return False
    raise InvalidConfigurationValueError(
        name, f"expected a boolean (true/false), got {raw_value!r}"
    )


def _load_smtp_settings(env: Mapping[str, str], environment: Environment) -> SmtpSettings:
    """Load SMTP configuration, enforcing DG Section 8.1's environment rule.

    Args:
        env: The environment mapping to read from.
        environment: The detected running environment, used to determine
            whether SMTP configuration is required (Staging, Production)
            or optional (Development, Testing).

    Returns:
        The loaded ``SmtpSettings``.

    Raises:
        MissingEnvironmentVariableError: If ``environment`` requires
            production-grade hardening (Staging or Production) and any
            SMTP variable is missing.
    """
    host = _read_optional(env, constants.ENV_SMTP_HOST)
    port_raw = _read_optional(env, constants.ENV_SMTP_PORT)
    username = _read_optional(env, constants.ENV_SMTP_USERNAME)
    password = _read_optional(env, constants.ENV_SMTP_PASSWORD)
    from_address = _read_optional(env, constants.ENV_SMTP_FROM_ADDRESS)

    if environment.requires_production_grade_hardening:
        if not all((host, port_raw, username, password, from_address)):
            raise MissingEnvironmentVariableError(
                f"{constants.ENV_SMTP_HOST}/{constants.ENV_SMTP_PORT}/"
                f"{constants.ENV_SMTP_USERNAME}/{constants.ENV_SMTP_PASSWORD}/"
                f"{constants.ENV_SMTP_FROM_ADDRESS}"
            )

    port: int | None = None
    if port_raw is not None:
        try:
            port = int(port_raw)
        except ValueError as exc:
            raise InvalidConfigurationValueError(
                constants.ENV_SMTP_PORT, f"expected an integer, got {port_raw!r}"
            ) from exc

    return SmtpSettings(
        host=host,
        port=port,
        username=username,
        password=password,
        from_address=from_address,
    )


def load_settings(env: Mapping[str, str] | None = None) -> AppSettings:
    """Load, parse, and validate the complete application configuration.

    This is the single entry point every other part of the codebase is
    expected to call, exactly once, at process startup — per the ADD, no
    component downstream of this function reads ``os.environ`` on its
    own.

    Args:
        env: The environment variable mapping to read from. Defaults to
            ``os.environ`` when ``None`` is passed. Tests supply a plain
            ``dict`` instead, which is what makes this function
            straightforward to exercise in isolation (TSD Section 3.4)
            without mutating real process environment variables or
            requiring a live Supabase project merely to construct
            settings.

    Returns:
        A fully populated, validated ``AppSettings`` instance.

    Raises:
        MissingEnvironmentVariableError: If a required variable is absent
            or empty, including SMTP variables when the detected
            environment requires them (Staging, Production).
        InvalidConfigurationValueError: If a variable is present but
            cannot be parsed into its expected type.
        EnvironmentDetectionError: If ``APP_ENVIRONMENT`` is set to an
            unrecognized value.
    """
    source: Mapping[str, str] = env if env is not None else os.environ

    environment = detect_environment(source)

    supabase = SupabaseConnectionSettings(
        url=_read_required(source, constants.ENV_SUPABASE_URL),
        anon_key=_read_required(source, constants.ENV_SUPABASE_ANON_KEY),
        service_role_key=_read_required(source, constants.ENV_SUPABASE_SERVICE_ROLE_KEY),
    )

    database_url = _read_required(source, constants.ENV_DATABASE_URL)

    smtp = _load_smtp_settings(source, environment)

    scheduler = SchedulerSettings(
        is_leader=_read_bool(
            source, constants.ENV_SCHEDULER_LEADER, constants.DEFAULT_SCHEDULER_LEADER
        ),
        escalation_interval_minutes=_read_int(
            source,
            constants.ENV_SCHEDULER_ESCALATION_INTERVAL_MINUTES,
            constants.DEFAULT_SCHEDULER_ESCALATION_INTERVAL_MINUTES,
        ),
        reminder_interval_hours=_read_int(
            source,
            constants.ENV_SCHEDULER_REMINDER_INTERVAL_HOURS,
            constants.DEFAULT_SCHEDULER_REMINDER_INTERVAL_HOURS,
        ),
        analytics_interval_hours=_read_int(
            source,
            constants.ENV_SCHEDULER_ANALYTICS_INTERVAL_HOURS,
            constants.DEFAULT_SCHEDULER_ANALYTICS_INTERVAL_HOURS,
        ),
    )

    streamlit = StreamlitSettings(
        server_address=_read_optional(
            source,
            constants.ENV_STREAMLIT_SERVER_ADDRESS,
            constants.DEFAULT_STREAMLIT_SERVER_ADDRESS,
        )
        or constants.DEFAULT_STREAMLIT_SERVER_ADDRESS,
        server_port=_read_int(
            source,
            constants.ENV_STREAMLIT_SERVER_PORT,
            constants.DEFAULT_STREAMLIT_SERVER_PORT,
        ),
    )

    logging_settings = LoggingSettings(
        level=(
            _read_optional(source, constants.ENV_LOG_LEVEL, constants.DEFAULT_LOG_LEVEL)
            or constants.DEFAULT_LOG_LEVEL
        ).upper()
    )
    if logging_settings.level not in constants.VALID_LOG_LEVELS:
        raise InvalidConfigurationValueError(
            constants.ENV_LOG_LEVEL,
            f"expected one of {sorted(constants.VALID_LOG_LEVELS)}, "
            f"got {logging_settings.level!r}",
        )

    rate_limits = RateLimitSettings(
        read_per_minute=_read_int(
            source,
            constants.ENV_RATE_LIMIT_READ_PER_MINUTE,
            constants.DEFAULT_RATE_LIMIT_READ_PER_MINUTE,
        ),
        write_per_minute=_read_int(
            source,
            constants.ENV_RATE_LIMIT_WRITE_PER_MINUTE,
            constants.DEFAULT_RATE_LIMIT_WRITE_PER_MINUTE,
        ),
        upload_per_minute=_read_int(
            source,
            constants.ENV_RATE_LIMIT_UPLOAD_PER_MINUTE,
            constants.DEFAULT_RATE_LIMIT_UPLOAD_PER_MINUTE,
        ),
        login_per_5_minutes=_read_int(
            source,
            constants.ENV_RATE_LIMIT_LOGIN_PER_5_MINUTES,
            constants.DEFAULT_RATE_LIMIT_LOGIN_PER_5_MINUTES,
        ),
        notification_poll_per_minute=_read_int(
            source,
            constants.ENV_RATE_LIMIT_NOTIFICATION_POLL_PER_MINUTE,
            constants.DEFAULT_RATE_LIMIT_NOTIFICATION_POLL_PER_MINUTE,
        ),
    )

    workflow = WorkflowSettings(
        default_escalation_hours=_read_float(
            source,
            constants.ENV_WORKFLOW_DEFAULT_ESCALATION_HOURS,
            constants.DEFAULT_WORKFLOW_ESCALATION_HOURS,
        )
    )

    return AppSettings(
        environment=environment,
        supabase=supabase,
        database_url=database_url,
        smtp=smtp,
        scheduler=scheduler,
        streamlit=streamlit,
        logging=logging_settings,
        rate_limits=rate_limits,
        workflow=workflow,
    )