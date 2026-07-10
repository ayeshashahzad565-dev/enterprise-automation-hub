"""Workflow definition resolution.

Per WEDD Section 2.1, ``DefinitionResolver`` is one of the Workflow
Engine's four internal collaborators, responsible for determining which
``WorkflowDefinition`` version governs a given request type at the
moment a request is submitted. As WEDD Section 2.4 makes explicit, this
component performs no I/O itself — it operates on a set of candidate
definitions already fetched by the calling Application Service (in
practice, typically a single active-or-none candidate returned by a
future ``WorkflowDefinitionRepository.find_active_for_request_type``
call, but this component accepts a general iterable so it can also
defensively verify the "at most one active" invariant when given a wider
candidate set, such as every version for a request type).
"""

from __future__ import annotations

import logging
from typing import Iterable

from app.models import WorkflowDefinition
from app.workflow.exceptions import MultipleActiveDefinitionsError, NoActiveDefinitionError

__all__ = ["DefinitionResolver"]

logger = logging.getLogger(__name__)


class DefinitionResolver:
    """Resolves the single active ``WorkflowDefinition`` for a request type.

    This class holds no state of its own; every method is a pure
    function of its arguments, making it trivially unit-testable without
    any database or Supabase dependency (TSD Section 3.2).
    """

    def resolve(
        self, request_type: str, candidates: Iterable[WorkflowDefinition]
    ) -> WorkflowDefinition:
        """Select the active workflow definition for a request type.

        Per WEDD Sections 3.3 and 5.3: at most one version per
        ``request_type`` has ``is_active = True`` at any moment, and this
        method resolves exactly that version.

        Args:
            request_type: The request type to resolve a definition for.
            candidates: The candidate ``WorkflowDefinition`` instances to
                consider — expected to already be filtered to this
                ``request_type`` by whatever repository call produced
                them, though this method defensively filters again to
                guard against a caller passing an unfiltered set.

        Returns:
            The single active ``WorkflowDefinition`` for ``request_type``.

        Raises:
            NoActiveDefinitionError: If no candidate is both active and
                matches ``request_type``. This is the domain-level
                trigger for what a future API-binding layer surfaces as
                ``422 INVALID_REQUEST_TYPE`` (WEDD Section 5.3).
            MultipleActiveDefinitionsError: If more than one candidate is
                simultaneously active for ``request_type`` — a defensive
                check against a violation of the invariant DSD Section
                3.2's activation transaction is meant to guarantee; this
                should never occur in correctly operating production
                code.
        """
        active_matches = [
            candidate
            for candidate in candidates
            if candidate.request_type == request_type and candidate.is_active
        ]

        if not active_matches:
            logger.info(
                "No active workflow definition found for request_type=%s",
                request_type,
                extra={"request_type": request_type},
            )
            raise NoActiveDefinitionError(request_type)

        if len(active_matches) > 1:
            ids = tuple(str(definition.id) for definition in active_matches)
            logger.error(
                "Multiple active workflow definitions found for request_type=%s: %s",
                request_type,
                ids,
                extra={"request_type": request_type, "active_definition_ids": ids},
            )
            raise MultipleActiveDefinitionsError(request_type, ids)

        resolved = active_matches[0]
        logger.debug(
            "Resolved workflow definition %s (version %d) for request_type=%s",
            resolved.id,
            resolved.version,
            request_type,
            extra={"request_type": request_type, "definition_id": str(resolved.id)},
        )
        return resolved