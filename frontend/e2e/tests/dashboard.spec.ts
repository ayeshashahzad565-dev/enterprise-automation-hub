import { expect, test } from "@playwright/test";

import { ACME_APPROVER, ACME_EMPLOYEE, authStateFile } from "../fixtures/test-users";

test.describe("employee dashboard", () => {
  test.use({ storageState: authStateFile(ACME_EMPLOYEE) });

  test("shows the employee's own KPIs and recent requests, no approval widgets", async ({
    page,
  }) => {
    await page.goto("/dashboard");

    await expect(page.getByText("Open requests")).toBeVisible();
    await expect(page.getByText("Unread notifications")).toBeVisible();
    // canApprove-gated KPIs/widgets (dashboard/page.tsx) must not render
    // for an employee — this is the exact distinction dashboard/page.tsx's
    // `canApprove` branch exists to enforce.
    await expect(page.getByText("Pending approvals")).not.toBeVisible();
    await expect(page.getByText("Needs your review")).not.toBeVisible();
    await expect(page.getByText("Workflow health")).not.toBeVisible();
  });
});

test.describe("approver dashboard", () => {
  test.use({ storageState: authStateFile(ACME_APPROVER) });

  test("shows the extra approval-related KPIs and widgets", async ({ page }) => {
    await page.goto("/dashboard");

    await expect(page.getByText("Open requests")).toBeVisible();
    await expect(page.getByText("Pending approvals")).toBeVisible();
    await expect(page.getByText("Needs your review")).toBeVisible();
    await expect(page.getByText("Workflow health")).toBeVisible();
  });
});
