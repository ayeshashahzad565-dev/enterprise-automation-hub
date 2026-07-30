"""Application service orchestrating enterprise user invitations.

Per the Enterprise User Onboarding architecture (Milestone 2), this is
the first dedicated user-management Application Service in this
codebase — every other admin-facing user operation
(``app.api.routers.admin_users``) calls ``ProfileRepository`` directly as
a narrow, documented exception, but invitation issuance carries real
business logic (token generation, expiry, status transitions, resend
semantics) that belongs behind a proper service, matching
``RequestService``'s/``CommentService``'s shape: constructor-injected
repositories, an authorization check before every mutation, and an
audit-log entry after every state change.

This module also owns invitation-token generation and hashing.
Consistent with ``app.auth.authentication``'s module docstring ("all
authentication is delegated to Supabase Auth"), an invitation token is
*not* a credential or session token — it proves only "you are the
intended recipient of this one invite" — so it is generated and verified
entirely with the standard library (``secrets``/``hashlib``/``hmac``),
the same dependency-free precedent already established by
``app.auth.password`` for the one other place this codebase handles a
secret locally.

``InvitationEmailSender`` is a ``typing.Protocol`` — this module defines
the interface only, matching
``app.services.notification_service.EmailSender``'s identical
"interface here, SMTP implementation elsewhere" split. The production
implementation (``app.services.invitation_email.SmtpInvitationEmailSender``,
Milestone 4) lives in its own module so that this one stays free of any
SMTP/template concern, consistent with "no HTTP-specific logic, no
dependency on FastAPI" applying equally to "no dependency on a specific
delivery mechanism." This service accepts an optional
``InvitationEmailSender`` and degrades gracefully (skipping dispatch,
logging that it did so) when none is supplied; a dispatch failure is
logged and suppressed, never allowed to reverse or block the
already-committed invitation.

Per Milestone 3, ``validate_invitation_token``/``accept_invitation`` are
this service's public, *unauthenticated* half: the invitee holds no
Supabase session when calling them, so neither method takes an
``AuthenticatedIdentity`` — possession of a valid, unexpired, still-
``pending`` token is the entire authorization boundary, distinct from
every other method on this class (all admin-gated). ``accept_invitation``
is designed so that retrying it — after a partial prior failure, a
network timeout, or a doubled client-side request — is always safe: see
its own docstring for the idempotency strategy, which hinges on
requesting a caller-chosen (rather than Supabase-generated) user id from
``SupabaseAuthAdminClient.create_user`` — the invitation's own id — so
that a retried call can recognize "this exact user was already created
by an earlier attempt of this exact acceptance" deterministically,
without needing an email-lookup capability the installed Supabase SDK
does not expose (``list_users`` takes no email filter).
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
from datetime import datetime, timedelta
from typing import Protocol, runtime_checkable
from uuid import UUID

from pydantic import ValidationError as PydanticValidationError

from app.auth import rbac
from app.auth.authentication import AuthenticatedIdentity
from app.database.exceptions import DatabaseError
from app.database.repositories.audit_repository import AuditRepository
from app.database.repositories.base_repository import Page, PagedResult
from app.database.repositories.invitation_repository import InvitationRecord, InvitationRepository
from app.database.repositories.user_repository import ProfileRepository
from app.models import Invitation, InvitationCreate
from app.models.enums import AuditAction, EffectiveInvitationStatus, InvitationStatus, UserRole
from app.models.exceptions import DomainError
from app.services.exceptions import (
    InvalidInvitationStateError,
    InvitationConflictError,
    NotFoundError,
    PermissionDeniedError,
    SupabaseAdminOperationError,
    translate_auth_error,
    translate_database_error,
    translate_model_construction_error,
)
from app.services.supabase_admin_client import SupabaseAuthAdminClient
from app.utils.datetime_utils import is_past, utc_now
from app.utils.decorators import log_calls
from app.utils.exceptions import RetryExhaustedError
from app.utils.retry import RetryPolicy, retry_call

__all__ = [
    "InvitationEmailSender",
    "generate_invitation_token",
    "hash_invitation_token",
    "verify_invitation_token",
    "compute_effective_status",
    "map_invitation_record_to_domain",
    "InvitationService",
    "DEFAULT_INVITATION_EXPIRY_HOURS",
]

logger = logging.getLogger(__name__)

#: The default lifetime of a newly created (or resent) invitation, used
#: whenever a caller does not inject a different value via
#: ``InvitationService.__init__``. A future milestone may promote this to
#: an ``app.config.settings``-backed value; no such wiring exists yet
#: (out of scope for this milestone, which introduces no Bootstrap
#: changes), so it is a plain module constant for now.
DEFAULT_INVITATION_EXPIRY_HOURS = 72.0

#: The number of random bytes ``generate_invitation_token`` draws from
#: ``secrets.token_urlsafe`` — 32 bytes is 256 bits of entropy, the same
#: order of magnitude every other secret this codebase generates
#: (Supabase's own session tokens) is generated with.
_TOKEN_ENTROPY_BYTES = 32


class _ProfileNotYetProvisionedError(Exception):
    """Internal, retryable marker exception: the ``on_auth_user_created``
    trigger has not yet provisioned a ``profiles`` row for a just-created
    Supabase Auth user, as of this poll attempt.

    Never raised across ``InvitationService``'s own public boundary — see
    ``_wait_for_profile``, the only place this is caught.
    """


#: The bounded-retry policy ``_wait_for_profile`` uses to tolerate the
#: brief propagation delay between a Supabase Auth Admin API call
#: returning and the ``on_auth_user_created`` trigger's effect becoming
#: visible to a subsequent read — reusing ``app.utils.retry``'s existing
#: bounded-retry mechanism (the same one ``SmtpEmailProvider`` uses for a
#: different transient-failure scenario) rather than a hand-rolled sleep
#: loop. Deliberately short: this trigger fires synchronously as part of
#: the same underlying database transaction Supabase's own API call
#: performs, so any propagation delay observed here is expected to be a
#: read-consistency artifact measured in milliseconds, not a
#: network-round-trip-scale wait.
_PROFILE_PROPAGATION_RETRY_POLICY = RetryPolicy(
    max_attempts=5,
    base_delay_seconds=0.05,
    backoff_multiplier=1.5,
    max_delay_seconds=0.5,
    jitter=False,
    retryable_exceptions=(_ProfileNotYetProvisionedError,),
)


@runtime_checkable
class InvitationEmailSender(Protocol):
    """Structural interface for dispatching a single invitation email.

    A future infrastructure module is expected to implement this
    protocol (an ``InvitationEmailSender`` built around
    ``app.notifications.email_sender.SmtpEmailProvider``, per the
    architecture's Notification Integration section) — no such
    implementation is provided in this package; this milestone stubs
    email delivery only, exactly as instructed.
    """

    def send_invitation(
        self,
        *,
        to_email: str,
        full_name: str,
        token: str,
        expires_at: datetime,
        is_resend: bool = False,
    ) -> bool:
        """Send a single invitation email.

        Args:
            to_email: The invited person's email address.
            full_name: The invited person's display name, for
                personalizing the email.
            token: The raw (unhashed) invitation token. Implementations
                are responsible for building the accept-invitation link
                from it; this service never logs this value.
            expires_at: The timestamp after which the token in this email
                will no longer be accepted.
            is_resend: ``True`` when this dispatch is a resend of an
                existing invitation (its token has just been rotated),
                ``False`` for a brand-new invitation. Implementations may
                use this to vary copy (e.g. "your invitation link has
                been renewed" vs. "you're invited"); it does not change
                which invitation this call refers to.

        Returns:
            ``True`` if the email was sent successfully, ``False``
            otherwise. Implementations are expected never to raise for an
            ordinary delivery failure; a raised exception is treated by
            ``InvitationService`` as an implementation defect, still
            caught and logged, never allowed to propagate.
        """
        ...


def generate_invitation_token() -> str:
    """Generate a new, high-entropy, URL-safe invitation token.

    Standard-library only (``secrets``), matching this codebase's
    established precedent (``app.auth.password``) for not introducing a
    third-party cryptography dependency for a locally-handled secret.

    Returns:
        A 256-bit-entropy, URL-safe random token string, suitable for
        embedding directly in an accept-invitation link's query string.
    """
    return secrets.token_urlsafe(_TOKEN_ENTROPY_BYTES)


def hash_invitation_token(token: str) -> str:
    """Hash a raw invitation token for storage.

    Uses a plain SHA-256 digest, deliberately *not*
    ``app.auth.password``'s PBKDF2-HMAC-SHA256 helper: that function's
    deliberate slowness (600,000 iterations) exists to defend a
    low-entropy, human-chosen *password* against offline brute force. A
    token produced by ``generate_invitation_token`` already carries 256
    bits of entropy — brute-forcing the hash is already infeasible — so a
    fast, deterministic digest is the correct choice here, and is what
    lets ``InvitationRepository.find_by_token_hash`` do an indexed,
    O(1) equality lookup rather than needing to re-derive and compare a
    salted hash against every row.

    Args:
        token: The raw invitation token to hash.

    Returns:
        The SHA-256 hex digest of ``token``. The raw token itself is
        never stored anywhere by this service.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def verify_invitation_token(token: str, token_hash: str) -> bool:
    """Verify a candidate raw token against a stored hash, in constant time.

    Not called by any method in this milestone (there is no public
    accept-invitation flow yet — a future milestone's concern) but
    implemented now as part of this milestone's token-handling contract,
    following the same constant-time-comparison discipline
    ``app.auth.password.verify_password`` already applies, so that a
    future caller never needs to hand-roll this comparison itself.

    Args:
        token: The candidate raw token, as presented by an invitee.
        token_hash: The stored SHA-256 hex digest to compare against.

    Returns:
        ``True`` if ``token`` hashes to ``token_hash``.
    """
    return hmac.compare_digest(hash_invitation_token(token), token_hash)


def compute_effective_status(
    *, status: InvitationStatus, expires_at: datetime, now: datetime | None = None
) -> EffectiveInvitationStatus:
    """Compute an invitation's effective, caller-facing status.

    ``InvitationStatus`` (the persisted value) never includes an
    "expired" state — see its own docstring. This function is the single
    place that derives the fourth, computed value from ``status`` plus
    ``expires_at``, so that every read path (``get_invitation``,
    ``list_invitations``) applies the identical rule.

    Args:
        status: The invitation's persisted status.
        expires_at: The invitation's expiry timestamp.
        now: The point in time to evaluate expiry against. Defaults to
            ``utc_now()`` when not provided; accepting it explicitly keeps
            this function a pure, deterministic, trivially-unit-testable
            computation rather than one silently coupled to wall-clock
            time.

    Returns:
        ``EffectiveInvitationStatus.ACCEPTED`` or ``.REVOKED`` when
        ``status`` is already terminal; otherwise ``.EXPIRED`` if
        ``expires_at`` has passed, or ``.PENDING`` if it has not.
    """
    if status is InvitationStatus.ACCEPTED:
        return EffectiveInvitationStatus.ACCEPTED
    if status is InvitationStatus.REVOKED:
        return EffectiveInvitationStatus.REVOKED
    if is_past(expires_at, reference=now):
        return EffectiveInvitationStatus.EXPIRED
    return EffectiveInvitationStatus.PENDING


def map_invitation_record_to_domain(
    record: InvitationRecord, *, now: datetime | None = None
) -> Invitation:
    """Map a persistence-level ``InvitationRecord`` into its Domain Layer
    ``Invitation`` representation.

    ``token_hash`` is deliberately never copied onto the returned model —
    see ``Invitation``'s own docstring.

    Args:
        record: The record returned by ``InvitationRepository``.
        now: Passed through to ``compute_effective_status``; see its
            docstring.

    Returns:
        The corresponding ``Invitation`` domain model.
    """
    return Invitation(
        id=record.id,
        email=record.email,
        full_name=record.full_name,
        role=record.role,
        department=record.department,
        effective_status=compute_effective_status(
            status=record.status, expires_at=record.expires_at, now=now
        ),
        invited_by=record.invited_by,
        expires_at=record.expires_at,
        accepted_at=record.accepted_at,
        revoked_at=record.revoked_at,
        accepted_profile_id=record.accepted_profile_id,
        resend_count=record.resend_count,
        version=record.version,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


class InvitationService:
    """Orchestrates invitation creation, listing, resend, revocation, and
    (Milestone 3) validation and acceptance.

    Depends only on ``InvitationRepository``, ``ProfileRepository``,
    ``AuditRepository``, ``SupabaseAuthAdminClient``, and the optional
    ``InvitationEmailSender`` abstraction — no database access of its
    own, no HTTP-specific logic, no dependency on FastAPI or any
    Presentation Layer concern, and, critically, no dependency on the
    Supabase SDK directly (only on the ``SupabaseAuthAdminClient``
    protocol) — matching every other Application Service in
    ``app.services``.
    """

    def __init__(
        self,
        *,
        invitation_repo: InvitationRepository,
        profile_repo: ProfileRepository,
        audit_repo: AuditRepository,
        auth_admin_client: SupabaseAuthAdminClient,
        email_sender: InvitationEmailSender | None = None,
        invitation_expiry_hours: float = DEFAULT_INVITATION_EXPIRY_HOURS,
    ) -> None:
        """Initialize the service with its injected collaborators.

        Args:
            invitation_repo: Persistence for ``user_invitations``.
            profile_repo: Persistence for ``profiles``, used by
                ``accept_invitation`` to confirm the
                ``on_auth_user_created`` trigger has provisioned a
                profile for a newly created Supabase user before linking
                ``accepted_profile_id`` to it.
            audit_repo: Persistence for ``audit_logs``.
            auth_admin_client: The abstraction ``accept_invitation`` uses
                to create a Supabase Auth user — never the Supabase SDK
                directly.
            email_sender: An implementation of ``InvitationEmailSender``,
                or ``None`` to disable email dispatch entirely (matching
                ``NotificationService``'s identical allowance).
            invitation_expiry_hours: The lifetime, in hours, assigned to a
                newly created or resent invitation.
        """
        self._invitation_repo = invitation_repo
        self._profile_repo = profile_repo
        self._audit_repo = audit_repo
        self._auth_admin_client = auth_admin_client
        self._email_sender = email_sender
        self._invitation_expiry_hours = invitation_expiry_hours
        self._logger = logging.getLogger(f"{__name__}.InvitationService")

    @log_calls()
    def create_invitation(
        self,
        identity: AuthenticatedIdentity,
        *,
        email: str,
        full_name: str,
        role: UserRole = UserRole.EMPLOYEE,
        department: str | None = None,
        company_id: UUID | None = None,
    ) -> Invitation:
        """Create a new, pending invitation and (best-effort) email it.

        Args:
            identity: The authenticated caller. Must be an administrator,
                unless ``company_id`` is supplied (see below).
            email: The invited person's email address.
            full_name: The invited person's display name.
            role: The role to provision the resulting profile with on
                acceptance.
            department: The department to provision the resulting profile
                with, if known.
            company_id: The company (tenant) to invite into. Defaults to
                ``identity.company_id`` (the ordinary case: an admin
                invites within their own company). A caller may only
                supply a *different* company here if
                ``identity.is_platform_admin`` is ``True`` — this is the
                one deliberate exception to "company_id is never client
                input" (see ``app/auth/authorization.py``'s
                ``authorize_platform_admin`` docstring), needed to invite
                a brand-new company's first admin, who does not exist yet
                to invite anyone themselves.

        Returns:
            The newly created ``Invitation``.

        Raises:
            PermissionDeniedError: If the caller is not an administrator,
                or supplied a ``company_id`` other than their own without
                being a platform admin.
            ValidationError: If ``email`` or ``full_name`` fails shape
                validation.
            InvitationConflictError: If a pending invitation already
                exists for this email address within the target company.
        """
        target_company_id = company_id if company_id is not None else identity.company_id
        if target_company_id != identity.company_id:
            if not identity.is_platform_admin:
                raise PermissionDeniedError(
                    f"Role '{identity.role.value}' may not invite into a company other "
                    "than its own."
                )
        else:
            self._authorize_admin(identity)

        try:
            payload = InvitationCreate(
                email=email, full_name=full_name, role=role, department=department
            )
        except (PydanticValidationError, DomainError) as exc:
            raise translate_model_construction_error(exc, model_name="InvitationCreate") from exc

        if (
            self._invitation_repo.find_pending_by_email(payload.email, company_id=target_company_id)
            is not None
        ):
            raise InvitationConflictError(payload.email)

        raw_token = generate_invitation_token()
        token_hash = hash_invitation_token(raw_token)
        expires_at = utc_now() + timedelta(hours=self._invitation_expiry_hours)

        try:
            created = self._invitation_repo.create_invitation(
                email=payload.email,
                full_name=payload.full_name,
                role=payload.role,
                department=payload.department,
                token_hash=token_hash,
                expires_at=expires_at,
                invited_by=identity.user_id,
                company_id=target_company_id,
            )
        except DatabaseError as exc:
            raise translate_database_error(exc) from exc

        self._record_audit_event(
            action=AuditAction.INVITATION_CREATED, actor_id=identity.user_id, record=created
        )
        self._dispatch_invitation_email(created, raw_token=raw_token)

        self._logger.info(
            "Invitation %s created for %s by %s",
            created.id,
            created.email,
            identity.user_id,
            extra={"invitation_id": str(created.id)},
        )
        return map_invitation_record_to_domain(created)

    @log_calls()
    def list_invitations(
        self,
        identity: AuthenticatedIdentity,
        *,
        status: EffectiveInvitationStatus | None = None,
        query: str | None = None,
        page: Page = Page(),
    ) -> PagedResult[Invitation]:
        """List invitations, optionally filtered by effective status and
        free text.

        ``status`` filters on *effective* status (including the computed
        ``EXPIRED`` value ``InvitationRepository`` never persists). A
        request for ``PENDING``/``EXPIRED`` is served by asking the
        repository to additionally filter on ``expires_at`` in the same
        query (``InvitationRepository.list_invitations``'s
        ``expires_after``/``expires_at_or_before`` parameters), so
        pagination and ``total_records`` are exact for every effective-
        status value, not only the three persisted ones. (An earlier
        version of this method instead filtered a persisted-``pending``
        page further in Python, which under-counted ``total_records``
        and could under-fill a page even when more matching rows existed
        on a later one — closed as part of the Milestone 1-5 cleanup
        pass.)

        A single reference timestamp is captured once, at the start of
        this call, and used both for the repository's ``expires_at``
        comparison and for computing each returned item's
        ``effective_status`` below — so a row can never be included by
        the query as "not yet expired" but then reported as "expired"
        (or vice versa) purely because wall-clock time advanced between
        the two steps.

        Args:
            identity: The authenticated caller. Must be an administrator.
            status: Restrict to this effective status, if provided.
            query: Free-text search matched against full name and email,
                if provided.
            page: The page to retrieve.

        Returns:
            A ``PagedResult`` of matching invitations, newest first.

        Raises:
            PermissionDeniedError: If the caller is not an administrator.
        """
        self._authorize_admin(identity)

        reference_now = utc_now()
        repo_status: InvitationStatus | None
        expires_after: datetime | None = None
        expires_at_or_before: datetime | None = None
        if status is None:
            repo_status = None
        elif status is EffectiveInvitationStatus.PENDING:
            repo_status = InvitationStatus.PENDING
            expires_after = reference_now
        elif status is EffectiveInvitationStatus.EXPIRED:
            repo_status = InvitationStatus.PENDING
            expires_at_or_before = reference_now
        else:
            repo_status = InvitationStatus(status.value)

        try:
            result = self._invitation_repo.list_invitations(
                company_id=identity.company_id,
                status=repo_status,
                query=query,
                expires_after=expires_after,
                expires_at_or_before=expires_at_or_before,
                page=page,
            )
        except DatabaseError as exc:
            raise translate_database_error(exc) from exc

        items = [
            map_invitation_record_to_domain(record, now=reference_now) for record in result.items
        ]
        return PagedResult(
            items=items,
            page=result.page,
            page_size=result.page_size,
            total_records=result.total_records,
        )

    @log_calls()
    def get_invitation(self, identity: AuthenticatedIdentity, invitation_id: UUID) -> Invitation:
        """Fetch a single invitation by id.

        Args:
            identity: The authenticated caller. Must be an administrator.
            invitation_id: The invitation's id.

        Returns:
            The matching ``Invitation``.

        Raises:
            PermissionDeniedError: If the caller is not an administrator.
            NotFoundError: If no invitation with this id exists.
        """
        self._authorize_admin(identity)
        record = self._get_record_or_raise(invitation_id, identity=identity)
        return map_invitation_record_to_domain(record)

    @log_calls()
    def resend_invitation(self, identity: AuthenticatedIdentity, invitation_id: UUID) -> Invitation:
        """Resend a pending invitation: rotate its token, extend its
        expiry, and increment its resend count.

        The invitation's old token stops working immediately (its hash is
        overwritten, not merely superseded), not just "eventually
        expires" — resending is a full replacement of the outstanding
        link, not an additional one.

        Args:
            identity: The authenticated caller. Must be an administrator.
            invitation_id: The invitation's id.

        Returns:
            The updated ``Invitation``.

        Raises:
            PermissionDeniedError: If the caller is not an administrator.
            NotFoundError: If no invitation with this id exists.
            InvalidInvitationStateError: If the invitation's persisted
                status is not ``pending`` (an accepted or revoked
                invitation may not be resent — note this check is against
                the *persisted* status, so a lazily-expired-but-still-
                pending invitation may still be resent, which is the
                entire point of resend).
            ConcurrencyError: If another writer changed this invitation
                between the read and the write below.
        """
        self._authorize_admin(identity)
        existing = self._get_record_or_raise(invitation_id, identity=identity)
        self._require_pending(existing, attempted_action="resend")

        raw_token = generate_invitation_token()
        token_hash = hash_invitation_token(raw_token)
        new_expiry = utc_now() + timedelta(hours=self._invitation_expiry_hours)

        try:
            updated = self._invitation_repo.update_status_with_lock(
                invitation_id,
                expected_version=existing.version,
                status=InvitationStatus.PENDING,
                token_hash=token_hash,
                expires_at=new_expiry,
                resend_count=existing.resend_count + 1,
            )
        except DatabaseError as exc:
            raise translate_database_error(exc) from exc

        self._record_audit_event(
            action=AuditAction.INVITATION_RESENT, actor_id=identity.user_id, record=updated
        )
        self._dispatch_invitation_email(updated, raw_token=raw_token, is_resend=True)

        self._logger.info(
            "Invitation %s resent by %s (resend_count=%d)",
            updated.id,
            identity.user_id,
            updated.resend_count,
            extra={"invitation_id": str(updated.id)},
        )
        return map_invitation_record_to_domain(updated)

    @log_calls()
    def revoke_invitation(self, identity: AuthenticatedIdentity, invitation_id: UUID) -> Invitation:
        """Revoke a pending invitation.

        Since a Supabase Auth user is only ever created at acceptance
        (a later milestone), revoking a pending invitation has nothing
        else to clean up — this is a pure status transition.

        Args:
            identity: The authenticated caller. Must be an administrator.
            invitation_id: The invitation's id.

        Returns:
            The updated ``Invitation``, with ``revoked_at`` populated.

        Raises:
            PermissionDeniedError: If the caller is not an administrator.
            NotFoundError: If no invitation with this id exists.
            InvalidInvitationStateError: If the invitation's persisted
                status is not ``pending``.
            ConcurrencyError: If another writer changed this invitation
                between the read and the write below.
        """
        self._authorize_admin(identity)
        existing = self._get_record_or_raise(invitation_id, identity=identity)
        self._require_pending(existing, attempted_action="revoke")

        try:
            updated = self._invitation_repo.update_status_with_lock(
                invitation_id,
                expected_version=existing.version,
                status=InvitationStatus.REVOKED,
                revoked_at=utc_now(),
            )
        except DatabaseError as exc:
            raise translate_database_error(exc) from exc

        self._record_audit_event(
            action=AuditAction.INVITATION_REVOKED, actor_id=identity.user_id, record=updated
        )

        self._logger.info(
            "Invitation %s revoked by %s",
            updated.id,
            identity.user_id,
            extra={"invitation_id": str(updated.id)},
        )
        return map_invitation_record_to_domain(updated)

    @log_calls()
    def validate_invitation_token(self, token: str) -> Invitation:
        """Validate a raw invitation token and return the invitation it
        refers to, if it is currently acceptable.

        Deliberately takes no ``identity`` — the invitee holds no
        Supabase session at this point (per this module's docstring);
        possession of ``token`` itself is the entire authorization
        boundary for this method.

        Args:
            token: The raw (unhashed) invitation token, as presented by
                an invitee (for example, from an accept-invitation link's
                query string).

        Returns:
            The matching ``Invitation``, with ``effective_status``
            necessarily ``EffectiveInvitationStatus.PENDING`` (any other
            effective status would have raised below).

        Raises:
            NotFoundError: If no invitation matches ``token``.
            InvalidInvitationStateError: If the invitation exists but is
                not currently acceptable (already accepted, revoked, or
                pending but expired).
        """
        record = self._find_by_token_or_raise(token)
        self._require_acceptable(record)
        return map_invitation_record_to_domain(record)

    @log_calls()
    def accept_invitation(self, token: str, *, password: str) -> Invitation:
        """Accept an invitation: create the invitee's Supabase Auth user
        and mark the invitation accepted.

        Deliberately takes no ``identity`` — see
        ``validate_invitation_token``'s identical note; this method
        performs no authentication or session handling of its own (that
        remains entirely Supabase's job, and entirely a later
        milestone's — the frontend signs the new user in itself, via the
        same client-side call the login page already makes, once this
        method returns successfully).

        **Idempotency.** This method is safe to retry. The Supabase user
        created for this invitation is assigned a caller-chosen id —
        the invitation's own id (``record.id``) — rather than letting
        Supabase generate one, specifically so that retrying this exact
        call (after a network timeout, a doubled client request, or a
        prior attempt that created the Supabase user but then failed
        before marking the invitation accepted) always computes the
        exact same candidate id. Concretely:

        - If ``self._auth_admin_client.create_user`` reports the user
          already exists (``InvitationConflictError``), that is treated
          as successful recovery, *not* a hard failure — but recovery is
          not assumed blindly: ``_wait_for_profile`` below still
          confirms a ``profiles`` row exists for exactly the candidate
          id before this method proceeds to link it. If the "already
          exists" was actually a *different*, unrelated account
          coincidentally sharing this email (not a prior attempt of this
          same acceptance), no ``profiles`` row will exist for the
          candidate id, ``_wait_for_profile`` will exhaust its retries,
          and this method fails loudly (``SupabaseAdminOperationError``)
          rather than silently linking the invitation to a profile that
          does not exist.
        - If invitation-status update fails *after* the Supabase user
          was already created (or recovered), the invitation remains
          ``pending`` and unmodified — a retry re-enters this exact same
          method, recomputes the exact same candidate id, hits the
          "already exists" recovery path, and completes the status
          update that failed the first time. No duplicate Supabase user
          is ever created by a retry.
        - Once an invitation is fully accepted, a further retry is
          correctly rejected by ``_require_acceptable`` as an invalid
          state transition (``InvalidInvitationStateError``) — retrying
          a *completed* acceptance is safe in the sense that it never
          corrupts state, but it does not silently succeed a second time
          either, matching every other terminal-state guard in this
          service.

        Args:
            token: The raw (unhashed) invitation token.
            password: The invitee's chosen password, in plaintext, over
                this one call only. Never logged, never persisted by this
                service (Supabase's Auth Admin API is the only place it
                is sent to).

        Returns:
            The accepted ``Invitation``, with ``accepted_at`` and
            ``accepted_profile_id`` populated.

        Raises:
            NotFoundError: If no invitation matches ``token``.
            InvalidInvitationStateError: If the invitation is not
                currently acceptable (already accepted, revoked, or
                pending but expired).
            InvitationConflictError: If Supabase reports an existing user
                for this email/id that ``_wait_for_profile`` cannot
                confirm belongs to this invitation (see above).
            SupabaseAdminOperationError: If Supabase Auth Admin API user
                creation fails for any other reason, or the
                ``on_auth_user_created`` trigger does not provision a
                matching ``profiles`` row within the expected window.
            ConcurrencyError: If another writer changed this invitation
                between this method's read and its write.
        """
        record = self._find_by_token_or_raise(token)
        self._require_acceptable(record)

        # Deterministic, retry-stable candidate id — see this method's
        # own "Idempotency" docstring section above.
        candidate_profile_id = record.id

        try:
            created_profile_id = self._auth_admin_client.create_user(
                user_id=candidate_profile_id,
                email=record.email,
                password=password,
                user_metadata={
                    "full_name": record.full_name,
                    "role": record.role.value,
                    "company_id": str(record.company_id),
                },
            )
        except InvitationConflictError:
            self._logger.info(
                "Supabase reported an existing user while accepting invitation %s; "
                "treating as idempotent recovery from a prior attempt.",
                record.id,
                extra={"invitation_id": str(record.id)},
            )
            created_profile_id = candidate_profile_id

        self._wait_for_profile(created_profile_id)

        try:
            updated = self._invitation_repo.update_status_with_lock(
                record.id,
                expected_version=record.version,
                status=InvitationStatus.ACCEPTED,
                accepted_at=utc_now(),
                accepted_profile_id=created_profile_id,
            )
        except DatabaseError as exc:
            raise translate_database_error(exc) from exc

        self._record_audit_event(
            action=AuditAction.INVITATION_ACCEPTED, actor_id=created_profile_id, record=updated
        )

        self._logger.info(
            "Invitation %s accepted; profile %s provisioned.",
            updated.id,
            created_profile_id,
            extra={"invitation_id": str(updated.id)},
        )
        return map_invitation_record_to_domain(updated)

    def _authorize_admin(self, identity: AuthenticatedIdentity) -> None:
        """Enforce that the caller is an administrator.

        Per the architecture's Security Considerations: invitation
        management is gated on ``UserRole.ADMIN`` directly, the same
        "admin only" role check every other admin-only surface in this
        codebase uses (``rbac.can_manage_user_roles``,
        ``rbac.can_manage_workflow_definitions``), rather than a new
        named ``Permission`` — no finer-grained delegation is required by
        this milestone.

        Args:
            identity: The authenticated caller.

        Raises:
            PermissionDeniedError: If ``identity.role`` is not
                ``UserRole.ADMIN``.
        """
        try:
            rbac.require_role(identity.role, UserRole.ADMIN)
        except Exception as exc:  # noqa: BLE001 - translated below
            raise translate_auth_error(exc) from exc

    def _get_record_or_raise(
        self, invitation_id: UUID, *, identity: AuthenticatedIdentity
    ) -> InvitationRecord:
        """Fetch an invitation record, translating a missing row or one
        outside the caller's company.

        Args:
            invitation_id: The invitation's id.
            identity: The authenticated caller — an invitation belonging
                to a different company is reported as not-found, never as
                a permission failure, matching this codebase's
                established cross-tenant/cross-owner convention.

        Returns:
            The matching ``InvitationRecord``.

        Raises:
            NotFoundError: If no invitation with this id exists, or it
                belongs to a different company.
        """
        try:
            record = self._invitation_repo.get_by_id(invitation_id)
        except DatabaseError as exc:
            raise translate_database_error(exc) from exc
        if record.company_id != identity.company_id:
            raise NotFoundError("invitation", invitation_id)
        return record

    def _require_pending(self, record: InvitationRecord, *, attempted_action: str) -> None:
        """Enforce that an invitation's persisted status is ``pending``.

        Args:
            record: The invitation to check.
            attempted_action: A short label for the rejected action (for
                example, ``"resend"`` or ``"revoke"``), included in the
                raised exception.

        Raises:
            InvalidInvitationStateError: If ``record.status`` is not
                ``InvitationStatus.PENDING``.
        """
        if record.status is not InvitationStatus.PENDING:
            raise InvalidInvitationStateError(
                record.id, record.status.value, attempted_action=attempted_action
            )

    def _find_by_token_or_raise(self, token: str) -> InvitationRecord:
        """Look up an invitation by its raw token, translating absence.

        The raw ``token`` itself is never included in the raised
        exception's message (a placeholder is used instead) — per this
        service's "never log raw tokens" discipline, since an exception's
        message can end up in a log line (``log_calls``' failure-path
        logging, in particular).

        Args:
            token: The raw (unhashed) invitation token.

        Returns:
            The matching ``InvitationRecord``.

        Raises:
            NotFoundError: If no invitation's stored hash matches
                ``token``.
        """
        token_hash = hash_invitation_token(token)
        try:
            record = self._invitation_repo.find_by_token_hash(token_hash)
        except DatabaseError as exc:
            raise translate_database_error(exc) from exc
        if record is None:
            raise NotFoundError("invitation", "<redacted-token>")
        return record

    def _require_acceptable(self, record: InvitationRecord) -> None:
        """Enforce that an invitation may currently be accepted.

        Distinct from ``_require_pending`` (used by resend/revoke): those
        two actions are still valid on a pending-but-expired invitation
        (that is the entire point of resend), but acceptance is not —
        an expired invitation must be resent before it can be accepted.

        Args:
            record: The invitation to check.

        Raises:
            InvalidInvitationStateError: If ``record.status`` is not
                ``InvitationStatus.PENDING`` (``current_status`` set to
                the actual persisted status), or if it is ``PENDING`` but
                ``record.expires_at`` has passed (``current_status`` set
                to the synthetic value ``"expired"``).
        """
        if record.status is not InvitationStatus.PENDING:
            raise InvalidInvitationStateError(
                record.id, record.status.value, attempted_action="accept"
            )
        if is_past(record.expires_at):
            raise InvalidInvitationStateError(record.id, "expired", attempted_action="accept")

    def _wait_for_profile(self, profile_id: UUID) -> None:
        """Wait for the ``on_auth_user_created`` trigger to provision a
        ``profiles`` row for a newly created (or idempotently recovered)
        Supabase user, tolerating brief propagation delay.

        This also doubles as the idempotent-recovery verification step —
        see ``accept_invitation``'s own "Idempotency" docstring section
        for why confirming the row actually exists under this exact id,
        rather than assuming Supabase's "already exists" response always
        means "our own prior attempt," matters.

        Args:
            profile_id: The id to poll ``ProfileRepository`` for.

        Raises:
            SupabaseAdminOperationError: If no matching ``profiles`` row
                appears within ``_PROFILE_PROPAGATION_RETRY_POLICY``'s
                bounded number of attempts.
        """

        def _check() -> None:
            if self._profile_repo.find_by_id(profile_id) is None:
                raise _ProfileNotYetProvisionedError(str(profile_id))

        try:
            retry_call(_check, policy=_PROFILE_PROPAGATION_RETRY_POLICY)
        except RetryExhaustedError as exc:
            raise SupabaseAdminOperationError(
                f"No profile was provisioned for user {profile_id} within the expected "
                "window after Supabase Auth user creation."
            ) from exc

    def _record_audit_event(
        self, *, action: AuditAction, actor_id: UUID, record: InvitationRecord
    ) -> None:
        """Record an invitation-related audit event.

        Args:
            action: The audit action code.
            actor_id: The user performing the action — an administrator
                for create/resend/revoke, or the newly created profile's
                own id for accept (the invitee accepting their own
                invitation; there is no administrator "actor" for that
                event).
            record: The invitation the action was performed on.

        Raises:
            EAHError: A translated ``DatabaseError``, if the audit write
                itself fails.
        """
        try:
            self._audit_repo.record_event(
                action=action,
                actor_id=actor_id,
                metadata={"invitation_id": str(record.id), "email": record.email},
            )
        except DatabaseError as exc:
            raise translate_database_error(exc) from exc

    def _dispatch_invitation_email(
        self, record: InvitationRecord, *, raw_token: str, is_resend: bool = False
    ) -> None:
        """Attempt to dispatch an invitation's email, best-effort.

        Mirrors ``NotificationService._attempt_email_dispatch``'s
        rationale exactly: dispatch is independent of the invitation's
        own creation/resend — a failure here is logged and suppressed,
        never propagated, and never reverses the already-committed
        invitation row. ``raw_token`` is passed to the sender but never
        included in any log message this method emits.

        Args:
            record: The invitation to send an email for.
            raw_token: The raw (unhashed) invitation token.
            is_resend: Passed through to
                ``InvitationEmailSender.send_invitation`` — see its own
                docstring.
        """
        if self._email_sender is None:
            self._logger.debug(
                "Invitation email dispatch skipped for %s: no InvitationEmailSender configured.",
                record.id,
            )
            return

        try:
            sent = self._email_sender.send_invitation(
                to_email=record.email,
                full_name=record.full_name,
                token=raw_token,
                expires_at=record.expires_at,
                is_resend=is_resend,
            )
        except Exception as exc:  # noqa: BLE001 - a sender failure must never propagate
            self._logger.warning(
                "Invitation email dispatch raised for invitation %s: %s",
                record.id,
                exc,
                exc_info=exc,
            )
            return

        if not sent:
            self._logger.warning(
                "Invitation email dispatch reported failure for invitation %s", record.id
            )
