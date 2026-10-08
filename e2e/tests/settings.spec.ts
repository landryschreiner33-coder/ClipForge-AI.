import { expect, getJson, test } from "../fixtures";

// Save settings, Replace, Test connection and Connect/Disconnect are never pressed. A change made to look at the
// save bar is thrown away with Discard (nothing is sent; writes are blocked anyway).

const SECRET_KEYS = ["openai_api_key", "anthropic_api_key", "youtube_client_secret", "tiktok_client_secret",
  "youtube_api_key", "tavily_api_key"];
// Shown only for the AI scoring choice that uses them.
const PROVIDER_KEYS: Record<string, string[]> = {
  ollama: ["ollama_url", "ollama_model"], openai_compatible: ["openai_url", "openai_model", "openai_api_key"],
  anthropic: ["anthropic_api_key", "anthropic_model"],
};
// The tabs that share the save bar. Integrations (NVIDIA AI and who sees your clips) saves its own forms.
const TABS = [["Accounts", "#/settings"], ["Defaults", "#/settings/defaults"], ["Advanced", "#/settings/advanced"]];
const INTEGRATIONS = ["Integrations", "#/settings/integrations"];

test.beforeEach(async ({ page }) => {
  await page.goto("/#/settings");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Settings");
});

test("Accounts comes first, with both platforms and how their posts get approved", async ({ page }) => {
  const tabs = page.getByRole("navigation", { name: "Settings sections" });
  for (const [name, href] of [...TABS, INTEGRATIONS]) {
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

test("Defaults and Advanced have their sections", async ({ page }) => {
  await page.goto("/#/settings/defaults");
  for (const h of ["New clips", "Autopilot"]) {
    await expect(page.getByRole("heading", { name: h, level: 2, exact: true })).toBeVisible();
  }
  await page.goto("/#/settings/advanced");
  for (const h of ["Transcription and GPU", "Autopilot details", "Autopilot posting", "Discovery and rights",
    "Rendering, AI scoring and system"]) {
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
  // NVIDIA AI and the audience settings have their own forms on Integrations (only looked at, never saved here)
  await page.goto(`/${INTEGRATIONS[1]}`);
  await expect(page.getByRole("heading", { name: "Who sees your clips" })).toBeVisible();
  await expect(page.getByText("Use NVIDIA AI", { exact: true })).toBeVisible();
  // Turned on and off on the Missions page and the Office's control bar (Pause publishing too); the caption style is
  // a picker of named styles; the way of working is chosen in first-time setup; the Brain's guards (brain_*,
  // docs/BRAIN.md) have no field on the Settings page.
  const elsewhere = ["autopilot_enabled", "autopilot_publish_paused", "caption_style", "setup_mode", ...hidden];
  const onItsOwn = (k: string) => /^(nvidia|audience|brain)_/.test(k);
  const missing = Object.keys(s).filter((k) => !found.has(k) && !elsewhere.includes(k) && !onItsOwn(k));
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
