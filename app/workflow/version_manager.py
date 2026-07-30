"""Workflow definition versioning business rules.

Per WEDD Section 9, this module implements the pure business rules
governing workflow definition creation, editing, and activation — the
numbering convention for a new version, and the invariants that must hold
before an edit or activation is permitted. The atomic database
transaction that actually performs an activation (deactivating the prior
active version and activating the target, per DSD Section 11 and WEDD
Section 9.2) is a Repository Layer concern (already implemented in
``app.database.repositories.workflow_repository.WorkflowDefinitionRepository.activate_definition``)
— this module validates that such an attempt *should* be allowed to
proceed, without performing the transaction itself.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

from app.models import WorkflowDefinition
from app.workflow.exceptions import (
    DefinitionAlreadyActiveError,
    DefinitionEditNotAllowedError,
    MismatchedRequestTypeError,
)

__all__ = ["VersionManager"]

logger = logging.getLogger(__name__)


class VersionManager:
    """Enforces workflow definition versioning business rules.

    This class holds no state of its own; every method is a pure
    function of its arguments.
    """

    def next_version_number(self, existing_versions: Sequence[int]) -> int:
        """Compute the next version number for a request type.

        Per DSD Section 3.2, versions are monotonically increasing
        integers, unique per ``request_type``.

        Args:
            existing_versions: Every version number already used for this
                request type (may be empty, for the first version ever
                created).

        Returns:
            ``max(existing_versions) + 1``, or ``1`` if
            ``existing_versions`` is empty.
        """
        return max(existing_versions, default=0) + 1

    def validate_edit_allowed(self, definition: WorkflowDefinition) -> None:
        """Enforce that a definition may be edited in place.

        Per API-ADD Section 19.9.2 and WEDD Section 9.1, only a
        definition that has not yet been activated may be edited; an
        active definition must be replaced by a new version instead.

        Args:
            definition: The definition an edit is being attempted against.

        Raises:
            DefinitionEditNotAllowedError: If ``definition.is_active`` is
                ``True``.
        """
        if definition.is_active:
            logger.warning(
                "Rejected edit attempt on active workflow definition %s",
                definition.id,
                extra={"definition_id": str(definition.id)},
            )
            raise DefinitionEditNotAllowedError(str(definition.id))

    def validate_activation(
        self,
        candidate: WorkflowDefinition,
        *,
        currently_active: WorkflowDefinition | None,
    ) -> None:
        """Enforce that an activation attempt is legal before it proceeds.

        Per WEDD Section 9.2, activation is an atomic transaction that
        deactivates whichever version is currently active for the same
        ``request_type`` (if any) and activates the candidate. This
        method validates the preconditions for that transaction being
        meaningful to attempt at all.

        Args:
            candidate: The definition being activated.
            currently_active: The definition currently active for this
                request type, if any (``None`` if no version is currently
                active).

        Raises:
            DefinitionAlreadyActiveError: If ``candidate`` is already the
                active version (either ``candidate.is_active`` is already
                ``True``, or ``currently_active`` is the same definition
                as ``candidate``) — the domain-level trigger for a future
                API-binding layer's ``409 DUPLICATE_ACTIVATION`` (WEDD
                Section 9.2).
            MismatchedRequestTypeError: If ``currently_active`` is
                provided and its ``request_type`` does not match
                ``candidate``'s — a defensive check against a programming
                error, since these should always agree by construction.
        """
        if candidate.is_active:
            raise DefinitionAlreadyActiveError(str(candidate.id))

        if currently_active is not None:
            if currently_active.request_type != candidate.request_type:
                raise MismatchedRequestTypeError(
                    candidate.request_type, currently_active.request_type
                )
            if currently_active.id == candidate.id:
                raise DefinitionAlreadyActiveError(str(candidate.id))

        logger.info(
            "Activation validated for workflow definition %s (version %d, request_type=%s)",
            candidate.id,
            candidate.version,
            candidate.request_type,
            extra={"definition_id": str(candidate.id), "request_type": candidate.request_type},
        )
