"""The Workflow Engine for the Enterprise Automation Hub.

Per the Workflow Engine Design Document, this package implements the
component responsible for determining, at every point in a request's
life, what approval stage exists, who is responsible for it, what happens
when it is decided, and when the request is finished. It has no
dependency on ``app.database`` and performs no I/O of any kind (WEDD
Section 2.4-2.5): every collaborator in this package is a pure function
of the arguments it is given, with all persistence orchestration left to
a future Application Service layer that injects this package's
``WorkflowEngine`` alongside the already-implemented Repository Layer.

This package contains:

- ``exceptions``: the typed exception hierarchy every workflow-logic
  failure raises.
- ``constants``: fixed values (first stage order, escalation fallback
  role) shared across collaborators.
- ``state_machine``: the request and workflow-stage state transition
  tables and validation functions (WEDD Section 10).
- ``definition_resolver``: resolves the active workflow definition for a
  request type (WEDD Section 5.3).
- ``stage_generator``: generates the next stage's structural shape,
  incrementally (WEDD Sections 4.6, 6.4-6.5).
- ``assignment_resolver``: resolves a stage's concrete assignment from
  its configured strategy (WEDD Section 7).
- ``escalation_manager``: computes escalation eligibility and plans
  escalation reassignments (WEDD Section 8).
- ``version_manager``: enforces workflow definition versioning business
  rules (WEDD Section 9).
- ``validators``: the one class of validation the Domain Layer cannot
  perform on its own — assignee existence, which requires external data
  (WEDD Section 13.3).
- ``engine``: ``WorkflowEngine``, the single composed facade over every
  collaborator above.

This module re-exports the public surface of every submodule so that
calling code can import from ``app.workflow`` directly.
"""

from __future__ import annotations

from app.workflow.assignment_resolver import AssignmentResolver, AssignmentResult
from app.workflow.constants import (
    ASSIGNMENT_FALLBACK_METADATA_KEY,
    ESCALATION_FALLBACK_ROLE,
    FALLBACK_REASON_NO_DEPARTMENT_APPROVER,
    FIRST_STAGE_ORDER,
    STAGE_ORDER_INCREMENT,
)
from app.workflow.definition_resolver import DefinitionResolver
from app.workflow.engine import StagePlan, WorkflowEngine
from app.workflow.escalation_manager import EscalationManager, EscalationPlan
from app.workflow.exceptions import (
    AssignmentResolutionError,
    DefinitionAlreadyActiveError,
    DefinitionEditNotAllowedError,
    DefinitionResolutionError,
    EscalationError,
    InvalidEscalationConfigurationError,
    InvalidStateTransitionError,
    MismatchedRequestTypeError,
    MultipleActiveDefinitionsError,
    NoActiveDefinitionError,
    NonSequentialStageOrderError,
    StageGenerationError,
    StageNotFoundInDefinitionError,
    UnknownAssigneeError,
    VersionManagementError,
    WorkflowError,
)
from app.workflow.stage_generator import StageGenerator
from app.workflow.state_machine import (
    REQUEST_STATUS_TRANSITIONS,
    STAGE_STATUS_TRANSITIONS,
    is_terminal_request_status,
    is_terminal_stage_status,
    is_valid_request_transition,
    is_valid_stage_transition,
    validate_request_transition,
    validate_stage_transition,
)
from app.workflow.validators import validate_definition_assignees, validate_specific_user_assignee
from app.workflow.version_manager import VersionManager

__all__ = [
    # assignment_resolver
    "AssignmentResolver",
    "AssignmentResult",
    # constants
    "ASSIGNMENT_FALLBACK_METADATA_KEY",
    "ESCALATION_FALLBACK_ROLE",
    "FALLBACK_REASON_NO_DEPARTMENT_APPROVER",
    "FIRST_STAGE_ORDER",
    "STAGE_ORDER_INCREMENT",
    # definition_resolver
    "DefinitionResolver",
    # engine
    "StagePlan",
    "WorkflowEngine",
    # escalation_manager
    "EscalationManager",
    "EscalationPlan",
    # exceptions
    "AssignmentResolutionError",
    "DefinitionAlreadyActiveError",
    "DefinitionEditNotAllowedError",
    "DefinitionResolutionError",
    "EscalationError",
    "InvalidEscalationConfigurationError",
    "InvalidStateTransitionError",
    "MismatchedRequestTypeError",
    "MultipleActiveDefinitionsError",
    "NoActiveDefinitionError",
    "NonSequentialStageOrderError",
    "StageGenerationError",
    "StageNotFoundInDefinitionError",
    "UnknownAssigneeError",
    "VersionManagementError",
    "WorkflowError",
    # stage_generator
    "StageGenerator",
    # state_machine
    "REQUEST_STATUS_TRANSITIONS",
    "STAGE_STATUS_TRANSITIONS",
    "is_terminal_request_status",
    "is_terminal_stage_status",
    "is_valid_request_transition",
    "is_valid_stage_transition",
    "validate_request_transition",
    "validate_stage_transition",
    # validators
    "validate_definition_assignees",
    "validate_specific_user_assignee",
    # version_manager
    "VersionManager",
]
