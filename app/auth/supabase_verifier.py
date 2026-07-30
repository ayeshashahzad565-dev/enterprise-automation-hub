"""Per-request Supabase bearer-token verification for a stateless HTTP entry point.

Per ``app.auth.middleware``'s own documented expectation, a
``ClaimsResolver`` "is expected to be a thin wrapper around Supabase's
own ``client.auth.get_user(token)`` call, supplied by a future
service-layer package that holds the actual Supabase client connection."
This module is that missing resolver.

This is deliberately a different, narrower capability than
``app.py``'s ``SupabaseAuthGateway``: that class performs the sign-in,
callback-exchange, and password-management *flows* a Streamlit login
form drives, always starting from a fresh Supabase Auth response.
This module instead validates a bearer token an HTTP client already
holds — the one thing every authenticated REST request needs checked,
fresh, on every call (API-ADD Section 5.3, 5.5), since a stateless API
has no server-side session to consult instead. Neither class depends on
the other; both happen to construct a fresh, unauthenticated Supabase
client per call, for the same isolation reason
``SupabaseAuthGateway``'s own docstring already gives (avoiding any
possibility of one caller's auth call mutating shared client-side state
another concurrent caller might rely on).

No new exception type is introduced here — every failure mode this
module can produce (a token Supabase rejects, a token whose subject has
no corresponding ``profiles`` row) is already represented by
``app.auth.exceptions.InvalidTokenError``.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any
from uuid import UUID

from app.auth.exceptions import (
    AccountAccessRevokedError,
    CompanyAccessRevokedError,
    InvalidTokenError,
)
from app.database.client import SupabaseClientFactory, SupabaseConnectionSettings
from app.database.exceptions import RecordNotFoundError
from app.database.repositories.company_repository import CompanyRepository
from app.database.repositories.user_repository import ProfileRepository

__all__ = ["SupabaseTokenVerifier"]

logger = logging.getLogger(__name__)


class SupabaseTokenVerifier:
    """Verifies an incoming bearer token against Supabase and resolves its role.

    Satisfies ``app.auth.middleware.ClaimsResolver``
    (``Callable[[str], Mapping[str, Any]]``) via its ``resolve_claims``
    method, so it can be handed directly to
    ``AuthenticationMiddleware(claims_resolver=...)`` without adapting.
    """

    def __init__(
        self,
        *,
        supabase_settings: SupabaseConnectionSettings,
        profile_repo: ProfileRepository,
        company_repo: CompanyRepository,
    ) -> None:
        """Initialize the verifier.

        Args:
            supabase_settings: The Supabase project's connection
                settings, used to construct a fresh anon-key client per
                call.
            profile_repo: Used to resolve the token's role from
                ``profiles`` — per the ADD, a role is always resolved
                from the database, never trusted from a raw JWT claim.
            company_repo: Used to check the caller's company is still
                active on every request — per the Platform
                Administration module, suspending or deleting a company
                must take effect immediately, not just at next login.
        """
        self._supabase_settings = supabase_settings
        self._profile_repo = profile_repo
        self._company_repo = company_repo
        self._logger = logging.getLogger(f"{__name__}.SupabaseTokenVerifier")

    def resolve_claims(self, token: str) -> Mapping[str, Any]:
        """Validate a bearer token against Supabase and return its claims.

        Args:
            token: The raw bearer token, as extracted by
                ``app.auth.authentication.extract_bearer_token``.

        Returns:
            A claims mapping (``sub``, ``email``, ``role``, ``company_id``,
            ``is_platform_admin``) suitable for
            ``app.auth.authentication.AuthenticatedIdentity.from_claims``.
            ``exp`` is intentionally omitted: Supabase's own
            ``get_user`` call below already confirms the token is valid
            *as of this call*, and the resulting identity is used and
            discarded within the same request — there is no later point
            in a stateless request for a separately-tracked expiry to
            matter.

        Raises:
            InvalidTokenError: If Supabase rejects the token, or no
                ``profiles`` row exists for its subject.
        """
        client = SupabaseClientFactory.create_anon_client(self._supabase_settings)
        try:
            response = client.auth.get_user(token)
        except Exception as exc:  # noqa: BLE001 - translated below; Supabase's own
            # exception type (gotrue's AuthApiError) is not part of any
            # finalized package's exception hierarchy, so it is caught
            # broadly here and translated into this project's own
            # InvalidTokenError, exactly as SupabaseAuthGateway translates
            # a third-party failure at this same integration boundary.
            self._logger.warning("Supabase bearer token verification failed: %s", exc)
            raise InvalidTokenError("Bearer token could not be verified.") from exc

        if response.user is None:
            raise InvalidTokenError("Supabase did not return a user for this bearer token.")

        try:
            profile = self._profile_repo.get_by_id(UUID(response.user.id))
        except RecordNotFoundError as exc:
            self._logger.error(
                "No profile exists for authenticated user %s: %s", response.user.id, exc
            )
            raise InvalidTokenError(
                "This account is not fully provisioned. Contact an administrator."
            ) from exc
        # A transient DatabaseError (connection timeout, pool exhaustion, a
        # one-off PostgREST 5xx) is deliberately NOT caught here: Supabase
        # has already confirmed this bearer token itself is valid (the
        # get_user call above succeeded), so a DB hiccup on the *profile
        # lookup* is not evidence of a bad token. Left uncaught, it
        # propagates to the generic 500 handler (retryable) instead of
        # being mislabeled InvalidTokenError -> 401, which would otherwise
        # make the frontend's handleUnauthorized() sign the user out of an
        # otherwise perfectly valid session on a one-off DB blip.

        # Per the deletion-strategy design (docs/database_schema.md
        # Section 3.10, 0020_profile_lifecycle): a deactivated or erased
        # profile must be blocked immediately, on this very request, not
        # just at next login — this verifier is re-run on every
        # authenticated request with no server-side session cache, the
        # same reasoning the company check just below already relies on.
        if profile.deleted_at is not None:
            raise AccountAccessRevokedError("erased")
        if not profile.is_active:
            raise AccountAccessRevokedError("deactivated")

        # Per the Platform Administration module: a suspended or deleted
        # company blocks every one of its users immediately, on their
        # very next request — this check runs here (not just at login)
        # because this verifier itself is re-run on every authenticated
        # request, with no server-side session cache to go stale.
        company = self._company_repo.get_by_id(profile.company_id)
        if company.deleted_at is not None:
            raise CompanyAccessRevokedError("deleted")
        if not company.is_active:
            raise CompanyAccessRevokedError("suspended")

        return {
            "sub": str(profile.id),
            "email": response.user.email,
            "role": profile.role.value,
            "company_id": str(profile.company_id),
            "is_platform_admin": profile.is_platform_admin,
        }
