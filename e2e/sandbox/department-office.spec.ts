import { expect, test, Page, APIRequestContext } from "@playwright/test";

// Only read-only browser responses are controlled; no fixture can start work or approve a publication.
async function fixture(page: Page, request: APIRequestContext) {
  const snap = await (await request.get("/api/office/snapshot")).json();
  snap.cursor = 0; snap.needs_you = [];
  snap.run = { ...snap.run, state: "running", label: "Running", actions: ["pause", "stop"] };
  snap.brain.state = "collecting";
  for (const row of snap.roles) Object.assign(row, {
    state: "idle", task: null, queued: 0, tasks: 0, last: null, error: "",
  });
  const events: any[] = [], writes: string[] = [];
  page.on("request", request => {
    const url = new URL(request.url());
    if (url.pathname.startsWith("/api/") && !["GET", "HEAD"].includes(request.method()))
      writes.push(`${request.method()} ${url.pathname}`);
  });
  await page.route("**/api/office/snapshot", route => route.fulfill({
    json: { ...snap, server_time: Date.now() / 1000 },
  }));
  await page.route("**/api/office/events**", route => {
    const after = Number(new URL(route.request().url()).searchParams.get("after") || 0);
    const rows = events.filter(event => event.id > after);
    return route.fulfill({ json: { events: rows, cursor: rows.length ? rows[rows.length - 1].id : after,
      latest: Math.max(after, ...events.map(event => event.id)), more: false, reset: false,
      server_time: Date.now() / 1000 } });
  });
  return { snap, writes, role: (id: string) => snap.roles.find((row: any) => row.id === id),
    emit: (type = "control", owner = "command", data = {}) => {
      const id = snap.cursor + 1;
      events.push({ id, at: Date.now() / 1000, type, role: owner,
        job_id: "department-job", kind: "analyze_source", ref_type: "source", ref_id: "department-source",
        message: "Controlled department transition", data: { stage: "render", routine: false, ...data } });
      snap.cursor = id;
    },
  };
}

const robot = (page: Page, id: string) => page.locator(`.robot-hit[data-id="${id}"]`);
const animations = (page: Page) => page.getByRole("combobox", { name: "Animations", exact: true });
const task = (id = "department-job", stage = "render") => ({ job_id: id, kind: "analyze_source", stage,
  status: "running", ref_type: "source", ref_id: "department-source", message: "Controlled department task",
  progress: null, updated_at: Date.now() / 1000 });
const departments = [
  { room: "discover", manager: "tracker", worker: "radar", peers: ["tracker", "radar", "archive"] },
  { room: "analyze", manager: "vector", worker: "pulse", peers: ["pulse", "gavel", "boost", "vector"] },
  { room: "studio", manager: "frame", worker: "splice", peers: ["frame", "spark", "story", "splice"] },
  { room: "caption", manager: "script", worker: "glyph", peers: ["glyph", "quill", "script"] },
  { room: "schedule", manager: "clock", worker: "clock", peers: ["clock"] },
  { room: "dock", manager: "harbor", worker: "dock", peers: ["lock", "dock", "harbor"] },
  { room: "system", manager: "switch", worker: "patch", peers: ["switch", "check", "patch"] },
  { room: "brain", manager: "curator", worker: "synapse", peers: ["metric", "synapse", "curator"] },
];

test("every department gathers its whole cast, with honest support and manager states", async ({ page, request }) => {
  const feed = await fixture(page, request);
  for (const dept of departments) {
    Object.assign(feed.role(dept.worker), { state: "working", task: task(`job-${dept.worker}`) });
    if (dept.worker !== dept.manager) feed.role(dept.manager).state = "working"; // actual API oversight convention
  }
  await page.goto("/#/office");
  await animations(page).selectOption("reduced");
  for (const dept of departments) {
    for (const id of dept.peers) {
      await expect(robot(page, id)).toHaveAttribute("data-room", dept.room);
      await expect(robot(page, id)).toHaveAttribute("data-break-activity", "");
    }
    await expect(robot(page, dept.worker)).toHaveAttribute("data-posture", "desk");
    await expect(robot(page, dept.worker)).toHaveAttribute("data-duty", "work");
    if (dept.worker !== dept.manager) {
      await expect(robot(page, dept.manager)).toHaveAttribute("data-duty", "supervising");
      await expect(robot(page, dept.manager)).toHaveAttribute("data-posture", "stand");
      await expect(robot(page, dept.manager)).toHaveAttribute("data-state", "working");
      await expect(robot(page, dept.manager)).toHaveAttribute("data-pose", "idle");
    }
    for (const id of dept.peers.filter(id => ![dept.worker, dept.manager].includes(id))) {
      await expect(robot(page, id)).toHaveAttribute("data-duty", "support");
      await expect(robot(page, id)).toHaveAttribute("data-state", "idle");
      await expect(robot(page, id)).toHaveAttribute("data-pose", "idle");
      await expect(robot(page, id)).toHaveAttribute("aria-label", /idle/);
    }
  }
  await expect(robot(page, "command")).toHaveAttribute("data-room", "lounge");
  expect(feed.writes).toEqual([]);
});

test("new work is immediately in its office; the team stays until its last job finishes",
async ({ page, request }) => {
  const feed = await fixture(page, request);
  await page.goto("/#/office");
  await animations(page).selectOption("full");
  await expect(robot(page, "splice")).toHaveAttribute("data-room", "lounge");
  Object.assign(feed.role("splice"), { state: "working", task: task() });
  feed.emit("job_started", "splice");
  await expect(robot(page, "splice")).toHaveAttribute("data-state", "working", { timeout: 8000 });
  await expect(robot(page, "splice")).toHaveAttribute("data-room", "studio");
  await expect(robot(page, "splice")).toHaveAttribute("data-posture", "desk");
  for (const id of ["frame", "spark", "story"])
    await expect(robot(page, id)).toHaveAttribute("data-room", "studio", { timeout: 20_000 });
  await expect(robot(page, "frame")).toHaveAttribute("data-duty", "supervising");
  await expect(robot(page, "frame")).toHaveAttribute("data-state", "idle");
  await expect(robot(page, "frame")).toHaveAttribute("title", /Supervising/);
  Object.assign(feed.role("frame"), { state: "working", task: task("manager-job") });
  Object.assign(feed.role("story"), { state: "working", task: task("story-job") });
  feed.emit();
  await expect(robot(page, "frame")).toHaveAttribute("data-duty", "work", { timeout: 8000 });
  await expect(robot(page, "frame")).toHaveAttribute("data-posture", "desk");
  feed.role("frame").state = "reviewing"; feed.emit();
  await expect(robot(page, "frame")).toHaveAttribute("data-pose", "review", { timeout: 8000 });
  Object.assign(feed.role("frame"), { state: "idle", task: null });
  Object.assign(feed.role("splice"), { state: "idle", task: null });
  feed.emit();
  await expect(robot(page, "splice")).toHaveAttribute("data-duty", "support", { timeout: 8000 });
  await expect(robot(page, "splice")).toHaveAttribute("data-room", "studio");
  await expect(robot(page, "splice")).toHaveAttribute("data-posture", "desk");
  await expect(robot(page, "splice")).toHaveAttribute("data-break-activity", "");
  Object.assign(feed.role("story"), { state: "idle", task: null }); feed.emit();
  for (const id of ["frame", "spark", "story", "splice"])
    await expect(robot(page, id)).toHaveAttribute("data-room", "lounge", { timeout: 20_000 });
  await expect(robot(page, "splice")).toHaveAttribute("data-break-activity", /.+/);
  expect(feed.writes).toEqual([]);
});

test("real backlog and failed work gather quiet peers; timers and stale paused tasks do not",
async ({ page, request }) => {
  const feed = await fixture(page, request);
  Object.assign(feed.role("splice"), { state: "waiting", task: { ...task(), status: "queued" } });
  feed.role("story").state = "paused"; feed.role("spark").state = "unavailable";
  await page.goto("/#/office");
  await animations(page).selectOption("reduced");
  for (const id of ["frame", "spark", "story", "splice"])
    await expect(robot(page, id)).toHaveAttribute("data-room", "studio");
  for (const id of ["spark", "story"]) {
    await expect(robot(page, id)).toHaveAttribute("data-duty", "quiet");
    await expect(robot(page, id)).toHaveAttribute("data-posture", "desk");
    await expect(robot(page, id)).toHaveAttribute("data-break-activity", "");
  }
  Object.assign(feed.role("splice"), { state: "waiting", queued: 12, task: {
    ...task(), kind: "schedule_tick", status: "queued", ref_type: "", ref_id: "",
  } });
  feed.emit();
  await expect(robot(page, "frame")).toHaveAttribute("data-room", "lounge", { timeout: 8000 });
  feed.role("splice").task = null; feed.emit();
  await expect(robot(page, "splice")).toHaveAttribute("data-room", "lounge");
  Object.assign(feed.role("splice"), { state: "error", task: { ...task(), status: "blocked" } });
  feed.emit();
  await expect(robot(page, "frame")).toHaveAttribute("data-room", "studio", { timeout: 8000 });
  await expect(robot(page, "splice")).toHaveAttribute("data-pose", "error");
  for (const row of feed.snap.roles) row.state = "paused";
  feed.role("splice").task.status = "queued";
  feed.snap.run.state = "paused"; feed.emit();
  await expect(page.locator('.robot-hit[data-posture="rest"]')).toHaveCount(25);
  await expect(page.locator('.robot-hit[data-duty="supervising"]')).toHaveCount(0);
  expect(feed.writes).toEqual([]);
});

test("a genuine handoff happens in the receiver office and returns to the still-busy sender department",
async ({ page, request }) => {
  const feed = await fixture(page, request);
  Object.assign(feed.role("splice"), { state: "working", task: task() });
  Object.assign(feed.role("story"), { state: "working", task: task("story-job") });
  feed.role("frame").state = "working";
  await page.goto("/#/office");
  await animations(page).selectOption("full");
  await expect(robot(page, "splice")).toHaveAttribute("data-posture", "desk");
  Object.assign(feed.role("splice"), { state: "idle", task: null });
  Object.assign(feed.role("glyph"), { state: "working", task: task("department-job", "captions") });
  feed.emit("job_stage", "glyph", { stage: "captions" });
  const note = page.locator(".handoff-note");
  await expect(note).toHaveAttribute("data-from", "splice", { timeout: 8000 });
  await expect(note).toHaveAttribute("data-to", "glyph");
  await expect(robot(page, "glyph")).toHaveAttribute("data-room", "caption");
  await expect(note).toHaveAttribute("data-phase", "pass", { timeout: 20_000 });
  await expect(note).toHaveAttribute("data-phase", "received", { timeout: 5000 });
  await expect(robot(page, "glyph")).toHaveAttribute("data-posture", "desk", { timeout: 8000 });
  await expect(robot(page, "splice")).toHaveAttribute("data-room", "studio", { timeout: 20_000 });
  await expect(robot(page, "splice")).toHaveAttribute("data-duty", "support");
  await expect(robot(page, "splice")).toHaveAttribute("data-posture", "desk");
  await expect(robot(page, "splice")).toHaveAttribute("data-state", "idle");
  await expect(robot(page, "splice")).toHaveAttribute("data-break-activity", "");
  expect(feed.writes).toEqual([]);
});

test("Canvas fallback preserves department supervision and freezes its pixels in Reduced",
async ({ page, request }) => {
  const feed = await fixture(page, request);
  Object.assign(feed.role("splice"), { state: "working", task: task() });
  feed.role("frame").state = "working";
  await page.route("**/assets/StudioScene-*.js", route => route.abort());
  await page.goto("/#/office");
  await animations(page).selectOption("full");
  await expect(page.locator(".office-map")).toHaveAttribute("data-renderer", "canvas");
  for (const id of ["frame", "spark", "story", "splice"])
    await expect(robot(page, id)).toHaveAttribute("data-room", "studio");
  await expect(robot(page, "frame")).toHaveAttribute("data-duty", "supervising");
  const image = () => robot(page, "frame").evaluate(button => {
    const canvas = button.parentElement!.querySelector("canvas")!;
    const x = parseFloat((button as HTMLElement).style.left) * canvas.width / 100;
    const y = parseFloat((button as HTMLElement).style.top) * canvas.height / 100;
    const crop = document.createElement("canvas"); crop.width = 48; crop.height = 72;
    crop.getContext("2d")!.drawImage(canvas, x - 5, y - 3, 48, 72, 0, 0, 48, 72);
    return crop.toDataURL();
  });
  const active = await image();
  // Poll across the two idle frames: a fixed delay can sample the same 900 ms clipboard frame twice.
  await expect.poll(image, { message: "supervision changes visible artwork", timeout: 3500,
    intervals: [100, 150, 250] }).not.toBe(active);
  await animations(page).selectOption("reduced");
  await page.waitForTimeout(400); const still = await image(); await page.waitForTimeout(1250);
  expect(await image(), "Reduced freezes the supervisor artwork").toBe(still);
  expect(feed.writes).toEqual([]);
});

test("a new own job preempts an outgoing old document and starts immediately inside its office",
async ({ page, request }) => {
  const feed = await fixture(page, request);
  Object.assign(feed.role("splice"), { state: "working", task: task() });
  await page.goto("/#/office");
  await animations(page).selectOption("full");
  await expect(robot(page, "splice")).toHaveAttribute("data-posture", "desk");
  Object.assign(feed.role("splice"), { state: "idle", task: null });
  Object.assign(feed.role("glyph"), { state: "working", task: task("department-job", "captions") });
  feed.emit("job_stage", "glyph", { stage: "captions" });
  await expect(page.locator(".handoff-note")).toHaveAttribute("data-phase", "approach", { timeout: 8000 });
  await expect(robot(page, "splice")).toHaveAttribute("data-pose", "carry");
  Object.assign(feed.role("splice"), { state: "working", task: task("new-render-job") });
  feed.emit();
  await expect(robot(page, "splice")).toHaveAttribute("data-state", "working", { timeout: 8000 });
  await expect(robot(page, "splice")).toHaveAttribute("data-room", "studio");
  await expect(robot(page, "splice")).toHaveAttribute("data-posture", "desk");
  await expect(robot(page, "splice")).toHaveAttribute("data-pose", "work");
  await expect(robot(page, "splice")).toHaveAttribute("data-carrying", "false");
  await expect(page.locator(".handoff-note")).toHaveAttribute("data-phase", "idle");
  await expect(robot(page, "glyph")).toHaveAttribute("data-room", "caption");
  await expect(robot(page, "glyph")).toHaveAttribute("data-posture", "desk");
  expect(feed.writes).toEqual([]);
});
