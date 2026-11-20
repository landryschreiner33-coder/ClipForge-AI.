import { expect, getJson, test } from "../fixtures";

// The Office (docs/OFFICE.md): the space ship over the real job system. Read-only: the bottom bar's controls
// (Start, Resume, Pause, Stop all, Pause publishing) are looked at, never pressed. Robots, rooms, Activity, Map/List
// and Animations only change what this browser shows.

const STATE_WORDS: Record<string, string> = {
  idle: "idle", working: "working", waiting: "waiting", retrying: "retrying", error: "stopped by an error",
  reviewing: "reviewing", paused: "paused", unavailable: "unavailable",
};

test.beforeEach(async ({ page }) => {
  await page.goto("/#/office");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Office");
});

test("the bottom bar shows Autopilot's real state and only the controls that fit it", async ({ page, request }) => {
  const bar = page.getByRole("region", { name: "Autopilot controls" });
  await expect(async () => {
    const snap = await getJson(request, "/api/office/snapshot");
    await expect(bar.locator("#office-run-state")).toHaveText(snap.run.label, { timeout: 1000 });
    for (const [action, name] of [["start", "Start"], ["resume", "Resume"], ["pause", "Pause"], ["stop", "Stop all"]]) {
      await expect(bar.getByRole("button", { name, exact: true }))
        .toHaveCount(snap.run.actions.includes(action) ? 1 : 0, { timeout: 1000 });
    }
    const publishing = snap.run.publishing_paused ? "Resume publishing" : "Pause publishing";
    await expect(bar.getByRole("button", { name: publishing })).toBeVisible({ timeout: 1000 });
  }).toPass();
  await expect(bar).toContainText("Who watches: YouTube invited viewers · TikTok approved followers");
});

test("the map has every room, and each robot says its real state", async ({ page, request }) => {
  await page.getByRole("button", { name: "Map", exact: true }).click();
  const world = page.locator(".office-world");
  await expect(world.locator("canvas")).toBeVisible();
  // the ship's rooms (office/cast.ts ROOM_NAMES), each a button over the canvas
  for (const room of ["Lounge", "Control room", "Media research", "Brain", "Intake", "Story & analysis", "Editing",
    "Sound & captions", "Quality & export", "Publishing"]) {
    await expect(world.getByRole("button", { name: new RegExp(`^${room}[.:]`) })).toHaveCount(1);
  }
  await expect(async () => {
    const snap = await getJson(request, "/api/office/snapshot");
    const shown = world.locator(".robot-hit:not([hidden])");
    const n = await shown.count();
    expect(n).toBeGreaterThan(0);
    expect(n).toBeLessThanOrEqual(25);
    for (let i = 0; i < n; i++) {
      const b = shown.nth(i);
      const id = await b.getAttribute("data-id");
      const row = snap.roles.find((r: any) => r.id === id);
      expect(row, "a robot the job system knows").toBeTruthy();
      await expect(b).toHaveAttribute("data-state", row.state, { timeout: 500 });
      await expect(b).toHaveAttribute("aria-label", new RegExp(`, ${STATE_WORDS[row.state]}`), { timeout: 500 });
    }
  }).toPass({ timeout: 20_000 });
});

test("robots on duty stand in their own room; resting ones are in the lounge", async ({ page, request }) => {
  const cast = await getJson(request, "/api/office/roles");
  const room: Record<string, string> = Object.fromEntries(cast.roles.map((r: any) => [r.id, r.room]));
  await page.getByRole("button", { name: "Map", exact: true }).click();
  await page.getByLabel("Animations").selectOption("reduced");  // robots jump to their places instead of walking
  await expect(async () => {
    const snap = await getJson(request, "/api/office/snapshot");
    for (const row of snap.roles) {
      const b = page.locator(`.robot-hit[data-id="${row.id}"]`);
      if (!(await b.count()) || await b.isHidden()) continue;  // a resting robot the lounge only counts
      // on duty: in its own room. Otherwise its own room while its department is busy (office/DepartmentDuty.ts),
      // or the lounge. Never another department's room.
      const want = ["working", "reviewing", "error"].includes(row.state) ? new RegExp(`^${room[row.id]}$`)
        : new RegExp(`^(${room[row.id]}|lounge)$`);
      await expect(b, row.id).toHaveAttribute("data-room", want, { timeout: 500 });
    }
  }).toPass({ timeout: 20_000 });
  await page.getByLabel("Animations").selectOption("system");
});

test("a robot opens its card: role, manager and the next stage", async ({ page }) => {
  await page.getByRole("button", { name: "List", exact: true }).click();
  await page.locator(".dept-robot", { hasText: "CLOCK" }).click();
  const panel = page.getByRole("complementary", { name: "Details" });
  await expect(panel.getByRole("heading", { level: 2 })).toHaveText("CLOCK");
  await expect(panel).toContainText("Media Research Manager");  // the rooms changed with the studio upgrade (section 5)
  await expect(panel).toContainText("COMMAND");
  await page.keyboard.press("Escape");
  await expect(panel.getByRole("heading", { level: 2 })).toHaveText("Today");
  await page.getByRole("button", { name: "Map", exact: true }).click();
});

test("a room opens its details", async ({ page }) => {
  await page.getByRole("button", { name: "Map", exact: true }).click();
  // System health and the Dev Log moved into Quality & export with the studio upgrade (section 5)
  await page.locator(".office-world").getByRole("button", { name: /^Quality & export\b/ }).click();
  const panel = page.getByRole("complementary", { name: "Details" });
  await expect(panel.getByRole("heading", { level: 2 })).toHaveText("Quality & export");
  await expect(panel).toContainText("Dev Log");
  await panel.getByRole("button", { name: "Close details" }).click();
  await expect(panel.getByRole("heading", { level: 2 })).toHaveText("Today");
});

test("Activity lists the real feed, newest first", async ({ page }) => {
  await page.getByRole("button", { name: "Activity" }).click();
  const panel = page.getByRole("complementary", { name: "Details" });
  await expect(panel.getByRole("heading", { level: 2 })).toHaveText("Activity");
  await expect(panel.locator(".op-activity li").first().or(panel.getByText("No activity yet."))).toBeVisible();
  const times = await panel.locator(".op-activity time").evaluateAll((ts) => ts.map((t) => t.getAttribute("datetime")));
  expect(times, "newest first").toEqual([...times].sort().reverse());
});

test("the overview's numbers come from the snapshot", async ({ page, request }) => {
  const panel = page.getByRole("complementary", { name: "Details" });
  await expect(async () => {
    const snap = await getJson(request, "/api/office/snapshot");
    await expect(panel).toContainText(snap.health.headline, { timeout: 1000 });
    if (!snap.next_upload) await expect(panel).toContainText("Next upload: none planned", { timeout: 1000 });
  }).toPass();
  await expect(panel.getByText("Nothing is uploaded", { exact: false })).toHaveCount(0);  // no invented promises
});

test("the Team roster lists the 25 robots and CORE", async ({ page }) => {
  await page.getByRole("link", { name: "Team" }).click();
  await expect(page).toHaveURL(/#\/office\/team$/);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Team");
  await expect(page.locator(".team-card")).toHaveCount(26);
  await expect(page.locator(".team-card", { has: page.locator("b", { hasText: /^CORE$/ }) })).toContainText("Brain");
});

test("the robot gallery shows every robot in every frame the ship uses", async ({ page }) => {
  await page.goto("/#/dev/robots");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Robot gallery");
  await expect(page.locator(".gallery tbody tr")).toHaveCount(25);
});
