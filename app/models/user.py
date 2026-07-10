"""Domain models for the ``profiles`` table.

Per DSD Section 3.1, ``profiles`` extends Supabase's ``auth.users`` with
application-specific identity attributes (role, department, display name)
required for authorization and display. Corresponds to the persistence
layer's ``app.database.repositories.user_repository.ProfileRepository``.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import Field, model_validator

from app.models.base import (
    EAHBaseModel,
    IdentifiedModel,
    PartialUpdateModel,
    UpdatableTimestampModel,
    VersionedModel,
)
from app.models.enums import UserRole
from app.models.exceptions import EmptyUpdatePayloadError

__all__ = ["Profile", "ProfileCreate", "ProfileUpdate"]


class Profile(IdentifiedModel, UpdatableTimestampModel, VersionedModel):
    """A fully validated, persisted representation of a ``profiles`` row.

    Mirrors DSD Section 3.1's column list exactly and corresponds
    directly to ``app.database.repositories.user_repository.ProfileRecord``,
    with the addition of the validation rules this Domain Layer model
    enforces that the persistence-level record does not (per the ADD's
    layering: the Repository Layer maps rows into Domain Layer models —
    this class is the target of that mapping, performed by the
    Application Layer).

    Attributes:
        full_name: The user's display name. Must be non-empty after
            whitespace stripping.
        role: The user's RBAC role (API-ADD Section 6.1).
        department: The user's organizational department, if set.
    """

    full_name: str = Field(min_length=1)
    role: UserRole
    department: str | None = None


class ProfileCreate(EAHBaseModel):
    """Input model for creating a new profile.

    In normal production operation a ``profiles`` row is created
    automatically by a Supabase trigger the first time a user
    authenticates (DSD Section 3.1's business rule); this model exists
    for the Application Layer / test-fixture code paths that create one
    directly (TSD Section 11).

    Attributes:
        id: The profile's id, matching an existing ``auth.users.id``.
        full_name: The initial display name.
        role: The initial RBAC role. Defaults to ``UserRole.EMPLOYEE``,
            matching the column's database default (DSD Section 3.1).
        department: The initial department, if known.
    """

    id: UUID
    full_name: str = Field(min_length=1)
    role: UserRole = UserRole.EMPLOYEE
    department: str | None = None


class ProfileUpdate(PartialUpdateModel):
    """Input model for ``PATCH /api/v1/profiles/{id}`` (API-ADD Section
    19.2.2).

    Which fields a given caller is authorized to change (a self-update
    may only set ``full_name``; only an administrator may set ``role`` or
    ``department``) is an authorization concern enforced by the
    Application Layer and Row-Level Security (API-ADD Section 6.3), not
    by this model — this model validates only the *shape* of a candidate
    update, not who is allowed to submit it.

    Attributes:
        full_name: The new display name, if changing.
        role: The new RBAC role, if changing.
        department: The new department, if changing.
    """

    full_name: str | None = Field(default=None, min_length=1)
    role: UserRole | None = None
    department: str | None = None

    @model_validator(mode="after")
    def _require_at_least_one_field(self) -> "ProfileUpdate":
        """Reject a patch payload that sets no field at all.

        Raises:
            EmptyUpdatePayloadError: If no field was explicitly provided.
        """
        if not self.has_updates():
            raise EmptyUpdatePayloadError(
                "ProfileUpdate requires at least one field to update."
            )
        return self