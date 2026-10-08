import { expect, test, type APIRequestContext, type Page } from "@playwright/test";
import { mkdir } from "node:fs/promises";
import path from "node:path";

const H = { "X-ClipFoundry": "1" };

async function get(request: APIRequestContext, url: string): Promise<any> {
  const result = await request.get(url);
  expect(result.ok(), `${url}: ${await result.text()}`).toBeTruthy();
  return result.json();
}

const office = (page: Page, name: string) => page.locator(".office-map")
  .getByRole("button", { name: new RegExp(`^${name}, `) });

async function post(request: APIRequestContext, url: string, data?: any): Promise<any> {
  const result = await request.post(url, { headers: H, data });
  expect(result.ok(), `${url}: ${await result.text()}`).toBeTruthy();
  return result.json();
}

test("one Start continues through real clips, checked uploads, results and a second discovery", async ({
  page, request,
}) => {
  const screenshots = path.resolve(process.cwd(), "..", "design", "retro-studio", "screenshots");
  await mkdir(screenshots, { recursive: true });
  // Only this test server exposes /sandbox. Every media and account belongs to its throwaway data folder.
  const fixture = await get(request, "/sandbox/state");
  expect(fixture.uploads).toEqual([]);
  await page.goto("/#/setup/mode");
  await page.getByRole("radio", { name: /Let Autopilot do it/ }).check();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await expect(page).toHaveURL(/#\/setup\/posting$/);
  const popup = page.waitForEvent("popup");
  await page.getByRole("button", { name: "Connect YouTube" }).click();
  const tab = await popup;
  await expect(tab.getByText("YouTube connected")).toBeVisible();
  await tab.close();
  await expect(page.getByText(/^Connected: /)).toHaveCount(1);

  // Who may see the uploads: the default "Keep on this PC" plans no posts and public is never allowed
  // (docs/AUDIENCE.md), so the user chooses a selected audience for YouTube (private + invited viewers).
  const audience = await post(request, "/api/audience", { youtube_intent: "SELECTED_AUDIENCE" });
  expect(audience.destinations.youtube.intent).toBe("SELECTED_AUDIENCE");
  // A one-time account permission is required even in the fake account. No post is approved by this test.
  await post(request, "/api/autopilot/auto-publish", { platform: "youtube", visibility: "private",
    made_for_kids: false, daily_limit: 4, start_hour: 0, end_hour: 24, agreed: true });
  await page.getByRole("button", { name: "Start Autopilot" }).click();
  // Finish the setup handler's own navigation (to the Office) before choosing the main control page.
  await expect(page).toHaveURL(/#\/$/);
  await expect(page.getByRole("heading", { name: "Office", exact: true, level: 1 })).toBeVisible();
  await expect(page.locator(".control-bar")).toContainText("Running");
  await page.goto("/#/missions");
  await expect(page.locator("#ap-state")).toContainText("Autopilot is on");

  // The unreadable original is selected first. It fails normally and the next discovered video still finishes.
  await expect.poll(async () => (await get(request, "/sandbox/state")).sources
    .find((s: any) => s.external_id === "loopbroken1")?.status, { timeout: 120_000 }).toBe("failed");
  await expect.poll(async () => (await get(request, "/sandbox/state")).sources
    .find((s: any) => s.external_id === "loopfirst01")?.status, { timeout: 120_000 }).toMatch(/ingesting|analyzing/);
  // The Office shows the robots doing that real work
  await page.goto("/#/");
  await expect(page.locator(".office-map button.bot.state-working").first()).toBeVisible();
  await page.screenshot({ path: path.join(screenshots, "working.png"), fullPage: true });
  await page.goto("/#/missions");
  await expect.poll(async () => (await get(request, "/sandbox/state")).publications
    .filter((p: any) => p.status === "done").length,
    { timeout: 240_000 }).toBeGreaterThanOrEqual(1);
  let state = await get(request, "/sandbox/state");
  const first = state.sources.find((s: any) => s.external_id === "loopfirst01");
  const publication = state.publications.find((p: any) => p.status === "done");
  const postItem = state.posts.find((p: any) => p.publication_id === publication.id);
  const clip = state.clips.find((c: any) => c.id === publication.clip_id);
  const report = state.reports.find((r: any) => r.clip_id === clip.id && r.status === "passed");
  expect(first.clips_selected).toBeGreaterThan(0);
  expect(state.transcriptions).toContain(first.id);
  expect(clip.render_info.artifact.sha256).toBe(report.artifact_sha256);
  expect(postItem.approval.by).toBe("automatic");
  expect(postItem.approval.video_sha256).toBe(report.artifact_sha256);
  const received = state.uploads.find((u: any) => u.id === publication.remote_id);
  expect(received.sha256).toBe(report.artifact_sha256);
  // Private for the invited viewers, and never public later: no publishAt
  expect(received.status.privacyStatus).toBe("private");
  expect(received.status.publishAt).toBeUndefined();
  for (const kind of ["trend_scan", "source_scout", "hunt_source", "analyze_source", "package_clip",
    "quality_check", "schedule_tick", "publish"]) {
    expect(state.jobs.some((j: any) => j.kind === kind && j.status === "completed"), kind).toBe(true);
  }

  // Add through the ordinary page while the loop is still on. A link with unknown publishing rights remains a
  // usable local clip; it never becomes an automatic post just because the user pasted it.
  await page.getByLabel("Paste a video or stream link", { exact: true }).fill(fixture.manual_url);
  await page.getByRole("button", { name: "ADD", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Added by you" })).toBeVisible();
  await expect.poll(async () => (await get(request, "/api/autopilot/links"))
    .find((i: any) => i.url.includes("manualvideo1"))?.project_id, { timeout: 90_000 }).toBeTruthy();
  const added = (await get(request, "/api/autopilot/links"))
    .find((i: any) => i.url.includes("manualvideo1"));
  await page.getByLabel("Paste a video or stream link", { exact: true }).fill("https://youtu.be/manualvideo1?t=12");
  await page.getByRole("button", { name: "ADD", exact: true }).click();
  await expect(page.getByText("Already added", { exact: false }).first()).toBeVisible();
  expect((await get(request, "/api/autopilot/links")).filter((i: any) => i.id === added.id)).toHaveLength(1);
  await expect.poll(async () => (await get(request, "/sandbox/state")).clips
    .filter((c: any) => c.project_id === added.project_id && c.status === "ready").length,
  { timeout: 240_000 }).toBeGreaterThan(0);
  state = await get(request, "/sandbox/state");
  expect(state.jobs.find((j: any) => j.kind === "identify_link" && j.ref_id === added.id).priority).toBe(80);
  expect(state.jobs.find((j: any) => j.kind === "hunt_source" && j.ref_id === added.id).priority).toBe(80);
  const localClips = state.clips.filter((c: any) => c.project_id === added.project_id);
  // A finished render still has asynchronous packaging and quality work ahead of it.
  await expect.poll(async () => (await get(request, "/sandbox/state")).reports
    .some((r: any) => localClips.some((c: any) => c.id === r.clip_id) && r.status === "passed"),
  { timeout: 90_000 }).toBe(true);
  state = await get(request, "/sandbox/state");
  expect(state.posts.filter((p: any) => localClips.some((c: any) => c.id === p.clip_id))).toEqual([]);

  // Replace the worker host over the same SQLite queue. Nothing presses Start again and finished uploads stay
  // finished. The fake upstream then publishes a new opportunity; ordinary discovery runs the second loop.
  const restart = await post(request, "/sandbox/restart-workers");
  expect(restart.enabled).toBe(true);
  expect((await get(request, "/api/autopilot/links")).find((i: any) => i.id === added.id).project_id)
    .toBe(added.project_id);
  await post(request, "/sandbox/next-video");
  await expect.poll(async () => (await get(request, "/sandbox/state")).publications
    .filter((p: any) => p.status === "done").length,
    { timeout: 240_000 }).toBe(2);
  state = await get(request, "/sandbox/state");
  expect(state.sources.find((s: any) => s.external_id === "loopagain01").clips_selected).toBeGreaterThan(0);
  expect(new Set(state.publications.filter((p: any) => p.status === "done").map((p: any) => p.remote_id)).size).toBe(2);

  // Simulate waiting a day for results. Stats still come from the platform, then the real learner executes.
  // Invited viewers are a test audience: their numbers feed the Brain's test cohort, never the public learner.
  await post(request, "/sandbox/age-results");
  await expect.poll(async () => (await get(request, "/sandbox/state")).performance.length,
    { timeout: 60_000 }).toBe(2);
  await expect.poll(async () => (await get(request, "/api/brain")).cohorts
    .some((c: any) => c.cohort === "selected:youtube:invited:v1"), { timeout: 60_000 }).toBe(true);
  await expect.poll(async () => (await get(request, "/sandbox/state")).learning?.samples,
    { timeout: 60_000 }).toBe(0);
  state = await get(request, "/sandbox/state");
  expect(state.performance.every((p: any) => p.views === 1234 && p.avg_view_percentage === null)).toBe(true);
  expect(state.learning.message).toContain("0 of 10 posts with real numbers");
  expect(state.learning.weights).toEqual({});
  const status = await get(request, "/api/autopilot/status");
  expect(status.enabled).toBe(true);
  expect(status.home.needs_you.filter((i: any) => ["rights", "failed"].includes(i.type))).toEqual([]);
  await page.reload();
  await expect(page.locator("#ap-state")).toContainText("Autopilot is on");

  // An upcoming link waits durably without blocking the system. Restart over that same pending item, then let
  // the fake platform go live. Actual capture/segment/transcript/render/post-live handlers finish its recording.
  const streamFixture = await post(request, "/sandbox/upcoming-stream");
  await page.getByLabel("Paste a video or stream link", { exact: true }).fill(streamFixture.url);
  await page.getByRole("button", { name: "ADD", exact: true }).click();
  await expect.poll(async () => (await get(request, "/api/autopilot/links"))
    .find((i: any) => i.url.includes("loopstream1"))?.status, { timeout: 30_000 }).toBe("waiting_stream");
  await expect(page.locator(".ap-link-row", { hasText: "A live conversation about diets" }))
    .toContainText("Waiting for stream");
  // In the Office, the robot researching links waits for the stream with that real job, and says why
  await page.goto("/#/");
  await expect(office(page, "ARCHIVE")).toHaveAccessibleName(/: Waiting: Researching a link$/);
  await office(page, "ARCHIVE").click();
  await expect(page.getByRole("complementary", { name: "Details" }).getByRole("region", { name: "Current task" }))
    .toContainText("Waiting for the stream to start");
  await page.screenshot({ path: path.join(screenshots, "waiting.png"), fullPage: true });
  const waitingStream = (await get(request, "/api/autopilot/links"))
    .find((i: any) => i.url.includes("loopstream1"));
  await post(request, "/sandbox/restart-workers");
  expect((await get(request, "/api/autopilot/links")).find((i: any) => i.id === waitingStream.id).status)
    .toBe("waiting_stream");
  await page.reload();
  await expect(page.locator(".control-bar")).toContainText("Running");
  await expect(office(page, "ARCHIVE")).toHaveAccessibleName(/: Waiting: Researching a link$/);
  await page.screenshot({ path: path.join(screenshots, "restarted.png"), fullPage: true });
  await page.goto("/#/missions");
  await expect(page.locator("#ap-state")).toContainText("Autopilot is on");
  await post(request, "/sandbox/start-stream");
  await expect.poll(async () => (await get(request, "/sandbox/state")).sources
    .find((s: any) => s.id === waitingStream.id)?.live_status, { timeout: 150_000 }).toBe("ended");
  await expect.poll(async () => (await get(request, "/sandbox/state")).jobs
    .some((j: any) => j.kind === "post_live" && j.ref_id === waitingStream.id && j.status === "completed"),
  { timeout: 180_000 }).toBe(true);
  state = await get(request, "/sandbox/state");
  const endedStream = state.sources.find((s: any) => s.id === waitingStream.id);
  const streamClips = state.clips.filter((c: any) => c.project_id === endedStream.project_id && c.status === "ready");
  expect(streamClips.length).toBeGreaterThan(0);
  await expect.poll(async () => (await get(request, "/sandbox/state")).reports
    .filter((r: any) => streamClips.some((c: any) => c.id === r.clip_id) && r.status === "passed").length,
  { timeout: 60_000 }).toBeGreaterThan(0);
  expect((await get(request, "/sandbox/state")).uploads).toHaveLength(2);

  // Deliberately pausing is the sole final stop. It is a real saved setting, and the office reflects it.
  await page.getByRole("button", { name: "Pause Autopilot", exact: true }).click();
  await expect.poll(async () => (await get(request, "/api/autopilot/status")).enabled).toBe(false);
  await page.goto("/#/");
  await expect(page.locator(".control-bar")).toContainText("Paused");
  await expect(page.locator('.office-map section.room[data-room="lounge"] button.bot').first()).toBeVisible();
  await page.screenshot({ path: path.join(screenshots, "paused.png"), fullPage: true });
});
