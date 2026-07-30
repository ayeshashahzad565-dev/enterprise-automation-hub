"""HTTP body schema for ``PATCH /api/v1/requests/{id}``.

``app.models.request.RequestUpdate`` already validates ``title``/
``description``/``department`` shape, but ``expected_version`` is not a
domain-model field (it is a plain keyword argument
``RequestService.update_request`` takes for optimistic-concurrency
checking) — this wraps the same three optional fields plus that required
field, exactly what the HTTP body carries.
"""

from __future__ import annotations

from pydantic import Field

from app.models.base import EAHBaseModel, RequestDescription, RequestTitle

__all__ = ["RequestPatchBody"]


class RequestPatchBody(EAHBaseModel):
    """Request body for ``PATCH /api/v1/requests/{id}``.

    Attributes:
        title: The new title, if changing.
        description: The new description, if changing.
        department: The new department, if changing.
        expected_version: The caller's last-known ``Request.version``,
            for optimistic-concurrency checking.
    """

    title: RequestTitle | None = None
    description: RequestDescription | None = None
    department: str | None = None
    expected_version: int = Field(ge=1)
