"""HTTP schemas for the public, unauthenticated invitation surface
(Milestone 6: ``GET /invitations/validate`` / ``POST /invitations/accept``).

Unlike ``app.api.schemas.admin_invitations.InvitationOut`` (a thin
``from_attributes=True`` wrapper over the full ``Invitation`` domain
model, intended for an authenticated administrator), the schemas here are
hand-built with an explicit, minimal field list — never
``model_validate``-ed straight off ``Invitation`` — precisely because the
caller is unauthenticated. Per this milestone's Security requirements,
``InvitationValidateOut`` must never expose the invitation's id, status,
version, audit trail, resend count, or any other internal field, even if
a future field is added to ``Invitation`` itself; explicit construction
in the router (see ``app.api.routers.public_invitations``) is what
guarantees that, not just this schema's ``extra="forbid"``.
"""

from __future__ import annotations

from pydantic import ConfigDict, Field

from app.models.base import EAHBaseModel, UTCDatetime
from app.models.enums import UserRole

__all__ = ["InvitationValidateOut", "InvitationAcceptBody", "InvitationAcceptOut"]

#: A generous but bounded cap on the raw invitation token accepted from a
#: caller, applied purely as a defensive shape check before the value
#: ever reaches ``hash_invitation_token`` — real tokens
#: (``generate_invitation_token``) are ~43 characters
#: (``secrets.token_urlsafe(32)``); this bound is intentionally far
#: looser than that so it never rejects a genuine token, only grotesquely
#: oversized junk.
_TOKEN_MAX_LENGTH = 512

#: A generous, bounded cap on the submitted password, applied purely as a
#: defensive request-shape limit. No complexity or minimum-strength rule
#: is enforced here (or anywhere else in this codebase) — per
#: ``app.auth.password``'s module docstring, password policy is entirely
#: Supabase Auth's own concern; this API layer only rejects an empty
#: value or an unreasonably large payload.
_PASSWORD_MAX_LENGTH = 4096


class InvitationValidateOut(EAHBaseModel):
    """Response for ``GET /invitations/validate``.

    Deliberately minimal: exactly the fields the accept-invitation
    frontend page needs to render before showing a password form, and
    nothing else — see this module's docstring.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    email: str
    full_name: str
    role: UserRole
    department: str | None
    expires_at: UTCDatetime


class InvitationAcceptBody(EAHBaseModel):
    """Body for ``POST /invitations/accept``."""

    token: str = Field(min_length=1, max_length=_TOKEN_MAX_LENGTH)
    password: str = Field(min_length=1, max_length=_PASSWORD_MAX_LENGTH)


class InvitationAcceptOut(EAHBaseModel):
    """Response for a successful ``POST /invitations/accept``.

    As minimal as ``InvitationValidateOut``, for the same reason. The
    frontend already holds ``email``/``password`` locally (it just
    submitted them) and signs the new user in itself via
    ``supabase.auth.signInWithPassword`` — this response exists only to
    confirm success and provide a display name for a "Welcome, {name}"
    transition, not to hand back any invitation state.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    email: str
    full_name: str
