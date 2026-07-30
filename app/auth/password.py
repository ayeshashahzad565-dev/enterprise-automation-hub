"""Generic password-hashing utility and password shape validation.

Per the Architecture Design Document, the API Design Document (Section
3.1), and the Deployment Guide (Section 10), Enterprise Automation Hub
delegates *all* user credential storage, hashing, and verification to
Supabase Auth — a plaintext password submitted to
``POST /api/v1/auth/login`` is forwarded directly to Supabase's sign-in
API and is never stored, hashed, or independently verified by this
codebase. No password complexity rule is enforced by EAH either; that is
also Supabase Auth's own configuration.

This module therefore serves two narrow, honestly-scoped purposes,
consistent with that architecture rather than in tension with it:

1. ``validate_password_shape``: the one password-related check the
   API-ADD does assign to this codebase (API-ADD Section 19.1.1:
   "password must be non-empty") — a presence check only, never a
   complexity rule.
2. ``hash_password`` / ``verify_password``: a self-contained,
   dependency-free (standard-library-only) password-hashing primitive
   using PBKDF2-HMAC-SHA256 with a per-password random salt. This is
   **not** used anywhere in the current baseline for Supabase-managed
   user credentials — it exists as generic, independently testable
   infrastructure for any narrow, documented future case where this
   application might need to hash a locally-held secret itself (there is
   no current call site). No dependency beyond ``hashlib``/``hmac``/
   ``secrets`` (Python's standard library) is introduced, consistent
   with the project's fixed technology stack, which includes no
   dedicated password-hashing library such as ``bcrypt`` or ``argon2``.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

from app.auth.exceptions import CredentialValidationError

__all__ = ["validate_password_shape", "hash_password", "verify_password"]

#: PBKDF2 iteration count. Chosen high enough to be computationally
#: costly for an attacker performing offline brute-force, per current
#: general-purpose guidance for PBKDF2-HMAC-SHA256, while remaining fast
#: enough for interactive, single-request use in the narrow contexts this
#: module is intended for.
_PBKDF2_ITERATIONS = 600_000

#: The salt length in bytes. 16 bytes (128 bits) is standard practice for
#: PBKDF2 salts.
_SALT_LENGTH_BYTES = 16

_HASH_ALGORITHM = "sha256"

#: The character separating the algorithm identifier, iteration count,
#: salt, and derived key within a single encoded hash string, chosen to
#: never collide with base64/hex output.
_FIELD_SEPARATOR = "$"


def validate_password_shape(password: str) -> str:
    """Validate that a candidate password is non-empty.

    Matches API-ADD Section 19.1.1's validation rule exactly: "password
    must be non-empty." No complexity, length, or character-class rule
    is enforced here, per DG Section 10's explicit statement that
    password policy is Supabase Auth's own concern.

    Args:
        password: The candidate password.

    Returns:
        ``password``, unchanged.

    Raises:
        CredentialValidationError: If ``password`` is empty.
    """
    if not password:
        raise CredentialValidationError("Password must not be empty.")
    return password


def hash_password(password: str) -> str:
    """Hash a password using PBKDF2-HMAC-SHA256 with a random salt.

    See this module's docstring for the scope and rationale of this
    function — it is not used for Supabase-managed user credentials in
    the current baseline.

    Args:
        password: The plaintext password to hash. Must be non-empty.

    Returns:
        An encoded string of the form
        ``"pbkdf2_sha256$<iterations>$<salt_hex>$<hash_hex>"``, suitable
        for storage and later verification via ``verify_password``.

    Raises:
        CredentialValidationError: If ``password`` is empty.
    """
    validate_password_shape(password)
    salt = secrets.token_bytes(_SALT_LENGTH_BYTES)
    derived_key = hashlib.pbkdf2_hmac(
        _HASH_ALGORITHM, password.encode("utf-8"), salt, _PBKDF2_ITERATIONS
    )
    return _FIELD_SEPARATOR.join(
        [
            f"pbkdf2_{_HASH_ALGORITHM}",
            str(_PBKDF2_ITERATIONS),
            salt.hex(),
            derived_key.hex(),
        ]
    )


def verify_password(password: str, encoded_hash: str) -> bool:
    """Verify a candidate password against a previously hashed value.

    Args:
        password: The candidate plaintext password.
        encoded_hash: A string previously produced by ``hash_password``.

    Returns:
        ``True`` if ``password`` matches the hash encoded in
        ``encoded_hash``, ``False`` otherwise (including if
        ``encoded_hash`` is malformed or uses an unrecognized algorithm
        identifier — a malformed stored hash is treated as a
        verification failure, never as an exception that could be
        mistaken for a successful bypass).

    Raises:
        CredentialValidationError: If ``password`` is empty.
    """
    validate_password_shape(password)
    try:
        algorithm, iterations_str, salt_hex, hash_hex = encoded_hash.split(_FIELD_SEPARATOR)
    except ValueError:
        return False
    if algorithm != f"pbkdf2_{_HASH_ALGORITHM}":
        return False
    try:
        iterations = int(iterations_str)
        salt = bytes.fromhex(salt_hex)
        expected_key = bytes.fromhex(hash_hex)
    except ValueError:
        return False

    candidate_key = hashlib.pbkdf2_hmac(_HASH_ALGORITHM, password.encode("utf-8"), salt, iterations)
    # Constant-time comparison to avoid leaking information about how
    # much of the derived key matched via a timing side channel.
    return hmac.compare_digest(candidate_key, expected_key)
