import { expect, test } from "@playwright/test";

import { ACME_EMPLOYEE, authStateFile } from "../fixtures/test-users";

test.use({ storageState: authStateFile(ACME_EMPLOYEE) });

test("an employee can submit a new leave request", async ({ page }) => {
  const title = `E2E leave request ${Date.now()}`;

  await page.goto("/requests/new");
  await page.getByLabel("Request type").click();
  await page.getByRole("option", { name: "Leave" }).click();
  await page.getByLabel("Title").fill(title);
  await page.getByLabel("Description").fill("Submitted by the Playwright E2E suite.");
  await page.getByRole("button", { name: "Create request" }).click();

  await expect(page).toHaveURL(/\/requests\/[0-9a-f-]+$/);
  await expect(page.getByText(title)).toBeVisible();
  await expect(page.getByText("Pending", { exact: true })).toBeVisible();

  await page.goto("/requests");
  await expect(page.getByRole("link", { name: title })).toBeVisible();
});
