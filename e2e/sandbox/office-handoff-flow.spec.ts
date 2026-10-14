import { expect, test, Page, APIRequestContext } from "@playwright/test";

// Controlled read-only responses exercise choreography; no production job, permission or upload is changed.
async function fixture(page: Page, request: APIRequestContext) {
  const snap = await (await request.get("/api/office/snapshot")).json();
  Object.assign(snap, { cursor: 0, needs_you: [] });
  snap.run = { ...snap.run, state: "running", label: "Running", actions: ["pause", "stop"] };
  snap.brain.state = "cold_start";
  delete snap.brain.activity;
  for (const role of snap.roles) Object.assign(role, {
    state: "idle", task: null, queued: 0, tasks: 0, last: null, error: "",
    idle_reason: "Waiting for an assigned stage; other rooms work only when their input is ready.",
  });
  const events: any[] = [], writes: string[] = [];
  page.on("request", request => {
    if (new URL(request.url()).pathname.startsWith("/api/") && !["GET", "HEAD"].includes(request.method()))
      writes.push(request.method());
  });
  await page.route("**/api/office/snapshot", route => route.fulfill({ json: {
    ...snap, server_time: Date.now() / 1000,
  } }));
  await page.route("**/api/office/events**", route => {
    const after = Number(new URL(route.request().url()).searchParams.get("after") || 0);
    const rows = events.filter(event => event.id > after);
    return route.fulfill({ json: { events: rows, cursor: rows.at(-1)?.id || after,
      latest: snap.cursor, more: false, reset: false, server_time: Date.now() / 1000 } });
  });
  return { snap, writes, role: (id: string) => snap.roles.find((role: any) => role.id === id),
    emit: (type: string, role: string, data: object, extra: object = {}) => {
      const event = { id: ++snap.cursor, at: Date.now() / 1000, type, role, job_id: "handoff-job",
        kind: "analyze_source", ref_type: "source", ref_id: "handoff-source",
        message: "Controlled recorded work handoff", data, ...extra };
      events.push(event); return event;
    } };
}
const robot = (page: Page, id: string) => page.locator(`.robot-hit[data-id="${id}"]`);
const animations = (page: Page) => page.getByRole("combobox", { name: "Animations", exact: true });
const task = (job = "handoff-job", stage = "render") => ({ job_id: job, kind: "analyze_source", stage,
  status: "running", ref_type: "source", ref_id: "handoff-source", message: "Controlled stage",
  progress: null, updated_at: Date.now() / 1000 });

async function recordPasses(page: Page) {
  await page.evaluate(() => {
    const note = document.querySelector<HTMLElement>(".handoff-note")!;
    const captured: string[] = [];
    (window as any).recordedOfficePasses = captured;
    new MutationObserver(() => {
      if (note.dataset.phase !== "pass") return;
      const pair = `${note.dataset.from}>${note.dataset.to}`;
      if (captured.at(-1) !== pair) captured.push(pair);
    }).observe(note, { attributes: true });
  });
}

test("a recorded report reaches its manager and boss before the next department receives it",
async ({ page, request }) => {
  const feed = await fixture(page, request);
  Object.assign(feed.role("splice"), { state: "working", task: task() });
  Object.assign(feed.role("story"), { state: "working", task: task("unrelated-story") });
  await page.goto("/#/office");
  await animations(page).selectOption("full");
  await expect(robot(page, "splice")).toHaveAttribute("data-posture", "desk");
  await recordPasses(page);
  Object.assign(feed.role("splice"), { state: "idle", task: null });
  Object.assign(feed.role("glyph"), { state: "working", task: task("handoff-job", "captions") });
  feed.emit("report", "frame", { worker: "splice", state: "done", handoff_kind: "report",
    handoff_path: ["splice", "frame", "command"], report_id: "recorded-report" });
  feed.emit("job_stage", "glyph", { stage: "captions", handoff_kind: "stage",
    handoff_path: ["command", "script", "glyph"], decision_id: "recorded-accept" });
  await expect.poll(() => page.evaluate(() => (window as any).recordedOfficePasses), {
    timeout: 55_000,
  }).toEqual(["splice>frame", "frame>command", "command>script", "script>glyph"]);
  await expect(robot(page, "glyph")).toHaveAttribute("data-room", "caption");
  await expect(robot(page, "glyph")).toHaveAttribute("data-state", "working");
  await expect(robot(page, "glyph")).toHaveAttribute("data-posture", "desk");
  await expect(robot(page, "story")).toHaveAttribute("data-room", "studio");
  await expect(robot(page, "story")).toHaveAttribute("data-posture", "desk");
  await expect(robot(page, "story")).toHaveAttribute("data-carrying", "false");
  await expect(robot(page, "splice")).toHaveAttribute("data-room", "studio");
  await expect(robot(page, "splice")).toHaveAttribute("data-duty", "support");
  expect(feed.writes).toEqual([]);
});

test("an explicit no-handoff path and unrelated active work never borrow a robot",
async ({ page, request }) => {
  const feed = await fixture(page, request);
  Object.assign(feed.role("splice"), { state: "working", task: task() });
  Object.assign(feed.role("frame"), { state: "working", task: task("manager-other-job") });
  await page.goto("/#/office");
  await animations(page).selectOption("full");
  await recordPasses(page);
  Object.assign(feed.role("splice"), { state: "idle", task: null });
  Object.assign(feed.role("glyph"), { state: "working", task: task("handoff-job", "captions") });
  feed.emit("job_stage", "glyph", { stage: "captions", handoff_path: [] });
  // The manager is processing a different durable job: even a real report waits in Activity.
  feed.emit("report", "frame", { worker: "splice", handoff_kind: "report",
    handoff_path: ["splice", "frame", "command"] });
  await expect(robot(page, "glyph")).toHaveAttribute("data-state", "working");
  await expect(robot(page, "glyph")).toHaveAttribute("data-posture", "desk");
  await expect(robot(page, "frame")).toHaveAttribute("data-posture", "desk");
  await expect(page.locator(".handoff-note")).toHaveAttribute("data-phase", "idle");
  expect(await page.evaluate(() => (window as any).recordedOfficePasses)).toEqual([]);
  await robot(page, "radar").click();
  await expect(page.locator(".office-panel")).toContainText("Waiting for an assigned stage");
  expect(feed.writes).toEqual([]);
});

test("actual Brain consultations light CORE without pretending results have trained it",
async ({ page, request }, testInfo) => {
  const feed = await fixture(page, request);
  feed.snap.brain.activity = { state: "working", role: "synapse", message: "Consulting saved guidance",
    at: Date.now() / 1000, consultation_id: "consultation-fixture", purpose: "blueprint", consulted: 2,
    applied: 1, ref_type: "clip", ref_id: "fixture-clip", last: null };
  Object.assign(feed.role("synapse"), { state: "working", task: { ...task("", "knowledge"),
    kind: "brain_consultation", consultation_id: "consultation-fixture",
    message: "Consulting saved guidance" } });
  feed.role("curator").state = "working"; // actual snapshot oversight: no manufactured task
  await page.goto("/#/office");
  await animations(page).selectOption("full");
  const core = page.locator(".brain-core-hit");
  await expect(core).toHaveAttribute("data-mode", "active");
  await expect(core).toHaveAttribute("aria-label", /Consulting guidance/);
  for (const id of ["synapse", "curator", "metric"])
    await expect(robot(page, id)).toHaveAttribute("data-room", "brain");
  await expect(robot(page, "synapse")).toHaveAttribute("data-posture", "desk");
  await expect(robot(page, "curator")).toHaveAttribute("data-duty", "supervising");
  await expect(robot(page, "metric")).toHaveAttribute("data-state", "idle");
  await robot(page, "synapse").click();
  await expect(page.locator(".op-task-meta")).toContainText("Saved guidance consultation");
  await expect(page.getByRole("link", { name: "Open Brain workspace", exact: true }))
    .toHaveAttribute("href", "#/brain");
  await expect(page.getByRole("link", { name: "Detailed jobs", exact: true })).toHaveCount(0);
  await page.screenshot({ path: testInfo.outputPath("brain-consulting.png") });
  await recordPasses(page);
  Object.assign(feed.role("synapse"), { state: "idle", task: null });
  feed.role("curator").state = "idle";
  feed.snap.brain.activity.state = "idle";
  feed.snap.brain.activity.last = { message: "Saved guidance consulted", consulted: 2, applied: 1 };
  feed.emit("brain_consultation_done", "synapse", { consultation_id: "consultation-fixture",
    handoff_path: ["synapse", "curator", "command"], handoff_kind: "report", consulted: 2, applied: 1 },
    { job_id: "", kind: "brain_consultation", ref_type: "clip", ref_id: "fixture-clip" });
  await expect.poll(() => page.evaluate(() => (window as any).recordedOfficePasses), {
    timeout: 30_000,
  }).toEqual(["synapse>curator", "curator>command"]);
  await expect(core).toHaveAttribute("data-mode", "standby");
  await animations(page).selectOption("reduced");
  // The sculpture in the room's center is its own Brain-workspace link; use the room sign for details.
  await page.getByRole("button", { name: "Brain Room. Open details", exact: true })
    .click({ position: { x: 12, y: 12 } });
  // The room has a separate read-only details endpoint; its explanation remains actual learning state.
  await expect(page.locator(".office-panel")).toContainText("Using saved guidance is separate from learning");
  await expect(page.locator(".office-panel")).toContainText("Results stored: 0 from the platforms");
  await expect(core).toHaveAttribute("data-mode", "standby");
  expect(feed.writes).toEqual([]);
});

test("an active Brain consultation stays at its desk when an older consultation hands off",
async ({ page, request }) => {
  const feed = await fixture(page, request);
  feed.snap.brain.activity = { state: "working", role: "synapse", message: "Consulting new saved guidance",
    at: Date.now() / 1000, consultation_id: "new-consultation", purpose: "blueprint", consulted: 2,
    applied: 1, ref_type: "clip", ref_id: "new-clip", last: null };
  Object.assign(feed.role("synapse"), { state: "working", task: { ...task("", "knowledge"),
    kind: "brain_consultation", consultation_id: "new-consultation", message: "Consulting new saved guidance" } });
  feed.role("curator").state = "working";
  await page.goto("/#/office");
  await animations(page).selectOption("full");
  await expect(robot(page, "synapse")).toHaveAttribute("data-posture", "desk");
  await recordPasses(page);
  await page.getByRole("button", { name: "Activity", exact: true }).click();
  feed.emit("brain_consultation_done", "synapse", { consultation_id: "old-consultation",
    handoff_path: ["synapse", "curator", "command"], handoff_kind: "report", consulted: 2, applied: 1 },
    { job_id: "", kind: "brain_consultation", message: "Previous guidance consultation finished" });
  await expect(page.locator(".op-activity")).toContainText("Previous guidance consultation finished");
  await expect(robot(page, "synapse")).toHaveAttribute("data-posture", "desk");
  await expect(robot(page, "synapse")).toHaveAttribute("data-carrying", "false");
  await expect(page.locator(".brain-core-hit")).toHaveAttribute("data-mode", "active");
  await expect(page.locator(".handoff-note")).toHaveAttribute("data-phase", "idle");
  expect(await page.evaluate(() => (window as any).recordedOfficePasses)).toEqual([]);
  expect(feed.writes).toEqual([]);
});

test("paused, reduced, hidden and offline displays do not replay queued document walks",
async ({ page, request }) => {
  const feed = await fixture(page, request);
  await page.goto("/#/office");
  await animations(page).selectOption("full");
  feed.emit("report", "frame", { worker: "splice", handoff_path: ["splice", "frame", "command"] });
  await expect(page.locator(".handoff-note")).toHaveAttribute("data-from", "splice");
  feed.snap.run.state = "paused";
  for (const role of feed.snap.roles) role.state = "paused";
  feed.emit("control", "command", {});
  await expect(page.locator(".handoff-note")).toHaveAttribute("data-phase", "idle");
  await expect(page.locator(".brain-core-hit")).toHaveAttribute("data-mode", "paused");
  for (const role of feed.snap.roles) role.state = "idle";
  feed.snap.run.state = "running";
  feed.emit("control", "command", {});
  await expect(robot(page, "splice")).toHaveAttribute("data-state", "idle");
  await animations(page).selectOption("reduced");
  feed.emit("report", "frame", { worker: "splice", handoff_path: ["splice", "frame", "command"] });
  await expect(page.locator(".handoff-note")).toHaveAttribute("data-phase", "idle");
  await animations(page).selectOption("full");
  await expect(page.locator(".handoff-note")).toHaveAttribute("data-phase", "idle");
  await page.evaluate(() => {
    Object.defineProperty(document, "hidden", { configurable: true, value: true });
    document.dispatchEvent(new Event("visibilitychange"));
  });
  feed.emit("report", "frame", { worker: "splice", handoff_path: ["splice", "frame", "command"] });
  await expect(page.locator(".handoff-note")).toHaveAttribute("data-phase", "idle");
  await page.evaluate(() => {
    Object.defineProperty(document, "hidden", { configurable: true, value: false });
    document.dispatchEvent(new Event("visibilitychange"));
  });
  await expect(page.locator(".handoff-note")).toHaveAttribute("data-phase", "idle");
  await page.route("**/api/office/events**", route => route.abort());
  await page.route("**/api/office/snapshot", route => route.abort());
  await expect(page.locator(".office-map")).toHaveClass(/stale/);
  await expect(page.locator(".brain-core-hit")).toHaveAttribute("data-mode", "offline");
  await expect(page.locator(".handoff-note")).toHaveAttribute("data-phase", "idle");
  expect(feed.writes).toEqual([]);
});
