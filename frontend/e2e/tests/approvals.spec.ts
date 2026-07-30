import { expect, test, type Browser, type Page } from "@playwright/test";

import { ACME_APPROVER, ACME_EMPLOYEE, authStateFile } from "../fixtures/test-users";

/**
 * Submits a leave request as the employee persona in its own, disposable
 * browser context (never the test's own default context, which is the
 * approver) — this suite's specs don't share fixtures across files, so
 * approve/reject each provision the exact request they act on.
 */
async function submitLeaveRequest(browser: Browser, title: string): Promise<void> {
  const context = await browser.newContext({ storageState: authStateFile(ACME_EMPLOYEE) });
  const page = await context.newPage();
  await page.goto("/requests/new");
  await page.getByLabel("Request type").click();
  await page.getByRole("option", { name: "Leave" }).click();
  await page.getByLabel("Title").fill(title);
  await page.getByRole("button", { name: "Create request" }).click();
  await expect(page).toHaveURL(/\/requests\/[0-9a-f-]+$/);
  await context.close();
}

function inboxRow(page: Page, title: string) {
  return page.getByRole("row").filter({ hasText: title });
}

test("an approver can approve a pending request", async ({ browser }) => {
  const title = `E2E approve ${Date.now()}`;
  await submitLeaveRequest(browser, title);

  const context = await browser.newContext({ storageState: authStateFile(ACME_APPROVER) });
  const page = await context.newPage();
  await page.goto("/approvals");

  const row = inboxRow(page, title);
  await expect(row).toBeVisible();
  await row.getByRole("button", { name: "Approve" }).click();

  const dialog = page.getByRole("dialog");
  await dialog.getByPlaceholder("Note (optional)...").fill("Looks good.");
  await dialog.getByRole("button", { name: "Approve" }).click();

  await expect(page.getByText("Request approved.")).toBeVisible();
  await expect(inboxRow(page, title)).not.toBeVisible();
  await context.close();
});

test("an approver can reject a pending request with a reason", async ({ browser }) => {
  const title = `E2E reject ${Date.now()}`;
  await submitLeaveRequest(browser, title);

  const context = await browser.newContext({ storageState: authStateFile(ACME_APPROVER) });
  const page = await context.newPage();
  await page.goto("/approvals");

  const row = inboxRow(page, title);
  await expect(row).toBeVisible();
  await row.getByRole("button", { name: "Reject" }).click();

  const dialog = page.getByRole("dialog");
  await dialog.getByPlaceholder("Reason (required)...").fill("Insufficient notice period.");
  await dialog.getByRole("button", { name: "Reject" }).click();

  await expect(page.getByText("Request rejected.")).toBeVisible();
  await expect(inboxRow(page, title)).not.toBeVisible();
  await context.close();
});
