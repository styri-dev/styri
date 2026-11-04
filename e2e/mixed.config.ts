import { defineConfig } from "@playwright/test";

// The control UI, against examples/mixed-fleet.
export default defineConfig({
  testDir: "./mixed",
  use: { baseURL: process.env.BASE_URL ?? "http://localhost:8080", channel: process.env.PW_CHANNEL },
  workers: 1,
  timeout: 60_000,
});
