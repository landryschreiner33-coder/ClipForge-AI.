import { expect, getJson, test } from "../fixtures";

// Looks at Autopilot without operating it: the AUTOPILOT switch, STOP ALL JOBS, Resume, Learn now, Dismiss,
// Add, Retry and Cancel are never pressed, and each test checks that Autopilot's on/off and paused state
// are the same afterwards.

const onOff = async (request: import("@playwright/test").APIRequestContext) => {
  const st = await getJson(request, "/api/autopilot/status");
  return { enabled: st.enabled, paused: st.paused };
};
let before: { enabled: boolean; paused: boolean };

test.beforeEach(async ({ page, request }) => {
  before = await onOff(request);
  await page.goto("/#/autopilot");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Autopilot");
});

test.afterEach(async ({ request }) => {
  expect(await onOff(request), "Autopilot's on/off or paused state changed during the test").toEqual(before);
});

test("the switch and the stop button reflect Autopilot's real state", async ({ page, request }) => {
  const st = await getJson(request, "/api/autopilot/status");
  const sw = page.getByRole("switch", { name: /^AUTOPILOT (ON|OFF)$/ });
  await expect(sw).toHaveAttribute("aria-checked", String(st.enabled));
  await expect(sw).toHaveText(st.enabled ? "AUTOPILOT ON" : "AUTOPILOT OFF");
  if (st.paused) {
    await expect(page.getByRole("button", { name: "Resume jobs" })).toBeVisible();
    await expect(page.getByText("All jobs are stopped.")).toBeVisible();
  } else {
    await expect(page.getByRole("button", { name: "STOP ALL JOBS" })).toBeVisible();
  }
  if (!st.enabled && !st.paused) await expect(page.getByText("Autopilot is off. Queued work waits")).toBeVisible();
});

test("Overview shows the daily target and every status card", async ({ page, request }) => {
  const st = await getJson(request, "/api/autopilot/status");
  await expect(page.locator(".target-big")).toContainText(`/ ${st.target.daily}`);
  await expect(page.locator(".target-big")).toContainText("DAILY TARGET");
  for (const h of ["Workers", "GPU", "Platforms", "YouTube API quota", "Rights of known sources", "Recent activity", "Trend opportunities"]) {
    await expect(page.getByRole("heading", { name: new RegExp(`^${h}`) })).toBeVisible();
  }
  await expect(page.locator(".workers .worker")).toHaveCount(st.workers.workers.length);
});

test("Open Publish Center goes to the queue", async ({ page }) => {
  await page.getByRole("link", { name: "Open Publish Center" }).click();
  await expect(page).toHaveURL(/#\/publish-center$/);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Publish Center");
});

const TABS = [
  { label: "Sources & rights", slug: "sources", headings: ["Where sources come from", "Rights rules", "Sources"] },
  { label: "Jobs", slug: "jobs", headings: ["Jobs"] },
  { label: "Learning", slug: "learning", headings: ["What your results show", "How the scores are weighted"] },
  { label: "Overview", slug: "overview", headings: ["Workers"] },
];

test("the tabs switch and keep their address", async ({ page }) => {
  const tabs = page.locator(".page > .segmented");
  for (const t of TABS) {
    await tabs.getByRole("button", { name: t.label, exact: true }).click();
    await expect(page).toHaveURL(new RegExp(`#/autopilot/${t.slug}$`));
    await expect(tabs.locator("button.on")).toHaveText(t.label);
    for (const h of t.headings) await expect(page.getByRole("heading", { name: new RegExp(`^${h}`) }).first()).toBeVisible();
  }
});

test("a tab can be opened directly, and an unknown one shows Overview", async ({ page }) => {
  const tabs = page.locator(".page > .segmented");
  await page.goto("/#/autopilot/jobs");
  await expect(tabs.locator("button.on")).toHaveText("Jobs");
  await page.goto("/#/autopilot/no-such-tab");
  await expect(tabs.locator("button.on")).toHaveText("Overview");
});

test("Jobs lists what the queue holds", async ({ page, request }) => {
  await page.goto("/#/autopilot/jobs");
  await expect(async () => {
    const jobs = await getJson<any[]>(request, "/api/autopilot/jobs?status=queued,running,waiting,retrying,failed&worker=&limit=150");
    if (jobs.length === 0) await expect(page.getByText("No jobs.")).toBeVisible({ timeout: 1000 });
    else await expect(page.locator(".jobs .job")).toHaveCount(jobs.length, { timeout: 1000 });
  }).toPass();
});
