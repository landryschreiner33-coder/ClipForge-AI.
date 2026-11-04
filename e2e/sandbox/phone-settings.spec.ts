import { expect, test } from "@playwright/test";

test("desktop owner can set up, pair and revoke the separate phone dashboard", async ({ page }) => {
  let running = false;
  let devices = 0;
  let mode = "tailscale";
  const actions: { url: string; method: string; body: any; marker: string | undefined }[] = [];
  const view = () => ({ enabled: running, running, state: running ? "running" : "off", mode,
    address: running ? "http://100.80.1.7:8766" : "", bind_address: "100.80.1.7", port: 8766, error: "",
    paired_devices: devices, addresses: [{ mode: "tailscale", address: "100.80.1.7" },
      { mode: "wifi", address: "192.168.50.7" }] });
  await page.route("**/api/phone-monitor{,/**}", async (route) => {
    const request = route.request();
    if (request.method() !== "GET") {
      actions.push({ url: request.url(), method: request.method(), body: request.postDataJSON(),
        marker: request.headers()["x-clipfoundry"] });
    }
    const path = new URL(request.url()).pathname;
    if (path.endsWith("/enable")) { running = true; mode = request.postDataJSON().mode; }
    if (path.endsWith("/disable")) running = false;
    if (path.endsWith("/revoke")) devices = 0;
    if (path.endsWith("/pairing")) {
      devices = 1;
      return route.fulfill({ json: { code: "12345678", expires_at: Date.now() / 1000 + 300,
        address: "http://100.80.1.7:8766" } });
    }
    await route.fulfill({ json: view() });
  });
  await page.goto("/#/settings/integrations");
  const panel = page.locator("#int-phone-panel");
  await expect(panel.getByText("Phone dashboard is off")).toBeVisible();
  await expect(panel.getByLabel("Connect through")).toHaveValue("tailscale");
  await panel.getByRole("button", { name: "Turn on phone dashboard" }).click();
  await expect(panel.getByText("Phone dashboard is on")).toBeVisible();
  await expect(panel.getByLabel("Open this address on your phone")).toHaveValue("http://100.80.1.7:8766");
  await panel.getByRole("button", { name: "Get pairing code" }).click();
  await expect(panel.getByLabel("Phone pairing code")).toHaveText("12345678");
  await expect(panel.getByText("Single use", { exact: false })).toBeVisible();
  await panel.getByRole("button", { name: "Turn off phone access" }).click();
  await expect(panel.getByLabel("Phone pairing code")).toHaveCount(0);
  await expect(panel.getByText("Phone dashboard is off")).toBeVisible();
  await panel.getByRole("button", { name: "Unpair all phones" }).click();
  await expect(panel.getByText("0 paired phones")).toBeVisible();
  await panel.getByLabel("Connect through").selectOption("wifi");
  await expect(panel.getByText("HTTP traffic is not encrypted.", { exact: false })).toBeVisible();
  await panel.getByLabel("PC network address (optional)").fill("192.168.50.7");
  await panel.getByRole("button", { name: "Turn on phone dashboard" }).click();
  expect(actions.map((a) => new URL(a.url).pathname)).toEqual([
    "/api/phone-monitor/enable", "/api/phone-monitor/pairing", "/api/phone-monitor/disable",
    "/api/phone-monitor/revoke", "/api/phone-monitor/enable",
  ]);
  expect(actions.every((a) => a.method === "POST" && a.marker === "1")).toBe(true);
  expect(actions[0].body).toEqual({ mode: "tailscale" });
  expect(actions[4].body).toEqual({ mode: "wifi", address: "192.168.50.7" });
  expect(actions.every((a) => !/[?#]/.test(a.url))).toBe(true);
});

test("a delayed status poll cannot overwrite a newer action or clear its pairing code", async ({ page }) => {
  let reads = 0;
  let release!: () => void;
  let received!: () => void;
  const pending = new Promise<void>((resolve) => { release = resolve; });
  const observed = new Promise<void>((resolve) => { received = resolve; });
  const view = (running: boolean) => ({ enabled: running, running, state: running ? "running" : "off",
    mode: "tailscale", address: "http://100.80.1.7:8766", bind_address: "100.80.1.7", port: 8766,
    error: "", paired_devices: 0, addresses: [{ mode: "tailscale", address: "100.80.1.7" }] });
  await page.route("**/api/phone-monitor{,/**}", async (route) => {
    if (route.request().method() === "GET") {
      if (++reads === 2) { received(); await pending; }
      return route.fulfill({ json: view(false) });
    }
    if (route.request().url().endsWith("/pairing")) {
      return route.fulfill({ json: { code: "12345678", expires_at: Date.now() / 1000 + 300,
        address: "http://100.80.1.7:8766" } });
    }
    return route.fulfill({ json: view(true) });
  });
  await page.goto("/#/settings/integrations");
  const panel = page.locator("#int-phone-panel");
  await expect(panel.getByText("Phone dashboard is off")).toBeVisible();
  await page.evaluate(() => document.dispatchEvent(new Event("visibilitychange")));
  await observed;
  await panel.getByRole("button", { name: "Turn on phone dashboard" }).click();
  await panel.getByRole("button", { name: "Get pairing code" }).click();
  await expect(panel.getByLabel("Phone pairing code")).toHaveText("12345678");
  const response = page.waitForResponse((r) => r.url().endsWith("/api/phone-monitor"));
  release(); await response;
  await expect(panel.getByText("Phone dashboard is on")).toBeVisible();
  await expect(panel.getByLabel("Phone pairing code")).toHaveText("12345678");
});
