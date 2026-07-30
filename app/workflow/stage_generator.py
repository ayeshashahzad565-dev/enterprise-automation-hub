"""Incremental workflow stage generation.

Per WEDD Section 2.1, ``StageGenerator`` is one of the Workflow Engine's
four internal collaborators, responsible for materializing the *next*
``StageDefinition`` in sequence — either the first stage at request
creation, or the successor stage after a prior stage's approval — never
the whole chain up front (WEDD Section 4.6's incremental-generation
design). This component performs no I/O: it operates entirely on an
already-resolved ``WorkflowDefinition`` and plain integer arguments
describing the request's current stage-generation progress, which the
calling Application Service is responsible for having already determined
from persisted data.

Conditional branching (a stage whose existence depends on an earlier
stage's outcome, producing a ``StageStatus.SKIPPED`` result) is not
implemented by this component in the current baseline — WEDD Section
20.2 identifies it as a forward-looking hook, and no ``StageDefinition``
field in ``app.models.workflow`` currently carries a condition to
evaluate. Every stage this component produces is destined to become
``StageStatus.PENDING`` when materialized.
"""

from __future__ import annotations

import logging

from app.models import StageDefinition, WorkflowDefinition
from app.utils.validators import validate_positive_integer
from app.workflow.constants import STAGE_ORDER_INCREMENT
from app.workflow.exceptions import NonSequentialStageOrderError, StageNotFoundInDefinitionError

__all__ = ["StageGenerator"]

logger = logging.getLogger(__name__)


class StageGenerator:
    """Generates the shape of the next workflow stage in sequence.

    This class holds no state of its own; every method is a pure
    function of its arguments.
    """

    def first_stage(self, definition: WorkflowDefinition) -> StageDefinition:
        """Return the first stage's configuration for a workflow definition.

        Used at request creation (WEDD Section 5.4). Because
        ``WorkflowDefinitionDocument`` already guarantees, at construction
        time, that ``stages`` orders form a contiguous sequence starting
        at 1 (``app.models.workflow.WorkflowDefinitionDocument``'s own
        validator), the first stage returned here is always the one with
        ``order == 1`` — no additional validation is required here.

        Args:
            definition: The resolved, active workflow definition.

        Returns:
            The ``StageDefinition`` for the first stage (``order == 1``).
        """
        first = definition.definition.ordered_stages()[0]
        logger.debug(
            "Generated first stage '%s' (order=%d) for definition %s",
            first.name,
            first.order,
            definition.id,
            extra={"definition_id": str(definition.id), "stage_order": first.order},
        )
        return first

    def next_stage(
        self,
        definition: WorkflowDefinition,
        *,
        current_order: int,
        highest_existing_order: int,
    ) -> StageDefinition | None:
        """Return the next stage's configuration, if one exists.

        Used after a stage approval to determine whether the workflow
        advances to a further stage or has reached its final stage (WEDD
        Sections 6.4-6.5).

        Args:
            definition: The workflow definition governing the request
                (the specific version pinned to it — never a freshly
                re-resolved one, per WEDD Section 9.6's running-workflow
                isolation guarantee, which this component trusts its
                caller to uphold).
            current_order: The ``stage_order`` of the stage that was just
                decided.
            highest_existing_order: The highest ``stage_order`` already
                materialized for this request. In normal operation this
                equals ``current_order``, since the just-decided stage is
                expected to be the most recently created one; this is
                passed explicitly, rather than assumed equal, so this
                method can perform the defensive check below.

        Returns:
            The ``StageDefinition`` for the next stage (``order ==
            current_order + STAGE_ORDER_INCREMENT``), or ``None`` if
            ``current_order`` is the definition's final stage — the
            trigger for workflow completion (WEDD Section 6.5).

        Raises:
            NonSequentialStageOrderError: If ``highest_existing_order``
                does not equal ``current_order``, indicating the caller's
                view of the request's stage history is inconsistent with
                the decision being processed (WEDD Section 13.2's
                defensive check).
        """
        validate_positive_integer(current_order, field_name="current_order")
        validate_positive_integer(highest_existing_order, field_name="highest_existing_order")

        if highest_existing_order != current_order:
            raise NonSequentialStageOrderError(highest_existing_order, current_order)

        next_order = current_order + STAGE_ORDER_INCREMENT
        for stage in definition.definition.ordered_stages():
            if stage.order == next_order:
                logger.debug(
                    "Generated next stage '%s' (order=%d) for definition %s",
                    stage.name,
                    stage.order,
                    definition.id,
                    extra={"definition_id": str(definition.id), "stage_order": stage.order},
                )
                return stage

        logger.info(
            "No further stage exists after order=%d for definition %s; workflow complete.",
            current_order,
            definition.id,
            extra={"definition_id": str(definition.id)},
        )
        return None

    def is_final_stage(self, definition: WorkflowDefinition, stage_order: int) -> bool:
        """Return whether a given stage order is the definition's final stage.

        Args:
            definition: The workflow definition.
            stage_order: The stage order to check.

        Returns:
            ``True`` if ``stage_order`` equals the highest ``order``
            value present in ``definition``'s stages.

        Raises:
            StageNotFoundInDefinitionError: If ``stage_order`` does not
                correspond to any stage in ``definition``.
        """
        orders = [stage.order for stage in definition.definition.stages]
        if stage_order not in orders:
            raise StageNotFoundInDefinitionError(stage_order)
        return stage_order == max(orders)
