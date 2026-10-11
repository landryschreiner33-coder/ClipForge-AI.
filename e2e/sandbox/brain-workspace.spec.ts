import { expect, test } from "@playwright/test";
import { mkdir } from "node:fs/promises";
import path from "node:path";

// This suite runs only against the throwaway sandbox, never the owner's normal app/data/accounts.
test("an uploaded guide persists, requires approval, and demonstrates its real preference lookup", async ({ page, request }) => {
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
  await expect(page.getByRole("button", { name: "Review & approve", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Review & approve", exact: true }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Approve preferences", exact: true }).click();
  await expect(page.getByText("Approved revision 1.", { exact: false })).toBeVisible();
  await page.reload();
  await expect(page.getByLabel("Title", { exact: true })).toHaveValue("Science caption guide — isolated test");
  await page.screenshot({ path: path.join(shots, "brain-knowledge.png"), fullPage: true });
  await page.getByRole("button", { name: "Try a decision", exact: true }).click();
  await page.getByLabel("Clip context", { exact: true }).fill("Science explains why sleep helps memory.");
  await page.getByRole("button", { name: "Apply approved preferences", exact: true }).click();
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
