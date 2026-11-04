import { defineConfig } from "@playwright/test";

// The control UI, against examples/mixed-fleet.
export default defineConfig({
  testDir: "./mixed",
  retries: 0,
  reporter: "list",
  use: {
    baseURL: process.env.BASE_URL ?? "http://localhost:8080",
    channel: process.env.PW_CHANNEL,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  workers: 1,
  timeout: 60_000,
});
