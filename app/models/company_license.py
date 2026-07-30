"""Domain model for the ``company_licenses`` table.

Per the Platform Administration module's "lightweight, informational"
scope decision: a license records a tenant's plan tier, seat limit, and
expiry for a platform admin's own reference. Nothing else in this
codebase reads or enforces these values — no invitation is blocked by
``seat_limit``, no login is blocked by an expired ``expires_at``. Should
real enforcement ever be wanted, this is the single source of truth it
would read from.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import model_validator

from app.models.base import EAHBaseModel, PartialUpdateModel, UTCDatetime
from app.models.exceptions import EmptyUpdatePayloadError

__all__ = ["CompanyLicense", "CompanyLicenseUpdate"]


class CompanyLicense(EAHBaseModel):
    """A company's license/plan information, plus computed, informational fields.

    Attributes:
        company_id: The licensed company.
        plan_tier: A free-text plan identifier (e.g. ``"free"``,
            ``"pro"``, ``"enterprise"``) — deliberately not a fixed enum,
            since there is no billing system to define the canonical set
            of tiers yet.
        seat_limit: The number of user seats this license permits, or
            ``None`` for unlimited.
        expires_at: When this license expires, or ``None`` for no expiry.
        notes: Free-text platform-admin notes about this license.
        seats_used: The company's actual current user count — computed at
            read time, for the UI to compare against ``seat_limit``.
        is_expired: Whether ``expires_at`` has already passed — computed
            at read time, for the UI to badge. Never checked anywhere
            else.
        updated_at: When this license was last changed.
    """

    company_id: UUID
    plan_tier: str
    seat_limit: int | None = None
    expires_at: UTCDatetime | None = None
    notes: str | None = None
    seats_used: int
    is_expired: bool
    updated_at: UTCDatetime


class CompanyLicenseUpdate(PartialUpdateModel):
    """Input model for ``PATCH /api/v1/platform/companies/{id}/license``.

    Attributes:
        plan_tier: The new plan identifier, if changing.
        seat_limit: The new seat limit, if changing.
        expires_at: The new expiry, if changing.
        notes: The new notes, if changing.
    """

    plan_tier: str | None = None
    seat_limit: int | None = None
    expires_at: UTCDatetime | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def _require_at_least_one_field(self) -> CompanyLicenseUpdate:
        """Reject a patch payload that sets no field at all.

        Raises:
            EmptyUpdatePayloadError: If no field was explicitly provided.
        """
        if not self.has_updates():
            raise EmptyUpdatePayloadError(
                "CompanyLicenseUpdate requires at least one field to update."
            )
        return self
