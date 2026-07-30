import type { Page } from "@playwright/test";

import type { TestUser } from "./test-users";

/** Logs in through the real UI form — used only by the specs that test the login flow itself. */
export async function loginViaUi(page: Page, user: TestUser): Promise<void> {
  await page.goto("/login");
  await page.getByLabel("Email").fill(user.email);
  await page.getByLabel("Password").fill(user.password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.waitForURL("**/dashboard");
}

/**
 * Corrupts the Supabase session cookie in place, simulating an expired
 * access token whose refresh also fails — deterministic, with no need to
 * wait out a real JWT's TTL. `@supabase/ssr` stores the session as one or
 * more `sb-<project-ref>-auth-token[.N]` cookies; overwriting every
 * matching cookie's value with invalid JSON is what makes both
 * `supabase.auth.getUser()` (server middleware) and a client-side
 * `getSession()`/`refreshSession()` call fail, exercising the same "dead
 * session" path a genuinely expired-and-unrefreshable token would.
 */
export async function corruptSessionCookie(page: Page): Promise<void> {
  const context = page.context();
  const cookies = await context.cookies();
  const sessionCookies = cookies.filter((cookie) => /^sb-.*-auth-token/.test(cookie.name));
  await context.addCookies(
    sessionCookies.map((cookie) => ({
      ...cookie,
      value: "corrupted-not-valid-session-data",
    })),
  );
}
