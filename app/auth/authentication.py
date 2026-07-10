"""Identity establishment from already-verified authentication claims.

Per the ADD, API Design Document (Section 3), and Deployment Guide
(Section 10), all authentication is delegated to Supabase Auth: token
issuance, refresh, and cryptographic signature verification are Supabase
Auth's responsibility, performed by whatever service-layer code holds a
Supabase client connection (outside this package's scope, per this
package's "no database access" constraint).

This module's responsibility begins *after* that point: given a mapping
of claims that have already been established as authentic (for example,
the payload Supabase's own ``client.auth.get_user(token)`` call returns
for a valid token), this module builds a typed, immutable
``AuthenticatedIdentity`` value object and enforces the one check that
*is* purely a function of the claims themselves and requires no network
access to perform: expiry.

This module also provides ``extract_bearer_token``, a pure string-parsing
function for the ``Authorization: Bearer <token>`` header convention
(API-ADD Section 3.2), and ``decode_jwt_payload_unverified``, a
diagnostic-only JWT payload decoder that performs **no cryptographic
verification whatsoever** and must never be used as the basis for an
authentication or authorization decision — it exists solely so that
logging or debugging code can inspect a token's claims without needing a
network round trip, and its docstring makes this restriction explicit.
"""

from __future__ import annotations

import base64
import binascii
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping
from uuid import UUID

from app.auth.exceptions import (
    InvalidTokenError,
    MalformedAuthorizationHeaderError,
    MissingCredentialsError,
    TokenExpiredError,
)
from app.config.security import AUTHORIZATION_HEADER_NAME, BEARER_AUTH_SCHEME
from app.models.enums import UserRole
from app.utils.datetime_utils import ensure_timezone_aware, is_past, utc_now

__all__ = [
    "AuthenticatedIdentity",
    "extract_bearer_token",
    "decode_jwt_payload_unverified",
]


@dataclass(frozen=True, slots=True)
class AuthenticatedIdentity:
    """An immutable representation of the currently authenticated caller.

    Instances are constructed exclusively via ``from_claims``, from a
    claims mapping the caller of this package is responsible for having
    already verified (per this module's docstring) — this class performs
    no cryptographic verification itself.

    Attributes:
        user_id: The authenticated user's id, resolved from the claims'
            ``sub`` field (matching ``profiles.id`` / ``auth.users.id``,
            per DSD Section 3.1).
        email: The authenticated user's email, if present in the claims.
        role: The user's RBAC role, resolved from the claims. Per API-ADD
            Section 3.4, ``AuthService`` resolves this from the
            ``profiles`` table rather than trusting a role embedded
            directly in the token, so the claims mapping passed to
            ``from_claims`` is expected to already carry the
            database-resolved role under a ``role`` key, not a raw,
            token-native claim.
        expires_at: The token's expiry timestamp, if present in the
            claims (standard JWT ``exp`` claim, as a Unix timestamp).
        raw_claims: The complete, original claims mapping, preserved for
            any diagnostic or forward-compatible need not covered by the
            typed fields above.
    """

    user_id: UUID
    email: str | None
    role: UserRole
    expires_at: datetime | None
    raw_claims: Mapping[str, Any]

    @classmethod
    def from_claims(cls, claims: Mapping[str, Any]) -> "AuthenticatedIdentity":
        """Construct an ``AuthenticatedIdentity`` from an already-verified
        claims mapping.

        Args:
            claims: A mapping containing at minimum ``sub`` (the user's
                id) and ``role`` (the user's RBAC role, already resolved
                from ``profiles.role`` by the caller, per API-ADD Section
                3.4). May also contain ``email`` and ``exp``.

        Returns:
            A new ``AuthenticatedIdentity``.

        Raises:
            InvalidTokenError: If ``sub`` or ``role`` is missing, or
                ``role`` does not match a recognized ``UserRole`` value.
            TokenExpiredError: If ``exp`` is present and indicates the
                token has already expired.
        """
        subject = claims.get("sub")
        if not subject:
            raise InvalidTokenError("Claims are missing a required 'sub' (subject) field.")
        try:
            user_id = UUID(str(subject))
        except (ValueError, AttributeError, TypeError) as exc:
            raise InvalidTokenError(f"Claims' 'sub' field is not a valid UUID: {subject!r}") from exc

        raw_role = claims.get("role")
        if not raw_role:
            raise InvalidTokenError("Claims are missing a required 'role' field.")
        try:
            role = UserRole(raw_role)
        except ValueError as exc:
            raise InvalidTokenError(f"Claims' 'role' field is not recognized: {raw_role!r}") from exc

        expires_at: datetime | None = None
        raw_exp = claims.get("exp")
        if raw_exp is not None:
            expires_at = ensure_timezone_aware(datetime.fromtimestamp(float(raw_exp), tz=None))
            if is_past(expires_at, reference=utc_now()):
                raise TokenExpiredError(expires_at)

        return cls(
            user_id=user_id,
            email=claims.get("email"),
            role=role,
            expires_at=expires_at,
            raw_claims=claims,
        )

    @property
    def is_expired(self) -> bool:
        """Whether this identity's token has already expired, per its
        own ``expires_at`` claim.

        Returns:
            ``True`` if ``expires_at`` is set and in the past; ``False``
            if ``expires_at`` is unset (no expiry claim was present) or
            still in the future.
        """
        if self.expires_at is None:
            return False
        return is_past(self.expires_at)


def extract_bearer_token(header_value: str | None) -> str:
    """Extract the raw token from an ``Authorization: Bearer <token>`` header.

    Matches API-ADD Section 3.2's authentication convention exactly.

    Args:
        header_value: The raw ``Authorization`` header value, or
            ``None`` if the header was not present at all.

    Returns:
        The extracted token string.

    Raises:
        MissingCredentialsError: If ``header_value`` is ``None`` or empty.
        MalformedAuthorizationHeaderError: If ``header_value`` does not
            match the ``"<scheme> <token>"`` shape, or its scheme is not
            ``Bearer`` (case-insensitive).
    """
    if not header_value or not header_value.strip():
        raise MissingCredentialsError()

    parts = header_value.strip().split(maxsplit=1)
    if len(parts) != 2:
        raise MalformedAuthorizationHeaderError(header_value)

    scheme, token = parts
    if scheme.lower() != BEARER_AUTH_SCHEME.lower():
        raise MalformedAuthorizationHeaderError(header_value)
    if not token:
        raise MalformedAuthorizationHeaderError(header_value)

    return token


def decode_jwt_payload_unverified(token: str) -> dict[str, Any]:
    """Decode a JWT's payload segment without verifying its signature.

    **Security warning:** this function performs no cryptographic
    verification whatsoever. It exists solely to allow diagnostic or
    logging code to inspect a token's claims (for example, to log the
    ``sub`` claim of a request that failed verified authentication
    upstream) without a network round trip. The output of this function
    must **never** be used as the basis for an authentication or
    authorization decision — use ``AuthenticatedIdentity.from_claims``
    with claims obtained through a verified path (Supabase's own
    ``client.auth.get_user(token)``) for that purpose instead.

    Args:
        token: The raw JWT string (``header.payload.signature``).

    Returns:
        The decoded payload as a dict.

    Raises:
        InvalidTokenError: If ``token`` is not a well-formed JWT (wrong
            number of segments, invalid base64url encoding, or a payload
            that does not decode to a JSON object).
    """
    segments = token.split(".")
    if len(segments) != 3:
        raise InvalidTokenError(
            f"Token does not have the expected three dot-separated segments; "
            f"got {len(segments)}."
        )
    payload_segment = segments[1]
    padded = payload_segment + "=" * (-len(payload_segment) % 4)
    try:
        payload_bytes = base64.urlsafe_b64decode(padded)
        payload = json.loads(payload_bytes)
    except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InvalidTokenError(f"Token payload could not be decoded: {exc}") from exc

    if not isinstance(payload, dict):
        raise InvalidTokenError("Token payload did not decode to a JSON object.")
    return payload