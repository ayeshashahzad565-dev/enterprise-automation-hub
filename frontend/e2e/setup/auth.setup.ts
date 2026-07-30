import { test as setup } from "@playwright/test";

import { ALL_TEST_USERS, authStateFile } from "../fixtures/test-users";

/**
 * Playwright's standard "authenticate once per persona" setup project
 * (this file matches playwright.config.ts's `testMatch: /.*\.setup\.ts/`
 * for the `setup` project every other project `dependencies` on). Every
 * spec file except auth.spec.ts/session-expiry.spec.ts (which test the
 * login/logout/session flows themselves) loads one of these saved
 * storageState files instead of re-authenticating through the UI.
 */
for (const user of ALL_TEST_USERS) {
  setup(`authenticate as ${user.persona}`, async ({ page }) => {
    await page.goto("/login");
    await page.getByLabel("Email").fill(user.email);
    await page.getByLabel("Password").fill(user.password);
    await page.getByRole("button", { name: "Sign in" }).click();
    await page.waitForURL("**/dashboard");
    await page.context().storageState({ path: authStateFile(user) });
  });
}
