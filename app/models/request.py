"""Domain models for the ``requests`` table.

Per DSD Section 3.3, ``requests`` is the central entity of the system — a
single business request submitted by an employee and tracked through to
completion. Corresponds to the persistence layer's
``app.database.repositories.request_repository.RequestRepository``.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import Field, model_validator

from app.models.base import (
    EAHBaseModel,
    IdentifiedModel,
    PartialUpdateModel,
    RequestDescription,
    RequestTitle,
    SoftDeletableModel,
    UpdatableTimestampModel,
    UTCDatetime,
    VersionedModel,
)
from app.models.enums import RequestStatus
from app.models.exceptions import EmptyUpdatePayloadError

__all__ = ["Request", "RequestCreate", "RequestUpdate"]


class Request(
    IdentifiedModel,
    UpdatableTimestampModel,
    VersionedModel,
    SoftDeletableModel,
):
    """A fully validated, persisted representation of a ``requests`` row.

    Mirrors DSD Section 3.3's column list exactly and corresponds
    directly to ``app.database.repositories.request_repository.RequestRecord``.

    Attributes:
        requester_id: The submitting user's profile id.
        workflow_definition_id: The specific workflow definition version
            governing this request (WEDD Sections 3.2 and 9.6 — this
            reference is permanent for the life of the request).
        request_type: The request type identifier.
        title: Short human-readable summary (1-200 characters, API-ADD
            Section 22).
        description: Full request details, if provided (up to 5,000
            characters).
        department: Department the request was raised under, if provided.
        status: Current lifecycle status (see API-ADD Section 20.1 /
            WEDD Section 10.1 for the full state transition table).
        current_stage_id: The stage currently awaiting action, if any.
        completed_at: Timestamp of final approval, rejection, or
            completion.
    """

    requester_id: UUID
    workflow_definition_id: UUID
    request_type: str = Field(min_length=1)
    title: RequestTitle
    description: RequestDescription | None = None
    department: str | None = None
    status: RequestStatus
    current_stage_id: UUID | None = None
    completed_at: UTCDatetime | None = None


class RequestCreate(EAHBaseModel):
    """Input model for ``POST /api/v1/requests`` (API-ADD Section 19.3.1).

    Attributes:
        request_type: The request type identifier. Must match an active
            ``WorkflowDefinition``, verified by the Application Layer, not
            by this model — this model validates only the field's shape.
        title: Short human-readable summary (1-200 characters).
        description: Full request details, if provided (up to 5,000
            characters).
        department: Department the request is being raised under, if
            provided.
    """

    request_type: str = Field(min_length=1)
    title: RequestTitle
    description: RequestDescription | None = None
    department: str | None = None


class RequestUpdate(PartialUpdateModel):
    """Input model for ``PATCH /api/v1/requests/{id}`` (API-ADD Section
    19.3.4).

    This model declares only the three fields the API-ADD documents as
    editable (``title``, ``description``, ``department``). Because
    ``EAHBaseModel`` forbids unrecognized fields, a caller attempting to
    include ``status`` or ``current_stage_id`` in a patch payload fails
    validation immediately — realizing API-ADD Section 3.6's
    ``IMMUTABLE_FIELD`` rule as a property of this model's declared
    fields, rather than logic that must separately check for and reject
    those field names.

    Whether the request is still in a state where an edit is permitted
    (``status == pending``) is an Application Layer guard clause (API-ADD
    Section 19.3.4), not something this model itself can determine.

    Attributes:
        title: The new title, if changing.
        description: The new description, if changing.
        department: The new department, if changing.
    """

    title: RequestTitle | None = None
    description: RequestDescription | None = None
    department: str | None = None

    @model_validator(mode="after")
    def _require_at_least_one_field(self) -> "RequestUpdate":
        """Reject a patch payload that sets no field at all.

        Raises:
            EmptyUpdatePayloadError: If no field was explicitly provided.
        """
        if not self.has_updates():
            raise EmptyUpdatePayloadError(
                "RequestUpdate requires at least one field to update."
            )
        return self