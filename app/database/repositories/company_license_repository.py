"""Repository for the ``company_licenses`` table.

One row per licensed company. Persistence only — the computed
``seats_used``/``is_expired`` fields live on the domain model
(``app.models.company_license.CompanyLicense``), not here, since they
require cross-referencing the company's actual user count, which is the
Application Layer's job (``CompanyService``), not this repository's.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from app.database.client import DatabaseClient
from app.database.repositories.base_repository import BaseRepository, parse_datetime, parse_uuid

logger = logging.getLogger(__name__)

__all__ = ["CompanyLicenseRecord", "CompanyLicenseRepository"]


@dataclass(frozen=True, slots=True)
class CompanyLicenseRecord:
    """An immutable, persistence-level representation of one
    ``company_licenses`` row.

    Attributes:
        company_id: The licensed company (primary key).
        plan_tier: A free-text plan identifier.
        seat_limit: The number of user seats this license permits, or
            ``None`` for unlimited.
        expires_at: When this license expires, or ``None`` for no expiry.
        notes: Free-text platform-admin notes.
        updated_at: Last modification timestamp.
    """

    company_id: UUID
    plan_tier: str
    seat_limit: int | None
    expires_at: datetime | None
    notes: str | None
    updated_at: datetime


def _map_license_row(row: dict[str, Any]) -> CompanyLicenseRecord:
    """Map a raw Supabase row dict into a ``CompanyLicenseRecord``."""
    return CompanyLicenseRecord(
        company_id=parse_uuid(row["company_id"]),  # type: ignore[arg-type]
        plan_tier=row["plan_tier"],
        seat_limit=row.get("seat_limit"),
        expires_at=parse_datetime(row.get("expires_at")),
        notes=row.get("notes"),
        updated_at=parse_datetime(row["updated_at"]),  # type: ignore[arg-type]
    )


class CompanyLicenseRepository(BaseRepository[CompanyLicenseRecord]):
    """Persistence operations for the ``company_licenses`` table."""

    table_name = "company_licenses"

    def __init__(self, client: DatabaseClient, *, always_use_injected_client: bool) -> None:
        super().__init__(client, always_use_injected_client=always_use_injected_client)

    def get_for_company(self, company_id: UUID) -> CompanyLicenseRecord | None:
        """Fetch a company's license, tolerating absence.

        Args:
            company_id: The company's id.

        Returns:
            The matching ``CompanyLicenseRecord``, or ``None`` if this
            company has no license configured yet.
        """
        response = self._execute(
            self._query().select("*").eq("company_id", str(company_id)).limit(1),
            operation="get_for_company",
        )
        rows = self._rows(response)
        return _map_license_row(rows[0]) if rows else None

    def upsert(
        self,
        company_id: UUID,
        *,
        plan_tier: str,
        seat_limit: int | None,
        expires_at: datetime | None,
        notes: str | None,
        updated_by: UUID | None,
    ) -> CompanyLicenseRecord:
        """Create or replace a company's license.

        A single ``INSERT ... ON CONFLICT (company_id) DO UPDATE`` round
        trip, matching the primitive introduced for
        ``NotificationPreferenceRepository.upsert``.

        Args:
            company_id: The company's id.
            plan_tier: The plan identifier.
            seat_limit: The seat limit, or ``None`` for unlimited.
            expires_at: The expiry timestamp, or ``None`` for no expiry.
            notes: Free-text notes, if any.
            updated_by: The platform admin performing this write.

        Returns:
            The resulting ``CompanyLicenseRecord``.
        """
        values: dict[str, Any] = {
            "company_id": str(company_id),
            "plan_tier": plan_tier,
            "seat_limit": seat_limit,
            "expires_at": expires_at.isoformat() if expires_at else None,
            "notes": notes,
            "updated_by": str(updated_by) if updated_by else None,
        }
        response = self._execute(
            self._query().upsert(values, on_conflict="company_id"),
            operation="upsert",
        )
        row = self._single_row(response, identifier=company_id)
        return _map_license_row(row)
