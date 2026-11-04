import { expect, Page, test } from "@playwright/test";
import type { Settings } from "../../frontend/src/api";

// All writes are intercepted. The app's disposable status supplies its full shape; discovery evidence is controlled.
async function discovery(page: Page, initial: Settings = {}) {
  let settings: Settings = {
    tavily_api_key: "********", tavily_free_credits: 2000, discovery_monthly_budget_usd: 7,
    autopilot_daily_target: 12, default_visibility: "private", youtube_client_secret: "********",
    ...initial,
  };
  const writes: { path: string; method: string; body: Settings }[] = [];
  const errors: string[] = [];
  const response = await page.request.get("/api/autopilot/status");
  expect(response.ok()).toBe(true);
  const status = await response.json();
  page.on("pageerror", error => errors.push(error.message));
  await page.route("**/api/**", async route => {
    const request = route.request(), path = new URL(request.url()).pathname;
    if (request.method() !== "GET") {
      const body = request.postDataJSON() as Settings;
      writes.push({ path, method: request.method(), body });
      if (path === "/api/settings" && request.method() === "PUT") {
        settings = { ...settings, ...body };
        for (const key of ["tavily_api_key", "youtube_api_key"]) {
          if (body[key]) settings[key] = "********";
        }
        return route.fulfill({ json: settings });
      }
      return route.fulfill({ status: 409, json: { detail: "Only controlled discovery settings are accepted." } });
    }
    if (path === "/api/settings") return route.fulfill({ json: settings });
    if (path === "/api/autopilot/status") {
      return route.fulfill({ json: {
        ...status,
        discovery_shortlist: {
          enabled: true, checked: 20, admitted: 3, held: 5, filtered: 12, backlog: 3,
          daily_attempts_remaining: 4, message: "A few strong candidates were kept; other finds wait.",
          reasons: { "Below the discovery estimate": 8, "Already checked": 4, "Shortlist limit": 5 },
        },
        web_search: { used: 27, free: 2000, allowed: 2000, budget_usd: 7, cost_usd: 0, month: "2026-10" },
      } });
    }
    return route.continue();
  });
  await page.goto("/#/missions/sources");
  const panel = page.getByRole("region", { name: "Quality before quantity", exact: true });
  await expect(panel.getByLabel("New finds per search", { exact: false })).toBeEnabled();
  return { panel, writes, settings: () => settings, errors };
}

test("discovery shows the focused defaults and recorded reasons, and saves only the changed choice",
async ({ page }) => {
  const fixture = await discovery(page), { panel, writes } = fixture;
  await expect(panel.getByRole("checkbox", { name: /Use a focused shortlist/ })).toBeChecked();
  await expect(panel.getByLabel("New finds per search", { exact: false })).toHaveValue("3");
  await expect(panel.getByLabel("Minimum discovery estimate", { exact: false })).toHaveValue("50");
  await panel.getByText("Shortlist limits", { exact: true }).click();
  await expect(panel.getByLabel("Unfinished finds before waiting", { exact: false })).toHaveValue("6");
  await expect(panel.getByLabel("New finds from one creator", { exact: false })).toHaveValue("1");
  const summary = panel.getByLabel("Last discovery shortlist", { exact: true });
  await expect(summary).toContainText("20 considered");
  await expect(summary).toContainText("3 shortlisted");
  await expect(summary).toContainText("12 filtered");
  await expect(summary).toContainText("5 held");
  await summary.getByText("Why others were left out", { exact: true }).click();
  await expect(summary.getByRole("listitem")).toHaveText([
    "Below the discovery estimate · 8", "Already checked · 4", "Shortlist limit · 5",
  ]);
  await expect(panel).toContainText("Search scores are estimates");
  await panel.getByText("Find better links with a free search key", { exact: true }).click();
  await expect(panel.getByText("A key is already saved on this PC.", { exact: true })).toBeVisible();
  await expect(panel.getByLabel("Tavily API key", { exact: false })).toHaveValue("");
  await panel.getByLabel("New finds per search", { exact: false }).fill("2");
  await panel.getByRole("button", { name: "Save discovery choices", exact: true }).click();
  await expect(page.locator(".toast").getByText("Discovery choices saved for the next search")).toBeVisible();
  expect(writes).toEqual([{ path: "/api/settings", method: "PUT", body: { discovery_candidates_per_scan: 2 } }]);
  expect(fixture.settings()).toMatchObject({
    tavily_api_key: "********", tavily_free_credits: 2000, discovery_monthly_budget_usd: 7,
    autopilot_daily_target: 12, default_visibility: "private", youtube_client_secret: "********",
  });
  expect(fixture.errors).toEqual([]);
});

test("a new free search key explicitly selects its free allowance and zero app spending without unrelated changes",
async ({ page }) => {
  const fixture = await discovery(page), { panel, writes } = fixture;
  await panel.getByText("Find better links with a free search key", { exact: true }).click();
  const freeAllowance = panel.getByRole("checkbox", { name: /Use the free allowance with a \$0 app spending limit/ });
  await expect(freeAllowance).toBeChecked();
  await expect(panel.getByRole("link", { name: "Open Tavily and create a free account", exact: true })).toHaveAttribute(
    "href", "https://app.tavily.com");
  await expect(panel).toContainText("This app has recorded 27 searches in 2026-10");
  await expect(panel).toContainText("your provider dashboard includes usage from other apps too");
  await expect(panel).toContainText("No key is required for your own folders or the free-license library");
  await expect(panel).toContainText("Search results provide links, not TikTok viewing statistics or reuse permission");
  // This value is a nonfunctional test sentinel; it is handled by the intercepted settings response only.
  await panel.getByLabel("Tavily API key", { exact: false }).fill("  nonfunctional-test-key  ");
  await panel.getByRole("button", { name: "Save discovery choices", exact: true }).click();
  await expect(page.locator(".toast").getByText("Discovery choices saved for the next search")).toBeVisible();
  expect(writes).toEqual([{ path: "/api/settings", method: "PUT", body: {
    tavily_api_key: "nonfunctional-test-key", tavily_free_credits: 1000, discovery_monthly_budget_usd: 0,
  } }]);
  await expect(panel.getByLabel("Tavily API key", { exact: false })).toHaveValue("");
  expect(fixture.settings()).toMatchObject({
    tavily_api_key: "********", tavily_free_credits: 1000, discovery_monthly_budget_usd: 0,
    autopilot_daily_target: 12, default_visibility: "private", youtube_client_secret: "********",
  });
  expect(fixture.errors).toEqual([]);
});

test("out-of-range and fractional shortlist limits never reach the settings endpoint", async ({ page }) => {
  const fixture = await discovery(page), { panel, writes } = fixture;
  await panel.getByText("Shortlist limits", { exact: true }).click();
  for (const [label, invalid, valid] of [
    ["New finds per search", "0", "3"], ["New finds per search", "2.5", "3"],
    ["Unfinished finds before waiting", "101", "6"], ["New finds from one creator", "31", "1"],
    ["Minimum discovery estimate", "101", "50"],
  ]) {
    const input = panel.getByLabel(label, { exact: false });
    await input.fill(invalid);
    await panel.getByRole("button", { name: "Save discovery choices", exact: true }).click();
    expect(await input.evaluate(element => (element as HTMLInputElement).validity.valid)).toBe(false);
    expect(writes).toEqual([]);
    await input.fill(valid);
  }
  expect(fixture.errors).toEqual([]);
});

test("a YouTube discovery key saves privately without changing the Tavily plan or upload account",
async ({ page }) => {
  const fixture = await discovery(page, { youtube_api_key: "********" }), { panel, writes } = fixture;
  await panel.getByText("Find better links with a free search key", { exact: true }).click();
  await panel.getByText("Optional YouTube search key", { exact: true }).click();
  await expect(panel).toContainText("A YouTube search key is already saved");
  await expect(panel).toContainText("It does not add unlimited searches or authorize uploads");
  const key = panel.getByLabel("YouTube Data API key", { exact: false });
  await expect(key).toHaveAttribute("type", "password");
  await expect(key).toHaveValue("");
  await key.fill("  nonfunctional-youtube-test-key  ");
  await panel.getByRole("button", { name: "Save discovery choices", exact: true }).click();
  await expect(page.locator(".toast").getByText("Discovery choices saved for the next search")).toBeVisible();
  expect(writes).toEqual([{ path: "/api/settings", method: "PUT",
    body: { youtube_api_key: "nonfunctional-youtube-test-key" } }]);
  await expect(key).toHaveValue("");
  expect(fixture.settings()).toMatchObject({
    youtube_api_key: "********", tavily_api_key: "********", tavily_free_credits: 2000,
    discovery_monthly_budget_usd: 7, youtube_client_secret: "********", default_visibility: "private",
  });
  expect(fixture.errors).toEqual([]);
});

test("a saved fractional score floor remains valid when another discovery choice changes", async ({ page }) => {
  const fixture = await discovery(page, { discovery_min_source_score: 57.5 }), { panel, writes } = fixture;
  await expect(panel.getByLabel("Minimum discovery estimate", { exact: false })).toHaveValue("57.5");
  await panel.getByLabel("New finds per search", { exact: false }).fill("2");
  await panel.getByRole("button", { name: "Save discovery choices", exact: true }).click();
  await expect(page.locator(".toast").getByText("Discovery choices saved for the next search")).toBeVisible();
  expect(writes).toEqual([{ path: "/api/settings", method: "PUT", body: { discovery_candidates_per_scan: 2 } }]);
  expect(fixture.settings().discovery_min_source_score).toBe(57.5);
  await expect(panel.getByLabel("Minimum discovery estimate", { exact: false })).toHaveValue("57.5");
  expect(fixture.errors).toEqual([]);
});

async function searchConnections(page: Page) {
  const savedResponse = await page.request.get("/api/settings");
  expect(savedResponse.ok()).toBe(true);
  let settings: Settings = {
    ...await savedResponse.json(),
    tavily_api_key: "********", youtube_api_key: "********", tavily_free_credits: 2000,
    discovery_monthly_budget_usd: 7, library_discovery: true, youtube_client_secret: "********",
  };
  const writes: Settings[] = [], errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  await page.route("**/api/**", async route => {
    const request = route.request(), path = new URL(request.url()).pathname;
    if (request.method() !== "GET") {
      if (path !== "/api/settings" || request.method() !== "PUT") {
        return route.fulfill({ status: 409, json: { detail: "Only controlled search settings are accepted." } });
      }
      const body = request.postDataJSON() as Settings;
      writes.push(body);
      settings = { ...settings, ...body };
      for (const key of ["youtube_api_key", "tavily_api_key"]) {
        if (settings[key]) settings[key] = "********";
      }
      return route.fulfill({ json: settings });
    }
    if (path === "/api/settings") return route.fulfill({ json: settings });
    return route.continue();
  });
  await page.goto("/#/settings/integrations");
  const panel = page.getByRole("region", { name: "Search connections", exact: true });
  await expect(panel.getByLabel("Tavily web search key", { exact: true })).toHaveValue("•••••••• (saved)");
  return { panel, writes, errors, settings: () => settings };
}

test("Integrations exposes real search setup, masked keys and explicit free-only plan controls", async ({ page }) => {
  const fixture = await searchConnections(page), { panel, writes } = fixture;
  await expect(panel).toContainText("saving a key does not test it or upload anything");
  await expect(panel).toContainText("1,000 credits each month with no credit card");
  await expect(panel).toContainText("The default allowance includes 100 searches a day");
  await expect(panel.getByRole("link", { name: "Current Tavily free allowance and credit costs" })).toHaveAttribute(
    "href", "https://docs.tavily.com/documentation/api-credits");
  await expect(panel.getByLabel("YouTube Data API key", { exact: true })).toHaveValue("•••••••• (saved)");
  await panel.getByRole("button", { name: "Use free Tavily plan limits", exact: true }).click();
  const savebar = page.getByRole("region", { name: "Save settings", exact: true });
  await savebar.getByRole("button", { name: "Save settings", exact: true }).click();
  await expect(page.locator(".toast").getByText("Settings saved", { exact: true })).toBeVisible();
  expect(writes).toEqual([{ tavily_free_credits: 1000, discovery_monthly_budget_usd: 0 }]);
  expect(fixture.settings()).toMatchObject({
    tavily_api_key: "********", youtube_api_key: "********", youtube_client_secret: "********",
    tavily_free_credits: 1000, discovery_monthly_budget_usd: 0, library_discovery: true,
  });
  expect(fixture.errors).toEqual([]);
});

test("Integrations can replace and remove search keys without echoing a saved key or changing posting settings",
async ({ page }) => {
  const fixture = await searchConnections(page), { panel, writes } = fixture;
  const tavilyRow = panel.locator(".setting").filter({ has: page.locator("#set-tavily_api_key") });
  await tavilyRow.getByRole("button", { name: "Replace…", exact: true }).click();
  const key = panel.getByLabel("Tavily web search key", { exact: true });
  await expect(key).toHaveAttribute("type", "password");
  await expect(key).toHaveValue("");
  await key.fill("nonfunctional-replacement-test-key");
  const savebar = page.getByRole("region", { name: "Save settings", exact: true });
  await savebar.getByRole("button", { name: "Save settings", exact: true }).click();
  await expect(key).toHaveValue("•••••••• (saved)");
  expect(writes).toEqual([{ tavily_api_key: "nonfunctional-replacement-test-key" }]);
  await expect(page.locator("body")).not.toContainText("nonfunctional-replacement-test-key");
  const youtubeRow = panel.locator(".setting").filter({ has: page.locator("#set-youtube_api_key") });
  await youtubeRow.getByRole("button", { name: "Remove", exact: true }).click();
  await expect(panel.getByLabel("YouTube Data API key", { exact: true })).toHaveValue("Removed when you save");
  await savebar.getByRole("button", { name: "Save settings", exact: true }).click();
  expect(writes).toEqual([{ tavily_api_key: "nonfunctional-replacement-test-key" }, { youtube_api_key: "" }]);
  await expect(panel.getByLabel("YouTube Data API key", { exact: true })).toHaveValue("");
  expect(fixture.settings()).toMatchObject({
    youtube_api_key: "", tavily_api_key: "********", tavily_free_credits: 2000,
    discovery_monthly_budget_usd: 7, youtube_client_secret: "********",
  });
  expect(fixture.errors).toEqual([]);
});
