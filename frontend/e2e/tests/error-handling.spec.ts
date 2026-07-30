import { expect, test } from "@playwright/test";

import { corruptSessionCookie, loginViaUi } from "../fixtures/auth-helpers";
import { ACME_EMPLOYEE, authStateFile } from "../fixtures/test-users";

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

    await expect(page.getByText("Select a request type")).toBeVisible();
    await expect(page.getByText("Title is required")).toBeVisible();
    await expect(page).toHaveURL(/\/requests\/new$/);
  });

  test("a backend 500 surfaces an error state with a working retry, not a blank page", async ({
    page,
  }) => {
    let failNext = true;
    await page.route("**/api/v1/dashboard-summary*", async (route) => {
      if (failNext) {
        failNext = false;
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

    await page.getByRole("button", { name: "Retry" }).click();
    await expect(page.getByText("Open requests")).toBeVisible();
    await expect(page.getByText("Couldn't load your dashboard.")).not.toBeVisible();
  });
});

test("a dead session hitting a protected page redirects to /login instead of erroring silently", async ({
  page,
}) => {
  await loginViaUi(page, ACME_EMPLOYEE);
  await corruptSessionCookie(page);
  await page.goto("/dashboard");
  await expect(page).toHaveURL(/\/login$/);
});
