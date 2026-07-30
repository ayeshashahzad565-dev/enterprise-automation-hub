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
from collections.abc import Mapping
from dataclasses import dataclass

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
class AiSettings:
    """AI provider configuration for ``app.ai``/``AiInsightService``.

    Per this feature's design, AI integration is strictly opt-in: with
    ``provider`` unset (the default in every environment until an operator
    configures it), ``app.bootstrap`` constructs no provider and every
    ``AiInsightService`` method returns its deterministic, non-AI fallback
    content — the application behaves byte-for-byte as it did before this
    layer was introduced.

    Attributes:
        provider: ``"openai"``, ``"anthropic"``, or ``None`` if AI features
            are disabled.
        api_key: The provider's API key. Required (and validated as such
            by ``load_settings``) whenever ``provider`` is set.
        model: The model identifier to request. Required whenever
            ``provider`` is set — deliberately has no guessed default,
            since model identifiers go stale and an operator enabling AI
            features is expected to choose one explicitly.
        timeout_seconds: The request timeout applied to every completion
            call.
        max_output_tokens: The default upper bound on generated response
            length, in provider-defined tokens.
    """

    provider: str | None
    api_key: str | None
    model: str | None
    timeout_seconds: float
    max_output_tokens: int

    @property
    def is_enabled(self) -> bool:
        """Whether an AI provider is configured and should be constructed."""
        return self.provider is not None


@dataclass(frozen=True, slots=True)
class SchedulerSettings:
    """APScheduler configuration, per WEDD Section 8 and DG Section 13.

    Attributes:
        is_leader: Whether this instance participates in the Scheduler
            pool at all — registers its jobs, and (when Redis is
            configured) contends for live leadership via
            ``app.scheduler.leader_election.LeaderElection``. ``app.jobs.
            worker`` processes always leave this ``False``, even with
            Redis configured, and must never participate.
            Without Redis configured, exactly one participating instance
            per environment should have this set to ``True`` (DG Section
            13.2) — this dataclass does not, and cannot, enforce that
            uniqueness itself, an operational discipline as before. With
            Redis configured, more than one participating instance is
            expected and safe: Redis-backed election automatically
            ensures only one is ever the live leader at a time, with
            automatic failover (``docs/scheduler_distributed_coordination.md``).
        escalation_interval_minutes: How often the Escalation Check job
            runs.
        reminder_interval_hours: How often the Reminder Dispatch job runs.
        analytics_interval_hours: Read and validated, but currently
            unused — no ``ScheduledJob`` reads this field or registers an
            analytics-aggregation job anywhere in ``app.scheduler``/
            ``app.bootstrap``. Kept as reserved configuration for a
            not-yet-implemented job rather than removed outright; do not
            infer that a "Nightly Analytics Aggregation" job exists from
            this field's presence.
        leader_lock_ttl_seconds: How long the Redis-backed Scheduler
            leader lock is held before expiring if not renewed. Only
            meaningful when Redis is configured — see
            ``app.scheduler.leader_election.LeaderElection`` and
            ``docs/scheduler_distributed_coordination.md``.
        job_lock_ttl_seconds: How long a single job's distributed
            execution lock is held before expiring if not released.
            Only meaningful when Redis is configured — see
            ``app.scheduler.distributed_lock.RedisDistributedLock``.
    """

    is_leader: bool
    escalation_interval_minutes: int
    reminder_interval_hours: int
    analytics_interval_hours: int
    leader_lock_ttl_seconds: float
    job_lock_ttl_seconds: float


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
        search_per_minute: Limit for ``GET /search`` — set higher than
            ``read_per_minute`` since the command palette and the
            dedicated search page both issue one request per debounced
            keystroke, a typeahead-driven request rate an ordinary read
            endpoint never sees.
        ai_per_minute: Limit for every ``/ai/*`` endpoint — set lower than
            ``read_per_minute``, deliberately, since each call may invoke a
            paid, multi-second external AI provider request rather than a
            local database query.
        invitation_public_per_5_minutes: Limit for the two public,
            unauthenticated invitation endpoints (``GET
            /invitations/validate``, ``POST /invitations/accept``),
            shared across both — per caller IP address, not per
            ``profiles.id`` (there is no authenticated identity yet for
            either endpoint). See ``app.api.rate_limiting``'s module
            docstring for why this is the one rate limit in this
            dataclass with an actual enforcement point as of Milestone 9.
    """

    read_per_minute: int
    write_per_minute: int
    upload_per_minute: int
    login_per_5_minutes: int
    notification_poll_per_minute: int
    search_per_minute: int
    ai_per_minute: int
    invitation_public_per_5_minutes: int


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
class RedisSettings:
    """Redis connection configuration for the production infrastructure layer.

    Every Redis-backed component (``app.utils.redis_rate_limiter``,
    ``app.utils.redis_cache``, ``app.jobs``) is strictly opt-in: absent
    ``REDIS_URL`` (``url is None``, the default in every environment
    until now) means ``app.bootstrap`` falls back to the existing
    in-process implementations, byte-for-byte unchanged from before this
    layer was introduced.

    Attributes:
        url: The Redis connection URL (e.g. ``redis://redis:6379/0``), or
            ``None`` if Redis is not configured for this environment.
    """

    url: str | None

    @property
    def enabled(self) -> bool:
        """Whether a Redis backend is configured for this process."""
        return self.url is not None


@dataclass(frozen=True, slots=True)
class ObservabilitySettings:
    """Observability configuration: Prometheus metrics exposure.

    Attributes:
        metrics_enabled: Whether ``GET /metrics`` is mounted. Defaults to
            ``True``; an operator may disable it if metrics scraping is
            handled some other way (e.g. a sidecar) or not wanted at all.
    """

    metrics_enabled: bool


@dataclass(frozen=True, slots=True)
class JobSettings:
    """Configuration for the production-grade job system (``app.jobs``).

    Attributes:
        default_max_attempts: The attempt budget a job is enqueued with
            when its producer does not pass an explicit override (e.g.
            ``EscalationJob``/``ReminderJob`` pass a smaller budget of
            their own).
        worker_role: Which ``queue_name``(s) this process's
            ``app.jobs.worker`` instance consumes, when not overridden by
            the worker's own ``--role`` CLI flag.
        worker_metrics_port: The port this process's own Prometheus
            metrics HTTP server listens on, if it runs as a worker.
        stuck_job_threshold_minutes: How long a job may sit
            ``status="running"`` before ``StuckJobReaperJob`` treats it
            as orphaned (its worker crashed) and recovers it.
        stuck_job_reaper_interval_minutes: How often
            ``StuckJobReaperJob`` runs.
    """

    default_max_attempts: int
    worker_role: str
    worker_metrics_port: int
    stuck_job_threshold_minutes: int
    stuck_job_reaper_interval_minutes: int


@dataclass(frozen=True, slots=True)
class InvitationSettings:
    """Configuration for the Enterprise User Onboarding invitation flow.

    Attributes:
        expiry_hours: The lifetime, in hours, assigned to a newly created
            or resent invitation. Passed explicitly into
            ``InvitationService``'s constructor by
            ``app.bootstrap.build_application_resources`` (the service
            itself defaults to the same value when constructed without
            it, e.g. in tests).
        app_base_url: The application's public frontend origin (no
            trailing slash), used to build the invitation-acceptance link
            embedded in invitation emails.
        accept_path: The frontend route path an invitation email's
            acceptance link points to, appended to ``app_base_url``.
    """

    expiry_hours: float
    app_base_url: str
    accept_path: str


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
        logging: Logging configuration.
        rate_limits: Rate limiting configuration.
        workflow: Workflow-related configuration defaults.
        invitation: Enterprise User Onboarding invitation configuration.
        redis: Redis connection configuration (production infrastructure
            layer) — see ``RedisSettings``.
        observability: Prometheus metrics exposure configuration.
        email_dispatch_mode: ``"direct"`` (default) or ``"queue"`` — see
            ``app.config.constants.ENV_EMAIL_DISPATCH_MODE``.
        jobs: Production-grade job system configuration (``app.jobs``).
        ai: AI provider configuration (``app.ai``/``AiInsightService``).
    """

    environment: Environment
    supabase: SupabaseConnectionSettings
    database_url: str
    smtp: SmtpSettings
    scheduler: SchedulerSettings
    logging: LoggingSettings
    rate_limits: RateLimitSettings
    workflow: WorkflowSettings
    invitation: InvitationSettings
    redis: RedisSettings
    observability: ObservabilitySettings
    email_dispatch_mode: str
    jobs: JobSettings
    ai: AiSettings


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
        raise InvalidConfigurationValueError(name, f"expected a number, got {raw_value!r}") from exc


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

    if environment.requires_production_grade_hardening and not all(
        (host, port_raw, username, password, from_address)
    ):
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


def _load_ai_settings(env: Mapping[str, str]) -> AiSettings:
    """Load AI provider configuration.

    Args:
        env: The environment mapping to read from.

    Returns:
        The loaded ``AiSettings``.

    Raises:
        InvalidConfigurationValueError: If ``AI_PROVIDER`` is set to a
            value other than ``"openai"``/``"anthropic"``.
        MissingEnvironmentVariableError: If ``AI_PROVIDER`` is set but
            ``AI_API_KEY`` or ``AI_MODEL`` is absent — a provider is never
            constructed from partial configuration (matching
            ``_load_smtp_settings``'s "incomplete config is a hard
            failure, not something to degrade from" discipline).
    """
    provider = _read_optional(env, constants.ENV_AI_PROVIDER)
    if provider is not None:
        provider = provider.lower()
        if provider not in constants.VALID_AI_PROVIDERS:
            raise InvalidConfigurationValueError(
                constants.ENV_AI_PROVIDER,
                f"expected one of {sorted(constants.VALID_AI_PROVIDERS)}, got {provider!r}",
            )

    api_key: str | None = None
    model: str | None = None
    if provider is not None:
        api_key = _read_required(env, constants.ENV_AI_API_KEY)
        model = _read_required(env, constants.ENV_AI_MODEL)

    return AiSettings(
        provider=provider,
        api_key=api_key,
        model=model,
        timeout_seconds=_read_float(
            env, constants.ENV_AI_TIMEOUT_SECONDS, constants.DEFAULT_AI_TIMEOUT_SECONDS
        ),
        max_output_tokens=_read_int(
            env, constants.ENV_AI_MAX_OUTPUT_TOKENS, constants.DEFAULT_AI_MAX_OUTPUT_TOKENS
        ),
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
        leader_lock_ttl_seconds=_read_float(
            source,
            constants.ENV_SCHEDULER_LEADER_LOCK_TTL_SECONDS,
            constants.DEFAULT_SCHEDULER_LEADER_LOCK_TTL_SECONDS,
        ),
        job_lock_ttl_seconds=_read_float(
            source,
            constants.ENV_SCHEDULER_JOB_LOCK_TTL_SECONDS,
            constants.DEFAULT_SCHEDULER_JOB_LOCK_TTL_SECONDS,
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
        search_per_minute=_read_int(
            source,
            constants.ENV_RATE_LIMIT_SEARCH_PER_MINUTE,
            constants.DEFAULT_RATE_LIMIT_SEARCH_PER_MINUTE,
        ),
        ai_per_minute=_read_int(
            source,
            constants.ENV_RATE_LIMIT_AI_PER_MINUTE,
            constants.DEFAULT_RATE_LIMIT_AI_PER_MINUTE,
        ),
        invitation_public_per_5_minutes=_read_int(
            source,
            constants.ENV_RATE_LIMIT_INVITATION_PUBLIC_PER_5_MINUTES,
            constants.DEFAULT_RATE_LIMIT_INVITATION_PUBLIC_PER_5_MINUTES,
        ),
    )
    if rate_limits.invitation_public_per_5_minutes < 0:
        raise InvalidConfigurationValueError(
            constants.ENV_RATE_LIMIT_INVITATION_PUBLIC_PER_5_MINUTES,
            f"must be zero or a positive integer, got {rate_limits.invitation_public_per_5_minutes}"
            " (0 blocks every request to the public invitation endpoints).",
        )

    workflow = WorkflowSettings(
        default_escalation_hours=_read_float(
            source,
            constants.ENV_WORKFLOW_DEFAULT_ESCALATION_HOURS,
            constants.DEFAULT_WORKFLOW_ESCALATION_HOURS,
        )
    )

    app_base_url_raw = _read_optional(source, constants.ENV_APP_BASE_URL)
    # Unlike every other optional-with-a-default field in this function, an
    # unset APP_BASE_URL in Staging/Production fails *silently*: SMTP is
    # already required there (see _load_smtp_settings above), so the
    # invitation email sends successfully — its acceptance link just
    # silently points every invited user at localhost:3000, breaking
    # onboarding with no startup error to point at the missing variable.
    # Matches _cors_allowed_origins' identical required-in-Staging/
    # Production discipline (app/api/main.py).
    if environment.requires_production_grade_hardening and not app_base_url_raw:
        raise MissingEnvironmentVariableError(constants.ENV_APP_BASE_URL)
    app_base_url = (app_base_url_raw or constants.DEFAULT_APP_BASE_URL).rstrip("/")
    invitation_expiry_hours = _read_float(
        source,
        constants.ENV_INVITATION_EXPIRY_HOURS,
        constants.DEFAULT_INVITATION_EXPIRY_HOURS,
    )
    # Per Milestone 9's Configuration audit: a non-positive expiry is not
    # a value InvitationService can degrade from gracefully — every
    # invitation created under it would be born already-expired (zero or
    # negative), silently breaking the entire onboarding flow with no
    # error until an admin noticed nobody could accept an invite. Fails
    # at startup instead, matching this function's existing "invalid
    # configuration fails early" discipline for every other field it
    # loads.
    if invitation_expiry_hours <= 0:
        raise InvalidConfigurationValueError(
            constants.ENV_INVITATION_EXPIRY_HOURS,
            f"must be a positive number of hours, got {invitation_expiry_hours}.",
        )
    invitation = InvitationSettings(
        expiry_hours=invitation_expiry_hours,
        app_base_url=app_base_url,
        accept_path=(
            _read_optional(
                source,
                constants.ENV_INVITATION_ACCEPT_PATH,
                constants.DEFAULT_INVITATION_ACCEPT_PATH,
            )
            or constants.DEFAULT_INVITATION_ACCEPT_PATH
        ),
    )

    redis = RedisSettings(url=_read_optional(source, constants.ENV_REDIS_URL))

    ai = _load_ai_settings(source)

    observability = ObservabilitySettings(
        metrics_enabled=_read_bool(
            source, constants.ENV_METRICS_ENABLED, constants.DEFAULT_METRICS_ENABLED
        )
    )

    email_dispatch_mode = (
        _read_optional(
            source, constants.ENV_EMAIL_DISPATCH_MODE, constants.DEFAULT_EMAIL_DISPATCH_MODE
        )
        or constants.DEFAULT_EMAIL_DISPATCH_MODE
    ).lower()
    if email_dispatch_mode not in constants.VALID_EMAIL_DISPATCH_MODES:
        raise InvalidConfigurationValueError(
            constants.ENV_EMAIL_DISPATCH_MODE,
            f"expected one of {sorted(constants.VALID_EMAIL_DISPATCH_MODES)}, "
            f"got {email_dispatch_mode!r}",
        )
    if email_dispatch_mode == "queue" and not redis.enabled:
        raise InvalidConfigurationValueError(
            constants.ENV_EMAIL_DISPATCH_MODE,
            "\"queue\" requires REDIS_URL to be configured.",
        )

    worker_role = (
        _read_optional(source, constants.ENV_WORKER_ROLE, constants.DEFAULT_WORKER_ROLE)
        or constants.DEFAULT_WORKER_ROLE
    ).lower()
    if worker_role not in constants.VALID_WORKER_ROLES:
        raise InvalidConfigurationValueError(
            constants.ENV_WORKER_ROLE,
            f"expected one of {sorted(constants.VALID_WORKER_ROLES)}, got {worker_role!r}",
        )
    jobs = JobSettings(
        default_max_attempts=_read_int(
            source, constants.ENV_JOB_DEFAULT_MAX_ATTEMPTS, constants.DEFAULT_JOB_MAX_ATTEMPTS
        ),
        worker_role=worker_role,
        worker_metrics_port=_read_int(
            source, constants.ENV_WORKER_METRICS_PORT, constants.DEFAULT_WORKER_METRICS_PORT
        ),
        stuck_job_threshold_minutes=_read_int(
            source,
            constants.ENV_STUCK_JOB_THRESHOLD_MINUTES,
            constants.DEFAULT_STUCK_JOB_THRESHOLD_MINUTES,
        ),
        stuck_job_reaper_interval_minutes=_read_int(
            source,
            constants.ENV_STUCK_JOB_REAPER_INTERVAL_MINUTES,
            constants.DEFAULT_STUCK_JOB_REAPER_INTERVAL_MINUTES,
        ),
    )

    return AppSettings(
        environment=environment,
        supabase=supabase,
        database_url=database_url,
        smtp=smtp,
        scheduler=scheduler,
        logging=logging_settings,
        rate_limits=rate_limits,
        workflow=workflow,
        invitation=invitation,
        redis=redis,
        observability=observability,
        email_dispatch_mode=email_dispatch_mode,
        jobs=jobs,
        ai=ai,
    )
