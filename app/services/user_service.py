"""Application service orchestrating profile lifecycle: role/department
assignment, deactivation/reactivation, and GDPR right-to-erasure.

Per this codebase's own stated reason ``app.api.routers.admin_users``
previously bypassed a service layer entirely ("``ProfileRepository`` has
no owning Application Service ... no such business logic exists
elsewhere"): the deactivation/erasure lifecycle introduced by
``0020_profile_lifecycle`` *is* real business logic (self-lockout guard,
Supabase Admin API orchestration, audit-event branching), so per that same
stated principle, this module is a new, correct addition, not scope creep.

Mirrors ``app.services.company_service.CompanyService`` closely: ordinary
mutations, a suspend/reactivate toggle folded into one generic update
method, and an irreversible destructive operation with a self-lockout
guard and its own audit action. The one structural difference: erasure has
no ``restore`` counterpart, because it also overwrites PII
(``full_name``/``department``) — once applied, there is nothing to restore
to (see ``ProfileRepository.erase``'s own docstring).
"""

from __future__ import annotations

import logging
from uuid import UUID

from app.auth import rbac
from app.auth.authentication import AuthenticatedIdentity
from app.database.exceptions import DatabaseError
from app.database.repositories.audit_repository import AuditRepository
from app.database.repositories.user_repository import ProfileRecord, ProfileRepository, UserRole
from app.models.enums import AuditAction
from app.services.exceptions import (
    NotFoundError,
    ValidationError,
    translate_auth_error,
    translate_database_error,
)
from app.services.supabase_admin_client import SupabaseAuthAdminClient
from app.utils.decorators import log_calls

__all__ = ["UserService"]

logger = logging.getLogger(__name__)


def _anonymized_full_name(user_id: UUID) -> str:
    """A stable, deterministic placeholder display name for an erased user.

    Derived from the profile's own id (never randomized) so that two
    distinct erased users remain distinguishable from one another in
    historical records (audit logs, old requests/comments) without
    exposing any real name.
    """
    return f"Deleted User {str(user_id)[:8]}"


def _anonymized_email(user_id: UUID) -> str:
    """A deterministic, non-deliverable replacement email for an erased user.

    ``.invalid`` is the RFC 2606 reserved TLD for addresses that must
    never resolve or be deliverable.
    """
    return f"deleted-{user_id}@erased.invalid"


class UserService:
    """Orchestrates admin-only profile mutations: role/department,
    deactivation/reactivation, and GDPR erasure."""

    def __init__(
        self,
        *,
        profile_repo: ProfileRepository,
        audit_repo: AuditRepository,
        auth_admin_client: SupabaseAuthAdminClient,
    ) -> None:
        """Initialize the service with its injected collaborators.

        Args:
            profile_repo: Persistence for ``profiles``.
            audit_repo: Records every mutation this service performs.
            auth_admin_client: Used by ``erase_user`` to scrub the
                corresponding Supabase Auth user's email and ban further
                login — the one piece of PII (email) that lives outside
                ``profiles`` entirely.
        """
        self._profile_repo = profile_repo
        self._audit_repo = audit_repo
        self._auth_admin_client = auth_admin_client
        self._logger = logging.getLogger(f"{__name__}.UserService")

    def _authorize(self, identity: AuthenticatedIdentity) -> None:
        try:
            if not rbac.can_manage_user_roles(identity.role):
                rbac.require_role(identity.role, UserRole.ADMIN)  # always raises here
        except Exception as exc:  # noqa: BLE001 - translated below
            raise translate_auth_error(exc) from exc

    def _get_in_tenant(self, identity: AuthenticatedIdentity, user_id: UUID) -> ProfileRecord:
        try:
            profile = self._profile_repo.get_by_id(user_id)
        except DatabaseError as exc:
            raise translate_database_error(exc) from exc
        if profile.company_id != identity.company_id:
            raise NotFoundError("profile", user_id)
        return profile

    @log_calls()
    def update_profile(
        self,
        identity: AuthenticatedIdentity,
        user_id: UUID,
        *,
        expected_version: int,
        role: UserRole | None = None,
        department: str | None = None,
        is_active: bool | None = None,
    ) -> ProfileRecord:
        """Update a profile's role, department, and/or active status.

        Deactivation (``is_active=False``) is enforced at authentication
        (``app.auth.supabase_verifier.SupabaseTokenVerifier``) — the user
        is rejected on their very next request. It never touches any
        other data and is fully reversible via ``is_active=True``.

        Args:
            identity: The authenticated caller. Must be able to manage
                user roles (``UserRole.ADMIN``).
            user_id: The profile's id.
            expected_version: The version last observed by the caller.
            role: The new RBAC role, if changing.
            department: The new department, if changing.
            is_active: The new active status, if changing.

        Returns:
            The updated ``ProfileRecord``.

        Raises:
            PermissionDeniedError: If the caller cannot manage user roles.
            ValidationError: If ``is_active=False`` is requested for the
                caller's own account.
            NotFoundError: If no profile with this id exists in the
                caller's own company.
            ConcurrencyError: If ``expected_version`` no longer matches.
        """
        self._authorize(identity)
        if is_active is False and user_id == identity.user_id:
            raise ValidationError("You may not deactivate your own account.")
        self._get_in_tenant(identity, user_id)

        try:
            updated = self._profile_repo.update_profile(
                user_id,
                expected_version=expected_version,
                role=role,
                department=department,
                is_active=is_active,
            )
        except DatabaseError as exc:
            raise translate_database_error(exc) from exc

        if is_active is not None:
            self._audit_repo.record_event(
                action=(
                    AuditAction.PROFILE_REACTIVATED
                    if is_active
                    else AuditAction.PROFILE_DEACTIVATED
                ),
                actor_id=identity.user_id,
                company_id=identity.company_id,
                metadata={"user_id": str(user_id)},
            )
        if role is not None or department is not None:
            self._audit_repo.record_event(
                action=AuditAction.PROFILE_UPDATED,
                actor_id=identity.user_id,
                company_id=identity.company_id,
                metadata={"user_id": str(user_id)},
            )
        return updated

    @log_calls()
    def erase_user(
        self, identity: AuthenticatedIdentity, user_id: UUID, *, expected_version: int
    ) -> ProfileRecord:
        """Erase a user: GDPR right-to-erasure.

        Anonymizes ``full_name``/``department`` and sets ``deleted_at``/
        ``deleted_by``/``is_active=False`` on the ``profiles`` row (never
        removes it — see ``ProfileRepository.erase``'s own docstring for
        why a genuine ``DELETE`` is impossible for any user with real
        history), and scrubs the corresponding Supabase Auth user's email
        while permanently banning further login
        (``SupabaseAuthAdminClient.anonymize_user``).

        Idempotent: if this profile is already erased, returns the
        current record unchanged rather than repeating either step —
        safe to retry after a partial failure (the auth-side scrub
        succeeded but the database write then hit a stale-version
        conflict, for example).

        **Irreversible.** Unlike ``update_profile``'s ``is_active``
        toggle, there is no corresponding "un-erase" operation: once
        ``full_name``/``department`` are overwritten, the original values
        are gone.

        Args:
            identity: The authenticated caller. Must be able to manage
                user roles (``UserRole.ADMIN``).
            user_id: The profile's id.
            expected_version: The version last observed by the caller.

        Returns:
            The anonymized ``ProfileRecord``.

        Raises:
            PermissionDeniedError: If the caller cannot manage user roles.
            ValidationError: If the caller's own account is targeted.
            NotFoundError: If no profile with this id exists in the
                caller's own company.
            ConcurrencyError: If ``expected_version`` no longer matches
                (never raised on the idempotent-replay path, since that
                path performs no write).
            SupabaseAdminOperationError: If the Supabase Auth Admin API
                scrub fails — nothing in ``profiles`` is changed in that
                case, so retrying the whole operation is always safe.
        """
        self._authorize(identity)
        if user_id == identity.user_id:
            raise ValidationError("You may not erase your own account.")
        existing = self._get_in_tenant(identity, user_id)

        if existing.deleted_at is not None:
            self._logger.info(
                "Profile %s is already erased; erase_user is a no-op replay.", user_id
            )
            return existing

        # The external, harder-to-retry side goes first: if it fails,
        # nothing in our own database has changed yet.
        self._auth_admin_client.anonymize_user(
            user_id=user_id, anonymized_email=_anonymized_email(user_id)
        )

        try:
            erased = self._profile_repo.erase(
                user_id,
                expected_version=expected_version,
                deleted_by=identity.user_id,
                anonymized_full_name=_anonymized_full_name(user_id),
            )
        except DatabaseError as exc:
            raise translate_database_error(exc) from exc

        self._audit_repo.record_event(
            action=AuditAction.PROFILE_ERASED,
            actor_id=identity.user_id,
            company_id=identity.company_id,
            metadata={"user_id": str(user_id)},
        )
        return erased
