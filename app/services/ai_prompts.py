"""Pure prompt-construction and non-AI fallback-text helpers for ``AiInsightService``.

Every function here is a pure, I/O-free string builder: given already-fetched
domain data, produce either a ``(system_prompt, user_prompt)`` pair to send
to an ``app.ai.interfaces.AiProvider``, or a deterministic, non-AI fallback
string built from the same data. Kept separate from
``app.services.ai_insight_service.AiInsightService`` so prompt wording can be
unit-tested in isolation from provider/service orchestration, and so that
module stays focused on authorization, data-gathering, caching, and fallback
selection rather than string templating.
"""

from __future__ import annotations

from collections.abc import Sequence

from app.analytics.dto import AnalyticsSummary
from app.analytics.operational_dto import (
    ApprovalDelayReport,
    BottleneckReport,
    ExecutiveKPIs,
    SLAMetrics,
)
from app.models.comment import Comment
from app.models.request import Request
from app.models.workflow import WorkflowDefinition
from app.services.request_service import WorkflowProgress

__all__ = [
    "build_request_summary_prompt",
    "build_request_summary_fallback",
    "build_approval_summary_prompt",
    "build_approval_summary_fallback",
    "build_workflow_improvements_prompt",
    "build_workflow_improvements_fallback",
    "build_bottleneck_explanation_prompt",
    "build_bottleneck_explanation_fallback",
    "build_policy_recommendation_prompt",
    "build_policy_recommendation_fallback",
    "build_operational_insights_prompt",
    "build_operational_insights_fallback",
    "build_executive_summary_prompt",
    "build_assistant_prompt",
    "ASSISTANT_UNAVAILABLE_FALLBACK",
]

#: The text substituted for any figure that is ``None`` (unavailable) when
#: building fallback text — matches
#: ``app.analytics.reporting._UNAVAILABLE``'s identical convention.
_UNAVAILABLE = "unavailable"

#: The fixed message returned when the AI assistant cannot answer a
#: free-form question — unlike every other fallback here, no deterministic
#: answer to arbitrary user text is possible, so this is a plain,
#: honestly-labeled unavailability notice rather than a computed summary.
ASSISTANT_UNAVAILABLE_FALLBACK = (
    "The AI assistant is currently unavailable. Please try again later, or "
    "explore the Analytics page directly for the same underlying figures."
)

_ASSISTANT_MAX_HISTORY_TURNS = 6
_ASSISTANT_MAX_HISTORY_CHARS = 2000


def _fmt(value: float | int | None, *, suffix: str = "") -> str:
    """Format an optional numeric value for inclusion in prompt/fallback text."""
    if value is None:
        return _UNAVAILABLE
    if isinstance(value, float):
        return f"{value:.1f}{suffix}"
    return f"{value}{suffix}"


def _fmt_percent(value: float | None) -> str:
    """Format an optional 0-1 fraction as a percentage string."""
    if value is None:
        return _UNAVAILABLE
    return f"{value:.1%}"


_SUMMARY_SYSTEM_PROMPT = (
    "You are an assistant embedded in an enterprise approval-workflow "
    "platform. Write concise, factual summaries (3-5 sentences) strictly "
    "from the data provided. Never invent facts, figures, or names not "
    "present in the input. Do not add a greeting or sign-off."
)

_RECOMMENDATION_SYSTEM_PROMPT = (
    "You are an assistant embedded in an enterprise approval-workflow "
    "platform. Given operational metrics, write concise, actionable "
    "recommendations (3-6 bullet points) strictly grounded in the figures "
    "provided. Never invent facts or figures not present in the input. Do "
    "not add a greeting or sign-off."
)


def _format_comments(comments: list[Comment], *, limit: int = 10) -> str:
    if not comments:
        return "No comments."
    lines = [f"- {comment.body}" for comment in comments[-limit:] if not comment.is_deleted]
    return "\n".join(lines) if lines else "No comments."


def build_request_summary_prompt(request: Request, comments: list[Comment]) -> tuple[str, str]:
    """Build the prompt pair for ``AiInsightService.summarize_request``."""
    user_prompt = (
        f"Request title: {request.title}\n"
        f"Type: {request.request_type}\n"
        f"Status: {request.status.value}\n"
        f"Department: {request.department or 'unspecified'}\n"
        f"Description: {request.description or 'none provided'}\n\n"
        f"Recent comments:\n{_format_comments(comments)}\n\n"
        "Summarize this request for someone who has not read it yet: what "
        "it's for, its current state, and anything notable from the "
        "comments."
    )
    return _SUMMARY_SYSTEM_PROMPT, user_prompt


def build_request_summary_fallback(request: Request, comments: list[Comment]) -> str:
    """Build the deterministic fallback for ``AiInsightService.summarize_request``."""
    active_comments = [c for c in comments if not c.is_deleted]
    return (
        f"'{request.title}' ({request.request_type.replace('_', ' ')}), "
        f"currently {request.status.value.replace('_', ' ')}. "
        f"{len(active_comments)} comment(s) on this request."
    )


def build_approval_summary_prompt(
    request: Request, progress: WorkflowProgress, comments: list[Comment]
) -> tuple[str, str]:
    """Build the prompt pair for ``AiInsightService.summarize_approval``."""
    stage_lines = "\n".join(
        f"- Stage {s.stage_order} ({s.stage_name}): {s.status.value}"
        + (f", decided by {s.decided_by_name}" if s.decided_by_name else "")
        + (f' — note: "{s.decision_note}"' if s.decision_note else "")
        for s in progress.stages
    )
    user_prompt = (
        f"Request title: {request.title}\n"
        f"Type: {request.request_type}\n"
        f"Department: {request.department or 'unspecified'}\n"
        f"Description: {request.description or 'none provided'}\n\n"
        f"Workflow progress (stage {progress.current_stage_order} of "
        f"{progress.total_stages}):\n{stage_lines or 'No stages recorded yet.'}\n\n"
        f"Recent comments:\n{_format_comments(comments)}\n\n"
        "Summarize what an approver needs to know to decide on this "
        "request: what it's for, prior decisions and notes in this "
        "workflow, and anything notable from the comments."
    )
    return _SUMMARY_SYSTEM_PROMPT, user_prompt


def build_approval_summary_fallback(
    request: Request, progress: WorkflowProgress, comments: list[Comment]
) -> str:
    """Build the deterministic fallback for ``AiInsightService.summarize_approval``."""
    active_comments = [c for c in comments if not c.is_deleted]
    return (
        f"'{request.title}' ({request.request_type.replace('_', ' ')}) is at "
        f"stage {progress.current_stage_order} of {progress.total_stages}. "
        f"{len(active_comments)} comment(s) on this request."
    )


def build_workflow_improvements_prompt(
    definition: WorkflowDefinition, bottlenecks: BottleneckReport, delays: ApprovalDelayReport
) -> tuple[str, str]:
    """Build the prompt pair for ``AiInsightService.suggest_workflow_improvements``."""
    stage_lines = "\n".join(
        f"- Stage {s.order} ({s.name}): assignment={s.assignment_strategy.value}, "
        f"escalation_hours={s.escalation_hours}"
        for s in definition.definition.ordered_stages()
    )
    duration_lines = "\n".join(
        f"- {b.key}: avg {_fmt(b.average_seconds, suffix='s')} over {b.count} decision(s)"
        for b in bottlenecks.slowest_stages
    ) or "No decided stages yet."
    user_prompt = (
        f"Workflow '{definition.request_type}' (version {definition.version}), "
        f"{len(definition.definition.stages)} stage(s):\n{stage_lines}\n\n"
        f"Slowest stages company-wide (may include other workflows):\n{duration_lines}\n\n"
        f"Average approval duration for this workflow type: "
        f"{_fmt(next((b.average_seconds for b in delays.duration_by_workflow if b.key == definition.request_type), None), suffix='s')}\n\n"
        "Suggest concrete improvements to this workflow's stage structure "
        "or configuration (e.g. escalation thresholds, parallelization, "
        "reassignment) that would reduce delay, grounded only in the data "
        "above."
    )
    return _RECOMMENDATION_SYSTEM_PROMPT, user_prompt


def build_workflow_improvements_fallback(
    definition: WorkflowDefinition, bottlenecks: BottleneckReport
) -> str:
    """Build the deterministic fallback for ``AiInsightService.suggest_workflow_improvements``."""
    matching = [b for b in bottlenecks.slowest_stages if b.average_seconds is not None][:3]
    if not matching:
        return (
            f"Workflow '{definition.request_type}' has {len(definition.definition.stages)} "
            "stage(s). No decided-stage duration data is available yet."
        )
    lines = "; ".join(f"{b.key}: avg {_fmt(b.average_seconds, suffix='s')}" for b in matching)
    return f"Slowest stages company-wide: {lines}."


def build_bottleneck_explanation_prompt(
    bottlenecks: BottleneckReport, delays: ApprovalDelayReport
) -> tuple[str, str]:
    """Build the prompt pair for ``AiInsightService.explain_bottlenecks``."""
    user_prompt = (
        "Slowest stages (by average decision duration):\n"
        + "\n".join(f"- {b.key}: {_fmt(b.average_seconds, suffix='s')}" for b in bottlenecks.slowest_stages)
        + "\n\nDepartments causing delay:\n"
        + "\n".join(f"- {b.key}: {_fmt(b.average_seconds, suffix='s')}" for b in bottlenecks.departments_causing_delay)
        + "\n\nFrequently overdue stages:\n"
        + "\n".join(f"- {b.key}: {b.count} currently overdue" for b in bottlenecks.frequently_overdue_stages)
        + "\n\nLongest-pending stages right now:\n"
        + "\n".join(
            f"- {p.stage_name} on '{p.request_title}': pending {p.age_hours:.1f}h"
            for p in delays.longest_pending[:5]
        )
        + "\n\nExplain, in plain language, why these are the current bottlenecks "
        "and what is causing the delay, grounded only in the data above."
    )
    return _RECOMMENDATION_SYSTEM_PROMPT, user_prompt


def build_bottleneck_explanation_fallback(
    bottlenecks: BottleneckReport, delays: ApprovalDelayReport
) -> str:
    """Build the deterministic fallback for ``AiInsightService.explain_bottlenecks``."""
    slowest = bottlenecks.slowest_stages[0] if bottlenecks.slowest_stages else None
    longest = delays.longest_pending[0] if delays.longest_pending else None
    parts = []
    if slowest is not None:
        parts.append(f"Slowest stage: '{slowest.key}' (avg {_fmt(slowest.average_seconds, suffix='s')})")
    if longest is not None:
        parts.append(f"Longest currently pending: '{longest.stage_name}' ({longest.age_hours:.1f}h)")
    return "; ".join(parts) + "." if parts else "No bottleneck data available yet."


def build_policy_recommendation_prompt(
    bottlenecks: BottleneckReport, delays: ApprovalDelayReport, sla: SLAMetrics
) -> tuple[str, str]:
    """Build the prompt pair for ``AiInsightService.recommend_policies``."""
    user_prompt = (
        f"SLA compliance: {_fmt_percent(sla.sla_compliance_percentage)} "
        f"({sla.sla_breaches_decided} breach(es) of {sla.decided_stage_count} decided)\n"
        f"Currently overdue: {sla.overdue_stage_count} stage(s) across "
        f"{sla.overdue_request_count} request(s)\n\n"
        "Rejection hotspots:\n"
        + "\n".join(
            f"- {r.key}: {_fmt_percent(r.rejection_rate)} rejection rate "
            f"({r.rejected_count}/{r.decided_count})"
            for r in bottlenecks.rejection_hotspots
        )
        + "\n\nDepartments causing delay:\n"
        + "\n".join(f"- {b.key}: {_fmt(b.average_seconds, suffix='s')}" for b in bottlenecks.departments_causing_delay)
        + "\n\nRecommend concrete approval-policy changes (e.g. SLA "
        "thresholds, added review steps, escalation rules) that would "
        "address the patterns above, grounded only in the data given."
    )
    return _RECOMMENDATION_SYSTEM_PROMPT, user_prompt


def build_policy_recommendation_fallback(
    bottlenecks: BottleneckReport, delays: ApprovalDelayReport
) -> str:
    """Build the deterministic fallback for ``AiInsightService.recommend_policies``."""
    del delays  # Not used by this fallback's summary — kept for signature symmetry.
    hotspot = next((r for r in bottlenecks.rejection_hotspots if r.rejection_rate), None)
    if hotspot is None:
        return "No rejection-hotspot data available yet."
    return (
        f"Highest rejection rate: '{hotspot.key}' at {_fmt_percent(hotspot.rejection_rate)} "
        f"({hotspot.rejected_count}/{hotspot.decided_count})."
    )


def build_operational_insights_prompt(
    bottlenecks: BottleneckReport,
    delays: ApprovalDelayReport,
    sla: SLAMetrics,
    kpis: ExecutiveKPIs,
) -> tuple[str, str]:
    """Build the prompt pair for ``AiInsightService.generate_operational_insights``."""
    user_prompt = (
        f"Active requests: {kpis.active_requests}; completed: {kpis.completed_requests}\n"
        f"Pending approvals: {kpis.pending_approvals}; overdue: {kpis.overdue_approvals}\n"
        f"Rejection rate: {_fmt_percent(kpis.rejection_rate)}\n"
        f"Throughput/day: {_fmt(kpis.throughput_per_day)}\n"
        f"Workflow efficiency score: {_fmt(kpis.workflow_efficiency_score)}\n"
        f"SLA compliance: {_fmt_percent(sla.sla_compliance_percentage)}\n\n"
        "Slowest stages:\n"
        + "\n".join(f"- {b.key}: {_fmt(b.average_seconds, suffix='s')}" for b in bottlenecks.slowest_stages)
        + "\n\nLongest-pending requests right now:\n"
        + "\n".join(
            f"- '{p.request_title}': pending {p.age_hours:.1f}h" for p in delays.oldest_pending_requests[:5]
        )
        + "\n\nWrite a short operational insights briefing: what's going "
        "well, what needs attention, grounded only in the data above."
    )
    return _RECOMMENDATION_SYSTEM_PROMPT, user_prompt


def build_operational_insights_fallback(
    bottlenecks: BottleneckReport,
    delays: ApprovalDelayReport,
    sla: SLAMetrics,
    kpis: ExecutiveKPIs,
) -> str:
    """Build the deterministic fallback for ``AiInsightService.generate_operational_insights``."""
    del bottlenecks, delays  # Not used by this fallback's summary — signature symmetry.
    return (
        f"{kpis.active_requests} active request(s), {kpis.pending_approvals} pending "
        f"approval(s) ({kpis.overdue_approvals} overdue). "
        f"SLA compliance: {_fmt_percent(sla.sla_compliance_percentage)}."
    )


def build_executive_summary_prompt(summary: AnalyticsSummary) -> tuple[str, str]:
    """Build the prompt pair for ``AiInsightService.generate_executive_summary``.

    ``summary.narrative`` (already a plain-language sentence built by
    ``app.analytics.reporting.ReportingEngine``) is *also* this feature's
    non-AI fallback — see ``AiInsightService.generate_executive_summary``,
    which uses it directly rather than calling a separate fallback builder
    here.
    """
    dashboard = summary.dashboard
    user_prompt = (
        f"{summary.narrative}\n\n"
        f"Total requests: {dashboard.total_requests if dashboard else _UNAVAILABLE}\n"
        f"Active: {dashboard.active_requests if dashboard else _UNAVAILABLE}\n"
        f"Completed: {dashboard.completed_requests if dashboard else _UNAVAILABLE}\n"
        f"Rejected: {dashboard.rejected_requests if dashboard else _UNAVAILABLE}\n\n"
        "Write a short executive summary (3-5 sentences) of this period's "
        "activity, grounded only in the figures above."
    )
    return _SUMMARY_SYSTEM_PROMPT, user_prompt


def _format_history(history: Sequence[tuple[str, str]]) -> str:
    if not history:
        return "No prior turns in this conversation."
    trimmed = history[-_ASSISTANT_MAX_HISTORY_TURNS:]
    lines = [f"{role}: {content}" for role, content in trimmed]
    joined = "\n".join(lines)
    return joined[-_ASSISTANT_MAX_HISTORY_CHARS:]


def build_assistant_prompt(
    question: str,
    history: Sequence[tuple[str, str]],
    *,
    open_requests: int,
    pending_approvals: int,
    unread_notifications: int,
    kpis: ExecutiveKPIs | None,
) -> tuple[str, str]:
    """Build the prompt pair for ``AiInsightService.ask_assistant``.

    Grounded in a snapshot of the caller's own already-authorized dashboard
    figures — never a live database query the model itself constructs (see
    ``AiInsightService``'s module docstring for why this assistant is
    deliberately non-agentic).
    """
    kpi_block = (
        f"Active requests: {kpis.active_requests}; completed: {kpis.completed_requests}\n"
        f"Company-wide pending approvals: {kpis.pending_approvals}; "
        f"of which overdue: {kpis.overdue_approvals}\n"
        f"Rejection rate: {_fmt_percent(kpis.rejection_rate)}\n"
        f"SLA compliance: {_fmt_percent(kpis.sla_compliance_percentage)}\n"
        if kpis is not None
        else "Company-wide operational figures are not available to this caller.\n"
    )
    user_prompt = (
        f"Your open requests: {open_requests}\n"
        f"Your pending approvals: {pending_approvals}\n"
        f"Your unread notifications: {unread_notifications}\n"
        f"{kpi_block}\n"
        f"Conversation so far:\n{_format_history(history)}\n\n"
        f"Question: {question}"
    )
    system_prompt = (
        "You are a dashboard assistant embedded in an enterprise "
        "approval-workflow platform. Answer the user's question strictly "
        "from the dashboard figures and conversation history provided. If "
        "the figures don't contain what's needed to answer, say so plainly "
        "rather than guessing. Do not claim to have run a query — you were "
        "given a fixed snapshot of figures, not live database access."
    )
    return system_prompt, user_prompt
