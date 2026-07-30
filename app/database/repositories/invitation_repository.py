"""Repository for the ``user_invitations`` table.

Per the Enterprise User Onboarding architecture (Milestone 1), this
application owns its own invitation record and its own opaque token: the
Supabase Auth user (and, in turn, the ``profiles`` row provisioned by the
``on_auth_user_created`` trigger) is created only when an invitation is
accepted, never at invite time. ``InvitationStatus`` is re-exported here
from ``app.models.enums`` (the single canonical definition) purely for
convenience, matching every other status-bearing repository in this
package (``RequestStatus`` in ``request_repository``, ``StageStatus`` in
``workflow_repository``, ``NotificationType`` in
``notification_repository``).

``'expired'`` is deliberately not a value ``status`` ever takes on this
table — it is a computed property of an unexpired-vs-expired comparison
against ``expires_at``, evaluated by the Application Layer (a later
milestone), not persisted here. This repository performs no such
computation; per ``BaseRepository``'s own docstring, it enforces no
business rule.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from app.database.client import DatabaseClient
from app.database.exceptions import InvalidQueryError
from app.database.repositories.base_repository import (
    BaseRepository,
    Page,
    PagedResult,
    escape_ilike_special_characters,
    parse_datetime,
    parse_uuid,
    quote_postgrest_filter_value,
)
from app.models.enums import InvitationStatus, UserRole

logger = logging.getLogger(__name__)

__all__ = ["InvitationStatus", "InvitationRecord", "InvitationRepository"]


@dataclass(frozen=True, slots=True)
class InvitationRecord:
    """An immutable, persistence-level representation of one
    ``user_invitations`` row.

    This is a thin data-transfer object mirroring the table's columns
    exactly — it performs no validation and enforces no business rule
    (including, notably, expiry: ``expires_at`` is exposed as a plain
    timestamp, and whether it has passed is left entirely to the caller).

    Attributes:
        id: Primary key.
        email: The invited person's email address.
        full_name: The invited person's display name, as provided by the
            inviting admin.
        role: The role the resulting profile will be provisioned with on
            acceptance.
        department: The department the resulting profile will be
            provisioned with, if set.
        token_hash: The SHA-256 hex digest of the raw invitation token.
            The raw token itself is never persisted anywhere.
        status: The invitation's persisted lifecycle status. Does not
            include "expired" — see the module docstring.
        invited_by: The admin who created this invitation, or ``None`` if
            that profile has since been hard-deleted
            (``user_invitations.invited_by`` is ``ON DELETE SET NULL``
            against ``profiles.id`` — ``0020_profile_lifecycle``).
        expires_at: The timestamp after which this invitation may no
            longer be accepted.
        accepted_at: The timestamp the invitation was accepted, if any.
        revoked_at: The timestamp the invitation was revoked, if any.
        accepted_profile_id: The id of the profile created on acceptance,
            if any.
        resend_count: The number of times this invitation has been
            resent (its token rotated and its expiry extended).
        version: Optimistic-locking row version.
        created_at: Record creation timestamp.
        updated_at: Last modification timestamp.
        company_id: The company (tenant) this invitation is for — the
            resulting profile is provisioned into this same company on
            acceptance.
    """

    id: UUID
    email: str
    full_name: str
    role: UserRole
    department: str | None
    token_hash: str
    status: InvitationStatus
    invited_by: UUID | None
    expires_at: datetime
    accepted_at: datetime | None
    revoked_at: datetime | None
    accepted_profile_id: UUID | None
    resend_count: int
    version: int
    created_at: datetime
    updated_at: datetime
    company_id: UUID


def _map_invitation_row(row: dict[str, Any]) -> InvitationRecord:
    """Map a raw Supabase row dict into an ``InvitationRecord``."""
    return InvitationRecord(
        id=parse_uuid(row["id"]),  # type: ignore[arg-type]
        email=row["email"],
        full_name=row["full_name"],
        role=UserRole(row["role"]),
        department=row.get("department"),
        token_hash=row["token_hash"],
        status=InvitationStatus(row["status"]),
        invited_by=parse_uuid(row.get("invited_by")),
        expires_at=parse_datetime(row["expires_at"]),  # type: ignore[arg-type]
        accepted_at=parse_datetime(row.get("accepted_at")),
        revoked_at=parse_datetime(row.get("revoked_at")),
        accepted_profile_id=parse_uuid(row.get("accepted_profile_id")),
        resend_count=row["resend_count"],
        version=row["version"],
        created_at=parse_datetime(row["created_at"]),  # type: ignore[arg-type]
        updated_at=parse_datetime(row["updated_at"]),  # type: ignore[arg-type]
        company_id=parse_uuid(row["company_id"]),  # type: ignore[arg-type]
    )


class InvitationRepository(BaseRepository[InvitationRecord]):
    """Persistence operations for the ``user_invitations`` table.

    Corresponds to the future ``InvitationService``'s persistence needs
    (Enterprise User Onboarding architecture, Milestones 2-3). No
    Application Service exists yet as of Milestone 1 — this repository is
    self-contained and independently testable via the in-memory fake in
    ``tests/fixtures/fakes.py``.
    """

    table_name = "user_invitations"

    def __init__(self, client: DatabaseClient, *, always_use_injected_client: bool) -> None:
        super().__init__(client, always_use_injected_client=always_use_injected_client)

    def get_by_id(self, invitation_id: UUID) -> InvitationRecord:  # type: ignore[override]
        """Fetch an invitation by its id.

        Args:
            invitation_id: The invitation's ``id``.

        Returns:
            The matching ``InvitationRecord``.

        Raises:
            RecordNotFoundError: If no invitation with this id exists or
                is visible under the current client's Row-Level Security
                context.
        """
        return super().get_by_id(invitation_id, mapper=_map_invitation_row)

    def find_by_id(self, invitation_id: UUID) -> InvitationRecord | None:  # type: ignore[override]
        """Fetch an invitation by its id, tolerating absence.

        Args:
            invitation_id: The invitation's ``id``.

        Returns:
            The matching ``InvitationRecord``, or ``None`` if not found.
        """
        return super().find_by_id(invitation_id, mapper=_map_invitation_row)

    def create_invitation(
        self,
        *,
        email: str,
        full_name: str,
        company_id: UUID,
        role: UserRole = UserRole.EMPLOYEE,
        department: str | None = None,
        token_hash: str,
        expires_at: datetime,
        invited_by: UUID,
    ) -> InvitationRecord:
        """Insert a new, pending invitation row.

        ``status``, ``resend_count``, and ``version`` are left unset here
        and populated by the table's own column defaults
        (``'pending'``, ``0``, ``1`` respectively) — no repository method
        in this package ever sets a column that the database itself
        maintains, matching ``ProfileRepository.create_profile``'s
        convention.

        Args:
            email: The invited person's email address.
            full_name: The invited person's display name.
            role: The role to provision the resulting profile with on
                acceptance. Defaults to ``UserRole.EMPLOYEE``, matching
                the column's database default.
            department: The department to provision the resulting
                profile with, if known.
            token_hash: The SHA-256 hex digest of the raw invitation
                token. Generating and hashing the token is the caller's
                responsibility (a future milestone's ``InvitationService``)
                — this repository only ever stores the digest.
            expires_at: The timestamp after which this invitation may no
                longer be accepted.
            invited_by: The id of the admin creating this invitation.

        Returns:
            The newly created ``InvitationRecord``.

        Raises:
            ConstraintViolationError: If ``invited_by`` does not resolve
                to an existing profile, or a pending invitation already
                exists for this email within this company (the partial
                unique index on ``lower(email), company_id where status =
                'pending'``).
        """
        values: dict[str, Any] = {
            "email": email,
            "full_name": full_name,
            "role": role.value,
            "department": department,
            "token_hash": token_hash,
            "expires_at": expires_at.isoformat(),
            "invited_by": str(invited_by),
            "company_id": str(company_id),
        }
        return self.insert(values, mapper=_map_invitation_row)

    def find_by_token_hash(self, token_hash: str) -> InvitationRecord | None:
        """Fetch an invitation by its token's hash, tolerating absence.

        Backed by the unique index on ``token_hash`` — the lookup a
        future public accept/validate endpoint hinges on: an
        unauthenticated caller presents only the raw token, which the
        caller hashes before calling this method (this repository never
        sees or handles the raw token itself).

        Args:
            token_hash: The SHA-256 hex digest of the raw invitation
                token.

        Returns:
            The matching ``InvitationRecord``, or ``None`` if no
            invitation has this token hash.
        """
        response = self._execute(
            self._query().select("*").eq("token_hash", token_hash).limit(1),
            operation="find_by_token_hash",
        )
        rows = self._rows(response)
        return _map_invitation_row(rows[0]) if rows else None

    def find_pending_by_email(self, email: str, *, company_id: UUID) -> InvitationRecord | None:
        """Fetch the pending invitation for an email address within a
        company, if any.

        Matches case-insensitively, consistent with the partial unique
        index on ``lower(email), company_id where status = 'pending'``
        this method is the read-side counterpart of — used by
        ``InvitationService.create_invitation`` to give a friendly
        conflict error rather than relying solely on the database
        rejecting a duplicate insert. The same email may have a pending
        invitation in a *different* company simultaneously — that is not
        a conflict.

        This is an exact (case-insensitive) match, not a substring
        search — ``email`` is escaped via ``escape_ilike_special_characters``
        before being handed to ``.ilike()`` (with no ``%`` wildcards
        added around it), so a literal ``%``/``_`` in the address is
        matched literally rather than reinterpreted as a wildcard.

        Args:
            email: The email address to look up.
            company_id: Restricts the lookup to this company (tenant).

        Returns:
            The matching pending ``InvitationRecord``, or ``None`` if no
            pending invitation exists for this email within this company.
        """
        response = self._execute(
            self._scoped_query(company_id=company_id, count=None)
            .eq("status", InvitationStatus.PENDING.value)
            .ilike("email", escape_ilike_special_characters(email))
            .limit(1),
            operation="find_pending_by_email",
        )
        rows = self._rows(response)
        return _map_invitation_row(rows[0]) if rows else None

    def list_invitations(
        self,
        *,
        company_id: UUID,
        status: InvitationStatus | None = None,
        query: str | None = None,
        expires_after: datetime | None = None,
        expires_at_or_before: datetime | None = None,
        page: Page = Page(),
    ) -> PagedResult[InvitationRecord]:
        """List invitations within a company, optionally filtered by
        status, expiry, and free text.

        ``status`` here is the persisted status only. ``expires_after``/
        ``expires_at_or_before`` let a caller additionally narrow by
        ``expires_at`` *in the same query* — this is what lets the
        Application Layer's "effective status" (``pending`` vs
        ``expired``, both persisted as ``InvitationStatus.PENDING``) be
        expressed as a single, correctly-paginated, correctly-counted
        database query, rather than fetching a persisted-``pending`` page
        and filtering it further in Python (which would both mis-count
        ``total_records`` and under-fill a page — see
        ``InvitationService.list_invitations``, the sole caller of these
        two parameters).

        Args:
            status: Restrict to this persisted status, if provided.
            query: Free-text search matched case-insensitively against
                both ``full_name`` and ``email``, if provided.
            expires_after: Restrict to rows whose ``expires_at`` is
                strictly after this timestamp, if provided (used for the
                effective-``pending`` case: not yet expired).
            expires_at_or_before: Restrict to rows whose ``expires_at`` is
                at or before this timestamp, if provided (used for the
                effective-``expired`` case). Mutually exclusive with
                ``expires_after`` in practice (the caller never has a
                reason to supply both), but both are accepted
                independently since this method applies no business rule
                of its own.
            page: The page to retrieve.

        Returns:
            A ``PagedResult`` of matching invitations, newest first.

        Raises:
            InvalidQueryError: If ``query`` is provided but empty or
                whitespace-only.
        """
        builder = self._scoped_query(company_id=company_id)
        if status is not None:
            builder = builder.eq("status", status.value)
        if expires_after is not None:
            builder = builder.gt("expires_at", expires_after.isoformat())
        if expires_at_or_before is not None:
            builder = builder.lte("expires_at", expires_at_or_before.isoformat())
        if query is not None:
            if not query.strip():
                raise InvalidQueryError(
                    "list_invitations requires a non-empty query when provided."
                )
            pattern = f"%{escape_ilike_special_characters(query.strip())}%"
            quoted_pattern = quote_postgrest_filter_value(pattern)
            builder = builder.or_(f"full_name.ilike.{quoted_pattern},email.ilike.{quoted_pattern}")
        builder = builder.order("created_at", desc=True)
        return self.paginate(builder, page, mapper=_map_invitation_row)

    def update_status_with_lock(
        self,
        invitation_id: UUID,
        *,
        expected_version: int,
        status: InvitationStatus,
        token_hash: str | None = None,
        expires_at: datetime | None = None,
        accepted_at: datetime | None = None,
        revoked_at: datetime | None = None,
        accepted_profile_id: UUID | None = None,
        resend_count: int | None = None,
    ) -> InvitationRecord:
        """Transition an invitation's status under optimistic-locking control.

        A single, generic status-transition method backing every write
        this table needs (resend, revoke, accept — each a future
        milestone's concern), rather than one bespoke method per
        transition, since every transition shares the same
        "update status plus a handful of transition-specific columns
        under optimistic-locking control" shape. Only the fields
        explicitly passed (non-``None``) beyond ``status`` are included
        in the update payload.

        Args:
            invitation_id: The invitation's ``id``.
            expected_version: The version last observed by the caller.
            status: The new persisted status.
            token_hash: The new token hash, when rotating the token
                (resend).
            expires_at: The new expiry timestamp, when extending it
                (resend).
            accepted_at: The acceptance timestamp, when accepting.
            revoked_at: The revocation timestamp, when revoking.
            accepted_profile_id: The id of the profile created on
                acceptance, when accepting.
            resend_count: The new resend count, when resending.

        Returns:
            The updated ``InvitationRecord``.

        Raises:
            ConcurrentUpdateError: If ``expected_version`` no longer
                matches the row's current version.
        """
        values: dict[str, Any] = {"status": status.value}
        if token_hash is not None:
            values["token_hash"] = token_hash
        if expires_at is not None:
            values["expires_at"] = expires_at.isoformat()
        if accepted_at is not None:
            values["accepted_at"] = accepted_at.isoformat()
        if revoked_at is not None:
            values["revoked_at"] = revoked_at.isoformat()
        if accepted_profile_id is not None:
            values["accepted_profile_id"] = str(accepted_profile_id)
        if resend_count is not None:
            values["resend_count"] = resend_count
        return self.update_with_optimistic_lock(
            invitation_id,
            expected_version=expected_version,
            values=values,
            mapper=_map_invitation_row,
        )
