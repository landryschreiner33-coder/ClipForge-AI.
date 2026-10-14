import { expect, test } from "@playwright/test";

// Mutations are intercepted; this suite always runs against the disposable sandbox.
test("unlimited automatic publishing keeps explicit account, audience and kids consent",
async ({ page }) => {
  const errors: string[] = [], writes: { path: string; body: any }[] = [];
  page.on("pageerror", error => errors.push(error.message));
  const youtube = { configured: true, connected: true, needs_reconnect: false, name: "Controlled channel",
    account_id: "controlled-continuous-channel", verified: false, scopes: [], restriction: "" };
  await page.route("**/api/**", async route => {
    const request = route.request(), path = new URL(request.url()).pathname;
    if (request.method() !== "GET") {
      writes.push({ path, body: request.postDataJSON() });
      return route.fulfill({ status: 409, json: { detail: "Controlled preview; nothing saved." } });
    }
    if (path === "/api/autopilot/auto-publish") return route.fulfill({ json: {
      review_before_publish: false,
      youtube: { supported: true, enabled: false, can_enable: true, blocker: "", visibility: "public",
        account_id: youtube.account_id, consent: null },
      tiktok: { supported: false, enabled: false, consent: null, note: "Your OK is required on each post." },
      channel: youtube.name, timezone: "UTC", defaults: { daily_limit: 0, start_hour: 0, end_hour: 24 },
    } });
    if (path === "/api/publish/accounts") return route.fulfill({ json: {
      youtube, tiktok: { configured: false, connected: false, needs_reconnect: false, name: "", scopes: [] },
    } });
    if (path === "/api/audience") return route.fulfill({ json: {
      youtube: { intent: "PUBLIC", confirmed: true, label: "Public audience", group_version: 11 },
      tiktok: { intent: "LOCAL_ONLY", confirmed: false, label: "Local clips" },
    } });
    return route.continue();
  });
  await page.goto("/#/settings");
  await page.getByRole("button", { name: "Turn on automatic publishing…", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Turn on automatic publishing for YouTube", exact: true });
  const submit = dialog.getByRole("button", { name: "Turn on automatic publishing", exact: true });
  await expect(dialog.getByRole("spinbutton", { name: "Posts a day at most" })).toHaveValue("0");
  await expect(dialog.getByText(/No app daily cap/)).toBeVisible();
  await expect(dialog.getByText(/Any hour/)).toBeVisible();
  await expect(submit).toBeDisabled();
  await dialog.getByRole("radio", { name: "No", exact: true }).check();
  await expect(submit).toBeDisabled();
  expect(writes).toEqual([]);
  await dialog.getByRole("checkbox").check();
  await expect(submit).toBeEnabled();
  await submit.click();
  await expect(dialog.getByRole("alert")).toContainText("Controlled preview");
  expect(writes).toEqual([{ path: "/api/autopilot/auto-publish", body: {
    platform: "youtube", visibility: "public", made_for_kids: false, daily_limit: 0, start_hour: 0, end_hour: 24,
    agreed: true, expected_account_id: youtube.account_id, expected_audience_version: 11,
  } }]);
  expect(errors).toEqual([]);
});

test("daily cap zero is valid in Settings and is saved without replacing it with a target",
async ({ page, request }) => {
  const settings = await (await request.get("/api/settings")).json();
  settings.autopilot_daily_target = 15;
  const writes: { path: string; body: any }[] = [];
  await page.route("**/api/settings", async route => {
    if (route.request().method() === "GET") return route.fulfill({ json: settings });
    writes.push({ path: new URL(route.request().url()).pathname, body: route.request().postDataJSON() });
    return route.fulfill({ status: 409, json: { detail: "Controlled settings preview." } });
  });
  await page.goto("/#/settings/defaults");
  await page.getByRole("spinbutton", { name: "Daily clip cap", exact: true }).fill("0");
  const save = page.getByRole("button", { name: "Save settings", exact: true });
  await expect(save).toBeEnabled();
  await save.click();
  expect(writes).toEqual([{ path: "/api/settings", body: { autopilot_daily_target: 0 } }]);
});

test("Missions explains local-only clips and concrete paths to eligible uploads",
async ({ page, request }) => {
  const initialStatus = await (await request.get("/api/autopilot/status")).json();
  const errors: string[] = [], writes: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  await page.route("**/api/autopilot/status", async route => {
    const status = structuredClone(initialStatus);
    status.enabled = true; status.paused = false; status.workers_alive = true;
    status.home.setup.started = true;
    status.home.posting = { finished: 3, checked: 3, sampled: false, source_guidance: {
      uploadable_only: true, title: "Find videos you can upload", detail: "Automatic searches now prefer permitted sources.",
      options: [
        { title: "Use your original videos", detail: "Add videos you made to the watched folder.", link: "#/missions" },
        { title: "Record creator permission", detail: "Use a valid agreement and the original media.", link: "#/missions/sources" },
        { title: "Search free-license videos", detail: "Confirmed licenses and quality checks still apply.", link: "#/settings/advanced" },
      ],
    }, platforms: [{ platform: "youtube", code: "local_only", title: "These clips are local only",
      detail: "These sources have no recorded reuse permission for YouTube.", link: "#/missions/sources", automatic: true,
      counts: { preparing: 0, checking: 0, failed_check: 0, local_only: 3, ready: 0, scheduled: 0 },
    }] };
    await route.fulfill({ json: status });
  });
  page.on("request", request => {
    if (new URL(request.url()).pathname.startsWith("/api/") && request.method() !== "GET") writes.push(request.method());
  });
  await page.goto("/#/missions");
  const panel = page.getByRole("region", { name: "Why clips are waiting to post" });
  await expect(panel.getByText("These clips are local only", { exact: true })).toBeVisible();
  await expect(panel.getByRole("heading", { name: "Find videos you can upload" })).toBeVisible();
  await expect(panel.getByRole("link", { name: "Record creator permission" })).toHaveAttribute("href", "#/missions/sources");
  await expect(panel.getByRole("link", { name: "Search free-license videos" })).toHaveAttribute("href", "#/settings/advanced");
  expect(writes).toEqual([]);
  expect(errors).toEqual([]);
});
