import { expect, test, type Page } from "@playwright/test";
import { fault } from "./sim";

// battery_sag drops the pack voltage by 2.5 V (to about 22.4 V here) while
// the reported charge stays put. What Styri makes of that depends on
// STYRI_MIN_VOLTAGE. CI runs this file twice: unset, then with
// STYRI_MIN_VOLTAGE=23.0 and E2E_MIN_VOLTAGE=23.0.
const MIN = process.env.E2E_MIN_VOLTAGE ? Number(process.env.E2E_MIN_VOLTAGE) : null;

const hero = (page: Page) => page.locator(".hero");
const tile = (page: Page, label: string) => page.locator(`.tile[data-label="${label}"]`);
const voltage = async (page: Page) => Number(await tile(page, "VOLTAGE").locator(".tile__number").textContent());

async function bridgeMinVoltage(page: Page): Promise<number | null> {
  return page.evaluate(() => new Promise<number | null>((resolve) => {
    const ws = new WebSocket(`ws://${location.host}/ws`);
    ws.onmessage = (e) => {
      const m = JSON.parse(e.data);
      if (m.type === "hello") { ws.close(); resolve(m.min_voltage); }
    };
  }));
}

test.describe.configure({ mode: "serial" });

test.beforeAll(() => {
  fault("clear");
  fault("battery:90");
});
test.afterAll(() => fault("clear"));

test.beforeEach(async ({ page }) => {
  await page.goto("/");
  await expect(hero(page)).toHaveAttribute("data-health", "ok");
  expect(await bridgeMinVoltage(page)).toBe(MIN); // testing the mode the bridge is really in
});

test("voltage sag without STYRI_MIN_VOLTAGE: shown, not judged", async ({ page }) => {
  test.skip(MIN !== null, "runs with STYRI_MIN_VOLTAGE unset");
  const before = await voltage(page);
  fault("battery_sag");
  await expect.poll(() => voltage(page)).toBeLessThan(before - 2);
  await expect(tile(page, "VOLTAGE")).not.toHaveClass(/tile--warn/);
  await expect(tile(page, "BATTERY")).not.toHaveClass(/tile--warn/);
  await expect(tile(page, "BATTERY").locator(".tile__number")).toHaveText(/^(89|90)$/);
  await page.waitForTimeout(2000); // a couple more snapshots: still nothing to report
  await expect(hero(page)).toHaveAttribute("data-health", "ok");
  await expect(hero(page)).toContainText("All systems normal.");
});

test("voltage sag below STYRI_MIN_VOLTAGE: amber tile and a low-voltage warning", async ({ page }) => {
  test.skip(MIN === null, "runs with STYRI_MIN_VOLTAGE set");
  fault("battery_sag");
  await expect(tile(page, "VOLTAGE")).toHaveClass(/tile--warn/);
  await expect(tile(page, "VOLTAGE")).toContainText("▲ LOW");
  await expect(hero(page)).toHaveAttribute("data-health", "warn");
  await expect(hero(page)).toContainText(new RegExp(`Battery voltage low — 22\\.\\d\\d V, below ${MIN!.toFixed(1)} V\\.`));
  await expect(tile(page, "BATTERY")).not.toHaveClass(/tile--warn/); // the charge itself is fine

  await page.getByRole("link", { name: "Activity log" }).click();
  await expect(page.locator(".lrow[data-kind=warning]").first()).toContainText(`Voltage below ${MIN!.toFixed(1)} V`);

  fault("clear");
  await page.getByRole("link", { name: "Overview" }).click();
  await expect(hero(page)).toHaveAttribute("data-health", "ok");
  await expect(tile(page, "VOLTAGE")).not.toHaveClass(/tile--warn/);
});
