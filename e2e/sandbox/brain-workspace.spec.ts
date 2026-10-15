import { expect, test } from "@playwright/test";
import { mkdir, mkdtemp, rm } from "node:fs/promises";
import { execFileSync } from "node:child_process";
import { tmpdir } from "node:os";
import path from "node:path";

// This suite runs only against the throwaway sandbox, never the owner's normal app/data/accounts.
test("an uploaded guide persists and demonstrates automatic preference lookup", async ({ page, request }) => {
  const shots = path.resolve(process.env.CLIPFOUNDRY_BROWSER_SHOTS ||
    path.join(process.cwd(), "..", "design", "robot-office", "screenshots"));
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
    "Captions should be minimal. Prioritize standalone context and a complete story with a payoff.",
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


test("unsupported prose stays searchable and explains how to make it affect new clips", async ({ page, request }) => {
  await page.goto("/#/brain");
  await page.getByRole("button", { name: "Add note", exact: true }).click();
  await page.getByLabel("Title", { exact: true }).fill("Amber palette — isolated reference");
  await page.getByRole("textbox", { name: "Notes / instructions", exact: true }).fill(
    "Use amber-colored furniture and an illustrated mountain background.",
  );
  await page.getByRole("button", { name: "Save knowledge", exact: true }).click();
  await expect(page.locator(".brain-editor .brain-pill")).toHaveText("Searchable reference");
  const effect = page.getByLabel("How Brain uses this lesson");
  await expect(effect).toContainText("Effect on new clips");
  await expect(effect).toContainText("Add a supported caption or pacing preference");
  await expect(effect).not.toContainText("Recognized choices");
  const rows = await (await request.get("/api/brain/knowledge?q=Amber%20palette")).json();
  expect(rows).toHaveLength(1);
  const preview = await request.post("/api/brain/knowledge/preview", {
    headers: { "X-ClipFoundry": "1" }, data: { text: "Amber palette on a mountain." },
  });
  expect((await preview.json()).influences.map((item: any) => item.knowledge_id)).not.toContain(rows[0].id);
  expect((await request.delete(`/api/brain/knowledge/${rows[0].id}`,
    { headers: { "X-ClipFoundry": "1" } })).ok()).toBe(true);
});

test("paused Brain shows a direct resume action and resumes saved guidance for new clips", async ({ page, request }) => {
  const headers = { "X-ClipFoundry": "1" };
  const saved = await request.post("/api/brain/knowledge", { headers, data: {
    kind: "instruction", title: "Nebula captions — isolated pause test", content: "Captions should be bold.",
    tags: ["nebula"], features: {}, preferences: {}, example_label: "", enabled: true,
  } });
  expect(saved.ok()).toBe(true);
  const item = await saved.json();
  try {
  const preview = () => request.post("/api/brain/knowledge/preview", { headers, data: { text: "Nebula colors explained." } });
  expect((await (await preview()).json()).after.caption_style).toBe("bold");
  expect((await request.post("/api/brain/pause", { headers, data: { paused: true } })).ok()).toBe(true);
  await page.goto("/#/brain");
  await page.getByRole("button", { name: "List & editor", exact: true }).click();
  await page.getByRole("searchbox", { name: "Search knowledge", exact: true }).fill("Nebula captions");
  await page.getByRole("button", { name: /Nebula captions — isolated pause test/ }).click();
  await expect(page.locator(".banner").getByText("Brain is paused", { exact: true })).toBeVisible();
  await expect(page.locator(".brain-editor .brain-pill")).toHaveText("Ready when Brain resumes");
  await expect(page.getByLabel("How Brain uses this lesson")).toContainText("Resume it to apply this lesson");
  expect((await (await preview()).json()).influences).toEqual([]);
  await page.getByRole("button", { name: "Resume Brain", exact: true }).click();
  await expect(page.locator(".banner").getByText("Brain is paused", { exact: true })).toHaveCount(0);
  await expect(page.locator(".brain-editor .brain-pill")).toHaveText("Used automatically");
  expect((await (await preview()).json()).after.caption_style).toBe("bold");
  expect((await (await request.get("/api/brain/knowledge/workspace")).json()).guidance.paused).toBe(false);
  } finally {
    await request.post("/api/brain/pause", { headers, data: { paused: false } });
    await request.delete(`/api/brain/knowledge/${item.id}`, { headers });
  }
});

test("a real example exposes its measured length hint and a bad example stops contributing it", async ({ page, request }) => {
  const directory = await mkdtemp(path.join(tmpdir(), "clipfoundry-brain-example-"));
  const file = path.join(directory, "six-second-example.mp4");
  execFileSync(process.env.CLIPFOUNDRY_FFMPEG || "ffmpeg", ["-v", "error", "-y", "-f", "lavfi", "-i",
    "color=c=0x233744:s=128x224:r=5", "-t", "6", "-c:v", "libx264", "-pix_fmt", "yuv420p", file]);
  try {
    await page.goto("/#/brain/examples");
    await page.getByRole("button", { name: "Add example", exact: true }).click();
    await page.getByLabel("Title", { exact: true }).fill("Lumen length — isolated real example");
    const details = page.locator(".brain-editor-details");
    if ((await details.getAttribute("open")) == null) await details.locator("summary").click();
    await page.getByLabel("Example clip (optional)").setInputFiles(file);
    await page.getByLabel("Topic tags (optional, separated by commas)").fill("lumen");
    await page.getByRole("button", { name: "Save knowledge", exact: true }).click();
    const effect = page.getByLabel("How Brain uses this lesson");
    await expect(page.locator(".brain-editor .brain-pill")).toHaveText("Used automatically");
    await expect(effect).toContainText("Measured length hint: 6.0 seconds");
    await expect(effect).toContainText("minimum and maximum clip lengths still apply");
    await expect(page.getByText(/Measured locally: 6.0 seconds/)).toBeVisible();
    const preview = () => request.post("/api/brain/knowledge/preview", {
      headers: { "X-ClipFoundry": "1" }, data: { text: "Lumen measurements in a lamp." },
    });
    const good = await (await preview()).json();
    expect(good.after.target_duration).toBeLessThan(good.before.target_duration);
    expect(good.after.target_duration).toBeGreaterThanOrEqual(20);
    const influence = good.influences.find((row: any) => row.snapshot.title === "Lumen length — isolated real example");
    expect(influence.decisions.target_duration.after).toBe(good.after.target_duration);
    const shots = path.resolve(process.env.CLIPFOUNDRY_BROWSER_SHOTS ||
      path.join(process.cwd(), "..", "design", "robot-office", "screenshots"));
    await mkdir(shots, { recursive: true });
    await page.screenshot({ path: path.join(shots, "brain-example-effect.png"), fullPage: true });
    await page.getByRole("combobox", { name: "Example judgment", exact: true }).selectOption("bad");
    await page.getByRole("button", { name: "Save changes", exact: true }).click();
    await expect(page.locator(".brain-editor .brain-pill")).toHaveText("Saved example");
    await expect(effect).toContainText("Its described traits are not copied");
    await expect(effect).not.toContainText("Measured length hint");
    const bad = await (await preview()).json();
    expect(bad.after.target_duration).toBe(bad.before.target_duration);
    expect(bad.influences.map((row: any) => row.knowledge_id)).not.toContain(influence.knowledge_id);
    expect((await request.delete(`/api/brain/knowledge/${influence.knowledge_id}`,
      { headers: { "X-ClipFoundry": "1" } })).ok()).toBe(true);
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
});
