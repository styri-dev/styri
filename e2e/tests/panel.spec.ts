import { readFile } from "node:fs/promises";
import { expect, test, type Page } from "@playwright/test";
import { fault, pose } from "./sim";

const hero = (page: Page) => page.locator(".hero");
const tile = (page: Page, label: string) => page.locator(`.tile[data-label="${label}"]`);

test.describe.configure({ mode: "serial" });

test.beforeAll(() => {
  // The sim keeps running between test runs; start from a known state.
  fault("clear");
  fault("battery:90");
});

test.beforeEach(async ({ page }) => {
  await page.goto("/");
  await expect(page.locator(".field__conn")).toContainText("Connected");
});

test("overview shows live data from the robot", async ({ page }) => {
  await expect(hero(page)).toHaveAttribute("data-health", "ok");
  await expect(hero(page)).toContainText("All systems normal.");
  await expect(tile(page, "BATTERY").locator(".tile__number")).toHaveText(/^\d+$/);
  await expect(tile(page, "VOLTAGE").locator(".tile__number")).toHaveText(/^2\d\.\d\d$/);
  await expect(tile(page, "CPU TEMP")).toContainText("/diagnostics");
  await expect(tile(page, "CPU TEMP").locator(".tile__number")).toHaveText(/^5\d\.\d$/);
  await expect(tile(page, "LINK LATENCY").locator(".tile__number")).toHaveText(/^\d+$/);
  await expect(tile(page, "BATTERY")).toContainText("LIVE");
});

test("topics tab lists the graph with rates and the latest message", async ({ page }) => {
  await page.getByRole("link", { name: /Topics/ }).click();
  const odom = page.locator('.trow[data-topic="/odom"]');
  await expect(odom).toContainText("nav_msgs/msg/Odometry");
  await expect.poll(async () => Number(await odom.locator(".num").first().textContent())).toBeGreaterThan(5);
  await expect(page.locator('.trow[data-topic="/scan"]')).toBeVisible();
  await odom.click();
  await expect(page.locator(".message")).toContainText("pose:");
  await expect(page.locator(".topics__detail")).toContainText("nav_msgs/msg/Odometry");
});

test("low battery raises a warning and logs it", async ({ page }) => {
  fault("battery:18");
  await expect(hero(page)).toHaveAttribute("data-health", "warn");
  await expect(hero(page)).toContainText("Battery low — 18 %. Send to dock soon.");
  await expect(tile(page, "BATTERY")).toContainText("▲ LOW");

  await page.getByRole("link", { name: "Activity log" }).click();
  await expect(page.locator(".lrow[data-kind=warning]").first()).toContainText("Battery below 25 %");
  await expect(page.getByText("Robot status changed OK → WARNING").first()).toBeVisible();

  fault("battery:90");
  await page.getByRole("link", { name: "Overview" }).click();
  await expect(hero(page)).toHaveAttribute("data-health", "ok");
});

test("a diagnostics error is a fault", async ({ page }) => {
  fault("motor_fault");
  await expect(hero(page)).toHaveAttribute("data-health", "fault");
  await expect(hero(page)).toContainText("motor_right reports Overcurrent.");
  fault("clear");
  await expect(hero(page)).toHaveAttribute("data-health", "ok");
});

test("a silent robot goes stale, then recovers", async ({ page }) => {
  fault("silence:8");
  await expect(tile(page, "BATTERY")).toContainText("STALE");
  await expect(hero(page)).toHaveAttribute("data-health", "unknown");
  await expect(hero(page)).toContainText("No data from the robot");
  await expect(hero(page)).toHaveAttribute("data-health", "ok", { timeout: 20_000 });
  await page.getByRole("link", { name: "Activity log" }).click();
  await expect(page.getByText(/\/battery_state recovered after \d+ s/).first()).toBeVisible();
});

test("activity log filters and exports CSV", async ({ page }) => {
  await page.getByRole("link", { name: "Activity log" }).click();
  await page.getByRole("button", { name: "Warnings" }).click();
  const kinds = await page.locator(".lrow[data-kind]").evaluateAll((rows) => rows.map((r) => r.getAttribute("data-kind")));
  expect(kinds.length).toBeGreaterThan(0);
  expect(new Set(kinds)).toEqual(new Set(["warning"]));

  await page.getByRole("button", { name: "All", exact: true }).first().click();
  const [download] = await Promise.all([
    page.waitForEvent("download"),
    page.getByRole("button", { name: "Export CSV" }).click(),
  ]);
  const csv = await readFile((await download.path())!, "utf8");
  expect(csv.split("\n")[0]).toBe('"timestamp","type","event","source"');
  expect(csv).toContain('"warning","Battery below 25 %","/battery_state"');
  expect(csv).toMatch(/"state","styri v[\d.]+ started"/);
});

test("with control off there are no control buttons", async ({ page }) => {
  await expect(page.getByTestId("stop-all")).toHaveCount(0);
  await expect(page.getByTestId("control-drawer")).toHaveCount(0);
  await expect(page.getByTestId("login-toggle")).toHaveCount(0);
});

test("view-only refuses control commands and the robot stays put", async ({ page }) => {
  const before = pose();
  const replies = await page.evaluate(async () => {
    const ws = new WebSocket(`ws://${location.host}/ws`);
    const got: any[] = [];
    await new Promise((r) => (ws.onopen = r));
    ws.onmessage = (e) => {
      const m = JSON.parse(e.data);
      if (m.type === "error") got.push(m);
    };
    for (const msg of [{ action: "OPERATOR_STOP", robot: 0 }, { action: "GOAL", robot: 0, x: 1, y: 1 }, { action: "TELEOP", robot: 0, linear: 0.4, angular: 0 }]) {
      ws.send(JSON.stringify(msg));
    }
    await new Promise((r) => setTimeout(r, 1500));
    ws.close();
    return got;
  });
  expect(replies).toHaveLength(3);
  for (const r of replies) expect(r.error).toContain("view-only");
  const after = pose();
  expect(after.v).toBe(0);
  expect(Math.hypot(after.x - before.x, after.y - before.y)).toBeLessThan(0.01);
});

test("the panel never requests anything from another origin", async ({ page, baseURL }) => {
  const foreign: string[] = [];
  page.on("request", (req) => {
    const url = new URL(req.url());
    if (url.origin !== new URL(baseURL!).origin && url.protocol !== "data:") foreign.push(req.url());
  });
  await page.goto("/");
  for (const name of ["Topics", "Activity log", "Overview"]) {
    await page.getByRole("link", { name: new RegExp(name) }).click();
  }
  await page.waitForTimeout(1500);
  expect(foreign).toEqual([]);
});

test.describe("at 768 px", () => {
  test.use({ viewport: { width: 768, height: 1024 } });

  test("overview tiles lay out 3 + 2", async ({ page }) => {
    // "Connected" can come before the first snapshot, and evaluateAll doesn't wait.
    await expect(page.locator(".tile")).toHaveCount(5);
    const tops = await page.locator(".tile").evaluateAll((els) => els.map((e) => Math.round(e.getBoundingClientRect().top)));
    expect(tops).toHaveLength(5);
    expect(new Set(tops.slice(0, 3)).size).toBe(1);
    expect(new Set(tops.slice(3)).size).toBe(1);
    expect(tops[3]).toBeGreaterThan(tops[0]);
  });
});

test.describe("on a phone (390 px)", () => {
  test.use({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });

  test("a warning fits: no sideways scroll, numbers inside their tiles, one-row header", async ({ page }) => {
    fault("battery:18");
    await expect(page.locator(".hero")).toHaveAttribute("data-health", "warn");
    const m = await page.evaluate(() => ({
      vw: document.documentElement.clientWidth,
      scrollW: document.documentElement.scrollWidth,
      heroRight: document.querySelector(".hero__word")!.getBoundingClientRect().right,
      spill: [...document.querySelectorAll(".tile")].filter((t) => {
        const v = t.querySelector(".tile__value") as HTMLElement;
        return v.scrollWidth > v.clientWidth + 1;
      }).map((t) => (t as HTMLElement).dataset.label),
      badgeH: (document.querySelector(".badge") as HTMLElement).getBoundingClientRect().height,
      headerH: document.querySelector(".header")!.getBoundingClientRect().height,
      tabsFit: [...document.querySelectorAll(".tab")].every((t) => t.getBoundingClientRect().right <= document.documentElement.clientWidth),
    }));
    fault("battery:90");
    expect(m.scrollW).toBe(m.vw);
    expect(m.heroRight).toBeLessThanOrEqual(m.vw);
    expect(m.spill).toEqual([]);
    expect(m.badgeH).toBeLessThanOrEqual(30); // "▲ LOW" on one line
    expect(m.headerH).toBeLessThanOrEqual(64);
    expect(m.tabsFit).toBe(true);
  });
});
