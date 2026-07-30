"""Unit tests for ``app.services.attachment_service.AttachmentService``."""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.database.repositories.base_repository import Page
from app.models.enums import AttachmentScanStatus, UserRole
from app.services.exceptions import (
    NotFoundError,
    PermissionDeniedError,
    StorageOperationError,
    ValidationError,
)
from tests.fixtures.factories import specific_user_stage

pytestmark = pytest.mark.unit

_PDF_BYTES = b"%PDF-1.4 fake pdf content"
_PNG_BYTES = b"\x89PNG\r\n\x1a\nfake png content"


def _submit_with_definition(
    env, employee_identity, approver_profile, make_definition, request_type
):
    make_definition(
        request_type=request_type,
        stages=[specific_user_stage(1, "Manager Review", user_id=approver_profile.id)],
    )
    return env.request_service.create_request(
        employee_identity, request_type=request_type, title="Team lunch"
    )


class TestUploadAttachment:
    def test_requester_can_upload_a_pdf(self, env, employee, approver, make_definition):
        employee_profile, employee_identity = employee
        approver_profile, _ = approver
        request = _submit_with_definition(
            env, employee_identity, approver_profile, make_definition, "expense_reimbursement"
        )

        created = env.attachment_service.upload_attachment(
            employee_identity,
            request.id,
            file_name="receipt.pdf",
            content_type="application/pdf",
            content=_PDF_BYTES,
        )

        assert created.request_id == request.id
        assert created.uploaded_by == employee_profile.id
        assert created.file_name == "receipt.pdf"
        assert created.version == 1
        assert created.replaces_attachment_id is None
        assert created.scan_status is AttachmentScanStatus.SKIPPED
        assert created.size_bytes == len(_PDF_BYTES)
        assert env.attachment_storage.objects[created.storage_path] == _PDF_BYTES

        audit_actions = [a.action for a in env.audit_repo.list_for_request(request.id).items]
        assert "ATTACHMENT_UPLOADED" in audit_actions

    def test_assigned_approver_can_upload(self, env, employee, approver, make_definition):
        _, employee_identity = employee
        approver_profile, approver_identity = approver
        request = _submit_with_definition(
            env, employee_identity, approver_profile, make_definition, "expense_reimbursement"
        )

        created = env.attachment_service.upload_attachment(
            approver_identity,
            request.id,
            file_name="policy.pdf",
            content_type="application/pdf",
            content=_PDF_BYTES,
        )

        assert created.uploaded_by == approver_profile.id

    def test_unrelated_employee_cannot_upload(
        self, env, employee, approver, make_user, make_definition
    ):
        _, employee_identity = employee
        approver_profile, _ = approver
        request = _submit_with_definition(
            env, employee_identity, approver_profile, make_definition, "expense_reimbursement"
        )
        _, other_identity = make_user(role=UserRole.EMPLOYEE, full_name="Outsider")

        with pytest.raises(NotFoundError):
            env.attachment_service.upload_attachment(
                other_identity,
                request.id,
                file_name="snoop.pdf",
                content_type="application/pdf",
                content=_PDF_BYTES,
            )

    def test_invalid_request_id_raises_not_found(self, env, employee):
        _, employee_identity = employee

        with pytest.raises(NotFoundError):
            env.attachment_service.upload_attachment(
                employee_identity,
                uuid4(),
                file_name="receipt.pdf",
                content_type="application/pdf",
                content=_PDF_BYTES,
            )

    def test_disallowed_content_type_is_rejected(self, env, employee, approver, make_definition):
        _, employee_identity = employee
        approver_profile, _ = approver
        request = _submit_with_definition(
            env, employee_identity, approver_profile, make_definition, "expense_reimbursement"
        )

        with pytest.raises(ValidationError):
            env.attachment_service.upload_attachment(
                employee_identity,
                request.id,
                file_name="script.exe",
                content_type="application/x-msdownload",
                content=b"MZ\x90\x00fake-exe",
            )

    def test_empty_file_is_rejected(self, env, employee, approver, make_definition):
        _, employee_identity = employee
        approver_profile, _ = approver
        request = _submit_with_definition(
            env, employee_identity, approver_profile, make_definition, "expense_reimbursement"
        )

        with pytest.raises(ValidationError):
            env.attachment_service.upload_attachment(
                employee_identity,
                request.id,
                file_name="empty.pdf",
                content_type="application/pdf",
                content=b"",
            )

    def test_mismatched_declared_content_type_is_rejected(
        self, env, employee, approver, make_definition
    ):
        _, employee_identity = employee
        approver_profile, _ = approver
        request = _submit_with_definition(
            env, employee_identity, approver_profile, make_definition, "expense_reimbursement"
        )

        with pytest.raises(ValidationError):
            env.attachment_service.upload_attachment(
                employee_identity,
                request.id,
                file_name="disguised.pdf",
                content_type="application/pdf",
                content=_PNG_BYTES,
            )

    def test_infected_scan_result_is_recorded_on_the_attachment(
        self, env, employee, approver, make_definition
    ):
        _, employee_identity = employee
        approver_profile, _ = approver
        request = _submit_with_definition(
            env, employee_identity, approver_profile, make_definition, "expense_reimbursement"
        )
        env.virus_scanner._status = AttachmentScanStatus.INFECTED

        created = env.attachment_service.upload_attachment(
            employee_identity,
            request.id,
            file_name="receipt.pdf",
            content_type="application/pdf",
            content=_PDF_BYTES,
        )

        assert created.scan_status is AttachmentScanStatus.INFECTED
        assert env.virus_scanner.scanned_content == [_PDF_BYTES]

    def test_storage_failure_is_translated_and_no_row_is_created(
        self, env, employee, approver, make_definition
    ):
        _, employee_identity = employee
        approver_profile, _ = approver
        request = _submit_with_definition(
            env, employee_identity, approver_profile, make_definition, "expense_reimbursement"
        )
        env.attachment_storage._raise_on_upload = True

        with pytest.raises(StorageOperationError):
            env.attachment_service.upload_attachment(
                employee_identity,
                request.id,
                file_name="receipt.pdf",
                content_type="application/pdf",
                content=_PDF_BYTES,
            )

        assert env.attachment_repo.list_for_request(request.id).items == []


class TestListAndDownload:
    def test_list_excludes_removed_attachments_and_orders_newest_first(
        self, env, employee, approver, make_definition
    ):
        _, employee_identity = employee
        approver_profile, _ = approver
        request = _submit_with_definition(
            env, employee_identity, approver_profile, make_definition, "expense_reimbursement"
        )
        first = env.attachment_service.upload_attachment(
            employee_identity,
            request.id,
            file_name="a.pdf",
            content_type="application/pdf",
            content=_PDF_BYTES,
        )
        second = env.attachment_service.upload_attachment(
            employee_identity,
            request.id,
            file_name="b.pdf",
            content_type="application/pdf",
            content=_PDF_BYTES,
        )
        env.attachment_service.remove_attachment(employee_identity, first.id)

        items = env.attachment_service.list_attachments(employee_identity, request.id).items

        assert [item.id for item in items] == [second.id]

    def test_unrelated_employee_cannot_list(
        self, env, employee, approver, make_user, make_definition
    ):
        _, employee_identity = employee
        approver_profile, _ = approver
        request = _submit_with_definition(
            env, employee_identity, approver_profile, make_definition, "expense_reimbursement"
        )
        _, other_identity = make_user(role=UserRole.EMPLOYEE, full_name="Outsider")

        with pytest.raises(NotFoundError):
            env.attachment_service.list_attachments(other_identity, request.id)

    def test_authorized_caller_gets_a_signed_download_url(
        self, env, employee, approver, make_definition
    ):
        _, employee_identity = employee
        approver_profile, approver_identity = approver
        request = _submit_with_definition(
            env, employee_identity, approver_profile, make_definition, "expense_reimbursement"
        )
        created = env.attachment_service.upload_attachment(
            employee_identity,
            request.id,
            file_name="a.pdf",
            content_type="application/pdf",
            content=_PDF_BYTES,
        )

        url = env.attachment_service.get_download_url(approver_identity, created.id)

        assert created.storage_path in url

    def test_unrelated_employee_cannot_download(
        self, env, employee, approver, make_user, make_definition
    ):
        _, employee_identity = employee
        approver_profile, _ = approver
        request = _submit_with_definition(
            env, employee_identity, approver_profile, make_definition, "expense_reimbursement"
        )
        created = env.attachment_service.upload_attachment(
            employee_identity,
            request.id,
            file_name="a.pdf",
            content_type="application/pdf",
            content=_PDF_BYTES,
        )
        _, other_identity = make_user(role=UserRole.EMPLOYEE, full_name="Outsider")

        with pytest.raises(NotFoundError):
            env.attachment_service.get_download_url(other_identity, created.id)

    def test_infected_attachment_cannot_be_downloaded(
        self, env, employee, approver, make_definition
    ):
        _, employee_identity = employee
        approver_profile, _ = approver
        request = _submit_with_definition(
            env, employee_identity, approver_profile, make_definition, "expense_reimbursement"
        )
        env.virus_scanner._status = AttachmentScanStatus.INFECTED
        created = env.attachment_service.upload_attachment(
            employee_identity,
            request.id,
            file_name="a.pdf",
            content_type="application/pdf",
            content=_PDF_BYTES,
        )

        with pytest.raises(ValidationError):
            env.attachment_service.get_download_url(employee_identity, created.id)


class TestReplaceAttachment:
    def test_uploader_can_replace_while_pending(self, env, employee, approver, make_definition):
        _, employee_identity = employee
        approver_profile, _ = approver
        request = _submit_with_definition(
            env, employee_identity, approver_profile, make_definition, "expense_reimbursement"
        )
        original = env.attachment_service.upload_attachment(
            employee_identity,
            request.id,
            file_name="v1.pdf",
            content_type="application/pdf",
            content=_PDF_BYTES,
        )

        replaced = env.attachment_service.replace_attachment(
            employee_identity,
            original.id,
            file_name="v2.pdf",
            content_type="application/pdf",
            content=_PDF_BYTES + b" v2",
        )

        assert replaced.version == 2
        assert replaced.replaces_attachment_id == original.id
        # The old row is soft-deleted, but its Storage object is kept.
        stale = env.attachment_repo.get_by_id(original.id)
        assert stale.deleted_at is not None
        assert original.storage_path in env.attachment_storage.objects
        assert replaced.storage_path in env.attachment_storage.objects

    def test_non_uploader_non_admin_cannot_replace(self, env, employee, approver, make_definition):
        _, employee_identity = employee
        approver_profile, approver_identity = approver
        request = _submit_with_definition(
            env, employee_identity, approver_profile, make_definition, "expense_reimbursement"
        )
        original = env.attachment_service.upload_attachment(
            employee_identity,
            request.id,
            file_name="v1.pdf",
            content_type="application/pdf",
            content=_PDF_BYTES,
        )

        with pytest.raises(PermissionDeniedError):
            env.attachment_service.replace_attachment(
                approver_identity,
                original.id,
                file_name="v2.pdf",
                content_type="application/pdf",
                content=_PDF_BYTES,
            )

    def test_admin_can_replace_any_attachment(
        self, env, employee, approver, make_user, make_definition
    ):
        _, employee_identity = employee
        approver_profile, _ = approver
        request = _submit_with_definition(
            env, employee_identity, approver_profile, make_definition, "expense_reimbursement"
        )
        original = env.attachment_service.upload_attachment(
            employee_identity,
            request.id,
            file_name="v1.pdf",
            content_type="application/pdf",
            content=_PDF_BYTES,
        )
        _, admin_identity = make_user(role=UserRole.ADMIN)

        replaced = env.attachment_service.replace_attachment(
            admin_identity,
            original.id,
            file_name="v2.pdf",
            content_type="application/pdf",
            content=_PDF_BYTES,
        )

        assert replaced.uploaded_by == admin_identity.user_id


class TestRemoveAttachment:
    def test_uploader_can_remove_while_pending(self, env, employee, approver, make_definition):
        _, employee_identity = employee
        approver_profile, _ = approver
        request = _submit_with_definition(
            env, employee_identity, approver_profile, make_definition, "expense_reimbursement"
        )
        created = env.attachment_service.upload_attachment(
            employee_identity,
            request.id,
            file_name="a.pdf",
            content_type="application/pdf",
            content=_PDF_BYTES,
        )

        removed = env.attachment_service.remove_attachment(employee_identity, created.id)

        assert removed.deleted_at is not None
        assert created.storage_path not in env.attachment_storage.objects
        audit_actions = [a.action for a in env.audit_repo.list_for_request(request.id).items]
        assert "ATTACHMENT_REMOVED" in audit_actions

    def test_non_uploader_non_admin_cannot_remove(self, env, employee, approver, make_definition):
        _, employee_identity = employee
        approver_profile, approver_identity = approver
        request = _submit_with_definition(
            env, employee_identity, approver_profile, make_definition, "expense_reimbursement"
        )
        created = env.attachment_service.upload_attachment(
            employee_identity,
            request.id,
            file_name="a.pdf",
            content_type="application/pdf",
            content=_PDF_BYTES,
        )

        with pytest.raises(PermissionDeniedError):
            env.attachment_service.remove_attachment(approver_identity, created.id)

    def test_admin_can_remove_any_attachment(
        self, env, employee, approver, make_user, make_definition
    ):
        _, employee_identity = employee
        approver_profile, _ = approver
        request = _submit_with_definition(
            env, employee_identity, approver_profile, make_definition, "expense_reimbursement"
        )
        created = env.attachment_service.upload_attachment(
            employee_identity,
            request.id,
            file_name="a.pdf",
            content_type="application/pdf",
            content=_PDF_BYTES,
        )
        _, admin_identity = make_user(role=UserRole.ADMIN)

        removed = env.attachment_service.remove_attachment(admin_identity, created.id)

        assert removed.deleted_at is not None

    def test_uploader_cannot_remove_once_request_is_no_longer_pending(
        self, env, employee, approver, make_definition
    ):
        _, employee_identity = employee
        approver_profile, approver_identity = approver
        request = _submit_with_definition(
            env, employee_identity, approver_profile, make_definition, "expense_reimbursement"
        )
        created = env.attachment_service.upload_attachment(
            employee_identity,
            request.id,
            file_name="a.pdf",
            content_type="application/pdf",
            content=_PDF_BYTES,
        )
        stage = env.approval_service.list_pending_approvals(
            approver_identity, page=Page(size=10)
        ).items[0]
        env.approval_service.approve_stage(
            approver_identity, stage.id, expected_version=stage.version
        )

        with pytest.raises(PermissionDeniedError):
            env.attachment_service.remove_attachment(employee_identity, created.id)

    def test_invalid_attachment_id_raises_not_found(self, env, employee):
        _, employee_identity = employee

        with pytest.raises(NotFoundError):
            env.attachment_service.remove_attachment(employee_identity, uuid4())


class TestCrossTenantIsolation:
    """Regression coverage for the cross-tenant IDOR fixed in
    ``AttachmentService._authorize_view``/``_get_parent_request``: an
    admin in Company B must never be able to view, list, download,
    replace, or remove an attachment belonging to a Company A request,
    even with a fully valid attachment/request id (guessed, leaked, or
    otherwise obtained). Every case uses an *admin* identity deliberately
    — role-only checks (``can_view_request``/``can_remove_attachment``)
    grant admins unconditional access within their own company, which is
    exactly the class of check that silently had no company comparison
    before this fix.
    """

    def _other_company_admin(self, make_user):
        return make_user(role=UserRole.ADMIN, full_name="Other Co Admin", company_id=uuid4())

    def test_admin_of_another_company_cannot_upload(
        self, env, employee, approver, make_user, make_definition
    ):
        _, employee_identity = employee
        approver_profile, _ = approver
        request = _submit_with_definition(
            env, employee_identity, approver_profile, make_definition, "expense_reimbursement"
        )
        _, other_company_admin = self._other_company_admin(make_user)

        with pytest.raises(NotFoundError):
            env.attachment_service.upload_attachment(
                other_company_admin,
                request.id,
                file_name="snoop.pdf",
                content_type="application/pdf",
                content=_PDF_BYTES,
            )

    def test_admin_of_another_company_cannot_list(
        self, env, employee, approver, make_user, make_definition
    ):
        _, employee_identity = employee
        approver_profile, _ = approver
        request = _submit_with_definition(
            env, employee_identity, approver_profile, make_definition, "expense_reimbursement"
        )
        env.attachment_service.upload_attachment(
            employee_identity,
            request.id,
            file_name="a.pdf",
            content_type="application/pdf",
            content=_PDF_BYTES,
        )
        _, other_company_admin = self._other_company_admin(make_user)

        with pytest.raises(NotFoundError):
            env.attachment_service.list_attachments(other_company_admin, request.id)

    def test_admin_of_another_company_cannot_download(
        self, env, employee, approver, make_user, make_definition
    ):
        _, employee_identity = employee
        approver_profile, _ = approver
        request = _submit_with_definition(
            env, employee_identity, approver_profile, make_definition, "expense_reimbursement"
        )
        created = env.attachment_service.upload_attachment(
            employee_identity,
            request.id,
            file_name="a.pdf",
            content_type="application/pdf",
            content=_PDF_BYTES,
        )
        _, other_company_admin = self._other_company_admin(make_user)

        with pytest.raises(NotFoundError):
            env.attachment_service.get_download_url(other_company_admin, created.id)

    def test_admin_of_another_company_cannot_replace(
        self, env, employee, approver, make_user, make_definition
    ):
        _, employee_identity = employee
        approver_profile, _ = approver
        request = _submit_with_definition(
            env, employee_identity, approver_profile, make_definition, "expense_reimbursement"
        )
        created = env.attachment_service.upload_attachment(
            employee_identity,
            request.id,
            file_name="v1.pdf",
            content_type="application/pdf",
            content=_PDF_BYTES,
        )
        _, other_company_admin = self._other_company_admin(make_user)

        with pytest.raises(NotFoundError):
            env.attachment_service.replace_attachment(
                other_company_admin,
                created.id,
                file_name="v2.pdf",
                content_type="application/pdf",
                content=_PDF_BYTES,
            )
        # Not just denied — untouched: still the original content, unremoved.
        assert env.attachment_repo.get_by_id(created.id).deleted_at is None

    def test_admin_of_another_company_cannot_remove(
        self, env, employee, approver, make_user, make_definition
    ):
        _, employee_identity = employee
        approver_profile, _ = approver
        request = _submit_with_definition(
            env, employee_identity, approver_profile, make_definition, "expense_reimbursement"
        )
        created = env.attachment_service.upload_attachment(
            employee_identity,
            request.id,
            file_name="a.pdf",
            content_type="application/pdf",
            content=_PDF_BYTES,
        )
        _, other_company_admin = self._other_company_admin(make_user)

        with pytest.raises(NotFoundError):
            env.attachment_service.remove_attachment(other_company_admin, created.id)
        assert env.attachment_repo.get_by_id(created.id).deleted_at is None
        assert created.storage_path in env.attachment_storage.objects
