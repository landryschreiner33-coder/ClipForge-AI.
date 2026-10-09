import { defineConfig, devices } from "@playwright/test";

// The beginner-flow test changes things (connects accounts, turns Autopilot on, answers a question), so it never
// runs against your real ClipFoundry: Playwright starts a throwaway sandbox (sandbox/run_sandbox.py) with its own
// temporary data folder, test connections to local stand-ins for Google and TikTok, and its own port.
const port = Number(process.env.CLIPFOUNDRY_SANDBOX_PORT || 8799);
const loopPort = port + 1;
const python = process.env.CLIPFOUNDRY_PYTHON || (process.platform === "win32" ? "..\\.venv\\Scripts\\python.exe" : "../.venv/bin/python");
const executablePath = process.env.CLIPFOUNDRY_E2E_CHROMIUM || undefined;

export default defineConfig({
  testDir: "./sandbox",
  workers: 1,
  fullyParallel: false,
  retries: 0,
  timeout: 600_000,
  expect: { timeout: 20_000 },
  reporter: [["list"], ["html", { open: "never", outputFolder: "playwright-report-sandbox" }]],
  outputDir: "test-results-sandbox",
  use: {
    baseURL: `http://127.0.0.1:${port}`,
    actionTimeout: 30_000,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  webServer: [
    {
      command: `"${python}" sandbox/run_sandbox.py --port ${port}`,
      url: `http://127.0.0.1:${port}/api/health`,
      reuseExistingServer: false,
      timeout: 120_000,
      stdout: "pipe",
    },
    {
      command: `"${python}" sandbox/run_sandbox.py --scenario zero-touch --port ${loopPort}`,
      url: `http://127.0.0.1:${loopPort}/api/health`,
      reuseExistingServer: false,
      timeout: 300_000,
      stdout: "pipe",
    },
  ],
  projects: [
    {
      name: "chromium",
      testMatch: ["beginner-flow.spec.ts", "motion.spec.ts", "robot-office.spec.ts", "brain-workspace.spec.ts", "pixel-office.spec.ts", "living-office.spec.ts"],
      use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 }, launchOptions: { executablePath } },
    },
    {
      name: "complete-loop",
      testMatch: "zero-touch-loop.spec.ts",
      use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 },
        baseURL: `http://127.0.0.1:${loopPort}`, launchOptions: { executablePath } },
    },
  ],
});
