import { expect, test } from "@playwright/test";

import { corruptSessionCookie, loginViaUi } from "../fixtures/auth-helpers";
import { ACME_SESSION_TESTER } from "../fixtures/test-users";

// No stored storageState — starts from a real, freshly-established login
// so the corrupted-cookie step below is the only deliberately broken part.

test("a dead session redirects to /login on the next protected navigation", async ({ page }) => {
  await loginViaUi(page, ACME_SESSION_TESTER);

  await corruptSessionCookie(page);

  // middleware.ts's updateSession calls supabase.auth.getUser() on every
  // request to a protected route; a session that can neither be trusted
  // nor refreshed must redirect to /login rather than rendering the page
  // (or, worse, a stale "still logged in" shell with failing API calls).
  // Tolerates net::ERR_ABORTED for the same reason as error-handling.spec's
  // dead-session test: the middleware redirect can supersede this
  // navigation mid-flight. The URL assertion is the real check.
  await page.goto("/requests").catch(() => {});
  await expect(page).toHaveURL(/\/login$/);
});

test("a dead session also redirects on a client-side (soft) navigation, not just a full reload", async ({
  page,
}) => {
  await loginViaUi(page, ACME_SESSION_TESTER);
  await page.goto("/dashboard");
  await expect(page.getByRole("heading", { name: /welcome back|dashboard/i })).toBeVisible();

  await corruptSessionCookie(page);

  // Next.js's App Router still fetches the target route's data from the
  // server on a same-tab <Link> click, so middleware.ts's updateSession
  // check applies here too — this asserts that path is equally enforced,
  // not just a hard page load (test above).
  await page.getByRole("link", { name: "Requests", exact: true }).click();
  await expect(page).toHaveURL(/\/login$/, { timeout: 15_000 });
});
