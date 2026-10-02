import { expect, test, type APIRequestContext, type Page } from "@playwright/test";
import path from "node:path";

// The whole beginner experience, in the throwaway sandbox (never your real ClipFoundry):
// open ClipFoundry → Get started → choose Autopilot and keep the suggested topics → connect accounts (test
// connections) → Start Autopilot → no source configuration (only your videos folder) → trend discovery starts →
// sources are created internally → videos nothing covers are skipped, not asked about → one agreement with a
// creator (with the folder they share) → that creator's video goes to the
// pipeline by itself, with no per-video question.

const get = async <T = any>(request: APIRequestContext, url: string): Promise<T> => {
  const res = await request.get(url);
  expect(res.status(), `GET ${url}`).toBe(200);
  return res.json();
};
const TECHNICAL = ["Workers", "Where sources come from", "Rights rules", "YouTube API quota", "Add a source", "Jobs"];
const nothingTechnical = async (page: Page) => {
  for (const words of TECHNICAL) await expect(page.getByText(words, { exact: true })).toHaveCount(0);
};

test("Get started, choose Autopilot, connect accounts, Start Autopilot, and ClipFoundry does the rest",
  async ({ page, request }) => {
    // OPEN CLIPFOUNDRY: Home welcomes you, with nothing technical on it
    await page.goto("/#/");
    const lead = page.locator("section.lead");
    await expect(lead.locator("#lead-title")).toHaveText(/^Start by adding a video you made/);
    await nothingTechnical(page);
    await lead.getByRole("link", { name: "Get started" }).click();

    // STEP 1, YOUR VIDEOS: one video now, or your videos folder (not opened here: Start sets it up)
    await expect(page).toHaveURL(/#\/setup\/videos$/);
    await expect(page.getByRole("heading", { name: "Where are your videos?" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Open videos folder" })).toBeVisible();
    await nothingTechnical(page);
    await page.getByRole("link", { name: "Continue" }).click();

    // STEP 2, HOW TO WORK: Autopilot, with a suggestion for its topics already filled in
    await expect(page).toHaveURL(/#\/setup\/mode$/);
    await page.getByRole("radio", { name: /Let Autopilot do it/ }).check();
    await expect(page.getByRole("textbox", { name: "Topics" })).not.toHaveValue("");
    await page.getByRole("button", { name: "Continue" }).click();

    // STEP 3, POSTING: each Connect opens the platform's sign-in page (here: the test stand-in) in a new tab
    await expect(page).toHaveURL(/#\/setup\/posting$/);
    for (const [button, done] of [["Connect YouTube", "YouTube connected"], ["Connect TikTok", "TikTok connected"]]) {
      const popup = page.waitForEvent("popup");
      await page.getByRole("button", { name: button }).click();
      const tab = await popup;
      await expect(tab.getByText(done)).toBeVisible();
      await tab.close();
    }
    await expect(page.getByText(/^Connected: /)).toHaveCount(2);
    // Connecting does not allow posting by itself; the page says so before you start
    await expect(page.getByText("does not let ClipFoundry post by itself", { exact: false })).toBeVisible();

    // START AUTOPILOT: one button, then Home
    await page.getByRole("button", { name: "Start Autopilot" }).click();
    await expect(page).toHaveURL(/#\/$/);
    await expect(page.locator(".page-head").getByRole("link", { name: "Autopilot: On" })).toBeVisible();

    // THE AUTOPILOT PAGE: on, simple, and honest about the PC
    await page.goto("/#/autopilot");
    await expect(page.locator("#ap-state")).toContainText("Autopilot is on");
    await expect(page.getByRole("button", { name: "Pause Autopilot" })).toBeVisible();
    for (const h of [/^Needs you/, /^Working on$/, /^Your videos$/, /^Coming up$/, /^How posts go out$/]) {
      await expect(page.getByRole("heading", { name: h })).toBeVisible();
    }
    await expect(page.locator(".pc-note")).toContainText("Keep this PC on");
    await nothingTechnical(page);

    // NO SOURCE CONFIGURATION: nobody added a feed, folder, rule or source; Start only set up your videos folder
    const feeds = await get<any[]>(request, "/api/autopilot/feeds");
    expect(feeds.map((f) => f.name)).toEqual(["Your videos folder"]);
    const rules = (await get(request, "/api/autopilot/rights")).rules;
    expect(rules.map((r: any) => [r.scope, r.status])).toEqual([["folder", "OWNED"]]);

    // TREND DISCOVERY STARTS AND SOURCES ARE CREATED INTERNALLY, each with its rights checked
    await expect.poll(async () => (await get<any[]>(request, "/api/autopilot/sources")).length, { timeout: 60_000 })
      .toBeGreaterThanOrEqual(3);
    const sources = await get<any[]>(request, "/api/autopilot/sources");
    expect(sources.every((s) => s.signal_id && s.rights_status === "MANUAL_CONFIRMATION_REQUIRED")).toBe(true);
    const hunts = await get<any[]>(request, "/api/autopilot/jobs?status=&worker=clip_hunter&limit=50");
    expect(hunts, "nothing uncovered is ever clipped").toEqual([]);

    // NOT COVERED: skipped and listed in Activity, never asked about one by one. Empty discovery is an ordinary
    // waiting state, while Your videos still explains how the owner can supply useful material.
    await expect(page.getByText(/videos? skipped in the last 24 hours/)).toBeVisible({ timeout: 30_000 });
    await expect(page.locator('.needs-you .need[data-type="rights"]')).toHaveCount(0);
    await expect(page.locator('.needs-you .need[data-type="videos"]')).toHaveCount(0);
    await expect(page.getByRole("region", { name: "Working on" }).getByRole("button", { name: "Open videos folder" }))
      .toBeVisible();
    await page.getByRole("link", { name: "See Activity" }).click();
    await expect(page).toHaveURL(/#\/autopilot\/activity$/);
    const skipped = page.locator(".activity-row.skipped", { hasText: "The podcast moment everyone is talking about" });
    await expect(skipped).toContainText("Skipped");
    await expect(skipped).toContainText("Not covered");

    // HOME SAYS THE SAME: waiting is visible, without a normal question in Needs you.
    await page.goto("/#/");
    await expect(lead.locator("#lead-title")).toHaveText("Nothing needs you. Add a video to make clips.");
    expect((await get(request, "/api/autopilot/status")).home.needs_you
      .filter((need: any) => ["videos", "rights"].includes(need.type))).toEqual([]);

    // ONE AGREEMENT, RECORDED ONCE: the creator allows clipping and shares their raw files in a folder
    const health = await get(request, "/api/health");
    await page.goto("/#/autopilot/sources");
    await page.getByRole("button", { name: "Record an agreement…" }).click();
    const dialog = page.getByRole("dialog", { name: "Record an agreement with a creator" });
    await dialog.getByLabel("Creator", { exact: true }).fill("The Podcast Channel");
    await dialog.getByLabel(/YouTube channel IDs and TikTok handles/).fill("UCpodcast000000001");
    await dialog.getByLabel(/What shows the agreement/)
      .fill("Email from them on 2026-09-01: you may clip and post our episodes");
    await dialog.getByLabel(/Folder with their files on this computer/)
      .fill(path.join(health.data_dir, "sandbox", "Podcast creator shared"));
    await dialog.getByRole("button", { name: "Save agreement" }).click();
    await expect(dialog).toHaveCount(0);
    await expect(page.locator(".agreements .agreement", { hasText: "The Podcast Channel" })).toHaveCount(1);

    // PIPELINE CONTINUES BY ITSELF: covered by the agreement, file from the shared folder, sent to the Clip Hunter
    const covered = () => get<any[]>(request, "/api/autopilot/sources")
      .then((all) => all.find((s) => s.external_id === "pod1"));
    await expect.poll(async () => (await covered())?.status, { timeout: 60_000 })
      .toMatch(/^(queued|ingesting|analyzing|analyzed|weak)$/);
    const src = await covered();
    expect(src.rights_status).toBe("ALLOWLISTED");
    expect(src.access?.method).toBe("creator_folder");
    await expect.poll(async () => (await get<any[]>(request,
      "/api/autopilot/jobs?status=&worker=clip_hunter&limit=50")).filter((j) => j.ref_id === src.id).length,
    { timeout: 30_000 }).toBeGreaterThan(0);
    // The other creators' videos stay skipped
    const others = (await get<any[]>(request, "/api/autopilot/sources")).filter((s) => s.external_id !== "pod1");
    expect(others.every((s) => s.rights_status === "MANUAL_CONFIRMATION_REQUIRED")).toBe(true);

    await page.goto("/#/autopilot");
    await expect(page.locator('.needs-you .need[data-type="rights"]')).toHaveCount(0);
    await expect(page.locator('.needs-you .need[data-type="videos"]')).toHaveCount(0); // it has a video to work on
    await expect(page.locator("#ap-state")).toContainText("Autopilot is on");
  });
