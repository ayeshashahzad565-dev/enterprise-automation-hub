"""Domain models for the ``user_invitations`` table.

Per the Enterprise User Onboarding architecture (Milestone 2),
corresponds to
``app.database.repositories.invitation_repository.InvitationRecord`` —
with two differences reflecting this layer's own responsibilities:
``token_hash`` is never exposed here (a persistence-level implementation
detail, not a domain concern for any caller of ``InvitationService``),
and ``effective_status`` is added, since it is what a caller actually
wants to know about an invitation's lifecycle state (see
``app.models.enums.EffectiveInvitationStatus``'s own docstring) — this
model performs no computation itself (per this package's "zero
dependencies on any other layer" rule); ``effective_status`` is computed
by ``app.services.invitation_service.compute_effective_status`` and
passed in already-resolved at construction time.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import Field, field_validator

from app.models.base import (
    EAHBaseModel,
    IdentifiedModel,
    UpdatableTimestampModel,
    UTCDatetime,
    VersionedModel,
)
from app.models.enums import EffectiveInvitationStatus, UserRole

__all__ = ["Invitation", "InvitationCreate"]

#: Matches RFC 5321's maximum total email-address length. No comparable
#: bound previously existed on this field (an oversight relative to this
#: package's own convention elsewhere — e.g. ``RequestTitle``,
#: ``CommentBody`` in ``app.models.base`` — flagged during the
#: Milestone 1-5 architecture review and closed here).
_EMAIL_MAX_LENGTH = 254
#: Matches ``RequestTitle``'s bound (``app.models.base``) — the closest
#: existing precedent for a short, single-line display string.
_FULL_NAME_MAX_LENGTH = 200
_DEPARTMENT_MAX_LENGTH = 200


def _validate_email_shape(value: str) -> str:
    """Reject a value that is not even superficially shaped like an email
    address.

    This is intentionally a lightweight, dependency-free check (a
    required ``local@domain.tld`` shape) rather than full RFC 5322
    validation — matching this codebase's preference for standard-library-
    only validation (see ``app.auth.password``'s equivalent rationale) over
    adding a third-party email-validation dependency.

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


class Invitation(IdentifiedModel, UpdatableTimestampModel, VersionedModel):
    """A fully validated, persisted representation of a
    ``user_invitations`` row, as returned by ``InvitationService``.

    Attributes:
        email: The invited person's email address.
        full_name: The invited person's display name.
        role: The role the resulting profile will be provisioned with on
            acceptance.
        department: The department the resulting profile will be
            provisioned with, if set.
        effective_status: The invitation's computed lifecycle status —
            see ``app.models.enums.EffectiveInvitationStatus``.
        invited_by: The admin who created this invitation, or ``None`` if
            that profile has since been hard-deleted (see
            ``InvitationRecord.invited_by``'s docstring).
        expires_at: The timestamp after which this invitation may no
            longer be accepted.
        accepted_at: The timestamp the invitation was accepted, if any.
        revoked_at: The timestamp the invitation was revoked, if any.
        accepted_profile_id: The id of the profile created on acceptance,
            if any.
        resend_count: The number of times this invitation has been
            resent.
    """

    email: str = Field(max_length=_EMAIL_MAX_LENGTH)
    full_name: str = Field(min_length=1, max_length=_FULL_NAME_MAX_LENGTH)
    role: UserRole
    department: str | None = Field(default=None, max_length=_DEPARTMENT_MAX_LENGTH)
    effective_status: EffectiveInvitationStatus
    invited_by: UUID | None
    expires_at: UTCDatetime
    accepted_at: UTCDatetime | None = None
    revoked_at: UTCDatetime | None = None
    accepted_profile_id: UUID | None = None
    resend_count: int = Field(ge=0)

    @field_validator("email")
    @classmethod
    def _validate_email(cls, value: str) -> str:
        return _validate_email_shape(value)


class InvitationCreate(EAHBaseModel):
    """Input model for ``InvitationService.create_invitation``.

    Validates only the *shape* of a candidate invitation — who is
    authorized to create one, and whether a conflicting invitation
    already exists, are ``InvitationService`` concerns, not this model's
    (matching ``CommentCreate``'s identical division of responsibility).

    Attributes:
        email: The invited person's email address.
        full_name: The invited person's display name.
        role: The role to provision the resulting profile with on
            acceptance. Defaults to ``UserRole.EMPLOYEE``, matching
            ``InvitationRepository.create_invitation``'s own default.
        department: The department to provision the resulting profile
            with, if known.
    """

    email: str = Field(max_length=_EMAIL_MAX_LENGTH)
    full_name: str = Field(min_length=1, max_length=_FULL_NAME_MAX_LENGTH)
    role: UserRole = UserRole.EMPLOYEE
    department: str | None = Field(default=None, max_length=_DEPARTMENT_MAX_LENGTH)

    @field_validator("email")
    @classmethod
    def _validate_email(cls, value: str) -> str:
        return _validate_email_shape(value)
