"""HTTP response schemas wrapping ``RequestService``'s workflow-progress
read model.

``app.services.request_service.WorkflowStageDetail``/``UpcomingStage``/
``WorkflowProgress`` are plain ``@dataclass`` instances (not Pydantic
models), since they are read-only, presentation-enriched projections, not
persisted domain entities. ``app.utils.serialization.serialize`` only
accepts a ``pydantic.BaseModel``, so these thin wrappers exist purely to
give the existing dataclasses a JSON-serializable shape — built via
``Model.model_validate(dataclass_instance)`` (``from_attributes=True``),
never by re-deriving any field.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import ConfigDict

from app.models.base import EAHBaseModel, UTCDatetime
from app.models.enums import StageStatus, UserRole

__all__ = ["WorkflowStageDetailOut", "UpcomingStageOut", "WorkflowProgressOut"]


class WorkflowStageDetailOut(EAHBaseModel):
    """Wraps ``app.services.request_service.WorkflowStageDetail``."""

    model_config = ConfigDict(from_attributes=True, extra="forbid", frozen=True)

    stage_id: UUID
    stage_order: int
    stage_name: str
    assigned_to_name: str | None
    assigned_role: UserRole | None
    status: StageStatus
    created_at: UTCDatetime
    decided_at: UTCDatetime | None
    decided_by_name: str | None
    decision_note: str | None
    is_escalated: bool


class UpcomingStageOut(EAHBaseModel):
    """Wraps ``app.services.request_service.UpcomingStage``."""

    model_config = ConfigDict(from_attributes=True, extra="forbid", frozen=True)

    stage_order: int
    stage_name: str


class WorkflowProgressOut(EAHBaseModel):
    """Wraps ``app.services.request_service.WorkflowProgress``."""

    model_config = ConfigDict(from_attributes=True, extra="forbid", frozen=True)

    stages: list[WorkflowStageDetailOut]
    upcoming_stages: list[UpcomingStageOut]
    current_stage_order: int
    total_stages: int
