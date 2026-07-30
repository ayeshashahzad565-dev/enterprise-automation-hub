"""Cross-tenant isolation tests for the multi-tenancy conversion.

Per the conversion plan's test strategy, this is the single most
important new test category the conversion introduces: seed two
companies, each with their own admin/employee/requests/definitions/
invitations, and assert Company A's identity can never list, fetch, or
act on Company B's rows through any repository or service method touched
by the conversion — a 404/empty-result/PermissionDeniedError as
appropriate, matching each method's existing not-found-vs-forbidden
convention (see ``app.auth.authorization.authorize_request_view``'s own
"out-of-scope resource is reported as not-found, never as a permission
failure" rule, applied identically here to cross-tenant access).

Uses the same ``env``/``make_user`` fixtures as every other unit test in
this suite (``tests/conftest.py``) — ``make_user`` now accepts an explicit
``company_id`` to build a user in a company other than the shared
``DEFAULT_TEST_COMPANY_ID`` every other test in this suite implicitly
uses, so this file is the only one that ever needs to pass it.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.database.exceptions import RecordNotFoundError
from app.models.enums import UserRole
from app.services.exceptions import NotFoundError, PermissionDeniedError
from app.services.invitation_service import InvitationService
from app.utils.datetime_utils import utc_now
from tests.conftest import Env
from tests.fixtures.fakes import (
    DEFAULT_TEST_COMPANY_ID,
    FakeAuditRepository,
    FakeInvitationRepository,
    FakeProfileRepository,
    FakeSupabaseAuthAdminClient,
)

pytestmark = pytest.mark.unit


@pytest.fixture
def company_b_id():
    return uuid4()


@pytest.fixture
def company_b_admin(env: Env, make_user, company_b_id):
    return make_user(role=UserRole.ADMIN, full_name="Bob Admin", company_id=company_b_id)


@pytest.fixture
def company_b_employee(env: Env, make_user, company_b_id):
    return make_user(role=UserRole.EMPLOYEE, full_name="Eve Employee (B)", company_id=company_b_id)


@pytest.fixture
def company_b_approver(env: Env, make_user, company_b_id):
    return make_user(role=UserRole.APPROVER, full_name="Amy Approver (B)", company_id=company_b_id)


def _activate_definition(env: Env, admin_identity, *, request_type: str, stages: list[dict]):
    created = env.workflow_definition_service.create_definition(
        admin_identity, request_type=request_type, definition={"stages": stages}
    )
    return env.workflow_definition_service.activate_version(admin_identity, created.id)


class TestRequestIsolation:
    def test_company_bs_admin_cannot_fetch_company_as_request(
        self, env: Env, admin, employee, approver, company_b_admin
    ):
        _, admin_identity = admin
        _, employee_identity = employee
        _, approver_identity = approver
        _activate_definition(
            env,
            admin_identity,
            request_type="expense_reimbursement",
            stages=[
                {
                    "order": 1,
                    "name": "Manager Review",
                    "assignment_strategy": "specific_user",
                    "assigned_user_id": str(approver_identity.user_id),
                    "escalation_hours": 24,
                }
            ],
        )
        created = env.request_service.create_request(
            employee_identity, request_type="expense_reimbursement", title="Team lunch"
        )

        _, other_admin_identity = company_b_admin
        with pytest.raises(NotFoundError):
            env.request_service.get_request(other_admin_identity, created.id)

    def test_company_bs_admin_list_requests_never_includes_company_as_rows(
        self, env: Env, admin, employee, approver, company_b_admin
    ):
        _, admin_identity = admin
        _, employee_identity = employee
        _, approver_identity = approver
        _activate_definition(
            env,
            admin_identity,
            request_type="expense_reimbursement",
            stages=[
                {
                    "order": 1,
                    "name": "Manager Review",
                    "assignment_strategy": "specific_user",
                    "assigned_user_id": str(approver_identity.user_id),
                    "escalation_hours": 24,
                }
            ],
        )
        env.request_service.create_request(
            employee_identity, request_type="expense_reimbursement", title="Team lunch"
        )

        _, other_admin_identity = company_b_admin
        result = env.request_service.list_requests(other_admin_identity)

        assert result.items == []
        assert result.total_records == 0


class TestApprovalQueueIsolation:
    def test_an_approver_in_company_b_never_sees_a_pending_stage_from_company_a(
        self, env: Env, admin, employee, approver, company_b_approver
    ):
        _, admin_identity = admin
        _, employee_identity = employee
        _, approver_identity = approver
        _activate_definition(
            env,
            admin_identity,
            request_type="expense_reimbursement",
            stages=[
                {
                    "order": 1,
                    "name": "Manager Review",
                    "assignment_strategy": "department_queue",
                    "department": "sales",
                    "assigned_role": "approver",
                    "escalation_hours": 24,
                }
            ],
        )
        env.request_service.create_request(
            employee_identity, request_type="expense_reimbursement", title="Team lunch"
        )

        # An approver in Company B shares the same role (APPROVER) as
        # Company A's approver, which is exactly the case a company_id
        # filter must guard against — a role match alone must never be
        # sufficient.
        _, other_approver_identity = company_b_approver
        result = env.approval_service.list_pending_approvals(other_approver_identity)

        assert result.items == []
        assert result.total_records == 0

        # Sanity check: Company A's own approver *does* see it.
        own_result = env.approval_service.list_pending_approvals(approver_identity)
        assert own_result.total_records == 1

    def test_an_approver_in_company_b_cannot_decide_a_stage_from_company_a(
        self, env: Env, admin, employee, approver, company_b_approver
    ):
        _, admin_identity = admin
        _, employee_identity = employee
        _, approver_identity = approver
        _activate_definition(
            env,
            admin_identity,
            request_type="expense_reimbursement",
            stages=[
                {
                    "order": 1,
                    "name": "Manager Review",
                    "assignment_strategy": "specific_user",
                    "assigned_user_id": str(approver_identity.user_id),
                    "escalation_hours": 24,
                }
            ],
        )
        created = env.request_service.create_request(
            employee_identity, request_type="expense_reimbursement", title="Team lunch"
        )
        progress = env.request_service.get_workflow_progress(admin_identity, created.id)
        stage_id = progress.stages[0].stage_id

        _, other_approver_identity = company_b_approver
        with pytest.raises(NotFoundError):
            env.approval_service.approve_stage(other_approver_identity, stage_id)


class TestWorkflowDefinitionIsolation:
    def test_each_companys_admin_may_independently_activate_the_same_request_type(
        self, env: Env, admin, approver, company_b_admin, company_b_approver
    ):
        _, admin_identity = admin
        _, approver_identity = approver
        _, other_admin_identity = company_b_admin
        _, other_approver_identity = company_b_approver

        definition_a = _activate_definition(
            env,
            admin_identity,
            request_type="expense_reimbursement",
            stages=[
                {
                    "order": 1,
                    "name": "Review",
                    "assignment_strategy": "specific_user",
                    "assigned_user_id": str(approver_identity.user_id),
                    "escalation_hours": 24,
                }
            ],
        )
        definition_b = _activate_definition(
            env,
            other_admin_identity,
            request_type="expense_reimbursement",
            stages=[
                {
                    "order": 1,
                    "name": "Review",
                    "assignment_strategy": "specific_user",
                    "assigned_user_id": str(other_approver_identity.user_id),
                    "escalation_hours": 24,
                }
            ],
        )

        assert definition_a.id != definition_b.id
        assert definition_a.is_active is True
        assert definition_b.is_active is True

    def test_company_bs_admin_cannot_activate_company_as_draft_definition(
        self, env: Env, admin, company_b_admin
    ):
        _, admin_identity = admin
        created = env.workflow_definition_service.create_definition(
            admin_identity,
            request_type="equipment_request",
            definition={
                "stages": [
                    {
                        "order": 1,
                        "name": "Review",
                        "assignment_strategy": "department_queue",
                        "department": "it",
                        "assigned_role": "approver",
                        "escalation_hours": 24,
                    }
                ]
            },
        )

        _, other_admin_identity = company_b_admin
        with pytest.raises(NotFoundError):
            env.workflow_definition_service.activate_version(other_admin_identity, created.id)

    def test_company_bs_admin_cannot_edit_company_as_draft_definition(
        self, env: Env, admin, company_b_admin
    ):
        _, admin_identity = admin
        created = env.workflow_definition_service.create_definition(
            admin_identity,
            request_type="equipment_request",
            definition={
                "stages": [
                    {
                        "order": 1,
                        "name": "Review",
                        "assignment_strategy": "department_queue",
                        "department": "it",
                        "assigned_role": "approver",
                        "escalation_hours": 24,
                    }
                ]
            },
        )

        _, other_admin_identity = company_b_admin
        with pytest.raises(NotFoundError):
            env.workflow_definition_service.update_draft(
                other_admin_identity,
                created.id,
                definition={
                    "stages": [
                        {
                            "order": 1,
                            "name": "Renamed",
                            "assignment_strategy": "department_queue",
                            "department": "it",
                            "assigned_role": "approver",
                            "escalation_hours": 24,
                        }
                    ]
                },
            )


class TestWorkflowRepositoryScopedGetById:
    """Repository-level coverage for ``get_by_id_for_company`` — the
    structural fix (Milestone 13, High finding 4) making a cross-tenant
    workflow definition/stage lookup impossible regardless of whether the
    calling service remembers to check ``company_id`` itself. The service-
    level tests above (``TestWorkflowDefinitionIsolation``,
    ``TestApprovalQueueIsolation``) already prove the real call sites use
    this correctly; these tests exercise the repository method itself.
    """

    def test_definition_get_by_id_for_company_raises_not_found_for_another_companys_row(
        self, env: Env, admin, company_b_id
    ):
        _, admin_identity = admin
        created = env.workflow_definition_service.create_definition(
            admin_identity,
            request_type="expense_reimbursement",
            definition={
                "stages": [
                    {
                        "order": 1,
                        "name": "Review",
                        "assignment_strategy": "department_queue",
                        "department": "finance",
                        "assigned_role": "approver",
                        "escalation_hours": 24,
                    }
                ]
            },
        )

        with pytest.raises(RecordNotFoundError):
            env.workflow_definition_repo.get_by_id_for_company(created.id, company_id=company_b_id)

        # Sanity check: the owning company can still fetch it.
        own = env.workflow_definition_repo.get_by_id_for_company(
            created.id, company_id=admin_identity.company_id
        )
        assert own.id == created.id

    def test_stage_get_by_id_for_company_raises_not_found_for_another_companys_row(
        self, env: Env, admin, employee, approver, company_b_id
    ):
        _, admin_identity = admin
        _, employee_identity = employee
        _, approver_identity = approver
        _activate_definition(
            env,
            admin_identity,
            request_type="expense_reimbursement",
            stages=[
                {
                    "order": 1,
                    "name": "Manager Review",
                    "assignment_strategy": "specific_user",
                    "assigned_user_id": str(approver_identity.user_id),
                    "escalation_hours": 24,
                }
            ],
        )
        created = env.request_service.create_request(
            employee_identity, request_type="expense_reimbursement", title="Team lunch"
        )
        progress = env.request_service.get_workflow_progress(admin_identity, created.id)
        stage_id = progress.stages[0].stage_id

        with pytest.raises(RecordNotFoundError):
            env.workflow_stage_repo.get_by_id_for_company(stage_id, company_id=company_b_id)

        own = env.workflow_stage_repo.get_by_id_for_company(
            stage_id, company_id=admin_identity.company_id
        )
        assert own.id == stage_id


class TestOverdueStagesScoping:
    """Milestone 13, Medium finding 5: ``list_overdue_stages`` now
    requires ``company_id`` (no more silent, implicit global scan via an
    omitted optional parameter) — the one legitimate cross-tenant sweep
    is the separate, explicitly-named ``list_overdue_stages_all_companies``.
    """

    def test_list_overdue_stages_is_scoped_to_one_company(
        self,
        env: Env,
        admin,
        employee,
        approver,
        company_b_admin,
        company_b_employee,
        company_b_approver,
        company_b_id,
    ):
        _, admin_identity = admin
        _, employee_identity = employee
        approver_profile, _ = approver
        _activate_definition(
            env,
            admin_identity,
            request_type="expense_reimbursement",
            stages=[
                {
                    "order": 1,
                    "name": "Review",
                    "assignment_strategy": "specific_user",
                    "assigned_user_id": str(approver_profile.id),
                    "escalation_hours": 24,
                }
            ],
        )
        env.request_service.create_request(
            employee_identity, request_type="expense_reimbursement", title="Company A request"
        )

        _, other_admin_identity = company_b_admin
        _, other_employee_identity = company_b_employee
        other_approver_profile, _ = company_b_approver
        _activate_definition(
            env,
            other_admin_identity,
            request_type="expense_reimbursement",
            stages=[
                {
                    "order": 1,
                    "name": "Review",
                    "assignment_strategy": "specific_user",
                    "assigned_user_id": str(other_approver_profile.id),
                    "escalation_hours": 24,
                }
            ],
        )
        env.request_service.create_request(
            other_employee_identity, request_type="expense_reimbursement", title="Company B request"
        )

        cutoff = utc_now()
        company_a_result = env.approval_repo.list_overdue_stages(
            created_before=cutoff, company_id=admin_identity.company_id
        )
        company_b_result = env.approval_repo.list_overdue_stages(
            created_before=cutoff, company_id=company_b_id
        )
        all_companies_result = env.approval_repo.list_overdue_stages_all_companies(
            created_before=cutoff
        )

        assert company_a_result.total_records == 1
        assert company_b_result.total_records == 1
        assert all_companies_result.total_records == 2


class TestUserDirectoryIsolation:
    def test_list_by_role_never_returns_another_companys_profiles(
        self, env: Env, approver, company_b_approver
    ):
        _, _ = approver
        _, _ = company_b_approver

        page = env.profile_repo.list_by_role(UserRole.APPROVER)
        names = {p.full_name for p in page.items}

        assert "Alan Approver" in names
        assert "Amy Approver (B)" not in names


def _make_invitation_service() -> InvitationService:
    profile_repo = FakeProfileRepository()
    return InvitationService(
        invitation_repo=FakeInvitationRepository(),
        profile_repo=profile_repo,
        audit_repo=FakeAuditRepository(),
        auth_admin_client=FakeSupabaseAuthAdminClient(profile_repo=profile_repo),
    )


class TestPlatformAdminBoundary:
    """``InvitationService.create_invitation``'s one deliberate exception
    to "company_id is never client input" — see its own docstring.
    """

    def test_an_ordinary_admin_cannot_invite_into_a_company_other_than_their_own(
        self, make_user, company_b_id
    ):
        service = _make_invitation_service()
        _, admin_identity = make_user(role=UserRole.ADMIN, full_name="Ada Admin")
        assert admin_identity.is_platform_admin is False

        with pytest.raises(PermissionDeniedError):
            service.create_invitation(
                admin_identity,
                email="first.admin@companyb.example.com",
                full_name="First Admin",
                role=UserRole.ADMIN,
                company_id=company_b_id,
            )

    def test_a_platform_admin_may_invite_a_new_companys_first_admin(self, make_user, company_b_id):
        service = _make_invitation_service()
        _, platform_admin_identity = make_user(
            role=UserRole.EMPLOYEE, full_name="Priya PlatformAdmin", is_platform_admin=True
        )
        assert platform_admin_identity.company_id == DEFAULT_TEST_COMPANY_ID
        assert platform_admin_identity.company_id != company_b_id

        created = service.create_invitation(
            platform_admin_identity,
            email="first.admin@companyb.example.com",
            full_name="First Admin",
            role=UserRole.ADMIN,
            company_id=company_b_id,
        )

        assert created.email == "first.admin@companyb.example.com"
