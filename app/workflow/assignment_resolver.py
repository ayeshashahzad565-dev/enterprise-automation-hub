"""Workflow stage assignment resolution.

Per WEDD Section 2.1, ``AssignmentResolver`` is one of the Workflow
Engine's four internal collaborators, responsible for turning a stage's
``assignment_strategy`` configuration into a concrete ``assigned_to``
and/or ``assigned_role`` value. This component performs no I/O: for the
``requester_manager`` strategy, which depends on data outside the
workflow definition itself (WEDD Section 7.4), the calling Application
Service is responsible for having already fetched the requester's own
profile and a candidate pool of department-eligible approvers, and passes
both in as plain arguments.

Per WEDD Section 7.6, this component's ``requester_manager`` resolution
is a documented, scoped simplification: the current ``profiles`` schema
(DSD Section 3.1) has no explicit manager-hierarchy column, so this
strategy resolves via the requester's ``department`` rather than a true
reporting line, treating "the department's designated approver" as a
practical stand-in for "the requester's manager."
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from app.models import Profile, StageDefinition
from app.models.enums import AssignmentStrategy, UserRole
from app.workflow.constants import ESCALATION_FALLBACK_ROLE, FALLBACK_REASON_NO_DEPARTMENT_APPROVER

__all__ = ["AssignmentResult", "AssignmentResolver"]

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class AssignmentResult:
    """The outcome of resolving a single stage's assignment.

    Attributes:
        assigned_to: The specific user resolved for this stage, or
            ``None`` if the stage is assigned to a role-eligible pool
            rather than a specific individual.
        assigned_role: The role eligible to act on this stage, or
            ``None`` if a specific user was resolved instead.
        used_fallback: Whether this result is the fallback outcome (WEDD
            Section 7.5) rather than a normal resolution.
        fallback_reason: A human-readable explanation of why the
            fallback was applied, populated only when ``used_fallback``
            is ``True``. The calling Application Service is expected to
            record this in the corresponding ``audit_logs`` entry's
            ``metadata`` field (WEDD Section 7.5, Section 14.1), under
            the key named by
            ``app.workflow.constants.ASSIGNMENT_FALLBACK_METADATA_KEY``.
    """

    assigned_to: UUID | None
    assigned_role: UserRole | None
    used_fallback: bool
    fallback_reason: str | None = None


class AssignmentResolver:
    """Resolves a workflow stage's concrete assignment from its configured strategy.

    This class holds no state of its own; every method is a pure
    function of its arguments.
    """

    def resolve(
        self,
        stage: StageDefinition,
        *,
        requester: Profile,
        department_approvers: Sequence[Profile] = (),
    ) -> AssignmentResult:
        """Resolve a stage's concrete assignment.

        Args:
            stage: The stage configuration to resolve assignment for.
            requester: The profile of the user who submitted the request
                this stage belongs to. Consulted only by the
                ``requester_manager`` strategy.
            department_approvers: The pool of ``UserRole.APPROVER``
                profiles already fetched by the caller as candidates for
                the ``requester_manager`` strategy's department-based
                resolution (WEDD Section 7.4). Ignored by the other two
                strategies.

        Returns:
            An ``AssignmentResult`` describing the resolved assignment.
        """
        if stage.assignment_strategy is AssignmentStrategy.SPECIFIC_USER:
            return self._resolve_specific_user(stage)
        if stage.assignment_strategy is AssignmentStrategy.DEPARTMENT_QUEUE:
            return self._resolve_department_queue(stage)
        return self._resolve_requester_manager(requester, department_approvers)

    def _resolve_specific_user(self, stage: StageDefinition) -> AssignmentResult:
        """Resolve a ``specific_user`` stage.

        Per WEDD Section 7.2, the definition already names an exact
        ``assigned_user_id``, validated for existence at
        definition-authoring time (never re-validated here, since the
        definition is immutable once activated, WEDD Section 3.2) —
        resolution is therefore a pure copy.

        Args:
            stage: The stage configuration.

        Returns:
            An ``AssignmentResult`` with ``assigned_to`` set and
            ``assigned_role`` ``None``.
        """
        logger.debug(
            "Resolved specific_user assignment for stage '%s': user=%s",
            stage.name,
            stage.assigned_user_id,
        )
        return AssignmentResult(
            assigned_to=stage.assigned_user_id, assigned_role=None, used_fallback=False
        )

    def _resolve_department_queue(self, stage: StageDefinition) -> AssignmentResult:
        """Resolve a ``department_queue`` stage.

        Per WEDD Section 7.3, this is a "queue" semantic: no specific
        user is assigned; the stage is left visible to the eligible role
        pool, and the first eligible approver to act on it decides it
        (with optimistic locking, per WEDD Section 6.10, preventing two
        members of the pool from both successfully deciding it).

        Args:
            stage: The stage configuration. ``assigned_role`` is
                guaranteed non-``None`` here by
                ``app.models.workflow.StageDefinition``'s own validation
                for this strategy.

        Returns:
            An ``AssignmentResult`` with ``assigned_to`` ``None`` and
            ``assigned_role`` set.
        """
        logger.debug(
            "Resolved department_queue assignment for stage '%s': role=%s, department=%s",
            stage.name,
            stage.assigned_role,
            stage.department,
        )
        return AssignmentResult(
            assigned_to=None, assigned_role=stage.assigned_role, used_fallback=False
        )

    def _resolve_requester_manager(
        self, requester: Profile, department_approvers: Sequence[Profile]
    ) -> AssignmentResult:
        """Resolve a ``requester_manager`` stage.

        Per WEDD Section 7.4, this strategy names no user in the
        definition itself; it resolves against the requester's own
        ``department``, selecting a deterministic (alphabetically
        first-by-name) candidate from ``department_approvers`` whose
        ``department`` matches the requester's. If no eligible candidate
        is found, this falls back to routing the stage to administrator
        attention (WEDD Section 7.5), rather than failing the request's
        creation.

        Args:
            requester: The requester's profile.
            department_approvers: The candidate pool of approver profiles
                already fetched by the caller.

        Returns:
            An ``AssignmentResult``, either a resolved department
            approver or the administrator fallback.
        """
        eligible = sorted(
            (
                approver
                for approver in department_approvers
                if approver.department == requester.department
            ),
            key=lambda approver: approver.full_name,
        )

        if eligible:
            chosen = eligible[0]
            logger.debug(
                "Resolved requester_manager assignment via department approver %s "
                "for requester department=%s",
                chosen.id,
                requester.department,
            )
            return AssignmentResult(assigned_to=chosen.id, assigned_role=None, used_fallback=False)

        logger.warning(
            "No department-designated approver found for requester department=%s; "
            "falling back to role=%s.",
            requester.department,
            ESCALATION_FALLBACK_ROLE.value,
            extra={"requester_department": requester.department},
        )
        return AssignmentResult(
            assigned_to=None,
            assigned_role=ESCALATION_FALLBACK_ROLE,
            used_fallback=True,
            fallback_reason=FALLBACK_REASON_NO_DEPARTMENT_APPROVER,
        )
