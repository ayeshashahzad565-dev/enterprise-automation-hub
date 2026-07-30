"""HTTP schemas for the ``workflow-definitions`` resource.

``app.models.workflow.StageDefinition``/``WorkflowDefinitionDocument``/
``WorkflowDefinition`` are already Pydantic models — the ``Out`` schemas
below are thin ``from_attributes=True`` wrappers around them (the same
"reuse, don't re-derive" technique this API layer uses everywhere a
domain model needs a stable, ``extra="forbid"`` HTTP-facing shape). The
``In`` schemas are the request bodies for ``POST``/``PATCH``, validated
independently before being handed to ``WorkflowDefinitionService`` as the
plain ``dict`` it expects (the service itself re-validates via
``WorkflowDefinitionDocument.model_validate`` — this is intentional
defense in depth, not duplicated business logic, since the service never
trusts a caller-supplied dict regardless of what schema fronted it).
"""

from __future__ import annotations

from uuid import UUID

from pydantic import ConfigDict, Field

from app.models.base import EAHBaseModel, UTCDatetime
from app.models.enums import AssignmentStrategy, UserRole

__all__ = [
    "StageDefinitionIn",
    "StageDefinitionOut",
    "WorkflowDefinitionDocumentIn",
    "WorkflowDefinitionDocumentOut",
    "WorkflowDefinitionOut",
    "CreateWorkflowDefinitionBody",
    "UpdateWorkflowDefinitionBody",
]


class StageDefinitionIn(EAHBaseModel):
    """One stage in a ``POST``/``PATCH`` request body. Mirrors ``StageDefinition`` field-for-field."""

    order: int = Field(gt=0)
    name: str = Field(min_length=1)
    assignment_strategy: AssignmentStrategy
    assigned_role: UserRole | None = None
    department: str | None = None
    assigned_user_id: UUID | None = None
    escalation_hours: float = Field(gt=0)


class WorkflowDefinitionDocumentIn(EAHBaseModel):
    """The ``{"stages": [...]}`` body shape for ``POST``/``PATCH``."""

    stages: list[StageDefinitionIn] = Field(min_length=1)


class StageDefinitionOut(EAHBaseModel):
    """Wraps ``app.models.workflow.StageDefinition``."""

    model_config = ConfigDict(from_attributes=True, extra="forbid", frozen=True)

    order: int
    name: str
    assignment_strategy: AssignmentStrategy
    assigned_role: UserRole | None
    department: str | None
    assigned_user_id: UUID | None
    escalation_hours: float


class WorkflowDefinitionDocumentOut(EAHBaseModel):
    """Wraps ``app.models.workflow.WorkflowDefinitionDocument``."""

    model_config = ConfigDict(from_attributes=True, extra="forbid", frozen=True)

    stages: list[StageDefinitionOut]


class WorkflowDefinitionOut(EAHBaseModel):
    """Wraps ``app.models.workflow.WorkflowDefinition``."""

    model_config = ConfigDict(from_attributes=True, extra="forbid", frozen=True)

    id: UUID
    request_type: str
    version: int
    definition: WorkflowDefinitionDocumentOut
    is_active: bool
    created_by: UUID | None
    row_version: int
    created_at: UTCDatetime


class CreateWorkflowDefinitionBody(EAHBaseModel):
    """Body for ``POST /workflow-definitions``. Mirrors ``WorkflowDefinitionService.create_definition``'s real kwargs (``request_type``, ``definition``) — deliberately not ``WorkflowDefinitionCreate``, whose ``version``/``created_by`` fields the service computes itself and never accepts from a caller."""

    request_type: str = Field(min_length=1)
    definition: WorkflowDefinitionDocumentIn


class UpdateWorkflowDefinitionBody(EAHBaseModel):
    """Body for ``PATCH /workflow-definitions/{id}``. Mirrors ``WorkflowDefinitionService.update_draft``'s real kwarg (``definition``)."""

    definition: WorkflowDefinitionDocumentIn
