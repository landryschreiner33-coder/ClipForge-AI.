import { expect, getJson, test } from "../fixtures";

// Nothing here uploads or starts processing: CREATE CLIPS is only checked for enabled/disabled, never pressed,
// and the fixture would block the upload anyway.

test.beforeEach(async ({ page }) => {
  await page.goto("/#/create");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Create clips");
});

const createButton = (page: import("@playwright/test").Page) => page.getByRole("button", { name: "CREATE CLIPS", exact: true });
const videoInput = (page: import("@playwright/test").Page) => page.locator('input[type="file"][accept*=".mp4"]');

test("CREATE CLIPS stays disabled until a video is chosen", async ({ page }) => {
  await expect(page.getByRole("heading", { name: "Drag & drop your video here" })).toBeVisible();
  for (const ext of ["MP4", "MOV", "MKV", "WEBM", "M4V"]) {
    await expect(page.locator(".dropzone .formats .badge", { hasText: new RegExp(`^${ext}$`) })).toBeVisible();
  }
  await expect(createButton(page)).toBeDisabled();
});

test("a file that is not a video is refused", async ({ page }) => {
  await videoInput(page).setInputFiles({ name: "notes.txt", mimeType: "text/plain", buffer: Buffer.from("not a video") });
  await expect(page.locator(".toast.bad")).toContainText("Unsupported file type .txt");
  await expect(page.locator(".dropzone")).toBeVisible();
  await expect(createButton(page)).toBeDisabled();
});

test("a chosen video can be swapped before anything is uploaded", async ({ page }) => {
  await videoInput(page).setInputFiles({ name: "e2e-sample.mp4", mimeType: "video/mp4", buffer: Buffer.alloc(2_500_000) });
  const chip = page.locator(".file-chip");
  await expect(chip).toContainText("e2e-sample.mp4");
  await expect(chip).toContainText("2.5 MB");
  await expect(createButton(page)).toBeEnabled();

  await chip.getByRole("button", { name: "Change" }).click();
  await expect(page.locator(".dropzone")).toBeVisible();
  await expect(createButton(page)).toBeDisabled();
});

test("From URL needs an http(s) link", async ({ page }) => {
  await page.getByRole("button", { name: "From URL", exact: true }).click();
  const url = page.getByLabel("Video URL");
  await expect(url).toBeVisible();
  await expect(page.getByText("Only for publicly accessible videos you have the rights to use.")).toBeVisible();
  await expect(createButton(page)).toBeDisabled();

  await url.fill("not a link");
  await expect(createButton(page)).toBeDisabled();
  await url.fill("https://example.com/video");
  await expect(createButton(page)).toBeEnabled();

  await page.getByRole("button", { name: "Upload file", exact: true }).click();
  await expect(page.locator(".dropzone")).toBeVisible();
  await expect(createButton(page)).toBeDisabled();
});

test("the options start from your saved defaults", async ({ page, request }) => {
  const s = await getJson(request, "/api/settings");
  const selected = (option: string) =>
    page.locator(".opt-row", { has: page.getByRole("button", { name: option, exact: true }) }).locator(".segmented button.on");

  if ([3, 5, 10].includes(s.clip_count)) await expect(selected("10")).toHaveText(String(s.clip_count));
  await expect(selected("Aggressive")).toHaveText({ off: "Off", light: "Light", aggressive: "Aggressive" }[s.silence as string]!);
  await expect(selected("Fit (blurred bg)")).toHaveText({ fill: "Fill (crop)", fit: "Fit (blurred bg)" }[s.layout as string]!);
  if (s.tracking !== "manual") {
    await expect(page.locator(".opt-row", { hasText: "Framing" }).locator("select")).toHaveValue(s.tracking);
  }
  await expect(page.getByRole("switch", { name: "Subtle auto-zoom" })).toHaveAttribute("aria-checked", String(!!s.auto_zoom));
  await expect(page.getByRole("switch", { name: "On-screen hook (first seconds)" })).toHaveAttribute("aria-checked", String(!!s.hook_overlay));
});

test("changing options here does not touch your saved settings", async ({ page, request }) => {
  const before = await getJson(request, "/api/settings");
  await page.getByRole("button", { name: "Aggressive", exact: true }).click();
  await page.getByRole("button", { name: "30-90s", exact: true }).click();
  await page.getByRole("switch", { name: "Subtle auto-zoom" }).click();
  await page.goto("/#/");
  expect(await getJson(request, "/api/settings")).toEqual(before);
});
