import { expect, test } from "@playwright/test";

import { ACME_APPROVER, ACME_EMPLOYEE, authStateFile } from "../fixtures/test-users";

test.describe("employee dashboard", () => {
  test.use({ storageState: authStateFile(ACME_EMPLOYEE) });

  test("shows the employee's own KPIs and recent requests, no approval widgets", async ({
    page,
  }) => {
    await page.goto("/dashboard");

    // `exact: true` throughout: getByText matches a case-insensitive
    // *substring* by default, and PageHeader's own description reads
    // "Your open requests, pending approvals, and recent activity at a
    // glance." That sentence contains both "open requests" and "pending
    // approvals", so the loose form matched the subtitle rather than any
    // KPI tile — making the negative assertions below impossible to
    // satisfy no matter how the page rendered. Matching the tile's exact
    // label ties each assertion to the element it is actually about.
    await expect(page.getByText("Open requests", { exact: true })).toBeVisible();
    await expect(page.getByText("Unread notifications", { exact: true })).toBeVisible();
    // canApprove-gated KPIs/widgets (dashboard/page.tsx) must not render
    // for an employee — this is the exact distinction dashboard/page.tsx's
    // `canApprove` branch exists to enforce.
    await expect(page.getByText("Pending approvals", { exact: true })).not.toBeVisible();
    await expect(page.getByText("Needs your review", { exact: true })).not.toBeVisible();
    await expect(page.getByText("Workflow health", { exact: true })).not.toBeVisible();
  });
});

test.describe("approver dashboard", () => {
  test.use({ storageState: authStateFile(ACME_APPROVER) });

  test("shows the extra approval-related KPIs and widgets", async ({ page }) => {
    await page.goto("/dashboard");

    // Exact for the same reason as the employee case above: without it
    // these four passed against PageHeader's description regardless of
    // whether a single approver KPI had rendered.
    await expect(page.getByText("Open requests", { exact: true })).toBeVisible();
    await expect(page.getByText("Pending approvals", { exact: true })).toBeVisible();
    await expect(page.getByText("Needs your review", { exact: true })).toBeVisible();
    await expect(page.getByText("Workflow health", { exact: true })).toBeVisible();
  });
});
