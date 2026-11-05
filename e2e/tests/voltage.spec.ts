import { expect, test, type Page } from "@playwright/test";
import { fault } from "./sim";

// battery_sag drops the pack voltage by 2.5 V (to about 22.4 V here) while
// the reported charge stays put. What Styri makes of that depends on
// STYRI_MIN_VOLTAGE. CI runs this file twice: unset, then with
// STYRI_MIN_VOLTAGE=23.0 and E2E_MIN_VOLTAGE=23.0.
const MIN = process.env.E2E_MIN_VOLTAGE ? Number(process.env.E2E_MIN_VOLTAGE) : null;

const hero = (page: Page) => page.getByTestId("verdict");
const tile = (page: Page, label: string) => page.locator(`.vital[data-label="${label}"]`);
const voltage = async (page: Page) => parseFloat((await tile(page, "VOLTAGE").locator(".vital__value").textContent()) ?? "");
async function detail(page: Page) {
  await page.goto("/#fleet");
  await page.locator(".ftile").first().click();
}

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
  await detail(page);
  await expect(hero(page)).toHaveAttribute("data-health", "ok");
  expect(await bridgeMinVoltage(page)).toBe(MIN); // testing the mode the bridge is really in
});

test("voltage sag without STYRI_MIN_VOLTAGE: shown, not judged", async ({ page }) => {
  test.skip(MIN !== null, "runs with STYRI_MIN_VOLTAGE unset");
  const before = await voltage(page);
  fault("battery_sag");
  await expect.poll(() => voltage(page)).toBeLessThan(before - 2);
  await expect(tile(page, "VOLTAGE")).not.toHaveClass(/is-warn/);
  await expect(tile(page, "BATTERY")).not.toHaveClass(/is-warn/);
  await expect(tile(page, "BATTERY").locator(".vital__value")).toHaveText(/^(89|90) %$/);
  await page.waitForTimeout(2000); // a couple more snapshots: still nothing to report
  await expect(hero(page)).toHaveAttribute("data-health", "ok");
  await expect(hero(page).locator(".verdict__reason")).toHaveCount(0);
});

test("voltage sag below STYRI_MIN_VOLTAGE: amber tile and a low-voltage warning", async ({ page }) => {
  test.skip(MIN === null, "runs with STYRI_MIN_VOLTAGE set");
  fault("battery_sag");
  await expect(tile(page, "VOLTAGE")).toHaveClass(/is-warn/);
  await expect(tile(page, "VOLTAGE")).toContainText("▲ VOLTAGE");
  await expect(hero(page)).toHaveAttribute("data-health", "warn");
  await expect(hero(page)).toContainText(new RegExp(`Battery voltage low — 22\\.\\d\\d V, below ${MIN!.toFixed(1)} V\\.`));
  await expect(tile(page, "BATTERY")).not.toHaveClass(/is-warn/); // the charge itself is fine

  await page.getByRole("link", { name: "Activity" }).click();
  await expect(page.locator(".arow[data-kind=warning]").first()).toContainText(`Voltage below ${MIN!.toFixed(1)} V`);

  fault("clear");
  await detail(page);
  await expect(hero(page)).toHaveAttribute("data-health", "ok");
  await expect(tile(page, "VOLTAGE")).not.toHaveClass(/is-warn/);
});
