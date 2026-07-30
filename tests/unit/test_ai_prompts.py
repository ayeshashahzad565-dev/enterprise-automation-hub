"""Unit tests for the pure formatting/truncation logic in ``app.services.ai_prompts``.

Most prompt-builder functions here are exercised end-to-end (real domain
data flowing through real service methods) by
``tests/unit/test_ai_insight_service.py``, which asserts on the exact
prompts a ``FakeAiProvider`` receives — a more realistic check than hand-
building every DTO in isolation. This file covers only the handful of pure
formatting edge cases (``None``-handling, history truncation) that are easy
to construct directly and worth isolating.
"""

from __future__ import annotations

import pytest

from app.analytics.operational_dto import ExecutiveKPIs
from app.services import ai_prompts

pytestmark = pytest.mark.unit


def _kpis(**overrides: object) -> ExecutiveKPIs:
    defaults = {
        "average_approval_seconds": 3600.0,
        "average_workflow_completion_seconds": 7200.0,
        "sla_compliance_percentage": 0.95,
        "active_requests": 4,
        "completed_requests": 10,
        "pending_approvals": 2,
        "overdue_approvals": 1,
        "rejection_rate": 0.1,
        "throughput_per_day": 2.5,
        "workflow_efficiency_score": 0.8,
    }
    defaults.update(overrides)
    return ExecutiveKPIs(**defaults)  # type: ignore[arg-type]


class TestFmtHelpers:
    def test_none_values_render_as_unavailable(self) -> None:
        assert ai_prompts._fmt(None) == "unavailable"
        assert ai_prompts._fmt_percent(None) == "unavailable"

    def test_percent_formats_as_percentage(self) -> None:
        assert ai_prompts._fmt_percent(0.5) == "50.0%"

    def test_int_value_has_no_decimal_point(self) -> None:
        assert ai_prompts._fmt(5) == "5"

    def test_float_value_has_one_decimal_place(self) -> None:
        assert ai_prompts._fmt(5.0, suffix="s") == "5.0s"


class TestBuildAssistantPrompt:
    def test_includes_dashboard_snapshot_and_question(self) -> None:
        system_prompt, user_prompt = ai_prompts.build_assistant_prompt(
            "How many requests are open?",
            [],
            open_requests=3,
            pending_approvals=1,
            unread_notifications=2,
            kpis=_kpis(),
        )
        assert "Your open requests: 3" in user_prompt
        assert "Your pending approvals: 1" in user_prompt
        assert "How many requests are open?" in user_prompt
        assert "not run" not in system_prompt  # sanity: no accidental wording collision
        assert "live database access" in system_prompt

    def test_includes_company_wide_pending_and_overdue_approvals(self) -> None:
        """A caller asking "how many approvals are overdue?" previously
        got told the figures didn't cover that, even though
        ExecutiveKPIs.overdue_approvals was already being computed — it
        just wasn't included in this prompt. Guards against the same
        field silently dropping out of the grounding context again."""
        _, user_prompt = ai_prompts.build_assistant_prompt(
            "How many approvals are overdue?",
            [],
            open_requests=0,
            pending_approvals=0,
            unread_notifications=0,
            kpis=_kpis(pending_approvals=7, overdue_approvals=3),
        )
        assert "Company-wide pending approvals: 7" in user_prompt
        assert "overdue: 3" in user_prompt

    def test_none_kpis_notes_figures_unavailable(self) -> None:
        _, user_prompt = ai_prompts.build_assistant_prompt(
            "question", [], open_requests=0, pending_approvals=0, unread_notifications=0, kpis=None
        )
        assert "not available to this caller" in user_prompt

    def test_history_is_included_in_order(self) -> None:
        history = [("user", "first question"), ("assistant", "first answer")]
        _, user_prompt = ai_prompts.build_assistant_prompt(
            "second question",
            history,
            open_requests=0,
            pending_approvals=0,
            unread_notifications=0,
            kpis=None,
        )
        assert user_prompt.index("first question") < user_prompt.index("first answer")
        assert "first answer" in user_prompt

    def test_history_is_truncated_to_recent_turns(self) -> None:
        history = [("user", f"turn {i}") for i in range(20)]
        _, user_prompt = ai_prompts.build_assistant_prompt(
            "latest",
            history,
            open_requests=0,
            pending_approvals=0,
            unread_notifications=0,
            kpis=None,
        )
        assert "turn 0" not in user_prompt
        assert "turn 19" in user_prompt

    def test_empty_history_says_no_prior_turns(self) -> None:
        _, user_prompt = ai_prompts.build_assistant_prompt(
            "q", [], open_requests=0, pending_approvals=0, unread_notifications=0, kpis=None
        )
        assert "No prior turns" in user_prompt


def test_assistant_unavailable_fallback_is_a_plain_unavailability_notice() -> None:
    assert "unavailable" in ai_prompts.ASSISTANT_UNAVAILABLE_FALLBACK.lower()
