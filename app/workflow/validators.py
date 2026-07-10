"""Workflow-specific validation not already enforced by the Domain Layer.

Per WEDD Sections 13.1 and 13.3, a workflow definition's *structural*
shape (a non-empty, contiguously-ordered ``stages`` array, and each
stage's strategy-specific required fields) is already validated at
construction time by ``app.models.workflow.WorkflowDefinitionDocument``
and ``app.models.workflow.StageDefinition``'s own Pydantic validators —
this module deliberately does not re-implement any of that, since doing
so would duplicate validation logic that already exists and is already
exercised by every ``WorkflowDefinitionDocument`` instance regardless of
where it was constructed.

This module implements only the one class of validation the Domain Layer
*cannot* perform on its own: checks that require information external to
the definition document itself — specifically, confirming that a
``specific_user`` stage's ``assigned_user_id`` resolves to a real,
known profile (WEDD Section 13.3), which requires a set of known profile
ids the calling Application Service has already fetched.
"""

from __future__ import annotations

import logging
from typing import AbstractSet
from uuid import UUID

from app.models import StageDefinition, WorkflowDefinitionDocument
from app.models.enums import AssignmentStrategy
from app.workflow.exceptions import UnknownAssigneeError

__all__ = ["validate_specific_user_assignee", "validate_definition_assignees"]

logger = logging.getLogger(__name__)


def validate_specific_user_assignee(
    stage: StageDefinition, known_profile_ids: AbstractSet[UUID]
) -> None:
    """Validate that a ``specific_user`` stage's assignee is a known profile.

    Per WEDD Sections 7.2 and 13.3, this validation is intended to run
    once, at definition-authoring time — never at stage-generation time,
    since the definition is immutable once activated (WEDD Section 3.2)
    and its assignee references were already validated before it could
    ever be activated.

    Args:
        stage: The stage configuration to validate. If its
            ``assignment_strategy`` is not ``SPECIFIC_USER``, this
            function is a no-op.
        known_profile_ids: The set of profile ids known to exist, already
            fetched by the calling Application Service.

    Raises:
        UnknownAssigneeError: If ``stage.assignment_strategy`` is
            ``SPECIFIC_USER`` and ``stage.assigned_user_id`` is not in
            ``known_profile_ids``.
    """
    if stage.assignment_strategy is not AssignmentStrategy.SPECIFIC_USER:
        return
    # StageDefinition's own validator (app.models.workflow) already
    # guarantees assigned_user_id is set whenever this strategy is used.
    assigned_user_id = stage.assigned_user_id
    assert assigned_user_id is not None  # noqa: S101 - guaranteed by StageDefinition's validator
    if assigned_user_id not in known_profile_ids:
        logger.warning(
            "Unknown assignee %s referenced by stage '%s'",
            assigned_user_id,
            stage.name,
            extra={"assigned_user_id": str(assigned_user_id)},
        )
        raise UnknownAssigneeError(str(assigned_user_id))


def validate_definition_assignees(
    document: WorkflowDefinitionDocument, known_profile_ids: AbstractSet[UUID]
) -> None:
    """Validate every ``specific_user`` stage's assignee across a full definition.

    Args:
        document: The workflow definition document to validate.
        known_profile_ids: The set of profile ids known to exist.

    Raises:
        UnknownAssigneeError: If any stage's ``specific_user`` assignee is
            not in ``known_profile_ids``. Validation stops at the first
            such stage encountered, in ``order``.
    """
    for stage in document.ordered_stages():
        validate_specific_user_assignee(stage, known_profile_ids)