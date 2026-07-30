"""Application service orchestrating platform-level company management.

Every method here is gated by ``authorize_platform_admin``, not
``UserRole.ADMIN`` — company management is a capability above ordinary
company-scoped administration (see that function's own docstring). This
is deliberately the only service in ``app.services`` whose methods are
platform-, not company-, scoped: it is the one place ``company_id`` is
itself the resource, not a filter applied to some other resource.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from uuid import UUID, uuid4

from app.auth.authentication import AuthenticatedIdentity
from app.auth.authorization import authorize_platform_admin
from app.database.exceptions import DatabaseError
from app.database.repositories.audit_repository import AuditRepository
from app.database.repositories.base_repository import Page, PagedResult
from app.database.repositories.company_license_repository import (
    CompanyLicenseRecord,
    CompanyLicenseRepository,
)
from app.database.repositories.company_repository import CompanyRecord, CompanyRepository
from app.database.repositories.user_repository import ProfileRepository
from app.models.company import Company
from app.models.company_license import CompanyLicense
from app.models.enums import AuditAction
from app.services.exceptions import ValidationError, translate_auth_error, translate_database_error
from app.utils.datetime_utils import utc_now
from app.utils.decorators import log_calls

__all__ = ["map_company_record_to_domain", "map_license_record_to_domain", "CompanyService"]

logger = logging.getLogger(__name__)


def map_company_record_to_domain(record: CompanyRecord) -> Company:
    """Map a persistence-level ``CompanyRecord`` into its Domain Layer
    ``Company`` representation.

    Args:
        record: The record returned by ``CompanyRepository``.

    Returns:
        The corresponding ``Company`` domain model.
    """
    return Company(
        id=record.id,
        name=record.name,
        slug=record.slug,
        is_active=record.is_active,
        contact_email=record.contact_email,
        notes=record.notes,
        version=record.version,
        created_at=record.created_at,
        updated_at=record.updated_at,
        deleted_at=record.deleted_at,
        deleted_by=record.deleted_by,
    )


def map_license_record_to_domain(
    record: CompanyLicenseRecord, *, seats_used: int
) -> CompanyLicense:
    """Map a persistence-level ``CompanyLicenseRecord`` into its Domain
    Layer ``CompanyLicense`` representation, computing its informational fields.

    Args:
        record: The record returned by ``CompanyLicenseRepository``.
        seats_used: The company's current user count, supplied by the
            caller (``CompanyService``, via ``ProfileRepository``) — this
            function performs no persistence access of its own.

    Returns:
        The corresponding ``CompanyLicense`` domain model.
    """
    return CompanyLicense(
        company_id=record.company_id,
        plan_tier=record.plan_tier,
        seat_limit=record.seat_limit,
        expires_at=record.expires_at,
        notes=record.notes,
        seats_used=seats_used,
        is_expired=record.expires_at is not None and record.expires_at <= utc_now(),
        updated_at=record.updated_at,
    )


def _slugify(name: str) -> str:
    """Derive a unique, URL-safe slug from a company name.

    A random suffix is always appended, rather than relying on the name
    alone plus a database-rejection retry loop, since two companies may
    legitimately share a display name (e.g. two unrelated "Acme"
    customers) — this keeps company creation a single, always-succeeding
    call with no collision-retry logic needed.

    Args:
        name: The company's display name.

    Returns:
        A unique, lowercase, hyphen-separated slug.
    """
    base = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    suffix = uuid4().hex[:8]
    return f"{base}-{suffix}" if base else suffix


class CompanyService:
    """Orchestrates platform-admin-only company creation, listing, and updates."""

    def __init__(
        self,
        *,
        company_repo: CompanyRepository,
        license_repo: CompanyLicenseRepository,
        profile_repo: ProfileRepository,
        audit_repo: AuditRepository,
    ) -> None:
        """Initialize the service with its injected collaborators.

        Args:
            company_repo: Persistence for ``companies``.
            license_repo: Persistence for ``company_licenses``.
            profile_repo: Used to compute a license's informational
                ``seats_used`` figure.
            audit_repo: Records every company mutation this service
                performs — previously, this service wrote no audit
                entries at all.
        """
        self._company_repo = company_repo
        self._license_repo = license_repo
        self._profile_repo = profile_repo
        self._audit_repo = audit_repo
        self._logger = logging.getLogger(f"{__name__}.CompanyService")

    def _authorize(self, identity: AuthenticatedIdentity) -> None:
        try:
            authorize_platform_admin(identity)
        except Exception as exc:  # noqa: BLE001 - translated below
            raise translate_auth_error(exc) from exc

    def _guard_against_self_lockout(
        self, identity: AuthenticatedIdentity, company_id: UUID, *, action: str
    ) -> None:
        """Refuse to let a platform admin suspend/delete their own company.

        Args:
            identity: The authenticated caller.
            company_id: The company about to be suspended or deleted.
            action: A short, human-readable action name for the error
                message (e.g. ``"suspend"``, ``"delete"``).

        Raises:
            ValidationError: If ``company_id`` is the caller's own company.
        """
        if company_id == identity.company_id:
            raise ValidationError(f"You may not {action} your own company.")

    @log_calls()
    def create_company(self, identity: AuthenticatedIdentity, *, name: str) -> Company:
        """Create a new, active company.

        Args:
            identity: The authenticated caller. Must be a platform admin.
            name: The company's display name.

        Returns:
            The newly created ``Company``.

        Raises:
            PermissionDeniedError: If the caller is not a platform admin.
        """
        self._authorize(identity)

        slug = _slugify(name)
        try:
            created = self._company_repo.create_company(name=name, slug=slug)
        except DatabaseError as exc:
            raise translate_database_error(exc) from exc

        self._audit_repo.record_event(
            action=AuditAction.COMPANY_CREATED,
            actor_id=identity.user_id,
            metadata={"company_id": str(created.id), "name": created.name},
        )
        self._logger.info(
            "Created company %s (%s)",
            created.id,
            created.name,
            extra={"company_id": str(created.id)},
        )
        return map_company_record_to_domain(created)

    @log_calls()
    def get_company(self, identity: AuthenticatedIdentity, company_id: UUID) -> Company:
        """Fetch a single company's detail.

        Args:
            identity: The authenticated caller. Must be a platform admin.
            company_id: The company's id.

        Returns:
            The matching ``Company``.

        Raises:
            PermissionDeniedError: If the caller is not a platform admin.
            NotFoundError: If no company with this id exists.
        """
        self._authorize(identity)

        try:
            record = self._company_repo.get_by_id(company_id)
        except DatabaseError as exc:
            raise translate_database_error(exc) from exc
        return map_company_record_to_domain(record)

    @log_calls()
    def list_companies(
        self,
        identity: AuthenticatedIdentity,
        *,
        include_deleted: bool = False,
        page: Page = Page(),
    ) -> PagedResult[Company]:
        """List every company on the platform.

        Args:
            identity: The authenticated caller. Must be a platform admin.
            include_deleted: Whether to include soft-deleted companies.
            page: The page to retrieve.

        Returns:
            A ``PagedResult`` of every ``Company``.

        Raises:
            PermissionDeniedError: If the caller is not a platform admin.
        """
        self._authorize(identity)

        try:
            result = self._company_repo.list_companies(include_deleted=include_deleted, page=page)
        except DatabaseError as exc:
            raise translate_database_error(exc) from exc

        return PagedResult(
            items=[map_company_record_to_domain(r) for r in result.items],
            page=result.page,
            page_size=result.page_size,
            total_records=result.total_records,
        )

    @log_calls()
    def update_company(
        self,
        identity: AuthenticatedIdentity,
        company_id: UUID,
        *,
        expected_version: int,
        name: str | None = None,
        is_active: bool | None = None,
        contact_email: str | None = None,
        notes: str | None = None,
    ) -> Company:
        """Update a company's display name, active status, and/or settings.

        Deactivating (suspending) a company is enforced at authentication
        (``app.auth.supabase_verifier.SupabaseTokenVerifier``) — every
        user in the company is rejected on their very next request. It
        never deletes or hides any of the company's data.

        Args:
            identity: The authenticated caller. Must be a platform admin.
            company_id: The company's id.
            expected_version: The version last observed by the caller.
            name: The new display name, if changing.
            is_active: The new active status, if changing.
            contact_email: The new contact email, if changing.
            notes: The new notes, if changing.

        Returns:
            The updated ``Company``.

        Raises:
            PermissionDeniedError: If the caller is not a platform admin.
            ValidationError: If ``is_active=False`` is requested for the
                caller's own company.
            NotFoundError: If no company with this id exists.
            ConcurrencyError: If ``expected_version`` no longer matches.
        """
        self._authorize(identity)
        if is_active is False:
            self._guard_against_self_lockout(identity, company_id, action="suspend")

        try:
            updated = self._company_repo.update_company(
                company_id,
                expected_version=expected_version,
                name=name,
                is_active=is_active,
                contact_email=contact_email,
                notes=notes,
            )
        except DatabaseError as exc:
            raise translate_database_error(exc) from exc

        if is_active is not None:
            self._audit_repo.record_event(
                action=(
                    AuditAction.COMPANY_REACTIVATED
                    if is_active
                    else AuditAction.COMPANY_SUSPENDED
                ),
                actor_id=identity.user_id,
                company_id=company_id,
            )
        if contact_email is not None or notes is not None:
            self._audit_repo.record_event(
                action=AuditAction.COMPANY_SETTINGS_UPDATED,
                actor_id=identity.user_id,
                company_id=company_id,
            )
        return map_company_record_to_domain(updated)

    @log_calls()
    def soft_delete_company(
        self, identity: AuthenticatedIdentity, company_id: UUID, *, expected_version: int
    ) -> Company:
        """Soft-delete a company: retains every row it owns, blocks access.

        Args:
            identity: The authenticated caller. Must be a platform admin.
            company_id: The company's id.
            expected_version: The version last observed by the caller.

        Returns:
            The updated ``Company``, with ``deleted_at`` populated.

        Raises:
            PermissionDeniedError: If the caller is not a platform admin.
            ValidationError: If the caller's own company is targeted.
            NotFoundError: If no company with this id exists.
            ConcurrencyError: If ``expected_version`` no longer matches.
        """
        self._authorize(identity)
        self._guard_against_self_lockout(identity, company_id, action="delete")

        try:
            deleted = self._company_repo.soft_delete(
                company_id, expected_version=expected_version, deleted_by=identity.user_id
            )
        except DatabaseError as exc:
            raise translate_database_error(exc) from exc

        self._audit_repo.record_event(
            action=AuditAction.COMPANY_DELETED,
            actor_id=identity.user_id,
            company_id=company_id,
        )
        return map_company_record_to_domain(deleted)

    @log_calls()
    def restore_company(
        self, identity: AuthenticatedIdentity, company_id: UUID, *, expected_version: int
    ) -> Company:
        """Reverse a soft-deletion, restoring the company to the active list.

        Args:
            identity: The authenticated caller. Must be a platform admin.
            company_id: The company's id.
            expected_version: The version last observed by the caller.

        Returns:
            The updated ``Company``.

        Raises:
            PermissionDeniedError: If the caller is not a platform admin.
            NotFoundError: If no company with this id exists.
            ConcurrencyError: If ``expected_version`` no longer matches.
        """
        self._authorize(identity)

        try:
            restored = self._company_repo.restore(company_id, expected_version=expected_version)
        except DatabaseError as exc:
            raise translate_database_error(exc) from exc

        self._audit_repo.record_event(
            action=AuditAction.COMPANY_RESTORED,
            actor_id=identity.user_id,
            company_id=company_id,
        )
        return map_company_record_to_domain(restored)

    @log_calls()
    def get_license(
        self, identity: AuthenticatedIdentity, company_id: UUID
    ) -> CompanyLicense | None:
        """Fetch a company's license, if one has been configured.

        Args:
            identity: The authenticated caller. Must be a platform admin.
            company_id: The company's id.

        Returns:
            The ``CompanyLicense``, or ``None`` if this company has no
            license configured yet.

        Raises:
            PermissionDeniedError: If the caller is not a platform admin.
        """
        self._authorize(identity)

        try:
            record = self._license_repo.get_for_company(company_id)
            if record is None:
                return None
            seats_used = self._profile_repo.count_for_company(company_id)
        except DatabaseError as exc:
            raise translate_database_error(exc) from exc

        return map_license_record_to_domain(record, seats_used=seats_used)

    @log_calls()
    def update_license(
        self,
        identity: AuthenticatedIdentity,
        company_id: UUID,
        *,
        plan_tier: str | None = None,
        seat_limit: int | None = None,
        expires_at: datetime | None = None,
        notes: str | None = None,
    ) -> CompanyLicense:
        """Set or update a company's license.

        Partial-patch semantics: a field left unset (``None``) keeps its
        current value (or the default, for a company with no license
        yet) rather than being reset. A known, disclosed limitation of
        this convention: ``seat_limit``/``expires_at`` cannot be
        explicitly cleared back to "unlimited"/"no expiry" once set in
        this pass (``notes``/``plan_tier`` can, via an empty string) —
        acceptable given this feature's deliberately lightweight,
        informational scope. Purely informational either way — nothing
        in this codebase enforces ``seat_limit`` or ``expires_at``
        against anything; see ``CompanyLicense``'s own docstring.

        Args:
            identity: The authenticated caller. Must be a platform admin.
            company_id: The company's id.
            plan_tier: The new plan identifier, if changing.
            seat_limit: The new seat limit, if changing.
            expires_at: The new expiry, if changing.
            notes: The new notes, if changing.

        Returns:
            The resulting ``CompanyLicense``.

        Raises:
            PermissionDeniedError: If the caller is not a platform admin.
        """
        self._authorize(identity)

        try:
            current = self._license_repo.get_for_company(company_id)
            updated = self._license_repo.upsert(
                company_id,
                plan_tier=plan_tier if plan_tier is not None else (current.plan_tier if current else "free"),
                seat_limit=seat_limit if seat_limit is not None else (current.seat_limit if current else None),
                expires_at=expires_at if expires_at is not None else (current.expires_at if current else None),
                notes=notes if notes is not None else (current.notes if current else None),
                updated_by=identity.user_id,
            )
            seats_used = self._profile_repo.count_for_company(company_id)
        except DatabaseError as exc:
            raise translate_database_error(exc) from exc

        self._audit_repo.record_event(
            action=AuditAction.COMPANY_LICENSE_UPDATED,
            actor_id=identity.user_id,
            company_id=company_id,
        )
        return map_license_record_to_domain(updated, seats_used=seats_used)
