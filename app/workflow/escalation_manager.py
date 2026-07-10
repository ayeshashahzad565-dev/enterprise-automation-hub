"""Escalation threshold computation and escalation reassignment planning.

Per WEDD Section 2.1, this module implements the component WEDD's
narrative names ``EscalationPlanner`` (Section 2.1) — named
``EscalationManager`` here to match this package's file-naming
convention, with no change in responsibility or behavior from what the
Workflow Engine Design Document specifies. Per WEDD Section 8.2, this
component computes, from a stage's ``created_at`` and its definition's
``escalation_hours``, the threshold after which a stage becomes eligible
for escalation — it does not itself schedule a timer or perform any I/O;
the actual periodic check is the Scheduler's Escalation Check job's
responsibility (outside this package's scope), which calls this
component's pure functions against durable data it has already fetched.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.models.enums import UserRole
from app.utils.datetime_utils import add_hours, is_past, utc_now
from app.utils.validators import validate_positive_number
from app.workflow.constants import ESCALATION_FALLBACK_ROLE

__all__ = ["EscalationPlan", "EscalationManager"]

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class EscalationPlan:
    """The outcome of planning an escalation reassignment for a stage.

    Attributes:
        previous_assigned_to: The stage's specific assignee prior to
            escalation, if any.
        previous_assigned_role: The stage's eligible role prior to
            escalation, if any.
        new_assigned_to: The stage's specific assignee after escalation
            (always ``None`` in the current baseline, per WEDD Section
            8.4's routing to a role-eligible pool rather than a specific
            escalation contact).
        new_assigned_role: The role the stage is reassigned to (always
            ``ESCALATION_FALLBACK_ROLE`` in the current baseline).
    """

    previous_assigned_to: UUID | None
    previous_assigned_role: UserRole | None
    new_assigned_to: UUID | None
    new_assigned_role: UserRole


class EscalationManager:
    """Computes escalation eligibility and plans escalation reassignments.

    This class holds no state of its own; every method is a pure
    function of its arguments, which is what allows WEDD Section 8.6's
    "recovery after restart" property to hold — escalation eligibility is
    always recomputed fresh from durable inputs, never from any state
    this class might otherwise have retained in memory.
    """

    def compute_threshold(self, stage_created_at: datetime, escalation_hours: float) -> datetime:
        """Compute the timestamp after which a stage becomes escalation-eligible.

        Per WEDD Section 8.2, this threshold is not persisted as a
        separate column; it is computed on demand from
        ``stage.created_at`` plus the definition's ``escalation_hours``
        each time it is needed.

        Args:
            stage_created_at: The stage's ``created_at`` timestamp.
            escalation_hours: The definition's configured escalation
                duration for this stage, in hours. Must be positive.

        Returns:
            The computed threshold timestamp.

        Raises:
            InputValidationError: If ``escalation_hours`` is not
                positive (a defensive check; ``StageDefinition``'s own
                field constraint already enforces this at construction
                time).
        """
        validate_positive_number(escalation_hours, field_name="escalation_hours")
        return add_hours(stage_created_at, escalation_hours)

    def is_eligible(
        self,
        stage_created_at: datetime,
        escalation_hours: float,
        *,
        now: datetime | None = None,
    ) -> bool:
        """Return whether a stage is currently eligible for escalation.

        Args:
            stage_created_at: The stage's ``created_at`` timestamp.
            escalation_hours: The definition's configured escalation
                duration for this stage, in hours.
            now: The point in time to evaluate eligibility against.
                Defaults to the current instant.

        Returns:
            ``True`` if the computed threshold has already passed
            relative to ``now``.
        """
        threshold = self.compute_threshold(stage_created_at, escalation_hours)
        reference = now if now is not None else utc_now()
        eligible = is_past(threshold, reference=reference)
        logger.debug(
            "Escalation eligibility check: created_at=%s, escalation_hours=%s, "
            "threshold=%s, now=%s, eligible=%s",
            stage_created_at,
            escalation_hours,
            threshold,
            reference,
            eligible,
        )
        return eligible

    def plan_escalation(
        self,
        *,
        current_assigned_to: UUID | None,
        current_assigned_role: UserRole | None,
    ) -> EscalationPlan:
        """Plan an escalation reassignment for an eligible, still-pending stage.

        Per WEDD Section 8.4, escalation reassigns the existing pending
        stage — it does not create a new stage — routing it to the same
        fallback role used by ``AssignmentResolver``'s own fallback path
        (WEDD Section 7.5), for a single, consistent "where things go
        when normal resolution or timely decision fails" destination.

        Args:
            current_assigned_to: The stage's current specific assignee,
                if any, prior to escalation.
            current_assigned_role: The stage's current eligible role, if
                any, prior to escalation.

        Returns:
            An ``EscalationPlan`` describing both the prior and new
            assignment, so the calling Application Service can record
            the prior assignee in the corresponding ``audit_logs``
            entry's ``metadata`` (WEDD Section 8.4: "including the prior
            assignee for traceability").
        """
        logger.info(
            "Planning escalation: previous_assigned_to=%s, previous_assigned_role=%s, "
            "new_assigned_role=%s",
            current_assigned_to,
            current_assigned_role.value if current_assigned_role else None,
            ESCALATION_FALLBACK_ROLE.value,
        )
        return EscalationPlan(
            previous_assigned_to=current_assigned_to,
            previous_assigned_role=current_assigned_role,
            new_assigned_to=None,
            new_assigned_role=ESCALATION_FALLBACK_ROLE,
        )