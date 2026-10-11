import { expect, test } from "@playwright/test";

// The account and consent responses are controlled. Every mutation is intercepted before it reaches the sandbox.
test("public automatic publishing needs explicit channel consent rather than the optional API audit flag",
async ({ page }) => {
  const errors: string[] = [], writes: { path: string; body: any }[] = [];
  page.on("pageerror", error => errors.push(error.message));
  const youtube = { configured: true, connected: true, needs_reconnect: false, name: "Controlled channel",
    account_id: "controlled-public-channel", verified: false, scopes: [], restriction: "" };
  const view = {
    youtube: { supported: true, enabled: false, can_enable: true, blocker: "", visibility: "public",
      account_id: youtube.account_id, consent: null, note: "The returned visibility is checked." },
    tiktok: { supported: false, enabled: false, consent: null, note: "Your OK is required on each post." },
    verified_project: false, channel: youtube.name, timezone: "UTC",
    defaults: { daily_limit: 3, start_hour: 9, end_hour: 21 },
  };
  await page.route("**/api/**", async route => {
    const request = route.request(), path = new URL(request.url()).pathname;
    if (request.method() !== "GET") {
      writes.push({ path, body: request.postDataJSON() });
      return route.fulfill({ status: 409, json: { detail: "Controlled preview; no permission or post was saved." } });
    }
    if (path === "/api/autopilot/auto-publish") return route.fulfill({ json: view });
    if (path === "/api/publish/accounts") return route.fulfill({ json: {
      youtube, tiktok: { configured: false, connected: false, needs_reconnect: false, name: "", scopes: [] },
    } });
    if (path === "/api/audience") return route.fulfill({ json: {
      youtube: { intent: "PUBLIC", visibility: "public", confirmed: true, label: "Public audience", group_version: 7 },
      tiktok: { intent: "LOCAL_ONLY", confirmed: false, label: "Local clips" },
    } });
    return route.continue(); // Ordinary read-only settings and status from the disposable app.
  });
  await page.goto("/#/settings");
  await expect(page.getByRole("heading", { name: "YouTube", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Turn on automatic publishing…", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Turn on automatic publishing for YouTube", exact: true });
  const submit = dialog.getByRole("button", { name: "Turn on automatic publishing", exact: true });
  await expect(dialog.getByText("Public: anyone can watch, including people who do not follow your channel."))
    .toBeVisible();
  await expect(dialog.getByText("Automatic publishing needs setup", { exact: true })).toHaveCount(0);
  await expect(submit).toBeDisabled();
  await dialog.getByRole("radio", { name: "No", exact: true }).check();
  await expect(submit).toBeDisabled();
  expect(writes).toEqual([]);
  await dialog.getByRole("checkbox").check();
  await expect(submit).toBeEnabled();
  await submit.click();
  await expect(dialog.getByRole("alert")).toContainText("Controlled preview");
  expect(writes).toEqual([{ path: "/api/autopilot/auto-publish", body: {
    platform: "youtube", visibility: "public", made_for_kids: false, daily_limit: 3, start_hour: 9, end_hour: 21,
    agreed: true, expected_account_id: youtube.account_id, expected_audience_version: 7,
  } }]);
  expect(errors).toEqual([]);
});
