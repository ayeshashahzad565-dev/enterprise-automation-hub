"""Unit tests for ``SupabaseClientFactory.create_user_scoped_client``.

Mirrors the existing testing shape for this factory's sibling methods
(``tests/unit/test_supabase_token_verifier.py`` patches
``create_anon_client`` at the call site it's used from; here we test the
factory method itself, so ``app.database.client.create_client`` — the
only place this module reaches out to the real ``supabase-py`` SDK — is
patched instead). No real network call is ever made.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.database.client import SupabaseClientFactory, SupabaseConnectionSettings

pytestmark = pytest.mark.unit


def _settings() -> SupabaseConnectionSettings:
    return SupabaseConnectionSettings(
        url="https://example.supabase.co",
        anon_key="anon-key",
        service_role_key="service-role-key",
    )


class TestCreateUserScopedClient:
    def test_constructs_a_non_service_role_client(self) -> None:
        with patch("app.database.client.create_client", return_value=MagicMock()):
            client = SupabaseClientFactory.create_user_scoped_client(_settings(), "a-caller-token")
        assert client.is_service_role is False

    def test_uses_the_anon_key_not_the_service_role_key(self) -> None:
        with patch("app.database.client.create_client", return_value=MagicMock()) as create_client:
            SupabaseClientFactory.create_user_scoped_client(_settings(), "a-caller-token")
        create_client.assert_called_once_with("https://example.supabase.co", "anon-key")

    def test_attaches_the_callers_access_token_to_postgrest(self) -> None:
        raw_client = MagicMock()
        with patch("app.database.client.create_client", return_value=raw_client):
            SupabaseClientFactory.create_user_scoped_client(_settings(), "a-callers-own-token")
        raw_client.postgrest.auth.assert_called_once_with("a-callers-own-token")

    def test_each_call_constructs_a_fresh_client_rather_than_reusing_one(self) -> None:
        """Two callers with different tokens must never share one
        underlying client instance — ``postgrest.auth(...)`` mutates
        headers in place, so reuse would let one request's identity leak
        into another's."""
        with patch("app.database.client.create_client", side_effect=[MagicMock(), MagicMock()]):
            first = SupabaseClientFactory.create_user_scoped_client(_settings(), "token-a")
            second = SupabaseClientFactory.create_user_scoped_client(_settings(), "token-b")
        assert first is not second

    def test_wraps_construction_failure_in_a_typed_error(self) -> None:
        from app.database.exceptions import DatabaseConnectionError

        with (
            patch("app.database.client.create_client", side_effect=RuntimeError("boom")),
            pytest.raises(DatabaseConnectionError),
        ):
            SupabaseClientFactory.create_user_scoped_client(_settings(), "a-caller-token")
