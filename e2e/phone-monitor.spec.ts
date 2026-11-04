import { test, expect, type Page } from "@playwright/test";
import { mkdir } from "node:fs/promises";
import { join } from "node:path";

// This is a visibly artificial grant used only by intercepted requests, never an account or device credential.
const testGrant = "0000000000000000000000000000000000000000000";
const now = 1791896400;
const snapshot = {
  version: "0.1-test",
  server_time: now,
  timezone: "America/Chicago",
  run: { state: "running", label: "Running", publishing_paused: false },
  workers: { alive: true, heartbeat_at: now - 2 },
  currently: "Making clips from your videos.",
  working: { title: "The surprising science of sleep", step: "Rendering captions", progress: 0.42 as number | null },
  today: { daily: 15, published: 2, scheduled: 3, published_posts: 4, scheduled_posts: 5, processed: 7 },
  posts: { review: 1, fix: 2, ready: 4, scheduled: 3 },
  next_post: { platform: "youtube", title: "Why your brain needs sleep", planned_at: now + 1800, status: "approved" },
  health: { status: "healthy", label: "Everything looks good", checked_at: now - 5 },
  health_checks: [{ id: "workers", label: "Background work", status: "healthy", checked_at: now - 5 }],
  needs_you: [{ kind: "approve", title: "A post needs approval on your PC" }],
  desktop_note: "Use ClipFoundry on your PC to make changes.",
};

type Mode = "ready" | "offline" | "unauthorized";
type Call = { method: string; path: string; url: string; authorization: string; body?: unknown };

async function controlledApi(page: Page) {
  const state = {
    mode: "ready" as Mode,
    pairError: "",
    pairStatus: 400,
    data: structuredClone(snapshot),
    calls: [] as Call[],
    unexpected: [] as string[],
    errors: [] as string[],
  };
  page.on("pageerror", (error) => state.errors.push(error.message));
  page.on("console", (message) => {
    if (message.type() === "error" && !message.text().startsWith("Failed to load resource")) {
      state.errors.push(message.text());
    }
  });
  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    state.calls.push({
      method: request.method(), path, url: request.url(),
      authorization: request.headers().authorization || "",
      body: request.method() === "POST" ? request.postDataJSON() : undefined,
    });
    if (path === "/api/pair" && request.method() === "POST") {
      if (state.pairError) return route.fulfill({ status: state.pairStatus, json: { detail: state.pairError } });
      return route.fulfill({ json: { token: testGrant, expires_at: Math.floor(Date.now() / 1000) + 90 * 86400 } });
    }
    if (path === "/api/status" && request.method() === "GET") {
      if (state.mode === "offline") return route.abort("failed");
      if (state.mode === "unauthorized") {
        return route.fulfill({ status: 401, json: { detail: "Pair this phone again from your PC." } });
      }
      return route.fulfill({ json: state.data });
    }
    state.unexpected.push(`${request.method()} ${path}`);
    return route.fulfill({ status: 404, json: { detail: "No other API exists in this isolated test." } });
  });
  return state;
}

async function connect(page: Page, remember = false) {
  await page.goto("/");
  await page.getByLabel("Pairing code", { exact: true }).fill("12345678");
  await page.getByLabel("Remember this phone", { exact: true }).setChecked(remember);
  await page.getByRole("button", { name: "Connect phone", exact: true }).click();
  await expect(page.getByText(snapshot.currently, { exact: true })).toBeVisible();
}

async function refresh(page: Page) {
  const button = page.getByRole("button", { name: /refresh/i });
  if (await button.count()) await button.first().click();
  else await page.clock.runFor(15_000);
}

async function stores(page: Page) {
  return page.evaluate(() => ({
    local: Object.values(localStorage),
    session: Object.values(sessionStorage),
  }));
}

async function preview(page: Page, name: string) {
  const directory = process.env.CLIPFOUNDRY_PHONE_PREVIEW_DIR;
  if (!directory) return;
  await mkdir(directory, { recursive: true });
  await page.screenshot({ path: join(directory, name), fullPage: true });
}

test("pairs on a narrow phone and keeps the grant in headers, with escaped media titles", async ({ page }) => {
  const state = await controlledApi(page);
  const unsafeTitle = '<img src=x onerror="window.phoneInjection=true">';
  state.data.next_post!.title = unsafeTitle;
  await page.goto("/");
  await expect(page.getByLabel("Pairing code", { exact: true })).toBeVisible();
  expect(state.calls).toEqual([]);
  await preview(page, "phone-pairing-controlled.png");
  await page.getByLabel("Pairing code", { exact: true }).fill("12345678");
  await page.getByRole("button", { name: "Connect phone", exact: true }).click();
  await expect(page.getByText(snapshot.currently, { exact: true })).toBeVisible();
  await expect(page.getByText(unsafeTitle, { exact: true })).toBeVisible();
  expect(await page.evaluate(() => "phoneInjection" in window)).toBe(false);
  expect(state.calls.find((call) => call.path === "/api/pair")?.body).toEqual({ code: "12345678" });
  const status = state.calls.filter((call) => call.path === "/api/status");
  expect(status.length).toBeGreaterThan(0);
  expect(status.every((call) => call.authorization === `Bearer ${testGrant}`)).toBe(true);
  expect(state.calls.every((call) => !call.url.includes(testGrant) && !call.url.includes("12345678"))).toBe(true);
  expect(page.url()).not.toContain(testGrant);
  expect(page.url()).not.toContain("12345678");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  expect(state.unexpected).toEqual([]);
  expect(state.errors).toEqual([]);
});

test("an expired or already used pairing code leaves the phone unconnected", async ({ page }) => {
  const state = await controlledApi(page);
  state.pairError = "This pairing code expired or was already used. Create a new code on your PC.";
  await page.goto("/");
  await page.getByLabel("Pairing code", { exact: true }).fill("12345678");
  await page.getByRole("button", { name: "Connect phone", exact: true }).click();
  await expect(page.getByText(/expired or already used/i)).toBeVisible();
  await expect(page.getByLabel("Pairing code", { exact: true })).toBeVisible();
  expect(state.calls.some((call) => call.path === "/api/status")).toBe(false);
  expect(await stores(page)).toEqual({ local: [], session: [] });
  expect(state.unexpected).toEqual([]);
  expect(state.errors).toEqual([]);
});

test("pairing throttling explains the wait and makes no status request", async ({ page }) => {
  const state = await controlledApi(page);
  state.pairError = "Too many pairing attempts. Wait a minute, then try again.";
  state.pairStatus = 429;
  await page.goto("/");
  await page.getByLabel("Pairing code", { exact: true }).fill("12345678");
  await page.getByRole("button", { name: "Connect phone", exact: true }).click();
  await expect(page.getByText(/too many|wait a minute/i)).toBeVisible();
  expect(state.calls.some((call) => call.path === "/api/status")).toBe(false);
  expect(state.unexpected).toEqual([]);
  expect(state.errors).toEqual([]);
});

test("measured progress is shown and missing progress stays unknown", async ({ page }) => {
  const state = await controlledApi(page);
  await connect(page);
  await expect(page.getByText(snapshot.working.title, { exact: true })).toBeVisible();
  await expect(page.getByRole("progressbar")).toHaveAttribute("value", "42");
  await expect(page.locator("#published")).toHaveText(String(snapshot.today.published));
  await expect(page.locator("#published-posts")).toHaveText(`${snapshot.today.published_posts} platform posts`);
  await expect(page.locator("#scheduled")).toHaveText(String(snapshot.today.scheduled));
  await expect(page.locator("#scheduled-posts")).toHaveText(`${snapshot.today.scheduled_posts} platform posts`);
  await preview(page, "phone-dashboard-controlled.png");
  state.data.working.progress = null;
  await refresh(page);
  await expect(page.getByRole("progressbar")).toHaveCount(0);
  await expect(page.getByText(snapshot.working.title, { exact: true })).toBeVisible();
  expect(state.unexpected).toEqual([]);
  expect(state.errors).toEqual([]);
});

test("a lost connection labels the retained snapshot as stale and recovers truthfully", async ({ page }) => {
  await page.clock.install();
  const state = await controlledApi(page);
  await connect(page);
  state.mode = "offline";
  await refresh(page);
  await expect(page.locator("#connection")).toHaveText(/not live|not updating|offline|reconnecting|lost|unavailable/i);
  await expect(page.getByText(snapshot.working.title, { exact: true })).toBeVisible();
  state.mode = "ready";
  state.data.currently = "Waiting for your next video.";
  await refresh(page);
  await expect(page.getByText(state.data.currently, { exact: true })).toBeVisible();
  await expect(page.locator("#connection")).toHaveText(/live|connected|up to date/i);
  expect(state.unexpected).toEqual([]);
  expect(state.errors).toEqual([]);
});

test("revoked access clears retained private titles and browser grants", async ({ page }) => {
  await page.clock.install();
  const state = await controlledApi(page);
  await connect(page, true);
  state.mode = "unauthorized";
  await refresh(page);
  await expect(page.getByLabel("Pairing code", { exact: true })).toBeVisible();
  await expect(page.getByText(snapshot.working.title, { exact: true })).toHaveCount(0);
  await expect(page.getByText(snapshot.next_post.title, { exact: true })).toHaveCount(0);
  const saved = await stores(page);
  expect([...saved.local, ...saved.session].some((value) => value.includes(testGrant))).toBe(false);
  expect(state.unexpected).toEqual([]);
  expect(state.errors).toEqual([]);
});

test("remembering a phone survives a new browser session without exposing its grant in the address", async ({
  page, browser, baseURL,
}) => {
  const state = await controlledApi(page);
  await connect(page, true);
  const saved = await stores(page);
  expect(saved.local.some((value) => value.includes(testGrant))).toBe(true);
  const newContext = await browser.newContext({ storageState: await page.context().storageState(), baseURL });
  try {
    const newPage = await newContext.newPage();
    const restarted = await controlledApi(newPage);
    await newPage.goto("/");
    await expect(newPage.getByText(snapshot.currently, { exact: true })).toBeVisible();
    expect(restarted.calls.some((call) => call.path === "/api/pair")).toBe(false);
    expect(restarted.calls.every((call) => !call.url.includes(testGrant))).toBe(true);
    expect(restarted.unexpected).toEqual([]);
    expect(restarted.errors).toEqual([]);
  } finally {
    await newContext.close();
  }
  expect(state.unexpected).toEqual([]);
  expect(state.errors).toEqual([]);
});

test("temporary pairing survives reload but another browser session needs its own code", async ({
  page, browser, baseURL,
}) => {
  const state = await controlledApi(page);
  await connect(page, false);
  const saved = await stores(page);
  expect(saved.local.some((value) => value.includes(testGrant))).toBe(false);
  expect(saved.session.some((value) => value.includes(testGrant))).toBe(true);
  await page.reload();
  await expect(page.getByText(snapshot.currently, { exact: true })).toBeVisible();
  expect(state.calls.filter((call) => call.path === "/api/pair")).toHaveLength(1);
  const newContext = await browser.newContext({ storageState: await page.context().storageState(), baseURL });
  try {
    const newPage = await newContext.newPage();
    const restarted = await controlledApi(newPage);
    await newPage.goto("/");
    await expect(newPage.getByLabel("Pairing code", { exact: true })).toBeVisible();
    expect(restarted.calls).toEqual([]);
    expect(restarted.errors).toEqual([]);
  } finally {
    await newContext.close();
  }
  expect(state.unexpected).toEqual([]);
  expect(state.errors).toEqual([]);
});

test("disconnecting forgets this browser and clears the status without desktop mutations", async ({ page }) => {
  await page.clock.install();
  const state = await controlledApi(page);
  await connect(page, true);
  const callsBefore = state.calls.length;
  await page.getByRole("button", { name: "Disconnect this phone", exact: true }).click();
  await expect(page.getByLabel("Pairing code", { exact: true })).toBeVisible();
  await expect(page.getByText(snapshot.working.title, { exact: true })).toHaveCount(0);
  await page.clock.runFor(30_000);
  expect(state.calls).toHaveLength(callsBefore);
  const saved = await stores(page);
  expect([...saved.local, ...saved.session].some((value) => value.includes(testGrant))).toBe(false);
  expect(state.calls.filter((call) => call.method !== "GET").map((call) => call.path)).toEqual(["/api/pair"]);
  expect(state.unexpected).toEqual([]);
  expect(state.errors).toEqual([]);
});

test("backgrounding the page pauses polling and foregrounding refreshes the status", async ({ page }) => {
  await page.clock.install();
  const state = await controlledApi(page);
  await connect(page);
  const callsBefore = state.calls.length;
  // Deliver a controlled visibility transition rather than relying on headless window-manager behavior.
  await page.evaluate(() => {
    Object.defineProperty(document, "hidden", { configurable: true, get: () => true });
    document.dispatchEvent(new Event("visibilitychange"));
  });
  await expect(page.locator("#connection")).toHaveText("Not live");
  await expect(page.locator("#stale")).toHaveText(/background/i);
  await page.clock.runFor(30_000);
  expect(state.calls).toHaveLength(callsBefore);
  state.data.currently = "Foregrounding has fetched this fresh status.";
  await page.evaluate(() => {
    Object.defineProperty(document, "hidden", { configurable: true, get: () => false });
    document.dispatchEvent(new Event("visibilitychange"));
  });
  await expect(page.getByText(state.data.currently, { exact: true })).toBeVisible();
  await expect(page.locator("#connection")).toHaveText("Live");
  expect(state.calls).toHaveLength(callsBefore + 1);
  expect(state.unexpected).toEqual([]);
  expect(state.errors).toEqual([]);
});
