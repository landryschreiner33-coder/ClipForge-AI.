import { expect, getJson, test } from "../fixtures";

// Looks at the publishing queue only: Approve, Edit, Publish now, Retry and Cancel are never pressed.

const VIEWS = [
  { label: "Upcoming", slug: "upcoming", empty: "Nothing scheduled yet" },
  { label: "Needs attention", slug: "problems", empty: "Nothing here" },
  { label: "Published", slug: "published", empty: "Nothing here" },
  { label: "History", slug: "history", empty: "Nothing here" },
];

test.beforeEach(async ({ page }) => {
  await page.goto("/#/publish-center");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Publish Center");
});

test("every view lists what the queue holds", async ({ page, request }) => {
  const views = page.locator(".page-head .segmented");
  for (const v of VIEWS) {
    await views.getByRole("button", { name: new RegExp(`^${v.label}`) }).click();
    await expect(page).toHaveURL(new RegExp(`#/publish-center/${v.slug}$`));
    await expect(views.locator("button.on")).toHaveText(new RegExp(`^${v.label}`));
    await expect(async () => {
      const data = await getJson(request, `/api/autopilot/scheduled?view=${v.slug}`);
      if (data.items.length === 0) await expect(page.getByRole("heading", { name: v.empty })).toBeVisible({ timeout: 1000 });
      else await expect(page.locator(".queue .qitem")).toHaveCount(data.items.length, { timeout: 1000 });
    }).toPass();
  }
});

test("the upcoming button counts posts waiting for approval", async ({ page, request }) => {
  const data = await getJson(request, "/api/autopilot/scheduled?view=upcoming");
  const waiting = data.counts.awaiting_approval || 0;
  const upcoming = page.locator(".page-head .segmented").getByRole("button", { name: /^Upcoming/ });
  await expect(upcoming).toHaveText(waiting ? `Upcoming · ${waiting} to approve` : "Upcoming");
});

test("the page says whether approved posts go out automatically", async ({ page, request }) => {
  const data = await getJson(request, "/api/autopilot/scheduled?view=upcoming");
  const intro = page.locator(".page-head p");
  await expect(intro).toContainText(data.auto_publish ? "automatically" : "automatic publishing is off");
  await expect(intro).toContainText(`Times are in ${data.timezone}`);
});

test("an unknown view shows Upcoming", async ({ page }) => {
  await page.goto("/#/publish-center/no-such-view");
  await expect(page.locator(".page-head .segmented button.on")).toHaveText(/^Upcoming/);
});

test("each post shows the final quality check of its exact file", async ({ page, request }) => {
  const data = await getJson(request, "/api/autopilot/scheduled?view=all");
  test.skip(data.items.length === 0, "no scheduled posts in your queue");
  const views = page.locator(".page-head .segmented");
  for (const v of ["upcoming", "problems", "published", "history"]) {
    const { items } = await getJson(request, `/api/autopilot/scheduled?view=${v}`);
    if (!items.length) continue;
    await views.getByRole("button", { name: new RegExp(`^${VIEWS.find((x) => x.slug === v)!.label}`) }).click();
    for (const it of items.slice(0, 10)) {
      const q = it.quality;
      const expected = !q ? "Final check pending" : q.status === "failed" ? "Final check failed"
        : q.text_status && q.text_status !== "passed" ? "Text needs a fix"
        : q.warnings.length ? /^Final check: \d+ warnings?$/ : "Final check passed";
      const badge = page.locator(`.qitem[data-id="${it.id}"] .badge`).filter({ hasText: /Final check|Text needs a fix/ });
      await expect(badge).toHaveText(expected);
    }
  }
});
