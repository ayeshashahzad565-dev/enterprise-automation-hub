"""A narrow abstraction around the Supabase Auth Admin API.

Per the Enterprise User Onboarding architecture (Milestone 3),
``InvitationService.accept_invitation`` needs to create a real,
login-capable Supabase Auth user at the moment an invitation is
accepted — the one point in this codebase where "authentication is
entirely delegated to Supabase" (``app.auth.authentication``'s module
docstring) requires *issuing* a credential, not just verifying one
already issued. ``SupabaseAuthAdminClient`` is the ``typing.Protocol``
that lets ``InvitationService`` depend on that capability abstractly —
never on the Supabase SDK directly — exactly mirroring
``app.database.client.DatabaseClient``'s identical role for the
Repository Layer, and ``app.services.notification_service.EmailSender``'s
identical role for email dispatch.

``SupabaseAuthAdminClientImpl`` is the production implementation, backed
by ``supabase-py``. It translates every Supabase SDK failure into this
project's own exception vocabulary before it ever reaches
``InvitationService`` — no ``supabase``/``supabase_auth`` exception type
is ever allowed to propagate past this module's boundary, matching
``BaseRepository._translate_and_raise``'s identical "translate at the
integration boundary, never leak the third-party type" discipline. Two
outcomes are distinguished, precisely because ``InvitationService``'s
idempotent-retry recovery depends on being able to tell them apart:

- ``InvitationConflictError``: Supabase reports a user already exists
  for the requested email/id. Recoverable — see
  ``InvitationService.accept_invitation``'s own docstring.
- ``SupabaseAdminOperationError``: any other failure. Not recoverable;
  the invitation remains ``pending`` and unmodified.

``anonymize_user`` is this same abstraction's second capability, added for
GDPR right-to-erasure (``app.services.user_service.UserService.
erase_user``): scrubbing a user's email and permanently banning login,
without deleting the ``auth.users`` row — see its own docstring for why
deletion is not an option here.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any, Protocol, runtime_checkable
from uuid import UUID

from app.database.client import SupabaseDatabaseClient
from app.services.exceptions import InvitationConflictError, SupabaseAdminOperationError

__all__ = ["SupabaseAuthAdminClient", "SupabaseAuthAdminClientImpl"]

logger = logging.getLogger(__name__)

#: Structured Supabase Auth error codes (``supabase_auth.errors.ErrorCode``)
#: observed for "a user already exists for this email/id" — checked first,
#: before the string-matching fallback below, mirroring
#: ``BaseRepository._translate_and_raise``'s identical "structured code
#: first, string match as a fallback" precedence.
_DUPLICATE_USER_ERROR_CODES = frozenset(
    {"email_exists", "user_already_exists", "identity_already_exists"}
)

#: Fallback substrings checked against the lowercased exception message
#: when no structured error code is available (e.g. a Supabase SDK
#: version whose exception type does not expose ``.code``).
_DUPLICATE_USER_MESSAGE_MARKERS = (
    "already been registered",
    "already registered",
    "already exists",
)


def _is_duplicate_user_error(exc: Exception) -> bool:
    """Return whether ``exc`` represents "a user already exists" rather
    than some other Supabase Admin API failure.

    Args:
        exc: The raw exception raised by the Supabase SDK.

    Returns:
        ``True`` if ``exc`` should be translated to
        ``InvitationConflictError``; ``False`` if it should be translated
        to the generic ``SupabaseAdminOperationError``.
    """
    code = getattr(exc, "code", None)
    if code in _DUPLICATE_USER_ERROR_CODES:
        return True
    message = str(exc).lower()
    return any(marker in message for marker in _DUPLICATE_USER_MESSAGE_MARKERS)


@runtime_checkable
class SupabaseAuthAdminClient(Protocol):
    """Structural interface for creating a Supabase Auth user
    administratively.

    ``InvitationService`` depends on this protocol only — never on
    ``supabase-py`` or any concrete client type — so that a hand-written
    fake satisfying only this interface can exercise
    ``accept_invitation`` in a unit test with no network dependency (TSD
    Section 3.3's established pattern, applied to this new integration
    boundary).
    """

    def create_user(
        self, *, user_id: UUID, email: str, password: str, user_metadata: Mapping[str, Any]
    ) -> UUID:
        """Create a new Supabase Auth user with a caller-specified id.

        Args:
            user_id: The id to assign the new user, overriding Supabase's
                own default of generating one — the caller (
                ``InvitationService``) is responsible for choosing a
                value that makes retrying this exact call safe; see its
                own docstring for why the invitation's own id is used.
            email: The new user's email address.
            password: The new user's chosen password, in plaintext, over
                this one call only — never stored or logged by any
                implementation of this protocol.
            user_metadata: Metadata attached to the new user
                (``full_name``, ``role``), read by the existing
                ``on_auth_user_created`` trigger (migration ``0002``) to
                provision the corresponding ``profiles`` row.

        Returns:
            The created user's id. Implementations are expected to
            return exactly ``user_id`` on success.

        Raises:
            InvitationConflictError: If a user already exists for this
                email address (or this id) — the specific, recoverable
                condition ``InvitationService.accept_invitation`` treats
                as idempotent-retry recovery rather than a hard failure.
            SupabaseAdminOperationError: For any other failure. No raw
                SDK exception type is ever raised by an implementation of
                this protocol.
        """
        ...

    def anonymize_user(self, *, user_id: UUID, anonymized_email: str) -> None:
        """Scrub a user's email and permanently ban further login.

        Used by ``app.services.user_service.UserService.erase_user`` for
        GDPR right-to-erasure. Deliberately does **not** delete the
        ``auth.users`` row: ``profiles.id`` is ``foreign key references
        auth.users(id) on delete cascade``, so deleting it would cascade
        into ``profiles`` and immediately fail with a foreign-key
        violation for any user with real audit/request/comment/attachment
        history (see ``0020_profile_lifecycle``'s migration docstring) —
        exactly the users this operation exists to serve. Scrubbing the
        email in place and banning the account instead achieves the same
        practical outcome (the account can never again be used, and its
        one piece of PII outside ``public.profiles`` is gone) without
        that failure mode.

        Args:
            user_id: The Supabase Auth user id to anonymize (equal to the
                corresponding ``profiles.id``).
            anonymized_email: The replacement email address (computed by
                the caller — see ``UserService.erase_user`` — as a
                deterministic, non-deliverable placeholder derived from
                ``user_id``).

        Raises:
            SupabaseAdminOperationError: If the Supabase Admin API call
                fails for any reason. No raw SDK exception type is ever
                raised by an implementation of this protocol.
        """
        ...


class SupabaseAuthAdminClientImpl:
    """Production ``SupabaseAuthAdminClient``, backed by ``supabase-py``.

    Constructed around an already-built ``SupabaseDatabaseClient`` (the
    service-role client — the elevated credential this Admin API call
    requires, per DSD Section 9.3) rather than constructing its own
    connection, matching every other production component in this
    codebase that depends on an already-constructed client rather than
    building one itself.
    """

    def __init__(self, client: SupabaseDatabaseClient) -> None:
        """Initialize the client wrapper.

        Args:
            client: An already-constructed Supabase client. Must be a
                service-role client (``client.is_service_role`` ``True``)
                — the Admin API is not reachable with an anon key. This
                is not asserted here (matching how this codebase's other
                privilege-sensitive call sites document, rather than
                runtime-check, that expectation); constructing this class
                with anything else is a configuration error at the
                composition root, not a runtime condition this class
                degrades from.
        """
        self._client = client
        self._logger = logging.getLogger(f"{__name__}.SupabaseAuthAdminClientImpl")

    def create_user(
        self, *, user_id: UUID, email: str, password: str, user_metadata: Mapping[str, Any]
    ) -> UUID:
        """See ``SupabaseAuthAdminClient.create_user``."""
        try:
            response = self._client.auth.admin.create_user(
                {
                    "id": str(user_id),
                    "email": email,
                    "password": password,
                    "email_confirm": True,
                    "user_metadata": dict(user_metadata),
                }
            )
        except Exception as exc:  # noqa: BLE001 - Supabase's own exception type (supabase_auth's
            # AuthApiError) is not part of any finalized package's exception
            # hierarchy, so it is caught broadly here and translated below —
            # exactly the same integration-boundary discipline
            # SupabaseTokenVerifier.resolve_claims already applies to a
            # different Supabase Auth SDK call.
            if _is_duplicate_user_error(exc):
                self._logger.info(
                    "Supabase Admin API reported an existing user for id %s during "
                    "invitation acceptance.",
                    user_id,
                )
                raise InvitationConflictError(email) from exc
            self._logger.error(
                "Supabase Admin API user creation failed for id %s: %s", user_id, exc, exc_info=exc
            )
            raise SupabaseAdminOperationError(
                "Supabase Admin API failed to create a user for this invitation."
            ) from exc

        return UUID(str(response.user.id))

    def anonymize_user(self, *, user_id: UUID, anonymized_email: str) -> None:
        """See ``SupabaseAuthAdminClient.anonymize_user``."""
        try:
            self._client.auth.admin.update_user_by_id(
                str(user_id),
                {
                    "email": anonymized_email,
                    "email_confirm": True,
                    "ban_duration": "876000h",  # ~100 years: permanent, in practice
                    "user_metadata": {},
                    "app_metadata": {},
                },
            )
        except Exception as exc:  # noqa: BLE001 - Supabase's own exception type is not part of
            # any finalized package's exception hierarchy; translated below,
            # matching create_user's identical integration-boundary discipline.
            self._logger.error(
                "Supabase Admin API failed to anonymize user %s: %s", user_id, exc, exc_info=exc
            )
            raise SupabaseAdminOperationError(
                "Supabase Admin API failed to anonymize this user."
            ) from exc
