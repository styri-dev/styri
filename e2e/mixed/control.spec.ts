import { expect, type Page, test } from "@playwright/test";

import { clean } from "./clean";

const PASSWORD = process.env.STYRI_ADMIN_PASSWORD ?? "styri-demo";

test.beforeEach(clean);
test.setTimeout(90_000);

async function login(page: Page) {
  await page.getByTestId("login-toggle").click();
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Log in", exact: true }).last().click();
  await expect(page.getByTestId("login-toggle")).toHaveText("Log out");
}

async function open(page: Page, robot: string) {
  await page.goto("/#fleet");
  await page.locator(`[data-robot="${robot}"]`).click();
  await expect(page.getByTestId("control-drawer")).toBeVisible();
}

test("the fleet shows both protocols, one verdict each", async ({ page }) => {
  await page.goto("/");
  for (const name of ["amr-01", "agv-07", "agv-08"]) await expect(page.locator(`button[data-robot="${name}"]`)).toBeVisible();
  await expect(page.locator(".badge-protocol", { hasText: "ROS 2" })).toHaveCount(1);
  await expect(page.locator(".badge-protocol", { hasText: "VDA 5050" })).toHaveCount(2);
});

test("without a login: Operator stop works, and everything else waits for one", async ({ page }) => {
  await open(page, "amr-01");
  await expect(page.getByRole("button", { name: "Log in to control robots" })).toBeVisible();
  await expect(page.getByText("Software stop, not a safety function").first()).toBeVisible();
  await expect(page.getByTestId("joystick")).toHaveCount(0);
  await page.getByTestId("operator-stop").click();
  await expect(page.getByTestId("notice")).toHaveCount(0);
  await page.goto("/#activity");
  await expect(page.getByText(/Operator stop from .* \(anonymous\)/).first()).toBeVisible();
});

test("only the controls a robot supports: a VDA vehicle has no joystick", async ({ page }) => {
  await open(page, "agv-07");
  await login(page);
  await expect(page.getByTestId("joystick")).toHaveCount(0);
  await expect(page.getByTestId("factsheet")).toContainText("virtual");
  await open(page, "amr-01");
  await expect(page.getByTestId("joystick")).toBeVisible();
});

test("holding the joystick drives, letting go stops, and it's in the audit log", async ({ page }) => {
  await open(page, "amr-01");
  await login(page);
  const pad = page.getByTestId("joystick");
  await pad.scrollIntoViewIfNeeded();
  const box = (await pad.boundingBox())!;
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width / 2, box.y + 10);
  await expect(page.getByTestId("speed")).not.toHaveText(/^\+?-?0\.00/);
  await page.waitForTimeout(500);
  await page.mouse.up();
  await expect(page.getByTestId("audit")).toContainText("TELEOP", { timeout: 10_000 });
});

test("one tap on the map, one Send: a VDA vehicle snaps to a node", async ({ page }) => {
  await page.goto("/#map");
  await login(page);
  await page.locator('g[data-robot="agv-07"]').click();
  const box = (await page.getByTestId("site-map").boundingBox())!;
  await page.mouse.click(box.x + box.width * 0.5, box.y + box.height * 0.3);
  await expect(page.getByTestId("send-goal")).toBeVisible();
  await page.getByTestId("send-goal").click();
  await expect(page.getByTestId("notice")).toHaveCount(0);
});

test("a paused robot refuses a new goal, and says why", async ({ page }) => {
  await page.goto("/#map");
  await login(page);
  await page.locator('g[data-robot="agv-08"]').click();
  await page.getByTestId("operator-stop").click();
  await expect(page.getByRole("button", { name: "Resume", exact: true })).toBeVisible({ timeout: 10_000 });
  const box = (await page.getByTestId("site-map").boundingBox())!;
  await page.mouse.click(box.x + box.width * 0.5, box.y + box.height * 0.3);
  await page.getByTestId("send-goal").click();
  await expect(page.getByTestId("graph-error")).toHaveText("This robot is paused. Press Resume first.");
});

test("the demo's map editor saves out of the box", async ({ page }) => {
  await page.goto("/#map");
  await login(page);
  await expect(page.locator("[data-node]").first()).toBeVisible();
  const before = await page.locator("[data-node]").count();
  await page.getByTestId("edit-graph").click();
  await page.getByTestId("tool-add").click();
  const box = (await page.getByTestId("site-map").boundingBox())!;
  // A clear spot each time: a tap on an existing node doesn't add one.
  await page.mouse.click(box.x + box.width * (0.08 + 0.09 * (before % 10)), box.y + box.height * 0.97);
  await page.getByTestId("save-graph").click();
  await expect(page.getByTestId("edit-graph")).toBeVisible();
  await expect(page.getByTestId("graph-error")).toHaveCount(0);
  await page.reload();
  await expect(page.locator("[data-node]")).toHaveCount(before + 1);
});

test("Stop all: a tap does nothing, a one-second hold stops the fleet", async ({ page }) => {
  await page.goto("/#activity");
  const stops = page.getByText(/Operator stop from/);
  await expect(page.locator(".tab--active")).toContainText("Activity");
  await page.waitForTimeout(1000);
  const before = await stops.count();
  const box = (await page.getByTestId("stop-all").boundingBox())!;
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await page.mouse.down();
  await page.waitForTimeout(300);
  await page.mouse.up();
  await page.waitForTimeout(1200);
  expect(await stops.count()).toBe(before);
  await page.mouse.down();
  await page.waitForTimeout(1200);
  await page.mouse.up();
  await expect.poll(() => stops.count()).toBeGreaterThan(before);
});

test("at 390 px the joystick is a real touch target and the page doesn't scroll sideways", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await open(page, "amr-01");
  await login(page);
  const pad = page.getByTestId("joystick");
  await expect(pad).toBeVisible();
  const box = (await pad.boundingBox())!;
  expect(box.width).toBeGreaterThanOrEqual(160);
  expect(await pad.evaluate((el) => getComputedStyle(el).touchAction)).toBe("none");
  expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(0);
});
