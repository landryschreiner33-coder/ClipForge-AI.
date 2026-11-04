import { defineConfig, devices } from "@playwright/test";

// Serve only the built phone shell. API responses are intercepted by the tests, so no application,
// saved data, account or platform is involved and CLIPFOUNDRY_URL is intentionally ignored.
const port = Number(process.env.CLIPFOUNDRY_PHONE_TEST_PORT || 8813);
const python = process.env.CLIPFOUNDRY_PYTHON
  || (process.platform === "win32" ? "..\\.venv\\Scripts\\python.exe" : "../.venv/bin/python");
const executablePath = process.env.CLIPFOUNDRY_E2E_CHROMIUM || undefined;

export default defineConfig({
  testDir: ".",
  testMatch: "phone-monitor.spec.ts",
  workers: 1,
  fullyParallel: false,
  retries: 0,
  timeout: 30_000,
  expect: { timeout: 8_000 },
  forbidOnly: !!process.env.CI,
  reporter: [["list"]],
  outputDir: "test-results-phone",
  use: {
    baseURL: `http://127.0.0.1:${port}`,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  webServer: {
    command: `"${python}" -m http.server ${port} --bind 127.0.0.1 --directory ../frontend/dist/phone`,
    url: `http://127.0.0.1:${port}`,
    reuseExistingServer: false,
    timeout: 20_000,
    stdout: "pipe",
  },
  projects: [{
    name: "phone-chromium",
    use: {
      ...devices["Desktop Chrome"],
      viewport: { width: 390, height: 844 },
      isMobile: true,
      hasTouch: true,
      launchOptions: { executablePath },
    },
  }],
});
