import { expect, test } from "@playwright/test";

// Needs e2e/mixed-fleet/first-run.yaml: no admin password, and amr-01 with no speed feedback.
test.skip(!process.env.E2E_FIRST_RUN, "needs the first-run stack");
test.describe.configure({ mode: "serial" });

const PASSWORD = "first-day-password";

test("first run: the first login sets the admin password", async ({ page }) => {
  await page.goto("/");
  await page.getByTestId("log-in").click();
  await expect(page.getByText("Set the admin password")).toBeVisible();
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Set password" }).click();
  await expect(page.getByTestId("user-menu")).toBeVisible();
});

test("no speed feedback: no drive or send, and a stop says it can't confirm", async ({ page }) => {
  await page.goto("/");
  await page.getByTestId("log-in").click();
  await page.getByLabel("Username").fill("admin");
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Log in", exact: true }).last().click();
  await expect(page.getByTestId("user-menu")).toBeVisible();
  await page.goto("/#robot/amr-01");
  await expect(page.getByRole("button", { name: /Send to/ })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Drive", exact: true })).toHaveCount(0);
  await page.getByTestId("operator-stop").click();
  await expect(page.getByTestId("stop-status")).toContainText("Stop sent · can't confirm: no speed feedback configured");
});
