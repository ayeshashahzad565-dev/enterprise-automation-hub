# tests/integration

Real-database tests: repository CRUD, foreign key/unique/check
constraints, transactions and rollback, optimistic locking, and
workflow/audit/notification persistence — all run against an actual
migrated Postgres/Supabase database, never the in-memory fakes used by
`tests/unit`, `tests/acceptance`, `tests/security`, and
`tests/performance`.

## Setup: a dedicated test database

**Never point this suite at the production project.** Several tests
deliberately trigger constraint violations and perform real deletes.

1. Create a separate Supabase project (the free tier is sufficient).
   This must be a real Supabase project (hosted, or the local Supabase
   CLI/Docker stack) rather than a vanilla Postgres instance: migration
   `0002_auth_profile_trigger` attaches a trigger to `auth.users`, and
   `profiles.id` has a foreign key to it — both require Supabase Auth's
   (GoTrue's) `auth` schema to already exist.
2. Apply this project's full migration history to it:
   ```
   TEST_DATABASE_URL=postgresql://postgres:<password>@<test-project-host>:5432/postgres \
     DATABASE_URL=$TEST_DATABASE_URL alembic upgrade head
   ```
   (Alembic reads `DATABASE_URL`; the export above just aliases your test
   connection string into the variable it looks for, without touching
   your real `.env`.)
3. Set the following environment variables before running this suite
   (e.g. in a `.env.test` file, loaded however you prefer — this suite
   does not load one automatically):

   | Variable                          | Where to find it                                            |
   |------------------------------------|--------------------------------------------------------------|
   | `TEST_DATABASE_URL`                | Test project's Database Settings → Connection string          |
   | `TEST_SUPABASE_URL`                | Test project's API Settings → Project URL                     |
   | `TEST_SUPABASE_ANON_KEY`           | Test project's API Settings → `anon`/`public` key              |
   | `TEST_SUPABASE_SERVICE_ROLE_KEY`   | Test project's API Settings → `service_role` secret            |

## Running

```
pytest tests/integration
```

Locally (no `CI` environment variable set), every fixture in
`tests/integration/conftest.py` skips — never fails — if these variables
are absent, so `pytest` (no args) and the rest of the suite remain fully
runnable with no test database configured at all.

**In CI, this behavior is deliberately different: missing variables fail
the job instead of skipping it.** `conftest.py`'s `_running_in_ci()`
checks the same ambient `CI=true` every CI provider sets, and
`_missing_config()` calls `pytest.fail(...)` rather than `pytest.skip(...)`
whenever it's true. This exists specifically so a broken CI step (a
typo'd variable name, a Supabase start step that silently exits 0 without
actually being ready) cannot make this suite silently pass by skipping
every single test — before this guard existed, that's exactly what a
misconfigured CI job would do: report green while asserting nothing.

## Running in CI

`.github/workflows/integration.yml` runs this suite automatically on
every push/PR to `main`, against a real, ephemeral **local Supabase CLI**
stack — the same infrastructure `.github/workflows/e2e.yml` already uses,
and for the same reason: this project's `auth.users` trigger (migration
`0002`) and every RLS policy this suite exercises need Supabase Auth's
actual `auth` schema, which a vanilla `postgres:16` GitHub Actions
service container does not provide. No hosted project, no secrets — the
workflow starts the stack, exports its fixed local dev keys as this
suite's `TEST_*` variables, runs `alembic upgrade head` (which is what
actually creates every RLS policy tested here), then runs
`pytest tests/integration`.

`.github/workflows/ci.yml`'s own `pytest` step (the fast lint/typecheck/unit-test
job) deliberately excludes this suite (`pytest -m "not integration"`) —
ownership of provisioning a real database belongs only to this dedicated,
heavier job, matching how `e2e.yml` is already kept separate from `ci.yml`
for the same reason (Playwright's own dependency install and multi-server
boot).

## Isolation model

- **Schema/constraint/transaction tests** (`test_schema_constraints.py`)
  run inside a single psycopg transaction per test (`pg_conn` fixture)
  that is unconditionally rolled back at teardown — nothing they do ever
  persists, so they need no cleanup logic of their own.
- **Repository-level tests** (CRUD, workflow/audit/notification
  persistence, optimistic locking) go through the real
  `supabase-py`/`postgrest` REST API, which has no ambient
  client-side transaction — every `.execute()` call commits
  independently. These tests use the `make_test_profile` fixture, which
  provisions a real `auth.users`/`profiles` row pair through the same
  Admin Auth API path production uses, and guarantees its complete
  removal (across `audit_logs`, `notifications`, `requests`,
  `workflow_definitions`, and finally the `auth.users` row itself, in
  foreign-key-safe order) at teardown regardless of test outcome.
- **Row-Level Security policy tests** come in two flavors:
  - `TestRowLevelSecurity` in `test_invitation_persistence.py` simulates
    an authenticated caller via raw SQL (`SET LOCAL ROLE authenticated`
    + `request.jwt.claims`) on the shared `pg_conn` transaction — the
    standard technique for exercising Postgres RLS without a real
    PostgREST request.
  - `test_rls_enforcement.py` instead signs in as a real user
    (`auth.sign_in_with_password`) via the `make_authenticated_user`
    fixture and issues requests through
    `SupabaseClientFactory.create_user_scoped_client` — the same
    mechanism `app.api.dependencies.bind_tenant_database_client` binds
    for every real authenticated request. This is the closer-to-production
    proof that a given RLS policy (today: `notification_preferences`)
    actually blocks a cross-user read/write under a genuine JWT, not a
    simulated role/claim.
