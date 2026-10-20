import { defineConfig, devices } from "@playwright/test";

// Drives the real operator panel against a running stack with the simulated
// robot: `docker compose up`, locally or in CI.
export default defineConfig({
  testDir: "tests",
  // One robot, one shared state: run in order, never in parallel.
  workers: 1,
  fullyParallel: false,
  timeout: 90_000,
  expect: { timeout: 10_000 },
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: process.env.BASE_URL ?? "http://localhost:8080",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
