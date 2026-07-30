"""Domain models for the ``companies`` table.

Per the multi-tenancy conversion, a company is the tenant boundary every
other table's ``company_id`` ultimately references. Company management
itself is platform-admin-only (``app.auth.authorization.authorize_platform_admin``),
distinct from every ordinary ``UserRole.ADMIN``-gated resource in this
codebase.
"""

from __future__ import annotations

from pydantic import Field

from app.models.base import (
    EAHBaseModel,
    IdentifiedModel,
    SoftDeletableModel,
    UpdatableTimestampModel,
    VersionedModel,
)

__all__ = ["Company", "CompanyCreate"]


class Company(IdentifiedModel, UpdatableTimestampModel, VersionedModel, SoftDeletableModel):
    """A fully validated, persisted representation of a ``companies`` row.

    Attributes:
        name: The company's display name.
        slug: A unique, URL-safe identifier — reserved for a future
            subdomain-routing feature, not used for anything yet.
        is_active: Whether this company may still be used. Per the
            Platform Administration module, deactivating (suspending) a
            company is enforced at authentication
            (``app.auth.supabase_verifier.SupabaseTokenVerifier``) — every
            user in the company is rejected on their next request, not
            just at their next login. Deactivating never deletes data.
        contact_email: The tenant's primary contact address, if recorded.
        notes: Free-text platform-admin notes about this tenant, if any.
    """

    name: str = Field(min_length=1, max_length=200)
    slug: str = Field(min_length=1)
    is_active: bool
    contact_email: str | None = None
    notes: str | None = None


class CompanyCreate(EAHBaseModel):
    """Input model for creating a new company.

    Attributes:
        name: The company's display name. ``slug`` is derived from this
            by the service, never accepted as caller input.
    """

    name: str = Field(min_length=1, max_length=200)
