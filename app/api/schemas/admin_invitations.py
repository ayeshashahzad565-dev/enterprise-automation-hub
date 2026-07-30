"""HTTP schemas for the ``admin-invitations`` resource.

``app.models.invitation.Invitation`` is already a Pydantic model —
``InvitationOut`` below is a thin ``from_attributes=True`` wrapper around
it, the same "reuse, don't re-derive" technique this API layer uses
everywhere a domain model needs a stable, ``extra="forbid"`` HTTP-facing
shape (see ``app.api.schemas.workflow_definitions.WorkflowDefinitionOut``).

``InvitationOut`` deliberately omits ``version``: per this milestone's
Security requirements, the invitation API never exposes an optimistic-
locking implementation detail to a caller — unlike ``UserOut``/
``WorkflowDefinitionOut``, no invitation endpoint requires (or accepts) a
caller-supplied ``expected_version``, since ``InvitationService.resend_invitation``/
``revoke_invitation`` re-read the current row themselves rather than
taking one as an argument. ``token_hash`` is already absent from
``Invitation`` itself (see that model's own docstring), so there is
nothing further to strip for that field.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import ConfigDict, Field, field_validator

from app.models.base import EAHBaseModel, UTCDatetime
from app.models.enums import EffectiveInvitationStatus, UserRole

__all__ = ["InvitationOut", "InvitationCreateBody"]


def _validate_email_shape(value: str) -> str:
    """Reject a value that is not even superficially shaped like an email address.

    Mirrors ``app.models.invitation._validate_email_shape``'s identical,
    lightweight, dependency-free check (no third-party email-validation
    library is introduced here either) — duplicated at this boundary so a
    malformed email is rejected as a ``422`` at the HTTP layer itself
    ("before reaching the service layer"), rather than only inside
    ``InvitationService.create_invitation``'s own re-validation, which
    still applies regardless as defense in depth.

    Args:
        value: The candidate email address.

    Returns:
        ``value``, unchanged, if it passes the shape check.

    Raises:
        ValueError: If ``value`` does not contain exactly one ``@`` with a
            non-empty local part and a domain part containing a ``.``.
    """
    local, separator, domain = value.partition("@")
    if not separator or not local or "." not in domain or domain.startswith(".") or not domain:
        raise ValueError("must be a valid email address, e.g. 'name@example.com'.")
    return value


class InvitationOut(EAHBaseModel):
    """Wraps ``app.models.invitation.Invitation``."""

    model_config = ConfigDict(from_attributes=True, extra="forbid", frozen=True)

    id: UUID
    email: str
    full_name: str
    role: UserRole
    department: str | None
    effective_status: EffectiveInvitationStatus
    invited_by: UUID | None
    expires_at: UTCDatetime
    accepted_at: UTCDatetime | None
    revoked_at: UTCDatetime | None
    accepted_profile_id: UUID | None
    resend_count: int
    created_at: UTCDatetime
    updated_at: UTCDatetime


#: Mirrors ``app.models.invitation``'s identical bounds — duplicated here
#: (rather than imported) since this module deliberately does not import
#: from the Domain Layer's private validation helpers; see
#: ``_validate_email_shape``'s own docstring for the same rationale.
_EMAIL_MAX_LENGTH = 254
_FULL_NAME_MAX_LENGTH = 200
_DEPARTMENT_MAX_LENGTH = 200


class InvitationCreateBody(EAHBaseModel):
    """Body for ``POST /admin/invitations``. Mirrors
    ``InvitationService.create_invitation``'s real kwargs exactly."""

    email: str = Field(min_length=3, max_length=_EMAIL_MAX_LENGTH)
    full_name: str = Field(min_length=1, max_length=_FULL_NAME_MAX_LENGTH)
    role: UserRole = UserRole.EMPLOYEE
    department: str | None = Field(default=None, max_length=_DEPARTMENT_MAX_LENGTH)
    company_id: UUID | None = Field(
        default=None,
        description=(
            "Invite into a company other than the caller's own. Accepted "
            "only from a platform admin (InvitationService.create_invitation "
            "rejects it otherwise) — the sole use is inviting a brand-new "
            "company's first admin, who does not exist yet to invite "
            "anyone themselves."
        ),
    )

    @field_validator("email")
    @classmethod
    def _validate_email(cls, value: str) -> str:
        return _validate_email_shape(value)
