import { expect, test } from "@playwright/test";

import { corruptSessionCookie, loginViaUi } from "../fixtures/auth-helpers";
import { ACME_EMPLOYEE, ACME_SESSION_TESTER, authStateFile } from "../fixtures/test-users";

test.describe("signed in", () => {
  test.use({ storageState: authStateFile(ACME_EMPLOYEE) });

  test("an unknown route renders the 404 page", async ({ page }) => {
    await page.goto("/this-route-does-not-exist");
    await expect(page.getByText("404")).toBeVisible();
    await expect(page.getByText(/doesn.t exist/i)).toBeVisible();
  });

  test("submitting the new-request form with missing fields shows inline errors", async ({
    page,
  }) => {
    await page.goto("/requests/new");
    await page.getByRole("button", { name: "Create request" }).click();

    // Target the field's own error node by id (request-form.tsx wires it
    // through aria-describedby). "Select a request type" is also the
    // Select's placeholder, so matching on text alone resolves to both the
    // placeholder and the validation message.
    await expect(page.locator("#request_type-error")).toHaveText("Select a request type");
    await expect(page.locator("#title-error")).toHaveText("Title is required");
    await expect(page).toHaveURL(/\/requests\/new$/);
  });

  test("a backend 500 surfaces an error state with a working retry, not a blank page", async ({
    page,
  }) => {
    // Two, not one: createQueryClient sets `retry: 1`, so a failed query
    // is automatically retried once before it is ever reported as an
    // error. Failing a single request meant that retry reached the real
    // backend, succeeded, and the error state this test exists to check
    // never rendered. Failing both attempts lets the query settle as an
    // error; everything after — including the manual Retry click below —
    // then passes through to the real endpoint.
    let failuresRemaining = 2;
    await page.route("**/api/v1/dashboard-summary*", async (route) => {
      if (failuresRemaining > 0) {
        failuresRemaining -= 1;
        await route.fulfill({
          status: 500,
          contentType: "application/json",
          body: JSON.stringify({ error: { code: "INTERNAL_ERROR", message: "boom" } }),
        });
        return;
      }
      await route.continue();
    });

    await page.goto("/dashboard");
    await expect(page.getByText("Couldn't load your dashboard.")).toBeVisible();

    // Scope the click to the KPI row's own ErrorState. A failed
    // dashboard-summary query renders several of the page's five
    // ErrorStates at once, each with its own Retry button, so an unscoped
    // getByRole resolves to more than one. The message <p> and the button
    // are siblings inside one ErrorState container, so stepping up from
    // the message picks exactly the right Retry.
    await page
      .getByText("Couldn't load your dashboard.")
      .locator("..")
      .getByRole("button", { name: "Retry" })
      .click();
    // Exact: PageHeader's description contains "open requests", so the
    // loose form would report success without a KPI tile ever appearing.
    await expect(page.getByText("Open requests", { exact: true })).toBeVisible();
    await expect(page.getByText("Couldn't load your dashboard.")).not.toBeVisible();
  });
});

test("a dead session hitting a protected page redirects to /login instead of erroring silently", async ({
  page,
}) => {
  // The session-lifecycle persona, not ACME_EMPLOYEE: this test signs in
  // for real and then breaks that session, so it stays clear of the
  // storageState the specs above depend on.
  await loginViaUi(page, ACME_SESSION_TESTER);
  await corruptSessionCookie(page);
  // A middleware redirect that lands while the navigation is still in
  // flight surfaces as net::ERR_ABORTED: the navigation was superseded,
  // not failed. That raced intermittently and made this test flaky. The
  // URL assertion below is what actually decides the outcome, so an
  // aborted goto is tolerated rather than thrown.
  await page.goto("/dashboard").catch(() => {});
  await expect(page).toHaveURL(/\/login$/);
});
