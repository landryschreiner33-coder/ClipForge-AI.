import { expect, getJson, test } from "../fixtures";

// Save settings, Replace, Test connection, Connect/Disconnect, Confirm who watches, My viewers changed, Save my
// agreement, Check the setup and Run a small AI test are never pressed. A change made to look at the
// save bar is thrown away with Discard (nothing is sent; writes are blocked anyway).

const SECRET_KEYS = ["openai_api_key", "anthropic_api_key", "youtube_client_secret", "tiktok_client_secret",
  "youtube_api_key", "tavily_api_key", "nvidia_api_key"];
// Shown only for the AI scoring choice that uses them.
const PROVIDER_KEYS: Record<string, string[]> = {
  ollama: ["ollama_url", "ollama_model"], openai_compatible: ["openai_url", "openai_model", "openai_api_key"],
  anthropic: ["anthropic_api_key", "anthropic_model"],
};
const TABS = [["Accounts", "#/settings"], ["Defaults", "#/settings/defaults"],
  ["Integrations", "#/settings/integrations"], ["Advanced", "#/settings/advanced"]];

test.beforeEach(async ({ page }) => {
  await page.goto("/#/settings");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Settings");
});

test("Accounts comes first, with both platforms and how their posts get approved", async ({ page }) => {
  const tabs = page.getByRole("navigation", { name: "Settings sections" });
  for (const [name, href] of TABS) {
    await expect(tabs.getByRole("link", { name, exact: true })).toHaveAttribute("href", href);
  }
  await expect(tabs.locator("[aria-current=page]")).toHaveText("Accounts");
  for (const h of ["YouTube", "TikTok"]) {
    await expect(page.getByRole("heading", { name: h, level: 2, exact: true })).toBeVisible();
  }
  await expect(page.getByText("How posts get approved", { exact: true })).toBeVisible();
  await expect(page.getByText("your OK on each post")).toBeVisible();
  // Accounts are not repeated under Advanced.
  await page.goto("/#/settings/advanced");
  await expect(page.getByRole("heading", { name: "YouTube", level: 2, exact: true })).toHaveCount(0);
});

test("Defaults, Integrations and Advanced have their sections", async ({ page }) => {
  await page.goto("/#/settings/defaults");
  for (const h of ["New clips", "Autopilot"]) {
    await expect(page.getByRole("heading", { name: h, level: 2, exact: true })).toBeVisible();
  }
  await page.goto("/#/settings/integrations");
  for (const h of ["Who watches", "Connections", "NVIDIA AI (optional)"]) {
    await expect(page.getByRole("heading", { name: h, level: 2, exact: true })).toBeVisible();
  }
  await page.goto("/#/settings/advanced");
  for (const h of ["Transcription and GPU", "Autopilot details", "Autopilot posting", "Discovery and rights",
    "Brain (learning)", "Rendering, AI scoring and system", "Dev Log"]) {
    await expect(page.getByRole("heading", { name: h, level: 2, exact: true })).toBeVisible();
  }
  await expect(page.getByRole("heading", { name: "System", exact: true })).toBeVisible();
});

test("every setting has a place on one of the tabs", async ({ page, request }) => {
  const s = await getJson(request, "/api/settings");
  const hidden = Object.entries(PROVIDER_KEYS).filter(([p]) => p !== s.ai_provider).flatMap(([, keys]) => keys);
  const found = new Set<string>();
  for (const [, href] of TABS) {
    await page.goto(`/${href}`);
    await expect(page.locator(".savebar")).toBeVisible();
    // the app codes sit behind a disclosure: open it (it only shows them)
    const closed = page.locator("details:not([open]) > summary", { hasText: "app codes" });
    while (await closed.count()) await closed.first().click();
    for (const k of Object.keys(s)) {
      if (await page.locator(`[id="set-${k}"], [id="set-${k}-label"]`).count()) found.add(k);
    }
  }
  // Turned on and off on the Autopilot page; the caption style is a picker of named styles; the way of working is
  // chosen in first-time setup; who watches is set with its own Confirm button on Integrations; the NVIDIA agreement
  // with its own button; publishing and the Brain are paused from the Office; YouTube uploads are always Private.
  // NVIDIA's endpoint, price and spending cap show only in its production mode.
  const own = Object.keys(s).filter((k) => k.startsWith("audience_"));
  const production = s.nvidia_mode === "production" ? [] :
    ["nvidia_production_url", "nvidia_price_per_mtok_usd", "nvidia_daily_spend_cap_usd"];
  const elsewhere = ["autopilot_enabled", "caption_style", "setup_mode", "nvidia_opt_in_at",
    "autopilot_publishing_paused", "brain_paused", "autopilot_youtube_privacy", ...own, ...production, ...hidden];
  const missing = Object.keys(s).filter((k) => !found.has(k) && !elsewhere.includes(k));
  expect(missing, "settings without a place on the Settings page").toEqual([]);
});

test("the data folder shown is the one the app uses", async ({ page, request }) => {
  const h = await getJson(request, "/api/health");
  await expect(page.locator(".page-head p code")).toHaveText(h.data_dir);
});

test("Save stays off until something changes, switching tabs keeps the change, and leaving asks first", async ({
  page, request,
}) => {
  const before = await getJson(request, "/api/settings");
  const bar = page.locator(".savebar");
  const save = bar.getByRole("button", { name: "Save settings" });
  await expect(save).toBeDisabled();
  await expect(bar).toContainText("No changes");

  await page.goto("/#/settings/defaults");
  await page.getByLabel("Hook on screen at the start").click();
  await expect(save).toBeEnabled();
  await expect(bar).toContainText("Unsaved changes: Hook on screen");
  // switching tabs keeps what you changed, without asking
  await page.getByRole("navigation", { name: "Settings sections" }).getByRole("link", { name: "Advanced" }).click();
  await expect(page).toHaveURL(/#\/settings\/advanced$/);
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(bar).toContainText("Unsaved changes: Hook on screen");
  // leaving the page asks; Stay keeps you here
  await page.getByRole("navigation", { name: "Main" }).first().getByRole("link", { name: "Clips" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByRole("heading")).toHaveText("Leave without saving?");
  await dialog.getByRole("button", { name: "Stay" }).click();
  await expect(page).toHaveURL(/#\/settings\/advanced$/);
  await bar.getByRole("button", { name: "Discard" }).click();
  await expect(save).toBeDisabled();
  expect(await getJson(request, "/api/settings")).toEqual(before);
});

test("a field error blocks saving and points at the field", async ({ page }) => {
  await page.goto("/#/settings/defaults");
  const box = page.locator("#set-autopilot_daily_target");
  await box.fill("0");
  await expect(box).toHaveAttribute("aria-invalid", "true");
  await expect(page.locator("#set-autopilot_daily_target-err")).toHaveText(/Enter a number from 1 to 100/);
  await expect(page.locator(".savebar [role=alert]"))
    .toContainText("Fix the field marked below before saving: Daily target");
  await page.locator(".savebar").getByRole("button", { name: "Discard" }).click();
  await expect(box).not.toHaveAttribute("aria-invalid", "true");
});

test("API keys and client secrets never reach the browser", async ({ page, request }) => {
  const s = await getJson(request, "/api/settings");
  for (const k of SECRET_KEYS) {
    if (k in s) expect(["", "********"], `${k} is masked`).toContain(s[k]);
  }
  // A saved secret is shown as a mask with Replace (not pressed here), never in a box of its own.
  const codes = page.locator("details", { has: page.locator("summary", { hasText: "Your YouTube app codes" }) });
  if ((await codes.getAttribute("open")) === null) await codes.locator("> summary").click();
  const secret = page.locator("#set-youtube_client_secret");
  if (s.youtube_client_secret === "********") {
    await expect(secret).toHaveValue("•••••••• (saved)");
    await expect(secret).toHaveAttribute("readonly", "");
    await expect(page.getByRole("button", { name: "Replace…" }).first()).toBeVisible();
  } else {
    await expect(secret).toHaveAttribute("type", "password");
    await expect(secret).toHaveValue("");
  }
});

test("Integrations says who watches and what each connection can do", async ({ page, request }) => {
  const [aud, int] = await Promise.all([getJson(request, "/api/audience"), getJson(request, "/api/integrations")]);
  await page.goto("/#/settings/integrations");
  for (const p of ["youtube", "tiktok"] as const) {
    const row = page.locator(".audience-row", { has: page.getByRole("heading", { name: p === "youtube" ? "YouTube"
      : "TikTok", level: 3, exact: true }) });
    const d = aud[p];
    await expect(row).toContainText(d.confirmed ? `${d.label} · confirmed` : d.intent === "LOCAL_ONLY"
      ? "Kept on this PC" : "Not confirmed");
    // never public, unlisted or "Everyone": those are not offered
    await expect(row.getByRole("radio")).toHaveCount(p === "tiktok" && d.intent === "SELECTED_AUDIENCE" ? 5 : 3);
    await expect(row.getByText(/public|unlisted|everyone/i)).toHaveCount(0);
  }
  const cards = page.locator(".integration");
  await expect(cards).toHaveCount(int.cards.filter((c: any) => c.id !== "nvidia").length);
  for (const c of int.cards.filter((x: any) => x.id !== "nvidia")) {
    await expect(cards.filter({ has: page.getByRole("heading", { name: c.name }) })).toContainText(c.status_label);
  }
  const nv = await getJson(request, "/api/integrations/nvidia");
  await expect(page.getByText(nv.data_note)).toBeVisible();
  if (!nv.opted_in) {
    await expect(page.getByRole("button", { name: "Save my agreement" })).toBeDisabled();
  }
});
