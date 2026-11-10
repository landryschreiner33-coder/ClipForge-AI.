import { expect, test, type Page } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { mkdtemp } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";

// Make a YouTube video with ClipForge AI (docs/clipforge/VIDEO_SETUP.md): drop in your files, tell it your idea,
// answer or skip its questions, change the plan by talking or by hand, build. Runs in the throwaway sandbox, whose
// transcripts are made up; with no model set up, ClipForge AI's built-in rules answer, so every answer is known.
const ffmpeg = process.env.CLIPFOUNDRY_FFMPEG || "ffmpeg";
let media: { dock: string; drive: string; song: string };

test.beforeAll(async () => {
  const dir = await mkdtemp(path.join(tmpdir(), "clipforge-video-setup-"));
  const video = (name: string, colour: string) => {
    const file = path.join(dir, name);
    execFileSync(ffmpeg, ["-v", "error", "-y", "-f", "lavfi", "-i", `color=c=${colour}:s=320x180:r=10`, "-f", "lavfi",
      "-i", "sine=frequency=220:duration=12", "-t", "12", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
      "-shortest", file]);
    return file;
  };
  const song = path.join(dir, "summer song.m4a");
  execFileSync(ffmpeg, ["-v", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=8", "-c:a", "aac", song]);
  media = { dock: video("dock jump.mp4", "0x2f6f8f"), drive: video("drive up.mp4", "0x6f5f2f"), song };
});

/** Errors thrown by the page (a broken page), not a picture that failed to load. */
function watch(page: Page): string[] {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  page.on("console", (m) => {
    if (m.type() === "error" && !m.text().startsWith("Failed to load resource")) errors.push(m.text());
  });
  return errors;
}

/** One line of the plan, by its label ("Length", "For", "Captions" …). */
const line = (page: Page, label: string) =>
  page.locator(".vs-plan > div").filter({ has: page.locator("dt", { hasText: new RegExp(`^${label}$`) }) }).locator("dd");

async function drop(page: Page, files: string[]) {
  await page.locator('input[type="file"]').first().setInputFiles(files);
  await expect(page.getByText(`${files.length} of ${files.length} uploaded`)).toBeVisible({ timeout: 60_000 });
}

test("drop in files, tell ClipForge AI the idea, answer a question, change the plan and build", async ({ page }) => {
  const errors = watch(page);
  const idea = "Our lake weekend, about 10 minutes. Start with the jump off the dock, then the drive up, and use my " +
    "summer song as the music.";
  // the ClipForge AI chat's "Make a YouTube video" button opens the page with your idea filled in
  await page.goto(`/#/create/video?idea=${encodeURIComponent(idea)}`);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Make a YouTube video");
  await expect(page.locator(".vs-idea textarea")).toHaveValue(idea);
  const go = page.locator(".vs-go button");
  await expect(go).toBeDisabled();
  await drop(page, [media.dock, media.drive, media.song]);
  await expect(page.getByRole("list", { name: "Your files in order" }).getByRole("listitem")).toHaveCount(3);
  await page.locator(".vs-modes label", { hasText: "Ask me questions" }).click();
  await expect(go).toHaveText("Plan it with ClipForge AI");
  await go.click();

  // the planning page: what the built-in rules read, and what they still need to know
  await expect(page).toHaveURL(/#\/create\/video\/vid-[\w-]+$/);
  const planning = page.url();
  await expect(line(page, "Length")).toHaveText("About 10 minutes");
  await expect(line(page, "Opens with")).toHaveText("the jump off the dock");
  await expect(line(page, "Music")).toHaveText("Your summer song.m4a");
  const asks = page.locator(".vs-ask");
  await expect(asks.locator("p")).toHaveText(["Who is it for?", "What should it feel like?"]);

  // a quick answer answers its question; the other one asked with it stays
  await asks.getByRole("button", { name: "Friends and family" }).click();
  await expect(line(page, "For")).toHaveText("Friends and family");
  await expect(asks.locator("p")).toHaveText(["What should it feel like?"]);
  await expect(page.locator(".cfai-msg.ai .vs-text").last()).toContainText("One more question below");

  // talking changes the plan, and the lines it changed light up for a moment
  const say = page.getByLabel("Tell ClipForge AI");
  await say.fill("make it 5 minutes and add captions");
  await say.press("Enter");
  await expect(line(page, "Length")).toHaveText("About 5 minutes");
  await expect(line(page, "Captions")).toHaveText("On");
  await expect(page.locator(".vs-plan > div.is-new")).not.toHaveCount(0);
  await expect(page.locator(".vs-plan > div.is-new")).toHaveCount(0, { timeout: 5_000 });
  await expect(asks).toHaveCount(0);  // moving on in your own words leaves no question to nag

  // a line changed by hand, and the video's name
  await page.getByRole("button", { name: "Change it by hand" }).click();
  const form = page.locator(".vs-form");
  await form.locator("label.field", { hasText: "Name" }).locator("input").fill("Lake Days");
  await form.locator("label.field", { hasText: "Feel" }).locator("select").selectOption("calm");
  await page.getByRole("button", { name: "Save the plan" }).click();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Lake Days");
  await expect(line(page, "Feel")).toHaveText("Calm");

  // nothing is lost when you leave: the draft waits in Projects and opens on this page again
  await page.goto("/#/projects");
  const card = page.locator(`a[href^="#/create/video/vid-"]`, { hasText: "Lake Days" }).first();
  await expect(card).toBeVisible();
  await card.click();
  await expect(page).toHaveURL(planning);
  await expect(line(page, "Captions")).toHaveText("On");

  // a phone: no sideways scrolling
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.locator(".vs-slate")).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBeLessThanOrEqual(0);
  await page.setViewportSize({ width: 1440, height: 900 });

  // build: the editor opens, with the plan beside it; the planning link of a made video opens the editor
  await page.getByRole("button", { name: "Build my video" }).click();
  await expect(page).toHaveURL(/#\/video\/vid-[\w-]+$/, { timeout: 30_000 });
  const plan = page.locator("section", { has: page.locator("#vr-plan") });
  await expect(plan).toBeVisible({ timeout: 60_000 });
  await expect(plan).toContainText("Lake Days");
  await expect(plan).toContainText("About 5 minutes");
  // Back from the editor does not land on the planning page, which would only send you on again
  await page.goBack();
  await expect(page).toHaveURL(/#\/projects$/);
  await page.goForward();
  await expect(page).toHaveURL(/#\/video\/vid-[\w-]+$/);
  await page.goto(planning);
  await expect(page).toHaveURL(/#\/video\/vid-[\w-]+$/);
  expect(errors).toEqual([]);
});

test("Just do it on a question builds with the plan as it is", async ({ page }) => {
  const errors = watch(page);
  await page.goto("/#/create/video");
  await drop(page, [media.dock]);
  await page.locator(".vs-idea textarea").fill("A fishing trip with my brother");
  await page.locator(".vs-modes label", { hasText: "Ask me questions" }).click();
  await page.locator(".vs-go button").click();
  await expect(page).toHaveURL(/#\/create\/video\/vid-/);
  await expect(page.locator(".vs-ask").first()).toBeVisible();
  await page.locator(".vs-just").click();
  await expect(page).toHaveURL(/#\/video\/vid-[\w-]+$/, { timeout: 30_000 });
  await expect(page.locator("#vr-plan")).toBeVisible({ timeout: 60_000 });
  expect(errors).toEqual([]);
});

test("words not sent and plan changes not saved are asked about before they are lost", async ({ page }) => {
  const errors = watch(page);
  await page.goto("/#/create/video");
  await drop(page, [media.dock]);
  await page.locator(".vs-idea textarea").fill("A fishing trip with my brother, about 10 minutes");
  await page.locator(".vs-modes label", { hasText: "Ask me questions" }).click();
  await page.locator(".vs-go button").click();
  await expect(page).toHaveURL(/#\/create\/video\/vid-/);
  const planning = page.url();
  await expect(line(page, "Length")).toHaveText("About 10 minutes");
  // the plan form opened and left as it was: nothing jumps to Minutes, and leaving asks nothing
  await page.getByRole("button", { name: "Change it by hand" }).click();
  const form = page.locator(".vs-form");
  await expect(form).toBeVisible();
  await expect(form.locator(":focus")).toHaveCount(0);
  await page.locator(".crumbs a", { hasText: "Projects" }).click();
  await expect(page).toHaveURL(/#\/projects$/);
  await page.goto(planning);
  // a change in the form is named before you leave
  await page.getByRole("button", { name: "Change it by hand" }).click();
  await form.locator("label.field", { hasText: "Feel" }).locator("select").selectOption("calm");
  await expect(page.locator(".vs-just")).toBeDisabled();  // Just do it waits for the form
  await expect(page.locator(".vs-asks .hint")).toHaveText("Save or cancel your changes to the plan first.");
  await page.locator(".crumbs a", { hasText: "Projects" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toContainText("If you leave now, you lose your changes in the plan form.");
  await dialog.getByRole("button", { name: "Stay" }).click();
  await expect(page).toHaveURL(planning);
  await form.getByRole("button", { name: "Cancel" }).click();
  // Build my video with words typed but not sent: send them first, and they count
  const say = page.getByLabel("Tell ClipForge AI");
  await say.fill("make it 5 minutes");
  await page.getByRole("button", { name: "Build my video" }).click();
  await expect(dialog).toContainText("You wrote a message but did not send it");
  await dialog.getByRole("button", { name: "Send it first" }).click();
  await expect(line(page, "Length")).toHaveText("About 5 minutes");
  await expect(say).toHaveValue("");
  await expect(page).toHaveURL(planning);
  expect(errors).toEqual([]);
});

test("Just do it from the start builds at once, and the choice is remembered for next time", async ({ page }) => {
  const errors = watch(page);
  await page.goto("/#/create/video");
  await drop(page, [media.drive]);
  await page.locator(".vs-idea textarea").fill("energetic, under 5 minutes, no music");
  await page.locator(".vs-modes label", { hasText: "Just do it" }).click();
  await expect(page.locator(".vs-go button")).toHaveText("Build my video");
  await page.locator(".vs-go button").click();
  await expect(page).toHaveURL(/#\/video\/vid-[\w-]+$/, { timeout: 30_000 });
  const plan = page.locator("section", { has: page.locator("#vr-plan") });
  await expect(plan).toBeVisible({ timeout: 60_000 });
  await expect(plan).toContainText("Energetic");
  await expect(plan).toContainText("No music");
  await page.goto("/#/create/video");
  await expect(page.locator(".vs-go button")).toHaveText("Build my video");
  await expect(page.locator(".vs-modes input[type=radio]").nth(1)).toBeChecked();
  expect(errors).toEqual([]);
});
