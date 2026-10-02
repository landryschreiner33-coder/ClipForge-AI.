import type { APIRequestContext, Page } from "@playwright/test";
import { expect, getJson, test } from "../fixtures";

// Looks at Autopilot without operating it. Never pressed: Start or Pause Autopilot, Resume jobs, Open videos folder,
// Connect, Use it, the answers under Needs you, switches, Scan now, Learn now, Dismiss, Retry, Cancel and Log.
// Dialogs are only opened and closed (Stop all jobs… with Keep running, the add dialogs with Cancel or Escape).
// Each test checks that Autopilot's on/off and paused state are the same afterwards, and the fixture blocks (and
// fails on) any request from the page that would change something.

const onOff = async (request: APIRequestContext) => {
  const st = await getJson(request, "/api/autopilot/status");
  return { enabled: st.enabled, paused: st.paused };
};
/** Until Autopilot was started once, the overview points to Setup instead. */
const notSetUp = (st: any) => !st.enabled && !st.home.setup.started;
const sections = (page: Page) => page.getByRole("navigation", { name: "Autopilot sections" });
const fact = (page: Page, label: string) =>
  page.locator(".fact", { has: page.locator(".k", { hasText: label }) }).locator(".v");
let before: { enabled: boolean; paused: boolean };

test.beforeEach(async ({ page, request }) => {
  before = await onOff(request);
  await page.goto("/#/autopilot");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Autopilot");
});

test.afterEach(async ({ request }) => {
  expect(await onOff(request), "Autopilot's on/off or paused state changed during the test").toEqual(before);
});

test("the overview shows Autopilot's real state, and Stop all jobs asks first", async ({ page, request }) => {
  const st = await getJson(request, "/api/autopilot/status");
  await expect(sections(page).getByRole("link", { name: "Overview" })).toHaveAttribute("aria-current", "page");
  const resume = page.getByRole("button", { name: "Resume jobs" });
  if (st.paused) {
    await expect(page.getByText("All jobs are stopped.")).toBeVisible();
    await expect(resume).toBeVisible();
  } else {
    await expect(resume).toHaveCount(0);
  }
  const start = page.getByRole("button", { name: "Start Autopilot", exact: true });
  const pause = page.getByRole("button", { name: "Pause Autopilot", exact: true });
  if (notSetUp(st)) {
    await expect(page.getByRole("heading", { name: "Autopilot is not set up" })).toBeVisible();
    await expect(page.getByRole("link", { name: "Set up Autopilot" })).toHaveAttribute("href", "#/setup/mode");
    await expect(start).toHaveCount(0);
    await expect(pause).toHaveCount(0);
    return;
  }
  const headline = page.locator("#ap-state");
  if (st.paused) {
    await expect(headline).toHaveText("Autopilot is stopped");
    await expect(start).toHaveCount(0);
    await expect(pause).toHaveCount(0);
  } else if (st.enabled) {
    await expect(headline).toContainText("Autopilot is on");
    await expect(pause).toBeVisible();
    await expect(start).toHaveCount(0);
  } else {
    await expect(headline).toHaveText("Autopilot is paused");
    await expect(start).toBeVisible();
    await expect(pause).toHaveCount(0);
  }
  await expect(page.getByRole("heading", { name: "Pause or stop everything" })).toBeVisible();
  if (!st.paused) {
    // The emergency stop says what it does before anything happens; Keep running closes it without a change.
    await page.getByRole("button", { name: "Stop all jobs…" }).click();
    const dialog = page.getByRole("dialog", { name: "Stop all jobs?" });
    await expect(dialog).toContainText("Queued work is canceled");
    await expect(dialog.getByRole("button", { name: "Stop all jobs", exact: true })).toBeVisible();
    await dialog.getByRole("button", { name: "Keep running" }).click();
    await expect(dialog).toHaveCount(0);
  }
});

test("the overview has simple facts and reports the real keep-awake state", async ({ page, request }) => {
  const first = await getJson(request, "/api/autopilot/status");
  test.skip(notSetUp(first), "Autopilot was never started here: the overview shows Set up Autopilot instead");
  // Kept awake only when Windows agreed (the real state, never the setting alone)
  await expect(async () => {
    const st = await getJson(request, "/api/autopilot/status");
    const on = st.enabled && !st.paused;
    const word = !on ? "Not kept awake" : ({
      on: "Kept awake", pending: "Asking Windows", failed: "Windows said no",
      unsupported: "Not available on this computer",
    } as Record<string, string>)[st.home.keep_awake] || "Not kept awake";
    await expect(fact(page, "This PC")).toHaveText(word, { timeout: 1000 });
    await expect(page.locator(".pc-note")).toHaveText(st.home.pc_note, { timeout: 1000 });
  }).toPass();
  for (const label of ["Now", "Progress", "Next", "Posts"]) await expect(fact(page, label)).toBeVisible();
  await expect(fact(page, "Processing")).toHaveCount(0);
  await expect(async () => {
    const st = await getJson(request, "/api/autopilot/status");
    const posts = st.home.posts;
    await expect(fact(page, "Posts")).toHaveText(`${posts.ready ?? 0} ready · ${posts.scheduled
      ?? st.target.scheduled_posts} scheduled · ${posts.review} need your OK`, { timeout: 1000 });
  }).toPass();
  // A search that did not work is named with what to do, while the other searches go on
  await expect(async () => {
    const st = await getJson(request, "/api/autopilot/status");
    const problems = st.enabled && !st.paused ? st.home.discovery.problems : [];
    const note = page.locator(".search-problems");
    await expect(note).toHaveCount(problems.length ? 1 : 0, { timeout: 1000 });
    for (const p of problems) await expect(note).toContainText(`${p.name}: ${p.detail}`, { timeout: 1000 });
  }).toPass();
  // Your videos folder: where it is (Open videos folder is not pressed: it would create and watch the folder)
  const st = await getJson(request, "/api/autopilot/status");
  await expect(page.getByRole("heading", { name: "Your videos", exact: true })).toBeVisible();
  await expect(page.locator(".my-videos-path")).toHaveText(st.home.my_videos.path);
  await expect(page.locator(".my-videos").getByRole("button", { name: "Open videos folder" })).toBeVisible();
  for (const h of ["Working on", "Coming up", "How posts go out"]) {
    await expect(page.getByRole("heading", { name: h, exact: true })).toBeVisible();
  }
});

test("video and stream intake is available without configuring a source", async ({ page, request }) => {
  await expect(page.getByRole("heading", { name: "Add a video or stream", exact: true })).toBeVisible();
  const input = page.getByLabel("Paste a video or stream link", { exact: true });
  const add = page.getByRole("button", { name: "ADD", exact: true });
  await expect(input).toBeVisible();
  await expect(add).toBeDisabled();
  // Typing alone is read-only; ADD and the item actions are never pressed against the user's data.
  await input.fill("https://example.com/video.mp4");
  await expect(add).toBeEnabled();
  await input.fill("");
  await expect(add).toBeDisabled();
  await expect(page.getByRole("heading", { name: "Added by you", exact: true })).toBeVisible();
  await expect(async () => {
    const links = await getJson<any[]>(request, "/api/autopilot/links");
    const rows = page.locator(".ap-link-row");
    await expect(rows).toHaveCount(links.length, { timeout: 1000 });
    for (const item of links) {
      const row = rows.filter({ has: page.locator(`[id="ap-link-title-${item.id}"]`) });
      await expect(row).toContainText(item.title || "Video or stream", { timeout: 1000 });
      await expect(row).toContainText(item.status_label, { timeout: 1000 });
      for (const [field, action] of [["can_remove", "Remove"], ["can_cancel", "Cancel"],
        ["can_retry", "Retry"], ["can_prioritize", "Move to top"]]) {
        await expect(row.getByRole("button", { name: new RegExp(`^${action}:`) }))
          .toHaveCount(item[field] ? 1 : 0, { timeout: 1000 });
      }
    }
  }).toPass();
});

test("Needs you lists exactly what Autopilot reports", async ({ page, request }) => {
  const st = await getJson(request, "/api/autopilot/status");
  test.skip(notSetUp(st), "Autopilot was never started here: the overview shows Set up Autopilot instead");
  await expect(page.getByRole("heading", { name: /^Needs you/ })).toBeVisible();
  await expect(async () => {
    const home = (await getJson(request, "/api/autopilot/status")).home;
    const rows = page.locator(".needs-you .need");
    await expect(rows).toHaveCount(home.needs_you.length, { timeout: 1000 });
    if (!home.needs_you.length) await expect(page.locator(".needs-you").getByText("Nothing right now.")).toBeVisible({ timeout: 1000 });
    for (const [i, item] of home.needs_you.slice(0, 5).entries()) {
      await expect(rows.nth(i)).toHaveAttribute("data-type", item.type, { timeout: 1000 });
      await expect(rows.nth(i)).toContainText(item.title, { timeout: 1000 });
    }
  }).toPass();
});

test("nothing technical on the overview: that lives under Advanced", async ({ page }) => {
  for (const h of ["Workers", "GPU", "YouTube API quota", "Jobs", "Trend opportunities", "Recent events"]) {
    await expect(page.getByRole("heading", { name: h, exact: true })).toHaveCount(0);
  }
  await sections(page).getByRole("link", { name: "Advanced" }).click();
  await expect(page).toHaveURL(/#\/autopilot\/system$/);
  await expect(page.getByRole("navigation", { name: "Advanced" }).getByRole("link", { name: "System" }))
    .toHaveAttribute("aria-current", "page");
  await expect(page.getByRole("heading", { name: /^Workers/ })).toBeVisible();
});

test("Activity shows what Autopilot found and what it did with each video", async ({ page, request }) => {
  await sections(page).getByRole("link", { name: "Activity" }).click();
  await expect(page).toHaveURL(/#\/autopilot\/activity$/);
  await expect(page.getByRole("heading", { name: "What Autopilot found" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Activity", exact: true })).toBeVisible();
  await expect(async () => {
    const { items } = await getJson(request, "/api/autopilot/activity");
    if (!items.length) await expect(page.getByText("Nothing yet.")).toBeVisible({ timeout: 1000 });
    else await expect(page.locator(".activity-row")).toHaveCount(items.length, { timeout: 1000 });
  }).toPass();
});

test("Permissions & sources lists agreements, places, rules and found videos", async ({ page, request }) => {
  await sections(page).getByRole("link", { name: "Permissions & sources" }).click();
  await expect(page).toHaveURL(/#\/autopilot\/sources$/);
  for (const h of ["Creator agreements", "Where videos come from", "Permission rules",
    "Found videos and their permission"]) {
    await expect(page.getByRole("heading", { name: h })).toBeVisible();
  }
  await expect(async () => {
    const [agreements, feeds, rights, sources] = await Promise.all([
      getJson<any[]>(request, "/api/autopilot/agreements"), getJson<any[]>(request, "/api/autopilot/feeds"),
      getJson(request, "/api/autopilot/rights"), getJson<any[]>(request, "/api/autopilot/sources"),
    ]);
    await expect(page.locator(".agreements .agreement")).toHaveCount(agreements.length, { timeout: 1000 });
    await expect(page.locator(".feed")).toHaveCount(feeds.length, { timeout: 1000 });
    await expect(page.locator(".rule")).toHaveCount(rights.rules.length, { timeout: 1000 });
    await expect(page.locator(".source")).toHaveCount(sources.length, { timeout: 1000 });
  }).toPass();
});

test("the add dialogs on Permissions & sources open and close without a change", async ({ page }) => {
  await page.goto("/#/autopilot/sources");
  // Record an agreement: the fields it needs, then Cancel
  await page.getByRole("button", { name: "Record an agreement…" }).click();
  let dialog = page.getByRole("dialog", { name: "Record an agreement with a creator" });
  await expect(dialog.getByLabel("Creator", { exact: true })).toBeVisible();
  await expect(dialog.getByLabel(/YouTube channel IDs and TikTok handles/)).toBeVisible();
  await expect(dialog.getByLabel(/What shows the agreement/)).toBeVisible();
  await expect(dialog.getByLabel(/Folder with their files on this computer/)).toBeVisible();
  await dialog.getByRole("button", { name: "Cancel" }).click();
  await expect(dialog).toHaveCount(0);
  // Add a video by hand: every way to add one and whether it may be used, then Escape
  await page.getByRole("button", { name: "Add…" }).click();
  await page.getByRole("menuitem", { name: "A video, link or folder of yours…" }).click();
  dialog = page.getByRole("dialog", { name: "Add a video Autopilot may use" });
  const ways = dialog.getByRole("radiogroup", { name: "What to add" });
  for (const way of ["A link", "A file", "A folder to watch", "Upload a video"]) {
    await expect(ways.getByRole("radio", { name: way, exact: true })).toBeVisible();
  }
  await expect(dialog.getByRole("group", { name: "Can ClipFoundry use it?" }).getByRole("radio")).toHaveCount(3);
  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);
});

test("System shows today's numbers and every status panel", async ({ page, request }) => {
  await page.goto("/#/autopilot/system");
  const st = await getJson(request, "/api/autopilot/status");
  await expect(page.locator(".daily")).toContainText(`of ${st.target.daily} unique clips posted today`);
  for (const h of ["Today's numbers", "Workers", "GPU", "This computer", "Platforms", "YouTube API quota",
    "Recent events", "Trend opportunities"]) {
    await expect(page.getByRole("heading", { name: new RegExp(`^${h}`) })).toBeVisible();
  }
  await expect(page.locator(".workers .worker")).toHaveCount(st.workers.workers.length);
  const health = await getJson(request, "/api/health");
  const pc = page.locator("section", { has: page.getByRole("heading", { name: "This computer" }) });
  await expect(pc).toContainText(health.ffmpeg ? "Found" : "Missing");
  await expect(pc).toContainText(health.nvenc ? "GPU (NVENC)" : "CPU (x264)");
  await expect(page.getByText("FFmpeg is required.")).toHaveCount(health.ffmpeg ? 0 : 1);
});

test("Open Posts goes to the scheduled posts", async ({ page }) => {
  await page.goto("/#/autopilot/system");
  await page.getByRole("link", { name: "Open Posts" }).click();
  await expect(page).toHaveURL(/#\/posts\/scheduled$/);
});

test("a section opens directly, the old Overview address goes to System, an unknown one to the overview",
  async ({ page }) => {
    const advanced = page.getByRole("navigation", { name: "Advanced" });
    await page.goto("/#/autopilot/jobs");
    await expect(sections(page).getByRole("link", { name: "Advanced" })).toHaveAttribute("aria-current", "page");
    await expect(advanced.getByRole("link", { name: "Jobs" })).toHaveAttribute("aria-current", "page");
    await page.goto("/#/autopilot/overview");
    await expect(page).toHaveURL(/#\/autopilot\/system$/);
    await expect(advanced.getByRole("link", { name: "System" })).toHaveAttribute("aria-current", "page");
    await page.goto("/#/autopilot/no-such-tab");
    await expect(page).toHaveURL(/#\/autopilot$/);
    await expect(sections(page).getByRole("link", { name: "Overview" })).toHaveAttribute("aria-current", "page");
    await expect(advanced).toHaveCount(0);
  });

test("Jobs lists what the queue holds", async ({ page, request }) => {
  await page.goto("/#/autopilot/jobs");
  await expect(async () => {
    const jobs = await getJson<any[]>(request,
      "/api/autopilot/jobs?status=queued,running,waiting,retrying,failed&worker=&limit=150");
    if (jobs.length === 0) await expect(page.getByText("No jobs.")).toBeVisible({ timeout: 1000 });
    else await expect(page.locator(".jobs .job")).toHaveCount(jobs.length, { timeout: 1000 });
  }).toPass();
});

test("Learning shows what the results show and how scores are weighted", async ({ page }) => {
  await page.goto("/#/autopilot/learning");
  await expect(page.getByRole("heading", { name: "What your results show" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "How the scores are weighted" })).toBeVisible();
});
