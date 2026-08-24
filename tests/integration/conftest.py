"""Fixtures for the real-database integration suite.

Unlike ``tests/unit``, ``tests/acceptance``, ``tests/security``, and
``tests/performance`` (which all run against the in-memory fakes in
``tests/fixtures/fakes.py`` and never touch a network), every fixture
here talks to a **real, disposable, migrated Postgres/Supabase test
database** — never the fakes, and never the production project. See
``tests/integration/README.md`` for how to provision one.

Configuration is read from four environment variables, deliberately
named differently from this project's production variables
(``DATABASE_URL``, ``SUPABASE_URL``, ``SUPABASE_ANON_KEY``,
``SUPABASE_SERVICE_ROLE_KEY``) so that this suite can never accidentally
run destructive constraint/rollback/cleanup operations against the
production project just because a populated ``.env`` happens to be
present:

- ``TEST_DATABASE_URL`` — a direct Postgres connection string (the same
  shape as ``DATABASE_URL``) to the test project/instance, used for raw
  schema/constraint/transaction tests and for cross-table cleanup that
  the Repository Layer deliberately does not expose (``audit_logs`` and
  ``comments`` are insert/soft-delete-only by design).
- ``TEST_SUPABASE_URL`` / ``TEST_SUPABASE_SERVICE_ROLE_KEY`` — the test
  project's API URL and service-role key, used to construct the exact
  same ``SupabaseDatabaseClient`` the running application uses, so
  repository-level tests exercise the real ``postgrest`` wire behavior.
- ``TEST_SUPABASE_ANON_KEY`` — the test project's real anon/public key,
  used only by ``make_authenticated_user`` to sign in as a genuine user
  and prove Row-Level Security itself (not the service-role bypass)
  blocks a cross-user request — see ``test_rls_enforcement.py``.

Locally (outside CI), every fixture here skips — never fails — when its
required variables are absent, so the rest of the suite
(unit/acceptance/security/performance) remains runnable with a plain
``pytest`` in any environment with no test database configured at all.
**In CI** (``CI=true``, set by every major provider including GitHub
Actions), the same missing configuration fails the run instead — see
``_running_in_ci``/``_missing_config`` below — so a broken CI step can
never make this suite silently report green by skipping every test.
"""

from __future__ import annotations

import contextlib
import os
import uuid
from collections.abc import Iterator
from typing import Any

import psycopg
import pytest

from app.database.client import (
    SupabaseClientFactory,
    SupabaseConnectionSettings,
    SupabaseDatabaseClient,
)
from app.database.repositories.analytics_repository import AnalyticsRepository
from app.database.repositories.approval_repository import ApprovalRepository
from app.database.repositories.attachment_repository import AttachmentRepository
from app.database.repositories.audit_repository import AuditRepository
from app.database.repositories.comment_repository import CommentRepository
from app.database.repositories.company_license_repository import CompanyLicenseRepository
from app.database.repositories.company_repository import CompanyRepository
from app.database.repositories.feature_flag_repository import FeatureFlagRepository
from app.database.repositories.invitation_repository import InvitationRepository
from app.database.repositories.job_repository import JobRepository
from app.database.repositories.notification_preference_repository import (
    NotificationPreferenceRepository,
)
from app.database.repositories.notification_repository import NotificationRepository
from app.database.repositories.request_repository import RequestRepository
from app.database.repositories.user_repository import ProfileRecord, ProfileRepository
from app.database.repositories.workflow_repository import (
    WorkflowDefinitionRepository,
    WorkflowStageRepository,
)
from app.models.enums import UserRole

TEST_DATABASE_URL_VAR = "TEST_DATABASE_URL"
TEST_SUPABASE_URL_VAR = "TEST_SUPABASE_URL"
TEST_SUPABASE_SERVICE_ROLE_KEY_VAR = "TEST_SUPABASE_SERVICE_ROLE_KEY"
TEST_SUPABASE_ANON_KEY_VAR = "TEST_SUPABASE_ANON_KEY"

_SKIP_DB_REASON = (
    f"{TEST_DATABASE_URL_VAR} is not set — see tests/integration/README.md "
    "to point this suite at a dedicated test database."
)
_SKIP_SUPABASE_REASON = (
    f"{TEST_SUPABASE_URL_VAR}/{TEST_SUPABASE_SERVICE_ROLE_KEY_VAR} are not set — "
    "see tests/integration/README.md to point this suite at a dedicated test project."
)
_SKIP_SUPABASE_ANON_REASON = (
    f"{TEST_SUPABASE_ANON_KEY_VAR} is not set — see tests/integration/README.md "
    "to point this suite at a dedicated test project."
)


def _running_in_ci() -> bool:
    """Whether this process is executing inside a CI runner.

    GitHub Actions (like every other major CI provider) sets ``CI=true``
    for every job unconditionally. This suite uses that ambient signal to
    tell apart the two situations that can lead here with no test
    database configured: a developer running plain ``pytest`` locally
    with no test project set up (skip, as always — the rest of the suite
    must stay runnable with zero configuration), versus a CI job that was
    supposed to provision one and didn't (fail loudly instead). Skipping
    in the latter case would report ``.github/workflows/integration.yml``
    as green while exercising zero real assertions against a real
    database or its RLS policies — the same vacuous-pass failure mode
    already fixed once in this project for a route-introspection test
    (see ``tests/unit/test_tenant_scoping_enforcement.py``), just showing
    up here as a skip instead of a trivially-true assertion.
    """
    return os.environ.get("CI", "").strip().lower() in ("true", "1", "yes")


def _missing_config(var_names: str, reason: str) -> None:
    """Skip locally, but fail hard in CI, when required test-database
    configuration is absent. See ``_running_in_ci`` for why the two
    environments are treated differently.
    """
    if _running_in_ci():
        pytest.fail(
            f"{var_names} not set while running in CI — the integration workflow "
            "must provision a real Supabase test database and export these "
            "(see .github/workflows/integration.yml and tests/integration/README.md). "
            "Skipping here would silently report this job as green without running "
            "any of these tests.",
            pytrace=False,
        )
    pytest.skip(reason)


def _test_database_url() -> str:
    url = os.environ.get(TEST_DATABASE_URL_VAR)
    if not url:
        _missing_config(TEST_DATABASE_URL_VAR, _SKIP_DB_REASON)
    assert url is not None  # narrows for mypy; _missing_config always raises/skips above
    return url


def _test_supabase_credentials() -> tuple[str, str]:
    url = os.environ.get(TEST_SUPABASE_URL_VAR)
    key = os.environ.get(TEST_SUPABASE_SERVICE_ROLE_KEY_VAR)
    if not url or not key:
        _missing_config(
            f"{TEST_SUPABASE_URL_VAR}/{TEST_SUPABASE_SERVICE_ROLE_KEY_VAR}",
            _SKIP_SUPABASE_REASON,
        )
    assert url is not None and key is not None
    return url, key


def _test_supabase_anon_key() -> str:
    key = os.environ.get(TEST_SUPABASE_ANON_KEY_VAR)
    if not key:
        _missing_config(TEST_SUPABASE_ANON_KEY_VAR, _SKIP_SUPABASE_ANON_REASON)
    assert key is not None
    return key


@pytest.fixture
def pg_conn() -> Iterator[psycopg.Connection]:
    """A raw psycopg connection to the test database, isolated per test.

    ``psycopg`` opens an implicit transaction on first statement
    (autocommit is off by default); this fixture unconditionally rolls
    that transaction back at teardown regardless of test outcome, so
    every raw-SQL test (constraints, transactions/rollback, schema
    introspection) is fully isolated and leaves the test database
    exactly as it found it — no cleanup logic is ever needed for tests
    that use only this fixture.
    """
    url = _test_database_url()
    conn = psycopg.connect(url)
    try:
        yield conn
    finally:
        conn.rollback()
        conn.close()


@pytest.fixture(scope="session")
def test_supabase_settings() -> SupabaseConnectionSettings:
    """The test project's full connection settings, including its real
    anon key — required for anything that signs in as an ordinary user
    (``make_authenticated_user`` below) rather than only ever using the
    service-role key, which is all ``supabase_service_client`` needs.
    """
    url, service_role_key = _test_supabase_credentials()
    anon_key = _test_supabase_anon_key()
    return SupabaseConnectionSettings(
        url=url, anon_key=anon_key, service_role_key=service_role_key
    )


@pytest.fixture(scope="session")
def supabase_service_client(
    test_supabase_settings: SupabaseConnectionSettings,
) -> SupabaseDatabaseClient:
    """A real service-role Supabase client pointed at the test project."""
    return SupabaseClientFactory.create_service_role_client(test_supabase_settings)


@pytest.fixture(scope="session")
def _committing_pg_conn() -> Iterator[psycopg.Connection]:
    """A session-scoped, autocommitting psycopg connection, used only for
    cross-table cleanup after tests that create real, committed rows via
    the Supabase REST API (which has no concept of an ambient client-side
    transaction — every ``.execute()`` call is independently committed).
    """
    url = _test_database_url()
    conn = psycopg.connect(url, autocommit=True)
    try:
        yield conn
    finally:
        conn.close()


@pytest.fixture(scope="session")
def test_company_id(_committing_pg_conn: psycopg.Connection) -> uuid.UUID:
    """The single company (tenant) every integration-test profile is
    provisioned into, per the multi-tenancy conversion's ``company_id``
    requirement on ``profiles``/``handle_new_user()`` (migrations 0009-0011).

    Session-scoped and idempotent (``on conflict (slug) do update``) so
    repeated test runs against a persistent test database reuse the same
    row rather than accumulating one company per run.
    """
    with _committing_pg_conn.cursor() as cur:
        cur.execute(
            "insert into public.companies (name, slug) "
            "values ('Integration Test Company', 'integration-test-company') "
            "on conflict (slug) do update set name = excluded.name "
            "returning id;"
        )
        row = cur.fetchone()
    assert row is not None
    return uuid.UUID(str(row[0]))


def _cleanup_profiles(
    committing_conn: psycopg.Connection,
    supabase_service_client: SupabaseDatabaseClient,
    profile_ids: list[uuid.UUID],
) -> None:
    """Remove every row a test created that is (transitively) owned by
    the given profile ids, in FK-safe order, then delete the underlying
    ``auth.users`` rows (cascading ``profiles`` automatically).

    Necessary because ``audit_logs`` (immutable, insert-only by design)
    and ``workflow_definitions`` (``created_by`` is ``ON DELETE
    RESTRICT``) are never cleaned up by cascade, and the Repository
    Layer deliberately exposes no delete method for either — this
    cleanup therefore goes around the Repository Layer entirely, via a
    direct superuser connection, exactly as a human operator resetting a
    test database would.
    """
    if not profile_ids:
        return
    ids = [str(i) for i in profile_ids]
    with committing_conn.cursor() as cur:
        cur.execute(
            "delete from public.audit_logs "
            "where actor_id = any(%s) or request_id in "
            "(select id from public.requests where requester_id = any(%s));",
            (ids, ids),
        )
        cur.execute("delete from public.notifications where recipient_id = any(%s);", (ids,))
        # Cascades workflow_stages, comments, and attachments belonging to these requests.
        cur.execute("delete from public.requests where requester_id = any(%s);", (ids,))
        cur.execute("delete from public.workflow_definitions where created_by = any(%s);", (ids,))
    for profile_id in profile_ids:
        with contextlib.suppress(Exception):  # best-effort cleanup must not fail the test
            supabase_service_client.auth.admin.delete_user(str(profile_id))


@pytest.fixture
def make_test_profile(supabase_service_client, _committing_pg_conn, test_company_id):
    """Factory fixture: provision a *real* ``auth.users``/``profiles`` row
    pair through the same Supabase Admin Auth API path production uses
    (``on_auth_user_created``, migration 0002), and guarantee its full
    removal — across every table it may end up referenced from — at
    teardown, regardless of what the test did with it.

    Returns:
        A callable ``(*, role, full_name, department=None) -> ProfileRecord``.
    """
    created_ids: list[uuid.UUID] = []
    profile_repo = ProfileRepository(supabase_service_client, always_use_injected_client=True)

    def _make(
        *,
        role: UserRole = UserRole.EMPLOYEE,
        full_name: str = "Integration Test User",
        department: str | None = None,
    ) -> ProfileRecord:
        unique = uuid.uuid4().hex[:12]
        email = f"itest.{unique}@example.invalid"
        response = supabase_service_client.auth.admin.create_user(
            {
                "email": email,
                "password": f"Itest!{unique}A1",
                "email_confirm": True,
                "user_metadata": {
                    "full_name": full_name,
                    "role": role.value,
                    "company_id": str(test_company_id),
                },
            }
        )
        user_id = uuid.UUID(str(response.user.id))
        created_ids.append(user_id)

        profile = profile_repo.get_by_id(user_id)
        if profile.department != department:
            profile = profile_repo.update_profile(
                user_id, expected_version=profile.version, department=department
            )
        return profile

    yield _make

    _cleanup_profiles(_committing_pg_conn, supabase_service_client, created_ids)


@pytest.fixture
def make_authenticated_user(
    supabase_service_client, test_supabase_settings, _committing_pg_conn, test_company_id
):
    """Factory fixture: provision a real ``auth.users``/``profiles`` row
    pair, like ``make_test_profile``, but additionally return a callable
    that signs in as that user for real (``auth.sign_in_with_password``
    against the anon-key client) and hands back a genuinely RLS-enforcing
    ``SupabaseDatabaseClient`` bound to their access token
    (``SupabaseClientFactory.create_user_scoped_client``) — the exact
    mechanism ``app.api.dependencies.bind_tenant_database_client`` uses
    for every real request, per docs/tenant_isolation.md.

    This is what closes that document's own disclosed gap ("A live-
    Postgres integration test proving RLS actually blocks a cross-tenant
    read under a real user JWT... needs a new signed-in-user fixture");
    kept separate from ``make_test_profile`` (rather than adding a
    sign-in callable to every caller of that fixture) since most existing
    integration tests have no use for a real session and only pay for
    Admin Auth API calls they already make.

    Returns:
        A callable ``(*, role, full_name) -> (ProfileRecord, sign_in)``,
        where ``sign_in() -> SupabaseDatabaseClient`` establishes a fresh,
        real session on each call (mirroring ``create_user_scoped_client``'s
        own per-call-not-shared contract).
    """
    created_ids: list[uuid.UUID] = []
    profile_repo = ProfileRepository(supabase_service_client, always_use_injected_client=True)

    def _make(
        *, role: UserRole = UserRole.EMPLOYEE, full_name: str = "Integration Test User"
    ) -> tuple[ProfileRecord, Any]:
        unique = uuid.uuid4().hex[:12]
        email = f"itest.rls.{unique}@example.invalid"
        password = f"Itest!{unique}A1"
        response = supabase_service_client.auth.admin.create_user(
            {
                "email": email,
                "password": password,
                "email_confirm": True,
                "user_metadata": {
                    "full_name": full_name,
                    "role": role.value,
                    "company_id": str(test_company_id),
                },
            }
        )
        user_id = uuid.UUID(str(response.user.id))
        created_ids.append(user_id)
        profile = profile_repo.get_by_id(user_id)

        def _sign_in() -> SupabaseDatabaseClient:
            anon_client = SupabaseClientFactory.create_anon_client(test_supabase_settings)
            session = anon_client.auth.sign_in_with_password(
                {"email": email, "password": password}
            )
            assert session.session is not None
            return SupabaseClientFactory.create_user_scoped_client(
                test_supabase_settings, session.session.access_token
            )

        return profile, _sign_in

    yield _make

    _cleanup_profiles(_committing_pg_conn, supabase_service_client, created_ids)


@pytest.fixture(scope="session")
def anchor_profile_id(supabase_service_client, test_company_id) -> Iterator[uuid.UUID]:
    """The id of a real, valid ``profiles`` row usable as an FK anchor by
    raw-SQL tests that need *some* valid profile id but do not care which
    one — created once per session (never inside an already-open
    ``pg_tx``, and cleaned up at session end) rather than per test, since
    every ``pg_tx``-based test rolls its own transaction back and never
    persists a reference to it anyway.
    """
    profile_repo = ProfileRepository(supabase_service_client, always_use_injected_client=True)
    unique = uuid.uuid4().hex[:12]
    email = f"itest.anchor.{unique}@example.invalid"
    response = supabase_service_client.auth.admin.create_user(
        {
            "email": email,
            "password": f"Itest!{unique}A1",
            "email_confirm": True,
            # company_id is mandatory, not decorative: handle_new_user()
            # (migration 0011) provisions the profiles row from this
            # metadata and reads company_id straight out of it, with no
            # fallback, while profiles.company_id has been NOT NULL since
            # 0010. Omitting it makes the trigger raise, which surfaces
            # from GoTrue as an opaque 500 "Database error creating new
            # user" — and because this fixture is session-scoped, that
            # single failure errors every test that depends on it.
            "user_metadata": {
                "full_name": "Anchor Profile",
                "role": "admin",
                "company_id": str(test_company_id),
            },
        }
    )
    user_id = uuid.UUID(str(response.user.id))
    # Confirm the trigger provisioned the profile before handing the id out.
    profile_repo.get_by_id(user_id)

    yield user_id

    with contextlib.suppress(Exception):  # best-effort session-end cleanup
        supabase_service_client.auth.admin.delete_user(str(user_id))


@pytest.fixture
def make_test_company(supabase_service_client, _committing_pg_conn: psycopg.Connection):
    """Factory fixture: create a company row and guarantee its removal
    at teardown.

    ``companies`` is never cascade-deleted from anything else this
    suite's other fixtures clean up (it is the parent, not a child, of
    ``profiles``), so this fixture owns its own cleanup, mirroring
    ``make_test_job``'s pattern. ``company_licenses`` cascades
    automatically (``on delete cascade``).
    """
    created_ids: list[uuid.UUID] = []
    company_repo = CompanyRepository(supabase_service_client, always_use_injected_client=True)

    def _make(*, name: str = "Integration Test Co"):
        unique = uuid.uuid4().hex[:8]
        company = company_repo.create_company(name=name, slug=f"itest-{unique}")
        created_ids.append(company.id)
        return company

    yield _make

    if created_ids:
        with _committing_pg_conn.cursor() as cur:
            cur.execute(
                "delete from public.companies where id = any(%s);",
                ([str(i) for i in created_ids],),
            )


@pytest.fixture
def real_repos(supabase_service_client):
    """A plain namespace of every real repository, constructed against
    the test project's service-role client.
    """

    # Every repository here is constructed with always_use_injected_client=True
    # regardless of that repository's real, app-wired choice
    # (app.bootstrap) — this fixture's whole purpose is deterministic,
    # full-access setup/verification against the test project's
    # service-role client, not exercising the per-request RLS-enforcing
    # path (that is covered separately; see docs/tenant_isolation.md).
    class RealRepos:
        profile = ProfileRepository(supabase_service_client, always_use_injected_client=True)
        request = RequestRepository(supabase_service_client, always_use_injected_client=True)
        workflow_definition = WorkflowDefinitionRepository(
            supabase_service_client, always_use_injected_client=True
        )
        workflow_stage = WorkflowStageRepository(
            supabase_service_client, always_use_injected_client=True
        )
        approval = ApprovalRepository(supabase_service_client, always_use_injected_client=True)
        audit = AuditRepository(supabase_service_client, always_use_injected_client=True)
        notification = NotificationRepository(
            supabase_service_client, always_use_injected_client=True
        )
        notification_preference = NotificationPreferenceRepository(
            supabase_service_client, always_use_injected_client=True
        )
        comment = CommentRepository(supabase_service_client, always_use_injected_client=True)
        attachment = AttachmentRepository(supabase_service_client, always_use_injected_client=True)
        invitation = InvitationRepository(supabase_service_client, always_use_injected_client=True)
        job = JobRepository(supabase_service_client, always_use_injected_client=True)
        company = CompanyRepository(supabase_service_client, always_use_injected_client=True)
        company_license = CompanyLicenseRepository(
            supabase_service_client, always_use_injected_client=True
        )
        feature_flag = FeatureFlagRepository(
            supabase_service_client, always_use_injected_client=True
        )
        analytics = AnalyticsRepository(supabase_service_client, always_use_injected_client=True)

    return RealRepos()
