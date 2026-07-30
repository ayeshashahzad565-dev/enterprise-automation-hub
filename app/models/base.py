"""Shared base classes, mixins, and reusable field types for the Domain Layer.

Per the Architecture Design Document (ADD Section 3.3), the Domain Layer
consists of Pydantic v2 models with zero dependencies on any other layer
(no Streamlit, no Supabase, no APScheduler) — this module is the
foundation every model in ``app.models`` is built on, and it depends on
nothing beyond Pydantic and the Python standard library.

This module centralizes:

- ``EAHBaseModel``: the base Pydantic configuration every domain model
  inherits, enforcing strict validation (no unrecognized fields, no
  implicit type-coercion surprises) and immutability (a validated model
  instance is a value object, never mutated in place).
- Field mixins (``IdentifiedModel``, ``TimestampedModel``,
  ``UpdatableTimestampModel``, ``VersionedModel``, ``SoftDeletableModel``)
  capturing column groups repeated across several tables in the Database
  Schema Design Document, so no concrete model redeclares them.
- ``PartialUpdateModel``: the base for every PATCH-style input model,
  providing a uniform way to determine which fields the caller actually
  supplied, matching the partial-merge-patch semantics fixed in API-ADD
  Section 3.6.
- Reusable, ``Annotated``-based field type aliases (``UTCDatetime``, and
  the string-length constraints the API-ADD documents explicitly) so
  that a validation rule stated once in the architecture documents is
  expressed exactly once in code.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer


def _serialize_utc_datetime(value: datetime) -> str:
    """Serialize a datetime to an ISO-8601 string in UTC with a 'Z' suffix.

    Matches the timestamp convention fixed throughout the API Design
    Document (API-ADD Section 8): ISO-8601, UTC, explicit offset. A naive
    (timezone-unaware) datetime is treated as already being in UTC rather
    than silently misinterpreted as local time.

    Args:
        value: The datetime to serialize.

    Returns:
        An ISO-8601 string such as ``"2026-07-08T14:32:00Z"``.
    """
    aware_value = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return aware_value.astimezone(UTC).isoformat().replace("+00:00", "Z")


#: A datetime field type that always serializes to the API-ADD's
#: ISO-8601/UTC/'Z'-suffixed convention, defined once here so every model
#: in this package uses it identically rather than each declaring its own
#: serializer.
UTCDatetime = Annotated[
    datetime,
    PlainSerializer(_serialize_utc_datetime, return_type=str, when_used="json"),
]

#: Field-length constraints matching the exact bounds documented in
#: API-ADD Section 22 (Validation Rules) and Section 19 (Endpoint
#: Specifications). Defined once here and reused by every model that
#: declares one of these fields, so a bound stated once in the
#: architecture is enforced in exactly one place in code.
RequestTitle = Annotated[str, Field(min_length=1, max_length=200)]
RequestDescription = Annotated[str, Field(max_length=5000)]
CommentBody = Annotated[str, Field(min_length=1, max_length=5000)]
DecisionNote = Annotated[str, Field(min_length=1, max_length=1000)]


class EAHBaseModel(BaseModel):
    """The base Pydantic v2 configuration shared by every model in app.models.

    Configuration choices and their rationale:

    - ``extra="forbid"``: An unrecognized field is always a validation
      error, never silently ignored. This is what makes API-ADD's
      ``IMMUTABLE_FIELD`` rule (Section 3.6) — rejecting a PATCH payload
      that includes a field such as ``status``, which the model does not
      declare as mutable — a property of the model definition itself,
      rather than logic a caller must remember to implement separately.
    - ``frozen=True``: Every model instance is an immutable value object
      once constructed, consistent with the ADD's description of the
      Domain Layer as pure data plus validation, never a stateful entity
      that mutates in place. A "changed" record is always represented as
      a newly constructed instance — exactly how the Repository Layer
      already returns fresh instances from every write operation.
    - ``str_strip_whitespace=True``: Leading/trailing whitespace on
      string input is stripped before length validation is applied, so a
      title of all-whitespace characters correctly fails a
      ``min_length=1`` check rather than passing on a technicality.
    - ``validate_default=True``: Default values are validated the same as
      any explicitly supplied value, so a default is never a silent
      escape hatch from this model's own validation rules.
    """

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
        validate_default=True,
    )


class IdentifiedModel(EAHBaseModel):
    """Mixin for models representing a persisted row with a UUID primary key.

    Attributes:
        id: The row's primary key, matching the corresponding table's
            ``id`` column exactly (DSD Section 16's naming convention).
    """

    id: UUID


class TimestampedModel(EAHBaseModel):
    """Mixin for models representing a row with only a creation timestamp.

    Attributes:
        created_at: The row's creation timestamp.
    """

    created_at: UTCDatetime


class UpdatableTimestampModel(TimestampedModel):
    """Mixin for models representing a row with both creation and
    last-modification timestamps.

    Among the tables this package models, only ``profiles`` and
    ``requests`` (DSD Sections 3.1 and 3.3) carry both timestamps;
    ``workflow_definitions``, ``workflow_stages``, ``notifications``, and
    ``audit_logs`` carry only ``created_at`` and use ``TimestampedModel``
    directly instead.

    Attributes:
        updated_at: The row's last modification timestamp.
    """

    updated_at: UTCDatetime


class VersionedModel(EAHBaseModel):
    """Mixin for models representing a row under optimistic-locking control.

    Attributes:
        version: The row's current optimistic-locking version (DSD
            Section 3.9). Always ``>= 1``, matching the database's
            ``version > 0`` check constraint (DSD Section 4.1).
    """

    version: int = Field(ge=1)


class SoftDeletableModel(EAHBaseModel):
    """Mixin for models representing a row that supports soft deletion.

    Among the tables this package models, only ``requests`` (DSD Section
    3.10) supports soft deletion.

    Attributes:
        deleted_at: The soft-deletion timestamp, or ``None`` if the row
            is active.
        deleted_by: The user who performed the soft deletion, or ``None``
            if the row is active.
    """

    deleted_at: UTCDatetime | None = None
    deleted_by: UUID | None = None

    @property
    def is_deleted(self) -> bool:
        """Whether this row has been soft-deleted."""
        return self.deleted_at is not None


class PartialUpdateModel(EAHBaseModel):
    """Base class for every PATCH-style input model.

    Realizes the partial-merge-patch semantics fixed in API-ADD Section
    3.6: a field's *absence* from the payload means "leave unchanged," and
    only fields the caller actually supplied should ever be considered
    for update. Pydantic v2 already tracks exactly this distinction via
    ``model_fields_set`` (the set of field names explicitly provided at
    construction time, as opposed to filled in from a default) — this
    class exposes that tracking through two purpose-named methods so that
    concrete update models, and the Application Layer code that consumes
    them, never need to touch ``model_fields_set`` directly.
    """

    def has_updates(self) -> bool:
        """Return whether the caller supplied at least one field to update.

        Returns:
            ``True`` if one or more fields were explicitly provided at
            construction time; ``False`` if the model was constructed
            with no fields set at all (an empty patch).
        """
        return len(self.model_fields_set) > 0

    def update_fields(self) -> dict[str, Any]:
        """Return only the fields the caller explicitly supplied.

        Unlike ``model_dump()``, which includes every declared field's
        current value (including untouched defaults), this returns
        exactly the subset ``model_fields_set`` identifies as explicitly
        provided — including a field explicitly set to ``None`` (an
        intentional "clear this field" instruction, per API-ADD Section
        3.4), while omitting any field the caller never mentioned at all.

        Returns:
            A dict of field name to value, restricted to explicitly
            supplied fields.
        """
        return self.model_dump(include=self.model_fields_set, exclude_none=False)
