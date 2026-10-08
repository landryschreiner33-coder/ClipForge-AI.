import { expect, test, Page, APIRequestContext } from "@playwright/test";
import { mkdir } from "node:fs/promises";
import path from "node:path";

// Rendering contracts of the Office map (docs/OFFICE.md) with controlled answers from /api/office: these browser
// contexts never change application data, and they never present a made-up state as a real worker. The real
// pipeline is in zero-touch-loop.spec.ts.

type Feed = { snap: any; events: any[]; down: boolean };

async function controlled(page: Page, request: APIRequestContext): Promise<Feed> {
  const snap = await (await request.get("/api/office/snapshot")).json();
  snap.run = { ...snap.run, state: "running", label: "Running", actions: ["pause", "stop"], publishing_paused: false };
  snap.needs_you = [];
  snap.cursor = 0;  // the controlled events below start at 1
  for (const r of snap.roles) {
    Object.assign(r, { state: "idle", task: null, tasks: 0, queued: 0, error: "", last: null });
  }
  const feed: Feed = { snap, events: [], down: false };
  await page.route("**/api/office/snapshot", (route) => (feed.down ? route.abort()
    : route.fulfill({ json: { ...feed.snap, server_time: Date.now() / 1000 } })));
  await page.route("**/api/office/events**", (route) => {
    if (feed.down) return route.abort();
    const after = Number(new URL(route.request().url()).searchParams.get("after") || 0);
    const rows = feed.events.filter((e) => e.id > after);
    return route.fulfill({ json: { events: rows, cursor: rows.length ? rows[rows.length - 1].id : after,
      latest: Math.max(after, ...feed.events.map((e) => e.id)), more: false, reset: false,
      server_time: Date.now() / 1000 } });
  });
  return feed;
}

const role = (feed: Feed, id: string) => feed.snap.roles.find((r: any) => r.id === id);
const robot = (page: Page, id: string) => page.locator(`.robot-hit[data-id="${id}"]`);
const task = (message: string, progress: number | null = null) => ({ job_id: `job-${message}`, kind: "analyze_source",
  stage: "", status: "running", message, progress, ref_type: "source", ref_id: "s1", updated_at: Date.now() / 1000 });

test("robots stand where their real work is, and follow it when it changes", async ({ page, request }) => {
  const feed = await controlled(page, request);
  Object.assign(role(feed, "radar"), { state: "working", task: task("Reading search results", 0.37) });
  Object.assign(role(feed, "splice"), { state: "working", task: task("Rendering clip 2") });
  Object.assign(role(feed, "check"), { state: "error", error: "ffmpeg is missing" });
  await page.goto("/#/");
  await page.getByLabel(/Reduce animations/).check();
  await expect(robot(page, "radar")).toHaveAttribute("data-room", "discover");
  await expect(robot(page, "radar")).toHaveAttribute("aria-label", "RADAR, Scout, working: Reading search results");
  await expect(robot(page, "splice")).toHaveAttribute("data-room", "studio");
  await expect(robot(page, "check")).toHaveAttribute("data-room", "system");
  await expect(robot(page, "check")).toHaveAttribute("data-state", "error");
  // a controlled rendering of a failure, for design/robot-office/screenshots (README there says so)
  const shots = path.resolve(process.cwd(), "..", "design", "robot-office", "screenshots");
  await mkdir(shots, { recursive: true });
  await page.screenshot({ path: path.join(shots, "error-controlled.png") });
  // a resting worker is in the lounge (or only counted there)
  const resting = robot(page, "glyph");
  if (await resting.isVisible()) await expect(resting).toHaveAttribute("data-room", "lounge");
  // measured progress is shown as measured; a step without a measurement shows no percentage
  await robot(page, "radar").click();
  const panel = page.getByRole("complementary", { name: "Details" });
  await expect(panel.getByRole("heading", { level: 2 })).toHaveText("RADAR");
  await expect(panel.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "37");
  // the job finished: the next snapshot sends RADAR to rest
  Object.assign(role(feed, "radar"), { state: "idle", task: null, last: { summary: "Found 3 videos", state: "done",
    at: Date.now() / 1000 } });
  await expect(robot(page, "radar")).toHaveAttribute("data-room", "lounge", { timeout: 15_000 });
  await expect(robot(page, "radar")).toHaveAttribute("data-state", "idle");
});

test("a real report is carried to the manager; a decision gets COMMAND's reaction", async ({ page, request }) => {
  const feed = await controlled(page, request);
  Object.assign(role(feed, "splice"), { state: "working", task: task("Rendering clip 2") });
  await page.goto("/#/");
  await page.getByLabel(/Reduce animations/).uncheck();
  await expect(robot(page, "splice")).toHaveAttribute("data-room", "studio");
  const now = Date.now() / 1000;
  feed.events.push({ id: 1, at: now, type: "report", role: "frame", job_id: "job-1", kind: "analyze_source",
    ref_type: "clip", ref_id: "c1", message: "Clip 2 rendered", data: { worker: "splice", state: "done" } });
  await expect(robot(page, "splice")).toHaveAttribute("data-pose", "carry", { timeout: 8000 });
  await expect(robot(page, "frame")).toHaveAttribute("data-pose", "review", { timeout: 15_000 });
  feed.events.push({ id: 2, at: Date.now() / 1000, type: "decision", role: "command", job_id: "job-2",
    kind: "quality_check", ref_type: "clip", ref_id: "c1", message: "Passed the final check",
    data: { point: "qc", action: "approved" } });
  await expect(robot(page, "command")).toHaveAttribute("data-pose", "approved", { timeout: 8000 });
  // history is listed, never walked: an old report moves nobody
  feed.events.push({ id: 3, at: Date.now() / 1000 - 600, type: "report", role: "tracker", job_id: "job-3",
    kind: "source_scout", ref_type: "source", ref_id: "s1", message: "Old report", data: { worker: "archive" } });
  await page.waitForTimeout(3000);
  await expect(robot(page, "tracker")).not.toHaveAttribute("data-pose", "review");
});

test("paused and stopped states rest the robots; a lost connection is said and marked", async ({ page, request }) => {
  const feed = await controlled(page, request);
  feed.snap.run = { ...feed.snap.run, state: "paused", label: "Paused", actions: ["resume", "stop"] };
  for (const r of feed.snap.roles) r.state = "paused";
  await page.goto("/#/");
  const bar = page.getByRole("region", { name: "Autopilot controls" });
  await expect(bar.locator("#office-run-state")).toHaveText("Paused");
  await expect(bar.getByRole("button", { name: "Resume", exact: true })).toBeVisible();
  await expect(bar.getByRole("button", { name: "Pause", exact: true })).toHaveCount(0);
  await expect(page.locator('.robot-hit[data-state="working"]')).toHaveCount(0);
  await expect(robot(page, "command")).toHaveAttribute("data-state", "paused");
  feed.down = true;
  await expect(page.getByText("The office is not updating", { exact: true })).toBeVisible({ timeout: 15_000 });
  await expect(page.locator(".office-map")).toHaveClass(/stale/);
  feed.down = false;
  await expect(page.getByText("The office is not updating", { exact: true })).toHaveCount(0, { timeout: 15_000 });
});

test("Reduce animations stills the map; the office fits common laptop screens", async ({ page, request }) => {
  const feed = await controlled(page, request);
  Object.assign(role(feed, "splice"), { state: "working", task: task("Rendering clip 2") });
  await page.setViewportSize({ width: 1366, height: 768 });
  await page.goto("/#/");
  const canvas = page.locator(".office-world canvas");
  await expect(robot(page, "splice")).toHaveAttribute("data-room", "studio");
  const frame = () => canvas.evaluate((c: HTMLCanvasElement) => c.toDataURL());
  const a = await frame();
  await page.waitForTimeout(700);
  expect(await frame(), "working robots move").not.toBe(a);
  await page.getByLabel(/Reduce animations/).check();
  await page.waitForTimeout(800);
  const b = await frame();
  await page.waitForTimeout(1200);
  expect(await frame(), "nothing moves with Reduce animations").toBe(b);
  await page.getByLabel(/Reduce animations/).uncheck();
  for (const [w, h] of [[1366, 768], [1280, 720]]) {
    await page.setViewportSize({ width: w, height: h });
    await expect(page.getByRole("region", { name: "Autopilot controls" })).toBeInViewport();
    await expect(page.getByRole("complementary", { name: "Details" })).toBeInViewport();
    const world = await page.locator(".office-world").boundingBox();
    expect(world!.width, `the whole office at ${w}×${h} without shrinking the pixels`).toBeGreaterThanOrEqual(704);
    expect(world!.y + world!.height).toBeLessThanOrEqual(h);
  }
  for (const [w, h] of [[683, 384], [390, 844]]) {
    await page.setViewportSize({ width: w, height: h });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  }
});
