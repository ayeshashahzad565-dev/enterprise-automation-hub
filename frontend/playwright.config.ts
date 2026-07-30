import path from "node:path";
import { defineConfig, devices } from "@playwright/test";

/**
 * Both the frontend (`supabase.auth.signInWithPassword`) and the backend
 * (`SupabaseTokenVerifier`) delegate authentication to a real Supabase
 * project — there is no local-JWT-secret shortcut this suite can use
 * instead. Locally and in CI alike, this suite is meant to run against a
 * real, ephemeral local Supabase stack (`supabase start`, see
 * `supabase/config.toml` and `frontend/e2e/README.md`), migrated
 * (`alembic upgrade head`) and seeded (`python
 * scripts/seed_e2e_fixtures.py`) *before* `npx playwright test` runs.
 *
 * `webServer` below boots the two remaining dependencies itself — the
 * FastAPI backend and the built Next.js frontend — so the single command
 * `npx playwright test` is everything both a developer and CI need to
 * run, once the Supabase stack is up and seeded.
 */
const repoRoot = path.resolve(__dirname, "..");
const isCI = Boolean(process.env.CI);

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: isCI,
  retries: isCI ? 2 : 0,
  workers: isCI ? 2 : undefined,
  reporter: isCI ? [["html", { open: "never" }], ["github"]] : "list",
  timeout: 30_000,
  use: {
    baseURL: "http://localhost:3000",
    trace: "on-first-retry",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },
  projects: [
    {
      name: "setup",
      testMatch: /.*\.setup\.ts/,
    },
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
      dependencies: ["setup"],
    },
  ],
  webServer: [
    {
      command:
        "uvicorn app.api.main:create_app --factory --host 0.0.0.0 --port 8000",
      cwd: repoRoot,
      // /health/live is the pure liveness check (never depends on
      // Supabase/DB reachability, app/api/routers/health.py) — the right
      // readiness probe for "has uvicorn finished starting," as opposed
      // to "is every downstream dependency already reachable."
      url: "http://localhost:8000/api/v1/health/live",
      reuseExistingServer: !isCI,
      timeout: 60_000,
      stdout: "pipe",
      stderr: "pipe",
    },
    {
      // A production build, not `next dev` — this suite is meant to
      // exercise the same artifact CI/CD actually ships
      // (docker_deployment.md's build), not the dev server's extra
      // overlay/fast-refresh behavior.
      command: "npm run build && npm run start",
      url: "http://localhost:3000/login",
      reuseExistingServer: !isCI,
      timeout: 180_000,
      stdout: "pipe",
      stderr: "pipe",
    },
  ],
});
