"""Routes for the ``notifications`` resource: the caller's own
Notification Center.

Every handler below is a thin wrapper over ``NotificationService``, which
is already fully identity-scoped (every method takes an
``AuthenticatedIdentity`` and hard-scopes to ``identity.user_id`` — there
is no "list all users' notifications" method) — no RBAC gate is added
here, since there is nothing to gate: every role may read and act on only
its own notifications. Responses wrap ``app.models.Notification`` via
``app.api.schemas.notifications.NotificationOut`` — see that module's
docstring for why a thin wrapper is still needed despite ``Notification``
already being a validated Pydantic model.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request

from app.api.dependencies import get_current_identity, get_notification_service
from app.api.rate_limiting import enforce_notification_poll_rate_limit
from app.api.schemas.notifications import NotificationOut
from app.auth.authentication import AuthenticatedIdentity
from app.config.constants import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from app.database.repositories.base_repository import Page
from app.models import Notification, NotificationPreference, NotificationPreferenceUpdate
from app.models.enums import NotificationType
from app.services.notification_service import NotificationService
from app.utils.pagination import build_pagination_metadata
from app.utils.response import build_list_response, build_success_response
from app.utils.serialization import serialize

__all__ = ["router"]

router = APIRouter(tags=["notifications"])


def _request_id_of(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


def _out(notification: Notification) -> dict[str, object]:
    return serialize(NotificationOut.model_validate(notification))


def _preference_out(preference: NotificationPreference) -> dict[str, object]:
    return serialize(preference)


@router.get("/notifications")
def list_notifications(
    request: Request,
    is_read: bool | None = Query(None),
    notification_type: NotificationType | None = Query(None),
    is_archived: bool | None = Query(False),
    search: str | None = Query(None, max_length=200),
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    service: NotificationService = Depends(get_notification_service),
) -> dict[str, Any]:
    """The caller's own notifications. See ``NotificationService.list_notifications``."""
    result = service.list_notifications(
        identity,
        is_read=is_read,
        notification_type=notification_type,
        is_archived=is_archived,
        search=search,
        page=Page(number=page, size=page_size),
    )
    pagination = build_pagination_metadata(
        page=result.page, page_size=result.page_size, total_records=result.total_records
    )
    return build_list_response(
        [_out(item) for item in result.items],
        pagination=pagination,
        request_id=_request_id_of(request),
    )


@router.get(
    "/notifications/unread-count", dependencies=[Depends(enforce_notification_poll_rate_limit)]
)
def get_unread_count(
    request: Request,
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    service: NotificationService = Depends(get_notification_service),
) -> dict[str, Any]:
    """The caller's unread notification count. See ``NotificationService.get_unread_count``."""
    count = service.get_unread_count(identity)
    return build_success_response({"unread_count": count}, request_id=_request_id_of(request))


@router.post("/notifications/{notification_id}/read")
def mark_notification_read(
    request: Request,
    notification_id: UUID,
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    service: NotificationService = Depends(get_notification_service),
) -> dict[str, Any]:
    """Mark one notification as read. See ``NotificationService.mark_read``."""
    notification = service.mark_read(identity, notification_id)
    return build_success_response(_out(notification), request_id=_request_id_of(request))


@router.post("/notifications/read-all")
def mark_all_notifications_read(
    request: Request,
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    service: NotificationService = Depends(get_notification_service),
) -> dict[str, Any]:
    """Mark every unread notification of the caller's as read. See ``NotificationService.mark_all_read``."""
    updated = service.mark_all_read(identity)
    return build_success_response({"updated": updated}, request_id=_request_id_of(request))


@router.post("/notifications/{notification_id}/archive")
def archive_notification(
    request: Request,
    notification_id: UUID,
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    service: NotificationService = Depends(get_notification_service),
) -> dict[str, Any]:
    """Archive one notification. See ``NotificationService.archive_notification``."""
    notification = service.archive_notification(identity, notification_id)
    return build_success_response(_out(notification), request_id=_request_id_of(request))


@router.post("/notifications/{notification_id}/unarchive")
def unarchive_notification(
    request: Request,
    notification_id: UUID,
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    service: NotificationService = Depends(get_notification_service),
) -> dict[str, Any]:
    """Restore one archived notification. See ``NotificationService.unarchive_notification``."""
    notification = service.unarchive_notification(identity, notification_id)
    return build_success_response(_out(notification), request_id=_request_id_of(request))


@router.get("/notifications/preferences")
def list_notification_preferences(
    request: Request,
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    service: NotificationService = Depends(get_notification_service),
) -> dict[str, Any]:
    """The caller's effective preference for every notification type. See
    ``NotificationService.list_preferences``.

    Not paginated — always exactly ``len(NotificationType)`` entries, so
    this returns a plain success response (list payload, no pagination
    metadata) rather than ``build_list_response``.
    """
    preferences = service.list_preferences(identity)
    return build_success_response(
        [_preference_out(p) for p in preferences], request_id=_request_id_of(request)
    )


@router.patch("/notifications/preferences/{notification_type}")
def update_notification_preference(
    request: Request,
    notification_type: NotificationType,
    body: NotificationPreferenceUpdate,
    identity: AuthenticatedIdentity = Depends(get_current_identity),
    service: NotificationService = Depends(get_notification_service),
) -> dict[str, Any]:
    """Set the caller's preference for one notification type. See
    ``NotificationService.update_preference``."""
    preference = service.update_preference(
        identity,
        notification_type,
        in_app_enabled=body.in_app_enabled,
        email_enabled=body.email_enabled,
    )
    return build_success_response(_preference_out(preference), request_id=_request_id_of(request))
