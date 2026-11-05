import { expect, type Page, test } from "@playwright/test";

import { execSync, spawn } from "node:child_process";
import { createReadStream } from "node:fs";
import { dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { clean } from "./clean";

const DEMO = `${dirname(fileURLToPath(import.meta.url))}/../../examples/mixed-fleet`;
const FAKE = `${DEMO}/../../e2e/mixed-fleet/fake_vehicle.py`;

const PASSWORD = process.env.STYRI_ADMIN_PASSWORD ?? "styri-demo";

test.beforeEach(clean);
test.setTimeout(90_000);

async function login(page: Page) {
  await page.getByTestId("log-in").click();
  await page.getByLabel("Username").fill("admin");
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Log in", exact: true }).last().click();
  await expect(page.getByTestId("user-menu")).toBeVisible();
}

/** A tile opens the Map with that robot's card. */
async function open(page: Page, robot: string) {
  await page.goto("/#fleet");
  await page.locator(`.ftile[data-robot="${robot}"]`).click();
  await expect(page.getByTestId("control-drawer")).toBeVisible();
}

/** Send to…, tap the map, and Send. */
async function sendSomewhere(page: Page) {
  await page.getByRole("button", { name: "Send to…" }).first().click();
  const box = (await page.getByTestId("site-map").boundingBox())!;
  await page.mouse.click(box.x + box.width * 0.5, box.y + box.height * 0.3);
  await expect(page.getByTestId("send-goal")).toBeVisible();
  await page.getByTestId("send-goal").click();
}

test("the fleet shows both protocols, one verdict each", async ({ page }) => {
  await page.goto("/");
  for (const name of ["amr-01", "agv-07", "agv-08"]) await expect(page.locator(`.ftile[data-robot="${name}"]`)).toBeVisible();
  await expect(page.locator(".badge-protocol", { hasText: "ROS 2" })).toHaveCount(1);
  await expect(page.locator(".badge-protocol", { hasText: "VDA 5050" })).toHaveCount(2);
});

test("without a login: Operator stop works, and everything else waits for one", async ({ page }) => {
  await open(page, "amr-01");
  await expect(page.getByRole("button", { name: "Log in to control" })).toBeVisible();
  await expect(page.getByText("Log in as an operator to send commands")).toBeVisible();
  await expect(page.getByText("Software stop, not a safety function").first()).toBeVisible();
  await expect(page.getByRole("button", { name: "Drive" })).toHaveCount(0);
  await page.getByTestId("operator-stop").click();
  await expect(page.getByTestId("notice")).toHaveCount(0);
  await page.goto("/#activity");
  await expect(page.getByText(/Operator stop from .* \(anonymous\)/).first()).toBeVisible();
});

test("only the controls a robot supports: a VDA vehicle has no Drive", async ({ page }) => {
  await open(page, "agv-07");
  await login(page);
  await expect(page.getByRole("button", { name: "Send to…" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Drive" })).toHaveCount(0);
  await page.getByRole("button", { name: "Details" }).first().click();
  await expect(page.getByTestId("factsheet")).toContainText("virtual");
  await open(page, "amr-01");
  await page.getByRole("button", { name: "Drive" }).click();
  await expect(page.getByTestId("joystick")).toBeVisible();
});

test("holding the joystick drives, letting go stops, and it's in the command history", async ({ page }) => {
  await open(page, "amr-01");
  await login(page);
  await page.getByRole("button", { name: "Drive" }).click();
  const pad = page.getByTestId("joystick");
  await expect(page.getByTestId("joy-hint")).toHaveText("Hold to drive");
  const box = (await pad.boundingBox())!;
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width / 2, box.y + 10);
  await expect(page.getByTestId("speed")).not.toHaveText(/^[+−]0\.00/);
  await page.waitForTimeout(500);
  await page.mouse.up();
  await expect(page.getByTestId("joy-hint")).toHaveText("Released — stopping");
  await page.getByRole("button", { name: "Done driving" }).click();
  await page.getByRole("button", { name: "Details" }).first().click();
  await expect(page.getByTestId("audit")).toContainText("Drive", { timeout: 10_000 });
});

test("Send to…, one tap on the map, one Send: a VDA vehicle snaps to a node, and the steps show", async ({ page }) => {
  await page.goto("/#map");
  await login(page);
  await page.locator('button[data-robot="agv-07"]').click();
  await sendSomewhere(page);
  await expect(page.getByTestId("notice")).toHaveCount(0);
  await expect(page.locator(".card__tasksum .status")).toContainText(/Running|Done/, { timeout: 10_000 });
});

test("a paused robot offers Resume, not Send to…, and the bridge refuses one anyway", async ({ page }) => {
  await page.goto("/#map");
  await login(page);
  await page.locator('button[data-robot="agv-08"]').click();
  await page.getByTestId("operator-stop").click();
  await expect(page.getByRole("button", { name: "Resume", exact: true })).toBeVisible({ timeout: 10_000 });
  await expect(page.getByRole("button", { name: "Send to…" })).toHaveCount(0);
  const refusal = await page.evaluate(async (password) => {
    const ws = new WebSocket(`ws://${location.host}/ws`);
    await new Promise((r) => (ws.onopen = r));
    const got = new Promise<string>((done) => ws.addEventListener("message", (e) => {
      const m = JSON.parse(e.data);
      if (m.type === "auth") ws.send(JSON.stringify({ action: "GOAL", robot: "agv-08", node: "n3" }));
      if (m.type === "error") done(m.error);
    }));
    ws.send(JSON.stringify({ action: "LOGIN", password }));
    const text = await got;
    ws.close();
    return text;
  }, PASSWORD);
  expect(refusal).toBe("This robot is paused. Press Resume first.");
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

test("an offline robot says OFFLINE on every screen, never OK", async ({ page }) => {
  execSync("docker compose stop -t 1 agv-08", { cwd: DEMO, stdio: "ignore" });
  await page.goto("/#fleet");
  const tile = page.locator('.ftile[data-robot="agv-08"]');
  await expect(tile).toHaveAttribute("data-health", "unknown", { timeout: 15_000 });
  await expect(tile).toContainText("⊘OFFLINE");
  await expect(tile).toContainText(/Offline since \d\d:\d\d\. VDA 5050 connection lost\./);
  await tile.click();
  await expect(page.getByTestId("card-verdict")).toHaveAttribute("data-health", "unknown");
  await expect(page.getByTestId("card-verdict")).toContainText("OFFLINE");
});

test("a robot that won't stop: its health stays, one alert says so, the card turns red", async ({ page }) => {
  execSync("docker compose stop -t 1 agv-07", { cwd: DEMO, stdio: "ignore" });
  const fake = spawn("docker", ["compose", "exec", "-T", "styri", "/ros_entrypoint.sh", "python3", "-"],
    { cwd: DEMO, stdio: ["pipe", "ignore", "ignore"] });
  createReadStream(FAKE).pipe(fake.stdin);
  await page.goto("/#fleet");
  await expect(page.locator('.ftile[data-robot="agv-07"]')).toHaveAttribute("data-task", "active", { timeout: 10_000 });
  await page.locator('.ftile[data-robot="agv-07"]').click();
  await page.getByTestId("operator-stop").click();
  await expect(page.getByTestId("stop-label")).toHaveText("Stop sent…");
  await expect(page.getByTestId("stop-status")).toHaveText("Waiting for agv-07");
  await expect(page.getByTestId("stop-alert")).toHaveText("◆ Stop NOT confirmed: still moving — use the robot's own hardware stop", { timeout: 20_000 });
  await expect(page.getByTestId("stop-status")).toHaveText("Tap to retry");
  await expect(page.getByTestId("card-verdict")).toHaveAttribute("data-health", "ok"); // health is health
  await expect(page.getByTestId("control-drawer")).toHaveClass(/is-stop-failed/);
  fake.kill();
});

test("a stop that works says Stopped, and the card stays as it was", async ({ page }) => {
  await page.goto("/#fleet");
  await page.locator('.ftile[data-robot="agv-08"]').click();
  await page.getByTestId("operator-stop").click();
  await expect(page.getByTestId("stop-label")).toHaveText("Stopped", { timeout: 10_000 });
  await expect(page.getByTestId("stop-status")).toHaveText(/^Stopped at \d\d:\d\d:\d\d · robot is paused$/);
  await expect(page.getByTestId("control-drawer")).not.toHaveClass(/is-stop-failed/);
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
  await expect(page.getByTestId("stop-all")).toContainText("Keep holding");
  await page.mouse.up();
  await page.waitForTimeout(1200);
  expect(await stops.count()).toBe(before);
  await expect(page.getByTestId("stop-all-banner")).toHaveCount(0);
  await page.mouse.down();
  await page.waitForTimeout(1200);
  await page.mouse.up();
  await expect.poll(() => stops.count()).toBeGreaterThan(before);
  await expect(page.getByTestId("stop-all-banner")).toBeVisible();
  await expect(page.locator(".sachip")).toHaveCount(3);
});

test("at 390 px the joystick is a real touch target and the page doesn't scroll sideways", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await open(page, "amr-01");
  await login(page);
  await page.getByTestId("sheet-grab").click();
  await page.getByRole("button", { name: "Drive" }).click();
  const pad = page.getByTestId("joystick");
  await expect(pad).toBeVisible();
  const box = (await pad.boundingBox())!;
  expect(box.width).toBeGreaterThanOrEqual(160);
  expect(await pad.evaluate((el) => getComputedStyle(el).touchAction)).toBe("none");
  expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(0);
});
