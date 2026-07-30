/**
 * Must be kept in sync with `scripts/seed_e2e_fixtures.py` — every email
 * below is a fixed, disposable persona that script creates against the
 * local Supabase stack `frontend/e2e/README.md` documents how to run.
 */

export const PASSWORD = "E2eTest123!";

export interface TestUser {
  /** Also used as the persona's storageState filename stem (e2e/.auth/<persona>.json). */
  persona: string;
  email: string;
  password: string;
  company: "acme" | "globex";
}

export const ACME_EMPLOYEE: TestUser = {
  persona: "acme-employee",
  email: "e2e.acme.employee@example.invalid",
  password: PASSWORD,
  company: "acme",
};

export const ACME_APPROVER: TestUser = {
  persona: "acme-approver",
  email: "e2e.acme.approver@example.invalid",
  password: PASSWORD,
  company: "acme",
};

export const ACME_ADMIN: TestUser = {
  persona: "acme-admin",
  email: "e2e.acme.admin@example.invalid",
  password: PASSWORD,
  company: "acme",
};

export const PLATFORM_ADMIN: TestUser = {
  persona: "platform-admin",
  email: "e2e.platform.admin@example.invalid",
  password: PASSWORD,
  company: "acme",
};

export const GLOBEX_EMPLOYEE: TestUser = {
  persona: "globex-employee",
  email: "e2e.globex.employee@example.invalid",
  password: PASSWORD,
  company: "globex",
};

export const GLOBEX_APPROVER: TestUser = {
  persona: "globex-approver",
  email: "e2e.globex.approver@example.invalid",
  password: PASSWORD,
  company: "globex",
};

export const ALL_TEST_USERS: readonly TestUser[] = [
  ACME_EMPLOYEE,
  ACME_APPROVER,
  ACME_ADMIN,
  PLATFORM_ADMIN,
  GLOBEX_EMPLOYEE,
  GLOBEX_APPROVER,
];

/** Path to a persona's saved storageState, produced by `e2e/setup/auth.setup.ts`. */
export function authStateFile(user: TestUser): string {
  return `e2e/.auth/${user.persona}.json`;
}
