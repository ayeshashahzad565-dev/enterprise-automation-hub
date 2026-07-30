import { expect, test } from "@playwright/test";

import { ACME_APPROVER, ACME_EMPLOYEE, authStateFile } from "../fixtures/test-users";

test.describe("employee", () => {
  test.use({ storageState: authStateFile(ACME_EMPLOYEE) });

  test("is denied analytics data (backend 403, surfaced as an error state)", async ({ page }) => {
    // No nav link for Analytics is rendered to an employee
    // (components/layout/nav-items.ts), but the route itself carries no
    // client-side redirect guard (unlike /platform, /admin) — the backend
    // rejects every query with a 403, and this asserts that rejection is
    // actually surfaced, not silently swallowed into an empty-looking page
    // (the exact failure class the analytics component audit fixed).
    await page.goto("/analytics");
    await expect(page.getByRole("button", { name: "Retry" }).first()).toBeVisible();
  });
});

test.describe("approver", () => {
  test.use({ storageState: authStateFile(ACME_APPROVER) });

  test("sees analytics panels resolve past loading, with no silent error", async ({ page }) => {
    await page.goto("/analytics");

    await expect(page.getByRole("heading", { name: "Analytics" })).toBeVisible();
    // The executive summary card resolving past its own loading/error
    // states (executive-narrative-panel.tsx) is a solid proxy for "this
    // whole tab's queries succeeded," without depending on exact chart
    // markup for a chart-heavy page.
    await expect(page.getByText("Executive summary")).toBeVisible();
    await expect(page.getByRole("button", { name: "Retry" })).toHaveCount(0);
  });
});
