# frontend/e2e

Playwright end-to-end suite covering login/logout, session expiry,
submitting/approving/rejecting requests, the dashboard, analytics,
Platform Administration, tenant isolation, and error handling — against
the real, running application (frontend + backend), never mocks.

Both the frontend (`supabase.auth.signInWithPassword`) and the backend
(`SupabaseTokenVerifier`) delegate authentication to a real Supabase
project, so this suite runs against a real, ephemeral **local** Supabase
stack via the [Supabase CLI](https://supabase.com/docs/guides/cli),
never a hosted project. `.github/workflows/e2e.yml` does exactly the
steps below in CI; running them locally reproduces that job.

## Running locally

From the repository root:

```bash
# 1. Start the local Supabase stack (Postgres + Auth + API gateway).
#    Prints fixed local dev keys — never secrets, only ever valid
#    against this ephemeral local instance.
supabase start

# 2. Export its connection details into the shape this repo's backend
#    (app/config/settings.py) and frontend (lib/supabase/env.ts) expect.
eval "$(supabase status -o env | sed 's/^/export /')"
export SUPABASE_URL="$API_URL"
export SUPABASE_ANON_KEY="$ANON_KEY"
export SUPABASE_SERVICE_ROLE_KEY="$SERVICE_ROLE_KEY"
export DATABASE_URL="$DB_URL"
export NEXT_PUBLIC_SUPABASE_URL="$API_URL"
export NEXT_PUBLIC_SUPABASE_ANON_KEY="$ANON_KEY"
export NEXT_PUBLIC_API_BASE_URL="http://localhost:8000/api/v1"
export APP_ENVIRONMENT=testing

# 3. Apply migrations and seed the suite's fixed test personas/companies.
alembic upgrade head
python scripts/seed_e2e_fixtures.py

# 4. Run the suite. playwright.config.ts's `webServer` boots the backend
#    (uvicorn) and frontend (a production build + `next start`) itself —
#    this is the only remaining command.
cd frontend
npx playwright install --with-deps chromium   # first run only
npx playwright test
```

Useful variants:

- `npx playwright test --ui` — interactive UI mode.
- `npx playwright show-report` — open the last HTML report.
- `python scripts/seed_e2e_fixtures.py` is idempotent — safe to re-run
  against the same stack without duplicating companies/users.

## Structure

- `e2e/setup/auth.setup.ts` — Playwright's standard "authenticate once
  per persona" setup project; saves each persona's `storageState` to
  `e2e/.auth/<persona>.json` (git-ignored — live session tokens).
- `e2e/fixtures/test-users.ts` — the fixed personas/companies, kept in
  sync with `scripts/seed_e2e_fixtures.py`.
- `e2e/fixtures/auth-helpers.ts` — interactive login and the
  corrupted-session-cookie helper used by the login/logout/session-expiry
  specs (the only specs that don't reuse a saved `storageState`).
- `e2e/tests/*.spec.ts` — one file per feature area (see each file's own
  description).

## Why a local Supabase stack, not a hosted project or mocked auth

See `playwright.config.ts`'s and `scripts/seed_e2e_fixtures.py`'s own
header comments for the full reasoning: mocking Supabase Auth away would
mean the login/logout/session-expiry specs never exercise the real
integration, and a hosted test project would need externally-managed
secrets and risks state leaking between runs. The local CLI stack is
real, ephemeral, and needs zero secrets.
