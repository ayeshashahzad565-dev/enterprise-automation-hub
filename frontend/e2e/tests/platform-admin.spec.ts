import { expect, test } from "@playwright/test";

import { ACME_ADMIN, PLATFORM_ADMIN, authStateFile } from "../fixtures/test-users";

test.describe("platform admin", () => {
  test.use({ storageState: authStateFile(PLATFORM_ADMIN) });

  test("sees every seeded company and can open one's detail", async ({ page }) => {
    await page.goto("/platform/companies");

    await expect(page.getByRole("row").filter({ hasText: "Acme Corp" })).toBeVisible();
    await expect(page.getByRole("row").filter({ hasText: "Globex Inc" })).toBeVisible();

    await page.getByRole("row").filter({ hasText: "Acme Corp" }).click();
    await expect(page).toHaveURL(/\/platform\/companies\/[0-9a-f-]+$/);
    await expect(page.getByRole("heading", { name: "Acme Corp" })).toBeVisible();
  });
});

test.describe("ordinary company admin", () => {
  test.use({ storageState: authStateFile(ACME_ADMIN) });

  test("is denied Platform Administration entirely", async ({ page }) => {
    // is_platform_admin is orthogonal to role (Profile.is_platform_admin) —
    // an ordinary company admin, however privileged within their own
    // tenant, must be redirected away by platform/layout.tsx's guard.
    await page.goto("/platform/companies");
    await expect(page).toHaveURL(/\/unauthorized$/);
  });
});
