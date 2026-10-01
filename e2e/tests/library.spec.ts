import type { Page } from "@playwright/test";
import { expect, getJson, test } from "../fixtures";

// Opens your videos and clips to look at them. Dialogs are opened and then canceled; nothing is deleted, made
// again, saved or rendered (the fixture blocks every write anyway). Tests that need a video or a clip are skipped
// when your library has none.

const BUSY = ["created", "uploading", "queued", "processing"];
const card = (page: Page, id: string) => page.locator(".pcard", { has: page.locator(`[id="pc-${id}"]`) });

async function readyClip(request: Parameters<typeof getJson>[0]) {
  for (const p of (await getJson<any[]>(request, "/api/projects")).filter((x) => x.clip_count > 0)) {
    const clip = (await getJson(request, `/api/projects/${p.id}`)).clips?.find((c: any) => c.status === "ready");
    if (clip) return clip;
  }
  return null;
}

test("the library lists every video", async ({ page, request }) => {
  await page.goto("/#/library");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Library");
  await expect(async () => {
    const projects = await getJson<any[]>(request, "/api/projects");
    if (projects.length === 0) {
      await expect(page.getByRole("heading", { name: "Your library is empty" })).toBeVisible({ timeout: 1000 });
      await expect(page.getByRole("button", { name: "Open videos folder" })).toBeVisible({ timeout: 1000 });
      await expect(page.getByText("put videos you made in your videos folder")).toBeVisible({ timeout: 1000 });
    } else {
      await expect(page.locator(".grid-cards .pcard")).toHaveCount(projects.length, { timeout: 1000 });
    }
  }).toPass();
});

test("the name filter and the chips only filter the page", async ({ page, request }) => {
  const projects = await getJson<any[]>(request, "/api/projects");
  test.skip(projects.length === 0, "the library is empty");

  await page.goto("/#/library");
  await expect(page.locator(".grid-cards .pcard").first()).toBeVisible();
  const all = await page.locator(".grid-cards .pcard").count();
  await page.getByLabel("Find a video by name").fill("zz-e2e no video has this name zz");
  await expect(page.getByText("No video matches.")).toBeVisible();
  await page.getByRole("button", { name: "Show all videos" }).click();
  await expect(page.locator(".grid-cards .pcard")).toHaveCount(all);

  const chips = page.getByRole("group", { name: "Show" });
  await chips.getByRole("button", { name: /^Ready/ }).click();
  await expect(chips.getByRole("button", { name: /^Ready/ })).toHaveAttribute("aria-pressed", "true");
  await expect(chips.getByRole("button", { name: /^All/ })).toHaveAttribute("aria-pressed", "false");
  await chips.getByRole("button", { name: /^All/ }).click();
  await expect(page.locator(".grid-cards .pcard")).toHaveCount(all);
});

test("Delete asks first, and nothing is deleted when you cancel", async ({ page, request }) => {
  const projects = await getJson<any[]>(request, "/api/projects");
  const idle = projects.find((p) => !BUSY.includes(p.status));
  test.skip(!idle, "no video that can be deleted");

  await page.goto("/#/library");
  await card(page, idle.id).getByRole("button", { name: `More for ${idle.name}` }).click();
  await page.getByRole("menuitem", { name: /Delete video and clips/ }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toContainText(`Delete “${idle.name}”?`);
  await expect(dialog.getByRole("button", { name: /^Delete video/ })).toBeVisible();
  await dialog.getByRole("button", { name: "Cancel" }).click();
  await expect(dialog).toHaveCount(0);
  await expect(page).toHaveURL(/#\/library$/);
  expect((await getJson<any[]>(request, "/api/projects")).some((p) => p.id === idle.id)).toBe(true);
});

test("a video opens from the library", async ({ page, request }) => {
  const projects = await getJson<any[]>(request, "/api/projects");
  test.skip(projects.length === 0, "the library is empty");
  const p = projects[0];

  await page.goto("/#/library");
  await card(page, p.id).getByRole("link", { name: p.name }).click();
  await expect(page).toHaveURL(new RegExp(`#/project/${p.id}$`));
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(p.name);
  await expect(page.locator(".page-head .kind-label")).toHaveText("Source video");
  await expect(page.getByRole("link", { name: /^Library$/ }).first()).toBeVisible();
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

  // Arrive from the Library so Back has somewhere to go.
  await page.goto("/#/library");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Library");
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
  await page.getByRole("navigation").getByRole("link", { name: /^Library$/ }).first().click();
  await expect(dialog).toContainText("Leave without saving?");
  await dialog.getByRole("button", { name: "Discard and leave" }).click();
  await expect(page).toHaveURL(/#\/library$/);
});

test("an unknown video or clip shows a message instead of crashing", async ({ page }) => {
  await page.goto("/#/project/e2e-no-such-project");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("This video isn't in your library");
  await page.goto("/#/clip/e2e-no-such-clip");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("This clip isn't in your library");
});
