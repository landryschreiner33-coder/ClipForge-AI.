import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

// The Office (#/) drawn from controlled responses: these tests check how the page shows a snapshot, not the
// pipeline (real worker captures are in zero-touch-loop.spec.ts). The snapshot starts from the sandbox's own
// /api/office answer, and the browser never changes application data: every write request fails the test.
async function controlled(page: Page, request: APIRequestContext) {
  const snap = await (await request.get("/api/office")).json();
  snap.run_state = "running";
  snap.needs_you = [];
  snap.recent = [];
  for (const r of snap.robots) Object.assign(r, { state: "idle", task: null, queued: 0, last: null });
  const writes: string[] = [];
  page.on("request", (r) => {
    if (r.url().includes("/api/") && !["GET", "HEAD"].includes(r.method())) writes.push(`${r.method()} ${r.url()}`);
  });
  await page.route("**/api/office", (route) => route.fulfill({ json: snap }));
  await page.route("**/api/office/events?*", (route) => route.fulfill({
    json: { events: [], cursor: snap.cursor, latest: snap.cursor, gap: false, server_time: Date.now() / 1000 },
  }));
  return { snap, writes };
}

const robot = (snap: any, role: string) => snap.robots.find((r: any) => r.role === role);
const bot = (page: Page, name: string) => page.locator(".office-map").getByRole("button", {
  name: new RegExp(`^${name}, `),
});
const panel = (page: Page) => page.getByRole("complementary", { name: "Details" });

test("robots stand in their rooms, and a robot or a room opens the detail panel", async ({ page, request }) => {
  const { snap, writes } = await controlled(page, request);
  Object.assign(robot(snap, "pulse"), { state: "working", queued: 1, task: {
    job_id: "job-pulse-1", stage: "analyze_source", label: "Finding the best moments", progress: 0.37,
    message: "Reported step 2", ref_type: "", ref_id: "",
  } });
  robot(snap, "vector").state = "monitoring";
  await page.goto("/#/");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Office");
  await expect(page).toHaveTitle("Office · ClipFoundry");

  // Every robot of the snapshot is drawn once, at its own desk: nobody rests while Autopilot runs.
  const map = page.locator(".office-map");
  await expect(map.locator("button.bot")).toHaveCount(snap.robots.length);
  await expect(map.locator('section.room[data-room="lounge"] button.bot')).toHaveCount(0);
  const analyze = map.locator('section.room[data-room="analyze"]');
  await expect(analyze.getByRole("button", { name: /^PULSE, .*: Working: Finding the best moments$/ }))
    .toBeVisible();
  await expect(analyze.getByRole("button", { name: /^VECTOR, .*: Watching the team's work$/ })).toBeVisible();
  await expect(analyze.getByRole("button", { name: "Analyze: open details (1 working)" })).toBeVisible();
  await expect(page.locator(".control-bar")).toContainText("Running");

  // A robot: who it is, its exact reported progress, and where its work leads
  await expect(panel(page).getByRole("heading", { level: 2 })).toHaveText("Studio");
  await bot(page, "PULSE").click();
  await expect(bot(page, "PULSE")).toHaveAttribute("aria-pressed", "true");
  await expect(panel(page).getByRole("heading", { level: 2 })).toHaveText("Robot");
  await expect(panel(page).getByRole("heading", { level: 3 })).toHaveText("PULSE");
  const task = panel(page).getByRole("region", { name: "Current task" });
  await expect(task).toContainText("Finding the best moments");
  await expect(task).toContainText("Reported step 2");
  await expect(task.getByRole("progressbar")).toHaveAccessibleName(/37% of this step/);
  // Its manager is one click away
  await panel(page).getByRole("button", { name: /^VECTOR · / }).click();
  await expect(panel(page).getByRole("heading", { level: 3 })).toHaveText("VECTOR");
  await panel(page).getByRole("button", { name: "Overview" }).click();
  await expect(panel(page).getByRole("heading", { level: 2 })).toHaveText("Studio");

  // A room: its sign opens the room's details with its crew; pressing it again goes back to the overview
  const sign = analyze.getByRole("button", { name: /^Analyze: open details/ });
  await sign.click();
  await expect(sign).toHaveAttribute("aria-pressed", "true");
  await expect(panel(page).getByRole("heading", { level: 2 })).toHaveText("Analyze");
  const crew = panel(page).getByRole("region", { name: "Analyze robots" });
  await expect(crew.getByRole("listitem")).toHaveCount(4);
  await expect(crew).toContainText("Working: Finding the best moments");
  await sign.click();
  await expect(panel(page).getByRole("heading", { level: 2 })).toHaveText("Studio");

  // The panel can be hidden and shown again
  await panel(page).getByRole("button", { name: "Hide details" }).click();
  await expect(panel(page)).toBeHidden();
  await page.getByRole("button", { name: "Show details" }).click();
  await expect(panel(page)).toBeVisible();
  expect(writes).toEqual([]);
});

test("paused robots rest in the Lounge, and a lost connection greys the office instead of guessing", async ({
  page, request,
}) => {
  const { snap, writes } = await controlled(page, request);
  snap.run_state = "paused";
  for (const r of snap.robots) r.state = "lounge";
  await page.goto("/#/");
  const lounge = page.locator('.office-map section.room[data-room="lounge"]');
  // At most five are drawn; the others are a count that opens the Lounge's list
  await expect(lounge.locator("button.bot")).toHaveCount(5);
  const more = lounge.getByRole("button", { name: `${snap.robots.length - 5} more robots resting: show the list` });
  await expect(more).toBeVisible();
  await more.click();
  await expect(panel(page).getByRole("heading", { level: 2 })).toHaveText("Lounge");
  await expect(panel(page).getByRole("region", { name: "Lounge robots" }).getByRole("listitem"))
    .toHaveCount(snap.robots.length);
  await expect(page.locator(".control-bar")).toContainText("Paused");

  // The office stops answering: after two missed reads it says so, and no robot claims a state
  await page.unroute("**/api/office");
  await page.unroute("**/api/office/events?*");
  await page.route("**/api/office**", (route) => route.abort());
  const note = page.locator(".office-toolbar [role=status]");
  await expect(note).toContainText("Connection lost, data may be stale", { timeout: 15_000 });
  await expect(page.locator(".office-stage")).toHaveClass(/is-stale/);
  await expect(lounge.locator("button.bot").first()).toHaveAccessibleName(/state unknown \(connection lost\)$/);
  await expect(page.locator(".control-bar")).toContainText("Health unknown");
  await expect(page.locator(".control-bar")).toContainText("Unknown");
  await panel(page).getByRole("button", { name: "Overview" }).click();
  await expect(panel(page)).toContainText("Unknown while ClipFoundry is not answering.");

  // It answers again: Try again reloads, and the notice goes away
  await page.unroute("**/api/office**");
  await page.route("**/api/office", (route) => route.fulfill({ json: snap }));
  await page.route("**/api/office/events?*", (route) => route.fulfill({
    json: { events: [], cursor: snap.cursor, latest: snap.cursor, gap: false, server_time: Date.now() / 1000 },
  }));
  await note.getByRole("button", { name: "Try again" }).click();
  await expect(page.getByText("Connection lost, data may be stale")).toHaveCount(0);
  await expect(page.locator(".office-stage")).not.toHaveClass(/is-stale/);
  expect(writes).toEqual([]);
});

test("Reduce animations freezes the robots, and the list view shows every robot without the map", async ({
  page, request,
}) => {
  await page.emulateMedia({ reducedMotion: "no-preference" });
  const { snap, writes } = await controlled(page, request);
  Object.assign(robot(snap, "spark"), { state: "working", queued: 1, task: {
    job_id: "job-spark-1", stage: "render", label: "Rendering", progress: null, message: "", ref_type: "",
    ref_id: "",
  } });
  await page.goto("/#/");
  const sprite = bot(page, "SPARK").locator("svg.robot-sprite");
  // A working robot animates while motion is allowed...
  const first = await sprite.getAttribute("data-frame");
  await expect.poll(() => sprite.getAttribute("data-frame"), { timeout: 5000 }).not.toBe(first);

  // ...and stands still once Reduce animations is on (a browser preference: nothing is saved in the app)
  const reduce = page.getByRole("switch", { name: "Reduce animations" });
  await expect(reduce).toHaveAttribute("aria-checked", "false");
  await reduce.click();
  await expect(reduce).toHaveAttribute("aria-checked", "true");
  await expect(page.locator("html")).toHaveAttribute("data-motion", "reduced");
  const still = await sprite.getAttribute("data-frame");
  await page.waitForTimeout(1500);
  await expect(sprite).toHaveAttribute("data-frame", still!);
  // Its progress is not reported, so the bar says so instead of moving
  await bot(page, "SPARK").click();
  const bar = panel(page).getByRole("progressbar", { name: /progress not reported/ });
  await expect(bar).toBeVisible();
  await expect(bar.locator("span")).toHaveCSS("animation-name", "none");

  // The operating system's preference wins: the switch shows it and cannot be turned off
  await reduce.click();
  await expect(reduce).toHaveAttribute("aria-checked", "false");
  await page.emulateMedia({ reducedMotion: "reduce" });
  await expect(reduce).toBeDisabled();
  await expect(reduce).toHaveAttribute("aria-checked", "true");
  await expect(page.locator("html")).toHaveAttribute("data-motion", "reduced");
  await page.emulateMedia({ reducedMotion: "no-preference" });

  // List view: the rooms as cards with every robot and its state; this browser remembers it
  const list = page.getByRole("switch", { name: "List view" });
  await list.click();
  await expect(list).toHaveAttribute("aria-checked", "true");
  await expect(page.locator(".office-map")).toBeHidden();
  const cards = page.locator(".office-list");
  await expect(cards).toBeVisible();
  await expect(cards.locator(".dept-row")).toHaveCount(snap.robots.length);
  await expect(cards.locator(".dept-row", { hasText: "SPARK" })).toContainText("Working");
  await page.reload();
  await expect(page.getByRole("switch", { name: "List view" })).toHaveAttribute("aria-checked", "true");
  await expect(page.locator(".office-map")).toBeHidden();
  await cards.locator(".dept-row", { hasText: "SPARK" }).click();
  await expect(panel(page).getByRole("heading", { level: 3 })).toHaveText("SPARK");
  await page.getByRole("switch", { name: "List view" }).click();
  await expect(page.locator(".office-map")).toBeVisible();

  // A narrow window shows the cards by itself, without sideways scrolling
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.locator(".office-map")).toBeHidden();
  await expect(cards).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
  expect(writes).toEqual([]);
});
