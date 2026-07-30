"""HTTP response schema wrapping ``RequestService.get_audit_trail``'s
read model.

See ``app.api.schemas.workflow`` for why a wrapper is needed at all:
``app.services.request_service.AuditEntryDetail`` is a plain dataclass,
not a ``pydantic.BaseModel``.
"""

from __future__ import annotations

from typing import Any

from pydantic import ConfigDict

from app.models.base import EAHBaseModel, UTCDatetime
from app.models.enums import AuditAction

__all__ = ["AuditEntryOut"]


class AuditEntryOut(EAHBaseModel):
    """Wraps ``app.services.request_service.AuditEntryDetail``."""

    model_config = ConfigDict(from_attributes=True, extra="forbid", frozen=True)

    action: AuditAction
    actor_name: str | None
    created_at: UTCDatetime
    metadata: dict[str, Any] | None
