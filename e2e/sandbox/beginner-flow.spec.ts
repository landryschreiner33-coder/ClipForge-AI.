import { expect, test, type APIRequestContext } from "@playwright/test";
import path from "node:path";

// The whole beginner experience, in the throwaway sandbox (never your real ClipFoundry):
// open ClipFoundry → connect accounts (test connections) → turn Autopilot on → no source configuration →
// trend discovery starts → a source is created internally → the pipeline continues.

const get = async <T = any>(request: APIRequestContext, url: string): Promise<T> => {
  const res = await request.get(url);
  expect(res.status(), `GET ${url}`).toBe(200);
  return res.json();
};

test("connect accounts, press START AUTOPILOT, and ClipFoundry does the rest", async ({ page, request }) => {
  // OPEN CLIPFOUNDRY: the first-run screen, with nothing technical on it
  await page.goto("/#/autopilot");
  await expect(page.getByText("CLIPFOUNDRY AUTOPILOT")).toBeVisible();
  for (const technical of ["Workers", "Where sources come from", "Rights rules", "YouTube API quota", "Add a source"]) {
    await expect(page.getByText(technical, { exact: true })).toHaveCount(0);
  }

  // CONNECT ACCOUNTS: each CONNECT opens the platform's sign-in page (here: the test stand-in) in a new tab
  for (const [button, done] of [["CONNECT YOUTUBE", "YouTube connected"], ["CONNECT TIKTOK", "TikTok connected"]]) {
    const popup = page.waitForEvent("popup");
    await page.getByRole("button", { name: button }).click();
    const tab = await popup;
    await expect(tab.getByText(done)).toBeVisible();
    await tab.close();
  }
  await expect(page.locator(".ob-step .badge.good")).toHaveCount(2);

  // TURN AUTOPILOT ON: one button
  await page.getByRole("button", { name: "START AUTOPILOT" }).click();
  await expect(page.getByRole("switch", { name: "AUTOPILOT ON" })).toBeVisible();
  await expect(page.getByRole("heading", { name: /^Needs you/ })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Top opportunities" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Upcoming posts" })).toBeVisible();
  await expect(page.getByText("Workers", { exact: true })).toHaveCount(0);

  // NO SOURCE CONFIGURATION: no feed, folder, rule or source was added by anyone
  expect(await get(request, "/api/autopilot/feeds")).toEqual([]);
  expect((await get(request, "/api/autopilot/rights")).rules).toEqual([]);

  // TREND DISCOVERY STARTS: what YouTube reports as trending shows up as opportunities
  const opportunities = page.locator(".card", { has: page.getByRole("heading", { name: "Top opportunities" }) });
  await expect(opportunities.getByText("The podcast moment everyone is talking about")).toBeVisible({ timeout: 60_000 });

  // SOURCE IS CREATED INTERNALLY: from discovery, each with its rights checked
  await expect.poll(async () => (await get<any[]>(request, "/api/autopilot/sources")).length, { timeout: 30_000 })
    .toBeGreaterThanOrEqual(3);
  const sources = await get<any[]>(request, "/api/autopilot/sources");
  expect(sources.every((s) => s.signal_id && s.rights_status === "MANUAL_CONFIRMATION_REQUIRED")).toBe(true);
  const hunts = await get<any[]>(request, "/api/autopilot/jobs?status=&worker=clip_hunter&limit=50");
  expect(hunts, "nothing unconfirmed is ever clipped").toEqual([]);

  // Only a strong video is worth a question, in plain words
  const question = page.locator('.needs-you .action[data-type="rights"]').first();
  await expect(question).toContainText("Can you use this content?");
  await expect(question.getByRole("link", { name: "VIEW SOURCE" })).toHaveAttribute("href", /^https:\/\/www\.youtube\.com\//);
  await question.getByRole("button", { name: "YES, I HAVE PERMISSION" }).click();

  // YouTube-hosted: ClipFoundry does not download it by itself, it asks for the original file
  const fileCard = page.locator('.needs-you .action[data-type="file"]').first();
  await expect(fileCard).toBeVisible({ timeout: 30_000 });
  const allowed = (await get<any[]>(request, "/api/autopilot/sources")).find((s) => s.rights_status === "ALLOWLISTED");
  expect(allowed?.status).toBe("needs_file");
  const health = await get(request, "/api/health");
  page.once("dialog", (d) => d.accept(path.join(health.data_dir, "sandbox", "original.mp4")));
  await fileCard.getByRole("button", { name: "ADD THE VIDEO FILE" }).click();

  // PIPELINE CONTINUES: the source goes to the Clip Hunter by itself
  await expect.poll(async () => (await get<any[]>(request, "/api/autopilot/sources")).find((s) => s.id === allowed.id)?.status,
    { timeout: 60_000 }).toMatch(/^(queued|ingesting|analyzing|analyzed|weak)$/);
  await expect.poll(async () => (await get<any[]>(request, "/api/autopilot/jobs?status=&worker=clip_hunter&limit=50"))
    .filter((j) => j.ref_id === allowed.id).length, { timeout: 30_000 }).toBeGreaterThan(0);
  await expect(page.locator(".home-now").first()).not.toHaveText("Off");
});
