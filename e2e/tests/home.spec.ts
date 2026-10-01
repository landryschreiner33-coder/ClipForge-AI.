import { expect, getJson, test } from "../fixtures";

// Home: the one next step, then recent videos and clips and the next few posts. Read-only: only links are followed;
// no button on the page is pressed (the fixture blocks, and fails on, anything that would change data).

test.beforeEach(async ({ page }) => {
  await page.goto("/#/");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Home");
});

test("the next step comes from Autopilot's and the library's real state", async ({ page, request }) => {
  const lead = page.locator("section.lead");
  await expect(async () => {
    const [st, stats] = await Promise.all([getJson(request, "/api/autopilot/status"), getJson(request, "/api/stats")]);
    const title = lead.locator("#lead-title");
    const failed = stats.recent.filter((p: any) => p.status === "error");
    if (!st.home.setup.started && stats.recent.length === 0) {
      // First use (this browser never chose to make clips by hand): a welcome with the two ways to start
      await expect(title).toHaveText(/^Start by adding a video you made/, { timeout: 1000 });
      await expect(lead.getByRole("link", { name: "Get started" })).toHaveAttribute("href", "#/setup/videos");
      await expect(lead.getByRole("link", { name: "Add a video now" })).toHaveAttribute("href", "#/create");
    } else if (st.home.needs_you.length) {
      await expect(title).toHaveText(st.home.needs_you[0].title, { timeout: 1000 });
      await expect(lead).toContainText("Needs you", { timeout: 1000 });
    } else if (failed.length) {
      await expect(title).toHaveText(`“${failed[0].name}” could not be made into clips`, { timeout: 1000 });
    } else {
      await expect(title).not.toBeEmpty({ timeout: 1000 });
      await expect(lead).not.toContainText("Needs you", { timeout: 1000 });
    }
  }).toPass();
});

test("the status line names Autopilot's real state and links to it", async ({ page, request }) => {
  await expect(async () => {
    const st = await getJson(request, "/api/autopilot/status");
    const word = st.paused ? "Stopped" : st.enabled ? "On" : st.home.setup.started ? "Paused" : "Off";
    await expect(page.locator(".page-head").getByRole("link", { name: `Autopilot: ${word}` }))
      .toHaveAttribute("href", "#/autopilot", { timeout: 1000 });
  }).toPass();
});

test("Recent videos and clips match the library", async ({ page, request }) => {
  await expect(page.getByRole("heading", { name: "Recent videos and clips" })).toBeVisible();
  await expect(async () => {
    const s = await getJson(request, "/api/stats");
    if (s.recent.length === 0) {
      await expect(page.getByText("No videos yet.")).toBeVisible({ timeout: 1000 });
    } else {
      const rows = page.locator(".recent-row");
      await expect(rows).toHaveCount(Math.min(4, s.recent.length), { timeout: 1000 });
      await expect(rows.first().locator(".post-title")).toHaveText(s.recent[0].name, { timeout: 1000 });
      await expect(rows.first().locator(".post-title")).toHaveAttribute("href", `#/project/${s.recent[0].id}`);
    }
  }).toPass();
  await expect(page.getByRole("link", { name: "Open Library" })).toHaveAttribute("href", "#/library");
});

test("Coming up matches the posts Autopilot planned", async ({ page, request }) => {
  const panel = page.locator("section", { has: page.getByRole("heading", { name: "Coming up" }) });
  await expect(async () => {
    const upcoming = (await getJson(request, "/api/autopilot/status")).home.upcoming.slice(0, 4);
    if (!upcoming.length) {
      await expect(panel.getByText(/^No posts planned\./)).toBeVisible({ timeout: 1000 });
    } else {
      const rows = panel.locator(".upcoming-row");
      await expect(rows).toHaveCount(upcoming.length, { timeout: 1000 });
      await expect(rows.first().locator(".post-title")).toHaveText(upcoming[0].title || "Untitled post",
        { timeout: 1000 });
    }
  }).toPass();
  await expect(panel.getByRole("link", { name: "All posts" })).toHaveAttribute("href", "#/posts/scheduled");
});

test("Home shows no stats or system details: those live under Autopilot → Advanced", async ({ page }) => {
  for (const h of ["Workers", "GPU", "System", "YouTube API quota", "Performance"]) {
    await expect(page.getByRole("heading", { name: h, exact: true })).toHaveCount(0);
  }
  await expect(page.getByText("Runtime cost", { exact: false })).toHaveCount(0);
});

test("Add video opens Add video", async ({ page }) => {
  await page.locator(".page-head").getByRole("link", { name: "Add video", exact: true }).click();
  await expect(page).toHaveURL(/#\/create$/);
});
