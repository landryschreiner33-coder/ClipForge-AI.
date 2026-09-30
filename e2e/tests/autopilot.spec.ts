import { expect, getJson, test } from "../fixtures";

// Looks at Autopilot without operating it: START / PAUSE AUTOPILOT, CONNECT, STOP ALL JOBS, Resume,
// Learn now, YES/NO, Dismiss, Add, Retry and Cancel are never pressed (Add content manually is opened and canceled),
// and each test checks that Autopilot's on/off and paused state are the same afterwards.

const onOff = async (request: import("@playwright/test").APIRequestContext) => {
  const st = await getJson(request, "/api/autopilot/status");
  return { enabled: st.enabled, paused: st.paused };
};
/** The first-run screen shows until Autopilot was started once. */
const firstRun = (st: any) => !st.enabled && !st.home.setup.started;
let before: { enabled: boolean; paused: boolean };

test.beforeEach(async ({ page, request }) => {
  before = await onOff(request);
  await page.goto("/#/autopilot");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Autopilot");
});

test.afterEach(async ({ request }) => {
  expect(await onOff(request), "Autopilot's on/off or paused state changed during the test").toEqual(before);
});

test("START / PAUSE (or the first-run steps) and the stop button reflect Autopilot's real state", async ({ page, request }) => {
  const st = await getJson(request, "/api/autopilot/status");
  if (firstRun(st)) {
    await expect(page.getByText("CLIPFOUNDRY AUTOPILOT")).toBeVisible();
    await expect(page.getByRole("button", { name: "START AUTOPILOT" })).toBeVisible();
    await expect(page.locator(".ap-state")).toHaveCount(0);
  } else if (!st.paused) {
    await expect(page.locator(".ap-state")).toHaveText(st.enabled ? "AUTOPILOT ON" : "AUTOPILOT PAUSED");
    const toggle = page.getByRole("button", { name: st.enabled ? "PAUSE AUTOPILOT" : "START AUTOPILOT" });
    await expect(toggle).toHaveAttribute("aria-pressed", String(st.enabled));
  }
  if (st.paused) {
    await expect(page.getByRole("button", { name: "Resume jobs" })).toBeVisible();
    await expect(page.getByText("All jobs are stopped.")).toBeVisible();
  } else {
    // STOP ALL JOBS is a technical control: it lives under Advanced, not on the simple page
    await expect(page.getByRole("button", { name: "STOP ALL JOBS" })).toHaveCount(0);
    await page.goto("/#/autopilot/system");
    await expect(page.getByRole("button", { name: "STOP ALL JOBS" })).toBeVisible();
  }
  if (!st.enabled && !st.paused && !firstRun(st)) await expect(page.getByText("Autopilot is paused.")).toBeVisible();
});

test("the main page is simple: what it is doing, what it found, what needs you", async ({ page, request }) => {
  const st = await getJson(request, "/api/autopilot/status");
  if (firstRun(st)) {
    for (const step of ["Connect YouTube", "Connect TikTok", "Choose topics", "Add your videos", "Start Autopilot"]) {
      await expect(page.locator(".ob-body b", { hasText: step })).toBeVisible();
    }
  } else {
    for (const k of ["Today", "Currently", "Next post"]) await expect(page.locator(".home-k", { hasText: k })).toBeVisible();
    await expect(page.locator(".home-today")).toContainText(`/ ${st.target.daily}`);
    await expect(page.locator(".home-now").first()).not.toBeEmpty();
    for (const h of [/^Needs you/, /^Your videos$/, /^Top opportunities$/, /^Upcoming posts$/]) await expect(page.getByRole("heading", { name: h })).toBeVisible();
    // Where to put videos, shown (OPEN MY VIDEOS FOLDER is not pressed: it would create the folder)
    await expect(page.locator(".my-videos-path")).toContainText(st.home.my_videos.path);
    await expect(async () => {
      const home = (await getJson(request, "/api/autopilot/status")).home;
      await expect(page.locator(".needs-you .action")).toHaveCount(home.needs_you.length, { timeout: 1000 });
      if (!home.opportunities.length) await expect(page.getByText(home.empty)).toBeVisible({ timeout: 1000 });
    }).toPass();
  }
  // Nothing technical on the main page: that lives under Advanced
  for (const h of ["Workers", "GPU", "YouTube API quota", "Rights of known sources", "Where sources come from", "Rights rules"]) {
    await expect(page.getByRole("heading", { name: h, exact: true })).toHaveCount(0);
  }
  await expect(page.getByText("No sources configured")).toHaveCount(0);
  await page.getByRole("link", { name: "Advanced", exact: true }).click();
  await expect(page).toHaveURL(/#\/autopilot\/system$/);
  await expect(page.getByRole("heading", { name: /^Workers/ })).toBeVisible();
});

test("Add content manually offers every way to add content, and is optional", async ({ page }) => {
  await page.getByRole("button", { name: "+ Add content manually" }).click();
  const dialog = page.locator(".modal");
  await expect(dialog.getByRole("heading", { name: "Add content manually" })).toBeVisible();
  for (const way of ["Paste a link", "A video on this computer", "Watch a folder", "Upload a video"]) {
    await expect(dialog.getByRole("button", { name: way, exact: true })).toBeVisible();
  }
  await expect(dialog.getByText("Can ClipFoundry use it?")).toBeVisible();
  await expect(dialog.getByRole("radio")).toHaveCount(3);
  await dialog.getByRole("button", { name: "Cancel" }).click();
  await expect(dialog).toHaveCount(0);
});

test("System details shows the daily target and every status card", async ({ page, request }) => {
  await page.goto("/#/autopilot/system");
  const st = await getJson(request, "/api/autopilot/status");
  await expect(page.locator(".target-big")).toContainText(`/ ${st.target.daily}`);
  await expect(page.locator(".target-big")).toContainText("DAILY TARGET");
  for (const h of ["Workers", "GPU", "Platforms", "YouTube API quota", "Rights of known sources", "Recent activity", "Trend opportunities"]) {
    await expect(page.getByRole("heading", { name: new RegExp(`^${h}`) })).toBeVisible();
  }
  await expect(page.locator(".workers .worker")).toHaveCount(st.workers.workers.length);
});

test("Open Publish Center goes to the queue", async ({ page }) => {
  await page.goto("/#/autopilot/system");
  await page.getByRole("link", { name: "Open Publish Center" }).click();
  await expect(page).toHaveURL(/#\/publish-center$/);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Publish Center");
});

const TABS = [
  { label: "Sources & rights", slug: "sources", headings: ["Where sources come from", "Rights rules", "Sources"] },
  { label: "Jobs", slug: "jobs", headings: ["Jobs"] },
  { label: "Learning", slug: "learning", headings: ["What your results show", "How the scores are weighted"] },
  { label: "System details", slug: "system", headings: ["Workers"] },
];

test("the Advanced tabs switch and keep their address", async ({ page }) => {
  await page.goto("/#/autopilot/system");
  const tabs = page.locator(".page > .segmented");
  for (const t of TABS) {
    await tabs.getByRole("button", { name: t.label, exact: true }).click();
    await expect(page).toHaveURL(new RegExp(`#/autopilot/${t.slug}$`));
    await expect(tabs.locator("button.on")).toHaveText(t.label);
    for (const h of t.headings) await expect(page.getByRole("heading", { name: new RegExp(`^${h}`) }).first()).toBeVisible();
  }
  await page.getByRole("link", { name: "Back to Autopilot" }).click();
  await expect(page).toHaveURL(/#\/autopilot$/);
  await expect(page.locator(".page > .segmented")).toHaveCount(0);
});

test("a tab can be opened directly, the old Overview address still works, and an unknown one shows the main page", async ({ page }) => {
  const tabs = page.locator(".page > .segmented");
  await page.goto("/#/autopilot/jobs");
  await expect(tabs.locator("button.on")).toHaveText("Jobs");
  await page.goto("/#/autopilot/overview");
  await expect(tabs.locator("button.on")).toHaveText("System details");
  await page.goto("/#/autopilot/no-such-tab");
  await expect(page.locator(".onboard, .ap-home")).toBeVisible();
  await expect(tabs).toHaveCount(0);
});

test("Jobs lists what the queue holds", async ({ page, request }) => {
  await page.goto("/#/autopilot/jobs");
  await expect(async () => {
    const jobs = await getJson<any[]>(request, "/api/autopilot/jobs?status=queued,running,waiting,retrying,failed&worker=&limit=150");
    if (jobs.length === 0) await expect(page.getByText("No jobs.")).toBeVisible({ timeout: 1000 });
    else await expect(page.locator(".jobs .job")).toHaveCount(jobs.length, { timeout: 1000 });
  }).toPass();
});
