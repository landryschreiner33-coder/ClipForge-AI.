import { expect, test, Page, APIRequestContext } from "@playwright/test";

// Only browser answers are controlled. These previews cannot start jobs, approve posts or write app settings.
async function loungeFixture(page: Page, request: APIRequestContext) {
  const snap = await (await request.get("/api/office/snapshot")).json();
  snap.cursor = 0; snap.needs_you = [];
  snap.run = { ...snap.run, state: "stopped", label: "Stopped", actions: ["start"] };
  snap.brain.state = "collecting";
  for (const row of snap.roles) Object.assign(row, {
    state: "paused", task: null, queued: 0, tasks: 0, last: null, error: "",
  });
  const events: any[] = [], writes: string[] = [];
  let disconnected = false;
  page.on("request", request => {
    if (new URL(request.url()).pathname.startsWith("/api/") && !["GET", "HEAD"].includes(request.method()))
      writes.push(`${request.method()} ${new URL(request.url()).pathname}`);
  });
  await page.route("**/api/office/snapshot", route => disconnected ? route.abort("failed")
    : route.fulfill({ json: { ...snap, server_time: Date.now() / 1000 } }));
  await page.route("**/api/office/events**", route => {
    if (disconnected) return route.abort("failed");
    const after = Number(new URL(route.request().url()).searchParams.get("after") || 0);
    const rows = events.filter(event => event.id > after);
    return route.fulfill({ json: { events: rows, cursor: rows.length ? rows[rows.length - 1].id : after,
      latest: Math.max(after, ...events.map(event => event.id)), more: false, reset: false,
      server_time: Date.now() / 1000 } });
  });
  return {
    snap, writes,
    role: (id: string) => snap.roles.find((row: any) => row.id === id),
    disconnect: () => { disconnected = true; },
    emit: (type: string, owner: string) => {
      const id = snap.cursor + 1;
      events.push({ id, at: Date.now() / 1000, type, role: owner,
        job_id: "lounge-job", kind: "analyze_source", ref_type: "source", ref_id: "lounge-source",
        message: "Controlled lounge transition", data: { stage: "render", routine: false } });
      snap.cursor = id;
    },
  };
}

const robot = (page: Page, id: string) => page.locator(`.robot-hit[data-id="${id}"]`);
const activityRobots = (page: Page) => page.locator('.robot-hit[data-break-activity]:not([data-break-activity=""])');
const animationControl = (page: Page) => page.getByRole("combobox", { name: "Animations", exact: true });

async function loungeImage(page: Page) {
  return page.locator(".office-world").evaluate(world => {
    const canvas = world.querySelector("canvas")!;
    const room = world.querySelector<HTMLElement>('.room-hit[aria-label^="Lounge"]')!;
    const x = Math.round(parseFloat(room.style.left) * canvas.width / 100);
    const y = Math.round(parseFloat(room.style.top) * canvas.height / 100);
    const width = Math.round(parseFloat(room.style.width) * canvas.width / 100);
    const height = Math.round(parseFloat(room.style.height) * canvas.height / 100);
    const crop = document.createElement("canvas"); crop.width = width; crop.height = height;
    crop.getContext("2d")!.drawImage(canvas, x, y, width, height, 0, 0, width, height);
    return crop.toDataURL();
  });
}

async function loungeState(page: Page) {
  return page.locator(".robot-hit").evaluateAll(elements => elements.map(element => {
    const el = element as HTMLElement;
    return { id: el.dataset.id, state: el.dataset.state, activity: el.dataset.breakActivity,
      phase: el.dataset.breakPhase, spot: el.dataset.breakSpot, pose: el.dataset.pose,
      left: el.style.left, top: el.style.top };
  }));
}

async function uniqueClaims(page: Page) {
  const claims = (await loungeState(page)).map(row => row.spot).filter(Boolean);
  expect(new Set(claims).size, "an activity place is reserved by at most one robot").toBe(claims.length);
}

test("a stopped office has games, food, drinks and reading while preserving all 25 actual paused states",
async ({ page, request }) => {
  const feed = await loungeFixture(page, request);
  await page.goto("/#/office");
  await animationControl(page).selectOption("reduced");
  await expect(activityRobots(page)).toHaveCount(25);
  await expect(page.locator('.robot-hit[data-state="paused"][data-room="lounge"]')).toHaveCount(25);
  const state = await loungeState(page), activities = new Set(state.map(row => row.activity));
  for (const activity of ["arcade", "boardgame", "snack", "drink", "read"])
    expect(activities.has(activity), `the lounge provides ${activity}`).toBe(true);
  expect(state.filter(row => row.spot).length, "every identity has its own activity place").toBe(25);
  await uniqueClaims(page);
  expect(new Set(state.map(row => `${row.left}|${row.top}`)).size, "robots do not share a pile of pixels").toBe(25);
  await expect(robot(page, "splice")).toHaveAttribute("aria-label", /paused/);
  await expect(page.locator(".handoff-note")).toHaveAttribute("data-phase", "idle");
  expect(feed.writes).toEqual([]);
});

test("Full animates lounge activities, while Reduced and actual Pause freeze both poses and pixels",
async ({ page, request }) => {
  const feed = await loungeFixture(page, request);
  await page.goto("/#/office");
  await animationControl(page).selectOption("full");
  await expect(activityRobots(page)).toHaveCount(25);
  const fullState = await loungeState(page), fullImage = await loungeImage(page);
  await page.waitForTimeout(850);
  expect(await loungeState(page), "activity phases advance while workers are stopped").not.toEqual(fullState);
  expect(await loungeImage(page), "the lounge has visible gestures, not just changing metadata").not.toBe(fullImage);

  await animationControl(page).selectOption("reduced");
  await page.waitForTimeout(400);
  const reducedState = await loungeState(page), reducedImage = await loungeImage(page);
  await page.waitForTimeout(850);
  expect(await loungeState(page), "Reduced does not rotate activities or advance their phases").toEqual(reducedState);
  expect(await loungeImage(page), "Reduced keeps the lounge art still").toBe(reducedImage);

  await animationControl(page).selectOption("full");
  feed.snap.run.state = "paused"; feed.emit("control", "command");
  await expect(page.locator(".brain-core-hit")).toHaveAttribute("data-mode", "paused", { timeout: 8000 });
  await page.waitForTimeout(400);
  const pausedState = await loungeState(page), pausedImage = await loungeImage(page);
  await page.waitForTimeout(850);
  expect(await loungeState(page), "an actual application Pause freezes recreational choreography").toEqual(pausedState);
  expect(await loungeImage(page)).toBe(pausedImage);
  expect(feed.writes).toEqual([]);
});

test("hidden or disconnected views freeze lounge activity instead of replaying it", async ({ page, request }) => {
  const feed = await loungeFixture(page, request);
  await page.goto("/#/office");
  await animationControl(page).selectOption("full");
  await expect(activityRobots(page)).toHaveCount(25);
  await page.evaluate(() => {
    Object.defineProperty(document, "hidden", { configurable: true, get: () => true });
    document.dispatchEvent(new Event("visibilitychange"));
  });
  await expect(page.locator("html")).toHaveAttribute("data-page-hidden", "true");
  await page.waitForTimeout(400);
  const hiddenState = await loungeState(page), hiddenImage = await loungeImage(page);
  await page.waitForTimeout(850);
  expect(await loungeState(page)).toEqual(hiddenState);
  expect(await loungeImage(page)).toBe(hiddenImage);

  await page.evaluate(() => {
    Object.defineProperty(document, "hidden", { configurable: true, get: () => false });
    document.dispatchEvent(new Event("visibilitychange"));
  });
  await expect.poll(async () => JSON.stringify(await loungeState(page)), { timeout: 8000 })
    .not.toBe(JSON.stringify(hiddenState));
  feed.disconnect();
  await expect(page.locator(".office-map")).toHaveClass(/stale/, { timeout: 10_000 });
  await page.waitForTimeout(400);
  const staleState = await loungeState(page), staleImage = await loungeImage(page);
  await page.waitForTimeout(850);
  expect(await loungeState(page)).toEqual(staleState);
  expect(await loungeImage(page)).toBe(staleImage);
  expect(feed.writes).toEqual([]);
});

test("real work preempts a lounge activity and the robot resumes its break after finishing",
async ({ page, request }) => {
  const feed = await loungeFixture(page, request);
  await page.goto("/#/office");
  await animationControl(page).selectOption("full");
  const splice = robot(page, "splice");
  await expect(splice).toHaveAttribute("data-break-activity", /^(arcade|boardgame|snack|drink|read|rest)$/);
  feed.snap.run.state = "running";
  for (const row of feed.snap.roles) row.state = "idle";
  feed.role("command").state = "paused";
  feed.role("radar").state = "unavailable";
  Object.assign(feed.role("splice"), { state: "working", task: {
    job_id: "lounge-job", kind: "analyze_source", stage: "render", status: "running",
    ref_type: "source", ref_id: "lounge-source", message: "Controlled render", progress: null,
    updated_at: Date.now() / 1000,
  } });
  feed.emit("job_started", "splice");
  await expect(splice).toHaveAttribute("data-state", "working", { timeout: 8000 });
  await expect(splice).toHaveAttribute("data-break-activity", "");
  await expect(splice).toHaveAttribute("data-break-spot", "");
  await expect(robot(page, "command")).toHaveAttribute("data-break-activity", "");
  await expect(robot(page, "radar")).toHaveAttribute("data-break-activity", "");
  await expect(splice).toHaveAttribute("data-pose", "work");
  await expect(splice).toHaveAttribute("data-posture", "desk");
  await expect(splice).toHaveAttribute("data-room", "studio");
  await expect(splice).toHaveAttribute("data-break-activity", "");
  await uniqueClaims(page);

  Object.assign(feed.role("splice"), { state: "idle", task: null });
  feed.emit("job_done", "splice");
  await expect(splice).toHaveAttribute("data-state", "idle", { timeout: 8000 });
  await expect(splice).toHaveAttribute("data-room", "lounge", { timeout: 20_000 });
  await expect(splice).toHaveAttribute("data-break-activity", /^(arcade|boardgame|snack|drink|read|rest)$/);
  await uniqueClaims(page);
  await expect(page.locator(".handoff-note")).toHaveAttribute("data-phase", "idle");
  expect(feed.writes).toEqual([]);
});

test("robots rotate lounge activities without sharing reservations or changing their backend states",
async ({ page, request }) => {
  const feed = await loungeFixture(page, request);
  await page.clock.install({ time: new Date() });
  await page.goto("/#/office");
  await page.clock.runFor(300);
  await animationControl(page).selectOption("full");
  await page.clock.runFor(300);
  await expect(activityRobots(page)).toHaveCount(25);
  const initial = await loungeState(page);
  let changed = false;
  // Run the real animation frames; jumping a timestamp would skip walking and falsely test reservations.
  for (let interval = 0; interval < 8; interval++) {
    await page.clock.runFor(5000);
    const current = await loungeState(page);
    await uniqueClaims(page);
    expect(current.every(row => row.state === "paused"), "recreation never becomes a fake working state").toBe(true);
    if (current.some((row, i) => row.spot !== initial[i].spot)) changed = true;
  }
  expect(changed, "breaks eventually include a change of place rather than one permanent seated loop").toBe(true);
  expect(feed.writes).toEqual([]);
});

test("stalled skyline art keeps Pixi usable, and a missing graphics bundle keeps animated Canvas activities",
async ({ page, request }) => {
  const feed = await loungeFixture(page, request);
  let skylineRequests = 0, graphicsRequests = 0;
  let holdSkyline = true;
  const releaseSkyline: (() => Promise<void>)[] = [];
  await page.route("**/office-art/skyline.png", route => {
    skylineRequests++;
    if (holdSkyline) {
      releaseSkyline.push(() => route.abort("failed"));
      return;
    }
    return route.abort("failed");
  });
  // A decorative image request may never complete, so the test does not wait for the page's load event.
  await page.goto("/#/office", { waitUntil: "domcontentloaded" });
  await animationControl(page).selectOption("full");
  await expect.poll(() => skylineRequests, { timeout: 6000,
    message: "the optional skyline request remains pending while the office starts" })
    .toBeGreaterThan(0);
  await expect(activityRobots(page)).toHaveCount(25, { timeout: 6000 });
  await expect(page.locator(".office-map")).toHaveAttribute("data-renderer", "pixi");
  const painted = await page.locator(".office-world canvas").evaluate((canvas: HTMLCanvasElement) => {
    const copy = document.createElement("canvas"); copy.width = canvas.width; copy.height = canvas.height;
    const ctx = copy.getContext("2d")!; ctx.drawImage(canvas, 0, 0);
    const pixels = ctx.getImageData(0, 0, copy.width, copy.height).data;
    let opaque = 0;
    for (let i = 3; i < pixels.length; i += 4) if (pixels[i]) opaque++;
    return opaque;
  });
  expect(painted, "the office paints without waiting for its decorative skyline").toBeGreaterThan(5000);
  const pixiImage = await loungeImage(page);
  await page.waitForTimeout(850);
  expect(await loungeImage(page), "a stalled image does not disable the Pixi activities").not.toBe(pixiImage);
  holdSkyline = false;
  await Promise.all(releaseSkyline.map(release => release()));
  await expect(page.locator(".office-map")).toHaveAttribute("data-renderer", "pixi");

  // Reload creates a fresh module graph: an already-loaded Scene cannot hide this deliberate bundle failure.
  await page.route("**/assets/StudioScene-*.js", route => {
    graphicsRequests++;
    return route.abort("failed");
  });
  await page.reload();
  await expect(page.locator(".office-map")).toHaveAttribute("data-renderer", "canvas");
  expect(graphicsRequests, "the production graphics chunk really failed to load").toBeGreaterThan(0);
  await expect(activityRobots(page)).toHaveCount(25);
  await expect(page.locator('.robot-hit[data-state="paused"][data-room="lounge"]')).toHaveCount(25);
  const fallbackImage = await loungeImage(page);
  await page.waitForTimeout(850);
  expect(await loungeImage(page), "the compatibility renderer also animates games, eating and drinking")
    .not.toBe(fallbackImage);
  await animationControl(page).selectOption("reduced");
  await page.waitForTimeout(400);
  const stillImage = await loungeImage(page), stillState = await loungeState(page);
  await page.waitForTimeout(850);
  expect(await loungeImage(page), "Reduced stills the Canvas activities as well").toBe(stillImage);
  expect(await loungeState(page)).toEqual(stillState);
  expect(feed.writes).toEqual([]);
});
