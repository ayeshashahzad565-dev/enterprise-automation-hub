import { expect, test } from "@playwright/test";

import { loginViaUi } from "../fixtures/auth-helpers";
import { ACME_SESSION_TESTER } from "../fixtures/test-users";

// Deliberately no `test.use({ storageState })` here — every test in this
// file starts from a genuinely signed-out browser context, since the
// login/logout flow itself is what's under test.

test.describe("login", () => {
  test("valid credentials redirect to the dashboard", async ({ page }) => {
    await loginViaUi(page, ACME_SESSION_TESTER);
    await expect(page).toHaveURL(/\/dashboard$/);
  });

  test("invalid credentials show an inline error and stay on /login", async ({ page }) => {
    await page.goto("/login");
    await page.getByLabel("Email").fill(ACME_SESSION_TESTER.email);
    await page.getByLabel("Password").fill("wrong-password-entirely");
    await page.getByRole("button", { name: "Sign in" }).click();

    await expect(page.getByText(/invalid login credentials/i)).toBeVisible();
    await expect(page).toHaveURL(/\/login$/);
  });

  test("visiting a protected route while signed out redirects to /login", async ({ page }) => {
    await page.goto("/dashboard");
    await expect(page).toHaveURL(/\/login$/);
  });
});

test.describe("logout", () => {
  test("signing out clears the session and protected routes redirect again", async ({ page }) => {
    await loginViaUi(page, ACME_SESSION_TESTER);

    await page.getByLabel("Account menu").click();
    await page.getByRole("menuitem", { name: "Sign out" }).click();
    await expect(page).toHaveURL(/\/login$/);

    await page.goto("/dashboard");
    await expect(page).toHaveURL(/\/login$/);
  });
});
