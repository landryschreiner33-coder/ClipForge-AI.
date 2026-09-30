import { expect, test, type APIRequestContext } from "@playwright/test";
import path from "node:path";

// The whole beginner experience, in the throwaway sandbox (never your real ClipFoundry):
// open ClipFoundry → connect accounts (test connections) → keep the suggested topics → START AUTOPILOT → no source
// configuration (only your videos folder) → trend discovery starts → sources are created internally → videos nothing
// covers are skipped, not asked about, and Needs you says Autopilot needs videos → one agreement with a creator (with
// the folder they share) → that creator's video goes to the pipeline by itself, with no per-video question.

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

  // CHOOSE TOPICS: a suggestion is already filled in and can be kept as it is
  await expect(page.getByRole("textbox", { name: "Topics" })).not.toHaveValue("");

  // TURN AUTOPILOT ON: one button
  await page.getByRole("button", { name: "START AUTOPILOT" }).click();
  await expect(page.getByText("AUTOPILOT ON", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "PAUSE AUTOPILOT" })).toBeVisible();
  await expect(page.getByRole("heading", { name: /^Needs you/ })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Top opportunities" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Upcoming posts" })).toBeVisible();
  await expect(page.getByText("How posts go out")).toBeVisible();
  await expect(page.getByText("Keep this PC on", { exact: false })).toBeVisible();
  await expect(page.getByText("Workers", { exact: true })).toHaveCount(0);

  // NO SOURCE CONFIGURATION: nobody added a feed, folder, rule or source; START only set up your videos folder
  const feeds = await get<any[]>(request, "/api/autopilot/feeds");
  expect(feeds.map((f) => f.name)).toEqual(["Your videos folder"]);
  const rules = (await get(request, "/api/autopilot/rights")).rules;
  expect(rules.map((r: any) => [r.scope, r.status])).toEqual([["folder", "OWNED"]]);
  await expect(page.getByRole("heading", { name: "Your videos" })).toBeVisible();

  // TREND DISCOVERY STARTS AND SOURCES ARE CREATED INTERNALLY, each with its rights checked
  await expect.poll(async () => (await get<any[]>(request, "/api/autopilot/sources")).length, { timeout: 60_000 })
    .toBeGreaterThanOrEqual(3);
  const sources = await get<any[]>(request, "/api/autopilot/sources");
  expect(sources.every((s) => s.signal_id && s.rights_status === "MANUAL_CONFIRMATION_REQUIRED")).toBe(true);
  const hunts = await get<any[]>(request, "/api/autopilot/jobs?status=&worker=clip_hunter&limit=50");
  expect(hunts, "nothing uncovered is ever clipped").toEqual([]);

  // NOT COVERED: skipped and listed in the activity log, never asked about one by one. Needs you says once, plainly,
  // that Autopilot has nothing it may use and what helps: your own videos in your videos folder.
  await expect(page.getByText(/videos? skipped in the last 24 hours/)).toBeVisible({ timeout: 30_000 });
  await expect(page.locator('.needs-you .action[data-type="rights"]')).toHaveCount(0);
  const needsVideos = page.locator('.needs-you .action[data-type="videos"]');
  await expect(needsVideos).toContainText("Autopilot needs videos to work with");
  await expect(needsVideos.getByRole("button", { name: "OPEN MY VIDEOS FOLDER" })).toBeVisible();
  await page.getByRole("button", { name: "Show activity" }).click();
  const skipped = page.locator(".activity-row.skipped", { hasText: "The podcast moment everyone is talking about" });
  await expect(skipped).toContainText("Not covered");

  // ONE AGREEMENT, RECORDED ONCE: the creator allows clipping and shares their raw files in a folder
  const health = await get(request, "/api/health");
  await page.goto("/#/autopilot/sources");
  await page.getByRole("button", { name: "+ Record an agreement" }).click();
  await page.getByLabel("Creator", { exact: true }).fill("The Podcast Channel");
  await page.getByLabel(/YouTube channel IDs and TikTok handles/).fill("UCpodcast000000001");
  await page.getByLabel(/What shows the agreement/).fill("Email from them on 2026-09-01: you may clip and post our episodes");
  await page.getByLabel(/Folder with their files on this computer/)
    .fill(path.join(health.data_dir, "sandbox", "Podcast creator shared"));
  await page.getByRole("button", { name: "Save agreement" }).click();
  await expect(page.locator(".agreements").getByText("The Podcast Channel")).toBeVisible();

  // PIPELINE CONTINUES BY ITSELF: covered by the agreement, file from the shared folder, sent to the Clip Hunter
  const covered = () => get<any[]>(request, "/api/autopilot/sources")
    .then((all) => all.find((s) => s.external_id === "pod1"));
  await expect.poll(async () => (await covered())?.status, { timeout: 60_000 })
    .toMatch(/^(queued|ingesting|analyzing|analyzed|weak)$/);
  const src = await covered();
  expect(src.rights_status).toBe("ALLOWLISTED");
  expect(src.access?.method).toBe("creator_folder");
  await expect.poll(async () => (await get<any[]>(request, "/api/autopilot/jobs?status=&worker=clip_hunter&limit=50"))
    .filter((j) => j.ref_id === src.id).length, { timeout: 30_000 }).toBeGreaterThan(0);
  // The other creators' videos stay skipped
  const others = (await get<any[]>(request, "/api/autopilot/sources")).filter((s) => s.external_id !== "pod1");
  expect(others.every((s) => s.rights_status === "MANUAL_CONFIRMATION_REQUIRED")).toBe(true);

  await page.goto("/#/autopilot");
  await expect(page.locator('.needs-you .action[data-type="rights"]')).toHaveCount(0);
  await expect(page.locator('.needs-you .action[data-type="videos"]')).toHaveCount(0);  // it has a video to work on
  await expect(page.locator(".home-now").first()).not.toHaveText("Off");
});
