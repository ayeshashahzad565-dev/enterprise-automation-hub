"""Routes for the admin Users module: directory browsing, profile
detail, role/department/active-status assignment, GDPR erasure, and
per-user activity.

``GET`` routes here have no business logic beyond admin-gating and a
cross-tenant existence check, so they still call ``ProfileRepository``/
``AuditRepository`` directly — the same narrow, already-established
exception this API layer uses for ``audit_repo``/``approval_repo`` in
``app.api.routers.analytics``. Any ``app.database.exceptions.DatabaseError``
these direct repository calls can raise is translated via the existing
``app.services.exceptions.translate_database_error``.

The mutating routes (``PATCH``, ``DELETE``) go through ``UserService``:
deactivation/reactivation and GDPR erasure are real business logic
(self-lockout guards, Supabase Auth Admin API orchestration, audit-event
branching) — the exact condition under which this module's previous
revision said a service layer would be warranted ("no such business logic
exists elsewhere ... building either now would mean writing new business
logic"). It now does, so ``UserService`` exists.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request

from app.api.dependencies import (
    get_audit_repository,
    get_current_identity,
    get_profile_repository,
    get_user_service,
)
from app.api.schemas.admin import UserOut, UserPatchBody
from app.api.schemas.analytics import AuditLogEntryOut
from app.auth import rbac
from app.auth.authentication import AuthenticatedIdentity
from app.config.constants import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from app.database.exceptions import DatabaseError
from app.database.repositories.audit_repository import AuditRepository
from app.database.repositories.base_repository import Page
from app.database.repositories.user_repository import ProfileRepository
from app.models.enums import AuditAction, UserRole
from app.services.exceptions import NotFoundError, ValidationError, translate_database_error
from app.services.user_service import UserService
from app.utils.pagination import build_pagination_metadata
from app.utils.response import build_list_response, build_success_response
from app.utils.serialization import serialize

__all__ = ["router"]

router = APIRouter(tags=["admin-users"])


def _request_id_of(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


def _require_admin(identity: AuthenticatedIdentity) -> None:
    rbac.require_role(identity.role, UserRole.ADMIN)


@router.get("/admin/users")
def list_admin_users(
    request: Request,
    role: UserRole | None = Query(None),
    department: str | None = Query(None, max_length=200),
    query: str | None = Query(None, max_length=200),
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    profile_repo: ProfileRepository = Depends(get_profile_repository),
) -> dict[str, Any]:
    """Browse the user directory by role, or search by name. Admin only.

    One of ``role`` or ``query`` is required — mirrors the
    ``workflow-definitions`` list/search pattern, since
    ``ProfileRepository`` likewise exposes two separate, non-overlapping
    read methods (``list_by_role``, ``search_by_name``) rather than one
    general "list all" method.
    """
    _require_admin(identity)
    page_obj = Page(number=page, size=page_size)
    try:
        if role is not None:
            result = profile_repo.list_by_role(
                role, company_id=identity.company_id, department=department, page=page_obj
            )
        elif query is not None:
            result = profile_repo.search_by_name(
                query, company_id=identity.company_id, page=page_obj
            )
        else:
            raise ValidationError("Either 'role' or 'query' is required.")
    except DatabaseError as exc:
        raise translate_database_error(exc) from exc

    pagination = build_pagination_metadata(
        page=result.page, page_size=result.page_size, total_records=result.total_records
    )
    out = [serialize(UserOut.model_validate(p)) for p in result.items]
    return build_list_response(out, pagination=pagination, request_id=_request_id_of(request))


@router.get("/admin/users/{user_id}")
def get_admin_user(
    request: Request,
    user_id: UUID,
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    profile_repo: ProfileRepository = Depends(get_profile_repository),
) -> dict[str, Any]:
    """Fetch one user's profile. Admin only."""
    _require_admin(identity)
    try:
        profile = profile_repo.get_by_id(user_id)
    except DatabaseError as exc:
        raise translate_database_error(exc) from exc
    if profile.company_id != identity.company_id:
        raise NotFoundError("profile", user_id)
    out = UserOut.model_validate(profile)
    return build_success_response(serialize(out), request_id=_request_id_of(request))


@router.patch("/admin/users/{user_id}")
def update_admin_user(
    request: Request,
    user_id: UUID,
    body: UserPatchBody,
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    service: UserService = Depends(get_user_service),
) -> dict[str, Any]:
    """Change a user's role, department, and/or active status. Admin only.

    See ``rbac.can_manage_user_roles``: "Only admin may update role or
    department for any profile." ``is_active`` (deactivation/reactivation)
    was added for the profile-lifecycle feature — see
    ``UserService.update_profile``.
    """
    updated = service.update_profile(
        identity,
        user_id,
        expected_version=body.expected_version,
        role=body.role,
        department=body.department,
        is_active=body.is_active,
    )
    out = UserOut.model_validate(updated)
    return build_success_response(serialize(out), request_id=_request_id_of(request))


@router.delete("/admin/users/{user_id}", status_code=200)
def erase_admin_user(
    request: Request,
    user_id: UUID,
    expected_version: int = Query(..., ge=1),
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    service: UserService = Depends(get_user_service),
) -> dict[str, Any]:
    """Erase a user: GDPR right-to-erasure. Admin only.

    Irreversible — see ``UserService.erase_user``'s own docstring. Mirrors
    ``DELETE /companies/{company_id}``'s exact request shape
    (``expected_version`` as a query parameter, since ``DELETE`` requests
    conventionally carry no body).
    """
    erased = service.erase_user(identity, user_id, expected_version=expected_version)
    out = UserOut.model_validate(erased)
    return build_success_response(serialize(out), request_id=_request_id_of(request))


@router.get("/admin/users/{user_id}/activity")
def get_admin_user_activity(
    request: Request,
    user_id: UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    profile_repo: ProfileRepository = Depends(get_profile_repository),
    audit_repo: AuditRepository = Depends(get_audit_repository),
) -> dict[str, Any]:
    """One user's personal activity history. Admin only. See
    ``AuditRepository.list_for_actor`` — the same method Phase 5's
    Activity Center already uses for a caller's own history.
    """
    _require_admin(identity)
    try:
        profile = profile_repo.get_by_id(user_id)
    except DatabaseError as exc:
        raise translate_database_error(exc) from exc
    if profile.company_id != identity.company_id:
        raise NotFoundError("profile", user_id)

    result = audit_repo.list_for_actor(user_id, page=Page(number=page, size=page_size))
    items = [
        AuditLogEntryOut(
            id=entry.id,
            actor_id=entry.actor_id,
            actor_name=profile.full_name,
            request_id=entry.request_id,
            action=AuditAction(entry.action),
            metadata=entry.metadata,
            created_at=entry.created_at,
        )
        for entry in result.items
    ]
    pagination = build_pagination_metadata(
        page=result.page, page_size=result.page_size, total_records=result.total_records
    )
    return build_list_response(
        [serialize(item) for item in items],
        pagination=pagination,
        request_id=_request_id_of(request),
    )
