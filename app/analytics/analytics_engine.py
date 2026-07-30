"""The Analytics Engine — central, read-only orchestration.

Per this package's design brief, ``AnalyticsEngine`` coordinates
analytics queries and calculations. It performs no state mutation of
any kind — every method is a read.

Every method computes each figure it returns via one of exactly two
strategies:

1. **A single, native repository aggregate query** (e.g.
   ``AnalyticsRepository.count_requests_by_status``), used whenever the
   Repository Layer already supports the requested scope directly. This
   is always exact.
2. **An exhaustive fetch-then-aggregate**, used only where no native
   aggregate exists for a needed grouping (e.g. "decisions per user").
   This fetches every matching page of an existing repository list
   method (no artificial page cap, so the result is the complete
   population, not a sample) and groups the result client-side using the
   pure functions in ``aggregations.py``. This is a single fetch per
   data source, not a loop issuing one query per item — the N+1 pattern
   this package does not introduce.

Wherever neither strategy can produce an accurate result for the
requested scope (see each DTO field's own docstring in ``dto.py`` for
the precise condition), this engine returns ``None`` rather than a
default, estimated, or partially-scoped value.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from datetime import datetime
from typing import TypeVar
from uuid import UUID

from app.analytics import aggregations, metrics
from app.analytics.dto import (
    ApprovalMetrics,
    DashboardMetrics,
    DepartmentMetrics,
    TimeGranularity,
    TimeSeries,
    UserMetrics,
    WorkflowMetrics,
)
from app.analytics.exceptions import MetricCalculationError, validate_date_range
from app.database.exceptions import DatabaseError, RecordNotFoundError
from app.database.repositories.analytics_repository import AnalyticsRepository
from app.database.repositories.approval_repository import ApprovalRepository
from app.database.repositories.audit_repository import AuditRepository
from app.database.repositories.base_repository import Page, PagedResult
from app.database.repositories.notification_repository import NotificationRepository
from app.database.repositories.request_repository import RequestRepository
from app.database.repositories.user_repository import ProfileRepository
from app.database.repositories.workflow_repository import (
    WorkflowStageRecord,
    WorkflowStageRepository,
)
from app.models import ApprovalThroughput, StatusBreakdown
from app.models.enums import AuditAction, UserRole
from app.utils.cache import ResponseCache, TTLCache, cached_method
from app.utils.datetime_utils import utc_now

__all__ = ["AnalyticsEngine"]

logger = logging.getLogger(__name__)

T = TypeVar("T")


def _map_status_breakdown(db_result) -> StatusBreakdown:
    """Map a persistence-level ``StatusBreakdown`` into its Domain Layer equivalent.

    Args:
        db_result: The result returned by ``AnalyticsRepository``.

    Returns:
        The corresponding ``app.models.StatusBreakdown``.
    """
    return StatusBreakdown(counts=dict(db_result.counts), total=db_result.total)


class AnalyticsEngine:
    """Coordinates read-only analytics queries and calculations.

    Every constructor argument is an already-finalized repository,
    injected — this class constructs no Supabase client of its own and
    performs no write of any kind.
    """

    def __init__(
        self,
        *,
        analytics_repo: AnalyticsRepository,
        request_repo: RequestRepository,
        approval_repo: ApprovalRepository,
        workflow_stage_repo: WorkflowStageRepository,
        profile_repo: ProfileRepository,
        audit_repo: AuditRepository,
        notification_repo: NotificationRepository,
        cache_ttl_seconds: float = 0.0,
        response_cache: ResponseCache | None = None,
    ) -> None:
        """Initialize the engine with its injected repositories.

        Args:
            analytics_repo: Pre-aggregated status/type/department/
                throughput queries.
            request_repo: Used for trend bucketing.
            approval_repo: Used for pending-approval counts.
            workflow_stage_repo: Reserved for future use; not currently
                queried directly by this engine (per-user stage duration
                is unavailable — see ``UserMetrics.average_decision_seconds``).
            profile_repo: Used to resolve individual users and
                role-scoped candidate pools.
            audit_repo: Used for escalation and per-user decision counts.
            notification_repo: Retained for interface completeness; not
                queried by this engine, since no method it exposes
                supports an organization-wide reminder count without
                iterating every recipient individually (see
                ``ApprovalMetrics.reminder_count``).
            cache_ttl_seconds: How long each public method's result is
                memoized for (``app.utils.cache.cached_method``), keyed
                by its own arguments — absorbs concurrent/duplicate
                dashboard requests within this window without serving
                meaningfully stale figures. Defaults to ``0`` (caching
                disabled, this class's original always-recompute
                behavior) so every existing caller/test sees no change
                unless it opts in; ``app.bootstrap`` passes a real,
                positive value for the production-wired instance.
            response_cache: An already-constructed cache backend to use
                instead of building a private in-process ``TTLCache``.
                ``app.bootstrap`` passes a shared
                ``app.utils.redis_cache.RedisCache`` here when
                ``AppSettings.redis.enabled`` — a multi-instance
                deployment then shares one analytics cache instead of
                each instance holding its own, independently-stale copy.
                Defaults to ``None`` (build a private ``TTLCache``, this
                class's original behavior), so every existing
                caller/test is unaffected.
        """
        self._analytics_repo = analytics_repo
        self._request_repo = request_repo
        self._approval_repo = approval_repo
        self._workflow_stage_repo = workflow_stage_repo
        self._profile_repo = profile_repo
        self._audit_repo = audit_repo
        self._notification_repo = notification_repo
        self._response_cache = response_cache or TTLCache(ttl_seconds=cache_ttl_seconds)
        self._logger = logging.getLogger(f"{__name__}.AnalyticsEngine")

    @cached_method
    def get_dashboard_metrics(
        self,
        *,
        company_id: UUID,
        department: str | None = None,
        request_type: str | None = None,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
    ) -> DashboardMetrics:
        """Return a company's dashboard figures, optionally further scoped.

        Args:
            company_id: Restricts every figure to this company (tenant).
            department: Restrict to this department, if provided.
            request_type: Restrict to this request type, if provided.
            created_after: Restrict to requests created at or after this
                timestamp, if provided.
            created_before: Restrict to requests created at or before
                this timestamp, if provided.

        Returns:
            The assembled ``DashboardMetrics``.

        Raises:
            InvalidTimeRangeError: If ``created_after`` is later than
                ``created_before``.
            MetricCalculationError: If the underlying repository query
                fails.
        """
        self._validate_range(created_after, created_before)
        status_breakdown = self._fetch_status_breakdown(
            company_id=company_id,
            department=department,
            request_type=request_type,
            created_after=created_after,
            created_before=created_before,
        )
        approval_metrics = self._compute_approval_metrics(
            company_id=company_id,
            request_type=request_type,
            department=department,
            created_after=created_after,
            created_before=created_before,
        )

        return DashboardMetrics(
            status_breakdown=status_breakdown,
            total_requests=metrics.total_requests(status_breakdown.counts),
            active_requests=metrics.active_requests(status_breakdown.counts),
            completed_requests=metrics.completed_requests(status_breakdown.counts),
            rejected_requests=metrics.rejected_requests(status_breakdown.counts),
            approval_metrics=approval_metrics,
        )

    @cached_method
    def get_approval_metrics(
        self,
        *,
        company_id: UUID,
        request_type: str | None = None,
        department: str | None = None,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
    ) -> ApprovalMetrics:
        """Return a company's approval-related metrics, optionally further scoped.

        Args:
            company_id: Restricts every figure to this company (tenant).
            request_type: Restrict to this request type, if provided.
            department: Restrict to this department, if provided.
            created_after: Restrict to decisions at or after this
                timestamp, if provided.
            created_before: Restrict to decisions at or before this
                timestamp, if provided.

        Returns:
            The assembled ``ApprovalMetrics``. See ``ApprovalMetrics``'s
            own docstring for the exact conditions under which
            ``average_decision_seconds``, ``escalation_count``, and
            ``reminder_count`` are ``None`` rather than a computed value.

        Raises:
            InvalidTimeRangeError: If ``created_after`` is later than
                ``created_before``.
            MetricCalculationError: If any underlying repository query
                fails.
        """
        self._validate_range(created_after, created_before)
        return self._compute_approval_metrics(
            company_id=company_id,
            request_type=request_type,
            department=department,
            created_after=created_after,
            created_before=created_before,
        )

    @cached_method
    def get_workflow_metrics(
        self,
        request_type: str,
        *,
        company_id: UUID,
        department: str | None = None,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
    ) -> WorkflowMetrics:
        """Return a company's metrics scoped to a single request type.

        Args:
            request_type: The request type to scope to.
            company_id: Restricts every figure to this company (tenant).
            department: Further restrict to this department, if
                provided.
            created_after: Restrict to requests created at or after this
                timestamp, if provided.
            created_before: Restrict to requests created at or before
                this timestamp, if provided.

        Returns:
            The assembled ``WorkflowMetrics``.

        Raises:
            InvalidTimeRangeError: If ``created_after`` is later than
                ``created_before``.
            MetricCalculationError: If any underlying repository query
                fails.
        """
        self._validate_range(created_after, created_before)
        status_breakdown = self._fetch_status_breakdown(
            company_id=company_id,
            department=department,
            request_type=request_type,
            created_after=created_after,
            created_before=created_before,
        )
        approval_metrics = self._compute_approval_metrics(
            company_id=company_id,
            request_type=request_type,
            department=department,
            created_after=created_after,
            created_before=created_before,
        )
        # escalation_count/reminder_count cannot be scoped by request_type
        # regardless of the department argument's value; _compute_approval_metrics
        # already returns None for both whenever request_type is provided.

        period_days = self._period_days(created_after, created_before)
        throughput_per_day = metrics.workflow_throughput_per_day(
            metrics.completed_requests(status_breakdown.counts), period_days
        )

        return WorkflowMetrics(
            request_type=request_type,
            status_breakdown=status_breakdown,
            approval_metrics=approval_metrics,
            throughput_per_day=throughput_per_day,
        )

    @cached_method
    def get_department_metrics(
        self,
        department: str,
        *,
        company_id: UUID,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
    ) -> DepartmentMetrics:
        """Return a company's metrics scoped to a single department.

        Args:
            department: The department to scope to.
            company_id: Restricts every figure to this company (tenant).
            created_after: Restrict to requests created at or after this
                timestamp, if provided.
            created_before: Restrict to requests created at or before
                this timestamp, if provided.

        Returns:
            The assembled ``DepartmentMetrics``. See
            ``DepartmentMetrics``'s own docstring for which
            ``approval_metrics`` fields are ``None``.

        Raises:
            InvalidTimeRangeError: If ``created_after`` is later than
                ``created_before``.
            MetricCalculationError: If any underlying repository query
                fails.
        """
        self._validate_range(created_after, created_before)
        status_breakdown = self._fetch_status_breakdown(
            company_id=company_id,
            department=department,
            created_after=created_after,
            created_before=created_before,
        )
        approval_metrics = self._compute_approval_metrics(
            company_id=company_id,
            request_type=None,
            department=department,
            created_after=created_after,
            created_before=created_before,
        )

        return DepartmentMetrics(
            department=department,
            status_breakdown=status_breakdown,
            approval_metrics=approval_metrics,
            workload=metrics.active_requests(status_breakdown.counts),
        )

    @cached_method
    def get_user_metrics(self, user_id: UUID, *, company_id: UUID) -> UserMetrics:
        """Return metrics scoped to a single user within a company.

        Every figure here is computed by a single, exact, count-only
        repository call scoped to ``user_id`` — this is not a loop over
        many users, so it carries none of the N+1 risk that a
        many-user summary would.

        Args:
            user_id: The user's id.
            company_id: The caller's own company (tenant). If ``user_id``
                resolves to a profile in a *different* company, this is
                treated identically to ``user_id`` not existing at all
                (a ``MetricCalculationError`` with the same "no profile
                exists" message) — never distinguished, matching this
                codebase's established not-found-vs-forbidden convention
                for out-of-scope resources.

        Returns:
            The assembled ``UserMetrics``. ``average_decision_seconds``
            is always ``None`` — see that field's own docstring.

        Raises:
            MetricCalculationError: If the profile does not exist, does
                not belong to ``company_id``, or any underlying
                repository query fails.
        """
        try:
            profile = self._profile_repo.get_by_id(user_id)
        except RecordNotFoundError as exc:
            raise MetricCalculationError(f"No profile exists for user {user_id}.") from exc
        except DatabaseError as exc:
            raise MetricCalculationError(f"Failed to fetch profile {user_id}: {exc}") from exc
        if profile.company_id != company_id:
            raise MetricCalculationError(f"No profile exists for user {user_id}.")

        try:
            approved_count = self._audit_repo.list_all(
                company_id=company_id,
                actor_id=user_id,
                action=AuditAction.STAGE_APPROVED.value,
                page=Page(size=1),
            ).total_records
            rejected_count = self._audit_repo.list_all(
                company_id=company_id,
                actor_id=user_id,
                action=AuditAction.STAGE_REJECTED.value,
                page=Page(size=1),
            ).total_records
            pending_count = self._approval_repo.list_pending_for_approver(
                company_id=company_id, assigned_to=user_id, page=Page(size=1)
            ).total_records
        except DatabaseError as exc:
            raise MetricCalculationError(
                f"Failed to compute user metrics for {user_id}: {exc}"
            ) from exc

        return UserMetrics(
            user_id=profile.id,
            full_name=profile.full_name,
            role=profile.role,
            decisions_approved=approved_count,
            decisions_rejected=rejected_count,
            pending_assigned_count=pending_count,
            average_decision_seconds=None,
        )

    @cached_method
    def get_workload_summary(
        self,
        *,
        company_id: UUID,
        department: str | None = None,
        pending_stages: Sequence[WorkflowStageRecord] | None = None,
    ) -> tuple[UserMetrics, ...]:
        """Return per-user metrics for every approver/administrator in a company.

        Unlike a naive per-user loop, this method issues exactly three
        exhaustive fetches — every matching profile, every
        ``STAGE_APPROVED`` audit entry, every ``STAGE_REJECTED`` audit
        entry, and every currently pending stage — and aggregates each
        client-side by actor/assignee using ``aggregations.py``'s pure
        grouping functions. No per-user repository call is issued.

        Note: the audit-entry and pending-stage fetches are company-wide
        (``audit_logs``/``workflow_stages`` carry no department column),
        so the resulting per-user counts are exact for each user
        regardless of the ``department`` filter, which is applied only to
        the profile pool being reported on.

        Args:
            company_id: Restricts every figure to this company (tenant).
            department: Restrict to approvers/administrators in this
                department, if provided.
            pending_stages: An already-fetched, company-wide pending-stage
                population, if the caller (typically
                ``OperationalAnalyticsEngine``, which needs this same
                population for its own figures) has already performed
                this exact exhaustive fetch itself — skips this method's
                own equivalent internal fetch, avoiding a second full
                scan of the same rows within one request. ``None`` (the
                default) preserves this method's original, fully
                self-contained behavior.

        Returns:
            A tuple of ``UserMetrics``, one per eligible user.
            ``average_decision_seconds`` is always ``None`` for every
            entry — see that field's own docstring.

        Raises:
            MetricCalculationError: If any underlying repository query
                fails.
        """
        try:
            approvers = self._fetch_all_by_role(
                UserRole.APPROVER, company_id=company_id, department=department
            )
            admins = self._fetch_all_by_role(
                UserRole.ADMIN, company_id=company_id, department=department
            )
        except DatabaseError as exc:
            raise MetricCalculationError(
                f"Failed to load workload summary profiles: {exc}"
            ) from exc

        profiles = (*approvers, *admins)

        try:
            approved_entries = self._fetch_all_audit(
                company_id=company_id, action=AuditAction.STAGE_APPROVED.value
            )
            rejected_entries = self._fetch_all_audit(
                company_id=company_id, action=AuditAction.STAGE_REJECTED.value
            )
            resolved_pending_stages = (
                pending_stages
                if pending_stages is not None
                else self._fetch_all_pending_stages(company_id=company_id)
            )
        except DatabaseError as exc:
            raise MetricCalculationError(
                f"Failed to load workload summary activity: {exc}"
            ) from exc

        approved_counts = aggregations.by_actor(approved_entries)
        rejected_counts = aggregations.by_actor(rejected_entries)
        pending_counts = aggregations.by_assignee(resolved_pending_stages)

        return tuple(
            UserMetrics(
                user_id=profile.id,
                full_name=profile.full_name,
                role=profile.role,
                decisions_approved=approved_counts.get(profile.id, 0),
                decisions_rejected=rejected_counts.get(profile.id, 0),
                pending_assigned_count=pending_counts.get(profile.id, 0),
                average_decision_seconds=None,
            )
            for profile in profiles
        )

    @cached_method
    def get_request_trend(
        self,
        *,
        company_id: UUID,
        granularity: TimeGranularity,
        department: str | None = None,
        request_type: str | None = None,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
    ) -> TimeSeries:
        """Return a company's time series of request submission volume, bucketed by granularity.

        Fetches every matching request exhaustively (no page cap), since
        no repository-level "group by period" aggregate exists — the
        result reflects the complete matching population, not a sample.

        Args:
            company_id: Restricts the population to this company (tenant).
            granularity: The bucket size.
            department: Restrict to this department, if provided.
            request_type: Restrict to this request type, if provided.
            created_after: Restrict to requests created at or after this
                timestamp, if provided.
            created_before: Restrict to requests created at or before
                this timestamp, if provided.

        Returns:
            The bucketed ``TimeSeries``.

        Raises:
            InvalidTimeRangeError: If ``created_after`` is later than
                ``created_before``.
            MetricCalculationError: If the underlying repository query
                fails.
        """
        self._validate_range(created_after, created_before)

        def _fetch_page(page: Page) -> PagedResult:
            return self._request_repo.list_requests(
                company_id=company_id,
                department=department,
                request_type=request_type,
                created_after=created_after,
                created_before=created_before,
                page=page,
            )

        try:
            all_requests = self._fetch_all(_fetch_page)
        except DatabaseError as exc:
            raise MetricCalculationError(f"Failed to compute request trend: {exc}") from exc

        timestamps = [request.created_at for request in all_requests]
        return aggregations.build_time_series(timestamps, granularity)

    def _compute_approval_metrics(
        self,
        *,
        company_id: UUID,
        request_type: str | None,
        department: str | None,
        created_after: datetime | None,
        created_before: datetime | None,
    ) -> ApprovalMetrics:
        """Compute approval metrics for an arbitrary department/request_type scope.

        Centralizes the exactness rules documented on ``ApprovalMetrics``:
        ``completed_count``/``rejected_count``/``completion_rate`` are
        always exact (``AnalyticsRepository.count_requests_by_status``
        supports both filters natively); ``average_decision_seconds`` is
        exact only when ``department`` is ``None`` (the repository's
        throughput query has no department parameter);
        ``escalation_count`` is exact only when both ``department`` and
        ``request_type`` are ``None`` (``audit_logs`` has neither
        column); ``reminder_count`` is always ``None``.

        Args:
            company_id: Restricts every figure to this company (tenant).
            request_type: The request type scope, if any.
            department: The department scope, if any.
            created_after: The lower date bound, if any.
            created_before: The upper date bound, if any.

        Returns:
            The assembled ``ApprovalMetrics``.

        Raises:
            MetricCalculationError: If any underlying repository query
                fails.
        """
        status_breakdown = self._fetch_status_breakdown(
            company_id=company_id,
            department=department,
            request_type=request_type,
            created_after=created_after,
            created_before=created_before,
        )
        completed_count = metrics.completed_requests(status_breakdown.counts)
        rejected_count = metrics.rejected_requests(status_breakdown.counts)
        completion = metrics.completion_rate(completed_count, rejected_count)

        average_decision_seconds: float | None = None
        if department is None:
            try:
                db_throughput = self._analytics_repo.approval_throughput(
                    company_id=company_id,
                    request_type=request_type,
                    created_after=created_after,
                    created_before=created_before,
                )
            except DatabaseError as exc:
                raise MetricCalculationError(
                    f"Failed to compute approval throughput: {exc}"
                ) from exc
            average_decision_seconds = db_throughput.average_decision_seconds

        escalation_count: int | None = None
        if department is None and request_type is None:
            escalation_count = self._count_escalations(
                company_id=company_id, created_after=created_after, created_before=created_before
            )

        throughput = ApprovalThroughput(
            average_decision_seconds=average_decision_seconds,
            completed_count=completed_count,
            rejected_count=rejected_count,
            completion_rate=completion,
        )

        return ApprovalMetrics(
            throughput=throughput,
            average_stage_duration_seconds=metrics.average_stage_duration_seconds(
                average_decision_seconds
            ),
            approval_latency_seconds=metrics.approval_latency_seconds(average_decision_seconds),
            escalation_count=escalation_count,
            reminder_count=None,
        )

    def _fetch_status_breakdown(
        self,
        *,
        company_id: UUID,
        department: str | None = None,
        request_type: str | None = None,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
    ) -> StatusBreakdown:
        """Fetch a request-status breakdown for an arbitrary scope.

        Args:
            company_id: Restricts the population to this company (tenant).
            department: Restrict to this department, if provided.
            request_type: Restrict to this request type, if provided.
            created_after: The lower date bound, if any.
            created_before: The upper date bound, if any.

        Returns:
            The mapped ``StatusBreakdown``.

        Raises:
            MetricCalculationError: If the underlying repository query
                fails.
        """
        try:
            db_status = self._analytics_repo.count_requests_by_status(
                company_id=company_id,
                department=department,
                request_type=request_type,
                created_after=created_after,
                created_before=created_before,
            )
        except DatabaseError as exc:
            raise MetricCalculationError(f"Failed to compute status breakdown: {exc}") from exc
        return _map_status_breakdown(db_status)

    def _count_escalations(
        self,
        *,
        company_id: UUID,
        created_after: datetime | None,
        created_before: datetime | None,
    ) -> int:
        """Count ``STAGE_ESCALATED`` audit events in the given date range, within a company.

        Args:
            company_id: Restricts the count to this company (tenant).
            created_after: The lower bound, if provided.
            created_before: The upper bound, if provided.

        Returns:
            The exact matching count.

        Raises:
            MetricCalculationError: If the underlying repository query
                fails.
        """
        try:
            return self._audit_repo.list_all(
                company_id=company_id,
                action=AuditAction.STAGE_ESCALATED.value,
                created_after=created_after,
                created_before=created_before,
                page=Page(size=1),
            ).total_records
        except DatabaseError as exc:
            raise MetricCalculationError(f"Failed to count escalations: {exc}") from exc

    def _fetch_all(
        self, fetch_page: Callable[[Page], PagedResult], *, page_size: int = 100
    ) -> list:
        """Exhaustively fetch every page of a paginated repository query.

        This performs no truncation: it continues until every page
        reported by the repository has been retrieved, so the returned
        list is the complete matching population, not a sample.

        Args:
            fetch_page: A callable accepting a ``Page`` and returning the
                corresponding ``PagedResult``.
            page_size: The page size to request on each call.

        Returns:
            The concatenated items from every page.
        """
        items: list = []
        page_number = 1
        while True:
            result = fetch_page(Page(number=page_number, size=page_size))
            if not result.items:
                break
            items.extend(result.items)
            if page_number >= result.total_pages:
                break
            page_number += 1
        return items

    def _fetch_all_by_role(self, role: UserRole, *, company_id: UUID, department: str | None):
        """Exhaustively fetch every profile with a given role, within a company.

        Args:
            role: The role to filter by.
            company_id: Restricts results to this company (tenant).
            department: Restrict to this department, if provided.

        Returns:
            The complete list of matching ``ProfileRecord`` instances.
        """
        return self._fetch_all(
            lambda page: self._profile_repo.list_by_role(
                role, company_id=company_id, department=department, page=page
            )
        )

    def _fetch_all_audit(self, *, company_id: UUID, action: str):
        """Exhaustively fetch every audit entry matching an action code, within a company.

        Args:
            company_id: Restricts results to this company (tenant).
            action: The audit action code to filter by.

        Returns:
            The complete list of matching ``AuditLogRecord`` instances.
        """
        return self._fetch_all(
            lambda page: self._audit_repo.list_all(company_id=company_id, action=action, page=page)
        )

    def _fetch_all_pending_stages(self, *, company_id: UUID):
        """Exhaustively fetch every currently pending workflow stage, within a company.

        Uses ``ApprovalRepository.list_overdue_stages`` with a cutoff of
        "now," which returns every pending stage regardless of assignee
        (every persisted stage's ``created_at`` is necessarily at or
        before the current instant) — the same technique already used by
        ``app.scheduler.jobs.iter_pending_stages``.

        Args:
            company_id: Restricts results to this company (tenant).

        Returns:
            The complete list of matching ``WorkflowStageRecord`` instances.
        """
        cutoff = utc_now()
        return self._fetch_all(
            lambda page: self._approval_repo.list_overdue_stages(
                created_before=cutoff, company_id=company_id, page=page
            )
        )

    def _period_days(
        self, created_after: datetime | None, created_before: datetime | None
    ) -> float | None:
        """Compute the length, in days, of a caller-supplied date range.

        Args:
            created_after: The lower bound, if provided.
            created_before: The upper bound, if provided.

        Returns:
            The number of days between the two bounds (never less than
            one, to keep a throughput calculation meaningful for a
            sub-daily range) if both are provided; ``None`` if either
            bound is missing — no default period is assumed.
        """
        return metrics.period_days(created_after, created_before)

    def _validate_range(
        self, created_after: datetime | None, created_before: datetime | None
    ) -> None:
        """Validate that a caller-supplied date range is internally consistent.

        Args:
            created_after: The lower bound, if provided.
            created_before: The upper bound, if provided.

        Raises:
            InvalidTimeRangeError: If both bounds are provided and
                ``created_after`` is later than ``created_before``.
        """
        validate_date_range(created_after, created_before)
