import { defineConfig, devices } from "@playwright/test";

// The tests drive a ClipFoundry that is already running (start.bat), by default at the app's own address.
// Use 127.0.0.1, not a LAN address: Autopilot and publishing only answer on this computer.
export const baseURL = (process.env.CLIPFOUNDRY_URL || "http://127.0.0.1:8765").replace(/\/+$/, "");

// Normally unset: Playwright uses the Chromium from `npx playwright install chromium`.
const executablePath = process.env.CLIPFOUNDRY_E2E_CHROMIUM || undefined;

export default defineConfig({
  testDir: "./tests",
  globalSetup: "./global-setup.ts",
  // One browser at a time: the app may be busy transcribing or rendering on the same machine.
  workers: 1,
  fullyParallel: false,
  retries: 0,
  timeout: 45_000,
  expect: { timeout: 15_000 },
  forbidOnly: !!process.env.CI,
  reporter: [["list"], ["html", { open: "never" }]],
  use: {
    baseURL,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 }, launchOptions: { executablePath } },
    },
  ],
});
