import { type Browser, expect, type Page, test } from "@playwright/test";
import { clean } from "./clean";

// The Users screen, admins only, against examples/mixed-fleet.
const PASSWORD = process.env.STYRI_ADMIN_PASSWORD ?? "styri-demo";
const SECRET = "correct-horse-1";

test.describe.configure({ mode: "serial" });
test.beforeAll(clean);
test.setTimeout(60_000);

async function login(page: Page, name = "admin", password = PASSWORD) {
  await page.goto("/#fleet");
  await page.getByTestId("log-in").click();
  await page.getByLabel("Username").fill(name);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Log in", exact: true }).last().click();
  await expect(page.getByTestId("user-menu")).toBeVisible();
}

async function users(page: Page) {
  await login(page);
  await page.getByTestId("user-menu").click();
  await page.getByRole("menuitem", { name: "Users and settings" }).click();
  await expect(page.getByTestId("users")).toBeVisible();
}

async function addUser(page: Page, name: string, role: string) {
  await page.getByTestId("add-user").click();
  const form = page.getByTestId("add-user-form");
  await form.getByLabel("Username").fill(name);
  await form.getByLabel("Password").fill(SECRET);
  await form.getByLabel("New user's role").selectOption(role);
  await form.getByRole("button", { name: "Add user" }).click();
  await expect(page.locator(`[data-user="${name}"]`)).toBeVisible();
}

const fresh = async (browser: Browser) => (await browser.newContext()).newPage();
const row = (page: Page, name: string) => page.locator(`[data-user="${name}"]`);

test("add a user, who can then log in with that role", async ({ page, browser }) => {
  await users(page);
  await addUser(page, "t.add", "operator");
  await expect(page.getByLabel("Role for t.add")).toHaveValue("operator");
  const them = await fresh(browser);
  await login(them, "t.add", SECRET);
  await them.getByTestId("user-menu").click();
  await expect(them.locator(".menu__who")).toContainText("t.add · Operator");
  await expect(them.getByRole("menuitem", { name: "Users and settings" })).toHaveCount(0);
});

test("a bad password is refused, and says why", async ({ page }) => {
  await users(page);
  await page.getByTestId("add-user").click();
  const form = page.getByTestId("add-user-form");
  await form.getByLabel("Username").fill("t.short");
  await form.getByLabel("Password").fill("short");
  await form.getByRole("button", { name: "Add user" }).click();
  await expect(page.getByTestId("users-error")).toContainText("Use at least 8 characters");
  await expect(row(page, "t.short")).toHaveCount(0);
});

test("a role change asks first, says what they lose, and Cancel changes nothing", async ({ page }) => {
  await users(page);
  await page.getByLabel("Role for t.add").selectOption("viewer");
  const ask = row(page, "t.add").getByTestId("user-confirm");
  await expect(ask).toContainText("Make t.add a Viewer?");
  await expect(ask).toContainText("can watch, but can no longer send, pause or drive robots.");
  await ask.getByRole("button", { name: "Cancel" }).click();
  await expect(page.getByLabel("Role for t.add")).toHaveValue("operator");

  await page.getByLabel("Role for t.add").selectOption("viewer");
  await row(page, "t.add").getByTestId("confirm-yes").click();
  await expect(row(page, "t.add").getByTestId("user-confirm")).toHaveCount(0);
  await page.reload();
  await expect(page.getByLabel("Role for t.add")).toHaveValue("viewer");
});

test("reset password: the old one stops working, the new one works", async ({ page, browser }) => {
  await users(page);
  await row(page, "t.add").getByRole("button", { name: "Reset password" }).click();
  const form = page.getByTestId("password-form");
  await form.getByLabel("New password").fill("a-new-password");
  await form.getByRole("button", { name: "Reset password" }).click();
  await expect(form).toHaveCount(0);
  const them = await fresh(browser);
  await them.goto("/#login");
  await them.getByLabel("Username").fill("t.add");
  await them.getByLabel("Password").fill(SECRET);
  await them.getByRole("button", { name: "Log in", exact: true }).last().click();
  await expect(them.getByTestId("login-error")).toContainText("Wrong username or password");
  await login(them, "t.add", "a-new-password");
});

test("viewers and anonymous can't reach the Users screen", async ({ page, browser }) => {
  await login(page, "t.add", "a-new-password"); // a viewer by now
  await page.getByTestId("user-menu").click();
  await expect(page.getByRole("menuitem", { name: "Users and settings" })).toHaveCount(0);
  await page.goto("/#users");
  await expect(page.locator(".ftile").first()).toBeVisible();
  await expect(page.getByTestId("users")).toHaveCount(0);

  const anon = await fresh(browser);
  await anon.goto("/#users");
  await expect(anon.locator(".ftile").first()).toBeVisible();
  await expect(anon.getByTestId("users")).toHaveCount(0);
  await expect(anon.getByTestId("user-menu")).toHaveCount(0);
});

test("a viewer keeps the stop button and has no commands", async ({ page }) => {
  await login(page, "t.add", "a-new-password");
  await page.locator('.ftile[data-robot="agv-07"]').click();
  await expect(page.getByTestId("operator-stop")).toBeVisible();
  await expect(page.getByRole("button", { name: "Log in to control" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Send to…" })).toHaveCount(0);
});

test("remove asks first; a removed user can't log in", async ({ page, browser }) => {
  await users(page);
  await row(page, "t.add").getByRole("button", { name: "Remove" }).click();
  const ask = row(page, "t.add").getByTestId("user-confirm");
  await expect(ask).toContainText("Remove t.add?");
  await expect(ask).toContainText("t.add can no longer log in. Their past commands stay in Activity.");
  await ask.getByRole("button", { name: "Cancel" }).click();
  await expect(row(page, "t.add")).toBeVisible();
  await row(page, "t.add").getByRole("button", { name: "Remove" }).click();
  await row(page, "t.add").getByTestId("confirm-yes").click();
  await expect(row(page, "t.add")).toHaveCount(0);
  const them = await fresh(browser);
  await them.goto("/#login");
  await them.getByLabel("Username").fill("t.add");
  await them.getByLabel("Password").fill("a-new-password");
  await them.getByRole("button", { name: "Log in", exact: true }).last().click();
  await expect(them.getByTestId("login-error")).toContainText("Wrong username or password");
});

test("robot control off asks first, every panel follows, and on comes back", async ({ page, browser }) => {
  const watcher = await fresh(browser);
  await watcher.goto("/#fleet");
  await expect(watcher.getByTestId("stop-all")).toBeVisible();
  await users(page);
  await page.getByTestId("switch-control").click();
  const ask = page.getByTestId("switch-confirm");
  await expect(ask).toContainText("Turn robot control off?");
  await ask.getByRole("button", { name: "Keep control on" }).click();
  await expect(page.getByTestId("switch-control")).toHaveAttribute("aria-pressed", "true");
  await page.getByTestId("switch-control").click();
  await page.getByTestId("switch-off").click();
  await expect(page.getByTestId("switch-control")).toHaveAttribute("aria-pressed", "false");
  await expect(watcher.getByTestId("stop-all")).toHaveCount(0); // the switches broadcast, no reload
  await page.getByTestId("switch-control").click();
  await expect(page.getByTestId("switch-control")).toHaveAttribute("aria-pressed", "true");
  await expect(watcher.getByTestId("stop-all")).toBeVisible();
});

test("anonymous viewing off asks first and leaves only the login; on brings the panel back", async ({ page, browser }) => {
  const watcher = await fresh(browser);
  await watcher.goto("/#fleet");
  await expect(watcher.locator(".ftile").first()).toBeVisible();
  await users(page);
  await page.getByTestId("switch-anonymous").click();
  await expect(page.getByTestId("switch-confirm")).toContainText("Turn anonymous viewing off?");
  await page.getByTestId("switch-off").click();
  await expect(page.getByTestId("switch-anonymous")).toHaveAttribute("aria-pressed", "false");
  await expect(watcher.getByRole("button", { name: "Log in", exact: true })).toBeVisible();
  await expect(watcher.locator(".ftile")).toHaveCount(0);
  await expect(watcher.getByTestId("stop-all")).toHaveCount(0);
  await page.getByTestId("switch-anonymous").click();
  await expect(page.getByTestId("switch-anonymous")).toHaveAttribute("aria-pressed", "true");
  await expect(watcher.locator(".ftile").first()).toBeVisible();
});
