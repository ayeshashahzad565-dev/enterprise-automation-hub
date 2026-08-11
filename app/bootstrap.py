"""Framework-agnostic dependency wiring for the FastAPI application.

This module is the single place every repository, Application Service,
and engine in this codebase is constructed. It originated as the shared
composition root for both the (now removed) Streamlit UI and the FastAPI
API, so that both wired the exact same object graph from the exact same
code rather than each maintaining its own copy — now that Streamlit is
gone, ``app.api.main`` is its only consumer, building it once in a
``lifespan`` handler and storing it on ``app.state``.

This module does dependency wiring only. It contains no business logic
of its own (every non-trivial decision is an integration decision, not a
domain one) and no framework-specific code.

No server-side session store is constructed here: JWT validation over
HTTP is stateless (API-ADD Section 5.5/5.6), so authentication is served
entirely by ``app.auth.supabase_verifier.SupabaseTokenVerifier`` (a
stateless, dependency-only component) verifying an already-issued bearer
token on every request.
"""

from __future__ import annotations

import atexit
import dataclasses
import logging
import os
import socket
from functools import partial
from typing import TYPE_CHECKING

from app.ai.exceptions import AiConfigurationError
from app.ai.interfaces import AiProvider
from app.ai.providers.anthropic_provider import AnthropicProvider
from app.ai.providers.openai_provider import OpenAiProvider
from app.analytics.analytics_engine import AnalyticsEngine
from app.analytics.interfaces import (
    AnalyticsProvider,
    OperationalAnalyticsProvider,
    ReportingProvider,
)
from app.analytics.operational_engine import OperationalAnalyticsEngine
from app.analytics.reporting import ReportingEngine
from app.auth.supabase_verifier import SupabaseTokenVerifier
from app.config.error_tracking import init_error_tracking
from app.config.logging_config import configure_logging
from app.config.settings import AiSettings, AppSettings, load_settings
from app.database.attachment_storage import AttachmentStorageGateway
from app.database.client import DatabaseClient, SupabaseClientFactory, SupabaseConnectionSettings
from app.database.repositories.analytics_repository import AnalyticsRepository
from app.database.repositories.approval_repository import ApprovalRepository
from app.database.repositories.attachment_repository import AttachmentRepository
from app.database.repositories.audit_repository import AuditRepository
from app.database.repositories.comment_repository import CommentRepository
from app.database.repositories.company_license_repository import CompanyLicenseRepository
from app.database.repositories.company_repository import CompanyRepository
from app.database.repositories.feature_flag_repository import FeatureFlagRepository
from app.database.repositories.invitation_repository import InvitationRepository
from app.database.repositories.job_repository import JobRepository
from app.database.repositories.notification_preference_repository import (
    NotificationPreferenceRepository,
)
from app.database.repositories.notification_repository import NotificationRepository
from app.database.repositories.platform_stats_repository import PlatformStatsRepository
from app.database.repositories.request_repository import RequestRepository
from app.database.repositories.saved_filter_repository import SavedFilterRepository
from app.database.repositories.search_history_repository import SearchHistoryRepository
from app.database.repositories.user_repository import ProfileRepository
from app.database.repositories.workflow_repository import (
    WorkflowDefinitionRepository,
    WorkflowStageRepository,
)
from app.jobs.email_sender import RedisQueueEmailSender
from app.jobs.handlers import handle_escalate_stage, handle_send_reminder
from app.jobs.job_service import JobDispatcher, JobService, SynchronousJobDispatcher
from app.jobs.redis_queue import RedisJobQueue
from app.jobs.task_types import TASK_ESCALATE_STAGE, TASK_SEND_REMINDER
from app.notifications.email_sender import SmtpEmailProvider
from app.notifications.exceptions import EmailDeliveryError, NotificationConfigurationError
from app.scheduler.distributed_lock import RedisDistributedLock
from app.scheduler.escalation_job import EscalationJob
from app.scheduler.health_check_job import HealthCheckJob
from app.scheduler.leader_election import LeaderElection
from app.scheduler.registry import JobRegistry
from app.scheduler.reminder_job import ReminderJob
from app.scheduler.scheduler import APSchedulerBackend, SchedulerCoordinator
from app.scheduler.stuck_job_reaper_job import StuckJobReaperJob
from app.services.ai_insight_service import AiInsightService
from app.services.analytics_service import AnalyticsService as ServicesAnalyticsService
from app.services.approval_service import ApprovalService
from app.services.attachment_service import AttachmentService, NullVirusScanner
from app.services.comment_service import CommentService
from app.services.company_service import CompanyService
from app.services.dashboard_service import DashboardService
from app.services.feature_flag_service import FeatureFlagService
from app.services.invitation_email import QueuedInvitationEmailSender, SmtpInvitationEmailSender
from app.services.invitation_service import InvitationEmailSender, InvitationService
from app.services.notification_service import NotificationService, ThreadPoolEmailDispatchExecutor
from app.services.request_service import RequestService
from app.services.search_service import GlobalSearchService
from app.services.supabase_admin_client import SupabaseAuthAdminClientImpl
from app.services.user_service import UserService
from app.services.workflow_definition_service import WorkflowDefinitionService
from app.utils.id_generator import generate_uuid_str
from app.utils.rate_limiter import InMemoryRateLimiter, RateLimiter
from app.utils.redis_cache import RedisCache
from app.utils.redis_client import create_redis_client
from app.utils.redis_rate_limiter import RedisRateLimiter
from app.workflow.engine import WorkflowEngine

if TYPE_CHECKING:
    import redis

__all__ = [
    "ApplicationResources",
    "build_application_resources",
    "shutdown_notification_email_dispatch",
    "shutdown_scheduler",
]

logger = logging.getLogger(__name__)


class _EmailSenderAdapter:
    """Bridges ``app.notifications.email_sender.SmtpEmailProvider`` to the
    narrower ``app.services.notification_service.EmailSender`` protocol.

    Lets ``app.services.notification_service.NotificationService`` (the
    stack actually wired into ``RequestService``/``ApprovalService``)
    reuse the same SMTP mechanism ``app.notifications`` already
    implements, rather than requiring a second, separate SMTP
    implementation.
    """

    def __init__(self, provider: SmtpEmailProvider) -> None:
        """Initialize the adapter.

        Args:
            provider: The underlying SMTP provider to delegate to.
        """
        self._provider = provider

    def send(self, *, to_address: str, subject: str, body: str) -> bool:
        """Send an email, satisfying the services-layer ``EmailSender`` protocol.

        Args:
            to_address: The recipient's email address.
            subject: The email subject line.
            body: The plain-text email body.

        Returns:
            ``True`` if delivery succeeded, ``False`` otherwise.
        """
        try:
            self._provider.send_email(to_address=to_address, subject=subject, text_body=body)
        except EmailDeliveryError:
            return False
        return True


def _build_email_sender(
    settings: AppSettings,
    *,
    job_service: JobService | None,
) -> tuple[_EmailSenderAdapter | RedisQueueEmailSender | None, SmtpEmailProvider | None]:
    """Construct the notification email sender and, where applicable, its SMTP provider.

    Args:
        settings: The loaded application settings.
        job_service: The process-wide ``JobService``, or ``None`` if
            Redis is not configured. Only consulted when
            ``settings.email_dispatch_mode == "queue"`` — and, per
            ``AppSettings.load_settings``'s own validation, that mode is
            never selected without Redis also being configured, so
            ``job_service`` is guaranteed non-``None`` whenever this
            branch is taken.

    Returns:
        A tuple of ``(sender, provider)``. ``sender`` satisfies
        ``app.services.notification_service.EmailSender`` and is ``None``
        if SMTP is disabled for this environment (per DG Section 8.1,
        permitted in Development/Testing). ``provider`` is the
        constructed ``SmtpEmailProvider`` (``None`` if SMTP is disabled),
        reused as-is by ``InvitationService``'s own email sender when
        ``email_dispatch_mode == "direct"``.
    """
    if not settings.smtp.is_enabled:
        logger.info("SMTP is disabled for this environment; email dispatch will be skipped.")
        return None, None
    try:
        provider = SmtpEmailProvider(settings=settings.smtp)
    except NotificationConfigurationError as exc:
        logger.error("Failed to construct SMTP provider despite is_enabled=True: %s", exc)
        return None, None

    if settings.email_dispatch_mode == "queue" and job_service is not None:
        logger.info("Notification email dispatch mode: queue (job-system-backed).")
        return RedisQueueEmailSender(job_service=job_service), provider

    return _EmailSenderAdapter(provider), provider


_GROQ_BASE_URL = "https://api.groq.com/openai/v1"


def _build_ai_provider(settings: AiSettings) -> AiProvider | None:
    """Construct the configured AI provider, or ``None`` if AI features are disabled.

    Mirrors ``_build_email_sender``'s exact shape: absent or invalid
    configuration degrades to ``None`` (logged, not raised) rather than
    crashing process startup — a bad ``AI_MODEL`` value should not take the
    whole application down, since ``AiInsightService`` already has a
    documented, graceful non-AI fallback for every one of its methods when
    ``ai_provider is None``.

    Args:
        settings: The loaded AI provider settings.

    Returns:
        The constructed provider, or ``None`` if ``settings.is_enabled`` is
        ``False`` or construction failed.
    """
    if not settings.is_enabled:
        logger.info("AI_PROVIDER not set; AI features will use non-AI fallbacks.")
        return None

    assert settings.provider is not None  # noqa: S101 - guaranteed by is_enabled
    assert settings.api_key is not None  # noqa: S101 - guaranteed by load_settings validation
    assert settings.model is not None  # noqa: S101 - guaranteed by load_settings validation

    try:
        if settings.provider == "openai":
            return OpenAiProvider(
                api_key=settings.api_key, model=settings.model, timeout_seconds=settings.timeout_seconds
            )
        if settings.provider == "anthropic":
            return AnthropicProvider(
                api_key=settings.api_key, model=settings.model, timeout_seconds=settings.timeout_seconds
            )
        if settings.provider == "groq":
            # Groq's API is wire-compatible with OpenAI's Chat Completions
            # format (same request/response shape, same Bearer auth), so
            # OpenAiProvider is reused as-is, just pointed at Groq's base
            # URL — no separate provider implementation needed.
            return OpenAiProvider(
                api_key=settings.api_key,
                model=settings.model,
                timeout_seconds=settings.timeout_seconds,
                base_url=_GROQ_BASE_URL,
                provider_name="groq",
            )
    except AiConfigurationError as exc:
        logger.error("Failed to construct AI provider despite is_enabled=True: %s", exc)
        return None

    logger.error("Unrecognized AI_PROVIDER=%r; AI features will use non-AI fallbacks.", settings.provider)
    return None


@dataclasses.dataclass(frozen=True, slots=True)
class ApplicationResources:
    """The process-wide, framework-agnostic dependency graph every
    Presentation Layer builds itself from.

    Every field is safe to share across concurrent callers (Streamlit
    sessions, or concurrent HTTP requests): identity is always passed
    per-call into an Application Service method, never held as
    connection state.

    Attributes:
        request_service: Orchestrates request creation, editing,
            withdrawal, and reads.
        approval_service: Orchestrates stage approval, rejection, and
            the pending-approvals queue.
        workflow_definition_service: Orchestrates workflow definition
            lifecycle operations.
        notification_service: Orchestrates notification reads and
            read-status updates.
        comment_service: Orchestrates comment creation, thread reads,
            and administrative moderation.
        attachment_service: Orchestrates attachment upload, replace,
            removal, and read access.
        search_service: Orchestrates fuzzy, filterable, cross-entity
            global search.
        dashboard_service: Aggregates the services above into a single
            dashboard DTO.
        analytics_provider: The read-only analytics engine
            (``app.analytics``).
        reporting_provider: The read-only reporting engine
            (``app.analytics``).
        operational_analytics_provider: The read-only operational
            analytics engine (``app.analytics``) — SLA, approval-delay,
            bottleneck, workload, trend, executive-KPI, and department
            intelligence, built on top of ``analytics_provider``.
        audit_repo: Direct repository access for the narrow,
            documented exception where an API route reads
            organization-wide audit history with no matching Application
            Service method (the Phase 4 "Recent Activity" feed) — see
            ``app.api.routers.analytics``'s module docstring.
        approval_repo: Direct repository access for the same narrow
            exception, backing the Phase 4 "Aging Requests" /
            bottleneck view via ``list_overdue_stages`` — no
            Application Service method surfaces that query either.
        profile_repo: Direct repository access for the narrow,
            established "resolve a profile for an already-authenticated
            identity" need (mirrored from ``app.py``'s
            ``SupabaseAuthGateway._build_auth_result``) — no
            ``ProfileService`` exists anywhere in this codebase.
        database_client: Direct access to the underlying Supabase client,
            for the one need no repository serves: ``GET /health``'s
            Supabase-reachability check (``docs/deployment.md`` Section
            15.2), via its ``health_check()`` method.
        token_verifier: Verifies an incoming bearer token against
            Supabase and resolves its ``profiles.role``, for a stateless
            HTTP entry point's per-request authentication.
        settings: The application's non-secret configuration.
        scheduler_stats: Exposes execution statistics for the in-process
            Scheduler, if this instance registered Scheduler jobs at all
            (with Redis-backed election active, that is every instance,
            regardless of current leadership — see ``leader_election``
            for whether this instance is *currently* leading); ``None``
            if no jobs were registered on this instance.
        leader_election: The running ``app.scheduler.leader_election.
            LeaderElection`` this instance uses to contend for Scheduler
            leadership, or ``None`` if Redis is not configured (in which
            case leadership is the static, single-instance
            ``SCHEDULER_LEADER`` designation instead — see
            ``docs/scheduler_distributed_coordination.md``).
        invitation_service: Orchestrates Enterprise User Onboarding
            invitation creation, listing, resend, revocation, validation,
            and acceptance (Milestones 1-4). Constructed and exposed here
            like every other Application Service; no API router or
            frontend consumes it yet — a later milestone's concern.
        company_service: Orchestrates platform-admin-only company
            creation, listing, and updates — the multi-tenancy
            conversion's bootstrap surface.
        user_service: Orchestrates admin-only profile mutations:
            role/department assignment, deactivation/reactivation, and
            GDPR right-to-erasure (``0020_profile_lifecycle``).
        invitation_rate_limiter: The single, process-wide
            ``InMemoryRateLimiter`` instance backing
            ``app.api.rate_limiting.enforce_invitation_rate_limit``
            (Milestone 9) — constructed once here, like every other
            stateful component in this bundle, so that a fresh instance
            (with independent, non-leaking counter state) is built for
            every process, and for every test that constructs its own
            ``ApplicationResources`` via ``create_app(resources_factory=...)``.
        email_dispatch_executor: The background thread pool backing
            ``notification_service``'s email dispatch, or ``None`` when
            SMTP is disabled for this environment. Retained here purely
            so the Presentation Layer's shutdown hook can drain it via
            ``shutdown_notification_email_dispatch``.
        read_rate_limiter: Per-authenticated-user rate limit for
            ``GET``/``HEAD``/``OPTIONS`` routes (``app.api.rate_limiting.
            enforce_rate_limit``).
        write_rate_limiter: Per-authenticated-user rate limit for
            ``POST``/``PUT``/``PATCH``/``DELETE`` routes, including
            approval decisions and administrative mutations (same
            dependency as ``read_rate_limiter``, method-aware).
        upload_rate_limiter: The tighter, attachment-upload-specific rate
            limit (``app.api.rate_limiting.enforce_upload_rate_limit``),
            enforced in addition to ``write_rate_limiter``.
        notification_poll_rate_limiter: The tighter, unread-count-poll-
            specific rate limit (``app.api.rate_limiting.
            enforce_notification_poll_rate_limit``), enforced in addition
            to ``read_rate_limiter``.
        search_rate_limiter: The tighter, typeahead-specific rate limit
            (``app.api.rate_limiting.enforce_search_rate_limit``) for
            ``GET /search``, enforced in addition to ``read_rate_limiter``
            — the command palette and the dedicated search page both
            issue a request per debounced keystroke, a materially higher
            request rate than an ordinary read endpoint.
        redis_client: The process-wide Redis client, or ``None`` if
            ``REDIS_URL`` is not configured for this environment. Used
            directly by ``GET /health/ready`` (``app.api.routers.health``)
            for its optional Redis-reachability check; every other
            Redis-backed component above is already fully constructed by
            the time this bundle exists.
        job_repository: Direct repository access to the ``jobs`` table's
            durable job-status/history record — the persistence layer
            ``app.api.routers.admin_jobs`` reads and writes against, and
            (when Redis is configured) what ``app.jobs.worker`` and
            ``StuckJobReaperJob`` transition. Always constructed
            (requires only Postgres, not Redis) so the admin API can
            always at least report "no jobs" rather than needing its own
            optional-dependency branch.
        job_service: The process-wide ``JobService`` (Postgres+Redis
            backed), or ``None`` if Redis is not configured — mirrors
            every other optional-Redis field's "``None`` means fall back"
            convention. Used by ``app.api.routers.admin_jobs`` to retry a
            dead-lettered job.
        redis_job_queue: The process-wide ``RedisJobQueue``, or ``None``
            if Redis is not configured — used by
            ``app.api.routers.admin_jobs``'s queue-depth/stats endpoint.
        company_repo: Direct repository access for ``GET /platform/stats``
            (active/total tenant counts) — the one other narrow,
            documented "no Application Service, pure composition" read
            exception, mirroring ``audit_repo``'s/``approval_repo``'s own.
        platform_stats_repo: Direct repository access to the cross-tenant
            aggregates (user count, request count/trend, workflow
            definition count, storage bytes) backing
            ``GET /platform/stats`` — deliberately has no Application
            Service, since there is no business rule beyond the
            platform-admin gate the router itself applies.
        feature_flag_service: Orchestrates platform-admin-only feature
            flag creation, listing, and updates.
        ai_insight_service: Orchestrates every AI-generated insight
            (summaries, recommendations, the dashboard assistant),
            gracefully falling back to deterministic non-AI content when
            ``AI_PROVIDER`` is unset or the provider call fails.
        ai_rate_limiter: The tighter, AI-specific rate limit
            (``app.api.rate_limiting.enforce_ai_rate_limit``) for every
            ``/ai/*`` route, enforced in addition to ``read_rate_limiter``/
            ``write_rate_limiter`` — each call may invoke a paid,
            multi-second external AI provider request.
        supabase_connection_settings: The raw Supabase connection settings
            (url/anon key), exposed so
            ``app.api.dependencies.bind_tenant_database_client`` can build
            a fresh, per-request, caller-scoped client
            (``SupabaseClientFactory.create_user_scoped_client``) for the
            repositories verified safe to run under real Row-Level
            Security (see ``BaseRepository.always_use_injected_client``).
    """

    request_service: RequestService
    approval_service: ApprovalService
    workflow_definition_service: WorkflowDefinitionService
    notification_service: NotificationService
    comment_service: CommentService
    attachment_service: AttachmentService
    search_service: GlobalSearchService
    ai_insight_service: AiInsightService
    dashboard_service: DashboardService
    analytics_provider: AnalyticsProvider
    reporting_provider: ReportingProvider
    operational_analytics_provider: OperationalAnalyticsProvider
    audit_repo: AuditRepository
    approval_repo: ApprovalRepository
    profile_repo: ProfileRepository
    database_client: DatabaseClient
    token_verifier: SupabaseTokenVerifier
    settings: AppSettings
    scheduler_stats: SchedulerCoordinator | None
    leader_election: LeaderElection | None
    invitation_service: InvitationService
    invitation_rate_limiter: RateLimiter
    company_service: CompanyService
    user_service: UserService
    email_dispatch_executor: ThreadPoolEmailDispatchExecutor | None
    read_rate_limiter: RateLimiter
    write_rate_limiter: RateLimiter
    upload_rate_limiter: RateLimiter
    notification_poll_rate_limiter: RateLimiter
    search_rate_limiter: RateLimiter
    ai_rate_limiter: RateLimiter
    redis_client: redis.Redis | None
    job_repository: JobRepository
    job_service: JobService | None
    redis_job_queue: RedisJobQueue | None
    company_repo: CompanyRepository
    platform_stats_repo: PlatformStatsRepository
    feature_flag_service: FeatureFlagService
    supabase_connection_settings: SupabaseConnectionSettings


def build_application_resources(settings: AppSettings | None = None) -> ApplicationResources:
    """Construct every process-wide singleton this application needs.

    Contains no framework-specific caching of its own — each Presentation
    Layer's entry point is responsible for calling this exactly once per
    process (Streamlit via ``st.cache_resource``, FastAPI via a
    ``lifespan`` handler) and reusing the result.

    Args:
        settings: The application's configuration. If not provided,
            loaded fresh via ``load_settings()`` — the same default every
            existing caller of this wiring already relied on.

    Returns:
        The constructed ``ApplicationResources`` bundle.
    """
    if settings is None:
        settings = load_settings()
    configure_logging(settings.logging.level)
    init_error_tracking(environment=settings.environment.value)
    logger.info("Loaded configuration for environment: %s", settings.environment.value)

    # --- Database client and repositories -----------------------------
    # Every repository behind the Application Service Layer is backed by
    # the service-role client: every app.services method already performs
    # a mandatory authorization check against the caller's
    # AuthenticatedIdentity before any repository call, and neither
    # Presentation Layer holds a client-side Supabase caller of its own —
    # every database call already originates from trusted, server-side
    # code that has already passed through that check.
    service_role_client = SupabaseClientFactory.create_service_role_client(settings.supabase)

    # Tenant-isolation architecture (see docs/tenant_isolation.md): each
    # repository below explicitly declares whether it always runs on the
    # constructor-injected client (`always_use_injected_client=True` —
    # service-role today, hardened instead via `BaseRepository._scoped_query`
    # and app-layer authorization checks) or additionally honors the
    # per-request, RLS-enforcing client bound by
    # `app.api.dependencies.bind_tenant_database_client`
    # (`always_use_injected_client=False`). `False` is used only where this
    # was verified against both the actual RLS policy *and* how the service
    # layer actually reads/writes that table — see the plan's classification
    # table for the evidence behind each choice; it is not a default.
    profile_repo = ProfileRepository(service_role_client, always_use_injected_client=True)
    request_repo = RequestRepository(service_role_client, always_use_injected_client=True)
    workflow_definition_repo = WorkflowDefinitionRepository(
        service_role_client, always_use_injected_client=False
    )
    workflow_stage_repo = WorkflowStageRepository(
        service_role_client, always_use_injected_client=True
    )
    approval_repo = ApprovalRepository(service_role_client, always_use_injected_client=True)
    notification_repo = NotificationRepository(service_role_client, always_use_injected_client=True)
    notification_preference_repo = NotificationPreferenceRepository(
        service_role_client, always_use_injected_client=False
    )
    audit_repo = AuditRepository(service_role_client, always_use_injected_client=True)
    analytics_repo = AnalyticsRepository(service_role_client, always_use_injected_client=True)
    comment_repo = CommentRepository(service_role_client, always_use_injected_client=False)
    attachment_repo = AttachmentRepository(service_role_client, always_use_injected_client=False)
    attachment_storage = AttachmentStorageGateway(service_role_client)
    invitation_repo = InvitationRepository(service_role_client, always_use_injected_client=True)
    company_repo = CompanyRepository(service_role_client, always_use_injected_client=True)
    company_license_repo = CompanyLicenseRepository(
        service_role_client, always_use_injected_client=True
    )
    feature_flag_repo = FeatureFlagRepository(service_role_client, always_use_injected_client=True)
    platform_stats_repo = PlatformStatsRepository(
        service_role_client, always_use_injected_client=True
    )
    saved_filter_repo = SavedFilterRepository(service_role_client, always_use_injected_client=False)
    search_history_repo = SearchHistoryRepository(
        service_role_client, always_use_injected_client=False
    )
    # Always constructed — needs only Postgres, not Redis — so the admin
    # API can always at least report "no jobs" (see ApplicationResources.job_repository).
    job_repository = JobRepository(service_role_client, always_use_injected_client=True)

    # --- Workflow Engine ------------------------------------------------
    workflow_engine = WorkflowEngine()

    # --- Redis (production infrastructure layer; strictly optional) -----
    # A single client shared by every Redis-backed component below (rate
    # limiters, the analytics response cache, the job system's live
    # dispatch layer) — mirrors service_role_client's "one client, many
    # consumers" construction above. `None` when REDIS_URL is unset,
    # which every consumer below treats as "fall back to the existing
    # in-process implementation," never as an error.
    redis_client: redis.Redis | None = (
        create_redis_client(settings.redis.url) if settings.redis.url is not None else None
    )
    redis_job_queue: RedisJobQueue | None = None
    job_service: JobService | None = None
    # Redis-backed Scheduler leader election (docs/scheduler_distributed_
    # coordination.md): constructed and started only for an instance that
    # has opted into the Scheduler pool at all (`SCHEDULER_LEADER=true` —
    # see this settings field's docstring for its updated, pool-membership
    # meaning). `app.jobs.worker` processes leave this `false` and must
    # never construct a `LeaderElection` or contend for this lock, even
    # with Redis configured — only `SCHEDULER_LEADER=true` instances
    # (ordinarily every `backend` API replica) do. Among those, whichever
    # instance actually holds the lock is the live leader, with automatic,
    # self-healing failover replacing the purely static single-instance
    # designation this mechanism used before Redis was configured.
    leader_election: LeaderElection | None = None
    if redis_client is not None:
        logger.info("Redis configured; rate limiting, analytics caching will be Redis-backed.")
        redis_job_queue = RedisJobQueue(client=redis_client)
        job_service = JobService(
            job_repository=job_repository,
            redis_queue=redis_job_queue,
            default_max_attempts=settings.jobs.default_max_attempts,
        )
        if settings.scheduler.is_leader:
            instance_id = f"{socket.gethostname()}:{os.getpid()}:{generate_uuid_str()[:8]}"
            leader_election = LeaderElection(
                lock=RedisDistributedLock(
                    client=redis_client,
                    key="eah:scheduler:leader",
                    ttl_seconds=settings.scheduler.leader_lock_ttl_seconds,
                    token=instance_id,
                ),
                renewal_interval_seconds=settings.scheduler.leader_lock_ttl_seconds / 3,
                instance_id=instance_id,
            )
            leader_election.start()
            logger.info(
                "Redis-backed Scheduler leader election started (instance_id=%s).", instance_id
            )
    else:
        logger.info("REDIS_URL not set; using in-process rate limiting and caching.")

    # --- AI Provider (app.ai stack) --------------------------------------
    ai_provider = _build_ai_provider(settings.ai)

    # --- Notification Layer (app.services stack; the one actually
    # wired into RequestService/ApprovalService/the Scheduler) ----------
    email_adapter, smtp_provider = _build_email_sender(settings, job_service=job_service)
    # A real SMTP send retries with exponential backoff on failure
    # (SmtpEmailProvider), which can take several seconds — dispatching
    # it on a background thread pool keeps that latency off the request
    # thread handling the approval/rejection/etc. that triggered it. No
    # executor is needed (and none is constructed) when SMTP is disabled,
    # since there is nothing to send in the background.
    email_dispatch_executor = (
        ThreadPoolEmailDispatchExecutor() if email_adapter is not None else None
    )
    notification_service = NotificationService(
        notification_repo=notification_repo,
        preference_repo=notification_preference_repo,
        email_sender=email_adapter,
        email_executor=email_dispatch_executor,
    )

    # --- Enterprise User Onboarding: invitations (Milestone 4) ----------
    # No API router or frontend consumes invitation_service yet (a later
    # milestone's concern) — constructed and exposed here regardless.
    # Dispatch is skipped entirely, exactly like notification_service
    # above, when SMTP is disabled for this environment. When
    # email_dispatch_mode == "queue" (and therefore
    # Redis is configured — settings.py's own validation guarantees this),
    # invitation email now goes through the job system too, closing a gap
    # that predated this class: invitations previously always dispatched
    # synchronously regardless of EMAIL_DISPATCH_MODE.
    invitation_email_sender: InvitationEmailSender | None = None
    if smtp_provider is not None:
        if settings.email_dispatch_mode == "queue" and job_service is not None:
            invitation_email_sender = QueuedInvitationEmailSender(job_service=job_service)
        else:
            invitation_email_sender = SmtpInvitationEmailSender(
                email_provider=smtp_provider, settings=settings.invitation
            )
    # Shared across every consumer needing the Supabase Auth Admin API
    # (InvitationService's user-creation call, UserService's GDPR-erasure
    # email scrub) — mirrors service_role_client's own "one client, many
    # consumers" construction.
    auth_admin_client = SupabaseAuthAdminClientImpl(service_role_client)
    invitation_service = InvitationService(
        invitation_repo=invitation_repo,
        profile_repo=profile_repo,
        audit_repo=audit_repo,
        auth_admin_client=auth_admin_client,
        email_sender=invitation_email_sender,
        invitation_expiry_hours=settings.invitation.expiry_hours,
    )
    # Milestone 9: the two public invitation endpoints' shared,
    # per-caller-IP rate-limit budget — see app.api.rate_limiting's
    # module docstring. 5 minutes matches this codebase's existing
    # "per 5 minutes" convention for auth-adjacent limits (login).
    #
    # Every limiter below is Redis-backed (shared, multi-instance-safe —
    # app.utils.redis_rate_limiter's whole reason for existing) when
    # Redis is configured, else the original in-process
    # InMemoryRateLimiter — byte-for-byte the same construction as
    # before this production infrastructure layer existed.
    def _rate_limiter(*, namespace: str, limit: int, window_seconds: float) -> RateLimiter:
        if redis_client is not None:
            return RedisRateLimiter(
                client=redis_client, namespace=namespace, limit=limit, window_seconds=window_seconds
            )
        return InMemoryRateLimiter(limit=limit, window_seconds=window_seconds)

    invitation_rate_limiter = _rate_limiter(
        namespace="invitation",
        limit=settings.rate_limits.invitation_public_per_5_minutes,
        window_seconds=300.0,
    )
    # Per-authenticated-user rate limits (app.api.rate_limiting), applied
    # across every authenticated route — see that module's docstring for
    # which dependency uses which limiter below.
    read_rate_limiter = _rate_limiter(
        namespace="read", limit=settings.rate_limits.read_per_minute, window_seconds=60.0
    )
    write_rate_limiter = _rate_limiter(
        namespace="write", limit=settings.rate_limits.write_per_minute, window_seconds=60.0
    )
    upload_rate_limiter = _rate_limiter(
        namespace="upload", limit=settings.rate_limits.upload_per_minute, window_seconds=60.0
    )
    notification_poll_rate_limiter = _rate_limiter(
        namespace="notification_poll",
        limit=settings.rate_limits.notification_poll_per_minute,
        window_seconds=60.0,
    )
    search_rate_limiter = _rate_limiter(
        namespace="search", limit=settings.rate_limits.search_per_minute, window_seconds=60.0
    )
    ai_rate_limiter = _rate_limiter(
        namespace="ai", limit=settings.rate_limits.ai_per_minute, window_seconds=60.0
    )

    # --- Application Services -------------------------------------------
    request_service = RequestService(
        request_repo=request_repo,
        workflow_definition_repo=workflow_definition_repo,
        workflow_stage_repo=workflow_stage_repo,
        profile_repo=profile_repo,
        audit_repo=audit_repo,
        notification_service=notification_service,
        workflow_engine=workflow_engine,
        approval_repo=approval_repo,
    )
    approval_service = ApprovalService(
        approval_repo=approval_repo,
        workflow_stage_repo=workflow_stage_repo,
        request_repo=request_repo,
        workflow_definition_repo=workflow_definition_repo,
        profile_repo=profile_repo,
        audit_repo=audit_repo,
        notification_service=notification_service,
        workflow_engine=workflow_engine,
    )
    workflow_definition_service = WorkflowDefinitionService(
        workflow_definition_repo=workflow_definition_repo,
        profile_repo=profile_repo,
        audit_repo=audit_repo,
        workflow_engine=workflow_engine,
    )
    comment_service = CommentService(
        comment_repo=comment_repo,
        request_repo=request_repo,
        workflow_stage_repo=workflow_stage_repo,
        audit_repo=audit_repo,
    )
    attachment_service = AttachmentService(
        attachment_repo=attachment_repo,
        storage_gateway=attachment_storage,
        request_repo=request_repo,
        workflow_stage_repo=workflow_stage_repo,
        audit_repo=audit_repo,
        # No virus scanner is integrated in this baseline (API-ADD
        # Section 23) — NullVirusScanner is the honest, always-SKIPPED
        # implementation; see app.services.attachment_service's own
        # docstring for how a real scanner would be substituted here.
        virus_scanner=NullVirusScanner(),
    )
    search_service = GlobalSearchService(
        request_service=request_service,
        approval_service=approval_service,
        workflow_definition_service=workflow_definition_service,
        request_repo=request_repo,
        comment_repo=comment_repo,
        audit_repo=audit_repo,
        profile_repo=profile_repo,
        notification_repo=notification_repo,
        attachment_repo=attachment_repo,
        saved_filter_repo=saved_filter_repo,
        search_history_repo=search_history_repo,
    )
    company_service = CompanyService(
        company_repo=company_repo,
        license_repo=company_license_repo,
        profile_repo=profile_repo,
        audit_repo=audit_repo,
    )
    user_service = UserService(
        profile_repo=profile_repo, audit_repo=audit_repo, auth_admin_client=auth_admin_client
    )
    feature_flag_service = FeatureFlagService(feature_flag_repo=feature_flag_repo, audit_repo=audit_repo)
    services_analytics_service = ServicesAnalyticsService(analytics_repo=analytics_repo)
    dashboard_service = DashboardService(
        request_service=request_service,
        approval_service=approval_service,
        notification_service=notification_service,
        analytics_service=services_analytics_service,
    )

    # --- Analytics Layer (app.analytics stack, backing the /analytics API) --
    # A short, disclosed staleness window absorbs several dashboard
    # widgets/concurrent users polling the same company/filter
    # combination in quick succession, without materially delaying how
    # soon a genuinely new figure becomes visible. Backed by a shared
    # app.utils.redis_cache.RedisCache when Redis is configured (so a
    # multi-instance deployment shares one cache instead of each
    # instance holding its own, independently-stale copy), else each
    # engine's original private app.utils.cache.TTLCache.
    _ANALYTICS_CACHE_TTL_SECONDS = 15.0
    analytics_engine = AnalyticsEngine(
        analytics_repo=analytics_repo,
        request_repo=request_repo,
        approval_repo=approval_repo,
        workflow_stage_repo=workflow_stage_repo,
        profile_repo=profile_repo,
        audit_repo=audit_repo,
        notification_repo=notification_repo,
        cache_ttl_seconds=_ANALYTICS_CACHE_TTL_SECONDS,
        response_cache=(
            RedisCache(
                client=redis_client,
                namespace="analytics_engine",
                ttl_seconds=_ANALYTICS_CACHE_TTL_SECONDS,
            )
            if redis_client is not None
            else None
        ),
    )
    reporting_engine = ReportingEngine(analytics_provider=analytics_engine)
    operational_analytics_engine = OperationalAnalyticsEngine(
        analytics_provider=analytics_engine,
        analytics_repo=analytics_repo,
        request_repo=request_repo,
        workflow_stage_repo=workflow_stage_repo,
        approval_repo=approval_repo,
        workflow_definition_repo=workflow_definition_repo,
        audit_repo=audit_repo,
        workflow_engine=workflow_engine,
        cache_ttl_seconds=_ANALYTICS_CACHE_TTL_SECONDS,
        response_cache=(
            RedisCache(
                client=redis_client,
                namespace="operational_analytics_engine",
                ttl_seconds=_ANALYTICS_CACHE_TTL_SECONDS,
            )
            if redis_client is not None
            else None
        ),
    )

    # AiInsightService's own two cache TTLs (entity summaries vs.
    # company-wide operational insights) differ from _ANALYTICS_CACHE_TTL_SECONDS
    # above and from each other — see that service's module docstring —
    # so each gets its own RedisCache namespace/ttl_seconds when Redis is
    # configured, else the service builds its own private TTLCache per the
    # identical "response_cache or TTLCache(...)" fallback convention.
    ai_insight_service = AiInsightService(
        request_service=request_service,
        comment_service=comment_service,
        workflow_definition_service=workflow_definition_service,
        operational_engine=operational_analytics_engine,
        reporting_engine=reporting_engine,
        dashboard_service=dashboard_service,
        ai_provider=ai_provider,
        entity_cache=(
            RedisCache(client=redis_client, namespace="ai_insight_entity", ttl_seconds=300.0)
            if redis_client is not None
            else None
        ),
        operational_cache=(
            RedisCache(client=redis_client, namespace="ai_insight_operational", ttl_seconds=900.0)
            if redis_client is not None
            else None
        ),
        max_output_tokens=settings.ai.max_output_tokens,
    )

    # --- Authentication (stateless HTTP entry points only; see module
    # docstring for why SupabaseAuthGateway is not constructed here) -----
    # response_cache here is the single biggest lever on per-request
    # latency in this system: without it, every authenticated request pays
    # a real Supabase Auth call plus two Postgres lookups (see
    # SupabaseTokenVerifier's module docstring) before any business query
    # even runs. Same RedisCache-when-configured/TTLCache-fallback
    # convention as the Analytics Layer above, shared across instances via
    # Redis when configured.
    token_verifier = SupabaseTokenVerifier(
        supabase_settings=settings.supabase,
        profile_repo=profile_repo,
        company_repo=company_repo,
        response_cache=(
            RedisCache(client=redis_client, namespace="auth_claims", ttl_seconds=15.0)
            if redis_client is not None
            else None
        ),
    )

    # --- Scheduler ----------------------------------------------------
    # SCHEDULER_LEADER=true means "this instance participates in the
    # Scheduler pool" (registers its jobs at all) — unchanged as the sole
    # gate on registration, which is what keeps `app.jobs.worker`
    # processes (SCHEDULER_LEADER=false, even with Redis configured)
    # correctly excluded. What Redis configuration changes is what
    # happens *among* participating instances: with Redis, `leader_check`
    # below makes only the one instance `leader_election` actually elects
    # execute any given tick, with automatic failover
    # (docs/scheduler_distributed_coordination.md); without it, this
    # falls back to the original assumption that exactly one participating
    # instance exists (Section 13.2 of docs/deployment.md).
    scheduler_stats: SchedulerCoordinator | None = None
    if settings.scheduler.is_leader:
        # EscalationJob/ReminderJob dispatch through a JobDispatcher
        # rather than calling ApprovalService.escalate_stage /
        # NotificationService.notify_reminder directly. When Redis is
        # configured, that's the real, async, retry/backoff/dead-letter-
        # capable JobService; when it is not, it's SynchronousJobDispatcher
        # — executes the same handler immediately, in this thread, with
        # no Redis or Postgres jobs-table involvement — preserving this
        # codebase's "REDIS_URL absent means byte-for-byte the same
        # behavior as before this layer was introduced" rule for these
        # two jobs, exactly as it already holds for the rate limiters and
        # analytics cache. See app.jobs.job_service's module docstring.
        job_dispatcher: JobDispatcher = job_service or SynchronousJobDispatcher(
            handlers={
                TASK_ESCALATE_STAGE: partial(
                    handle_escalate_stage, approval_service=approval_service
                ),
                TASK_SEND_REMINDER: partial(
                    handle_send_reminder, notification_service=notification_service
                ),
            }
        )
        # Bound as `lambda: leader_election.is_leader` (rather than passing
        # the property's current value) so SchedulerCoordinator re-reads
        # live leadership status on every tick, not just once at startup.
        leader_check = (
            (lambda: leader_election.is_leader) if leader_election is not None else None
        )
        distributed_lock_factory = (
            (
                lambda job_name: RedisDistributedLock(
                    client=redis_client,
                    key=f"eah:scheduler:job-lock:{job_name}",
                    ttl_seconds=settings.scheduler.job_lock_ttl_seconds,
                )
            )
            if redis_client is not None
            else None
        )
        coordinator = SchedulerCoordinator(
            backend=APSchedulerBackend(),
            registry=JobRegistry(),
            leader_check=leader_check,
            distributed_lock_factory=distributed_lock_factory,
        )
        escalation_job = EscalationJob(
            job_dispatcher=job_dispatcher,
            approval_repo=approval_repo,
            request_repo=request_repo,
            workflow_definition_repo=workflow_definition_repo,
            workflow_engine=workflow_engine,
            interval_seconds=settings.scheduler.escalation_interval_minutes * 60,
        )
        reminder_job = ReminderJob(
            job_dispatcher=job_dispatcher,
            approval_repo=approval_repo,
            request_repo=request_repo,
            workflow_definition_repo=workflow_definition_repo,
            notification_repo=notification_repo,
            workflow_engine=workflow_engine,
            interval_seconds=settings.scheduler.reminder_interval_hours * 3600,
        )
        health_check_job = HealthCheckJob(statistics_provider=coordinator)

        coordinator.register_job(escalation_job)
        coordinator.register_job(reminder_job)
        coordinator.register_job(health_check_job)
        # Only meaningful when a real, async job system is active — with
        # no Redis, SynchronousJobDispatcher never leaves a row in the
        # jobs table for this job to ever find (see its own docstring).
        if job_service is not None and redis_job_queue is not None:
            stuck_job_reaper_job = StuckJobReaperJob(
                job_repository=job_repository,
                redis_queue=redis_job_queue,
                threshold_minutes=settings.jobs.stuck_job_threshold_minutes,
                interval_seconds=settings.jobs.stuck_job_reaper_interval_minutes * 60,
            )
            coordinator.register_job(stuck_job_reaper_job)
        coordinator.start()
        atexit.register(lambda: shutdown_scheduler(coordinator, leader_election))

        scheduler_stats = coordinator
        if leader_election is not None:
            logger.info(
                "Scheduler registered on this instance; participating in Redis-backed "
                "leader election (currently_leader=%s).",
                leader_election.is_leader,
            )
        else:
            logger.info("Scheduler started on this instance (SCHEDULER_LEADER=true, static).")
    else:
        logger.info("This instance is not the Scheduler leader; no jobs were registered.")

    resources = ApplicationResources(
        request_service=request_service,
        approval_service=approval_service,
        workflow_definition_service=workflow_definition_service,
        notification_service=notification_service,
        comment_service=comment_service,
        attachment_service=attachment_service,
        search_service=search_service,
        ai_insight_service=ai_insight_service,
        dashboard_service=dashboard_service,
        analytics_provider=analytics_engine,
        reporting_provider=reporting_engine,
        operational_analytics_provider=operational_analytics_engine,
        audit_repo=audit_repo,
        approval_repo=approval_repo,
        profile_repo=profile_repo,
        database_client=service_role_client,
        token_verifier=token_verifier,
        settings=settings,
        scheduler_stats=scheduler_stats,
        leader_election=leader_election,
        invitation_service=invitation_service,
        invitation_rate_limiter=invitation_rate_limiter,
        company_service=company_service,
        user_service=user_service,
        email_dispatch_executor=email_dispatch_executor,
        read_rate_limiter=read_rate_limiter,
        write_rate_limiter=write_rate_limiter,
        upload_rate_limiter=upload_rate_limiter,
        notification_poll_rate_limiter=notification_poll_rate_limiter,
        search_rate_limiter=search_rate_limiter,
        ai_rate_limiter=ai_rate_limiter,
        redis_client=redis_client,
        job_repository=job_repository,
        job_service=job_service,
        redis_job_queue=redis_job_queue,
        company_repo=company_repo,
        platform_stats_repo=platform_stats_repo,
        feature_flag_service=feature_flag_service,
        supabase_connection_settings=settings.supabase,
    )

    if email_dispatch_executor is not None:
        atexit.register(lambda: shutdown_notification_email_dispatch(email_dispatch_executor))

    return resources


def shutdown_scheduler(
    coordinator: SchedulerCoordinator, leader_election: LeaderElection | None = None
) -> None:
    """Gracefully stop the Scheduler on process exit.

    Args:
        coordinator: The running ``SchedulerCoordinator`` to stop.
        leader_election: The running ``LeaderElection`` to stop, if Redis-
            backed election is active — stopping it releases this
            instance's leadership immediately (rather than waiting for
            the lock's TTL to expire), so a graceful shutdown hands off
            leadership to another instance without a gap.
    """
    try:
        coordinator.stop(wait=True)
        logger.info("Scheduler stopped cleanly on process shutdown.")
    except Exception as exc:  # noqa: BLE001 - shutdown must not raise past atexit
        logger.error("Scheduler failed to shut down cleanly: %s", exc, exc_info=exc)

    if leader_election is not None:
        try:
            leader_election.stop()
        except Exception as exc:  # noqa: BLE001 - shutdown must not raise past atexit
            logger.error("Leader election failed to stop cleanly: %s", exc, exc_info=exc)


def shutdown_notification_email_dispatch(executor: ThreadPoolEmailDispatchExecutor) -> None:
    """Stop accepting new background email-dispatch tasks on process exit.

    Args:
        executor: The running ``ThreadPoolEmailDispatchExecutor`` to close.
    """
    try:
        executor.close(wait=False)
        logger.info("Notification email dispatch executor closed on process shutdown.")
    except Exception as exc:  # noqa: BLE001 - shutdown must not raise past atexit
        logger.error(
            "Notification email dispatch executor failed to close cleanly: %s", exc, exc_info=exc
        )
