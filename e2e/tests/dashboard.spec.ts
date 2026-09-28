import { expect, getJson, test } from "../fixtures";

test.beforeEach(async ({ page }) => {
  await page.goto("/#/");
});

test("the stat cards show the app's real counts", async ({ page, request }) => {
  const stat = (label: string) => page.locator(".card.stat", { has: page.getByText(label, { exact: true }) }).locator("b");
  // Counts can move while a project is processing, so compare against a fresh reading until they agree.
  await expect(async () => {
    const s = await getJson(request, "/api/stats");
    expect(await stat("Projects").textContent()).toBe(String(s.projects));
    expect(await stat("Processing now").textContent()).toBe(String(s.processing));
  }).toPass();
  await expect(stat("Runtime cost (local mode)")).toHaveText("$0");
});

test("the System card matches /api/health", async ({ page, request }) => {
  const h = await getJson(request, "/api/health");
  const row = (k: string) => page.locator(".sys-item", { has: page.locator(".k", { hasText: new RegExp(`^${k}$`) }) });
  await expect(row("FFmpeg").locator(".badge")).toHaveText(h.ffmpeg ? "Found" : "Missing");
  await expect(row("GPU encoder").locator(".badge")).toHaveText(h.nvenc ? "NVENC" : "x264 (CPU)");
  await expect(row("Transcription").locator(".badge")).toContainText(h.whisper.mode === "gpu" ? "GPU mode" : "CPU mode");
  await expect(row("Clip scoring").locator(".badge")).toHaveText(h.ai_provider);
  await expect(page.getByText("FFmpeg is required.")).toHaveCount(h.ffmpeg ? 0 : 1);
});

test("recent projects match the library", async ({ page, request }) => {
  await expect(async () => {
    const s = await getJson(request, "/api/stats");
    if (s.recent.length === 0) {
      await expect(page.getByRole("heading", { name: "No projects yet" })).toBeVisible({ timeout: 1000 });
    } else {
      await expect(page.locator(".proj-grid .proj-card")).toHaveCount(s.recent.length, { timeout: 1000 });
      await expect(page.locator(".proj-grid .proj-card .name").first()).toHaveText(s.recent[0].name, { timeout: 1000 });
    }
  }).toPass();
});

test("CREATE CLIPS on the hero opens Create", async ({ page }) => {
  await page.getByRole("button", { name: "CREATE CLIPS", exact: true }).click();
  await expect(page).toHaveURL(/#\/create$/);
});
