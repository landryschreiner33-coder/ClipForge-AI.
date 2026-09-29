import { expect, getJson, test } from "../fixtures";

// Save settings, Test connection and the Connect/Disconnect buttons are never pressed.

const SECRET_KEYS = ["openai_api_key", "anthropic_api_key", "youtube_client_secret", "tiktok_client_secret", "youtube_api_key"];

test.beforeEach(async ({ page }) => {
  await page.goto("/#/settings");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Settings");
});

const ADVANCED = [
  "Transcription (faster-whisper, local)",
  "Clip discovery",
  "AI scoring (Stage 2)",
  "Publishing (YouTube Shorts and TikTok)",
  "Rendering defaults",
  "Autopilot details",
  "Discovery",
  "Rights",
  "YouTube quota and GPU",
  "System",
];

test("General has only the accounts and the Autopilot basics", async ({ page }) => {
  await expect(page.locator(".segmented button.on")).toHaveText("General");
  for (const h of ["Accounts", "Autopilot"]) await expect(page.getByRole("heading", { name: h, exact: true })).toBeVisible();
  for (const row of ["Daily target", "Automatic publishing"]) await expect(page.locator(".opt-row .lbl", { hasText: row })).toBeVisible();
  for (const platform of ["YouTube", "TikTok"]) await expect(page.locator(".platform-head b", { hasText: platform })).toBeVisible();
  for (const h of ADVANCED) await expect(page.getByRole("heading", { name: h, exact: true })).toHaveCount(0);
});

test("Advanced still has every technical section", async ({ page }) => {
  await page.getByRole("button", { name: "Advanced", exact: true }).click();
  await expect(page).toHaveURL(/#\/settings\/advanced$/);
  for (const h of ADVANCED) await expect(page.getByRole("heading", { name: h, exact: true })).toBeVisible();
  for (const row of ["Worker process", "Topics", "YouTube Data API key", "Download authorized platform sources", "Allow CPU transcription"]) {
    await expect(page.locator(".opt-row .lbl", { hasText: row }).first()).toBeVisible();
  }
});

test("the data folder shown is the one the app uses", async ({ page, request }) => {
  const h = await getJson(request, "/api/health");
  await expect(page.locator(".page-head p code")).toHaveText(h.data_dir);
});

test("Save stays off until something changes, and leaving without saving keeps your settings", async ({ page, request }) => {
  const before = await getJson(request, "/api/settings");
  const save = page.getByRole("button", { name: "Save settings" });
  await expect(save).toBeDisabled();

  await page.goto("/#/settings/advanced");
  await page.getByRole("switch", { name: "Hook overlay", exact: true }).click();
  await expect(save).toBeEnabled();
  // switching between General and Advanced keeps what you changed
  await page.getByRole("button", { name: "General", exact: true }).click();
  await page.getByRole("button", { name: "Advanced", exact: true }).click();
  await expect(save).toBeEnabled();

  await page.locator(".sidebar").getByRole("link", { name: "Dashboard", exact: true }).click();
  expect(await getJson(request, "/api/settings")).toEqual(before);
});

test("API keys and client secrets never reach the browser", async ({ request }) => {
  const s = await getJson(request, "/api/settings");
  for (const k of SECRET_KEYS) {
    if (k in s) expect(["", "********"], `${k} is masked`).toContain(s[k]);
  }
});
