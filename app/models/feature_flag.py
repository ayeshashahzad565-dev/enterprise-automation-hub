"""Domain models for the ``feature_flags`` table.

Per the Platform Administration module's "lightweight, informational"
scope decision: a feature flag is global (not per-tenant), platform-admin
managed, and consumed by nothing else in this codebase yet — it exists so
platform admins have one authoritative place to define and toggle flags
ahead of any future enforcement point, not as a fully-gated system today.
"""

from __future__ import annotations

from pydantic import Field, model_validator

from app.models.base import EAHBaseModel, PartialUpdateModel, UTCDatetime
from app.models.exceptions import EmptyUpdatePayloadError

__all__ = ["FeatureFlag", "FeatureFlagCreate", "FeatureFlagUpdate"]


class FeatureFlag(EAHBaseModel):
    """A fully validated, persisted representation of a ``feature_flags`` row.

    Attributes:
        key: The flag's stable identifier (primary key), e.g.
            ``"new_dashboard_layout"``.
        description: A human-readable description of what this flag
            controls.
        enabled: Whether this flag is currently on.
        updated_at: When this flag was last changed.
    """

    key: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1)
    enabled: bool
    updated_at: UTCDatetime


class FeatureFlagCreate(EAHBaseModel):
    """Input model for defining a new feature flag.

    Attributes:
        key: The flag's stable identifier.
        description: A human-readable description.
        enabled: The flag's initial state. Defaults to ``False`` — a new
            flag never starts on by default.
    """

    key: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1)
    enabled: bool = False


class FeatureFlagUpdate(PartialUpdateModel):
    """Input model for ``PATCH /api/v1/platform/feature-flags/{key}``.

    Attributes:
        description: The new description, if changing.
        enabled: The new on/off state, if changing.
    """

    description: str | None = Field(default=None, min_length=1)
    enabled: bool | None = None

    @model_validator(mode="after")
    def _require_at_least_one_field(self) -> FeatureFlagUpdate:
        """Reject a patch payload that sets no field at all.

        Raises:
            EmptyUpdatePayloadError: If no field was explicitly provided.
        """
        if not self.has_updates():
            raise EmptyUpdatePayloadError("FeatureFlagUpdate requires at least one field to update.")
        return self
