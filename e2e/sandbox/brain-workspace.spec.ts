import { expect, test } from "@playwright/test";
import { mkdir } from "node:fs/promises";
import path from "node:path";

// This suite runs only against the throwaway sandbox, never the owner's normal app/data/accounts.
test("an uploaded guide persists and demonstrates automatic preference lookup", async ({ page, request }) => {
  const shots = path.resolve(process.cwd(), "..", "design", "robot-office", "screenshots");
  await mkdir(shots, { recursive: true });
  await page.goto("/#/brain");
  await page.getByRole("button", { name: "Add knowledge", exact: true }).click();
  await page.getByLabel("Title", { exact: true }).fill("Science caption guide — isolated test");
  await page.getByRole("combobox", { name: "Use as", exact: true }).selectOption("instruction");
  await page.getByLabel("Upload a document (optional)").setInputFiles({
    name: "science-guide.md", mimeType: "text/markdown", buffer: Buffer.from("# Science clips\nPrefer readable, quiet captions. Keep spoken facts intact.") });
  await page.getByLabel("Topic tags (optional, separated by commas)").fill("science");
  await page.getByRole("combobox", { name: "Caption style", exact: true }).selectOption("minimal");
  await page.getByRole("button", { name: "Save knowledge", exact: true }).click();
  await expect(page.locator(".brain-editor .brain-pill")).toHaveText("Used automatically");
  await expect(page.getByRole("button", { name: "Review & approve", exact: true })).toHaveCount(0);
  await page.reload();
  await expect(page.getByLabel("Title", { exact: true })).toHaveValue("Science caption guide — isolated test");
  await page.screenshot({ path: path.join(shots, "brain-knowledge.png"), fullPage: true });
  await page.getByRole("button", { name: "Try a decision", exact: true }).click();
  await page.getByLabel("Clip context", { exact: true }).fill("Science explains why sleep helps memory.");
  await page.getByRole("button", { name: "Check Brain guidance", exact: true }).click();
  await expect(page.locator(".brain-preview-result")).toContainText("minimal");
  await expect(page.locator(".brain-preview-result")).toContainText("Science caption guide");
  await page.screenshot({ path: path.join(shots, "brain-influence-preview.png"), fullPage: true });
  await page.getByRole("dialog").getByRole("button", { name: "Close", exact: true }).click();
  await page.getByRole("button", { name: "Disable", exact: true }).click();
  const rows = await (await request.get("/api/brain/knowledge?q=Science%20caption%20guide")).json();
  expect(rows).toHaveLength(1);
  await expect.poll(async () => (await (await request.get(`/api/brain/knowledge?q=Science%20caption%20guide`)).json())[0].enabled).toBe(false);
  const preview = await request.post("/api/brain/knowledge/preview", { headers: { "X-ClipFoundry": "1" }, data: { text: "Science of memory" } });
  expect((await preview.json()).influences).toEqual([]);
  expect((await request.delete(`/api/brain/knowledge/${rows[0].id}`, { headers: { "X-ClipFoundry": "1" } })).ok()).toBe(true);
  expect((await request.get("/api/brain/knowledge/export")).headers()["content-disposition"]).toContain("brain-knowledge.json");
  for (const width of [1366, 390]) {
    await page.setViewportSize({ width, height: 800 });
    await page.reload();
    await expect(page.getByRole("heading", { name: "Brain", exact: true })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
  }
});

test("a plain saved note is interpreted locally and unsaved edits do not activate", async ({ page, request }) => {
  await page.goto("/#/brain");
  await page.getByRole("button", { name: "Add note", exact: true }).click();
  await page.getByLabel("Title", { exact: true }).fill("Automatic note — isolated test");
  await page.getByRole("textbox", { name: "Notes / instructions", exact: true }).fill(
    "Caption style: minimal. Prioritize standalone context and a complete story with a payoff.",
  );
  await page.getByRole("button", { name: "Save knowledge", exact: true }).click();
  await expect(page.locator(".brain-editor .brain-pill")).toHaveText("Used automatically");
  await expect(page.getByLabel("How Brain uses this lesson")).toContainText("caption style: minimal");
  await expect(page.getByRole("button", { name: "Review & approve", exact: true })).toHaveCount(0);
  const preview = () => request.post("/api/brain/knowledge/preview", {
    headers: { "X-ClipFoundry": "1" }, data: { text: "A story told with full context." },
  });
  expect((await (await preview()).json()).after.caption_style).toBe("minimal");
  await page.getByRole("combobox", { name: "Caption style", exact: true }).selectOption("clean");
  await expect(page.locator(".brain-editor .brain-pill")).toHaveText("Unsaved changes");
  expect((await (await preview()).json()).after.caption_style).toBe("minimal");
  await page.getByRole("button", { name: "Save changes", exact: true }).click();
  expect((await (await preview()).json()).after.caption_style).toBe("clean");
});

test("Integrations shows supported connections without inactive platform placeholders", async ({ page }) => {
  await page.goto("/#/settings/integrations");
  await expect(page.getByRole("heading", { name: "Connections", exact: true })).toBeVisible();
  const cards = page.locator(".integration-cards");
  await expect(cards).toContainText("YouTube");
  await expect(cards).toContainText("TikTok");
  await expect(cards).not.toContainText("Not in this version");
  await expect(cards).not.toContainText("Unsupported");
  for (const name of ["Twitch", "Kick", "Reddit", "Instagram", "Google Trends", "Podcasts"])
    await expect(cards.getByRole("heading", { name, exact: true })).toHaveCount(0);
});
