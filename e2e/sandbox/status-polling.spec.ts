import { expect, test, APIRequestContext, Page, Route } from "@playwright/test";

// Responses are controlled in this browser only. The sandbox's accounts and Autopilot settings stay unchanged.
async function controlled(page: Page, request: APIRequestContext) {
  const status = await (await request.get("/api/autopilot/status")).json();
  status.enabled = true;
  status.paused = false;
  status.home.setup.started = true;
  status.home.needs_you = [];
  let hold = false;
  let calls = 0;
  const held: Route[] = [];
  await page.route("**/api/autopilot/status", (route) => {
    calls += 1;
    if (hold) held.push(route);
    else return route.fulfill({ json: status });
  });
  await page.clock.install();
  await page.goto("/#/autopilot");
  await expect(page.getByRole("heading", { name: "Autopilot is on", exact: true })).toBeVisible();
  await page.clock.pauseAt(new Date(await page.evaluate(() => Date.now()) + 1000));
  return { status, held, calls: () => calls, hold: (value: boolean) => { hold = value; } };
}

async function visible(page: Page, value: boolean) {
  await page.evaluate((shown) => {
    Object.defineProperty(document, "hidden", { configurable: true, value: !shown });
    document.dispatchEvent(new Event("visibilitychange"));
  }, value);
}

test("returning to a tab during a status request keeps one polling loop", async ({ page, request }) => {
  const poll = await controlled(page, request);
  poll.hold(true);
  await page.clock.runFor(3000);
  await expect.poll(() => poll.held.length).toBe(1);
  const before = poll.calls();
  for (let i = 0; i < 3; i += 1) {
    await visible(page, false);
    await visible(page, true);
  }
  await page.waitForTimeout(150);
  expect(poll.calls()).toBe(before);

  poll.hold(false);
  await poll.held[0].fulfill({ json: poll.status });
  await expect.poll(poll.calls).toBe(before + 1);
  await page.clock.runFor(3000);
  await expect.poll(poll.calls).toBe(before + 2);
  await page.waitForTimeout(150);
  expect(poll.calls()).toBe(before + 2);
});

test("an older status response cannot undo a successful Pause action", async ({ page, request }) => {
  const poll = await controlled(page, request);
  poll.hold(true);
  await page.clock.runFor(3000);
  await expect.poll(() => poll.held.length).toBe(1);
  const stale = structuredClone(poll.status);
  await page.route("**/api/autopilot/enable", (route) => {
    poll.status.enabled = false;
    return route.fulfill({ json: poll.status });
  });
  await page.getByRole("button", { name: "Pause Autopilot", exact: true }).click();
  const paused = page.getByRole("heading", { name: "Autopilot is paused", exact: true });
  await expect(paused).toBeVisible();
  poll.hold(false);
  await poll.held[0].fulfill({ json: stale });
  await page.waitForTimeout(150);
  await expect(paused).toBeVisible();
  await expect(page.locator("#top-state")).toHaveText("Autopilot: Paused");
});

test("an older failed poll cannot mark a successful Pause action disconnected", async ({ page, request }) => {
  const poll = await controlled(page, request);
  poll.hold(true);
  await page.clock.runFor(3000);
  await expect.poll(() => poll.held.length).toBe(1);
  await page.route("**/api/autopilot/enable", (route) => {
    poll.status.enabled = false;
    return route.fulfill({ json: poll.status });
  });
  await page.getByRole("button", { name: "Pause Autopilot", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Autopilot is paused", exact: true })).toBeVisible();
  await poll.held[0].abort();
  await page.waitForTimeout(150);
  await page.clock.runFor(3000);
  await expect.poll(() => poll.held.length).toBe(2);
  await poll.held[1].abort();
  await page.waitForTimeout(150);
  await expect(page.getByText("ClipFoundry is not answering", { exact: true })).toHaveCount(0);
  await page.clock.runFor(3000);
  await expect.poll(() => poll.held.length).toBe(3);
  await poll.held[2].abort();
  await expect(page.getByText("ClipFoundry is not answering", { exact: true })).toBeVisible();
});

test("hidden tabs poll every fifteen seconds and returning wakes the status", async ({ page, request }) => {
  const poll = await controlled(page, request);
  poll.hold(true);
  await page.clock.runFor(3000);
  await expect.poll(() => poll.held.length).toBe(1);
  await visible(page, false);
  const before = poll.calls();
  await poll.held[0].fulfill({ json: poll.status });
  await page.waitForTimeout(150);
  await page.clock.runFor(14999);
  expect(poll.calls()).toBe(before);
  await page.clock.runFor(1);
  await expect.poll(poll.calls).toBe(before + 1);
  await poll.held[1].fulfill({ json: poll.status });
  await page.waitForTimeout(150);
  await visible(page, true);
  await expect.poll(poll.calls).toBe(before + 2);
});

test("Local test mode saves on the overview and stays on after reload", async ({ page, request }) => {
  const headers = { "X-ClipFoundry": "1" };
  await request.put("/api/settings", { headers, data: { autopilot_local_test_mode: false } });
  const writes: unknown[] = [];
  page.on("request", (req) => {
    if (req.method() === "PUT" && req.url().endsWith("/api/settings")) writes.push(req.postDataJSON());
  });
  try {
    await page.goto("/#/autopilot");
    const mode = page.getByRole("switch", { name: "Local test mode", exact: true });
    await expect(mode).not.toBeChecked();
    await expect(page.getByText("All uploads are off while this is on.", { exact: true })).toBeVisible();
    await mode.click();
    await expect(mode).toBeChecked();
    expect(writes).toEqual([{ autopilot_local_test_mode: true }]);
    expect((await (await request.get("/api/settings")).json()).autopilot_local_test_mode).toBe(true);
    await expect(page.locator(".page-head")).toContainText("Clips stay on this PC. All uploads are off.");
    await page.reload();
    await expect(mode).toBeChecked();
    await mode.click();
    await expect(mode).not.toBeChecked();
    expect(writes).toEqual([{ autopilot_local_test_mode: true }, { autopilot_local_test_mode: false }]);
  } finally {
    await request.put("/api/settings", { headers, data: { autopilot_local_test_mode: false } });
  }
});

test("Local test mode is named and saved by the Advanced settings save bar", async ({ page, request }) => {
  const headers = { "X-ClipFoundry": "1" };
  await request.put("/api/settings", { headers, data: { autopilot_local_test_mode: false } });
  try {
    await page.goto("/#/settings/advanced");
    await page.getByRole("switch", { name: "Local test mode", exact: true }).click();
    await expect(page.getByText("Unsaved changes: Local test mode", { exact: true })).toBeVisible();
    await page.getByRole("button", { name: "Save settings", exact: true }).click();
    await expect(page.getByText("Saved", { exact: true })).toBeVisible();
    expect((await (await request.get("/api/settings")).json()).autopilot_local_test_mode).toBe(true);
    await page.goto("/#/autopilot");
    await expect(page.getByRole("switch", { name: "Local test mode", exact: true })).toBeChecked();
  } finally {
    await request.put("/api/settings", { headers, data: { autopilot_local_test_mode: false } });
  }
});

test("a failed Local test mode save keeps the confirmed setting off", async ({ page, request }) => {
  const headers = { "X-ClipFoundry": "1" };
  await request.put("/api/settings", { headers, data: { autopilot_local_test_mode: false } });
  await page.route("**/api/settings", (route) => route.request().method() === "PUT"
    ? route.fulfill({ status: 503, json: { detail: "Settings could not be saved. Try again." } })
    : route.continue());
  await page.goto("/#/autopilot");
  const mode = page.getByRole("switch", { name: "Local test mode", exact: true });
  await expect(mode).not.toBeChecked();
  await mode.click();
  await expect(page.locator(".toast")).toHaveText("Settings could not be saved. Try again.");
  await expect(page.locator(".toast")).toBeVisible();
  await expect(mode).not.toBeChecked();
  await expect(mode).toBeEnabled();
  expect((await (await request.get("/api/settings")).json()).autopilot_local_test_mode).toBe(false);
});

test("Local test mode shows three local clip links and preserves earlier upload history", async ({ page, request }) => {
  const poll = await controlled(page, request);
  poll.status.settings.autopilot_local_test_mode = true;
  poll.status.home.local_test_mode = true;
  poll.status.home.local_ready = Array.from({ length: 4 }, (_, n) => ({
    id: `local-${n}`, title: `Local clip ${n}`, project_id: `project-${n}`,
  }));
  poll.status.home.upcoming = [
    { id: "pending", title: "Pending test post", platform: "youtube", planned_at: Date.now() / 1000 + 3600,
      status: "approved", auto: false, on_platform: false },
    { id: "earlier", title: "Earlier upload", platform: "youtube", planned_at: Date.now() / 1000 + 3600,
      status: "published", auto: false, on_platform: true },
    { id: "draft", title: "TikTok draft needing attention", platform: "tiktok", planned_at: null,
      status: "action_needed", auto: false, on_platform: false },
  ];
  await page.clock.runFor(3000);
  await expect(page.getByRole("heading", { name: "Local clips", exact: true })).toBeVisible();
  for (let n = 0; n < 3; n += 1) {
    await expect(page.getByRole("link", { name: `Local clip ${n}`, exact: true }))
      .toHaveAttribute("href", `#/clip/local-${n}`);
  }
  await expect(page.getByRole("link", { name: "Local clip 3", exact: true })).toHaveCount(0);
  await expect(page.getByRole("link", { name: "Pending test post", exact: true })).toHaveCount(0);
  await expect(page.getByRole("link", { name: "Earlier upload", exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: "TikTok draft needing attention", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Turn on automatic publishing…", exact: true })).toHaveCount(0);
});

test("Local test setup starts without a topic and keeps uploads off", async ({ page, request }) => {
  const headers = { "X-ClipFoundry": "1" };
  const before = await (await request.get("/api/settings")).json();
  await request.put("/api/settings", { headers, data: {
    autopilot_local_test_mode: true, autopilot_enabled: false, trend_topics: "setup test topic",
  } });
  const status = await (await request.get("/api/autopilot/status")).json();
  status.enabled = false;
  status.paused = false;
  status.home.setup.started = false;
  status.platforms.youtube.connected = false;
  status.platforms.tiktok.connected = false;
  let started: unknown;
  let submitted: unknown;
  await page.route("**/api/autopilot/status", (route) => route.fulfill({ json: started || status }));
  await page.route("**/api/autopilot/start", async (route) => {
    submitted = route.request().postDataJSON();
    const response = await route.fetch();
    expect(response.ok()).toBe(true);
    started = await response.json();
    await route.fulfill({ response, json: started });
  });
  try {
    await page.goto("/#/autopilot");
    await expect(page.locator('section[aria-labelledby="ap-off"]')).toContainText("all uploads are off");
    await page.goto("/#/setup/videos");
    await expect(page.getByText(/Local test mode lets Autopilot find public videos/)).toBeVisible();
    await expect(page.getByText(/ClipFoundry never uses other people's videos/)).toHaveCount(0);
    await page.getByRole("link", { name: "Continue", exact: true }).click();
    await page.getByRole("radio", { name: /Let Autopilot do it/ }).check();
    await page.getByRole("textbox", { name: "Topics", exact: true }).fill("");
    await expect(page.getByText("Choose topics, or leave this empty to look for videos on any topic.",
      { exact: true })).toBeVisible();
    await page.getByRole("button", { name: "Continue", exact: true }).click();
    await expect(page).toHaveURL(/#\/setup\/posting$/);
    await expect(page.getByRole("heading", { name: "Find videos for local testing", exact: true })).toBeVisible();
    await expect(page.getByText(/TikTok is not needed for local testing/)).toBeVisible();
    await expect(page.getByText("Finds public videos for local clips.", { exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "Connect TikTok", exact: true })).toHaveCount(0);
    await expect(page.getByText(/turn on automatic publishing later/)).toHaveCount(0);
    await page.getByRole("button", { name: "Start Autopilot", exact: true }).click();
    await expect(page).toHaveURL(/#\/$/);
    await expect(page.locator(".page-head").getByRole("link", { name: "Autopilot: On" })).toBeVisible();
    expect(submitted).toEqual({ topics: "" });
    const saved = await (await request.get("/api/settings")).json();
    expect(saved.trend_topics).toBe("");
    expect(saved.autopilot_enabled).toBe(true);
    expect(saved.autopilot_local_test_mode).toBe(true);
  } finally {
    await request.put("/api/settings", { headers, data: {
      autopilot_local_test_mode: before.autopilot_local_test_mode, autopilot_enabled: before.autopilot_enabled,
      trend_topics: before.trend_topics, setup_mode: before.setup_mode,
    } });
  }
});
