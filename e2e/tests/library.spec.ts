import { expect, getJson, test } from "../fixtures";

// Opens your videos and clips to look at them. Dialogs are opened and then canceled; nothing is deleted, made
// again, saved or rendered (the fixture blocks every write anyway). Tests that need a video or a clip are skipped
// when your library has none.

const BUSY = ["created", "uploading", "queued", "processing"];

async function readyClip(request: Parameters<typeof getJson>[0]) {
  for (const p of (await getJson<any[]>(request, "/api/projects")).filter((x) => x.clip_count > 0)) {
    const clip = (await getJson(request, `/api/projects/${p.id}`)).clips?.find((c: any) => c.status === "ready");
    if (clip) return clip;
  }
  return null;
}

test("Projects lists every clips project and full video", async ({ page, request }) => {
  await page.goto("/#/projects");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Projects");
  await expect(async () => {
    const items = await getJson<any[]>(request, "/api/studio/projects?kind=&q=");
    if (items.length === 0) {
      await expect(page.getByRole("heading", { name: "No projects yet" })).toBeVisible({ timeout: 1000 });
    } else {
      await expect(page.locator(".lib-grid .lib-card")).toHaveCount(items.length, { timeout: 1000 });
    }
  }).toPass();
});

test("the search and the Show choice only filter the page", async ({ page, request }) => {
  const items = await getJson<any[]>(request, "/api/studio/projects?kind=&q=");
  test.skip(items.length === 0, "there are no projects");

  await page.goto("/#/projects");
  await expect(page.locator(".lib-grid .lib-card").first()).toBeVisible();
  await page.getByLabel("Search projects").fill("zz-e2e no project has this name zz");
  await expect(page.getByRole("heading", { name: "Nothing matches that search" })).toBeVisible();
  await page.getByLabel("Search projects").fill("");
  await expect(page.locator(".lib-grid .lib-card")).toHaveCount(items.length);

  const show = page.getByRole("radiogroup", { name: "Show" });
  await show.getByRole("radio", { name: "Clips", exact: true }).check();
  await expect(show.getByRole("radio", { name: "All", exact: true })).not.toBeChecked();
  await expect(page.locator(".lib-grid .lib-card")).toHaveCount(items.filter((i) => i.kind === "clips").length);
  await show.getByRole("radio", { name: "All", exact: true }).check();
  await expect(page.locator(".lib-grid .lib-card")).toHaveCount(items.length);
});

test("Delete asks first, and nothing is deleted when you cancel", async ({ page, request }) => {
  const projects = await getJson<any[]>(request, "/api/projects");
  const idle = projects.find((p) => !BUSY.includes(p.status));
  test.skip(!idle, "no video that can be deleted");

  await page.goto(`/#/project/${idle.id}`);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(idle.name);
  await page.getByRole("button", { name: "More for this video" }).click();
  await page.getByRole("menuitem", { name: /Delete video and clips/ }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toContainText(`Delete “${idle.name}”?`);
  // what goes and what stays, or why it has to wait (Autopilot or a post may be busy with it)
  await expect(dialog.getByText(/^(Deleted for good|It can't be deleted right now)$/)).toBeVisible();
  if (await dialog.getByText("It can't be deleted right now").count() === 0) {
    await expect(dialog.getByRole("heading", { name: "Stays" })).toBeVisible();
    await expect(dialog.getByRole("button", { name: "Delete project" })).toBeVisible();
  }
  await dialog.getByRole("button", { name: /^(Keep it|Close)$/ }).click();
  await expect(dialog).toHaveCount(0);
  await expect(page).toHaveURL(new RegExp(`#/project/${idle.id}$`));
  expect((await getJson<any[]>(request, "/api/projects")).some((p) => p.id === idle.id)).toBe(true);
});

test("the trash button on Projects asks first, and Keep it deletes nothing", async ({ page, request }) => {
  const items = await getJson<any[]>(request, "/api/studio/projects?kind=&q=");
  test.skip(items.length === 0, "there are no projects");
  const first = items[0];

  await page.goto("/#/projects");
  await page.getByRole("button", { name: `Delete ${first.name}`, exact: true }).first().click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toContainText(`Delete “${first.name}”?`);
  await expect(dialog.getByText(/^(Deleted for good|It can't be deleted right now)$/)).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);
  expect((await getJson<any[]>(request, "/api/studio/projects?kind=&q=")).some((i) => i.id === first.id)).toBe(true);
});

test("a video opens from Projects", async ({ page, request }) => {
  const projects = await getJson<any[]>(request, "/api/projects");
  test.skip(projects.length === 0, "there are no clips projects");
  const p = projects[0];

  await page.goto("/#/projects");
  await page.locator(`.lib-card[href="#/project/${p.id}"]`).click();
  await expect(page).toHaveURL(new RegExp(`#/project/${p.id}$`));
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(p.name);
  await expect(page.locator(".page-head .kind-label")).toHaveText("Source video");
  await expect(page.locator(".page-head").getByRole("link", { name: "Projects" })).toBeVisible();
});

test("Make clips again asks first and can be canceled", async ({ page, request }) => {
  const projects = await getJson<any[]>(request, "/api/projects");
  const ready = projects.find((p) => p.status === "ready");
  test.skip(!ready, "no finished video");

  await page.goto(`/#/project/${ready.id}`);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(ready.name);
  await page.getByRole("button", { name: "More for this video" }).click();
  await page.getByRole("menuitem", { name: /Make clips again/ }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);
});

test("a clip opens in the editor, and leaving with an unsaved change asks first", async ({ page, request }) => {
  const clip = await readyClip(request);
  test.skip(!clip, "no ready clip in the library");

  // Arrive from Projects so Back has somewhere to go.
  await page.goto("/#/projects");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Projects");
  await page.evaluate((id) => { window.location.hash = `#/clip/${id}`; }, clip.id);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(clip.title);
  const save = page.getByRole("button", { name: "Save", exact: true });
  await expect(save).toBeVisible();
  await expect(save).toBeDisabled();
  for (const tab of ["Trim", "Captions", "Layout", "Audio", "Post text"]) {
    await expect(page.getByRole("tab", { name: new RegExp(`^${tab}`) })).toBeVisible();
  }

  // An unsaved change in the page only (never saved): the zoom slider.
  await page.getByRole("tab", { name: /^Layout/ }).click();
  const zoom = page.getByLabel(/^Zoom/);
  await zoom.focus();
  await page.keyboard.press(Number(await zoom.inputValue()) >= 2 ? "ArrowLeft" : "ArrowRight");
  await expect(page.locator(".savebar")).toContainText("Unsaved changes: Layout");
  await expect(page.locator(".savebar")).toContainText("doesn't render");
  await expect(save).toBeEnabled();

  // Browser Back asks first; Stay keeps the change.
  await page.goBack();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toContainText("Leave without saving?");
  await expect(dialog).toContainText("You changed the layout.");
  await dialog.getByRole("button", { name: "Stay" }).click();
  await expect(dialog).toHaveCount(0);
  await expect(page).toHaveURL(new RegExp(`#/clip/${clip.id}$`));
  await expect(page.locator(".savebar")).toContainText("Unsaved changes: Layout");

  // A link asks too; Discard and leave forgets the change without saving anything.
  await page.getByRole("navigation").getByRole("link", { name: /^Projects$/ }).first().click();
  await expect(dialog).toContainText("Leave without saving?");
  await dialog.getByRole("button", { name: "Discard and leave" }).click();
  await expect(page).toHaveURL(/#\/projects$/);
});

test("an unknown video or clip shows a message instead of crashing", async ({ page }) => {
  await page.goto("/#/project/e2e-no-such-project");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("This video isn't in your library");
  await page.goto("/#/clip/e2e-no-such-clip");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("This clip isn't in your library");
});
