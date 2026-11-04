import { expect, test } from "@playwright/test";

// The account and consent responses are controlled. Every mutation is intercepted before it reaches the sandbox.
test("public automatic publishing needs explicit channel consent rather than the optional API audit flag",
async ({ page }) => {
  const errors: string[] = [], writes: { path: string; body: any }[] = [];
  page.on("pageerror", error => errors.push(error.message));
  const youtube = { configured: true, connected: true, needs_reconnect: false, name: "Controlled channel",
    account_id: "controlled-public-channel", verified: false, scopes: [], restriction: "" };
  const view = {
    review_before_publish: false,
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

test("fresh YouTube-only setup offers explicit audience and automatic publishing in the posting step",
async ({ page, request }) => {
  const initialStatus = await (await request.get("/api/autopilot/status")).json();
  const errors: string[] = [], writes: { path: string; body: any }[] = [];
  page.on("pageerror", error => errors.push(error.message));
  const youtube = { configured: true, connected: true, needs_reconnect: false, name: "Controlled setup channel",
    account_id: "controlled-setup-channel", verified: false, scopes: [], restriction: "" };
  const tiktok = { configured: false, connected: false, needs_reconnect: false, name: "", scopes: [] };
  const audience = {
    policy_version: 2, summary: "Controlled setup", limits: "Existing posts keep their audience.",
    youtube_steps: "Share private videos in YouTube Studio.", tiktok_steps: "Finish in TikTok.",
    youtube: { platform: "youtube", intent: "SELECTED_AUDIENCE", confirmed: false, confirmed_at: null as number | null,
      label: "Invited viewers", detail: "Private until you share it.", group: "invited", group_version: 1,
      halted: null },
    tiktok: { platform: "tiktok", intent: "SELECTED_AUDIENCE", confirmed: false, confirmed_at: null,
      label: "Approved followers", detail: "Followers only", group: "followers", group_version: 1, halted: null },
  };
  let enabled = false;
  const permission = () => ({
    review_before_publish: false,
    youtube: { supported: true, enabled, can_enable: audience.youtube.confirmed,
      blocker: audience.youtube.confirmed ? "" : "Confirm who watches in Settings → Integrations first.",
      visibility: audience.youtube.intent === "PUBLIC" ? "public" : "private", account_id: youtube.account_id,
      audience_version: audience.youtube.group_version, note: "The returned visibility is checked.",
      consent: enabled ? { id: "controlled-permission", text: "Controlled explicit Public permission",
        settings: { visibility: "public", daily_limit: 3, start_hour: 9, end_hour: 21 } } : null },
    tiktok: { supported: false, enabled: false, consent: null, note: "Your OK is required on each post." },
    verified_project: false, channel: youtube.name, timezone: "UTC",
    defaults: { daily_limit: 3, start_hour: 9, end_hour: 21 },
  });
  await page.route("**/api/**", async route => {
    const request = route.request(), path = new URL(request.url()).pathname;
    if (request.method() !== "GET") {
      const body = request.postDataJSON();
      writes.push({ path, body });
      if (path === "/api/audience/youtube") {
        expect(body).toEqual({ intent: "public", group: "", confirm: true, group_changed: false });
        audience.youtube = { ...audience.youtube, intent: "PUBLIC", confirmed: true, confirmed_at: 100,
          label: "Public audience", group: "public", group_version: 2 };
        return route.fulfill({ json: audience });
      }
      if (path === "/api/autopilot/auto-publish") {
        enabled = true;
        return route.fulfill({ json: permission() });
      }
      return route.fulfill({ status: 409, json: { detail: "Controlled setup; no other action is permitted." } });
    }
    if (path === "/api/autopilot/status") {
      const status = structuredClone(initialStatus);
      status.enabled = false;
      status.platforms = { youtube, tiktok };
      status.home.setup.started = false;
      status.home.setup.topics = "business";
      return route.fulfill({ json: status });
    }
    if (path === "/api/publish/accounts") return route.fulfill({ json: { youtube, tiktok } });
    if (path === "/api/audience") return route.fulfill({ json: audience });
    if (path === "/api/autopilot/auto-publish") return route.fulfill({ json: permission() });
    return route.continue();
  });
  await page.goto("/#/setup/mode");
  await page.getByRole("radio", { name: /Let Autopilot do it/ }).check();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  const row = page.locator(".audience-row");
  await expect(row).toHaveCount(1);
  await expect(row.getByRole("heading", { name: "YouTube", exact: true })).toBeVisible();
  await expect(row).toContainText("Not confirmed: nothing uploads to YouTube");
  expect(writes).toEqual([]);
  await row.getByRole("radio", { name: /^Public audience/ }).check();
  const confirm = row.getByRole("button", { name: "Confirm who watches", exact: true });
  await expect(confirm).toBeDisabled();
  expect(writes).toEqual([]);
  await row.getByRole("checkbox", { name: /^I understand/ }).check();
  await confirm.click();
  await expect(row).toContainText("Public audience · confirmed");
  await page.getByRole("button", { name: "Turn on automatic publishing…", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Turn on automatic publishing for YouTube", exact: true });
  const submit = dialog.getByRole("button", { name: "Turn on automatic publishing", exact: true });
  await expect(submit).toBeDisabled();
  await dialog.getByRole("radio", { name: "No", exact: true }).check();
  await expect(submit).toBeDisabled();
  await dialog.getByRole("checkbox").check();
  await submit.click();
  await expect(dialog).toHaveCount(0);
  await expect(page.getByText("Automatic public publishing on", { exact: true })).toBeVisible();
  expect(writes.map(w => w.path)).toEqual(["/api/audience/youtube", "/api/autopilot/auto-publish"]);
  expect(writes[1].body).toEqual({ platform: "youtube", visibility: "public", made_for_kids: false,
    daily_limit: 3, start_hour: 9, end_hour: 21, agreed: true, expected_account_id: youtube.account_id,
    expected_audience_version: 2 });
  expect(audience.tiktok.confirmed).toBe(false);
  expect(errors).toEqual([]);
});
