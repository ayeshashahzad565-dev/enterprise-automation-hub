"""Application service orchestrating every AI-generated insight in the platform.

Per this feature's design brief, this is the *only* service in ``app.services``
permitted to import ``app.ai`` or build a prompt — ``RequestService``,
``ApprovalService``, ``WorkflowDefinitionService``,
``AnalyticsService``/``OperationalAnalyticsEngine`` are consumed exactly as
``DashboardService``/``GlobalSearchService`` already consume other services
(read-only composition, never a repository directly) and are never modified
themselves. Prompt wording lives in ``app.services.ai_prompts`` (pure string
templating); this module owns authorization, data-gathering, caching, and
the graceful-fallback decision.

Every public method follows the same four steps:

1. Call the relevant existing service method(s) — this is both the data
   fetch *and* the authorization check (e.g. ``RequestService.get_request``
   raises ``NotFoundError`` for an out-of-scope request; company-wide
   methods call ``_require_analytics_access``, the same ``_ANALYTICS_ROLES``
   gate ``AnalyticsService`` already uses).
2. Build a ``(system_prompt, user_prompt)`` pair via ``app.services.ai_prompts``.
3. If no ``AiProvider`` is configured, or the call raises ``AiProviderError``,
   return the method's deterministic, non-AI fallback (built from the same
   data already fetched in step 1) — the single, centralized "graceful
   fallback" implementation every method reuses.
4. Wrap the result in an ``app.models.ai_insight.AiInsight``, transparently
   cached (a cache hit re-marks ``cached=True`` on the stored value rather
   than recomputing).

A failure to *fetch the underlying data* (e.g. ``app.analytics.exceptions.AnalyticsError``
from a repository-level failure) is a different concern from AI
unavailability and is deliberately **not** caught here — it propagates
exactly as it already does from ``app.api.routers.analytics``, to the same
existing global exception handler, since it means the requested data itself
could not be computed, not that the AI provider was unreachable.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Hashable
from typing import Literal
from uuid import UUID

from app.ai.exceptions import AiProviderError
from app.ai.interfaces import AiProvider
from app.analytics.operational_engine import OperationalAnalyticsEngine
from app.analytics.reporting import ReportingEngine
from app.auth.authentication import AuthenticatedIdentity
from app.auth.rbac import require_role
from app.database.repositories.base_repository import Page
from app.models.ai_insight import AiInsight
from app.models.enums import UserRole
from app.services import ai_prompts
from app.services.comment_service import CommentService
from app.services.dashboard_service import DashboardService
from app.services.exceptions import translate_auth_error
from app.services.request_service import RequestService
from app.services.workflow_definition_service import WorkflowDefinitionService
from app.utils.cache import ResponseCache, TTLCache
from app.utils.datetime_utils import utc_now
from app.utils.decorators import log_calls, timed

__all__ = ["AiChatTurn", "AiInsightService"]

logger = logging.getLogger(__name__)

#: The roles permitted to access company-wide AI insights — identical to
#: ``app.services.analytics_service._ANALYTICS_ROLES``, this module's own
#: least-privilege policy for the same class of organization-wide data.
_ANALYTICS_ROLES: tuple[UserRole, ...] = (UserRole.APPROVER, UserRole.ADMIN)

#: Cache TTL for per-entity summaries (request/approval) — short, since new
#: comments should become reflected reasonably soon.
_ENTITY_SUMMARY_CACHE_TTL_SECONDS = 300.0

#: Cache TTL for company-wide insights (bottlenecks, policy, operational
#: insights, executive summary, workflow improvements) — longer, since these
#: are this feature's most expensive calls and the underlying figures change
#: slowly. Both TTLs are a disclosed, bounded staleness window, the same
#: precedent ``app.analytics.analytics_engine.AnalyticsEngine``'s own cache
#: already established for this codebase.
_OPERATIONAL_INSIGHT_CACHE_TTL_SECONDS = 900.0

AiChatTurn = tuple[Literal["user", "assistant"], str]


class AiInsightService:
    """Orchestrates every AI-generated insight, with graceful, cached fallback."""

    def __init__(
        self,
        *,
        request_service: RequestService,
        comment_service: CommentService,
        workflow_definition_service: WorkflowDefinitionService,
        operational_engine: OperationalAnalyticsEngine,
        reporting_engine: ReportingEngine,
        dashboard_service: DashboardService,
        ai_provider: AiProvider | None,
        entity_cache: ResponseCache | None = None,
        operational_cache: ResponseCache | None = None,
        max_output_tokens: int = 600,
    ) -> None:
        """Initialize the service with its injected collaborators.

        Args:
            request_service: Used for request fetch/authorization and
                workflow-progress history.
            comment_service: Used for a request's comment thread.
            workflow_definition_service: Used to fetch a workflow
                definition's active version and structure.
            operational_engine: Used for bottleneck/delay/SLA/KPI data.
            reporting_engine: Used for the executive summary (and its
                narrative, which doubles as this feature's fallback).
            dashboard_service: Used to ground the AI assistant in the
                caller's own dashboard snapshot.
            ai_provider: The configured AI provider, or ``None`` if AI
                features are disabled (see ``app.bootstrap._build_ai_provider``)
                — every method degrades to its deterministic fallback in
                that case.
            entity_cache: Cache backend for per-entity summaries. Defaults
                to a private ``TTLCache`` when not supplied (matching
                ``AnalyticsEngine``'s own ``response_cache or TTLCache(...)``
                convention).
            operational_cache: Cache backend for company-wide insights.
                Same default-construction convention as ``entity_cache``.
            max_output_tokens: The default upper bound passed to every
                ``AiProvider.complete`` call.
        """
        self._request_service = request_service
        self._comment_service = comment_service
        self._workflow_definition_service = workflow_definition_service
        self._operational_engine = operational_engine
        self._reporting_engine = reporting_engine
        self._dashboard_service = dashboard_service
        self._ai_provider = ai_provider
        self._entity_cache = entity_cache or TTLCache(ttl_seconds=_ENTITY_SUMMARY_CACHE_TTL_SECONDS)
        self._operational_cache = operational_cache or TTLCache(
            ttl_seconds=_OPERATIONAL_INSIGHT_CACHE_TTL_SECONDS
        )
        self._max_output_tokens = max_output_tokens
        self._logger = logging.getLogger(f"{__name__}.AiInsightService")

    # ------------------------------------------------------------------
    # Request / approval summaries
    # ------------------------------------------------------------------

    @timed()
    @log_calls()
    def summarize_request(self, identity: AuthenticatedIdentity, request_id: UUID) -> AiInsight:
        """Summarize a request for someone who has not read it yet.

        Args:
            identity: The authenticated caller.
            request_id: The request's id.

        Returns:
            An ``AiInsight``.

        Raises:
            NotFoundError: If no request with this id exists, or it is
                outside the caller's visibility — per
                ``RequestService.get_request``'s own authorization.
        """
        request = self._request_service.get_request(identity, request_id)
        comments = self._comment_service.list_comments(identity, request_id, page=Page(size=50)).items

        def _compute() -> AiInsight:
            system_prompt, user_prompt = ai_prompts.build_request_summary_prompt(request, comments)
            fallback = ai_prompts.build_request_summary_fallback(request, comments)
            return self._complete_or_fallback(system_prompt, user_prompt, fallback)

        key = ("summarize_request", request_id, request.updated_at)
        return self._get_or_compute(self._entity_cache, key, _compute)

    @timed()
    @log_calls()
    def summarize_approval(self, identity: AuthenticatedIdentity, request_id: UUID) -> AiInsight:
        """Summarize a request, framed for an approver deciding on it.

        Authorization is deliberately identical to ``summarize_request`` —
        this method differs only in prompt framing (decision-oriented),
        not visibility; the requester, an assigned approver, or an admin
        may all call it, per ``RequestService.get_request``.

        Args:
            identity: The authenticated caller.
            request_id: The request's id.

        Returns:
            An ``AiInsight``.

        Raises:
            NotFoundError: If no request with this id exists, or it is
                outside the caller's visibility.
        """
        request = self._request_service.get_request(identity, request_id)
        progress = self._request_service.get_workflow_progress(identity, request_id)
        comments = self._comment_service.list_comments(identity, request_id, page=Page(size=50)).items

        def _compute() -> AiInsight:
            system_prompt, user_prompt = ai_prompts.build_approval_summary_prompt(
                request, progress, comments
            )
            fallback = ai_prompts.build_approval_summary_fallback(request, progress, comments)
            return self._complete_or_fallback(system_prompt, user_prompt, fallback)

        key = ("summarize_approval", request_id, request.updated_at)
        return self._get_or_compute(self._entity_cache, key, _compute)

    # ------------------------------------------------------------------
    # Workflow improvements
    # ------------------------------------------------------------------

    @timed()
    @log_calls()
    def suggest_workflow_improvements(
        self, identity: AuthenticatedIdentity, request_type: str
    ) -> AiInsight:
        """Suggest improvements to a workflow's active version.

        Args:
            identity: The authenticated caller. Must be an admin — matches
                the Workflow Designer page's own admin-only gate.
            request_type: The workflow's request type.

        Returns:
            An ``AiInsight``.

        Raises:
            PermissionDeniedError: If ``identity`` is not an admin.
            NotFoundError: If no active workflow definition exists for
                ``request_type``.
        """
        self._require_role(identity, UserRole.ADMIN)
        definition = self._workflow_definition_service.get_active_version(
            request_type, company_id=identity.company_id
        )
        bottlenecks = self._operational_engine.get_bottlenecks(
            company_id=identity.company_id, request_type=request_type
        )
        delays = self._operational_engine.get_approval_delays(
            company_id=identity.company_id, request_type=request_type
        )

        def _compute() -> AiInsight:
            system_prompt, user_prompt = ai_prompts.build_workflow_improvements_prompt(
                definition, bottlenecks, delays
            )
            fallback = ai_prompts.build_workflow_improvements_fallback(definition, bottlenecks)
            return self._complete_or_fallback(system_prompt, user_prompt, fallback)

        key = ("suggest_workflow_improvements", identity.company_id, request_type, definition.version)
        return self._get_or_compute(self._operational_cache, key, _compute)

    # ------------------------------------------------------------------
    # Company-wide operational insights
    # ------------------------------------------------------------------

    @timed()
    @log_calls()
    def explain_bottlenecks(self, identity: AuthenticatedIdentity) -> AiInsight:
        """Explain the company's current approval bottlenecks and delays.

        Args:
            identity: The authenticated caller. Must be an approver or
                admin.

        Returns:
            An ``AiInsight``.

        Raises:
            PermissionDeniedError: If ``identity`` is an employee.
        """
        self._require_analytics_access(identity)
        bottlenecks = self._operational_engine.get_bottlenecks(company_id=identity.company_id)
        delays = self._operational_engine.get_approval_delays(company_id=identity.company_id)

        def _compute() -> AiInsight:
            system_prompt, user_prompt = ai_prompts.build_bottleneck_explanation_prompt(
                bottlenecks, delays
            )
            fallback = ai_prompts.build_bottleneck_explanation_fallback(bottlenecks, delays)
            return self._complete_or_fallback(system_prompt, user_prompt, fallback)

        key = ("explain_bottlenecks", identity.company_id)
        return self._get_or_compute(self._operational_cache, key, _compute)

    @timed()
    @log_calls()
    def recommend_policies(self, identity: AuthenticatedIdentity) -> AiInsight:
        """Recommend approval-policy changes based on current operational data.

        Args:
            identity: The authenticated caller. Must be an approver or
                admin.

        Returns:
            An ``AiInsight``.

        Raises:
            PermissionDeniedError: If ``identity`` is an employee.
        """
        self._require_analytics_access(identity)
        bottlenecks = self._operational_engine.get_bottlenecks(company_id=identity.company_id)
        delays = self._operational_engine.get_approval_delays(company_id=identity.company_id)
        sla = self._operational_engine.get_sla_metrics(company_id=identity.company_id)

        def _compute() -> AiInsight:
            system_prompt, user_prompt = ai_prompts.build_policy_recommendation_prompt(
                bottlenecks, delays, sla
            )
            fallback = ai_prompts.build_policy_recommendation_fallback(bottlenecks, delays)
            return self._complete_or_fallback(system_prompt, user_prompt, fallback)

        key = ("recommend_policies", identity.company_id)
        return self._get_or_compute(self._operational_cache, key, _compute)

    @timed()
    @log_calls()
    def generate_operational_insights(self, identity: AuthenticatedIdentity) -> AiInsight:
        """Generate a broad operational-insights briefing.

        Args:
            identity: The authenticated caller. Must be an approver or
                admin.

        Returns:
            An ``AiInsight``.

        Raises:
            PermissionDeniedError: If ``identity`` is an employee.
        """
        self._require_analytics_access(identity)
        bottlenecks = self._operational_engine.get_bottlenecks(company_id=identity.company_id)
        delays = self._operational_engine.get_approval_delays(company_id=identity.company_id)
        sla = self._operational_engine.get_sla_metrics(company_id=identity.company_id)
        kpis = self._operational_engine.get_executive_kpis(company_id=identity.company_id)

        def _compute() -> AiInsight:
            system_prompt, user_prompt = ai_prompts.build_operational_insights_prompt(
                bottlenecks, delays, sla, kpis
            )
            fallback = ai_prompts.build_operational_insights_fallback(bottlenecks, delays, sla, kpis)
            return self._complete_or_fallback(system_prompt, user_prompt, fallback)

        key = ("generate_operational_insights", identity.company_id)
        return self._get_or_compute(self._operational_cache, key, _compute)

    @timed()
    @log_calls()
    def generate_executive_summary(self, identity: AuthenticatedIdentity) -> AiInsight:
        """Generate an AI executive summary of the current period's activity.

        Args:
            identity: The authenticated caller. Must be an approver or
                admin.

        Returns:
            An ``AiInsight``. Its fallback is
            ``ReportingEngine.build_executive_summary(...).narrative``
            verbatim — the existing, already-good, non-AI summary this
            codebase already computes — rather than a separately
            hand-written fallback string.

        Raises:
            PermissionDeniedError: If ``identity`` is an employee.
        """
        self._require_analytics_access(identity)
        summary = self._reporting_engine.build_executive_summary(company_id=identity.company_id)

        def _compute() -> AiInsight:
            system_prompt, user_prompt = ai_prompts.build_executive_summary_prompt(summary)
            return self._complete_or_fallback(system_prompt, user_prompt, summary.narrative)

        key = ("generate_executive_summary", identity.company_id)
        return self._get_or_compute(self._operational_cache, key, _compute)

    # ------------------------------------------------------------------
    # Dashboard assistant
    # ------------------------------------------------------------------

    @timed()
    @log_calls()
    def ask_assistant(
        self,
        identity: AuthenticatedIdentity,
        question: str,
        history: list[AiChatTurn] | None = None,
    ) -> AiInsight:
        """Answer a natural-language question, grounded in the caller's
        own dashboard snapshot.

        Deliberately not cached (arbitrary question text plus per-call
        history makes cache keys low-hit-rate) and not agentic — it
        answers strictly from a fixed snapshot of already-authorized
        figures, never a query the model itself constructs.

        Args:
            identity: The authenticated caller. Must be an approver or
                admin.
            question: The caller's free-form question.
            history: Prior turns in this conversation, oldest first, as
                supplied by the client (no server-side persistence — see
                this feature's documented scope decision).

        Returns:
            An ``AiInsight``.

        Raises:
            PermissionDeniedError: If ``identity`` is an employee.
        """
        self._require_analytics_access(identity)
        dashboard = self._dashboard_service.get_dashboard_summary(identity)
        kpis = (
            self._operational_engine.get_executive_kpis(company_id=identity.company_id)
            if identity.role is UserRole.ADMIN or identity.role is UserRole.APPROVER
            else None
        )

        system_prompt, user_prompt = ai_prompts.build_assistant_prompt(
            question,
            history or [],
            open_requests=dashboard.open_requests_count,
            pending_approvals=dashboard.pending_approvals_count,
            unread_notifications=dashboard.unread_notifications_count,
            kpis=kpis,
        )
        return self._complete_or_fallback(
            system_prompt, user_prompt, ai_prompts.ASSISTANT_UNAVAILABLE_FALLBACK
        )

    # ------------------------------------------------------------------
    # Shared internals
    # ------------------------------------------------------------------

    def _require_analytics_access(self, identity: AuthenticatedIdentity) -> None:
        """Enforce this module's ``_ANALYTICS_ROLES`` least-privilege policy."""
        self._require_role(identity, *_ANALYTICS_ROLES)

    def _require_role(self, identity: AuthenticatedIdentity, *allowed_roles: UserRole) -> None:
        try:
            require_role(identity.role, *allowed_roles)
        except Exception as exc:  # noqa: BLE001 - translated below
            raise translate_auth_error(exc) from exc

    def _complete_or_fallback(
        self, system_prompt: str, user_prompt: str, fallback_text: str
    ) -> AiInsight:
        """Call the AI provider, degrading to ``fallback_text`` when
        unavailable or on any provider-level failure.

        This is the single, centralized implementation of this feature's
        "graceful fallback" requirement — every public method above calls
        this, so no per-caller ``try``/``except`` exists anywhere else.
        """
        if self._ai_provider is None:
            return AiInsight(
                text=fallback_text, generated_by=None, is_fallback=True, cached=False,
                generated_at=utc_now(),
            )
        try:
            completion = self._ai_provider.complete(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_output_tokens=self._max_output_tokens,
            )
        except AiProviderError as exc:
            self._logger.warning("AI provider call failed, using fallback: %s", exc)
            return AiInsight(
                text=fallback_text, generated_by=None, is_fallback=True, cached=False,
                generated_at=utc_now(),
            )
        return AiInsight(
            text=completion.text,
            generated_by=f"{completion.provider_name}:{completion.model}",
            is_fallback=False,
            cached=False,
            generated_at=utc_now(),
        )

    def _get_or_compute(
        self, cache: ResponseCache, key: Hashable, compute: Callable[[], AiInsight]
    ) -> AiInsight:
        """Wrap ``cache.get_or_compute`` with accurate ``AiInsight.cached`` tracking.

        ``cache.get_or_compute`` itself has no way to tell its caller
        whether a given call was a hit or a miss — a mutable closure flag
        tracks it here, and a hit's stored ``cached=False`` value is
        re-marked ``cached=True`` on return, without recomputing anything.
        """
        state = {"hit": True}

        def _tracked_compute() -> AiInsight:
            state["hit"] = False
            return compute()

        result = cache.get_or_compute(key, _tracked_compute)
        return result.model_copy(update={"cached": True}) if state["hit"] else result
