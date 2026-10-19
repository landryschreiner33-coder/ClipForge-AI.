import { expect, Page, test } from "@playwright/test";

// Disposable sandbox only. Every mutation is intercepted, including multipart files; no upload reaches an account.
const account = { configured: true, connected: true, needs_reconnect: false, name: "Submitted video test channel",
  account_id: "submitted-test-channel", verified: true, scopes: [], restriction: "" };
const setup = (changes: Record<string, unknown> = {}) => ({
  account_id: account.account_id, account_name: account.name, connected: true,
  audience: { confirmed: true, group_version: 9, label: "Only you", detail: "Uploaded as Private." },
  privacy: "private", can_upload: true, blocker: "", input_mode: "submitted",
  reuse_bases: [
    { id: "owned", label: "My original video", text: "I own this video and all included material." },
    { id: "permission", label: "I have permission", text: "Permission covers this use and all included audio." },
    { id: "legal_exception", label: "Other lawful basis", text: "I checked the basis for this use." },
  ], ...changes,
});
const video = (changes: Record<string, any> = {}) => ({
  id: "submitted-source", title: "My submitted source", url: "https://example.com/my-video", platform: "url",
  kind: "recorded", live_status: "", status: "analyzed", status_label: "Clips prepared", detail: "Final checks are running.",
  progress: 0, project_id: "submitted-project", added_at: 100, scheduled_at: null,
  can_cancel: false, can_retry: false, can_remove: false, can_prioritize: false,
  submission: { id: "submitted-grant", auto_upload: true, account_id: account.account_id, privacy: "private",
    made_for_kids: false, created_at: 100, status: "waiting",
    progress: { clips_ready: 2, posts_waiting: 2, posts_uploading: 0, posts_uploaded: 0, posts_failed: 0 } }, ...changes,
});

async function controlled(page: Page, config: { setup?: ReturnType<typeof setup>; videos?: any[]; reject?: string } = {}) {
  const baseline = await (await page.request.get("/api/autopilot/status")).json();
  const state = { setup: config.setup || setup(), videos: config.videos || [],
    writes: [] as { path: string; body: any; header: string | undefined }[], errors: [] as string[], setupReads: 0 };
  page.on("pageerror", error => state.errors.push(error.message));
  await page.route("**/api/**", async route => {
    const request = route.request(), path = new URL(request.url()).pathname;
    if (request.method() !== "GET") {
      const isFile = path === "/api/autopilot/submissions/file";
      state.writes.push({ path, body: isFile ? request.postData() : request.postDataJSON(),
        header: request.headers()["x-clipfoundry"] });
      if (["/api/autopilot/submissions/file", "/api/autopilot/submissions/link"].includes(path)) {
        if (config.reject) return route.fulfill({ status: 409, json: { detail: config.reject,
          fix: "Check the current account and submit again." } });
        const row = video();
        state.videos = [row];
        return route.fulfill({ json: { item: row, submission: row.submission, already_added: false } });
      }
      return route.fulfill({ status: 409, json: { detail: "Unexpected browser-test mutation refused." } });
    }
    if (path === "/api/autopilot/status") return route.fulfill({ json: {
      ...baseline, enabled: true, paused: false, settings: { ...baseline.settings, autopilot_input_mode: "submitted" },
      platforms: { ...baseline.platforms, youtube: account }, home: {
        ...baseline.home, currently: "Waiting for a video from you", needs_you: [], working: null,
        next: "Add a video link or file in Missions", discovery: { ...baseline.home.discovery, problems: [] },
      },
    } });
    if (path === "/api/autopilot/submissions/setup") {
      state.setupReads++;
      return route.fulfill({ json: state.setup });
    }
    if (path === "/api/autopilot/submissions") return route.fulfill({ json: state.videos });
    return route.continue();
  });
  await page.goto("/#/missions");
  const panel = page.getByRole("region", { name: "Add a video", exact: true });
  await expect(panel.getByText(account.name, { exact: true }).first()).toBeVisible();
  const submit = panel.getByRole("button", { name: "Make & upload clips", exact: true });
  const agree = panel.getByRole("checkbox");
  return { state, panel, submit, agree };
}

async function allowSource(panel: ReturnType<Page["getByRole"]>) {
  await panel.getByRole("radio", { name: "No, not made for kids", exact: true }).check();
  await panel.getByRole("radio", { name: "My original video", exact: true }).check();
  await panel.getByRole("checkbox").check();
}

async function capture(page: Page, name: string) {
  if (!process.env.CLIPFOUNDRY_BROWSER_SHOTS) return;
  await page.evaluate(() => window.scrollTo(0, 0));
  await expect.poll(() => page.evaluate(() => window.scrollY)).toBe(0);
  await page.screenshot({
    path: `${process.env.CLIPFOUNDRY_BROWSER_SHOTS}/${name}.png`, fullPage: true,
  });
}

test("a new link uses explicit source-only upload choices without changing review mode or Brain", async ({ page }) => {
  const { state, panel, submit, agree } = await controlled(page);
  await expect(panel).toContainText("No search API key is needed.");
  await expect(page.getByRole("heading", { name: "Add a video or stream", exact: true })).toHaveCount(0);
  await expect(panel.getByRole("radio", { name: "No, not made for kids", exact: true })).not.toBeChecked();
  await expect(panel.getByRole("radio", { name: "Yes, made for kids", exact: true })).not.toBeChecked();
  await panel.getByRole("textbox", { name: "Video link", exact: true }).fill("https://example.com/my-video");
  await expect(submit).toBeDisabled();
  await allowSource(panel);
  await expect(agree).toBeChecked();
  await expect(submit).toBeEnabled();
  await expect(panel).toContainText("not saved in Brain knowledge");
  await capture(page, "submitted-video-source-consent");
  await submit.click();
  await expect.poll(() => state.writes.length).toBe(1);
  expect(state.writes).toEqual([{ path: "/api/autopilot/submissions/link", header: "1", body: {
    url: "https://example.com/my-video", auto_upload: true, account_id: account.account_id,
    privacy: "private", made_for_kids: false, audience_version: 9, reuse_basis: "owned", reuse_statement: "", agreed: true,
  } }]);
  await expect(panel.getByRole("article", { name: "My submitted source", exact: true })).toContainText("Waiting to upload");
  await expect(panel.getByRole("textbox", { name: "Video link", exact: true })).toBeEmpty();
  await expect(agree).not.toBeChecked();
  expect(state.errors).toEqual([]);
});

test("changing the video, kids answer or reuse basis requires a fresh source confirmation", async ({ page }) => {
  const { state, panel, submit, agree } = await controlled(page);
  const url = panel.getByRole("textbox", { name: "Video link", exact: true });
  await url.fill("https://example.com/first");
  await allowSource(panel);
  await expect(submit).toBeEnabled();
  await url.fill("https://example.com/second");
  await expect(agree).not.toBeChecked();
  await expect(submit).toBeDisabled();
  await agree.check();
  await panel.getByRole("radio", { name: "Yes, made for kids", exact: true }).check();
  await expect(agree).not.toBeChecked();
  await agree.check();
  await panel.getByRole("radio", { name: "I have permission", exact: true }).check();
  await expect(agree).not.toBeChecked();
  await expect(submit).toBeDisabled();
  expect(state.writes).toEqual([]);
  expect(state.errors).toEqual([]);
});

test("create-only file submission needs no publishing agreement or kids answer", async ({ page }) => {
  const { state, panel } = await controlled(page);
  await panel.getByRole("radio", { name: "Video file", exact: true }).check();
  await panel.locator('input[type="file"]').setInputFiles({
    name: "my-original.mp4", mimeType: "video/mp4", buffer: Buffer.from("controlled inert video fixture"),
  });
  await panel.getByRole("radio", { name: /Make clips only/ }).check();
  await expect(panel.getByRole("checkbox")).toHaveCount(0);
  await panel.getByRole("button", { name: "Make clips on this PC", exact: true }).click();
  await expect.poll(() => state.writes.length).toBe(1);
  const write = state.writes[0];
  expect(write.path).toBe("/api/autopilot/submissions/file");
  expect(write.header).toBe("1");
  expect(write.body).toContain('name="file"; filename="my-original.mp4"');
  expect(write.body).toContain('"auto_upload":false');
  expect(write.body).toContain('"made_for_kids":null');
  expect(write.body).toContain('"account_id":""');
  expect(write.body).toContain('"agreed":false');
  await expect(panel).toContainText("without uploading them");
  expect(state.errors).toEqual([]);
});

test("server-side account changes preserve the input and display the refusal without approving anything else", async ({ page }) => {
  const { state, panel, submit } = await controlled(page, { reject: "The connected account changed. Nothing was authorized." });
  const url = panel.getByRole("textbox", { name: "Video link", exact: true });
  await url.fill("https://example.com/my-video");
  await allowSource(panel);
  await submit.click();
  await expect(panel.getByRole("alert")).toContainText("The connected account changed. Nothing was authorized.");
  await expect(url).toHaveValue("https://example.com/my-video");
  expect(state.writes.map(write => write.path)).toEqual(["/api/autopilot/submissions/link"]);
  expect(state.errors).toEqual([]);
});

test("source progress distinguishes finished renders, pending uploads and actual returned uploads", async ({ page }) => {
  const uploading = video({ id: "second-source", title: "Second submitted source", status_label: "Making clips",
    submission: { ...video().submission, status: "uploading", progress: {
      clips_ready: 3, posts_waiting: 1, posts_uploading: 1, posts_uploaded: 1, posts_failed: 0,
    } } });
  const { state, panel } = await controlled(page, { videos: [video(), uploading] });
  const waiting = panel.getByRole("article", { name: "My submitted source", exact: true });
  await expect(waiting).toContainText("Waiting to upload");
  await expect(waiting).toContainText("2 clips ready · 2 waiting · 0 uploading · 0 uploaded");
  await expect(waiting.getByText("Uploaded", { exact: true })).toHaveCount(0);
  const active = panel.getByRole("article", { name: "Second submitted source", exact: true });
  await expect(active).toContainText("3 clips ready · 1 waiting · 1 uploading · 1 uploaded");
  await capture(page, "submitted-video-real-progress");
  expect(state.writes).toEqual([]);
  expect(state.errors).toEqual([]);
});

test("public uploads show the current chosen audience and keep a genuine kids choice", async ({ page }) => {
  const { state, panel, submit } = await controlled(page, { setup: setup({ privacy: "public",
    audience: { confirmed: true, group_version: 12, label: "Public audience", detail: "Anyone can watch." } }) });
  await expect(panel).toContainText("Public · anyone can watch");
  await panel.getByRole("textbox", { name: "Video link", exact: true }).fill("https://example.com/my-video");
  await allowSource(panel);
  await expect(panel).toContainText("Channel defaults and YouTube restrictions can still turn comments off");
  await submit.click();
  await expect.poll(() => state.writes.length).toBe(1);
  expect(state.writes[0].body).toMatchObject({ privacy: "public", made_for_kids: false, audience_version: 12 });
  expect(state.errors).toEqual([]);
});

test("small screens keep link, audience and submit controls reachable without horizontal overflow", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const { state, panel, submit } = await controlled(page);
  await panel.getByRole("textbox", { name: "Video link", exact: true }).fill("https://example.com/my-video");
  await allowSource(panel);
  await expect(submit).toBeEnabled();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await capture(page, "submitted-video-phone-layout");
  expect(state.writes).toEqual([]);
  expect(state.errors).toEqual([]);
});
