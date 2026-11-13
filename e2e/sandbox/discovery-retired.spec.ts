import { expect, test } from "@playwright/test";

// Automatic source discovery is retired (studio upgrade, section 2): ClipForge works only on the videos and links you
// add. Its old setup screens (search connections, search keys, scan limits, topics) are gone; these checks keep them
// gone. Every request that could change something is refused by this fixture, so nothing is saved.

test("no screen offers discovery search, search keys, topics or scan limits", async ({ page }) => {
  const writes: string[] = [];
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.route("**/api/**", (route) => {
    const request = route.request();
    if (request.method() === "GET" || request.method() === "HEAD") return route.continue();
    writes.push(`${request.method()} ${new URL(request.url()).pathname}`);
    return route.fulfill({ status: 409, json: { detail: "Read-only check; nothing is saved." } });
  });

  await page.goto("/#/settings/integrations");
  await expect(page.getByRole("heading", { name: "Connections", level: 2, exact: true })).toBeVisible();
  await expect(page.getByRole("region", { name: "Search connections", exact: true })).toHaveCount(0);
  await expect(page.locator("#set-youtube_api_key, #set-tavily_api_key")).toHaveCount(0);

  await page.goto("/#/settings/advanced");
  await expect(page.getByRole("heading", { name: "Rights and YouTube data", level: 2, exact: true })).toBeVisible();
  for (const key of ["trend_topics", "trend_region", "trend_poll_minutes", "discovery_min_source_score",
    "discovery_candidates_per_scan", "discovery_monthly_budget_usd", "library_discovery", "autopilot_public_videos"]) {
    await expect(page.locator(`[id="set-${key}"]`), key).toHaveCount(0);
  }

  await page.goto("/#/setup/mode");
  await expect(page.getByRole("radio", { name: /Process the videos I add automatically/ })).toBeVisible();
  await expect(page.getByText("ClipForge never searches the internet for videos to clip.", { exact: false }))
    .toBeVisible();
  await expect(page.getByRole("textbox", { name: /topic/i })).toHaveCount(0);

  expect(writes).toEqual([]);
  expect(errors).toEqual([]);
});
