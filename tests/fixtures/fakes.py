"""In-memory fake repositories for deterministic, isolated service-layer tests.

Each ``Fake*Repository`` below exposes the exact public method signatures
of its real counterpart in ``app.database.repositories``, backed by a
plain in-memory dict rather than a Supabase/postgrest client, so the real,
unmodified service classes (``RequestService``, ``ApprovalService``, ...)
can be exercised end-to-end without any network dependency. Two pairs of
fakes intentionally share a single underlying ``FakeTable`` so their
combined behavior matches production exactly: ``FakeWorkflowStageRepository``
and ``FakeApprovalRepository`` both operate on ``workflow_stages`` — a test
fixture must construct both from the same ``FakeTable`` instance.
"""

from __future__ import annotations

import dataclasses
import threading
from collections import Counter
from collections.abc import Sequence
from datetime import datetime
from enum import Enum
from typing import Any, Generic, TypeVar
from uuid import UUID, uuid4

from app.ai.exceptions import AiProviderError
from app.ai.interfaces import AiCompletion
from app.database.exceptions import (
    ConcurrentUpdateError,
    ConstraintViolationError,
    InvalidQueryError,
    RecordNotFoundError,
    StorageError,
)
from app.database.repositories.analytics_repository import (
    ApprovalThroughput,
    StatusBreakdown,
    VolumeByKey,
)
from app.database.repositories.attachment_repository import AttachmentRecord
from app.database.repositories.audit_repository import AuditLogRecord
from app.database.repositories.base_repository import Page, PagedResult
from app.database.repositories.comment_repository import CommentRecord
from app.database.repositories.company_license_repository import CompanyLicenseRecord
from app.database.repositories.company_repository import CompanyRecord
from app.database.repositories.feature_flag_repository import FeatureFlagRecord
from app.database.repositories.invitation_repository import InvitationRecord
from app.database.repositories.notification_preference_repository import (
    NotificationPreferenceRecord,
)
from app.database.repositories.notification_repository import NotificationRecord
from app.database.repositories.request_repository import RequestRecord
from app.database.repositories.saved_filter_repository import SavedFilterRecord
from app.database.repositories.search_history_repository import SearchHistoryRecord
from app.database.repositories.user_repository import ProfileRecord
from app.database.repositories.workflow_repository import (
    StageStatus,
    WorkflowDefinitionRecord,
    WorkflowStageRecord,
)
from app.models.enums import (
    AttachmentScanStatus,
    InvitationStatus,
    NotificationType,
    RequestStatus,
    UserRole,
)
from app.notifications.exceptions import EmailDeliveryError
from app.services.attachment_service import ScanResult
from app.services.exceptions import InvitationConflictError, SupabaseAdminOperationError
from app.utils.datetime_utils import utc_now

__all__ = [
    "FakeTable",
    "FakeProfileRepository",
    "FakeRequestRepository",
    "FakeWorkflowDefinitionRepository",
    "FakeWorkflowStageRepository",
    "FakeApprovalRepository",
    "FakeAuditRepository",
    "FakeNotificationRepository",
    "FakeNotificationPreferenceRepository",
    "FakeCompanyRepository",
    "FakeCompanyLicenseRepository",
    "FakeFeatureFlagRepository",
    "FakePlatformStatsRepository",
    "FakeCommentRepository",
    "FakeAttachmentRepository",
    "FakeAttachmentStorageGateway",
    "FakeInvitationRepository",
    "FakeVirusScanner",
    "FakeEmailSender",
    "FakeInvitationEmailSender",
    "FakeEmailProvider",
    "FakeSupabaseAuthAdminClient",
    "FakeAnalyticsRepository",
    "SentEmail",
    "SentInvitationEmail",
    "SentSupabaseUserCreation",
    "SentSupabaseUserAnonymization",
    "SentProviderEmail",
    "FakeAiProvider",
    "SentAiRequest",
]

T = TypeVar("T")

#: The company (tenant) every fake record defaults to when a test doesn't
#: explicitly pass one — keeps the hundreds of pre-existing, single-tenant
#: -shaped test call sites in this suite working unchanged (they all
#: create/query within this one implicit company), while a dedicated
#: cross-tenant-isolation test can still pass a different company_id
#: explicitly to prove two companies' data never mixes. Production code
#: never has an equivalent default — every real repository method's
#: company_id parameter is required, with no fallback.
DEFAULT_TEST_COMPANY_ID = UUID("00000000-0000-0000-0000-000000000001")


class FakeTable(Generic[T]):
    """A minimal in-memory stand-in for one Supabase table.

    ``update`` reproduces the real ``BaseRepository.update_with_optimistic_lock``
    contract exactly: it raises ``ConcurrentUpdateError`` when the row's
    current version does not match ``expected_version``, under a lock so
    that concurrent callers racing for the same row see the same
    guarantee a real ``UPDATE ... WHERE version = :expected`` would give.
    """

    def __init__(self, table_name: str, *, version_attr: str | None = "version") -> None:
        self.table_name = table_name
        self._version_attr = version_attr
        self._rows: dict[UUID, T] = {}
        self._lock = threading.Lock()

    def insert(self, record: T) -> T:
        self._rows[record.id] = record  # type: ignore[attr-defined]
        return record

    def get(self, record_id: UUID) -> T:
        try:
            return self._rows[record_id]
        except KeyError:
            raise RecordNotFoundError(self.table_name, record_id) from None

    def find(self, record_id: UUID) -> T | None:
        return self._rows.get(record_id)

    def update(self, record_id: UUID, *, expected_version: int, **changes: Any) -> T:
        assert self._version_attr is not None
        with self._lock:
            current = self.get(record_id)
            if getattr(current, self._version_attr) != expected_version:
                raise ConcurrentUpdateError(self.table_name, record_id, expected_version)
            changes[self._version_attr] = expected_version + 1
            updated = dataclasses.replace(current, **changes)  # type: ignore[arg-type]
            self._rows[record_id] = updated
            return updated

    def update_unconditional(self, record_id: UUID, **changes: Any) -> T:
        with self._lock:
            current = self.get(record_id)
            updated = dataclasses.replace(current, **changes)  # type: ignore[arg-type]
            self._rows[record_id] = updated
            return updated

    def delete(self, record_id: UUID) -> None:
        with self._lock:
            self._rows.pop(record_id, None)

    def delete_if_version_matches(self, record_id: UUID, *, expected_version: int) -> bool:
        """Version-guarded delete, mirroring ``update``'s optimistic-lock
        contract: only removes the row if its current version still
        matches ``expected_version``, returning whether it actually
        deleted anything."""
        assert self._version_attr is not None
        with self._lock:
            current = self._rows.get(record_id)
            if current is None or getattr(current, self._version_attr) != expected_version:
                return False
            del self._rows[record_id]
            return True

    def values(self) -> list[T]:
        return list(self._rows.values())


def _paginate(items: list[T], page: Page) -> PagedResult[T]:
    total = len(items)
    start = page.offset
    end = start + page.size
    return PagedResult(
        items=items[start:end], page=page.number, page_size=page.size, total_records=total
    )


class FakeProfileRepository:
    table_name = "profiles"

    def __init__(self) -> None:
        self._table: FakeTable[ProfileRecord] = FakeTable("profiles")

    def get_by_id(self, profile_id: UUID) -> ProfileRecord:
        return self._table.get(profile_id)

    def find_by_id(self, profile_id: UUID) -> ProfileRecord | None:
        return self._table.find(profile_id)

    def find_by_ids(self, profile_ids: Sequence[UUID]) -> list[ProfileRecord]:
        return [record for pid in profile_ids if (record := self._table.find(pid)) is not None]

    def create_profile(
        self,
        *,
        profile_id: UUID,
        full_name: str,
        role: UserRole = UserRole.EMPLOYEE,
        department: str | None = None,
        company_id: UUID = DEFAULT_TEST_COMPANY_ID,
        is_platform_admin: bool = False,
    ) -> ProfileRecord:
        now = utc_now()
        record = ProfileRecord(
            id=profile_id,
            full_name=full_name,
            role=role,
            department=department,
            version=1,
            created_at=now,
            updated_at=now,
            company_id=company_id,
            is_platform_admin=is_platform_admin,
            is_active=True,
            deleted_at=None,
            deleted_by=None,
        )
        return self._table.insert(record)

    def update_profile(
        self,
        profile_id: UUID,
        *,
        expected_version: int,
        full_name: str | None = None,
        role: UserRole | None = None,
        department: str | None = None,
        is_active: bool | None = None,
    ) -> ProfileRecord:
        changes: dict[str, Any] = {"updated_at": utc_now()}
        if full_name is not None:
            changes["full_name"] = full_name
        if role is not None:
            changes["role"] = role
        if department is not None:
            changes["department"] = department
        if is_active is not None:
            changes["is_active"] = is_active
        if len(changes) == 1:
            raise InvalidQueryError("update_profile requires at least one field to update.")
        return self._table.update(profile_id, expected_version=expected_version, **changes)

    def erase(
        self,
        profile_id: UUID,
        *,
        expected_version: int,
        deleted_by: UUID,
        anonymized_full_name: str,
    ) -> ProfileRecord:
        return self._table.update(
            profile_id,
            expected_version=expected_version,
            updated_at=utc_now(),
            deleted_at=utc_now(),
            deleted_by=deleted_by,
            is_active=False,
            full_name=anonymized_full_name,
            department=None,
        )

    def list_by_role(
        self,
        role: UserRole,
        *,
        company_id: UUID = DEFAULT_TEST_COMPANY_ID,
        department: str | None = None,
        include_deleted: bool = False,
        page: Page = Page(),
    ) -> PagedResult[ProfileRecord]:
        items = [
            p
            for p in self._table.values()
            if p.role is role
            and p.company_id == company_id
            and (department is None or p.department == department)
            and (include_deleted or p.deleted_at is None)
        ]
        items.sort(key=lambda p: p.full_name)
        return _paginate(items, page)

    def search_by_name(
        self,
        query_text: str,
        *,
        company_id: UUID = DEFAULT_TEST_COMPANY_ID,
        include_deleted: bool = False,
        page: Page = Page(),
    ) -> PagedResult[ProfileRecord]:
        if not query_text or not query_text.strip():
            raise InvalidQueryError("search_by_name requires a non-empty query_text.")
        needle = query_text.strip().lower()
        items = [
            p
            for p in self._table.values()
            if needle in p.full_name.lower()
            and p.company_id == company_id
            and (include_deleted or p.deleted_at is None)
        ]
        items.sort(key=lambda p: p.full_name)
        return _paginate(items, page)

    def count_for_company(self, company_id: UUID) -> int:
        return len(
            [
                p
                for p in self._table.values()
                if p.company_id == company_id and p.deleted_at is None
            ]
        )


class FakeRequestRepository:
    table_name = "requests"

    def __init__(self) -> None:
        self._table: FakeTable[RequestRecord] = FakeTable("requests")

    def get_by_id(self, request_id: UUID) -> RequestRecord:
        return self._table.get(request_id)

    def find_by_id(self, request_id: UUID) -> RequestRecord | None:
        return self._table.find(request_id)

    def create_request(
        self,
        *,
        requester_id: UUID,
        workflow_definition_id: UUID,
        request_type: str,
        title: str,
        description: str | None = None,
        department: str | None = None,
        company_id: UUID = DEFAULT_TEST_COMPANY_ID,
    ) -> RequestRecord:
        now = utc_now()
        record = RequestRecord(
            id=uuid4(),
            requester_id=requester_id,
            workflow_definition_id=workflow_definition_id,
            request_type=request_type,
            title=title,
            description=description,
            department=department,
            status=RequestStatus.PENDING,
            current_stage_id=None,
            version=1,
            deleted_at=None,
            deleted_by=None,
            created_at=now,
            updated_at=now,
            completed_at=None,
            company_id=company_id,
        )
        return self._table.insert(record)

    def set_current_stage(
        self,
        request_id: UUID,
        *,
        expected_version: int,
        current_stage_id: UUID | None,
        status: RequestStatus,
        completed_at=None,
    ) -> RequestRecord:
        changes: dict[str, Any] = {
            "current_stage_id": current_stage_id,
            "status": status,
            "updated_at": utc_now(),
            "completed_at": completed_at,
        }
        return self._table.update(request_id, expected_version=expected_version, **changes)

    def update_editable_fields(
        self,
        request_id: UUID,
        *,
        expected_version: int,
        title: str | None = None,
        description: str | None = None,
        department: str | None = None,
    ) -> RequestRecord:
        changes: dict[str, Any] = {"updated_at": utc_now()}
        if title is not None:
            changes["title"] = title
        if description is not None:
            changes["description"] = description
        if department is not None:
            changes["department"] = department
        if len(changes) == 1:
            raise InvalidQueryError("update_editable_fields requires at least one field to update.")
        return self._table.update(request_id, expected_version=expected_version, **changes)

    def soft_delete(
        self, request_id: UUID, *, expected_version: int, deleted_by: UUID
    ) -> RequestRecord:
        return self._table.update(
            request_id,
            expected_version=expected_version,
            deleted_at=utc_now(),
            deleted_by=deleted_by,
            updated_at=utc_now(),
        )

    def list_requests(
        self,
        *,
        company_id: UUID = DEFAULT_TEST_COMPANY_ID,
        status: RequestStatus | None = None,
        request_type: str | None = None,
        department: str | None = None,
        requester_id: UUID | None = None,
        request_ids: Sequence[UUID] | None = None,
        created_after=None,
        created_before=None,
        include_deleted: bool = False,
        sort_descending_by_created_at: bool = True,
        page: Page = Page(),
    ) -> PagedResult[RequestRecord]:
        items = [r for r in self._table.values() if r.company_id == company_id]
        if status is not None:
            items = [r for r in items if r.status is status]
        if request_type is not None:
            items = [r for r in items if r.request_type == request_type]
        if department is not None:
            items = [r for r in items if r.department == department]
        if requester_id is not None:
            items = [r for r in items if r.requester_id == requester_id]
        if request_ids is not None:
            request_id_set = set(request_ids)
            items = [r for r in items if r.id in request_id_set]
        if created_after is not None:
            items = [r for r in items if r.created_at >= created_after]
        if created_before is not None:
            items = [r for r in items if r.created_at <= created_before]
        if not include_deleted:
            items = [r for r in items if r.deleted_at is None]
        items.sort(key=lambda r: r.created_at, reverse=sort_descending_by_created_at)
        return _paginate(items, page)

    def search_requests(
        self,
        query_text: str,
        *,
        company_id: UUID = DEFAULT_TEST_COMPANY_ID,
        requester_id: UUID | None = None,
        request_ids: Sequence[UUID] | None = None,
        include_deleted: bool = False,
        page: Page = Page(),
    ) -> PagedResult[RequestRecord]:
        if not query_text or not query_text.strip():
            raise InvalidQueryError("search_requests requires a non-empty query_text.")
        needle = query_text.strip().lower()
        items = [
            r
            for r in self._table.values()
            if (needle in r.title.lower() or (r.description and needle in r.description.lower()))
            and r.company_id == company_id
        ]
        if requester_id is not None:
            items = [r for r in items if r.requester_id == requester_id]
        if request_ids is not None:
            request_id_set = set(request_ids)
            items = [r for r in items if r.id in request_id_set]
        if not include_deleted:
            items = [r for r in items if r.deleted_at is None]
        items.sort(key=lambda r: r.created_at, reverse=True)
        return _paginate(items, page)


class FakeWorkflowDefinitionRepository:
    table_name = "workflow_definitions"

    def __init__(self) -> None:
        self._table: FakeTable[WorkflowDefinitionRecord] = FakeTable(
            "workflow_definitions", version_attr="row_version"
        )

    def get_by_id(self, definition_id: UUID) -> WorkflowDefinitionRecord:
        return self._table.get(definition_id)

    def get_by_id_for_company(
        self, definition_id: UUID, *, company_id: UUID
    ) -> WorkflowDefinitionRecord:
        record = self.get_by_id(definition_id)
        if record.company_id != company_id:
            raise RecordNotFoundError("workflow_definition", definition_id)
        return record

    def list_by_ids(
        self,
        definition_ids: list[UUID],
        *,
        company_id: UUID,
        page: Page = Page(size=100),
    ) -> PagedResult[WorkflowDefinitionRecord]:
        if not definition_ids:
            return _paginate([], page)
        ids = set(definition_ids)
        items = [d for d in self._table.values() if d.id in ids and d.company_id == company_id]
        return _paginate(items, page)

    def find_active_for_request_type(
        self, request_type: str, *, company_id: UUID = DEFAULT_TEST_COMPANY_ID
    ) -> WorkflowDefinitionRecord | None:
        matches = [
            d
            for d in self._table.values()
            if d.request_type == request_type and d.is_active and d.company_id == company_id
        ]
        return matches[0] if matches else None

    def create_definition(
        self,
        *,
        request_type: str,
        version: int,
        definition: dict[str, Any],
        created_by: UUID,
        company_id: UUID = DEFAULT_TEST_COMPANY_ID,
    ) -> WorkflowDefinitionRecord:
        record = WorkflowDefinitionRecord(
            id=uuid4(),
            request_type=request_type,
            version=version,
            definition=definition,
            is_active=False,
            created_by=created_by,
            row_version=1,
            created_at=utc_now(),
            company_id=company_id,
        )
        return self._table.insert(record)

    def update_inactive_definition(
        self, definition_id: UUID, *, expected_row_version: int, definition: dict[str, Any]
    ) -> WorkflowDefinitionRecord:
        return self._table.update(
            definition_id, expected_version=expected_row_version, definition=definition
        )

    def activate_definition(
        self,
        definition_id: UUID,
        *,
        request_type: str,
        expected_row_version: int,
        company_id: UUID = DEFAULT_TEST_COMPANY_ID,
    ) -> WorkflowDefinitionRecord:
        current_active = self.find_active_for_request_type(request_type, company_id=company_id)
        if current_active is not None and current_active.id != definition_id:
            self._table.update_unconditional(
                current_active.id, is_active=False, row_version=current_active.row_version + 1
            )
        return self._table.update(
            definition_id, expected_version=expected_row_version, is_active=True
        )

    def list_definitions(
        self,
        *,
        company_id: UUID = DEFAULT_TEST_COMPANY_ID,
        request_type: str | None = None,
        is_active: bool | None = None,
        page: Page = Page(),
    ) -> PagedResult[WorkflowDefinitionRecord]:
        items = [d for d in self._table.values() if d.company_id == company_id]
        if request_type is not None:
            items = [d for d in items if d.request_type == request_type]
        if is_active is not None:
            items = [d for d in items if d.is_active == is_active]
        items.sort(key=lambda d: d.created_at, reverse=True)
        return _paginate(items, page)

    def search_definitions(
        self,
        query_text: str,
        *,
        company_id: UUID = DEFAULT_TEST_COMPANY_ID,
        is_active: bool | None = None,
        page: Page = Page(),
    ) -> PagedResult[WorkflowDefinitionRecord]:
        if not query_text or not query_text.strip():
            raise InvalidQueryError("search_definitions requires a non-empty query_text.")
        needle = query_text.strip().lower()
        items = [
            d
            for d in self._table.values()
            if needle in d.request_type.lower() and d.company_id == company_id
        ]
        if is_active is not None:
            items = [d for d in items if d.is_active == is_active]
        items.sort(key=lambda d: d.created_at, reverse=True)
        return _paginate(items, page)


class FakeWorkflowStageRepository:
    """Structural reads/creation on ``workflow_stages``, sharing a table with ``FakeApprovalRepository``."""

    table_name = "workflow_stages"

    def __init__(self, table: FakeTable[WorkflowStageRecord]) -> None:
        self._table = table

    def get_by_id(self, stage_id: UUID) -> WorkflowStageRecord:
        return self._table.get(stage_id)

    def get_by_id_for_company(self, stage_id: UUID, *, company_id: UUID) -> WorkflowStageRecord:
        record = self.get_by_id(stage_id)
        if record.company_id != company_id:
            raise RecordNotFoundError("workflow_stage", stage_id)
        return record

    def create_stage(
        self,
        *,
        request_id: UUID,
        stage_order: int,
        stage_name: str,
        assigned_role: UserRole | None = None,
        assigned_to: UUID | None = None,
        company_id: UUID = DEFAULT_TEST_COMPANY_ID,
    ) -> WorkflowStageRecord:
        record = WorkflowStageRecord(
            id=uuid4(),
            request_id=request_id,
            stage_order=stage_order,
            stage_name=stage_name,
            assigned_role=assigned_role,
            assigned_to=assigned_to,
            status=StageStatus.PENDING,
            decided_by=None,
            decided_at=None,
            decision_note=None,
            version=1,
            created_at=utc_now(),
            company_id=company_id,
        )
        return self._table.insert(record)

    def delete_if_unchanged(self, stage_id: UUID, *, expected_version: int) -> bool:
        return self._table.delete_if_version_matches(stage_id, expected_version=expected_version)

    def list_for_request(
        self, request_id: UUID, *, page: Page = Page(size=100)
    ) -> PagedResult[WorkflowStageRecord]:
        items = [s for s in self._table.values() if s.request_id == request_id]
        items.sort(key=lambda s: s.stage_order)
        return _paginate(items, page)

    def get_highest_stage_order(self, request_id: UUID) -> int:
        orders = [s.stage_order for s in self._table.values() if s.request_id == request_id]
        return max(orders) if orders else 0

    def list_decided_for_request(
        self, request_id: UUID, *, page: Page = Page(size=100)
    ) -> PagedResult[WorkflowStageRecord]:
        items = [
            s
            for s in self._table.values()
            if s.request_id == request_id and s.status is not StageStatus.PENDING
        ]
        items.sort(key=lambda s: s.stage_order)
        return _paginate(items, page)

    def list_decided(
        self,
        *,
        company_id: UUID = DEFAULT_TEST_COMPANY_ID,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
        page: Page = Page(size=100),
    ) -> PagedResult[WorkflowStageRecord]:
        items = [
            s
            for s in self._table.values()
            if s.company_id == company_id
            and s.status in (StageStatus.APPROVED, StageStatus.REJECTED)
        ]
        if created_after is not None:
            items = [s for s in items if s.created_at >= created_after]
        if created_before is not None:
            items = [s for s in items if s.created_at <= created_before]
        items.sort(key=lambda s: s.created_at, reverse=True)
        return _paginate(items, page)


class FakeApprovalRepository:
    """Decision-specific mutations on ``workflow_stages``, sharing a table with ``FakeWorkflowStageRepository``."""

    table_name = "workflow_stages"

    def __init__(self, table: FakeTable[WorkflowStageRecord]) -> None:
        self._table = table

    def approve_stage(
        self,
        stage_id: UUID,
        *,
        expected_version: int,
        decided_by: UUID,
        decision_note: str | None = None,
    ) -> WorkflowStageRecord:
        return self._table.update(
            stage_id,
            expected_version=expected_version,
            status=StageStatus.APPROVED,
            decided_by=decided_by,
            decided_at=utc_now(),
            decision_note=decision_note,
        )

    def reject_stage(
        self, stage_id: UUID, *, expected_version: int, decided_by: UUID, decision_note: str
    ) -> WorkflowStageRecord:
        if not decision_note or not decision_note.strip():
            raise InvalidQueryError("reject_stage requires a non-empty decision_note.")
        return self._table.update(
            stage_id,
            expected_version=expected_version,
            status=StageStatus.REJECTED,
            decided_by=decided_by,
            decided_at=utc_now(),
            decision_note=decision_note,
        )

    def escalate_stage(
        self,
        stage_id: UUID,
        *,
        expected_version: int,
        new_assigned_to: UUID | None,
        new_assigned_role: UserRole | None,
    ) -> WorkflowStageRecord:
        return self._table.update(
            stage_id,
            expected_version=expected_version,
            assigned_to=new_assigned_to,
            assigned_role=new_assigned_role,
        )

    def revert_to_pending(self, stage_id: UUID, *, expected_version: int) -> WorkflowStageRecord:
        return self._table.update(
            stage_id,
            expected_version=expected_version,
            status=StageStatus.PENDING,
            decided_by=None,
            decided_at=None,
            decision_note=None,
        )

    def list_pending_for_approver(
        self,
        *,
        company_id: UUID = DEFAULT_TEST_COMPANY_ID,
        assigned_to: UUID | None = None,
        assigned_role: UserRole | None = None,
        page: Page = Page(),
    ) -> PagedResult[WorkflowStageRecord]:
        if assigned_to is None and assigned_role is None:
            raise InvalidQueryError(
                "list_pending_for_approver requires at least one of assigned_to or assigned_role."
            )
        items = [
            s
            for s in self._table.values()
            if s.status is StageStatus.PENDING and s.company_id == company_id
        ]
        if assigned_to is not None and assigned_role is not None:
            items = [
                s for s in items if s.assigned_to == assigned_to or s.assigned_role is assigned_role
            ]
        elif assigned_to is not None:
            items = [s for s in items if s.assigned_to == assigned_to]
        else:
            items = [s for s in items if s.assigned_role is assigned_role]
        items.sort(key=lambda s: s.created_at)
        return _paginate(items, page)

    def list_overdue_stages(
        self,
        *,
        created_before,
        company_id: UUID,
        page: Page = Page(size=100),
    ) -> PagedResult[WorkflowStageRecord]:
        items = [
            s
            for s in self._table.values()
            if s.status is StageStatus.PENDING
            and s.created_at <= created_before
            and s.company_id == company_id
        ]
        items.sort(key=lambda s: s.created_at)
        return _paginate(items, page)

    def list_overdue_stages_all_companies(
        self,
        *,
        created_before,
        page: Page = Page(size=100),
    ) -> PagedResult[WorkflowStageRecord]:
        items = [
            s
            for s in self._table.values()
            if s.status is StageStatus.PENDING and s.created_at <= created_before
        ]
        items.sort(key=lambda s: s.created_at)
        return _paginate(items, page)


class FakeAuditRepository:
    table_name = "audit_logs"

    def __init__(self) -> None:
        self._table: FakeTable[AuditLogRecord] = FakeTable("audit_logs", version_attr=None)

    def record_event(
        self,
        *,
        action: Any,
        actor_id: UUID | None = None,
        request_id: UUID | None = None,
        metadata: dict[str, Any] | None = None,
        company_id: UUID | None = DEFAULT_TEST_COMPANY_ID,
    ) -> AuditLogRecord:
        action_value = action.value if isinstance(action, Enum) else action
        record = AuditLogRecord(
            id=uuid4(),
            actor_id=actor_id,
            request_id=request_id,
            action=action_value,
            metadata=metadata,
            created_at=utc_now(),
            company_id=company_id,
        )
        return self._table.insert(record)

    def get_by_id(self, audit_log_id: UUID) -> AuditLogRecord:
        return self._table.get(audit_log_id)

    def list_for_request(
        self, request_id: UUID, *, page: Page = Page(size=100)
    ) -> PagedResult[AuditLogRecord]:
        items = [a for a in self._table.values() if a.request_id == request_id]
        items.sort(key=lambda a: a.created_at)
        return _paginate(items, page)

    def list_for_actor(self, actor_id: UUID, *, page: Page = Page()) -> PagedResult[AuditLogRecord]:
        items = [a for a in self._table.values() if a.actor_id == actor_id]
        items.sort(key=lambda a: a.created_at, reverse=True)
        return _paginate(items, page)

    def list_all(
        self,
        *,
        company_id: UUID = DEFAULT_TEST_COMPANY_ID,
        actor_id: UUID | None = None,
        action: str | None = None,
        created_after=None,
        created_before=None,
        page: Page = Page(),
    ) -> PagedResult[AuditLogRecord]:
        items = [a for a in self._table.values() if a.company_id == company_id]
        if actor_id is not None:
            items = [a for a in items if a.actor_id == actor_id]
        if action is not None:
            items = [a for a in items if a.action == action]
        if created_after is not None:
            items = [a for a in items if a.created_at >= created_after]
        if created_before is not None:
            items = [a for a in items if a.created_at <= created_before]
        items.sort(key=lambda a: a.created_at, reverse=True)
        return _paginate(items, page)

    def search(
        self, query_text: str, *, request_ids: Sequence[UUID] | None = None, page: Page = Page()
    ) -> PagedResult[AuditLogRecord]:
        if not query_text or not query_text.strip():
            raise InvalidQueryError("search requires a non-empty query_text.")
        needle = query_text.strip().lower()
        items = [a for a in self._table.values() if needle in a.action.lower()]
        if request_ids is not None:
            request_id_set = set(request_ids)
            items = [a for a in items if a.request_id in request_id_set]
        items.sort(key=lambda a: a.created_at, reverse=True)
        return _paginate(items, page)

    def list_platform_wide(
        self,
        *,
        company_id: UUID | None = None,
        actor_id: UUID | None = None,
        action: str | None = None,
        created_after=None,
        created_before=None,
        page: Page = Page(),
    ) -> PagedResult[AuditLogRecord]:
        items = list(self._table.values())
        if company_id is not None:
            items = [a for a in items if a.company_id == company_id]
        if actor_id is not None:
            items = [a for a in items if a.actor_id == actor_id]
        if action is not None:
            items = [a for a in items if a.action == action]
        if created_after is not None:
            items = [a for a in items if a.created_at >= created_after]
        if created_before is not None:
            items = [a for a in items if a.created_at <= created_before]
        items.sort(key=lambda a: a.created_at, reverse=True)
        return _paginate(items, page)


class FakeNotificationRepository:
    table_name = "notifications"

    def __init__(self) -> None:
        self._table: FakeTable[NotificationRecord] = FakeTable("notifications", version_attr=None)

    def get_by_id(self, notification_id: UUID) -> NotificationRecord:
        return self._table.get(notification_id)

    def create_notification(
        self,
        *,
        recipient_id: UUID,
        notification_type: NotificationType,
        message: str,
        request_id: UUID | None = None,
    ) -> NotificationRecord:
        record = NotificationRecord(
            id=uuid4(),
            recipient_id=recipient_id,
            request_id=request_id,
            notification_type=notification_type,
            message=message,
            is_read=False,
            read_at=None,
            email_sent=False,
            email_sent_at=None,
            archived_at=None,
            created_at=utc_now(),
        )
        return self._table.insert(record)

    def mark_read(self, notification_id: UUID) -> NotificationRecord:
        return self._table.update_unconditional(notification_id, is_read=True, read_at=utc_now())

    def mark_all_read(self, recipient_id: UUID) -> int:
        unread = [
            n for n in self._table.values() if n.recipient_id == recipient_id and not n.is_read
        ]
        for notification in unread:
            self._table.update_unconditional(notification.id, is_read=True, read_at=utc_now())
        return len(unread)

    def archive(self, notification_id: UUID) -> NotificationRecord:
        return self._table.update_unconditional(notification_id, archived_at=utc_now())

    def unarchive(self, notification_id: UUID) -> NotificationRecord:
        return self._table.update_unconditional(notification_id, archived_at=None)

    def mark_email_sent(self, notification_id: UUID) -> NotificationRecord:
        return self._table.update_unconditional(
            notification_id, email_sent=True, email_sent_at=utc_now()
        )

    def list_for_recipient(
        self,
        recipient_id: UUID,
        *,
        is_read: bool | None = None,
        notification_type: NotificationType | None = None,
        is_archived: bool | None = False,
        search: str | None = None,
        page: Page = Page(),
    ) -> PagedResult[NotificationRecord]:
        items = [n for n in self._table.values() if n.recipient_id == recipient_id]
        if is_read is not None:
            items = [n for n in items if n.is_read == is_read]
        if notification_type is not None:
            items = [n for n in items if n.notification_type == notification_type]
        if is_archived is not None:
            items = [n for n in items if (n.archived_at is not None) == is_archived]
        if search:
            needle = search.strip().lower()
            items = [n for n in items if needle in n.message.lower()]
        items.sort(key=lambda n: n.created_at, reverse=True)
        return _paginate(items, page)

    def get_unread_count(self, recipient_id: UUID) -> int:
        return len(
            [
                n
                for n in self._table.values()
                if n.recipient_id == recipient_id and not n.is_read and n.archived_at is None
            ]
        )

    def search_for_recipient(
        self, query_text: str, recipient_id: UUID, *, page: Page = Page()
    ) -> PagedResult[NotificationRecord]:
        return self.list_for_recipient(recipient_id, is_archived=None, search=query_text, page=page)


class FakeNotificationPreferenceRepository:
    table_name = "notification_preferences"

    def __init__(self) -> None:
        self._table: FakeTable[NotificationPreferenceRecord] = FakeTable(
            "notification_preferences", version_attr=None
        )

    def get_for_user(self, user_id: UUID) -> list[NotificationPreferenceRecord]:
        return [record for record in self._table.values() if record.user_id == user_id]

    def upsert(
        self,
        user_id: UUID,
        notification_type: NotificationType,
        *,
        in_app_enabled: bool,
        email_enabled: bool,
    ) -> NotificationPreferenceRecord:
        existing = next(
            (
                record
                for record in self._table.values()
                if record.user_id == user_id and record.notification_type == notification_type
            ),
            None,
        )
        now = utc_now()
        if existing is None:
            record = NotificationPreferenceRecord(
                id=uuid4(),
                user_id=user_id,
                notification_type=notification_type,
                in_app_enabled=in_app_enabled,
                email_enabled=email_enabled,
                created_at=now,
                updated_at=now,
            )
            return self._table.insert(record)
        return self._table.update_unconditional(
            existing.id,
            in_app_enabled=in_app_enabled,
            email_enabled=email_enabled,
            updated_at=now,
        )


class FakeCommentRepository:
    table_name = "comments"

    def __init__(self) -> None:
        self._table: FakeTable[CommentRecord] = FakeTable("comments", version_attr=None)

    def get_by_id(self, comment_id: UUID) -> CommentRecord:
        return self._table.get(comment_id)

    def find_by_id(self, comment_id: UUID) -> CommentRecord | None:
        return self._table.find(comment_id)

    def create_comment(
        self, *, request_id: UUID, author_id: UUID, body: str, parent_comment_id: UUID | None = None
    ) -> CommentRecord:
        record = CommentRecord(
            id=uuid4(),
            request_id=request_id,
            author_id=author_id,
            parent_comment_id=parent_comment_id,
            body=body,
            deleted_at=None,
            deleted_by=None,
            created_at=utc_now(),
        )
        return self._table.insert(record)

    def list_for_request(
        self, request_id: UUID, *, page: Page = Page(size=100)
    ) -> PagedResult[CommentRecord]:
        items = [c for c in self._table.values() if c.request_id == request_id]
        items.sort(key=lambda c: c.created_at)
        return _paginate(items, page)

    def search(
        self,
        query_text: str,
        *,
        request_ids: Sequence[UUID] | None = None,
        include_deleted: bool = False,
        page: Page = Page(),
    ) -> PagedResult[CommentRecord]:
        if not query_text or not query_text.strip():
            raise InvalidQueryError("search requires a non-empty query_text.")
        needle = query_text.strip().lower()
        items = [c for c in self._table.values() if needle in c.body.lower()]
        if request_ids is not None:
            request_id_set = set(request_ids)
            items = [c for c in items if c.request_id in request_id_set]
        if not include_deleted:
            items = [c for c in items if c.deleted_at is None]
        items.sort(key=lambda c: c.created_at, reverse=True)
        return _paginate(items, page)

    def soft_delete(self, comment_id: UUID, *, deleted_by: UUID) -> CommentRecord:
        return self._table.update_unconditional(
            comment_id, deleted_at=utc_now(), deleted_by=deleted_by
        )


class FakeAttachmentRepository:
    table_name = "attachments"

    def __init__(self) -> None:
        self._table: FakeTable[AttachmentRecord] = FakeTable("attachments", version_attr=None)

    def get_by_id(self, attachment_id: UUID) -> AttachmentRecord:
        return self._table.get(attachment_id)

    def find_by_id(self, attachment_id: UUID) -> AttachmentRecord | None:
        return self._table.find(attachment_id)

    def create_attachment(
        self,
        *,
        attachment_id: UUID,
        request_id: UUID,
        uploaded_by: UUID,
        file_name: str,
        content_type: str,
        size_bytes: int,
        storage_path: str,
        checksum_sha256: str,
        version: int = 1,
        replaces_attachment_id: UUID | None = None,
        scan_status: AttachmentScanStatus = AttachmentScanStatus.SKIPPED,
    ) -> AttachmentRecord:
        existing_paths = {a.storage_path for a in self._table.values()}
        if storage_path in existing_paths:
            raise InvalidQueryError(
                f"storage_path '{storage_path}' already exists (unique constraint)."
            )
        if size_bytes <= 0:
            raise InvalidQueryError("size_bytes must be > 0 (check constraint).")
        record = AttachmentRecord(
            id=attachment_id,
            request_id=request_id,
            uploaded_by=uploaded_by,
            file_name=file_name,
            content_type=content_type,
            size_bytes=size_bytes,
            storage_path=storage_path,
            checksum_sha256=checksum_sha256,
            version=version,
            replaces_attachment_id=replaces_attachment_id,
            scan_status=scan_status,
            deleted_at=None,
            deleted_by=None,
            created_at=utc_now(),
        )
        return self._table.insert(record)

    def list_for_request(
        self, request_id: UUID, *, include_deleted: bool = False, page: Page = Page(size=100)
    ) -> PagedResult[AttachmentRecord]:
        items = [a for a in self._table.values() if a.request_id == request_id]
        if not include_deleted:
            items = [a for a in items if a.deleted_at is None]
        items.sort(key=lambda a: a.created_at, reverse=True)
        return _paginate(items, page)

    def soft_delete(self, attachment_id: UUID, *, deleted_by: UUID) -> AttachmentRecord:
        return self._table.update_unconditional(
            attachment_id, deleted_at=utc_now(), deleted_by=deleted_by
        )

    def search(
        self,
        query_text: str,
        *,
        request_ids: Sequence[UUID] | None = None,
        include_deleted: bool = False,
        page: Page = Page(),
    ) -> PagedResult[AttachmentRecord]:
        if not query_text or not query_text.strip():
            raise InvalidQueryError("search requires a non-empty query_text.")
        needle = query_text.strip().lower()
        items = [a for a in self._table.values() if needle in a.file_name.lower()]
        if request_ids is not None:
            request_id_set = set(request_ids)
            items = [a for a in items if a.request_id in request_id_set]
        if not include_deleted:
            items = [a for a in items if a.deleted_at is None]
        items.sort(key=lambda a: a.created_at, reverse=True)
        return _paginate(items, page)


class FakeInvitationRepository:
    """In-memory analogue of ``InvitationRepository``, replicating the
    partial-unique-index behavior (``lower(email) where status =
    'pending'``) the real ``user_invitations`` table enforces, so a
    future ``InvitationService``'s duplicate-pending-invite handling can
    be exercised the same way against either backend.
    """

    table_name = "user_invitations"

    def __init__(self) -> None:
        self._table: FakeTable[InvitationRecord] = FakeTable("user_invitations")

    def get_by_id(self, invitation_id: UUID) -> InvitationRecord:
        return self._table.get(invitation_id)

    def find_by_id(self, invitation_id: UUID) -> InvitationRecord | None:
        return self._table.find(invitation_id)

    def create_invitation(
        self,
        *,
        email: str,
        full_name: str,
        role: UserRole = UserRole.EMPLOYEE,
        department: str | None = None,
        token_hash: str,
        expires_at,
        invited_by: UUID,
        company_id: UUID = DEFAULT_TEST_COMPANY_ID,
    ) -> InvitationRecord:
        if self.find_pending_by_email(email, company_id=company_id) is not None:
            raise InvalidQueryError(
                f"a pending invitation for '{email}' already exists (unique constraint)."
            )
        now = utc_now()
        record = InvitationRecord(
            id=uuid4(),
            email=email,
            full_name=full_name,
            role=role,
            department=department,
            token_hash=token_hash,
            status=InvitationStatus.PENDING,
            invited_by=invited_by,
            expires_at=expires_at,
            accepted_at=None,
            revoked_at=None,
            accepted_profile_id=None,
            resend_count=0,
            version=1,
            created_at=now,
            updated_at=now,
            company_id=company_id,
        )
        return self._table.insert(record)

    def find_by_token_hash(self, token_hash: str) -> InvitationRecord | None:
        matches = [i for i in self._table.values() if i.token_hash == token_hash]
        return matches[0] if matches else None

    def find_pending_by_email(
        self, email: str, *, company_id: UUID = DEFAULT_TEST_COMPANY_ID
    ) -> InvitationRecord | None:
        needle = email.strip().lower()
        matches = [
            i
            for i in self._table.values()
            if i.status is InvitationStatus.PENDING
            and i.email.strip().lower() == needle
            and i.company_id == company_id
        ]
        return matches[0] if matches else None

    def list_invitations(
        self,
        *,
        company_id: UUID = DEFAULT_TEST_COMPANY_ID,
        status: InvitationStatus | None = None,
        query: str | None = None,
        expires_after: datetime | None = None,
        expires_at_or_before: datetime | None = None,
        page: Page = Page(),
    ) -> PagedResult[InvitationRecord]:
        items = [i for i in self._table.values() if i.company_id == company_id]
        if status is not None:
            items = [i for i in items if i.status is status]
        if expires_after is not None:
            items = [i for i in items if i.expires_at > expires_after]
        if expires_at_or_before is not None:
            items = [i for i in items if i.expires_at <= expires_at_or_before]
        if query is not None:
            if not query.strip():
                raise InvalidQueryError(
                    "list_invitations requires a non-empty query when provided."
                )
            needle = query.strip().lower()
            items = [i for i in items if needle in i.full_name.lower() or needle in i.email.lower()]
        items.sort(key=lambda i: i.created_at, reverse=True)
        return _paginate(items, page)

    def update_status_with_lock(
        self,
        invitation_id: UUID,
        *,
        expected_version: int,
        status: InvitationStatus,
        token_hash: str | None = None,
        expires_at=None,
        accepted_at=None,
        revoked_at=None,
        accepted_profile_id: UUID | None = None,
        resend_count: int | None = None,
    ) -> InvitationRecord:
        changes: dict[str, Any] = {"status": status, "updated_at": utc_now()}
        if token_hash is not None:
            changes["token_hash"] = token_hash
        if expires_at is not None:
            changes["expires_at"] = expires_at
        if accepted_at is not None:
            changes["accepted_at"] = accepted_at
        if revoked_at is not None:
            changes["revoked_at"] = revoked_at
        if accepted_profile_id is not None:
            changes["accepted_profile_id"] = accepted_profile_id
        if resend_count is not None:
            changes["resend_count"] = resend_count
        return self._table.update(invitation_id, expected_version=expected_version, **changes)


class FakeAttachmentStorageGateway:
    """A test double for ``app.database.attachment_storage.AttachmentStorageGateway``.

    Backed by a plain in-memory dict of path -> content, so
    ``AttachmentService`` tests exercise the exact same upload/download/
    remove/signed-URL call shape the real gateway exposes, without any
    network dependency.
    """

    def __init__(self, *, raise_on_upload: bool = False, raise_on_remove: bool = False) -> None:
        self.objects: dict[str, bytes] = {}
        self._raise_on_upload = raise_on_upload
        self._raise_on_remove = raise_on_remove

    def upload(self, *, path: str, content: bytes, content_type: str) -> None:
        del content_type  # Unused: this fake does not validate it.
        if self._raise_on_upload:
            raise StorageError("Simulated Storage upload failure.", bucket="attachments", path=path)
        self.objects[path] = content

    def download(self, *, path: str) -> bytes:
        try:
            return self.objects[path]
        except KeyError:
            raise StorageError(f"No object at '{path}'.", bucket="attachments", path=path) from None

    def remove(self, *, path: str) -> None:
        if self._raise_on_remove:
            raise StorageError(
                "Simulated Storage removal failure.", bucket="attachments", path=path
            )
        self.objects.pop(path, None)

    def create_signed_url(self, *, path: str, expires_in_seconds: int) -> str:
        if path not in self.objects:
            raise StorageError(f"No object at '{path}'.", bucket="attachments", path=path)
        return f"https://fake-storage.test/{path}?expires_in={expires_in_seconds}"


class FakeVirusScanner:
    """A test double for ``app.services.attachment_service.VirusScanner``.

    Always reports the same, fixed ``ScanResult`` regardless of content —
    tests configure the desired result at construction time (e.g.
    ``FakeVirusScanner(status=AttachmentScanStatus.INFECTED)``) rather
    than this fake inspecting the bytes it's given.
    """

    def __init__(self, *, status: AttachmentScanStatus = AttachmentScanStatus.SKIPPED) -> None:
        self._status = status
        self.scanned_content: list[bytes] = []

    def scan(self, content: bytes) -> ScanResult:
        self.scanned_content.append(content)
        return ScanResult(status=self._status)


@dataclasses.dataclass
class SentEmail:
    to_address: str
    subject: str
    body: str


class FakeEmailSender:
    """A test double for ``app.services.notification_service.EmailSender``."""

    def __init__(self, *, always_succeed: bool = True, raise_exception: bool = False) -> None:
        self.sent: list[SentEmail] = []
        self._always_succeed = always_succeed
        self._raise_exception = raise_exception

    def send(self, *, to_address: str, subject: str, body: str) -> bool:
        if self._raise_exception:
            raise RuntimeError("Simulated SMTP failure.")
        self.sent.append(SentEmail(to_address=to_address, subject=subject, body=body))
        return self._always_succeed


@dataclasses.dataclass
class SentInvitationEmail:
    to_email: str
    full_name: str
    token: str
    expires_at: Any
    is_resend: bool = False


class FakeInvitationEmailSender:
    """A test double for
    ``app.services.invitation_service.InvitationEmailSender``.
    """

    def __init__(self, *, always_succeed: bool = True, raise_exception: bool = False) -> None:
        self.sent: list[SentInvitationEmail] = []
        self._always_succeed = always_succeed
        self._raise_exception = raise_exception

    def send_invitation(
        self,
        *,
        to_email: str,
        full_name: str,
        token: str,
        expires_at: Any,
        is_resend: bool = False,
    ) -> bool:
        if self._raise_exception:
            raise RuntimeError("Simulated SMTP failure.")
        self.sent.append(
            SentInvitationEmail(
                to_email=to_email,
                full_name=full_name,
                token=token,
                expires_at=expires_at,
                is_resend=is_resend,
            )
        )
        return self._always_succeed


@dataclasses.dataclass
class SentProviderEmail:
    to_address: str
    subject: str
    text_body: str
    html_body: str | None


class FakeEmailProvider:
    """A test double for ``app.notifications.interfaces.EmailProvider``.

    Used to unit-test ``app.services.invitation_email.SmtpInvitationEmailSender``
    without exercising real SMTP/``smtplib`` — the same role
    ``FakeEmailSender``/``FakeInvitationEmailSender`` play one layer up,
    applied here at the lowest-level abstraction instead.
    """

    def __init__(self, *, raise_delivery_error: bool = False) -> None:
        self.sent: list[SentProviderEmail] = []
        self._raise_delivery_error = raise_delivery_error

    def send_email(
        self,
        *,
        to_address: str,
        subject: str,
        text_body: str,
        html_body: str | None = None,
    ) -> None:
        if self._raise_delivery_error:
            raise EmailDeliveryError(to_address, "Simulated SMTP failure.")
        self.sent.append(
            SentProviderEmail(
                to_address=to_address, subject=subject, text_body=text_body, html_body=html_body
            )
        )


@dataclasses.dataclass
class SentSupabaseUserCreation:
    user_id: UUID
    email: str
    password: str
    user_metadata: dict[str, Any]


@dataclasses.dataclass
class SentSupabaseUserAnonymization:
    user_id: UUID
    anonymized_email: str


class FakeSupabaseAuthAdminClient:
    """A test double for
    ``app.services.supabase_admin_client.SupabaseAuthAdminClient``.

    Optionally wired to a ``FakeProfileRepository`` to simulate the real
    ``on_auth_user_created`` trigger's effect: a successful
    ``create_user`` call synchronously inserts a matching ``profiles``
    row, so ``InvitationService._wait_for_profile`` (a genuine, bounded
    retry loop) succeeds on its very first poll in the common case, the
    same way it would against a real, already-committed Postgres
    transaction. Passing ``provision_profile=False`` instead simulates a
    trigger that never fires (or an id whose "already exists" recovery
    was actually a different, unrelated account), so tests can exercise
    ``_wait_for_profile``'s retry-exhaustion failure path.

    Calling ``create_user`` twice with the same email (exactly what a
    retried ``accept_invitation`` does) raises ``InvitationConflictError``
    on the second call, matching the real Supabase Admin API's own
    duplicate-email rejection — this is what makes this fake usable for
    idempotent-retry-recovery tests without any special-casing.
    """

    def __init__(
        self,
        *,
        profile_repo: FakeProfileRepository | None = None,
        provision_profile: bool = True,
        raise_generic_error: bool = False,
    ) -> None:
        self.created_users: list[SentSupabaseUserCreation] = []
        self.anonymized_users: list[SentSupabaseUserAnonymization] = []
        self._profile_repo = profile_repo
        self._provision_profile = provision_profile
        self._raise_generic_error = raise_generic_error
        self._existing_emails: dict[str, UUID] = {}

    def create_user(self, *, user_id: UUID, email: str, password: str, user_metadata: Any) -> UUID:
        if self._raise_generic_error:
            raise SupabaseAdminOperationError("Simulated Supabase Admin API failure.")
        if email in self._existing_emails:
            raise InvitationConflictError(email)

        self.created_users.append(
            SentSupabaseUserCreation(
                user_id=user_id, email=email, password=password, user_metadata=dict(user_metadata)
            )
        )
        self._existing_emails[email] = user_id
        if self._provision_profile and self._profile_repo is not None:
            role_value = user_metadata.get("role", UserRole.EMPLOYEE.value)
            self._profile_repo.create_profile(
                profile_id=user_id,
                full_name=user_metadata.get("full_name", ""),
                role=UserRole(role_value),
            )
        return user_id

    def anonymize_user(self, *, user_id: UUID, anonymized_email: str) -> None:
        if self._raise_generic_error:
            raise SupabaseAdminOperationError("Simulated Supabase Admin API failure.")
        self.anonymized_users.append(
            SentSupabaseUserAnonymization(user_id=user_id, anonymized_email=anonymized_email)
        )


class FakeAnalyticsRepository:
    """In-memory analogue of ``app.database.repositories.analytics_repository
    .AnalyticsRepository``'s four aggregate methods.

    Reads directly from the same underlying ``FakeRequestRepository`` and
    ``workflow_stages`` ``FakeTable`` a test's other fakes already share
    (see ``tests/conftest.py``'s ``env`` fixture), reproducing the real
    repository's filtering/grouping logic over in-memory data rather than
    a Supabase query builder — so ``AnalyticsEngine`` (real, unmodified)
    can be exercised end-to-end the same way every other service is.
    """

    table_name = "requests"

    def __init__(
        self, request_repo: FakeRequestRepository, stages_table: FakeTable[WorkflowStageRecord]
    ) -> None:
        self._request_repo = request_repo
        self._stages_table = stages_table

    def _matching_requests(
        self,
        *,
        company_id: UUID,
        department: str | None,
        request_type: str | None,
        created_after: Any | None,
        created_before: Any | None,
    ) -> list[RequestRecord]:
        matched = []
        for record in self._request_repo._table.values():
            if record.company_id != company_id:
                continue
            if record.deleted_at is not None:
                continue
            if department is not None and record.department != department:
                continue
            if request_type is not None and record.request_type != request_type:
                continue
            if created_after is not None and record.created_at < created_after:
                continue
            if created_before is not None and record.created_at > created_before:
                continue
            matched.append(record)
        return matched

    def count_requests_by_status(
        self,
        *,
        company_id: UUID = DEFAULT_TEST_COMPANY_ID,
        department: str | None = None,
        request_type: str | None = None,
        created_after: Any | None = None,
        created_before: Any | None = None,
    ) -> StatusBreakdown:
        matched = self._matching_requests(
            company_id=company_id,
            department=department,
            request_type=request_type,
            created_after=created_after,
            created_before=created_before,
        )
        tally: Counter[RequestStatus] = Counter(record.status for record in matched)
        return StatusBreakdown(counts=dict(tally), total=sum(tally.values()))

    def count_requests_by_type(
        self,
        *,
        company_id: UUID = DEFAULT_TEST_COMPANY_ID,
        department: str | None = None,
        created_after: Any | None = None,
        created_before: Any | None = None,
    ) -> VolumeByKey:
        matched = self._matching_requests(
            company_id=company_id,
            department=department,
            request_type=None,
            created_after=created_after,
            created_before=created_before,
        )
        tally: Counter[str] = Counter(record.request_type for record in matched)
        return VolumeByKey(counts=dict(tally), total=sum(tally.values()))

    def count_requests_by_department(
        self,
        *,
        company_id: UUID = DEFAULT_TEST_COMPANY_ID,
        request_type: str | None = None,
        created_after: Any | None = None,
        created_before: Any | None = None,
    ) -> VolumeByKey:
        matched = self._matching_requests(
            company_id=company_id,
            department=None,
            request_type=request_type,
            created_after=created_after,
            created_before=created_before,
        )
        tally: Counter[str] = Counter((record.department or "unspecified") for record in matched)
        return VolumeByKey(counts=dict(tally), total=sum(tally.values()))

    def approval_throughput(
        self,
        *,
        company_id: UUID = DEFAULT_TEST_COMPANY_ID,
        request_type: str | None = None,
        created_after: Any | None = None,
        created_before: Any | None = None,
    ) -> ApprovalThroughput:
        matched = self._matching_requests(
            company_id=company_id,
            department=None,
            request_type=request_type,
            created_after=created_after,
            created_before=created_before,
        )
        request_ids = {record.id for record in matched}
        completed_count = sum(1 for record in matched if record.status is RequestStatus.COMPLETED)
        rejected_count = sum(1 for record in matched if record.status is RequestStatus.REJECTED)
        completion_rate: float | None = None
        terminal_total = completed_count + rejected_count
        if terminal_total > 0:
            completion_rate = completed_count / terminal_total

        durations: list[float] = []
        for stage in self._stages_table.values():
            if stage.request_id not in request_ids:
                continue
            if stage.company_id != company_id:
                continue
            if stage.status not in (StageStatus.APPROVED, StageStatus.REJECTED):
                continue
            if stage.decided_at is None:
                continue
            durations.append((stage.decided_at - stage.created_at).total_seconds())
        average_decision_seconds = sum(durations) / len(durations) if durations else None

        return ApprovalThroughput(
            average_decision_seconds=average_decision_seconds,
            completed_count=completed_count,
            rejected_count=rejected_count,
            completion_rate=completion_rate,
        )


class FakeCompanyRepository:
    table_name = "companies"

    def __init__(self) -> None:
        self._table: FakeTable[CompanyRecord] = FakeTable("companies")

    def get_by_id(self, company_id: UUID) -> CompanyRecord:
        return self._table.get(company_id)

    def find_by_id(self, company_id: UUID) -> CompanyRecord | None:
        return self._table.find(company_id)

    def create_company(self, *, name: str, slug: str) -> CompanyRecord:
        now = utc_now()
        record = CompanyRecord(
            id=uuid4(),
            name=name,
            slug=slug,
            is_active=True,
            contact_email=None,
            notes=None,
            version=1,
            created_at=now,
            updated_at=now,
            deleted_at=None,
            deleted_by=None,
        )
        return self._table.insert(record)

    def update_company(
        self,
        company_id: UUID,
        *,
        expected_version: int,
        name: str | None = None,
        is_active: bool | None = None,
        contact_email: str | None = None,
        notes: str | None = None,
    ) -> CompanyRecord:
        changes: dict[str, Any] = {"updated_at": utc_now()}
        if name is not None:
            changes["name"] = name
        if is_active is not None:
            changes["is_active"] = is_active
        if contact_email is not None:
            changes["contact_email"] = contact_email
        if notes is not None:
            changes["notes"] = notes
        if len(changes) == 1:
            raise InvalidQueryError("update_company requires at least one field to update.")
        return self._table.update(company_id, expected_version=expected_version, **changes)

    def soft_delete(
        self, company_id: UUID, *, expected_version: int, deleted_by: UUID
    ) -> CompanyRecord:
        return self._table.update(
            company_id,
            expected_version=expected_version,
            deleted_at=utc_now(),
            deleted_by=deleted_by,
            updated_at=utc_now(),
        )

    def restore(self, company_id: UUID, *, expected_version: int) -> CompanyRecord:
        return self._table.update(
            company_id,
            expected_version=expected_version,
            deleted_at=None,
            deleted_by=None,
            updated_at=utc_now(),
        )

    def list_companies(
        self, *, include_deleted: bool = False, page: Page = Page()
    ) -> PagedResult[CompanyRecord]:
        items = list(self._table.values())
        if not include_deleted:
            items = [c for c in items if c.deleted_at is None]
        items.sort(key=lambda c: c.created_at, reverse=True)
        return _paginate(items, page)

    def count_companies(self, *, is_active: bool | None = None, include_deleted: bool = False) -> int:
        items = list(self._table.values())
        if not include_deleted:
            items = [c for c in items if c.deleted_at is None]
        if is_active is not None:
            items = [c for c in items if c.is_active == is_active]
        return len(items)


class FakeCompanyLicenseRepository:
    table_name = "company_licenses"

    def __init__(self) -> None:
        self._by_company: dict[UUID, CompanyLicenseRecord] = {}

    def get_for_company(self, company_id: UUID) -> CompanyLicenseRecord | None:
        return self._by_company.get(company_id)

    def upsert(
        self,
        company_id: UUID,
        *,
        plan_tier: str,
        seat_limit: int | None,
        expires_at,
        notes: str | None,
        updated_by: UUID | None,
    ) -> CompanyLicenseRecord:
        record = CompanyLicenseRecord(
            company_id=company_id,
            plan_tier=plan_tier,
            seat_limit=seat_limit,
            expires_at=expires_at,
            notes=notes,
            updated_at=utc_now(),
        )
        self._by_company[company_id] = record
        return record


class FakeFeatureFlagRepository:
    table_name = "feature_flags"

    def __init__(self) -> None:
        self._by_key: dict[str, FeatureFlagRecord] = {}

    def create(
        self, *, key: str, description: str, enabled: bool, updated_by: UUID | None
    ) -> FeatureFlagRecord:
        if key in self._by_key:
            raise ConstraintViolationError("feature_flags", "unique")
        record = FeatureFlagRecord(
            key=key,
            description=description,
            enabled=enabled,
            updated_at=utc_now(),
            updated_by=updated_by,
        )
        self._by_key[key] = record
        return record

    def get_by_key(self, key: str) -> FeatureFlagRecord:
        try:
            return self._by_key[key]
        except KeyError:
            raise RecordNotFoundError("feature_flags", key) from None

    def list_all(self) -> list[FeatureFlagRecord]:
        return sorted(self._by_key.values(), key=lambda f: f.key)

    def update(
        self,
        key: str,
        *,
        description: str | None = None,
        enabled: bool | None = None,
        updated_by: UUID | None = None,
    ) -> FeatureFlagRecord:
        current = self.get_by_key(key)
        if description is None and enabled is None:
            raise InvalidQueryError("update requires at least one field to update.")
        updated = dataclasses.replace(
            current,
            description=description if description is not None else current.description,
            enabled=enabled if enabled is not None else current.enabled,
            updated_by=updated_by,
            updated_at=utc_now(),
        )
        self._by_key[key] = updated
        return updated


class FakePlatformStatsRepository:
    """A simple, directly-settable stand-in for ``PlatformStatsRepository``.

    Unlike the other fakes in this module (backed by a shared
    ``FakeTable`` so cross-repository consistency is automatic), this one
    exposes its counters as plain, test-settable attributes — router-level
    tests for ``GET /platform/stats`` only need controllable, deterministic
    numbers, not a realistic cross-repository join.
    """

    table_name = "platform_stats"

    def __init__(self) -> None:
        self.user_count = 0
        self.request_timestamps: list[Any] = []
        self.active_workflow_definition_count = 0
        self.storage_bytes = 0

    def count_users(self) -> int:
        return self.user_count

    def count_requests(self, *, created_after=None) -> int:
        if created_after is None:
            return len(self.request_timestamps)
        return len([t for t in self.request_timestamps if t >= created_after])

    def request_created_timestamps(self, *, created_after) -> list[Any]:
        return [t for t in self.request_timestamps if t >= created_after]

    def count_active_workflow_definitions(self) -> int:
        return self.active_workflow_definition_count

    def sum_attachment_storage_bytes(self) -> int:
        return self.storage_bytes


class FakeSavedFilterRepository:
    table_name = "saved_filters"

    def __init__(self) -> None:
        self._table: FakeTable[SavedFilterRecord] = FakeTable("saved_filters", version_attr=None)

    def list_for_user(self, user_id: UUID, *, company_id: UUID) -> list[SavedFilterRecord]:
        items = [
            f
            for f in self._table.values()
            if f.user_id == user_id and f.company_id == company_id
        ]
        items.sort(key=lambda f: f.updated_at, reverse=True)
        return items

    def create(
        self,
        *,
        user_id: UUID,
        company_id: UUID,
        name: str,
        query_text: str,
        entity_types: list[str] | None,
        filters: dict[str, Any],
    ) -> SavedFilterRecord:
        if any(f.user_id == user_id and f.name == name for f in self._table.values()):
            raise ConstraintViolationError("saved_filters", "unique")
        now = utc_now()
        record = SavedFilterRecord(
            id=uuid4(),
            user_id=user_id,
            company_id=company_id,
            name=name,
            query_text=query_text,
            entity_types=entity_types,
            filters=filters,
            created_at=now,
            updated_at=now,
        )
        return self._table.insert(record)

    def delete(self, filter_id: UUID, *, user_id: UUID) -> None:
        record = self._table.find(filter_id)
        if record is None or record.user_id != user_id:
            raise RecordNotFoundError("saved_filters", filter_id)
        self._table.delete(filter_id)


class FakeSearchHistoryRepository:
    table_name = "search_history"

    def __init__(self) -> None:
        self._table: FakeTable[SearchHistoryRecord] = FakeTable(
            "search_history", version_attr=None
        )

    def record(
        self,
        *,
        user_id: UUID,
        company_id: UUID,
        query_text: str,
        entity_types: list[str] | None,
        result_count: int,
    ) -> SearchHistoryRecord:
        entry = SearchHistoryRecord(
            id=uuid4(),
            user_id=user_id,
            company_id=company_id,
            query_text=query_text,
            entity_types=entity_types,
            result_count=result_count,
            created_at=utc_now(),
        )
        return self._table.insert(entry)

    def list_recent(
        self, user_id: UUID, *, company_id: UUID, limit: int = 10
    ) -> list[SearchHistoryRecord]:
        items = [
            e
            for e in self._table.values()
            if e.user_id == user_id and e.company_id == company_id
        ]
        items.sort(key=lambda e: e.created_at, reverse=True)
        seen: set[str] = set()
        deduped: list[SearchHistoryRecord] = []
        for entry in items:
            key = entry.query_text.strip().lower()
            if key in seen:
                continue
            seen.add(key)
            deduped.append(entry)
            if len(deduped) >= limit:
                break
        return deduped

    def clear_for_user(self, user_id: UUID) -> int:
        to_delete = [e.id for e in self._table.values() if e.user_id == user_id]
        for entry_id in to_delete:
            self._table.delete(entry_id)
        return len(to_delete)


@dataclasses.dataclass
class SentAiRequest:
    system_prompt: str
    user_prompt: str
    max_output_tokens: int
    temperature: float


class FakeAiProvider:
    """A test double for ``app.ai.interfaces.AiProvider``.

    Same shape as ``FakeEmailProvider``: a constructor flag selects success
    or failure, every call is recorded (into ``sent``) for prompt-content
    assertions, and a simulated failure raises the real domain exception
    (``AiProviderError``) rather than a generic ``RuntimeError``.
    """

    def __init__(
        self,
        *,
        response_text: str = "Fake AI response.",
        raise_exception: bool = False,
    ) -> None:
        self.sent: list[SentAiRequest] = []
        self._response_text = response_text
        self._raise_exception = raise_exception

    def complete(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        max_output_tokens: int = 600,
        temperature: float = 0.2,
    ) -> AiCompletion:
        self.sent.append(
            SentAiRequest(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_output_tokens=max_output_tokens,
                temperature=temperature,
            )
        )
        if self._raise_exception:
            raise AiProviderError("fake", "Simulated provider failure.")
        return AiCompletion(text=self._response_text, provider_name="fake", model="fake-model")
