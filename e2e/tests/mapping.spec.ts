import { expect, test, type Page } from "@playwright/test";

// The panel driven by a styri.yaml. CI runs this file twice against the sim:
//   E2E_CONFIG=preset  STYRI_CONFIG=/opt/styri/presets/styri-sim.yaml (every mapping works)
//   E2E_CONFIG=broken  STYRI_CONFIG=/etc/styri/fixtures/broken.yaml (two mistakes to explain)
// Without E2E_CONFIG (the default run) it checks the no-file behaviour.
const MODE = process.env.E2E_CONFIG ?? "none";

const tile = (page: Page, label: string) => page.locator(`.vital[data-label="${label}"]`);
const configuration = async (page: Page) => {
  await page.getByTestId("user-menu").click();
  await page.getByRole("menuitem", { name: "Configuration" }).click();
};
const row = (page: Page, key: string) => page.locator(`.crow[data-mapping="${key}"]`);

test.beforeEach(async ({ page }) => {
  await page.goto("/");
  await page.locator(".ftile").first().click();
  await expect(page.getByTestId("verdict")).toBeVisible();
});

test("no file: environment defaults, shown as such", async ({ page }) => {
  test.skip(MODE !== "none", "runs without a mapping file");
  await configuration(page);
  await expect(page.getByTestId("config-source")).toHaveText("Environment variables (no styri.yaml)");
  await expect(row(page, "battery")).toHaveAttribute("data-status", "ok");
  await expect(row(page, "cpu_temp")).toContainText("/diagnostics");
  await expect(page.locator(".crow")).toHaveCount(4); // battery, voltage, CPU, diagnostics
});

test("preset: status and custom field tiles, every mapping OK", async ({ page }) => {
  test.skip(MODE !== "preset", "runs with the styri-sim preset");
  await expect(tile(page, "STATUS")).toContainText(/IDLE|MOVING/);
  await expect(tile(page, "SPEED")).toContainText("m/s");
  await expect(tile(page, "BATTERY TEMPERATURE")).toContainText("°C");
  await expect(tile(page, "BATTERY PRESENT")).toContainText("true");
  await expect(tile(page, "CPU TEMP")).toHaveAttribute("title", /\/diagnostics/); // the robot's figure, not the host's
  await expect(page.getByTestId("mapping-banner")).toHaveCount(0);

  await configuration(page);
  await expect(page.getByTestId("config-source")).toHaveText("/opt/styri/presets/styri-sim.yaml");
  await expect(page.locator(".crow")).toHaveCount(8);
  await expect(page.locator('.crow:not([data-status="ok"])')).toHaveCount(0, { timeout: 10_000 });
});

test("broken file: the banner and Configuration say what's wrong", async ({ page }) => {
  test.skip(MODE !== "broken", "runs with the broken fixture");
  const banner = page.getByTestId("mapping-banner");
  await expect(banner).toContainText("2 mapped values aren't coming through", { timeout: 15_000 });
  await expect(banner).toContainText("/robot_state not found. Did you mean /robot_status?");
  await expect(banner).toContainText("no field “linear”");
  await expect(tile(page, "BATTERY")).toContainText("%"); // what is mapped right still works

  await configuration(page);
  await expect(row(page, "status")).toHaveAttribute("data-status", "missing");
  await expect(row(page, "status")).toContainText("Close matches: /robot_status");
  await expect(row(page, "field1")).toHaveAttribute("data-status", "error");
  await expect(row(page, "battery")).toHaveAttribute("data-status", "ok");

  await page.getByRole("link", { name: "Activity" }).click();
  await expect(page.locator(".main")).toContainText("Mapped topic /robot_state not found. Did you mean /robot_status?");
});
