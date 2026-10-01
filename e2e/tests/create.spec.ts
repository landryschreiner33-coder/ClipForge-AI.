import type { Page } from "@playwright/test";
import { expect, getJson, test } from "../fixtures";

// Nothing here uploads or starts processing: "Make clips" is only checked for enabled/disabled, never pressed,
// and the fixture would block the upload anyway.

test.beforeEach(async ({ page }) => {
  await page.goto("/#/create");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Add video");
});

const makeClips = (page: Page) => page.getByRole("button", { name: "Make clips", exact: true });
const videoInput = (page: Page) => page.locator('input[type="file"][accept*=".mp4"]');
const openDetails = async (page: Page, summary: RegExp) => {
  const details = page.locator("details.more", { has: page.locator("summary", { hasText: summary }) });
  if (!(await details.evaluate((d) => (d as HTMLDetailsElement).open))) await details.locator("summary").click();
  return details;
};

test("Make clips stays disabled until a video is chosen", async ({ page }) => {
  await expect(page.getByRole("heading", { name: "Drop a video here" })).toBeVisible();
  await expect(page.locator(".drop")).toContainText("MP4, MOV, MKV, WEBM or M4V");
  await expect(page.getByRole("button", { name: "Choose a video", exact: true })).toBeVisible();
  await expect(makeClips(page)).toBeDisabled();
  await expect(page.getByText("Choose a video, or open “Import from a link instead”.")).toBeVisible();
});

test("a file that is not a video is refused", async ({ page }) => {
  const notes = { name: "notes.txt", mimeType: "text/plain", buffer: Buffer.from("not a video") };
  await videoInput(page).setInputFiles(notes);
  await expect(page.locator(".toast.bad")).toContainText("“notes.txt” isn't a video ClipFoundry can use.");
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

test("a link must start with http:// or https://", async ({ page }) => {
  const details = await openDetails(page, /Import from a link instead/);
  const url = details.getByLabel("Video link");
  await expect(url).toBeVisible();
  await expect(details.getByText(/doesn't get around\s+DRM, paywalls, logins/)).toBeVisible();
  await expect(makeClips(page)).toBeDisabled();

  await url.fill("not a link");
  await expect(details.getByText("Use a link that starts with http:// or https://")).toBeVisible();
  await expect(url).toHaveAttribute("aria-invalid", "true");
  await expect(makeClips(page)).toBeDisabled();

  await url.fill("https://example.com/video");
  await expect(details.getByText("Use a link that starts with http:// or https://")).toHaveCount(0);
  await expect(makeClips(page)).toBeEnabled();

  await url.fill("");
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
