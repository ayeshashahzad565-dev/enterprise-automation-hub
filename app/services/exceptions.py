"""Centralized exception hierarchy for the Application Service Layer.

Mirroring the pattern already established in every finalized package
(``app.database.exceptions``, ``app.models.exceptions``,
``app.config.exceptions``, ``app.utils.exceptions``,
``app.auth.exceptions``, ``app.workflow.exceptions``), every exception a
service in ``app.services`` raises directly to its own caller is defined
here, exactly once.

This module additionally provides a small set of ``translate_*``
functions that convert an exception raised by a lower layer (the
Repository Layer, the Workflow Engine, the Auth Layer, or Pydantic model
construction) into the appropriate member of this hierarchy. Centralizing
that translation here — rather than repeating an equivalent
``try``/``except`` block in every service method — is what keeps
``request_service.py``, ``approval_service.py``, and
``workflow_definition_service.py`` free of duplicated exception-handling
logic: each service method catches the narrow, lower-layer exception it
expects and calls the matching ``translate_*`` function, which is the
single place that decides, e.g., "a database ``RecordNotFoundError``
becomes a service-layer ``NotFoundError``."
"""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError as PydanticValidationError

from app.auth.exceptions import (
    AuthenticationError as _AuthAuthenticationError,
)
from app.auth.exceptions import (
    AuthorizationError as _AuthAuthorizationError,
)
from app.database.exceptions import (
    ConcurrentUpdateError as _DbConcurrentUpdateError,
)
from app.database.exceptions import (
    ConstraintViolationError as _DbConstraintViolationError,
)
from app.database.exceptions import (
    DatabaseConnectionError as _DbConnectionError,
)
from app.database.exceptions import (
    DatabaseError as _DbError,
)
from app.database.exceptions import (
    InvalidQueryError as _DbInvalidQueryError,
)
from app.database.exceptions import (
    RecordNotFoundError as _DbRecordNotFoundError,
)
from app.models.exceptions import DomainError as _ModelsDomainError
from app.workflow.exceptions import (
    AssignmentResolutionError as _EngineAssignmentResolutionError,
)
from app.workflow.exceptions import (
    DefinitionAlreadyActiveError as _EngineDefinitionAlreadyActiveError,
)
from app.workflow.exceptions import (
    InvalidStateTransitionError as _EngineInvalidStateTransitionError,
)
from app.workflow.exceptions import (
    NoActiveDefinitionError as _EngineNoActiveDefinitionError,
)
from app.workflow.exceptions import (
    WorkflowError as _EngineWorkflowError,
)

__all__ = [
    "EAHError",
    "ValidationError",
    "NotFoundError",
    "PermissionDeniedError",
    "ConcurrencyError",
    "WorkflowError",
    "AssignmentError",
    "ConfigurationError",
    "translate_database_error",
    "translate_workflow_error",
    "translate_auth_error",
    "translate_model_construction_error",
]


class EAHError(Exception):
    """Base class for every exception raised by the Application Service Layer.

    Attributes:
        message: A human-readable description of the failure.
        details: A structured, machine-inspectable payload describing the
            failure, useful for logging and for tests asserting on
            failure cause without parsing the exception's string
            representation.
    """

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details: dict[str, Any] = details or {}

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return f"{self.__class__.__name__}(message={self.message!r}, details={self.details!r})"


class ValidationError(EAHError):
    """Raised when a request payload fails shape or structural validation
    before any persistence is attempted."""


class NotFoundError(EAHError):
    """Raised when a requested resource does not exist, or exists but is
    outside the caller's visibility.

    Attributes:
        resource: The kind of resource that was not found (e.g.
            ``"request"``, ``"workflow_stage"``).
        identifier: The identifier that was searched for.
    """

    def __init__(self, resource: str, identifier: Any) -> None:
        super().__init__(
            f"{resource} not found: {identifier}",
            details={"resource": resource, "identifier": str(identifier)},
        )
        self.resource = resource
        self.identifier = identifier


class PermissionDeniedError(EAHError):
    """Raised when an authenticated caller is not permitted to perform a
    requested action, whether due to role, ownership, or session state."""


class ConcurrencyError(EAHError):
    """Raised when an optimistic-locking conflict, or an equivalent
    state-conflict (e.g. a competing workflow-definition activation),
    prevents an operation from completing."""


class WorkflowError(EAHError):
    """Raised when the Workflow Engine rejects an operation for a
    workflow-logic reason not covered by ``ValidationError``,
    ``ConcurrencyError``, or ``AssignmentError``."""


class AssignmentError(EAHError):
    """Raised when a workflow stage's assignment cannot be resolved to a
    known, valid assignee."""


class ConfigurationError(EAHError):
    """Raised when a dependency (most commonly the database connection)
    is unavailable or misconfigured, independent of the specific request
    being served."""


def translate_database_error(exc: _DbError) -> EAHError:
    """Translate an ``app.database.exceptions`` failure into an ``EAHError``.

    Args:
        exc: The exception raised by a repository call.

    Returns:
        The corresponding ``EAHError`` subclass instance. Callers are
        expected to ``raise translate_database_error(exc) from exc``.
    """
    if isinstance(exc, _DbRecordNotFoundError):
        return NotFoundError(exc.table, exc.identifier)
    if isinstance(exc, _DbConcurrentUpdateError):
        return ConcurrencyError(exc.message, details=exc.details)
    if isinstance(exc, _DbConstraintViolationError):
        return ValidationError(exc.message, details=exc.details)
    if isinstance(exc, _DbInvalidQueryError):
        return ValidationError(exc.message, details=exc.details)
    if isinstance(exc, _DbConnectionError):
        return ConfigurationError(exc.message, details=exc.details)
    return EAHError(str(exc))


def translate_workflow_error(exc: _EngineWorkflowError) -> EAHError:
    """Translate an ``app.workflow.exceptions`` failure into an ``EAHError``.

    Args:
        exc: The exception raised by a Workflow Engine call.

    Returns:
        The corresponding ``EAHError`` subclass instance.
    """
    if isinstance(exc, _EngineNoActiveDefinitionError):
        return ValidationError(exc.message, details={"request_type": exc.request_type})
    if isinstance(exc, _EngineDefinitionAlreadyActiveError):
        return ConcurrencyError(exc.message, details={"definition_id": exc.definition_id})
    if isinstance(exc, _EngineAssignmentResolutionError):
        return AssignmentError(exc.message)
    if isinstance(exc, _EngineInvalidStateTransitionError):
        return WorkflowError(
            exc.message,
            details={
                "entity": exc.entity,
                "current_state": exc.current_state,
                "attempted_state": exc.attempted_state,
            },
        )
    return WorkflowError(exc.message if hasattr(exc, "message") else str(exc))


def translate_auth_error(exc: Exception) -> EAHError:
    """Translate an ``app.auth.exceptions`` failure into an ``EAHError``.

    Args:
        exc: The exception raised by an authentication or authorization
            call.

    Returns:
        A ``PermissionDeniedError`` for every authentication or
        authorization failure — the Application Service Layer does not
        distinguish "not authenticated" from "not authorized" in its own
        exception surface, since both ultimately mean "this action will
        not be performed for this caller"; the underlying distinction
        remains inspectable via ``exc.__cause__`` for any caller that
        needs it.
    """
    message = getattr(exc, "message", str(exc))
    if isinstance(exc, (_AuthAuthenticationError, _AuthAuthorizationError)):
        return PermissionDeniedError(message)
    return PermissionDeniedError(message)


def translate_model_construction_error(
    exc: PydanticValidationError | _ModelsDomainError, *, model_name: str
) -> ValidationError:
    """Translate a Domain Layer model construction failure into a ``ValidationError``.

    Args:
        exc: Either a Pydantic ``ValidationError`` (raised for field-shape
            failures) or an ``app.models.exceptions.DomainError`` subclass
            (raised by a custom validator for a structural rule, per that
            module's documented behavior that such exceptions propagate
            unwrapped).
        model_name: The name of the model class construction was
            attempted against, for error attribution.

    Returns:
        A ``ValidationError`` describing the failure.
    """
    if isinstance(exc, PydanticValidationError):
        return ValidationError(
            f"'{model_name}' failed validation.", details={"errors": exc.errors()}
        )
    return ValidationError(f"'{model_name}' failed validation: {exc.message}")