"""Real-database CRUD tests for every repository, via the actual
Supabase/postgrest REST API — not the in-memory fakes.

Every test creates its own real ``auth.users``/``profiles`` row through
``make_test_profile`` (which guarantees full cleanup, across every table
that may end up referencing it, at teardown) rather than a rolled-back
transaction, since a real ``postgrest`` call has no ambient client-side
transaction to roll back.
"""

from __future__ import annotations

import uuid

import pytest

from app.database.exceptions import ConstraintViolationError, RecordNotFoundError
from app.models.enums import AttachmentScanStatus, RequestStatus, StageStatus, UserRole
from app.utils.file_utils import build_storage_path
from tests.fixtures.factories import specific_user_stage

pytestmark = pytest.mark.integration


class TestProfileRepositoryCrud:
    def test_get_by_id_and_update_profile_round_trip(self, real_repos, make_test_profile):
        profile = make_test_profile(
            role=UserRole.EMPLOYEE, full_name="Original Name", department="sales"
        )

        fetched = real_repos.profile.get_by_id(profile.id)
        assert fetched.full_name == "Original Name"
        assert fetched.department == "sales"

        updated = real_repos.profile.update_profile(
            profile.id, expected_version=fetched.version, full_name="Updated Name"
        )
        assert updated.full_name == "Updated Name"
        assert updated.version == fetched.version + 1

    def test_find_by_id_returns_none_for_an_unknown_profile(self, real_repos):
        assert real_repos.profile.find_by_id(uuid.uuid4()) is None

    def test_list_by_role_and_department(self, real_repos, make_test_profile, test_company_id):
        make_test_profile(
            role=UserRole.APPROVER, full_name="Finance Approver", department="finance"
        )

        result = real_repos.profile.list_by_role(
            UserRole.APPROVER, department="finance", company_id=test_company_id
        )

        assert any(p.full_name == "Finance Approver" for p in result.items)

    def test_search_by_name_matches_a_substring_case_insensitively(
        self, real_repos, make_test_profile, test_company_id
    ):
        unique = uuid.uuid4().hex[:8]
        make_test_profile(role=UserRole.EMPLOYEE, full_name=f"Zzyx Search Target {unique}")

        result = real_repos.profile.search_by_name(
            f"search target {unique}", company_id=test_company_id
        )

        assert any(unique in p.full_name for p in result.items)


class TestWorkflowDefinitionRepositoryCrud:
    def test_create_activate_and_read_back_a_definition(
        self, real_repos, make_test_profile, test_company_id
    ):
        admin = make_test_profile(role=UserRole.ADMIN)
        request_type = f"itest_{uuid.uuid4().hex[:8]}"
        approver = make_test_profile(role=UserRole.APPROVER)

        created = real_repos.workflow_definition.create_definition(
            request_type=request_type,
            version=1,
            definition={"stages": [specific_user_stage(1, "Manager Review", user_id=approver.id)]},
            created_by=admin.id,
            company_id=test_company_id,
        )
        assert created.is_active is False

        activated = real_repos.workflow_definition.activate_definition(
            created.id,
            request_type=request_type,
            expected_row_version=created.row_version,
            company_id=test_company_id,
        )
        assert activated.is_active is True

        active = real_repos.workflow_definition.find_active_for_request_type(
            request_type, company_id=test_company_id
        )
        assert active is not None
        assert active.id == created.id
        assert active.definition["stages"][0]["assignment_strategy"] == "specific_user"

    def test_activating_a_new_version_deactivates_the_previous_one(
        self, real_repos, make_test_profile, test_company_id
    ):
        admin = make_test_profile(role=UserRole.ADMIN)
        approver = make_test_profile(role=UserRole.APPROVER)
        request_type = f"itest_{uuid.uuid4().hex[:8]}"
        stages = [specific_user_stage(1, "Manager Review", user_id=approver.id)]

        v1 = real_repos.workflow_definition.create_definition(
            request_type=request_type,
            version=1,
            definition={"stages": stages},
            created_by=admin.id,
            company_id=test_company_id,
        )
        v2 = real_repos.workflow_definition.create_definition(
            request_type=request_type,
            version=2,
            definition={"stages": stages},
            created_by=admin.id,
            company_id=test_company_id,
        )
        real_repos.workflow_definition.activate_definition(
            v1.id,
            request_type=request_type,
            expected_row_version=v1.row_version,
            company_id=test_company_id,
        )

        real_repos.workflow_definition.activate_definition(
            v2.id,
            request_type=request_type,
            expected_row_version=v2.row_version,
            company_id=test_company_id,
        )

        v1_reloaded = real_repos.workflow_definition.get_by_id(v1.id)
        assert v1_reloaded.is_active is False

    def test_search_definitions_matches_request_type_substring(
        self, real_repos, make_test_profile, test_company_id
    ):
        admin = make_test_profile(role=UserRole.ADMIN)
        approver = make_test_profile(role=UserRole.APPROVER)
        unique = uuid.uuid4().hex[:8]
        request_type = f"itest_search_target_{unique}"
        real_repos.workflow_definition.create_definition(
            request_type=request_type,
            version=1,
            definition={"stages": [specific_user_stage(1, "Manager Review", user_id=approver.id)]},
            created_by=admin.id,
            company_id=test_company_id,
        )

        result = real_repos.workflow_definition.search_definitions(
            f"search_target_{unique}", company_id=test_company_id
        )

        assert any(d.request_type == request_type for d in result.items)

        active_only = real_repos.workflow_definition.search_definitions(
            f"search_target_{unique}", is_active=True, company_id=test_company_id
        )
        assert active_only.items == []


class TestRequestAndWorkflowStageRepositoryCrud:
    def test_create_request_create_stage_and_set_current_stage(
        self, real_repos, make_test_profile, test_company_id
    ):
        employee = make_test_profile(role=UserRole.EMPLOYEE)
        admin = make_test_profile(role=UserRole.ADMIN)
        approver = make_test_profile(role=UserRole.APPROVER)
        request_type = f"itest_{uuid.uuid4().hex[:8]}"
        definition = real_repos.workflow_definition.create_definition(
            request_type=request_type,
            version=1,
            definition={"stages": [specific_user_stage(1, "Manager Review", user_id=approver.id)]},
            created_by=admin.id,
            company_id=test_company_id,
        )

        request = real_repos.request.create_request(
            requester_id=employee.id,
            workflow_definition_id=definition.id,
            request_type=request_type,
            title="Integration test request",
            company_id=test_company_id,
        )
        assert request.status is RequestStatus.PENDING
        assert request.current_stage_id is None

        stage = real_repos.workflow_stage.create_stage(
            request_id=request.id,
            stage_order=1,
            stage_name="Manager Review",
            assigned_to=approver.id,
            company_id=test_company_id,
        )
        assert stage.status is StageStatus.PENDING

        updated_request = real_repos.request.set_current_stage(
            request.id,
            expected_version=request.version,
            current_stage_id=stage.id,
            status=RequestStatus.PENDING,
        )
        assert updated_request.current_stage_id == stage.id

        reloaded = real_repos.request.get_by_id(request.id)
        assert reloaded.current_stage_id == stage.id
        assert reloaded.version == updated_request.version

    def test_get_by_id_raises_not_found_for_an_unknown_request(self, real_repos):
        with pytest.raises(RecordNotFoundError):
            real_repos.request.get_by_id(uuid.uuid4())

    def test_soft_delete_a_request(self, real_repos, make_test_profile, test_company_id):
        employee = make_test_profile(role=UserRole.EMPLOYEE)
        admin = make_test_profile(role=UserRole.ADMIN)
        request_type = f"itest_{uuid.uuid4().hex[:8]}"
        definition = real_repos.workflow_definition.create_definition(
            request_type=request_type,
            version=1,
            definition={"stages": []},
            created_by=admin.id,
            company_id=test_company_id,
        )
        request = real_repos.request.create_request(
            requester_id=employee.id,
            workflow_definition_id=definition.id,
            request_type=request_type,
            title="To be withdrawn",
            company_id=test_company_id,
        )

        withdrawn = real_repos.request.soft_delete(
            request.id, expected_version=request.version, deleted_by=employee.id
        )

        assert withdrawn.deleted_at is not None
        assert withdrawn.deleted_by == employee.id

    def test_list_requests_and_search_requests_filter_by_request_ids(
        self, real_repos, make_test_profile, test_company_id
    ):
        employee = make_test_profile(role=UserRole.EMPLOYEE)
        admin = make_test_profile(role=UserRole.ADMIN)
        request_type = f"itest_{uuid.uuid4().hex[:8]}"
        definition = real_repos.workflow_definition.create_definition(
            request_type=request_type,
            version=1,
            definition={"stages": []},
            created_by=admin.id,
            company_id=test_company_id,
        )
        kept = real_repos.request.create_request(
            requester_id=employee.id,
            workflow_definition_id=definition.id,
            request_type=request_type,
            title="Kept by request_ids filter",
            company_id=test_company_id,
        )
        real_repos.request.create_request(
            requester_id=employee.id,
            workflow_definition_id=definition.id,
            request_type=request_type,
            title="Excluded by request_ids filter",
            company_id=test_company_id,
        )

        listed = real_repos.request.list_requests(
            request_ids=[kept.id], company_id=test_company_id
        ).items
        assert [r.id for r in listed] == [kept.id]

        searched = real_repos.request.search_requests(
            "filter", request_ids=[kept.id], company_id=test_company_id
        ).items
        assert [r.id for r in searched] == [kept.id]


class TestCommentRepositoryCrud:
    def test_create_and_list_comments_for_a_request(
        self, real_repos, make_test_profile, test_company_id
    ):
        employee = make_test_profile(role=UserRole.EMPLOYEE)
        admin = make_test_profile(role=UserRole.ADMIN)
        request_type = f"itest_{uuid.uuid4().hex[:8]}"
        definition = real_repos.workflow_definition.create_definition(
            request_type=request_type,
            version=1,
            definition={"stages": []},
            created_by=admin.id,
            company_id=test_company_id,
        )
        request = real_repos.request.create_request(
            requester_id=employee.id,
            workflow_definition_id=definition.id,
            request_type=request_type,
            title="Commentable request",
            company_id=test_company_id,
        )

        comment = real_repos.comment.create_comment(
            request_id=request.id, author_id=employee.id, body="A real, persisted comment."
        )

        thread = real_repos.comment.list_for_request(request.id).items
        assert [c.id for c in thread] == [comment.id]

        removed = real_repos.comment.soft_delete(comment.id, deleted_by=admin.id)
        assert removed.deleted_at is not None

    def test_search_matches_body_substring_and_respects_request_ids_scope(
        self, real_repos, make_test_profile, test_company_id
    ):
        employee = make_test_profile(role=UserRole.EMPLOYEE)
        admin = make_test_profile(role=UserRole.ADMIN)
        request_type = f"itest_{uuid.uuid4().hex[:8]}"
        definition = real_repos.workflow_definition.create_definition(
            request_type=request_type,
            version=1,
            definition={"stages": []},
            created_by=admin.id,
            company_id=test_company_id,
        )
        in_scope = real_repos.request.create_request(
            requester_id=employee.id,
            workflow_definition_id=definition.id,
            request_type=request_type,
            title="In scope request",
            company_id=test_company_id,
        )
        out_of_scope = real_repos.request.create_request(
            requester_id=employee.id,
            workflow_definition_id=definition.id,
            request_type=request_type,
            title="Out of scope request",
            company_id=test_company_id,
        )
        unique = uuid.uuid4().hex[:8]
        real_repos.comment.create_comment(
            request_id=in_scope.id, author_id=employee.id, body=f"searchable comment {unique}"
        )
        real_repos.comment.create_comment(
            request_id=out_of_scope.id, author_id=employee.id, body=f"searchable comment {unique}"
        )

        unscoped = real_repos.comment.search(unique).items
        assert len(unscoped) == 2

        scoped = real_repos.comment.search(unique, request_ids=[in_scope.id]).items
        assert [c.request_id for c in scoped] == [in_scope.id]


class TestAttachmentRepositoryCrud:
    @staticmethod
    def _make_request(real_repos, make_test_profile, test_company_id):
        employee = make_test_profile(role=UserRole.EMPLOYEE)
        admin = make_test_profile(role=UserRole.ADMIN)
        request_type = f"itest_{uuid.uuid4().hex[:8]}"
        definition = real_repos.workflow_definition.create_definition(
            request_type=request_type,
            version=1,
            definition={"stages": []},
            created_by=admin.id,
            company_id=test_company_id,
        )
        request = real_repos.request.create_request(
            requester_id=employee.id,
            workflow_definition_id=definition.id,
            request_type=request_type,
            title="Attachable request",
            company_id=test_company_id,
        )
        return employee, request

    def test_create_and_get_an_attachment(self, real_repos, make_test_profile, test_company_id):
        employee, request = self._make_request(real_repos, make_test_profile, test_company_id)
        attachment_id = uuid.uuid4()
        storage_path = build_storage_path(
            request_id=request.id, attachment_id=attachment_id, sanitized_file_name="receipt.pdf"
        )

        created = real_repos.attachment.create_attachment(
            attachment_id=attachment_id,
            request_id=request.id,
            uploaded_by=employee.id,
            file_name="receipt.pdf",
            content_type="application/pdf",
            size_bytes=1024,
            storage_path=storage_path,
            checksum_sha256="a" * 64,
        )

        assert created.id == attachment_id
        assert created.version == 1
        assert created.replaces_attachment_id is None
        assert created.scan_status is AttachmentScanStatus.SKIPPED

        fetched = real_repos.attachment.get_by_id(attachment_id)
        assert fetched.storage_path == storage_path
        assert fetched.uploaded_by == employee.id

    def test_get_by_id_raises_not_found_for_an_unknown_attachment(self, real_repos):
        with pytest.raises(RecordNotFoundError):
            real_repos.attachment.get_by_id(uuid.uuid4())

    def test_list_for_request_excludes_soft_deleted_by_default_and_orders_newest_first(
        self, real_repos, make_test_profile, test_company_id
    ):
        employee, request = self._make_request(real_repos, make_test_profile, test_company_id)

        def _upload(name: str):
            attachment_id = uuid.uuid4()
            path = build_storage_path(
                request_id=request.id, attachment_id=attachment_id, sanitized_file_name=name
            )
            return real_repos.attachment.create_attachment(
                attachment_id=attachment_id,
                request_id=request.id,
                uploaded_by=employee.id,
                file_name=name,
                content_type="application/pdf",
                size_bytes=100,
                storage_path=path,
                checksum_sha256="b" * 64,
            )

        first = _upload("a.pdf")
        second = _upload("b.pdf")
        real_repos.attachment.soft_delete(first.id, deleted_by=employee.id)

        visible = real_repos.attachment.list_for_request(request.id).items
        assert [a.id for a in visible] == [second.id]

        everything = real_repos.attachment.list_for_request(request.id, include_deleted=True).items
        assert {a.id for a in everything} == {first.id, second.id}

    def test_soft_delete_an_attachment(self, real_repos, make_test_profile, test_company_id):
        employee, request = self._make_request(real_repos, make_test_profile, test_company_id)
        attachment_id = uuid.uuid4()
        path = build_storage_path(
            request_id=request.id, attachment_id=attachment_id, sanitized_file_name="a.pdf"
        )
        created = real_repos.attachment.create_attachment(
            attachment_id=attachment_id,
            request_id=request.id,
            uploaded_by=employee.id,
            file_name="a.pdf",
            content_type="application/pdf",
            size_bytes=100,
            storage_path=path,
            checksum_sha256="c" * 64,
        )

        removed = real_repos.attachment.soft_delete(created.id, deleted_by=employee.id)

        assert removed.deleted_at is not None
        assert removed.deleted_by == employee.id

    def test_zero_size_bytes_violates_the_check_constraint(
        self, real_repos, make_test_profile, test_company_id
    ):
        employee, request = self._make_request(real_repos, make_test_profile, test_company_id)
        attachment_id = uuid.uuid4()
        path = build_storage_path(
            request_id=request.id, attachment_id=attachment_id, sanitized_file_name="empty.pdf"
        )

        with pytest.raises(ConstraintViolationError):
            real_repos.attachment.create_attachment(
                attachment_id=attachment_id,
                request_id=request.id,
                uploaded_by=employee.id,
                file_name="empty.pdf",
                content_type="application/pdf",
                size_bytes=0,
                storage_path=path,
                checksum_sha256="d" * 64,
            )

    def test_duplicate_storage_path_violates_the_unique_constraint(
        self, real_repos, make_test_profile, test_company_id
    ):
        employee, request = self._make_request(real_repos, make_test_profile, test_company_id)
        path = build_storage_path(
            request_id=request.id, attachment_id=uuid.uuid4(), sanitized_file_name="dup.pdf"
        )
        real_repos.attachment.create_attachment(
            attachment_id=uuid.uuid4(),
            request_id=request.id,
            uploaded_by=employee.id,
            file_name="dup.pdf",
            content_type="application/pdf",
            size_bytes=100,
            storage_path=path,
            checksum_sha256="e" * 64,
        )

        with pytest.raises(ConstraintViolationError):
            real_repos.attachment.create_attachment(
                attachment_id=uuid.uuid4(),
                request_id=request.id,
                uploaded_by=employee.id,
                file_name="dup2.pdf",
                content_type="application/pdf",
                size_bytes=100,
                storage_path=path,
                checksum_sha256="f" * 64,
            )
