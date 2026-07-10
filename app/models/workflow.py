"""Domain models for the ``workflow_definitions`` and ``workflow_stages`` tables.

Per DSD Sections 3.2 and 3.4, and WEDD Sections 3 and 9, this module
models both the versioned, JSON-encoded workflow definition and the
runtime stage instances generated from it. Corresponds to the
persistence layer's ``app.database.repositories.workflow_repository``
module, which defines the two matching repository classes
(``WorkflowDefinitionRepository`` and ``WorkflowStageRepository``).
"""

from __future__ import annotations

from uuid import UUID

from pydantic import Field, model_validator

from app.models.base import (
    DecisionNote,
    EAHBaseModel,
    IdentifiedModel,
    TimestampedModel,
    UTCDatetime,
    VersionedModel,
)
from app.models.enums import AssignmentStrategy, StageStatus, UserRole
from app.models.exceptions import (
    InvalidStageConfigurationError,
    InvalidWorkflowDefinitionError,
)

__all__ = [
    "StageDefinition",
    "WorkflowDefinitionDocument",
    "WorkflowDefinition",
    "WorkflowDefinitionCreate",
    "WorkflowStage",
]


class StageDefinition(EAHBaseModel):
    """A single entry within a workflow definition's ``stages`` array.

    Mirrors the stage configuration fields specified in DSD Section 5.2
    and WEDD Section 3.5. Structural validation here corresponds to WEDD
    Section 13.3's assignment-validation rules: a ``specific_user``
    strategy must name a user; a ``department_queue`` strategy must name
    both a department and an eligible role. ``requester_manager``
    requires no additional static field, since it is resolved against the
    requester's own profile at runtime (WEDD Section 7.4), not from a
    value present in the definition itself.

    Attributes:
        order: The stage's 1-indexed position within the approval chain.
            Must be strictly positive.
        name: The human-readable stage label.
        assignment_strategy: Which of the three strategies in WEDD
            Section 7 resolves this stage's assignee.
        assigned_role: The role eligible to act on this stage, required
            for ``department_queue`` and optional otherwise.
        department: The department scope for a ``department_queue``
            stage; required for that strategy, otherwise ``None``.
        assigned_user_id: The specific user for a ``specific_user`` stage;
            required for that strategy, otherwise ``None``.
        escalation_hours: The duration after which this stage becomes
            eligible for escalation (WEDD Section 8.2). Must be strictly
            positive.
    """

    order: int = Field(gt=0)
    name: str = Field(min_length=1)
    assignment_strategy: AssignmentStrategy
    assigned_role: UserRole | None = None
    department: str | None = None
    assigned_user_id: UUID | None = None
    escalation_hours: float = Field(gt=0)

    @model_validator(mode="after")
    def _validate_strategy_specific_fields(self) -> "StageDefinition":
        """Enforce that each assignment strategy carries its required fields.

        Raises:
            InvalidStageConfigurationError: If a required, strategy-
                specific field is missing.
        """
        if self.assignment_strategy is AssignmentStrategy.SPECIFIC_USER:
            if self.assigned_user_id is None:
                raise InvalidStageConfigurationError(
                    f"Stage '{self.name}' uses assignment_strategy="
                    "'specific_user' but does not provide assigned_user_id."
                )
        elif self.assignment_strategy is AssignmentStrategy.DEPARTMENT_QUEUE:
            if not self.department:
                raise InvalidStageConfigurationError(
                    f"Stage '{self.name}' uses assignment_strategy="
                    "'department_queue' but does not provide department."
                )
            if self.assigned_role is None:
                raise InvalidStageConfigurationError(
                    f"Stage '{self.name}' uses assignment_strategy="
                    "'department_queue' but does not provide assigned_role."
                )
        # AssignmentStrategy.REQUESTER_MANAGER requires no additional
        # static field; it is resolved against the requester's own
        # profile at runtime (WEDD Section 7.4).
        return self


class WorkflowDefinitionDocument(EAHBaseModel):
    """The structured JSON document stored in
    ``workflow_definitions.definition`` (DSD Section 5.2).

    Attributes:
        stages: The ordered list of stage configurations. Must be
            non-empty.
    """

    stages: list[StageDefinition] = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_stage_ordering(self) -> "WorkflowDefinitionDocument":
        """Enforce that stage ``order`` values are unique and contiguous.

        Corresponds to WEDD Section 13.1's structural validation: the
        set of ``order`` values across all stages must form exactly the
        sequence ``1, 2, ..., N`` for ``N`` stages, with no gaps and no
        duplicates.

        Raises:
            InvalidWorkflowDefinitionError: If ``order`` values are
                duplicated or do not form a contiguous sequence starting
                at 1.
        """
        orders = [stage.order for stage in self.stages]
        if len(orders) != len(set(orders)):
            raise InvalidWorkflowDefinitionError(
                "Workflow definition contains duplicate stage 'order' "
                "values; each stage must have a unique order."
            )
        expected = list(range(1, len(self.stages) + 1))
        if sorted(orders) != expected:
            raise InvalidWorkflowDefinitionError(
                "Workflow definition stage 'order' values must form a "
                f"contiguous sequence starting at 1 (expected {expected}, "
                f"got {sorted(orders)})."
            )
        return self

    def ordered_stages(self) -> list[StageDefinition]:
        """Return this document's stages sorted by ``order`` ascending.

        Returns:
            The stage list, sorted ascending by ``order``. Since
            ``_validate_stage_ordering`` already guarantees a contiguous,
            unique sequence, this is equivalent to indexing by position,
            but expressed explicitly rather than relying on input
            ordering matching declared ``order`` values.
        """
        return sorted(self.stages, key=lambda stage: stage.order)


class WorkflowDefinition(IdentifiedModel, TimestampedModel):
    """A fully validated, persisted representation of a
    ``workflow_definitions`` row.

    Mirrors DSD Section 3.2's column list exactly and corresponds
    directly to
    ``app.database.repositories.workflow_repository.WorkflowDefinitionRecord``.

    Attributes:
        request_type: The request type this definition governs.
        version: The business-level, monotonically increasing version
            number for this ``request_type`` (distinct from
            ``row_version``, DSD Section 3.2).
        definition: The validated stage configuration document.
        is_active: Whether this version currently governs new requests of
            this type.
        created_by: The administrator who authored this version.
        row_version: The optimistic-locking column for this table (DSD
            Section 3.9).
    """

    request_type: str = Field(min_length=1)
    version: int = Field(ge=1)
    definition: WorkflowDefinitionDocument
    is_active: bool
    created_by: UUID
    row_version: int = Field(ge=1)


class WorkflowDefinitionCreate(EAHBaseModel):
    """Input model for ``POST /api/v1/workflow-definitions`` (API-ADD
    Section 19.9.1).

    Attributes:
        request_type: The request type this definition will govern.
        version: The business version number for this request type.
            Uniqueness of ``(request_type, version)`` is enforced by the
            database (DSD Section 3.2), not by this model.
        definition: The stage configuration document.
        created_by: The administrator authoring this version.
    """

    request_type: str = Field(min_length=1)
    version: int = Field(ge=1)
    definition: WorkflowDefinitionDocument
    created_by: UUID


class WorkflowStage(IdentifiedModel, TimestampedModel):
    """A fully validated, persisted representation of a
    ``workflow_stages`` row.

    Mirrors DSD Section 3.4's column list exactly and corresponds
    directly to
    ``app.database.repositories.workflow_repository.WorkflowStageRecord``.

    Attributes:
        request_id: The request this stage belongs to.
        stage_order: 1-indexed position within the approval chain.
        stage_name: Human-readable stage label.
        assigned_role: The role eligible to act on this stage, if not
            assigned to a specific user.
        assigned_to: The specific user assigned to this stage, if
            resolved.
        status: The stage's current decision status (see WEDD Section
            10.3 for the full state transition table).
        decided_by: The user who made the decision, if any.
        decided_at: The decision timestamp, if any.
        decision_note: An optional note provided at decision time (up to
            1,000 characters).
    """

    request_id: UUID
    stage_order: int = Field(gt=0)
    stage_name: str = Field(min_length=1)
    assigned_role: UserRole | None = None
    assigned_to: UUID | None = None
    status: StageStatus
    decided_by: UUID | None = None
    decided_at: UTCDatetime | None = None
    decision_note: DecisionNote | None = None
    version: int = Field(ge=1)