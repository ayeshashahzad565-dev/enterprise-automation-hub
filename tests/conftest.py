"""Shared pytest fixtures for the Enterprise Automation Hub test suite.

The ``env`` fixture builds a fresh set of in-memory fake repositories
(``tests/fixtures/fakes.py``) for every test, wired into the real,
unmodified service and Workflow Engine classes from ``app.services`` and
``app.workflow`` — so every test exercises production business logic
end-to-end without a real Supabase/network dependency, and without any
two tests sharing state (each test's ``env`` is a fresh, isolated
in-memory database).
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from uuid import UUID, uuid4

import pytest

from app.auth.authentication import AuthenticatedIdentity
from app.database.repositories.user_repository import ProfileRecord
from app.database.repositories.workflow_repository import WorkflowStageRecord
from app.models import WorkflowDefinition
from app.models.enums import UserRole
from app.services.approval_service import ApprovalService
from app.services.attachment_service import AttachmentService
from app.services.comment_service import CommentService
from app.services.company_service import CompanyService
from app.services.feature_flag_service import FeatureFlagService
from app.services.notification_service import NotificationService
from app.services.request_service import RequestService
from app.services.search_service import GlobalSearchService
from app.services.user_service import UserService
from app.services.workflow_definition_service import WorkflowDefinitionService
from app.workflow.engine import WorkflowEngine
from tests.fixtures.fakes import (
    FakeApprovalRepository,
    FakeAttachmentRepository,
    FakeAttachmentStorageGateway,
    FakeAuditRepository,
    FakeCommentRepository,
    FakeCompanyLicenseRepository,
    FakeCompanyRepository,
    FakeEmailSender,
    FakeFeatureFlagRepository,
    FakeNotificationPreferenceRepository,
    FakeNotificationRepository,
    FakeProfileRepository,
    FakeRequestRepository,
    FakeSavedFilterRepository,
    FakeSearchHistoryRepository,
    FakeSupabaseAuthAdminClient,
    FakeTable,
    FakeVirusScanner,
    FakeWorkflowDefinitionRepository,
    FakeWorkflowStageRepository,
)

pytest_plugins: list[str] = []


@dataclasses.dataclass
class Env:
    """Every fake repository plus every real service, wired together."""

    profile_repo: FakeProfileRepository
    request_repo: FakeRequestRepository
    workflow_definition_repo: FakeWorkflowDefinitionRepository
    workflow_stage_repo: FakeWorkflowStageRepository
    approval_repo: FakeApprovalRepository
    stages_table: FakeTable[WorkflowStageRecord]
    audit_repo: FakeAuditRepository
    notification_repo: FakeNotificationRepository
    notification_preference_repo: FakeNotificationPreferenceRepository
    company_repo: FakeCompanyRepository
    company_license_repo: FakeCompanyLicenseRepository
    feature_flag_repo: FakeFeatureFlagRepository
    comment_repo: FakeCommentRepository
    attachment_repo: FakeAttachmentRepository
    attachment_storage: FakeAttachmentStorageGateway
    saved_filter_repo: FakeSavedFilterRepository
    search_history_repo: FakeSearchHistoryRepository
    virus_scanner: FakeVirusScanner
    email_sender: FakeEmailSender
    workflow_engine: WorkflowEngine
    notification_service: NotificationService
    request_service: RequestService
    approval_service: ApprovalService
    comment_service: CommentService
    attachment_service: AttachmentService
    workflow_definition_service: WorkflowDefinitionService
    search_service: GlobalSearchService
    company_service: CompanyService
    feature_flag_service: FeatureFlagService
    auth_admin_client: FakeSupabaseAuthAdminClient
    user_service: UserService


@pytest.fixture
def env() -> Env:
    """A fresh, isolated set of fake repositories and real services."""
    profile_repo = FakeProfileRepository()
    request_repo = FakeRequestRepository()
    workflow_definition_repo = FakeWorkflowDefinitionRepository()
    stages_table: FakeTable[WorkflowStageRecord] = FakeTable("workflow_stages")
    workflow_stage_repo = FakeWorkflowStageRepository(stages_table)
    approval_repo = FakeApprovalRepository(stages_table)
    audit_repo = FakeAuditRepository()
    notification_repo = FakeNotificationRepository()
    notification_preference_repo = FakeNotificationPreferenceRepository()
    company_repo = FakeCompanyRepository()
    company_license_repo = FakeCompanyLicenseRepository()
    feature_flag_repo = FakeFeatureFlagRepository()
    comment_repo = FakeCommentRepository()
    attachment_repo = FakeAttachmentRepository()
    attachment_storage = FakeAttachmentStorageGateway()
    saved_filter_repo = FakeSavedFilterRepository()
    search_history_repo = FakeSearchHistoryRepository()
    virus_scanner = FakeVirusScanner()
    email_sender = FakeEmailSender()

    workflow_engine = WorkflowEngine()
    notification_service = NotificationService(
        notification_repo=notification_repo,
        preference_repo=notification_preference_repo,
        email_sender=email_sender,
    )
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
        virus_scanner=virus_scanner,
    )
    workflow_definition_service = WorkflowDefinitionService(
        workflow_definition_repo=workflow_definition_repo,
        profile_repo=profile_repo,
        audit_repo=audit_repo,
        workflow_engine=workflow_engine,
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
    feature_flag_service = FeatureFlagService(
        feature_flag_repo=feature_flag_repo, audit_repo=audit_repo
    )
    auth_admin_client = FakeSupabaseAuthAdminClient(profile_repo=profile_repo)
    user_service = UserService(
        profile_repo=profile_repo, audit_repo=audit_repo, auth_admin_client=auth_admin_client
    )
    return Env(
        profile_repo=profile_repo,
        request_repo=request_repo,
        workflow_definition_repo=workflow_definition_repo,
        workflow_stage_repo=workflow_stage_repo,
        approval_repo=approval_repo,
        stages_table=stages_table,
        audit_repo=audit_repo,
        notification_repo=notification_repo,
        notification_preference_repo=notification_preference_repo,
        company_repo=company_repo,
        company_license_repo=company_license_repo,
        feature_flag_repo=feature_flag_repo,
        comment_repo=comment_repo,
        attachment_repo=attachment_repo,
        attachment_storage=attachment_storage,
        saved_filter_repo=saved_filter_repo,
        search_history_repo=search_history_repo,
        virus_scanner=virus_scanner,
        email_sender=email_sender,
        workflow_engine=workflow_engine,
        notification_service=notification_service,
        request_service=request_service,
        approval_service=approval_service,
        comment_service=comment_service,
        attachment_service=attachment_service,
        workflow_definition_service=workflow_definition_service,
        search_service=search_service,
        company_service=company_service,
        feature_flag_service=feature_flag_service,
        auth_admin_client=auth_admin_client,
        user_service=user_service,
    )


def _identity_for(profile: ProfileRecord) -> AuthenticatedIdentity:
    return AuthenticatedIdentity(
        user_id=profile.id,
        email=None,
        role=profile.role,
        company_id=profile.company_id,
        is_platform_admin=profile.is_platform_admin,
        expires_at=None,
        raw_claims={},
    )


@pytest.fixture
def make_user(env: Env) -> Callable[..., tuple[ProfileRecord, AuthenticatedIdentity]]:
    """Factory fixture: create a profile plus its matching authenticated identity.

    ``company_id``/``is_platform_admin`` default to
    ``FakeProfileRepository.create_profile``'s own defaults (the shared
    ``DEFAULT_TEST_COMPANY_ID``, not a platform admin) — pass either
    explicitly to build a cross-tenant-isolation or platform-admin
    fixture.
    """

    def _make(
        *,
        role: UserRole,
        full_name: str = "Test User",
        department: str | None = None,
        company_id: UUID | None = None,
        is_platform_admin: bool = False,
    ) -> tuple[ProfileRecord, AuthenticatedIdentity]:
        kwargs: dict[str, object] = {
            "profile_id": uuid4(),
            "full_name": full_name,
            "role": role,
            "department": department,
            "is_platform_admin": is_platform_admin,
        }
        if company_id is not None:
            kwargs["company_id"] = company_id
        profile = env.profile_repo.create_profile(**kwargs)
        return profile, _identity_for(profile)

    return _make


@pytest.fixture
def employee(make_user) -> tuple[ProfileRecord, AuthenticatedIdentity]:
    return make_user(role=UserRole.EMPLOYEE, full_name="Eve Employee", department="sales")


@pytest.fixture
def approver(make_user) -> tuple[ProfileRecord, AuthenticatedIdentity]:
    return make_user(role=UserRole.APPROVER, full_name="Alan Approver", department="sales")


@pytest.fixture
def platform_admin(make_user) -> tuple[ProfileRecord, AuthenticatedIdentity]:
    return make_user(
        role=UserRole.EMPLOYEE,
        full_name="Pat PlatformAdmin",
        is_platform_admin=True,
    )


@pytest.fixture
def second_approver(make_user) -> tuple[ProfileRecord, AuthenticatedIdentity]:
    return make_user(role=UserRole.APPROVER, full_name="Amy Approver", department="engineering")


@pytest.fixture
def admin(make_user) -> tuple[ProfileRecord, AuthenticatedIdentity]:
    return make_user(role=UserRole.ADMIN, full_name="Ada Admin")


@pytest.fixture
def make_definition(
    env: Env, admin: tuple[ProfileRecord, AuthenticatedIdentity]
) -> Callable[..., WorkflowDefinition]:
    """Factory fixture: create and activate a workflow definition through
    the real ``WorkflowDefinitionService`` (full validation, no shortcuts).
    """
    _, admin_identity = admin

    def _make(*, request_type: str, stages: list[dict[str, object]]) -> WorkflowDefinition:
        created = env.workflow_definition_service.create_definition(
            admin_identity, request_type=request_type, definition={"stages": stages}
        )
        return env.workflow_definition_service.activate_version(admin_identity, created.id)

    return _make
