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
