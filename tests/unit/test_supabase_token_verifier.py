"""Unit tests for ``app.auth.supabase_verifier.SupabaseTokenVerifier``.

No such test file existed before the Platform Administration module —
this covers both the pre-existing behavior (valid token → claims,
Supabase rejection → ``InvalidTokenError``, no profile →
``InvalidTokenError``) and the new company-suspension/-deletion
enforcement this module adds (``CompanyAccessRevokedError``).

The real Supabase client is never constructed: ``SupabaseClientFactory
.create_anon_client`` is patched to return a stand-in whose
``auth.get_user`` is a plain ``Mock``, matching this verifier's own
narrow "translate whatever Supabase/gotrue raises" contract without any
real network dependency.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from app.auth.exceptions import (
    AccountAccessRevokedError,
    CompanyAccessRevokedError,
    InvalidTokenError,
)
from app.auth.supabase_verifier import SupabaseTokenVerifier
from app.database.client import SupabaseConnectionSettings
from app.models.enums import UserRole
from tests.fixtures.fakes import FakeCompanyRepository, FakeProfileRepository

pytestmark = pytest.mark.unit


def _settings() -> SupabaseConnectionSettings:
    return SupabaseConnectionSettings(
        url="https://example.supabase.co",
        anon_key="anon-key",
        service_role_key="service-role-key",
    )


def _verifier(
    profile_repo: FakeProfileRepository, company_repo: FakeCompanyRepository
) -> SupabaseTokenVerifier:
    return SupabaseTokenVerifier(
        supabase_settings=_settings(), profile_repo=profile_repo, company_repo=company_repo
    )


def _mock_supabase_client(*, user_id, email: str = "user@example.com"):
    client = MagicMock()
    client.auth.get_user.return_value = MagicMock(user=MagicMock(id=str(user_id), email=email))
    return client


class TestValidToken:
    def test_resolves_claims_for_an_active_company(self):
        profile_repo = FakeProfileRepository()
        company_repo = FakeCompanyRepository()
        company = company_repo.create_company(name="Acme", slug="acme")
        profile = profile_repo.create_profile(
            profile_id=uuid4(), full_name="Jane", role=UserRole.EMPLOYEE, company_id=company.id
        )
        verifier = _verifier(profile_repo, company_repo)

        with patch(
            "app.auth.supabase_verifier.SupabaseClientFactory.create_anon_client",
            return_value=_mock_supabase_client(user_id=profile.id),
        ):
            claims = verifier.resolve_claims("a-real-token")

        assert claims["sub"] == str(profile.id)
        assert claims["role"] == "employee"
        assert claims["company_id"] == str(company.id)
        assert claims["is_platform_admin"] is False


class TestSupabaseRejection:
    def test_no_user_returned_raises_invalid_token(self):
        profile_repo = FakeProfileRepository()
        company_repo = FakeCompanyRepository()
        verifier = _verifier(profile_repo, company_repo)
        client = MagicMock()
        client.auth.get_user.return_value = MagicMock(user=None)

        with patch(
            "app.auth.supabase_verifier.SupabaseClientFactory.create_anon_client",
            return_value=client,
        ), pytest.raises(InvalidTokenError):
            verifier.resolve_claims("bad-token")

    def test_supabase_raising_is_translated_to_invalid_token(self):
        profile_repo = FakeProfileRepository()
        company_repo = FakeCompanyRepository()
        verifier = _verifier(profile_repo, company_repo)
        client = MagicMock()
        client.auth.get_user.side_effect = Exception("network error")

        with patch(
            "app.auth.supabase_verifier.SupabaseClientFactory.create_anon_client",
            return_value=client,
        ), pytest.raises(InvalidTokenError):
            verifier.resolve_claims("bad-token")


class TestNoProfile:
    def test_missing_profile_raises_invalid_token(self):
        profile_repo = FakeProfileRepository()
        company_repo = FakeCompanyRepository()
        verifier = _verifier(profile_repo, company_repo)
        missing_user_id = uuid4()

        with patch(
            "app.auth.supabase_verifier.SupabaseClientFactory.create_anon_client",
            return_value=_mock_supabase_client(user_id=missing_user_id),
        ), pytest.raises(InvalidTokenError):
            verifier.resolve_claims("a-real-token")


class TestCompanyAccessRevoked:
    def test_suspended_company_blocks_the_user(self):
        profile_repo = FakeProfileRepository()
        company_repo = FakeCompanyRepository()
        company = company_repo.create_company(name="Acme", slug="acme")
        company_repo.update_company(company.id, expected_version=company.version, is_active=False)
        profile = profile_repo.create_profile(
            profile_id=uuid4(), full_name="Jane", role=UserRole.EMPLOYEE, company_id=company.id
        )
        verifier = _verifier(profile_repo, company_repo)

        with patch(
            "app.auth.supabase_verifier.SupabaseClientFactory.create_anon_client",
            return_value=_mock_supabase_client(user_id=profile.id),
        ), pytest.raises(CompanyAccessRevokedError) as exc_info:
            verifier.resolve_claims("a-real-token")
        assert exc_info.value.reason == "suspended"

    def test_deleted_company_blocks_the_user(self):
        profile_repo = FakeProfileRepository()
        company_repo = FakeCompanyRepository()
        company = company_repo.create_company(name="Acme", slug="acme")
        company_repo.soft_delete(company.id, expected_version=company.version, deleted_by=uuid4())
        profile = profile_repo.create_profile(
            profile_id=uuid4(), full_name="Jane", role=UserRole.EMPLOYEE, company_id=company.id
        )
        verifier = _verifier(profile_repo, company_repo)

        with patch(
            "app.auth.supabase_verifier.SupabaseClientFactory.create_anon_client",
            return_value=_mock_supabase_client(user_id=profile.id),
        ), pytest.raises(CompanyAccessRevokedError) as exc_info:
            verifier.resolve_claims("a-real-token")
        assert exc_info.value.reason == "deleted"

    def test_active_company_is_unaffected(self):
        profile_repo = FakeProfileRepository()
        company_repo = FakeCompanyRepository()
        company = company_repo.create_company(name="Acme", slug="acme")
        profile = profile_repo.create_profile(
            profile_id=uuid4(), full_name="Jane", role=UserRole.EMPLOYEE, company_id=company.id
        )
        verifier = _verifier(profile_repo, company_repo)

        with patch(
            "app.auth.supabase_verifier.SupabaseClientFactory.create_anon_client",
            return_value=_mock_supabase_client(user_id=profile.id),
        ):
            claims = verifier.resolve_claims("a-real-token")
        assert claims["sub"] == str(profile.id)


class TestAccountAccessRevoked:
    def test_a_deactivated_profile_is_blocked_on_its_very_next_request(self):
        profile_repo = FakeProfileRepository()
        company_repo = FakeCompanyRepository()
        company = company_repo.create_company(name="Acme", slug="acme")
        profile = profile_repo.create_profile(
            profile_id=uuid4(), full_name="Jane", role=UserRole.EMPLOYEE, company_id=company.id
        )
        profile_repo.update_profile(profile.id, expected_version=profile.version, is_active=False)
        verifier = _verifier(profile_repo, company_repo)

        with patch(
            "app.auth.supabase_verifier.SupabaseClientFactory.create_anon_client",
            return_value=_mock_supabase_client(user_id=profile.id),
        ), pytest.raises(AccountAccessRevokedError) as exc_info:
            verifier.resolve_claims("a-real-token")
        assert exc_info.value.reason == "deactivated"

    def test_an_erased_profile_is_blocked(self):
        profile_repo = FakeProfileRepository()
        company_repo = FakeCompanyRepository()
        company = company_repo.create_company(name="Acme", slug="acme")
        profile = profile_repo.create_profile(
            profile_id=uuid4(), full_name="Jane", role=UserRole.EMPLOYEE, company_id=company.id
        )
        profile_repo.erase(
            profile.id,
            expected_version=profile.version,
            deleted_by=uuid4(),
            anonymized_full_name="Deleted User",
        )
        verifier = _verifier(profile_repo, company_repo)

        with patch(
            "app.auth.supabase_verifier.SupabaseClientFactory.create_anon_client",
            return_value=_mock_supabase_client(user_id=profile.id),
        ), pytest.raises(AccountAccessRevokedError) as exc_info:
            verifier.resolve_claims("a-real-token")
        assert exc_info.value.reason == "erased"

    def test_an_active_profile_is_unaffected(self):
        profile_repo = FakeProfileRepository()
        company_repo = FakeCompanyRepository()
        company = company_repo.create_company(name="Acme", slug="acme")
        profile = profile_repo.create_profile(
            profile_id=uuid4(), full_name="Jane", role=UserRole.EMPLOYEE, company_id=company.id
        )
        verifier = _verifier(profile_repo, company_repo)

        with patch(
            "app.auth.supabase_verifier.SupabaseClientFactory.create_anon_client",
            return_value=_mock_supabase_client(user_id=profile.id),
        ):
            claims = verifier.resolve_claims("a-real-token")
        assert claims["sub"] == str(profile.id)
