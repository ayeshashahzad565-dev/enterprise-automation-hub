"""The Operational Analytics Engine (Milestone 12).

``OperationalAnalyticsEngine`` implements ``OperationalAnalyticsProvider``
on top of the finalized ``AnalyticsProvider``/``AnalyticsRepository``
stack (Milestones 0-11): SLA tracking, approval-delay detection,
bottleneck detection, workload analytics, trend analytics, executive
KPIs, and department analytics.

Per this package's own design brief (see ``analytics_engine.py``'s
docstring), every figure here is computed one of three ways, in order of
preference:

1. **Direct reuse** of an already-computed ``AnalyticsProvider``/
   ``AnalyticsRepository`` figure (``get_dashboard_metrics``,
   ``get_workload_summary``, ``get_request_trend``,
   ``get_department_metrics``, ``count_requests_by_department``,
   ``count_requests_by_type``, ``approval_throughput``) — never
   recomputed independently.
2. **A single, native repository aggregate query**, when one already
   exists and no reuse opportunity applies.
3. **An exhaustive fetch-then-aggregate** over ``WorkflowStageRepository
   .list_decided``/``ApprovalRepository.list_overdue_stages`` (a single
   fetch per data source, not a loop issuing one query per item), used
   only for the row-level breakdowns (by stage, by department, by
   workflow, median, SLA-breach-at-decision-time) no existing aggregate
   method returns.

SLA breach and "escalation eligible" are, by construction, the exact
same computation: every overdue/breach determination in this module
calls ``WorkflowEngine.is_stage_escalation_eligible`` — the identical
pure function the Scheduler's Escalation Check job already uses — against
a stage's own workflow definition's configured ``escalation_hours``
(or an explicit caller override), never a second, independently invented
threshold concept.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from datetime import datetime, timedelta
from typing import TypeVar
from uuid import UUID

from app.analytics import aggregations, metrics
from app.analytics.dto import TimeGranularity
from app.analytics.exceptions import MetricCalculationError, validate_date_range
from app.analytics.interfaces import AnalyticsProvider
from app.analytics.operational_dto import (
    ApprovalDelayReport,
    BottleneckReport,
    CountBucket,
    DepartmentAnalytics,
    DurationBucket,
    ExecutiveKPIs,
    PendingApprovalAge,
    RejectionBucket,
    SLAMetrics,
    TrendReport,
    WorkloadReport,
)
from app.database.exceptions import DatabaseError
from app.database.repositories.analytics_repository import AnalyticsRepository
from app.database.repositories.approval_repository import ApprovalRepository
from app.database.repositories.audit_repository import AuditRepository
from app.database.repositories.base_repository import Page, PagedResult
from app.database.repositories.request_repository import RequestRecord, RequestRepository
from app.database.repositories.workflow_repository import (
    WorkflowDefinitionRecord,
    WorkflowDefinitionRepository,
    WorkflowStageRecord,
    WorkflowStageRepository,
)
from app.models import StageDefinition, WorkflowDefinition
from app.models.enums import AuditAction, RequestStatus, StageStatus
from app.services.workflow_definition_service import map_workflow_definition_record_to_domain
from app.utils.cache import ResponseCache, TTLCache, cached_method
from app.utils.datetime_utils import seconds_between, utc_now
from app.workflow.engine import WorkflowEngine

__all__ = ["OperationalAnalyticsEngine"]

logger = logging.getLogger(__name__)

T = TypeVar("T")

#: The default number of rows returned by every ranked/sortable dataset
#: this engine produces, matching the existing "Aging Requests" view's
#: own default page size (``app.api.routers.analytics.get_aging_requests``).
_DEFAULT_LIMIT = 10

#: Maximum ids per ``.in_("id", [...])`` filter for a single bulk-resolve
#: request. Every distinct id referenced by the stages in scope was
#: previously placed into one filter regardless of count; with a
#: realistically sized dataset (hundreds of distinct requests referenced
#: company-wide) that produces a query string long enough for Supabase's
#: gateway to reject the request outright with a non-JSON 400 response,
#: before it ever reaches PostgREST. Chunking bounds each request's URL
#: length comfortably regardless of how large the dataset grows.
_ID_FILTER_BATCH_SIZE = 50


def _chunked(items: Sequence[T], size: int) -> list[list[T]]:
    """Split ``items`` into consecutive chunks of at most ``size`` each."""
    return [list(items[i : i + size]) for i in range(0, len(items), size)]


class OperationalAnalyticsEngine:
    """Coordinates operational-intelligence queries and calculations.

    Every constructor argument is an already-finalized repository or
    engine, injected — this class constructs nothing of its own and
    performs no write of any kind. ``analytics_provider`` is depended on
    directly (composition, not duplication) so that every figure
    ``AnalyticsEngine`` already computes is reused rather than
    re-derived.
    """

    def __init__(
        self,
        *,
        analytics_provider: AnalyticsProvider,
        analytics_repo: AnalyticsRepository,
        request_repo: RequestRepository,
        workflow_stage_repo: WorkflowStageRepository,
        approval_repo: ApprovalRepository,
        workflow_definition_repo: WorkflowDefinitionRepository,
        audit_repo: AuditRepository,
        workflow_engine: WorkflowEngine,
        cache_ttl_seconds: float = 0.0,
        response_cache: ResponseCache | None = None,
    ) -> None:
        """Initialize the engine with its injected collaborators.

        Args:
            analytics_provider: The finalized Analytics Layer facade,
                reused directly for every figure it already computes.
            analytics_repo: Read-only aggregate queries against
                ``requests``/``workflow_stages``.
            request_repo: Used to bulk-resolve stages' owning requests
                and to fetch completed requests for duration/trend
                figures.
            workflow_stage_repo: Used for ``list_decided``, the
                company-wide row-level read this module's breakdown
                figures depend on.
            approval_repo: Used for ``list_overdue_stages`` (the
                company-wide pending-stage read).
            workflow_definition_repo: Used to resolve each stage's own
                configured ``escalation_hours``.
            audit_repo: Used for approval/rejection trend bucketing.
            workflow_engine: The composed Workflow Engine facade, used
                for the pure escalation/SLA-eligibility check.
            cache_ttl_seconds: How long each public method's result is
                memoized for (``app.utils.cache.cached_method``), keyed
                by its own arguments — see ``AnalyticsEngine``'s
                identical parameter for the full rationale, including why
                this defaults to ``0`` (disabled). Every public method
                here already avoids duplicate work *within* one call (the
                module's own "single fetch per data source" design
                brief); a positive TTL additionally bounds duplicate work
                *across* nearby calls, e.g. a dashboard's several widgets
                polling the same company/filter combination within a few
                seconds of each other.
            response_cache: An already-constructed cache backend to use
                instead of building a private in-process ``TTLCache`` —
                see ``AnalyticsEngine``'s identical parameter. Defaults
                to ``None`` (build a private ``TTLCache``), so every
                existing caller/test is unaffected.
        """
        self._analytics_provider = analytics_provider
        self._analytics_repo = analytics_repo
        self._request_repo = request_repo
        self._workflow_stage_repo = workflow_stage_repo
        self._approval_repo = approval_repo
        self._workflow_definition_repo = workflow_definition_repo
        self._audit_repo = audit_repo
        self._workflow_engine = workflow_engine
        self._response_cache = response_cache or TTLCache(ttl_seconds=cache_ttl_seconds)
        self._logger = logging.getLogger(f"{__name__}.OperationalAnalyticsEngine")

    # ------------------------------------------------------------------
    # 1. SLA Engine
    # ------------------------------------------------------------------

    @cached_method
    def get_sla_metrics(
        self,
        *,
        company_id: UUID,
        sla_hours_override: float | None = None,
        department: str | None = None,
        request_type: str | None = None,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
    ) -> SLAMetrics:
        """Return a company's SLA compliance snapshot, optionally further scoped.

        Raises:
            InvalidTimeRangeError: If ``created_after`` is later than
                ``created_before``.
            MetricCalculationError: If any underlying repository query
                fails.
        """
        validate_date_range(created_after, created_before)
        now = utc_now()
        try:
            pending_stages = self._fetch_all_pending_stages(company_id=company_id)
            decided_stages = self._fetch_decided_stages(
                company_id=company_id, created_after=created_after, created_before=created_before
            )
            requests_by_id, definitions_by_id = self._resolve_contexts(
                (*pending_stages, *decided_stages), company_id=company_id
            )
        except DatabaseError as exc:
            raise MetricCalculationError(f"Failed to compute SLA metrics: {exc}") from exc

        pending_ages = self._filter_pending_scope(
            self._build_pending_approval_ages(
                pending_stages,
                requests_by_id,
                definitions_by_id,
                sla_hours_override=sla_hours_override,
                now=now,
            ),
            department=department,
            request_type=request_type,
        )
        overdue = [p for p in pending_ages if p.is_overdue]

        decided_scoped = self._filter_decided_scope(
            decided_stages, requests_by_id, department=department, request_type=request_type
        )
        decided_count = 0
        breach_count = 0
        for stage in decided_scoped:
            effective_sla = self._effective_sla_hours(
                stage, requests_by_id, definitions_by_id, sla_hours_override=sla_hours_override
            )
            if effective_sla is None or stage.decided_at is None:
                continue
            decided_count += 1
            if self._workflow_engine.is_stage_escalation_eligible(
                stage.created_at, effective_sla, now=stage.decided_at
            ):
                breach_count += 1

        scoped_completed = self._scope_requests(
            self._fetch_completed_requests(company_id=company_id),
            department=department,
            request_type=request_type,
            created_after=created_after,
            created_before=created_before,
        )
        durations = [
            seconds_between(r.created_at, r.completed_at)
            for r in scoped_completed
            if r.completed_at is not None
        ]

        average_approval_duration_seconds: float | None = None
        if department is None:
            try:
                average_approval_duration_seconds = self._analytics_repo.approval_throughput(
                    company_id=company_id,
                    request_type=request_type,
                    created_after=created_after,
                    created_before=created_before,
                ).average_decision_seconds
            except DatabaseError as exc:
                raise MetricCalculationError(
                    f"Failed to compute approval throughput: {exc}"
                ) from exc

        return SLAMetrics(
            sla_hours_override=sla_hours_override,
            pending_stage_count=len(pending_ages),
            overdue_stage_count=len(overdue),
            overdue_request_count=len({p.request_id for p in overdue}),
            average_current_stage_age_hours=metrics.average([p.age_hours for p in pending_ages]),
            decided_stage_count=decided_count,
            sla_breaches_decided=breach_count,
            sla_compliance_percentage=metrics.compliance_rate(
                decided_count - breach_count, breach_count
            ),
            average_total_workflow_duration_seconds=metrics.average(durations),
            average_approval_duration_seconds=average_approval_duration_seconds,
        )

    # ------------------------------------------------------------------
    # 2. Approval Delay Detection
    # ------------------------------------------------------------------

    @cached_method
    def get_approval_delays(
        self,
        *,
        company_id: UUID,
        department: str | None = None,
        request_type: str | None = None,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
        limit: int = _DEFAULT_LIMIT,
    ) -> ApprovalDelayReport:
        """Return a company's approval-delay datasets, optionally further scoped.

        Raises:
            InvalidTimeRangeError: If ``created_after`` is later than
                ``created_before``.
            MetricCalculationError: If any underlying repository query
                fails.
        """
        validate_date_range(created_after, created_before)
        now = utc_now()
        try:
            pending_stages = self._fetch_all_pending_stages(company_id=company_id)
            decided_stages = self._fetch_decided_stages(
                company_id=company_id, created_after=created_after, created_before=created_before
            )
            requests_by_id, definitions_by_id = self._resolve_contexts(
                (*pending_stages, *decided_stages), company_id=company_id
            )
        except DatabaseError as exc:
            raise MetricCalculationError(f"Failed to compute approval delays: {exc}") from exc

        pending_ages = self._filter_pending_scope(
            self._build_pending_approval_ages(
                pending_stages, requests_by_id, definitions_by_id, sla_hours_override=None, now=now
            ),
            department=department,
            request_type=request_type,
        )
        longest_pending = tuple(
            sorted(pending_ages, key=lambda p: p.age_hours, reverse=True)[:limit]
        )

        distinct_by_request: dict[UUID, PendingApprovalAge] = {}
        for pending in pending_ages:
            distinct_by_request.setdefault(pending.request_id, pending)
        oldest_pending_requests = tuple(
            sorted(
                distinct_by_request.values(),
                key=lambda p: requests_by_id[p.request_id].created_at,
            )[:limit]
        )

        decided_scoped = self._filter_decided_scope(
            decided_stages, requests_by_id, department=department, request_type=request_type
        )
        durations = [
            seconds_between(s.created_at, s.decided_at)
            for s in decided_scoped
            if s.decided_at is not None
        ]

        return ApprovalDelayReport(
            longest_pending=longest_pending,
            oldest_pending_requests=oldest_pending_requests,
            average_approval_seconds=metrics.average(durations),
            median_approval_seconds=metrics.median(durations),
            duration_by_stage=self._duration_buckets(decided_scoped, key_fn=lambda s: s.stage_name),
            duration_by_department=self._duration_buckets(
                decided_scoped,
                key_fn=lambda s: requests_by_id[s.request_id].department or "unspecified",
            ),
            duration_by_workflow=self._duration_buckets(
                decided_scoped, key_fn=lambda s: requests_by_id[s.request_id].request_type
            ),
        )

    # ------------------------------------------------------------------
    # 3. Bottleneck Detection
    # ------------------------------------------------------------------

    @cached_method
    def get_bottlenecks(
        self,
        *,
        company_id: UUID,
        department: str | None = None,
        request_type: str | None = None,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
        limit: int = _DEFAULT_LIMIT,
    ) -> BottleneckReport:
        """Return a company's bottleneck-identification datasets, optionally further scoped.

        Reuses the exact same pending/decided stage populations
        ``get_approval_delays``/``get_sla_metrics`` already fetch, and
        ``AnalyticsProvider.get_workload_summary`` for approver queue
        depth — no separate query is issued for an overlapping
        population.

        Raises:
            InvalidTimeRangeError: If ``created_after`` is later than
                ``created_before``.
            MetricCalculationError: If any underlying repository query
                fails.
        """
        validate_date_range(created_after, created_before)
        now = utc_now()
        try:
            pending_stages = self._fetch_all_pending_stages(company_id=company_id)
            decided_stages = self._fetch_decided_stages(
                company_id=company_id, created_after=created_after, created_before=created_before
            )
            requests_by_id, definitions_by_id = self._resolve_contexts(
                (*pending_stages, *decided_stages), company_id=company_id
            )
            workload = self._analytics_provider.get_workload_summary(
                company_id=company_id, department=department, pending_stages=pending_stages
            )
        except DatabaseError as exc:
            raise MetricCalculationError(f"Failed to compute bottlenecks: {exc}") from exc

        pending_ages = self._filter_pending_scope(
            self._build_pending_approval_ages(
                pending_stages, requests_by_id, definitions_by_id, sla_hours_override=None, now=now
            ),
            department=department,
            request_type=request_type,
        )
        decided_scoped = self._filter_decided_scope(
            decided_stages, requests_by_id, department=department, request_type=request_type
        )

        approver_queue_depth = tuple(
            sorted(workload, key=lambda u: u.pending_assigned_count, reverse=True)[:limit]
        )

        overdue_counts: dict[str, int] = {}
        for pending in pending_ages:
            if pending.is_overdue:
                overdue_counts[pending.stage_name] = overdue_counts.get(pending.stage_name, 0) + 1
        frequently_overdue_stages = tuple(
            sorted(
                (CountBucket(key=key, count=count) for key, count in overdue_counts.items()),
                key=lambda b: b.count,
                reverse=True,
            )[:limit]
        )

        rejection_counts: dict[str, list[bool]] = {}
        for stage in decided_scoped:
            rejection_counts.setdefault(stage.stage_name, []).append(
                stage.status is StageStatus.REJECTED
            )
        rejection_hotspots_all = [
            RejectionBucket(
                key=key,
                decided_count=len(outcomes),
                rejected_count=sum(outcomes),
                rejection_rate=(sum(outcomes) / len(outcomes)) if outcomes else None,
            )
            for key, outcomes in rejection_counts.items()
        ]
        rejection_hotspots_all.sort(
            key=lambda b: (b.rejection_rate is None, -(b.rejection_rate or 0.0))
        )

        return BottleneckReport(
            slowest_stages=self._duration_buckets(decided_scoped, key_fn=lambda s: s.stage_name)[
                :limit
            ],
            slowest_workflows=self._duration_buckets(
                decided_scoped, key_fn=lambda s: requests_by_id[s.request_id].request_type
            )[:limit],
            departments_causing_delay=self._duration_buckets(
                decided_scoped,
                key_fn=lambda s: requests_by_id[s.request_id].department or "unspecified",
            )[:limit],
            approver_queue_depth=approver_queue_depth,
            frequently_overdue_stages=frequently_overdue_stages,
            rejection_hotspots=tuple(rejection_hotspots_all[:limit]),
        )

    # ------------------------------------------------------------------
    # 4. Workload Analytics
    # ------------------------------------------------------------------

    @cached_method
    def get_workload_report(
        self, *, company_id: UUID, department: str | None = None
    ) -> WorkloadReport:
        """Return a company's workload distribution, optionally scoped to a department.

        Raises:
            MetricCalculationError: If any underlying repository query
                fails.
        """
        now = utc_now()
        try:
            dashboard = self._analytics_provider.get_dashboard_metrics(
                company_id=company_id, department=department
            )
            # Fetched once, up front, and passed into get_workload_summary
            # below — avoids that method's own equivalent internal
            # pending-stage fetch re-scanning the exact same rows.
            pending_stages = self._fetch_all_pending_stages(company_id=company_id)
            workload_summary = self._analytics_provider.get_workload_summary(
                company_id=company_id, department=department, pending_stages=pending_stages
            )
            requests_per_department = self._analytics_repo.count_requests_by_department(
                company_id=company_id
            ).counts
            requests_per_workflow = self._analytics_repo.count_requests_by_type(
                company_id=company_id, department=department
            ).counts
            completed_requests = self._fetch_completed_requests(company_id=company_id)
        except DatabaseError as exc:
            raise MetricCalculationError(f"Failed to compute workload report: {exc}") from exc

        pending_workload = len(pending_stages)
        scoped_completed = completed_requests
        if department is not None:
            try:
                requests_by_id, _ = self._resolve_contexts(pending_stages, company_id=company_id)
            except DatabaseError as exc:
                raise MetricCalculationError(f"Failed to compute workload report: {exc}") from exc
            pending_workload = sum(
                1
                for stage in pending_stages
                if (request := requests_by_id.get(stage.request_id)) is not None
                and request.department == department
            )
            scoped_completed = [r for r in completed_requests if r.department == department]

        completed_ats = [r.completed_at for r in scoped_completed if r.completed_at is not None]
        start_of_today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        week_ago = now - timedelta(days=7)
        month_ago = now - timedelta(days=30)

        return WorkloadReport(
            approvals_per_approver=tuple(workload_summary),
            requests_per_department=requests_per_department,
            requests_per_workflow=requests_per_workflow,
            completed_today=sum(1 for ts in completed_ats if ts >= start_of_today),
            completed_this_week=sum(1 for ts in completed_ats if ts >= week_ago),
            completed_this_month=sum(1 for ts in completed_ats if ts >= month_ago),
            active_workload=dashboard.active_requests,
            completed_workload=dashboard.completed_requests,
            pending_workload=pending_workload,
        )

    # ------------------------------------------------------------------
    # 5. Trend Analytics
    # ------------------------------------------------------------------

    @cached_method
    def get_trends(
        self,
        *,
        company_id: UUID,
        granularity: TimeGranularity,
        department: str | None = None,
        request_type: str | None = None,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
    ) -> TrendReport:
        """Return a company's execution trends, optionally further scoped.

        ``approval_trend``/``rejection_trend`` are computed organization-
        (company-)wide regardless of ``department``/``request_type`` —
        ``audit_logs`` carries neither column, the same documented
        limitation ``ApprovalMetrics.escalation_count`` already discloses
        elsewhere in this package, not a new gap introduced here.

        Raises:
            InvalidTimeRangeError: If ``created_after`` is later than
                ``created_before``.
            MetricCalculationError: If any underlying repository query
                fails.
        """
        validate_date_range(created_after, created_before)
        try:
            request_volume = self._analytics_provider.get_request_trend(
                company_id=company_id,
                granularity=granularity,
                department=department,
                request_type=request_type,
                created_after=created_after,
                created_before=created_before,
            )
            completed_requests = self._fetch_completed_requests(company_id=company_id)
            approved_entries = self._fetch_all_audit(
                company_id=company_id,
                action=AuditAction.STAGE_APPROVED.value,
                created_after=created_after,
                created_before=created_before,
            )
            rejected_entries = self._fetch_all_audit(
                company_id=company_id,
                action=AuditAction.STAGE_REJECTED.value,
                created_after=created_after,
                created_before=created_before,
            )
        except DatabaseError as exc:
            raise MetricCalculationError(f"Failed to compute trends: {exc}") from exc

        scoped_completed = [
            r
            for r in self._scope_requests(
                completed_requests,
                department=department,
                request_type=request_type,
                created_after=created_after,
                created_before=created_before,
            )
            if r.completed_at is not None
        ]

        return TrendReport(
            request_volume=request_volume,
            completion_trend=aggregations.build_time_series(
                [r.completed_at for r in scoped_completed if r.completed_at is not None],
                granularity,
            ),
            approval_trend=aggregations.build_time_series(
                [e.created_at for e in approved_entries], granularity
            ),
            rejection_trend=aggregations.build_time_series(
                [e.created_at for e in rejected_entries], granularity
            ),
            average_completion_time_trend=aggregations.build_average_time_series(
                [
                    (r.completed_at, seconds_between(r.created_at, r.completed_at))
                    for r in scoped_completed
                    if r.completed_at is not None
                ],
                granularity,
            ),
        )

    # ------------------------------------------------------------------
    # 6. Executive KPIs
    # ------------------------------------------------------------------

    @cached_method
    def get_executive_kpis(
        self,
        *,
        company_id: UUID,
        department: str | None = None,
        request_type: str | None = None,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
    ) -> ExecutiveKPIs:
        """Return a company's single-screen executive KPI composite.

        Raises:
            InvalidTimeRangeError: If ``created_after`` is later than
                ``created_before``.
            MetricCalculationError: If any underlying repository query
                fails.
        """
        validate_date_range(created_after, created_before)
        try:
            dashboard = self._analytics_provider.get_dashboard_metrics(
                company_id=company_id,
                department=department,
                request_type=request_type,
                created_after=created_after,
                created_before=created_before,
            )
        except DatabaseError as exc:
            raise MetricCalculationError(f"Failed to compute executive KPIs: {exc}") from exc

        sla = self.get_sla_metrics(
            company_id=company_id,
            department=department,
            request_type=request_type,
            created_after=created_after,
            created_before=created_before,
        )
        period = metrics.period_days(created_after, created_before)

        return ExecutiveKPIs(
            average_approval_seconds=sla.average_approval_duration_seconds,
            average_workflow_completion_seconds=sla.average_total_workflow_duration_seconds,
            sla_compliance_percentage=sla.sla_compliance_percentage,
            active_requests=dashboard.active_requests,
            completed_requests=dashboard.completed_requests,
            pending_approvals=sla.pending_stage_count,
            overdue_approvals=sla.overdue_stage_count,
            rejection_rate=metrics.rejection_rate(
                dashboard.completed_requests, dashboard.rejected_requests
            ),
            throughput_per_day=metrics.workflow_throughput_per_day(
                dashboard.completed_requests, period
            ),
            workflow_efficiency_score=metrics.efficiency_score(
                dashboard.approval_metrics.throughput.completion_rate,
                sla.sla_compliance_percentage,
            ),
        )

    # ------------------------------------------------------------------
    # 7. Department Analytics
    # ------------------------------------------------------------------

    @cached_method
    def get_department_analytics(
        self,
        department: str,
        *,
        company_id: UUID,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
    ) -> DepartmentAnalytics:
        """Return operational figures scoped to a single department.

        Raises:
            InvalidTimeRangeError: If ``created_after`` is later than
                ``created_before``.
            MetricCalculationError: If any underlying repository query
                fails.
        """
        validate_date_range(created_after, created_before)
        try:
            department_metrics = self._analytics_provider.get_department_metrics(
                department,
                company_id=company_id,
                created_after=created_after,
                created_before=created_before,
            )
        except DatabaseError as exc:
            raise MetricCalculationError(f"Failed to compute department analytics: {exc}") from exc

        sla = self.get_sla_metrics(
            company_id=company_id,
            department=department,
            created_after=created_after,
            created_before=created_before,
        )
        period = metrics.period_days(created_after, created_before)
        completed_count = department_metrics.status_breakdown.counts.get(RequestStatus.COMPLETED, 0)

        return DepartmentAnalytics(
            department=department,
            throughput_per_day=metrics.workflow_throughput_per_day(completed_count, period),
            sla_compliance_percentage=sla.sla_compliance_percentage,
            average_approval_seconds=sla.average_approval_duration_seconds,
            active_workload=department_metrics.workload,
            backlog_count=sla.overdue_stage_count,
        )

    # ------------------------------------------------------------------
    # Shared data-loading and computation helpers
    # ------------------------------------------------------------------

    def _fetch_all(
        self, fetch_page: Callable[[Page], PagedResult], *, page_size: int = 100
    ) -> list:
        """Exhaustively fetch every page of a paginated repository query.

        Identical in behavior to ``AnalyticsEngine``'s own private
        helper of the same name (duplicated rather than shared across
        modules purely to avoid a cross-engine coupling for ten lines of
        generic pagination-walking, which carries no business logic of
        its own to duplicate).
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

    def _fetch_all_pending_stages(self, *, company_id: UUID) -> list[WorkflowStageRecord]:
        """Exhaustively fetch every currently pending stage in a company."""
        cutoff = utc_now()
        return self._fetch_all(
            lambda page: self._approval_repo.list_overdue_stages(
                created_before=cutoff, company_id=company_id, page=page
            )
        )

    def _fetch_decided_stages(
        self,
        *,
        company_id: UUID,
        created_after: datetime | None,
        created_before: datetime | None,
    ) -> list[WorkflowStageRecord]:
        """Exhaustively fetch every decided stage in a company, in scope."""
        return self._fetch_all(
            lambda page: self._workflow_stage_repo.list_decided(
                company_id=company_id,
                created_after=created_after,
                created_before=created_before,
                page=page,
            )
        )

    def _fetch_completed_requests(self, *, company_id: UUID) -> list[RequestRecord]:
        """Exhaustively fetch every completed request in a company.

        Unbounded by date (matching ``AnalyticsEngine.get_request_trend``'s
        own existing exhaustive-fetch precedent) since every caller of
        this helper needs to bucket/filter by ``completed_at``, a column
        no repository method can filter on server-side.
        """
        return self._fetch_all(
            lambda page: self._request_repo.list_requests(
                company_id=company_id, status=RequestStatus.COMPLETED, page=page
            )
        )

    def _fetch_all_audit(
        self,
        *,
        company_id: UUID,
        action: str,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
    ) -> list:
        """Exhaustively fetch every audit entry matching an action code, in scope."""
        return self._fetch_all(
            lambda page: self._audit_repo.list_all(
                company_id=company_id,
                action=action,
                created_after=created_after,
                created_before=created_before,
                page=page,
            )
        )

    def _bulk_requests_by_id(
        self, *, company_id: UUID, request_ids: set[UUID]
    ) -> dict[UUID, RequestRecord]:
        """Bulk-resolve a set of request ids to their records, in one exhaustive fetch.

        Uses ``RequestRepository.list_requests``'s existing
        ``request_ids`` filter (already relied on elsewhere for
        approver-scoped visibility) rather than one ``get_by_id`` call
        per id — a single fetch per data source, not the N+1 pattern
        this package's own design brief forbids. ``include_deleted=True``
        so a withdrawn request's historical decided stages still resolve
        correctly for duration analytics.
        """
        if not request_ids:
            return {}
        records: list[RequestRecord] = []
        for batch in _chunked(list(request_ids), _ID_FILTER_BATCH_SIZE):
            records.extend(self._fetch_request_batch(batch, company_id=company_id))
        return {record.id: record for record in records}

    def _fetch_request_batch(
        self, request_ids: list[UUID], *, company_id: UUID
    ) -> list[RequestRecord]:
        """Exhaustively fetch every request matching one id batch."""
        return self._fetch_all(
            lambda page: self._request_repo.list_requests(
                company_id=company_id, request_ids=request_ids, include_deleted=True, page=page
            )
        )

    def _resolve_definitions(
        self, definition_ids: set[UUID], *, company_id: UUID
    ) -> dict[UUID, WorkflowDefinition]:
        """Resolve every distinct workflow definition id in one bulk fetch.

        Uses ``WorkflowDefinitionRepository.list_by_ids`` — a single
        fetch per page, not one ``get_by_id`` call per definition —
        matching this module's own "a single fetch per data source"
        design brief. Bounded by the number of *distinct* definitions
        actually referenced by the stages in scope, typically small (one
        per request type per version in active use).
        """
        if not definition_ids:
            return {}
        records = []
        for batch in _chunked(list(definition_ids), _ID_FILTER_BATCH_SIZE):
            records.extend(self._fetch_definition_batch(batch, company_id=company_id))
        return {record.id: map_workflow_definition_record_to_domain(record) for record in records}

    def _fetch_definition_batch(
        self, definition_ids: list[UUID], *, company_id: UUID
    ) -> list[WorkflowDefinitionRecord]:
        """Exhaustively fetch every workflow definition matching one id batch."""
        return self._fetch_all(
            lambda page: self._workflow_definition_repo.list_by_ids(
                definition_ids, company_id=company_id, page=page
            )
        )

    def _resolve_contexts(
        self, stages: Sequence[WorkflowStageRecord], *, company_id: UUID
    ) -> tuple[dict[UUID, RequestRecord], dict[UUID, WorkflowDefinition]]:
        """Bulk-resolve every stage's owning request and workflow definition."""
        request_ids = {stage.request_id for stage in stages}
        requests_by_id = self._bulk_requests_by_id(company_id=company_id, request_ids=request_ids)
        definition_ids = {r.workflow_definition_id for r in requests_by_id.values()}
        definitions_by_id = self._resolve_definitions(definition_ids, company_id=company_id)
        return requests_by_id, definitions_by_id

    def _find_stage_definition(
        self, definition: WorkflowDefinition | None, stage_order: int
    ) -> StageDefinition | None:
        """Find a stage's own entry within its resolved workflow definition."""
        if definition is None:
            return None
        matching = [s for s in definition.definition.stages if s.order == stage_order]
        return matching[0] if matching else None

    def _effective_sla_hours(
        self,
        stage: WorkflowStageRecord,
        requests_by_id: dict[UUID, RequestRecord],
        definitions_by_id: dict[UUID, WorkflowDefinition],
        *,
        sla_hours_override: float | None,
    ) -> float | None:
        """Resolve the SLA threshold a single stage should be evaluated against."""
        if sla_hours_override is not None:
            return sla_hours_override
        request = requests_by_id.get(stage.request_id)
        definition = definitions_by_id.get(request.workflow_definition_id) if request else None
        stage_def = self._find_stage_definition(definition, stage.stage_order)
        return stage_def.escalation_hours if stage_def else None

    def _build_pending_approval_ages(
        self,
        stages: Sequence[WorkflowStageRecord],
        requests_by_id: dict[UUID, RequestRecord],
        definitions_by_id: dict[UUID, WorkflowDefinition],
        *,
        sla_hours_override: float | None,
        now: datetime,
    ) -> list[PendingApprovalAge]:
        """Build one ``PendingApprovalAge`` per pending stage with a resolvable request."""
        results: list[PendingApprovalAge] = []
        for stage in stages:
            request = requests_by_id.get(stage.request_id)
            if request is None:
                continue
            effective_sla = self._effective_sla_hours(
                stage, requests_by_id, definitions_by_id, sla_hours_override=sla_hours_override
            )
            is_overdue = (
                effective_sla is not None
                and self._workflow_engine.is_stage_escalation_eligible(
                    stage.created_at, effective_sla, now=now
                )
            )
            results.append(
                PendingApprovalAge(
                    stage_id=stage.id,
                    request_id=stage.request_id,
                    request_title=request.title,
                    request_type=request.request_type,
                    department=request.department,
                    stage_name=stage.stage_name,
                    stage_order=stage.stage_order,
                    assigned_to=stage.assigned_to,
                    assigned_role=stage.assigned_role,
                    created_at=stage.created_at,
                    age_hours=seconds_between(stage.created_at, now) / 3600.0,
                    sla_hours=effective_sla,
                    is_overdue=is_overdue,
                )
            )
        return results

    def _filter_pending_scope(
        self,
        items: Sequence[PendingApprovalAge],
        *,
        department: str | None,
        request_type: str | None,
    ) -> list[PendingApprovalAge]:
        """Apply an optional department/request_type filter to a pending-age list."""
        result = list(items)
        if department is not None:
            result = [p for p in result if p.department == department]
        if request_type is not None:
            result = [p for p in result if p.request_type == request_type]
        return result

    def _filter_decided_scope(
        self,
        stages: Sequence[WorkflowStageRecord],
        requests_by_id: dict[UUID, RequestRecord],
        *,
        department: str | None,
        request_type: str | None,
    ) -> list[WorkflowStageRecord]:
        """Apply an optional department/request_type filter to a decided-stage list."""
        result = []
        for stage in stages:
            request = requests_by_id.get(stage.request_id)
            if request is None:
                continue
            if department is not None and request.department != department:
                continue
            if request_type is not None and request.request_type != request_type:
                continue
            result.append(stage)
        return result

    def _scope_requests(
        self,
        requests: Sequence[RequestRecord],
        *,
        department: str | None,
        request_type: str | None,
        created_after: datetime | None,
        created_before: datetime | None,
    ) -> list[RequestRecord]:
        """Apply the standard department/request_type/date-range filter set to requests."""
        result = list(requests)
        if department is not None:
            result = [r for r in result if r.department == department]
        if request_type is not None:
            result = [r for r in result if r.request_type == request_type]
        if created_after is not None:
            result = [r for r in result if r.created_at >= created_after]
        if created_before is not None:
            result = [r for r in result if r.created_at <= created_before]
        return result

    def _duration_buckets(
        self,
        stages: Sequence[WorkflowStageRecord],
        *,
        key_fn: Callable[[WorkflowStageRecord], str],
    ) -> tuple[DurationBucket, ...]:
        """Group decided stages by an arbitrary key, averaging decision duration per group.

        Buckets are returned slowest-average-first, matching every
        "slowest X" / "X causing delay" dataset this module produces.
        """
        grouped: dict[str, list[float]] = {}
        for stage in stages:
            if stage.decided_at is None:
                continue
            grouped.setdefault(key_fn(stage), []).append(
                seconds_between(stage.created_at, stage.decided_at)
            )
        buckets = [
            DurationBucket(
                key=key, average_seconds=metrics.average(durations), count=len(durations)
            )
            for key, durations in grouped.items()
        ]
        buckets.sort(key=lambda b: (b.average_seconds is None, -(b.average_seconds or 0.0)))
        return tuple(buckets)
