"""Unit tests for ``app.services.ai_insight_service.AiInsightService``.

Every test exercises the real, unmodified ``AiInsightService`` end-to-end
against ``tests/conftest.py``'s ``env`` fixture's in-memory fakes — the same
pattern ``test_operational_analytics_engine.py`` already established for the
Analytics Layer's engines this service composes — with a ``FakeAiProvider``
standing in for the external AI call. Because ``DashboardService``/
``OperationalAnalyticsEngine``/``ReportingEngine`` are not part of the
shared ``env`` fixture (most unit test files have no use for them),
``_build_ai_insight_service`` below constructs them locally, mirroring
``test_operational_analytics_engine.py``'s own ``_build_engine`` helper.
"""

from __future__ import annotations

import pytest

from app.analytics.analytics_engine import AnalyticsEngine
from app.analytics.operational_engine import OperationalAnalyticsEngine
from app.analytics.reporting import ReportingEngine
from app.models.enums import UserRole
from app.services.ai_insight_service import AiInsightService
from app.services.analytics_service import AnalyticsService as ServicesAnalyticsService
from app.services.dashboard_service import DashboardService
from app.services.exceptions import NotFoundError, PermissionDeniedError
from tests.conftest import Env
from tests.fixtures.factories import specific_user_stage
from tests.fixtures.fakes import FakeAiProvider, FakeAnalyticsRepository

pytestmark = pytest.mark.unit


def _build_ai_insight_service(env: Env, *, ai_provider: FakeAiProvider | None = None) -> AiInsightService:
    analytics_repo = FakeAnalyticsRepository(env.request_repo, env.stages_table)
    analytics_engine = AnalyticsEngine(
        analytics_repo=analytics_repo,
        request_repo=env.request_repo,
        approval_repo=env.approval_repo,
        workflow_stage_repo=env.workflow_stage_repo,
        profile_repo=env.profile_repo,
        audit_repo=env.audit_repo,
        notification_repo=env.notification_repo,
    )
    operational_engine = OperationalAnalyticsEngine(
        analytics_provider=analytics_engine,
        analytics_repo=analytics_repo,
        request_repo=env.request_repo,
        workflow_stage_repo=env.workflow_stage_repo,
        approval_repo=env.approval_repo,
        workflow_definition_repo=env.workflow_definition_repo,
        audit_repo=env.audit_repo,
        workflow_engine=env.workflow_engine,
    )
    reporting_engine = ReportingEngine(analytics_provider=analytics_engine)
    dashboard_service = DashboardService(
        request_service=env.request_service,
        approval_service=env.approval_service,
        notification_service=env.notification_service,
        analytics_service=ServicesAnalyticsService(analytics_repo=analytics_repo),
    )
    return AiInsightService(
        request_service=env.request_service,
        comment_service=env.comment_service,
        workflow_definition_service=env.workflow_definition_service,
        operational_engine=operational_engine,
        reporting_engine=reporting_engine,
        dashboard_service=dashboard_service,
        ai_provider=ai_provider,
    )


def _create_request(env: Env, requester_identity, *, request_type: str, title: str = "Laptop purchase"):
    return env.request_service.create_request(
        requester_identity, request_type=request_type, title=title, description="A new laptop."
    )


class TestSummarizeRequest:
    def test_happy_path_returns_ai_text(self, env: Env, employee, approver, make_definition) -> None:
        _, employee_identity = employee
        _, approver_identity = approver
        make_definition(
            request_type="equipment",
            stages=[specific_user_stage(1, "Manager Review", user_id=approver_identity.user_id)],
        )
        request = _create_request(env, employee_identity, request_type="equipment")
        provider = FakeAiProvider(response_text="This request is for a laptop.")
        service = _build_ai_insight_service(env, ai_provider=provider)

        insight = service.summarize_request(employee_identity, request.id)

        assert insight.text == "This request is for a laptop."
        assert insight.generated_by == "fake:fake-model"
        assert insight.is_fallback is False
        assert insight.cached is False
        assert len(provider.sent) == 1
        assert "Laptop purchase" in provider.sent[0].user_prompt

    def test_no_provider_returns_deterministic_fallback(
        self, env: Env, employee, approver, make_definition
    ) -> None:
        _, employee_identity = employee
        _, approver_identity = approver
        make_definition(
            request_type="equipment",
            stages=[specific_user_stage(1, "Manager Review", user_id=approver_identity.user_id)],
        )
        request = _create_request(env, employee_identity, request_type="equipment")
        service = _build_ai_insight_service(env, ai_provider=None)

        insight = service.summarize_request(employee_identity, request.id)

        assert insight.is_fallback is True
        assert insight.generated_by is None
        assert "Laptop purchase" in insight.text

    def test_provider_failure_falls_back_gracefully(
        self, env: Env, employee, approver, make_definition
    ) -> None:
        _, employee_identity = employee
        _, approver_identity = approver
        make_definition(
            request_type="equipment",
            stages=[specific_user_stage(1, "Manager Review", user_id=approver_identity.user_id)],
        )
        request = _create_request(env, employee_identity, request_type="equipment")
        provider = FakeAiProvider(raise_exception=True)
        service = _build_ai_insight_service(env, ai_provider=provider)

        insight = service.summarize_request(employee_identity, request.id)

        assert insight.is_fallback is True
        assert "Laptop purchase" in insight.text

    def test_out_of_scope_request_is_not_found(
        self, env: Env, employee, second_approver, make_definition, make_user
    ) -> None:
        _, employee_identity = employee
        _, other_identity = second_approver
        make_definition(
            request_type="equipment", stages=[specific_user_stage(1, "Review", user_id=other_identity.user_id)]
        )
        request = _create_request(env, employee_identity, request_type="equipment")
        service = _build_ai_insight_service(env, ai_provider=FakeAiProvider())

        _, unrelated_identity = make_user(role=UserRole.EMPLOYEE, full_name="Unrelated Bystander")

        with pytest.raises(NotFoundError):
            service.summarize_request(unrelated_identity, request.id)

    def test_result_is_cached_on_second_call(
        self, env: Env, employee, approver, make_definition
    ) -> None:
        _, employee_identity = employee
        _, approver_identity = approver
        make_definition(
            request_type="equipment",
            stages=[specific_user_stage(1, "Manager Review", user_id=approver_identity.user_id)],
        )
        request = _create_request(env, employee_identity, request_type="equipment")
        provider = FakeAiProvider()
        service = _build_ai_insight_service(env, ai_provider=provider)

        first = service.summarize_request(employee_identity, request.id)
        second = service.summarize_request(employee_identity, request.id)

        assert first.cached is False
        assert second.cached is True
        assert len(provider.sent) == 1


class TestSummarizeApproval:
    def test_happy_path_includes_workflow_progress(
        self, env: Env, employee, approver, make_definition
    ) -> None:
        _, employee_identity = employee
        _, approver_identity = approver
        make_definition(
            request_type="equipment",
            stages=[specific_user_stage(1, "Manager Review", user_id=approver_identity.user_id)],
        )
        request = _create_request(env, employee_identity, request_type="equipment")
        provider = FakeAiProvider(response_text="Approve if budget allows.")
        service = _build_ai_insight_service(env, ai_provider=provider)

        insight = service.summarize_approval(approver_identity, request.id)

        assert insight.text == "Approve if budget allows."
        assert "Manager Review" in provider.sent[0].user_prompt
        assert "stage 1 of 1" in provider.sent[0].user_prompt


class TestSuggestWorkflowImprovements:
    def test_employee_is_denied(self, env: Env, employee) -> None:
        _, employee_identity = employee
        service = _build_ai_insight_service(env, ai_provider=FakeAiProvider())
        with pytest.raises(PermissionDeniedError):
            service.suggest_workflow_improvements(employee_identity, "equipment")

    def test_approver_is_denied(self, env: Env, approver) -> None:
        _, approver_identity = approver
        service = _build_ai_insight_service(env, ai_provider=FakeAiProvider())
        with pytest.raises(PermissionDeniedError):
            service.suggest_workflow_improvements(approver_identity, "equipment")

    def test_unknown_request_type_is_not_found(self, env: Env, admin) -> None:
        _, admin_identity = admin
        service = _build_ai_insight_service(env, ai_provider=FakeAiProvider())
        with pytest.raises(NotFoundError):
            service.suggest_workflow_improvements(admin_identity, "no-such-type")

    def test_admin_succeeds(self, env: Env, admin, approver, make_definition) -> None:
        _, admin_identity = admin
        _, approver_identity = approver
        make_definition(
            request_type="equipment",
            stages=[specific_user_stage(1, "Manager Review", user_id=approver_identity.user_id)],
        )
        provider = FakeAiProvider(response_text="Add a parallel review stage.")
        service = _build_ai_insight_service(env, ai_provider=provider)

        insight = service.suggest_workflow_improvements(admin_identity, "equipment")

        assert insight.text == "Add a parallel review stage."
        assert "equipment" in provider.sent[0].user_prompt


class TestOperationalInsightFamily:
    """``explain_bottlenecks``/``recommend_policies``/``generate_operational_insights``
    share the same authorization gate and data shape — tested together."""

    @pytest.mark.parametrize(
        "method_name",
        ["explain_bottlenecks", "recommend_policies", "generate_operational_insights", "generate_executive_summary"],
    )
    def test_employee_is_denied(self, env: Env, employee, method_name: str) -> None:
        _, employee_identity = employee
        service = _build_ai_insight_service(env, ai_provider=FakeAiProvider())
        with pytest.raises(PermissionDeniedError):
            getattr(service, method_name)(employee_identity)

    @pytest.mark.parametrize(
        "method_name",
        ["explain_bottlenecks", "recommend_policies", "generate_operational_insights"],
    )
    def test_approver_can_call_and_receives_ai_text(self, env: Env, approver, method_name: str) -> None:
        _, approver_identity = approver
        provider = FakeAiProvider(response_text="Insight text.")
        service = _build_ai_insight_service(env, ai_provider=provider)

        insight = getattr(service, method_name)(approver_identity)

        assert insight.text == "Insight text."
        assert insight.is_fallback is False

    @pytest.mark.parametrize(
        "method_name",
        ["explain_bottlenecks", "recommend_policies", "generate_operational_insights"],
    )
    def test_result_is_cached_on_second_call(self, env: Env, approver, method_name: str) -> None:
        _, approver_identity = approver
        provider = FakeAiProvider()
        service = _build_ai_insight_service(env, ai_provider=provider)

        first = getattr(service, method_name)(approver_identity)
        second = getattr(service, method_name)(approver_identity)

        assert first.cached is False
        assert second.cached is True
        assert len(provider.sent) == 1


class TestGenerateExecutiveSummary:
    def test_fallback_uses_reporting_engine_narrative_verbatim(self, env: Env, approver) -> None:
        _, approver_identity = approver
        service = _build_ai_insight_service(env, ai_provider=None)

        insight = service.generate_executive_summary(approver_identity)

        assert insight.is_fallback is True
        assert "total request(s)" in insight.text

    def test_ai_success_uses_provider_text(self, env: Env, approver) -> None:
        _, approver_identity = approver
        provider = FakeAiProvider(response_text="This quarter was strong.")
        service = _build_ai_insight_service(env, ai_provider=provider)

        insight = service.generate_executive_summary(approver_identity)

        assert insight.text == "This quarter was strong."
        assert insight.is_fallback is False


class TestAskAssistant:
    def test_employee_is_denied(self, env: Env, employee) -> None:
        _, employee_identity = employee
        service = _build_ai_insight_service(env, ai_provider=FakeAiProvider())
        with pytest.raises(PermissionDeniedError):
            service.ask_assistant(employee_identity, "How many requests are open?")

    def test_approver_receives_grounded_answer(self, env: Env, approver) -> None:
        _, approver_identity = approver
        provider = FakeAiProvider(response_text="You have 0 open requests.")
        service = _build_ai_insight_service(env, ai_provider=provider)

        insight = service.ask_assistant(approver_identity, "How many requests are open?")

        assert insight.text == "You have 0 open requests."
        assert "How many requests are open?" in provider.sent[0].user_prompt

    def test_no_provider_returns_fixed_unavailable_message(self, env: Env, approver) -> None:
        _, approver_identity = approver
        service = _build_ai_insight_service(env, ai_provider=None)

        insight = service.ask_assistant(approver_identity, "question")

        assert insight.is_fallback is True
        assert "unavailable" in insight.text.lower()

    def test_is_never_cached(self, env: Env, approver) -> None:
        _, approver_identity = approver
        provider = FakeAiProvider()
        service = _build_ai_insight_service(env, ai_provider=provider)

        first = service.ask_assistant(approver_identity, "question")
        second = service.ask_assistant(approver_identity, "question")

        assert first.cached is False
        assert second.cached is False
        assert len(provider.sent) == 2

    def test_history_is_forwarded_to_the_prompt(self, env: Env, approver) -> None:
        _, approver_identity = approver
        provider = FakeAiProvider()
        service = _build_ai_insight_service(env, ai_provider=provider)

        service.ask_assistant(
            approver_identity, "follow-up question", [("user", "first question"), ("assistant", "first answer")]
        )

        assert "first question" in provider.sent[0].user_prompt
        assert "first answer" in provider.sent[0].user_prompt
