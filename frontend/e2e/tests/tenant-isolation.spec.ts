import { expect, test } from "@playwright/test";

import { ACME_APPROVER, ACME_EMPLOYEE, GLOBEX_EMPLOYEE, authStateFile } from "../fixtures/test-users";

test("a Globex request is never visible to an Acme employee by direct URL", async ({ browser }) => {
  const title = `E2E tenant isolation ${Date.now()}`;

  const globexContext = await browser.newContext({ storageState: authStateFile(GLOBEX_EMPLOYEE) });
  const globexPage = await globexContext.newPage();
  await globexPage.goto("/requests/new");
  await globexPage.getByLabel("Request type").click();
  await globexPage.getByRole("option", { name: "Leave" }).click();
  await globexPage.getByLabel("Title").fill(title);
  await globexPage.getByRole("button", { name: "Create request" }).click();
  await expect(globexPage).toHaveURL(/\/requests\/[0-9a-f-]+$/);
  const globexRequestId = globexPage.url().split("/requests/")[1];
  await globexContext.close();

  const acmeContext = await browser.newContext({ storageState: authStateFile(ACME_EMPLOYEE) });
  const acmePage = await acmeContext.newPage();
  await acmePage.goto(`/requests/${globexRequestId}`);

  // The multi-tenancy RLS boundary (migration 0003_row_level_security)
  // makes a cross-company request id resolve as not-found, never as a
  // real payload — surfaced the same way any other genuine load failure
  // is, per requests/[id]/page.tsx's isError branch, not a data leak.
  await expect(acmePage.getByText("Couldn't load this request.")).toBeVisible();
  await expect(acmePage.getByText(title)).not.toBeVisible();
  await acmeContext.close();
});

test("a Globex pending stage never appears in an Acme approver's inbox", async ({ browser }) => {
  const title = `E2E tenant isolation inbox ${Date.now()}`;

  const globexContext = await browser.newContext({ storageState: authStateFile(GLOBEX_EMPLOYEE) });
  const globexPage = await globexContext.newPage();
  await globexPage.goto("/requests/new");
  await globexPage.getByLabel("Request type").click();
  await globexPage.getByRole("option", { name: "Leave" }).click();
  await globexPage.getByLabel("Title").fill(title);
  await globexPage.getByRole("button", { name: "Create request" }).click();
  await expect(globexPage).toHaveURL(/\/requests\/[0-9a-f-]+$/);
  await globexContext.close();

  const acmeContext = await browser.newContext({ storageState: authStateFile(ACME_APPROVER) });
  const acmePage = await acmeContext.newPage();
  await acmePage.goto("/approvals");
  await expect(acmePage.getByRole("row").filter({ hasText: title })).not.toBeVisible();
  await acmeContext.close();
});
