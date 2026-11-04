import { expect, Locator, Page, test } from "@playwright/test";
import type { Settings } from "../../frontend/src/api";
import type { SearchCheck, SearchConnection } from "../../frontend/src/office/api";

// These tests use disposable data and intercept every mutation. No provider, real key or account is contacted.
type Provider = "youtube" | "tavily";
const names = { youtube: "YouTube", tavily: "Tavily" } as const;
const accepted = (provider: Provider, overrides: Partial<SearchCheck> = {}): SearchCheck => ({
  provider, ok: true, status: "connected", detail: `${names[provider]} accepted the saved connection.`,
  fix: "", code: "accepted", until: null, at: Math.floor(Date.now() / 1000), current: true, auth_mode: "api_key",
  ...overrides,
});
const configured = (overrides: Partial<SearchConnection> = {}): SearchConnection => ({
  configured: true, auth_mode: "api_key", last_check: null, ...overrides,
});

async function controlled(page: Page, initial: Partial<Record<Provider, SearchConnection>> = {}) {
  const baseline = await page.request.get("/api/settings");
  expect(baseline.ok()).toBe(true);
  const connections = { youtube: configured(), tavily: configured(), ...initial };
  const settings: Settings = { ...await baseline.json(), youtube_api_key: "********", tavily_api_key: "********",
    tavily_free_credits: 1000, discovery_monthly_budget_usd: 0 };
  for (const provider of ["youtube", "tavily"] as Provider[]) {
    if (!connections[provider].configured || connections[provider].auth_mode !== "api_key") {
      settings[`${provider}_api_key`] = "";
    }
  }
  const state = { settings, connections, errors: [] as string[], reads: 0,
    writes: [] as { path: string; body: unknown }[],
    next: { youtube: [] as SearchCheck[], tavily: [] as SearchCheck[] },
    failed: null as null | Provider };
  page.on("pageerror", error => state.errors.push(error.message));
  await page.route("**/api/**", async route => {
    const request = route.request(), path = new URL(request.url()).pathname;
    if (request.method() !== "GET") {
      state.writes.push({ path, body: request.postDataJSON() });
      if (request.method() === "PUT" && path === "/api/settings") {
        const patch = request.postDataJSON() as Settings;
        Object.assign(state.settings, patch);
        for (const provider of ["youtube", "tavily"] as Provider[]) {
          const key = `${provider}_api_key`;
          if (!(key in patch)) continue;
          state.settings[key] = patch[key] ? "********" : "";
          state.connections[provider] = configured({ configured: !!patch[key],
            auth_mode: patch[key] ? "api_key" : "not_configured",
            last_check: state.connections[provider].last_check
              ? { ...state.connections[provider].last_check!, current: false } : null });
        }
        return route.fulfill({ json: state.settings });
      }
      const provider = (["youtube", "tavily"] as Provider[])
        .find(value => path === `/api/integrations/search/${value}/test`);
      if (request.method() === "POST" && provider) {
        if (state.failed === provider) return route.fulfill({ status: 503,
          json: { detail: "The connection check could not reach the service. Try again when online." } });
        const result = state.next[provider].shift() || accepted(provider);
        state.connections[provider].last_check = result;
        return route.fulfill({ json: result });
      }
      return route.fulfill({ status: 409, json: { detail: "Unexpected mutation refused by the browser fixture." } });
    }
    if (path === "/api/settings") return route.fulfill({ json: state.settings });
    if (path === "/api/integrations/search") {
      state.reads++;
      return route.fulfill({ json: state.connections });
    }
    return route.continue();
  });
  await page.goto("/#/settings/integrations");
  const panel = page.getByRole("region", { name: "Search connections", exact: true });
  await expect.poll(() => state.reads).toBeGreaterThan(0);
  const row = (provider: Provider) => panel.locator(".setting")
    .filter({ has: page.locator(`#set-${provider}_api_key`) });
  const button = (provider: Provider) => row(provider).getByRole("button", {
    name: `Test saved ${names[provider]} connection`, exact: true,
  });
  const save = async () => {
    await page.getByRole("region", { name: "Save settings", exact: true })
      .getByRole("button", { name: "Save settings", exact: true }).click();
    await expect(page.locator(".toast").getByText("Settings saved", { exact: true })).toBeVisible();
  };
  return { state, panel, row, button, save };
}

async function capture(subject: Locator, name: string) {
  if (!process.env.CLIPFOUNDRY_BROWSER_SHOTS) return;
  // Center the connection row so the sticky page save bar does not cover its explanation in the evidence.
  await subject.evaluate(element => element.scrollIntoView({ block: "center" }));
  await subject.screenshot({ path: `${process.env.CLIPFOUNDRY_BROWSER_SHOTS}/${name}.png` });
}

test("missing search connections cannot be tested and viewing setup never contacts a provider", async ({ page }) => {
  const { state, row, button } = await controlled(page, {
    youtube: configured({ configured: false, auth_mode: "not_configured" }),
    tavily: configured({ configured: false, auth_mode: "not_configured" }),
  });
  await expect(button("youtube")).toBeDisabled();
  await expect(button("tavily")).toBeDisabled();
  await expect(row("youtube")).toContainText("Save a search API key or connect your YouTube account first.");
  await expect(row("tavily")).toContainText("Save your Tavily API key first.");
  expect(state.writes).toEqual([]);
  expect(state.errors).toEqual([]);
});

test("saved API keys and connected-account search identify their mode and require an explicit safe test",
async ({ page }) => {
  const { state, row, button } = await controlled(page, {
    youtube: configured({ auth_mode: "connected_account" }),
  });
  await expect(button("youtube")).toBeEnabled();
  await expect(button("tavily")).toBeEnabled();
  await expect(row("youtube")).toContainText("connected YouTube account");
  await expect(row("tavily")).toContainText("Saved search method: Tavily API key.");
  await expect(row("youtube")).toContainText("No search or upload");
  await expect(row("tavily")).toContainText("without running a search");
  expect(state.writes).toEqual([]);
  state.next.youtube.push(accepted("youtube", { auth_mode: "connected_account" }));
  await button("youtube").click();
  await expect(row("youtube")).toContainText("YouTube connection accepted");
  await button("tavily").click();
  await expect(row("tavily")).toContainText("Tavily connection accepted");
  expect(state.writes).toEqual([
    { path: "/api/integrations/search/youtube/test", body: null },
    { path: "/api/integrations/search/tavily/test", body: null },
  ]);
  expect(state.errors).toEqual([]);
});

test("unsaved key changes disable only that provider and saving refreshes the actual saved setup", async ({ page }) => {
  const { state, panel, row, button, save } = await controlled(page, {
    tavily: configured({ configured: false, auth_mode: "not_configured" }),
  });
  const key = panel.getByLabel("Tavily web search key", { exact: true });
  await key.fill("nonfunctional-new-search-test-key");
  await expect(button("tavily")).toBeDisabled();
  await expect(button("youtube")).toBeEnabled();
  await expect(row("tavily")).toContainText("Save changes first; this checks the saved connection.");
  expect(state.writes).toEqual([]);
  await save();
  await expect(key).toHaveValue("•••••••• (saved)");
  await expect(button("tavily")).toBeEnabled();
  expect(state.writes).toEqual([{ path: "/api/settings", body: {
    tavily_api_key: "nonfunctional-new-search-test-key",
  } }]);
  await expect(page.locator("body")).not.toContainText("nonfunctional-new-search-test-key");
  await button("tavily").click();
  await expect(row("tavily")).toContainText("Tavily connection accepted");
  expect(state.writes[1]).toEqual({ path: "/api/integrations/search/tavily/test", body: null });
  expect(state.errors).toEqual([]);
});

for (const provider of ["youtube", "tavily"] as Provider[]) {
  test(`${names[provider]} shows actionable rejection and tests a corrected saved key without leaking it`,
  async ({ page }) => {
    const { state, panel, row, button, save } = await controlled(page);
    const detail = provider === "youtube" ? "YouTube rejected this API key's application restriction."
      : "Tavily did not accept the saved API key.";
    const fix = provider === "youtube" ? "Use application restrictions suited to this desktop PC."
      : "Copy a current API key from your Tavily dashboard, replace it here, then save.";
    state.next[provider].push(accepted(provider, { ok: false, status: "error", detail, fix, code: "key_rejected" }));
    await button(provider).click();
    await expect(row(provider)).toContainText(`${names[provider]} needs attention`);
    await expect(row(provider)).toContainText(detail);
    await expect(row(provider)).toContainText(fix);
    await capture(row(provider), `search-${provider}-rejected`);
    await row(provider).getByRole("button", { name: "Replace…", exact: true }).click();
    const label = provider === "youtube" ? "YouTube Data API key" : "Tavily web search key";
    await panel.getByLabel(label, { exact: true }).fill("nonfunctional-corrected-test-key");
    await expect(button(provider)).toBeDisabled();
    await expect(row(provider)).toContainText("Previous connection result");
    expect(state.writes).toHaveLength(1);
    await save();
    await expect(button(provider)).toBeEnabled();
    await expect(row(provider)).toContainText("Previous connection result");
    await button(provider).click();
    await expect(row(provider)).toContainText(`${names[provider]} connection accepted`);
    await expect(row(provider)).not.toContainText("Previous connection result");
    expect(state.writes).toEqual([
      { path: `/api/integrations/search/${provider}/test`, body: null },
      { path: "/api/settings", body: { [`${provider}_api_key`]: "nonfunctional-corrected-test-key" } },
      { path: `/api/integrations/search/${provider}/test`, body: null },
    ]);
    await expect(page.locator("body")).not.toContainText("nonfunctional-corrected-test-key");
    expect(state.errors).toEqual([]);
  });
}

test("durable provider waits remain visible after reload without triggering repeated checks", async ({ page }) => {
  const until = Math.floor(Date.now() / 1000) + 3600;
  const waiting = accepted("youtube", { ok: false, status: "waiting", code: "quotaExceeded", until,
    detail: "YouTube's allowance is used up for now.",
    fix: "Wait for the provider's reset; other sources can continue." });
  const { state, row, button } = await controlled(page, { youtube: configured({ last_check: waiting }) });
  await expect(row("youtube")).toContainText("YouTube's allowance is used up for now.");
  await expect(row("youtube")).toContainText("Try again after");
  expect(state.writes).toEqual([]);
  await page.reload();
  await expect(row("youtube")).toContainText("Wait for the provider's reset; other sources can continue.");
  await expect(row("youtube")).toContainText("Try again after");
  expect(state.writes).toEqual([]);
  state.next.youtube.push(waiting);
  await button("youtube").click();
  await expect(row("youtube")).toContainText("Try again after");
  expect(state.writes).toEqual([{ path: "/api/integrations/search/youtube/test", body: null }]);
  await capture(row("youtube"), "search-durable-wait");
  expect(state.errors).toEqual([]);
});

test("a result for an old key is labeled previous rather than claiming the current connection works",
async ({ page }) => {
  const { state, row } = await controlled(page, {
    tavily: configured({ last_check: accepted("tavily", { current: false }) }),
  });
  await expect(row("tavily")).toContainText("Previous connection result");
  await expect(row("tavily")).toContainText("The saved connection has changed.");
  await expect(row("tavily").getByText("Tavily connection accepted", { exact: true })).toHaveCount(0);
  expect(state.writes).toEqual([]);
  expect(state.errors).toEqual([]);
});

test("an interrupted connection check gives a retry explanation and never starts a search or upload",
async ({ page }) => {
  const { state, row, button } = await controlled(page);
  state.failed = "tavily";
  await button("tavily").click();
  await expect(row("tavily")).toContainText("Connection check could not finish");
  await expect(row("tavily")).toContainText("Try again when online.");
  await expect(button("tavily")).toBeEnabled();
  expect(state.writes).toEqual([{ path: "/api/integrations/search/tavily/test", body: null }]);
  expect(state.errors).toEqual([]);
});
