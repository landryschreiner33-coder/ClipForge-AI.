import type { Page } from "@playwright/test";
import { expect, getJson, test } from "../fixtures";

// Nothing here uploads or starts processing: "Make clips" is only checked for enabled/disabled, never pressed,
// and the fixture would block the upload anyway. Make clips (studio upgrade, section 2) takes a video file or a link;
// a file chosen there uploads at once, so the "choose, look, swap before anything is copied" checks run on
// "Add a video with its transcript", which copies the video only when Make clips is pressed.

const makeClips = (page: Page) => page.getByRole("button", { name: "Make clips", exact: true });
const videoInput = (page: Page) => page.locator('input[type="file"][accept*=".mp4"]');
const openDetails = async (page: Page, summary: RegExp) => {
  const details = page.locator("details.more", { has: page.locator("summary", { hasText: summary }) });
  if (!(await details.evaluate((d) => (d as HTMLDetailsElement).open))) await details.locator("summary").click();
  return details;
};

test.describe("Make clips from a video link", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/#/create/link");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Make clips");
  });

  test("a link is checked as it is typed, and only one video is taken from it", async ({ page }) => {
    const url = page.getByLabel("Link to one video");
    const help = page.locator("#mc-link-help");
    await expect(page.getByText("ClipForge never signs in or uses your browser's cookies.", { exact: false })).toBeVisible();
    await expect(makeClips(page)).toBeDisabled();
    await expect(page.getByText("Paste a link to one video first.")).toBeVisible();

    await url.fill("not a link");
    await expect(help).toContainText("Not a video link.");
    await expect(help).toContainText("Paste a link that starts with https://, or use Video file.");
    await expect(url).toHaveAttribute("aria-invalid", "true");
    await expect(makeClips(page)).toBeDisabled();

    await url.fill("https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=PL123");
    await expect(help).toHaveText(
      "YouTube video dQw4w9WgXcQ. Only this video is downloaded, even if the link names a playlist.");
    await expect(url).toHaveAttribute("aria-invalid", "false");
    await expect(makeClips(page)).toBeEnabled();

    await url.fill("");
    await expect(makeClips(page)).toBeDisabled();
  });

  test("with Video file chosen, Make clips waits for the upload", async ({ page }) => {
    await page.getByRole("radiogroup", { name: "Where the video comes from" }).getByRole("radio", { name: "Video file" })
      .check();
    await expect(page.getByText("Drop a video here")).toBeVisible();
    await expect(page.getByText("Upload a video first.")).toBeVisible();
    await expect(makeClips(page)).toBeDisabled();
  });
});

test.describe("Add a video with its transcript", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/#/create/transcript");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Add a video with its transcript");
  });

  test("Make clips stays disabled until a video is chosen", async ({ page }) => {
    await expect(page.getByRole("heading", { name: "Drop a video here" })).toBeVisible();
    await expect(page.locator(".drop")).toContainText("MP4, MOV, MKV, WEBM or M4V");
    await expect(page.getByRole("button", { name: "Choose a video", exact: true })).toBeVisible();
    await expect(makeClips(page)).toBeDisabled();
    await expect(page.getByText("Choose a video and, if you have one, its transcript file.")).toBeVisible();
    await expect(page.getByRole("link", { name: "Use Make clips → Video link" })).toHaveAttribute("href", "#/create/link");
  });

  test("a file that is not a video is refused", async ({ page }) => {
    const notes = { name: "notes.txt", mimeType: "text/plain", buffer: Buffer.from("not a video") };
    await videoInput(page).setInputFiles(notes);
    await expect(page.locator(".toast.bad")).toContainText("“notes.txt” isn't a video ClipForge can use.");
    await expect(page.locator(".drop")).toBeVisible();
    await expect(makeClips(page)).toBeDisabled();
  });

  test("a chosen video can be swapped before anything is copied", async ({ page }) => {
    const sample = { name: "e2e-sample.mp4", mimeType: "video/mp4", buffer: Buffer.alloc(2_500_000) };
    await videoInput(page).setInputFiles(sample);
    const chip = page.getByRole("region", { name: "Chosen video" });
    await expect(chip).toContainText("e2e-sample.mp4");
    await expect(chip).toContainText("2.5 MB");
    await expect(makeClips(page)).toBeEnabled();

    await chip.getByRole("button", { name: "Choose another", exact: true }).click();
    await expect(page.locator(".drop")).toBeVisible();
    await expect(makeClips(page)).toBeDisabled();
  });

  test("the options start from your saved defaults", async ({ page, request }) => {
    const s = await getJson(request, "/api/settings");
    const details = await openDetails(page, /More options/);
    const choice = (group: string, name: string) =>
      details.getByRole("radiogroup", { name: group }).getByRole("radio", { name, exact: true });

    if (typeof s.clip_count === "number") await expect(choice("Clips at most", String(s.clip_count))).toBeChecked();
    const silence: Record<string, string> = { off: "Off", light: "Light", aggressive: "Strong" };
    if (silence[s.silence]) await expect(choice("Silence cleanup", silence[s.silence])).toBeChecked();
    const layout: Record<string, string> = { fill: "Fill (crop)", fit: "Fit (blurred background)" };
    if (layout[s.layout]) await expect(choice("Layout", layout[s.layout])).toBeChecked();
    if (s.tracking) await expect(details.getByLabel("Framing")).toHaveValue(s.tracking);
    if (s.caption_style) {
      const picked = details.getByRole("radiogroup", { name: "Caption style" }).locator("input:checked");
      if (await picked.count()) await expect(picked).toHaveValue(s.caption_style);
    }
    const zoom = details.getByRole("checkbox", { name: "Subtle auto-zoom" });
    await (s.auto_zoom ? expect(zoom).toBeChecked() : expect(zoom).not.toBeChecked());
    const hook = details.getByRole("checkbox", { name: "On-screen hook in the first seconds" });
    await (s.hook_overlay ? expect(hook).toBeChecked() : expect(hook).not.toBeChecked());
  });

  test("changing options here does not touch your saved settings", async ({ page, request }) => {
    const before = await getJson(request, "/api/settings");
    const details = await openDetails(page, /More options/);
    await details.getByRole("radiogroup", { name: "Silence cleanup" }).getByText("Strong", { exact: true }).click();
    await details.getByRole("radiogroup", { name: "Clip length" }).getByText("30–90 s", { exact: true }).click();
    await details.getByRole("checkbox", { name: "Subtle auto-zoom" }).click();
    await page.goto("/#/");
    expect(await getJson(request, "/api/settings")).toEqual(before);
  });
});
