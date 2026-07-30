"""Domain-layer exception hierarchy for app.models.

These exceptions are distinct from ``app.database.exceptions``: the
database package's exceptions describe *persistence* failures (a missing
row, a violated database constraint, a lost optimistic-locking race). The
exceptions here describe *domain-level semantic validation* failures —
cases where a payload is individually well-typed but violates a
cross-field or structural rule specified in the architecture documents
(for example, a workflow definition whose stage ``order`` values are not
a contiguous sequence, per WEDD Section 13.1).

A note on how these interact with Pydantic v2's validation machinery:
Pydantic v2 only catches and wraps ``ValueError``, ``TypeError``, and
``AssertionError`` raised inside a validator function into its own
``pydantic.ValidationError``. Any other exception type raised inside a
validator — including every exception defined in this module — propagates
directly, unwrapped, to the caller. The custom validators throughout
``app.models`` deliberately raise these exception types (rather than a
plain ``ValueError``) specifically so that calling code can catch a
precise, meaningful exception type (e.g. ``InvalidWorkflowDefinitionError``)
rather than a generic ``pydantic.ValidationError`` it would need to
inspect further to understand.
"""

from __future__ import annotations


class DomainError(Exception):
    """Base class for every exception raised by the app.models package.

    Attributes:
        message: A human-readable description of the validation failure.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return f"{self.__class__.__name__}(message={self.message!r})"


class InvalidWorkflowDefinitionError(DomainError):
    """Raised when a workflow definition document fails structural
    validation as a whole.

    Corresponds to the structural checks specified in WEDD Section 13.1:
    a non-empty ``stages`` array, and stage ``order`` values that form a
    unique, contiguous sequence starting at 1.
    """


class InvalidStageConfigurationError(DomainError):
    """Raised when a single stage definition entry is internally
    inconsistent — for example, an ``assignment_strategy`` of
    ``specific_user`` with no ``assigned_user_id`` provided, per WEDD
    Section 7.2 and Section 13.3.
    """


class EmptyUpdatePayloadError(DomainError):
    """Raised when a partial-update (PATCH-style) model is constructed
    with no field explicitly set.

    Corresponds to API-ADD Section 22's rule that a request body
    containing no updatable field is a validation failure
    (``422 VALIDATION_ERROR``), evaluated here at the Domain Layer before
    any Application Service or repository is ever involved.
    """


class InvalidDecisionError(DomainError):
    """Raised when an approval-decision payload violates a rule intrinsic
    to the decision itself.

    Currently applies to the rejection-specific business rule in WEDD
    Section 6.6 (a rejection must always carry a non-empty
    ``decision_note``), enforced here as a field constraint rather than a
    custom validator — this exception type is retained for any future
    decision-shape rule that requires explicit validator logic beyond a
    simple field constraint.
    """
