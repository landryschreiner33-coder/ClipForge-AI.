import { expect, test, Page, APIRequestContext } from "@playwright/test";

async function fixture(page: Page, request: APIRequestContext) {
  const snap = await (await request.get("/api/office/snapshot")).json();
  snap.cursor = 0; snap.needs_you = [];
  snap.run = { ...snap.run, state: "running", label: "Running", actions: ["pause", "stop"] };
  snap.brain.state = "collecting";
  for (const role of snap.roles) Object.assign(role, { state: "idle", task: null, queued: 0, tasks: 0, last: null, error: "" });
  const events: any[] = [];
  await page.route("**/api/office/snapshot", route => route.fulfill({ json: { ...snap, server_time: Date.now() / 1000 } }));
  await page.route("**/api/office/events**", route => {
    const after = Number(new URL(route.request().url()).searchParams.get("after") || 0);
    const rows = events.filter(event => event.id > after);
    return route.fulfill({ json: { events: rows, cursor: rows.length ? rows[rows.length - 1].id : after,
      latest: Math.max(after, ...events.map(event => event.id)), more: false, reset: false, server_time: Date.now() / 1000 } });
  });
  const role = (id: string) => snap.roles.find((row: any) => row.id === id);
  const emit = (type: string, owner: string, overrides: any = {}) => {
    events.push({ id: snap.cursor + 1,
      at: Date.now() / 1000, type, role: owner, job_id: "stage-job", kind: "analyze_source", ref_type: "source",
      ref_id: "source-1", message: "Controlled visual transition", data: { stage: "render", routine: false }, ...overrides });
    snap.cursor = events[events.length - 1].id;
  };
  return { snap, role, emit, events };
}
const robot = (page: Page, id: string) => page.locator(`.robot-hit[data-id="${id}"]`);
const task = () => ({ job_id: "stage-job", kind: "analyze_source", stage: "render", status: "running",
  ref_type: "source", ref_id: "source-1", message: "Rendering an isolated fixture", progress: null,
  updated_at: Date.now() / 1000 });

test("all idle robots have individual lounge seats and the camera can inspect a room", async ({ page, request }) => {
  await fixture(page, request);
  await page.goto("/#/office");
  await page.getByRole("combobox", { name: "Animations", exact: true }).selectOption("reduced");
  await expect(page.locator('.robot-hit[data-room="lounge"][data-posture="rest"]')).toHaveCount(25);
  const places = await page.locator(".robot-hit").evaluateAll(elements => elements.map(el => `${(el as HTMLElement).style.left}|${(el as HTMLElement).style.top}`));
  expect(new Set(places).size, "each robot owns a seat instead of sharing a pile of sprites").toBe(25);
  await page.getByRole("combobox", { name: "Office camera", exact: true }).selectOption("lounge");
  await expect(page.locator(".office-map")).toHaveAttribute("data-camera", "lounge");
  await expect(robot(page, "glyph")).toBeInViewport();
  await page.getByRole("combobox", { name: "Office camera", exact: true }).selectOption("");
  await expect(page.locator(".office-map")).toHaveAttribute("data-camera", "office");
});

test("a robot walks from its seat, sits to work and returns to the lounge when finished", async ({ page, request }) => {
  const feed = await fixture(page, request);
  await page.goto("/#/office");
  await page.getByRole("combobox", { name: "Animations", exact: true }).selectOption("full");
  await expect(robot(page, "splice")).toHaveAttribute("data-posture", "rest");
  Object.assign(feed.role("splice"), { state: "working", task: task() });
  feed.emit("job_started", "splice");
  await expect(robot(page, "splice")).toHaveAttribute("data-pose", "walk", { timeout: 8000 });
  await expect(robot(page, "splice")).toHaveAttribute("data-posture", "desk", { timeout: 20_000 });
  await expect(robot(page, "splice")).toHaveAttribute("data-room", "studio");
  Object.assign(feed.role("splice"), { state: "idle", task: null });
  feed.emit("job_done", "splice");
  await expect(robot(page, "splice")).toHaveAttribute("data-pose", "walk", { timeout: 8000 });
  await expect(robot(page, "splice")).toHaveAttribute("data-posture", "rest", { timeout: 20_000 });
  await expect(robot(page, "splice")).toHaveAttribute("data-room", "lounge");
});

test("an actual same-job stage event passes a document to the next robot before seated work resumes", async ({ page, request }) => {
  const feed = await fixture(page, request);
  Object.assign(feed.role("splice"), { state: "working", task: task() });
  await page.goto("/#/office");
  await page.getByRole("combobox", { name: "Animations", exact: true }).selectOption("full");
  await expect(robot(page, "splice")).toHaveAttribute("data-posture", "desk");
  Object.assign(feed.role("splice"), { state: "idle", task: null });
  Object.assign(feed.role("glyph"), { state: "working", task: { ...task(), stage: "captions" } });
  feed.emit("job_stage", "glyph", { data: { stage: "captions", routine: false } });
  const note = page.locator(".handoff-note");
  await expect(note).toHaveAttribute("data-from", "splice", { timeout: 8000 });
  await expect(note).toHaveAttribute("data-to", "glyph");
  await expect(robot(page, "splice")).toHaveAttribute("data-carrying", "true");
  await expect(note).toHaveAttribute("data-phase", "pass", { timeout: 20_000 });
  await expect(note).toHaveAttribute("data-phase", "received", { timeout: 5000 });
  await expect(robot(page, "glyph")).toHaveAttribute("data-carrying", "true");
  await expect(robot(page, "glyph")).toHaveAttribute("data-posture", "desk", { timeout: 8000 });
  await expect(robot(page, "splice")).toHaveAttribute("data-room", "lounge", { timeout: 20_000 });
});

test("queued, unrelated and old events do not invent handoffs; Pause cancels a live transfer", async ({ page, request }) => {
  const feed = await fixture(page, request);
  Object.assign(feed.role("splice"), { state: "waiting", task: { ...task(), status: "queued" } });
  await page.goto("/#/office");
  await page.getByRole("combobox", { name: "Animations", exact: true }).selectOption("full");
  feed.emit("job_stage", "glyph", { data: { stage: "captions", routine: false } });
  await page.waitForTimeout(1800);
  await expect(page.locator(".handoff-note")).toHaveAttribute("data-phase", "idle");
  feed.emit("job_stage", "splice", { ref_id: "unrelated-source" });
  feed.emit("report", "script", { at: Date.now() / 1000 - 300, data: { worker: "glyph" } });
  await page.waitForTimeout(1800);
  await expect(page.locator(".handoff-note")).toHaveAttribute("data-phase", "idle");
  feed.emit("job_stage", "splice");
  await expect(page.locator(".handoff-note")).toHaveAttribute("data-phase", "approach", { timeout: 8000 });
  feed.snap.run.state = "paused";
  for (const row of feed.snap.roles) row.state = "paused";
  feed.emit("control", "command");
  await expect(page.locator(".handoff-note")).toHaveAttribute("data-phase", "idle", { timeout: 8000 });
  await expect(page.locator('.robot-hit[data-posture="rest"]')).toHaveCount(25);
  await expect(page.locator('.robot-hit[data-pose="carry"]')).toHaveCount(0);
});

test("hidden and paused stages recover the actual sender before the next fresh handoff", async ({ page, request }) => {
  const feed = await fixture(page, request);
  Object.assign(feed.role("splice"), { state: "working", task: task() });
  await page.goto("/#/office");
  await page.getByRole("combobox", { name: "Animations", exact: true }).selectOption("full");
  await expect(robot(page, "splice")).toHaveAttribute("data-posture", "desk");
  await page.evaluate(() => {
    Object.defineProperty(document, "hidden", { configurable: true, get: () => true });
    document.dispatchEvent(new Event("visibilitychange"));
  });
  Object.assign(feed.role("splice"), { state: "idle", task: null });
  Object.assign(feed.role("glyph"), { state: "working", task: { ...task(), stage: "captions" } });
  feed.emit("job_stage", "glyph", { data: { stage: "captions", routine: false } });
  await page.waitForTimeout(2000);
  await expect(page.locator(".handoff-note")).toHaveAttribute("data-phase", "idle");
  await page.evaluate(() => {
    Object.defineProperty(document, "hidden", { configurable: true, get: () => false });
    document.dispatchEvent(new Event("visibilitychange"));
  });
  await expect(robot(page, "glyph")).toHaveAttribute("data-posture", "desk", { timeout: 8000 });
  Object.assign(feed.role("glyph"), { state: "idle", task: null });
  Object.assign(feed.role("splice"), { state: "working", task: task() });
  feed.emit("job_stage", "splice");
  await expect(page.locator(".handoff-note")).toHaveAttribute("data-from", "glyph", { timeout: 8000 });
  await expect(page.locator(".handoff-note")).toHaveAttribute("data-to", "splice");
  feed.snap.run.state = "paused";
  for (const row of feed.snap.roles) row.state = "paused";
  feed.emit("control", "command");
  await expect(page.locator(".handoff-note")).toHaveAttribute("data-phase", "idle", { timeout: 8000 });
  Object.assign(feed.role("splice"), { task: null });
  Object.assign(feed.role("glyph"), { task: { ...task(), stage: "captions" } });
  feed.emit("job_stage", "glyph", { data: { stage: "captions", routine: false } });
  await page.waitForTimeout(2000);
  feed.snap.run.state = "running";
  for (const row of feed.snap.roles) row.state = "idle";
  feed.role("glyph").state = "working";
  feed.emit("control", "command");
  await expect(robot(page, "glyph")).toHaveAttribute("data-posture", "desk", { timeout: 8000 });
  Object.assign(feed.role("glyph"), { state: "idle", task: null });
  Object.assign(feed.role("splice"), { state: "working", task: task() });
  feed.emit("job_stage", "splice");
  await expect(page.locator(".handoff-note")).toHaveAttribute("data-from", "glyph", { timeout: 8000 });
  await expect(page.locator(".handoff-note")).toHaveAttribute("data-to", "splice");
});

test("a feed reset uses the current worker without replaying its fresh-looking historical stages", async ({ page, request }) => {
  const feed = await fixture(page, request);
  Object.assign(feed.role("splice"), { state: "working", task: task() });
  await page.goto("/#/office");
  await page.getByRole("combobox", { name: "Animations", exact: true }).selectOption("full");
  await expect(robot(page, "splice")).toHaveAttribute("data-posture", "desk");
  Object.assign(feed.role("splice"), { state: "idle", task: null });
  Object.assign(feed.role("glyph"), { state: "working", task: { ...task(), stage: "captions" } });
  feed.snap.cursor = 200;
  const history = { id: 185, at: Date.now() / 1000 - 2, type: "job_stage", role: "splice", job_id: "stage-job",
    kind: "analyze_source", ref_type: "source", ref_id: "source-1", message: "Controlled earlier stage",
    data: { stage: "render", routine: false } };
  let reset = true;
  await page.route("**/api/office/events**", route => {
    const after = Number(new URL(route.request().url()).searchParams.get("after") || 0);
    if (reset) { reset = false; return route.fulfill({ json: { events: [], cursor: after, latest: 200,
      more: false, reset: true, server_time: Date.now() / 1000 } }); }
    const rows = [history, ...feed.events].filter(event => event.id > after);
    return route.fulfill({ json: { events: rows, cursor: rows.length ? rows[rows.length - 1].id : after,
      latest: Math.max(200, ...feed.events.map(event => event.id)), more: false, reset: false, server_time: Date.now() / 1000 } });
  });
  await expect(robot(page, "glyph")).toHaveAttribute("data-state", "working", { timeout: 8000 });
  await page.waitForTimeout(1800);
  await expect(page.locator(".handoff-note")).toHaveAttribute("data-phase", "idle");
  Object.assign(feed.role("glyph"), { state: "idle", task: null });
  Object.assign(feed.role("splice"), { state: "working", task: task() });
  feed.emit("job_stage", "splice");
  await expect(page.locator(".handoff-note")).toHaveAttribute("data-from", "glyph", { timeout: 8000 });
  await expect(page.locator(".handoff-note")).toHaveAttribute("data-to", "splice");
});

test("the Brain animates in standby and processing, freezes when paused or Reduced, and has a close camera", async ({ page, request }) => {
  const feed = await fixture(page, request);
  await page.goto("/#/office");
  await page.getByRole("combobox", { name: "Animations", exact: true }).selectOption("full");
  await page.getByRole("combobox", { name: "Office camera", exact: true }).selectOption("brain");
  await expect(page.locator(".brain-core-hit")).toHaveAttribute("data-mode", "standby");
  await expect(page.locator(".brain-core-hit")).toHaveAttribute("href", "#/brain");
  const image = () => page.locator(".office-world canvas").evaluate((canvas: HTMLCanvasElement) => canvas.toDataURL());
  const brainImage = () => page.locator(".office-world canvas").evaluate((canvas: HTMLCanvasElement) => {
    const crop = document.createElement("canvas"); crop.width = crop.height = 132;
    crop.getContext("2d")!.drawImage(canvas, 746, 16, 132, 132, 0, 0, 132, 132);
    return crop.toDataURL();
  });
  const a = await image(); await page.waitForTimeout(850);
  expect(await image(), "the powered Brain has a decorative standby orbit").not.toBe(a);
  feed.snap.brain.state = "evaluating";
  feed.emit("brain_evaluation", "synapse");
  await expect(page.locator(".brain-core-hit")).toHaveAttribute("data-mode", "active", { timeout: 8000 });
  const processing = await brainImage(); await page.waitForTimeout(850);
  expect(await brainImage(), "processing has a live neural animation").not.toBe(processing);
  feed.snap.brain.state = "paused";
  feed.emit("control", "command");
  await expect(page.locator(".brain-core-hit")).toHaveAttribute("data-mode", "paused", { timeout: 8000 });
  await page.waitForTimeout(400); const paused = await brainImage(); await page.waitForTimeout(850);
  expect(await brainImage(), "pausing the Brain freezes its art while the office is still running").toBe(paused);
  feed.snap.brain.state = "collecting";
  feed.emit("control", "command");
  await expect(page.locator(".brain-core-hit")).toHaveAttribute("data-mode", "standby", { timeout: 8000 });
  await page.getByRole("combobox", { name: "Animations", exact: true }).selectOption("reduced");
  await page.waitForTimeout(400); const b = await image(); await page.waitForTimeout(850);
  expect(await image(), "Reduced freezes the Brain and all other art").toBe(b);
});
