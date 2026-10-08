import { expect, test, type APIRequestContext, type Page } from "@playwright/test";
import { mkdir } from "node:fs/promises";
import path from "node:path";

// The whole beginner experience, in the throwaway sandbox (never your real ClipFoundry):
// open ClipFoundry → Set up ClipFoundry → choose Autopilot and keep the suggested topics → connect accounts (test
// connections) → Start Autopilot → choose who watches (selected viewers, the one question asked) → no source
// configuration (only your videos folder) → trend discovery starts →
// sources are created internally → public videos are clipped on this PC (public video discovery, on by default),
// a video it cannot get is reported and skipped, and nothing is planned or posted without reuse permission, nor
// asked about → one agreement with a creator → that creator's checked clips are planned by themselves (waiting for
// your OK), while the other creators' clips stay on this PC.

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
    // OPEN CLIPFOUNDRY: the Office says what to do first, with nothing technical on it
    await page.goto("/#/");
    const panel = page.getByRole("complementary", { name: "Details" });
    await expect(panel).toContainText("Finish setting up");
    await nothingTechnical(page);
    const screenshots = path.resolve(process.cwd(), "..", "design", "robot-office", "screenshots");
    await mkdir(screenshots, { recursive: true });
    await page.screenshot({ path: path.join(screenshots, "first-run.png") });
    await panel.getByRole("link", { name: "Set up ClipFoundry" }).click();

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

    // START AUTOPILOT: one button, then the Office
    await page.getByRole("button", { name: "Start Autopilot" }).click();
    await expect(page).toHaveURL(/#\/$/);
    await expect(page.locator("#top-state")).toHaveText("Autopilot: On");
    await expect(page.locator("#office-run-state")).toHaveText("Running");

    // WHO WATCHES: the one question Needs you asks after connecting. Until it is answered nothing is planned for
    // a platform. The beginner picks the selected viewers once, in Settings → Integrations (never "Everyone"), so
    // the checks below that nothing is planned for other people's videos really test the permission to reuse them.
    const asksAudience = async () => (await get(request, "/api/autopilot/status")).home.needs_you
      .filter((need: any) => /^Choose who watches/.test(need.title)).map((need: any) => need.title).sort();
    await expect.poll(asksAudience, { timeout: 60_000 })
      .toEqual(["Choose who watches your TikTok clips", "Choose who watches your YouTube clips"]);
    await page.goto("/#/settings/integrations");
    for (const [name, choice] of [["YouTube", "My invited viewers"], ["TikTok", "My approved followers"]]) {
      const row = page.locator(".audience-row", { has: page.getByRole("heading", { name, exact: true }) });
      await row.getByRole("radio", { name: new RegExp(`^${choice}`) }).check();
      await row.getByRole("checkbox", { name: /^I understand/ }).check();
      await row.getByRole("button", { name: "Confirm who watches" }).click();
      await expect(row).toContainText("confirmed");
    }
    await expect.poll(asksAudience, { timeout: 90_000 }).toEqual([]);

    // MISSIONS (the Autopilot page): on, simple, and honest about the PC
    await page.goto("/#/missions");
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

    // TREND DISCOVERY STARTS AND SOURCES ARE CREATED INTERNALLY: public videos by other creators, and nothing
    // claims a reuse permission that nobody gave
    await expect.poll(async () => (await get<any[]>(request, "/api/autopilot/sources")).length, { timeout: 60_000 })
      .toBeGreaterThanOrEqual(3);
    const sources = await get<any[]>(request, "/api/autopilot/sources");
    expect(sources.every((s) => s.signal_id && s.rights_status === "MANUAL_CONFIRMATION_REQUIRED")).toBe(true);
    const found = async (id: string) => (await get<any[]>(request, "/api/autopilot/sources"))
      .find((s) => s.external_id === id);

    // CLIPPED ON THIS PC: public video discovery (on by default) gets each public video it can and makes clips from
    // it here. Getting the file is a separate question from the permission to reuse it.
    // (a short video gives one strong clip, so it counts as "weak": another video is tried as well)
    await expect.poll(async () => { const s = await found("int1"); return s?.clips_selected > 0 &&
      ["analyzed", "weak"].includes(s.status); }, { timeout: 300_000 }).toBe(true);
    const interview = await found("int1");
    expect(interview.access?.method).toBe("platform");
    expect(interview.rights_status).toBe("MANUAL_CONFIRMATION_REQUIRED");
    // A video it cannot get (a login, here) is reported with the reason, and Autopilot goes on with the others
    await expect.poll(async () => (await found("pod2"))?.status, { timeout: 120_000 }).toBe("failed");
    expect((await found("pod2")).status_note).toContain("could not be downloaded");

    // THE CLIPS PASS THE SAME FINAL CHECK AS ANY OTHER CLIP: only the missing permission keeps them from posting
    const project = await get(request, `/api/projects/${interview.project_id}`);
    const clipIds = new Set(project.clips.map((c: any) => c.id));
    const checks = async () => (await get<any[]>(request,
      "/api/autopilot/jobs?status=completed&worker=quality_gate&limit=200"))
      .filter((j) => clipIds.has(j.ref_id) && j.result?.status === "passed");
    await expect.poll(async () => (await checks()).length, { timeout: 180_000 }).toBeGreaterThan(0);
    // Planning runs after every passed check and every minute; let it run after the last of them
    const checkedAt = Math.max(...(await checks()).map((j) => j.updated_at));
    await expect.poll(async () => (await get<any[]>(request,
      "/api/autopilot/jobs?status=completed&worker=scheduler&limit=50")).some((j) => j.updated_at > checkedAt),
    { timeout: 150_000 }).toBe(true);

    // NEVER PLANNED OR POSTED: posting is decided apart from clipping, and these videos have no reuse permission
    const planned = async () => (await get(request, "/api/autopilot/scheduled?view=all")).items as any[];
    const publicIds = new Set(sources.map((s) => s.id));
    expect((await planned()).filter((p) => publicIds.has(p.source?.id))).toEqual([]);
    expect(await get<any[]>(request, "/api/autopilot/jobs?status=&worker=publisher&limit=50")).toEqual([]);

    // NOT COVERED: never asked about one by one. Activity says what was made and that it stays on this PC
    await expect(page.locator('.needs-you .need[data-type="rights"]')).toHaveCount(0);
    await expect(page.locator('.needs-you .need[data-type="videos"]')).toHaveCount(0);
    await page.goto("/#/missions/activity");
    const made = page.locator(".activity-row.used", { hasText: "Podcast interview: the founder who almost quit" });
    await expect(made).toContainText(/\d+ clips? made/);
    await expect(made).toContainText("Not covered");
    await expect(made.locator(".not-posted")).toContainText("stay on this PC and are never posted");
    const blocked = page.locator(".activity-row", { hasText: "Podcast debate gets heated over remote work" });
    await expect(blocked).toContainText("could not be downloaded");

    // THE OFFICE SAYS THE SAME: Autopilot runs, without a normal question under Needs your action.
    await page.goto("/#/");
    await expect(page.locator("#office-run-state")).toHaveText("Running");
    const needs = panel.locator(".op-needs");  // e.g. "Choose who watches": never a question about one video
    if (await needs.count()) await expect(needs).not.toContainText(/trending video|needs videos/);
    expect((await get(request, "/api/autopilot/status")).home.needs_you
      .filter((need: any) => ["videos", "rights"].includes(need.type))).toEqual([]);

    // ONE AGREEMENT, RECORDED ONCE: the creator allows clipping and shares their raw files in a folder
    const health = await get(request, "/api/health");
    await page.goto("/#/missions/sources");
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

    // THE AGREEMENT DECIDES POSTING BY ITSELF: that creator's video is covered and its checked clips are planned
    // (waiting for your OK: connecting accounts does not let ClipFoundry post by itself), with no per-video question
    await expect.poll(async () => (await found("pod1"))?.rights_status, { timeout: 60_000 }).toBe("ALLOWLISTED");
    const pod1 = await found("pod1");
    expect(["queued", "ingesting", "analyzing", "analyzed", "weak"]).toContain(pod1.status);
    await expect.poll(async () => (await planned()).filter((p) => p.source?.id === pod1.id).length,
      { timeout: 420_000 }).toBeGreaterThan(0);
    const posts = (await planned()).filter((p) => p.source?.id === pod1.id);
    expect(posts.every((p) => p.status === "awaiting_approval")).toBe(true);
    // The other creators' videos stay unplanned, and nothing was uploaded
    expect((await planned()).filter((p) => p.source?.id !== pod1.id)).toEqual([]);
    expect((await found("int1")).rights_status).toBe("MANUAL_CONFIRMATION_REQUIRED");
    expect(await get<any[]>(request, "/api/autopilot/jobs?status=&worker=publisher&limit=50")).toEqual([]);

    await page.goto("/#/missions");
    await expect(page.locator('.needs-you .need[data-type="rights"]')).toHaveCount(0);
    await expect(page.locator('.needs-you .need[data-type="videos"]')).toHaveCount(0); // it has a video to work on
    await expect(page.locator("#ap-state")).toContainText("Autopilot is on");
  });
