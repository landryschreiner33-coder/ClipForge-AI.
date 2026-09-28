import { expect, getJson, test } from "../fixtures";

// Opens your projects and clips to look at them; never deletes, renames, selects, exports or re-renders.
// Tests that need a project or a clip are skipped when your library has none.

test("the library lists every project", async ({ page, request }) => {
  await page.goto("/#/projects");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Projects");
  await expect(async () => {
    const projects = await getJson<any[]>(request, "/api/projects");
    if (projects.length === 0) {
      await expect(page.getByRole("heading", { name: "Your library is empty" })).toBeVisible({ timeout: 1000 });
    } else {
      await expect(page.locator(".proj-grid .proj-card")).toHaveCount(projects.length, { timeout: 1000 });
    }
  }).toPass();
});

test("Delete asks first, and nothing is deleted when you say no", async ({ page, request }) => {
  const projects = await getJson<any[]>(request, "/api/projects");
  const idle = projects.find((p) => !["processing", "queued"].includes(p.status));
  test.skip(!idle, "no project that can be deleted");

  await page.goto("/#/projects");
  const card = page.locator(".proj-card", { has: page.locator(".name", { hasText: idle.name }) }).first();
  let asked = "";
  page.once("dialog", async (d) => {
    asked = d.message();
    await d.dismiss();
  });
  await card.getByRole("button", { name: "Delete" }).click();
  expect(asked).toContain("This cannot be undone.");
  await expect(page).toHaveURL(/#\/projects$/);
  expect((await getJson<any[]>(request, "/api/projects")).some((p) => p.id === idle.id)).toBe(true);
});

test("a project opens from the library", async ({ page, request }) => {
  const projects = await getJson<any[]>(request, "/api/projects");
  test.skip(projects.length === 0, "the library is empty");
  const p = projects[0];

  await page.goto("/#/projects");
  await page.locator(".proj-card", { has: page.locator(".name", { hasText: p.name }) }).first().locator(".proj-thumb").click();
  await expect(page).toHaveURL(new RegExp(`#/project/${p.id}$`));
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(p.name);
  await expect(page.locator(".sidebar a.nav-item.active")).toHaveText("Projects");
});

test("a clip opens in the editor", async ({ page, request }) => {
  const projects = await getJson<any[]>(request, "/api/projects");
  let clip: any;
  for (const p of projects.filter((x) => x.clip_count > 0)) {
    clip = (await getJson(request, `/api/projects/${p.id}`)).clips?.find((c: any) => c.status === "ready");
    if (clip) break;
  }
  test.skip(!clip, "no ready clip in the library");

  await page.goto(`/#/clip/${clip.id}`);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(clip.title);
  await expect(page.getByRole("button", { name: "Save", exact: true })).toBeVisible();
});

test("an unknown project shows an error instead of crashing", async ({ page }) => {
  await page.goto("/#/project/e2e-no-such-project");
  await expect(page.getByText("Project not found")).toBeVisible();
});
