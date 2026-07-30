"""Domain model for the ``notification_preferences`` table.

Per-user, per-``notification_type`` overrides of the default "always
in-app, always email" delivery behavior described in
``app.services.notification_service``. Corresponds to the persistence
layer's
``app.database.repositories.notification_preference_repository.NotificationPreferenceRepository``.
"""

from __future__ import annotations

from pydantic import model_validator

from app.models.base import EAHBaseModel, PartialUpdateModel, UTCDatetime
from app.models.enums import NotificationType
from app.models.exceptions import EmptyUpdatePayloadError

__all__ = ["NotificationPreference", "NotificationPreferenceUpdate"]


class NotificationPreference(EAHBaseModel):
    """A user's effective delivery preference for one notification type.

    Deliberately not an ``IdentifiedModel``: a type the caller has never
    explicitly configured has no corresponding
    ``notification_preferences`` row at all — it is a synthesized default
    (both flags ``True``, ``updated_at=None``), not a persisted record.
    ``NotificationService.list_preferences`` always returns exactly one
    entry per ``NotificationType`` regardless of which ones actually have
    a row.

    Attributes:
        notification_type: The notification category this preference
            applies to.
        in_app_enabled: Whether this event is recorded in the caller's
            in-app notification center at all. ``False`` suppresses the
            notification entirely — including its email leg, since there
            is no persisted row to attach delivery metadata to.
        email_enabled: Whether this event, when recorded in-app, is also
            emailed. Irrelevant when ``in_app_enabled`` is ``False``.
        updated_at: When this preference was last explicitly set, or
            ``None`` if the caller has never configured this type (the
            two flags above are then the synthesized default).
    """

    notification_type: NotificationType
    in_app_enabled: bool
    email_enabled: bool
    updated_at: UTCDatetime | None = None


class NotificationPreferenceUpdate(PartialUpdateModel):
    """Input model for ``PATCH /api/v1/notifications/preferences/{notification_type}``.

    Attributes:
        in_app_enabled: Whether to record this event in-app going
            forward, if changing.
        email_enabled: Whether to also email this event going forward,
            if changing.
    """

    in_app_enabled: bool | None = None
    email_enabled: bool | None = None

    @model_validator(mode="after")
    def _require_at_least_one_field(self) -> NotificationPreferenceUpdate:
        """Reject a patch payload that sets no field at all.

        Raises:
            EmptyUpdatePayloadError: If no field was explicitly provided.
        """
        if not self.has_updates():
            raise EmptyUpdatePayloadError(
                "NotificationPreferenceUpdate requires at least one field to update."
            )
        return self
