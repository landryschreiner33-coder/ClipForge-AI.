import { expect, test } from "@playwright/test";

test("Missions explains finished clips waiting for post preparation even when Needs you is empty",
async ({ page, request }) => {
  const initialStatus = await (await request.get("/api/autopilot/status")).json();
  const errors: string[] = [];
  const writes: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.route("**/api/autopilot/status", async (route) => {
    const data = structuredClone(initialStatus);
    data.enabled = true; data.paused = false; data.workers_alive = true;
    data.home.setup.started = true;
    data.home.needs_you = [];
    data.home.posting = { finished: 3, checked: 3, sampled: false, platforms: [{
      platform: "youtube", code: "preparing", title: "Finished clips need titles and captions",
      detail: "Eligible interrupted handoffs recover automatically. Check Jobs for the current post-preparation step.",
      link: "#/missions/jobs", automatic: true,
      counts: { preparing: 3, checking: 0, failed_check: 0, local_only: 0, ready: 0, scheduled: 0 },
    }] };
    await route.fulfill({ json: data });
  });
  page.on("request", (request) => {
    if (new URL(request.url()).pathname.startsWith("/api/") && request.method() !== "GET") {
      writes.push(request.method() + " " + request.url());
    }
  });
  await page.goto("/#/missions");
  const panel = page.getByRole("region", { name: "Why clips are waiting to post" });
  await expect(panel.getByText("3 finished automatic clips")).toBeVisible();
  await expect(panel.getByText("Finished clips need titles and captions")).toBeVisible();
  await expect(panel.getByLabel("YouTube posting stages")).toContainText("3 need post text");
  await expect(panel.getByRole("link", { name: "See the next step" })).toHaveAttribute("href", "#/missions/jobs");
  await expect(panel.getByText("TikTok", { exact: true })).toHaveCount(0);
  expect(writes).toEqual([]);
  expect(errors).toEqual([]);
});
