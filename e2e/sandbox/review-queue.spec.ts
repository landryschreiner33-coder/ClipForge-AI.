import { expect, Page, test } from "@playwright/test";

// This suite uses the disposable sandbox. Every mutation is intercepted before reaching even its fake accounts.
const channel = { configured: true, connected: true, needs_reconnect: false, name: "Review test channel",
  account_id: "controlled-review-channel", verified: true, scopes: [], restriction: "" };
const plannedAt = Math.floor(Date.now() / 1000) + 3600;
const item = (changes: Record<string, unknown> = {}) => ({
  id: "controlled-review-post", platform: "youtube", clip_id: "controlled-review-clip", status: "awaiting_approval",
  title: "A complete story", description: "A complete story with a clear ending", tags: [], privacy: "public",
  planned_at: plannedAt, local_time: "", status_note: "Planned for your review. Nothing uploads until you approve.",
  options: { made_for_kids: false }, approval: {}, approval_valid: false, audit: [],
  audience: { intent: "PUBLIC", visibility: "public", group: "public", group_version: 5 },
  audience_label: "Public audience", metadata_options: [], trend: null, publication: null,
  clip: { id: "controlled-review-clip", title: "A complete story", duration: 30, score: 85, status: "ready",
    has_thumbnail: false, video_url: "", thumbnail_url: "", caption_text: "A complete story" },
  source: { id: "controlled-review-source", title: "Source with no recorded reuse permission", channel: "Test creator",
    rights_status: "MANUAL", rights_label: "No recorded permission" },
  reuse_review: { required: true, confirmed: false, basis: "", status: "MANUAL",
    explanation: "No current recorded permission covers this post. Check that you can reuse it before approving." },
  quality: { status: "passed", warnings: [], blockers: [], checks: [], checked_at: 100,
    sha256: "controlled-file-fingerprint", coverage: {}, text_status: "passed", text_problems: [] },
  ...changes,
});

async function capture(page: Page, name: string) {
  if (!process.env.CLIPFOUNDRY_REVIEW_SHOTS) return;
  await expect(page.locator(".toast")).toHaveCount(0); // Capture the reviewed state after earlier form reminders clear.
  if (name === "post-reuse-review") {
    const panel = page.getByRole("region", { name: "Check reuse before approving", exact: true });
    await panel.evaluate(element => element.scrollIntoView({ block: "center" }));
    await panel.screenshot({ path: `${process.env.CLIPFOUNDRY_REVIEW_SHOTS}/reuse-review-fields.png` });
    await page.screenshot({ path: `${process.env.CLIPFOUNDRY_REVIEW_SHOTS}/${name}.png` });
    return;
  }
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({ path: `${process.env.CLIPFOUNDRY_REVIEW_SHOTS}/${name}.png`, fullPage: true });
}

async function controlled(page: Page, initialStatus: any, post = item(), autoPublish = true) {
  const writes: { path: string; body: any }[] = [], errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  await page.route("**/api/**", async route => {
    const request = route.request(), path = new URL(request.url()).pathname;
    if (request.method() !== "GET") {
      writes.push({ path, body: request.postDataJSON() });
      return route.fulfill({ status: 409, json: { detail: "Controlled review preview. No post was approved or uploaded." } });
    }
    if (path === "/api/autopilot/status") {
      const status = structuredClone(initialStatus);
      status.platforms.youtube = channel;
      status.settings.autopilot_review_before_publish = true;
      status.enabled = true; status.paused = false; status.workers_alive = true;
      status.home.setup.started = true;
      status.home.currently = "Prepared posts are waiting for your review in Queue.";
      status.home.next = "Open Queue to check reuse and approve each post.";
      status.home.posts = { ...status.home.posts, ready: 0, scheduled: 1, review: 1 };
      status.home.upcoming = [{ id: post.id, title: post.title, platform: post.platform,
        planned_at: post.planned_at, status: post.status, auto: false, on_platform: false }];
      status.home.posting = { finished: 1, checked: 1, sampled: false, platforms: [{
        platform: "youtube", code: "review", title: "Prepared posts need your review",
        detail: "Check reuse, the video, text and audience in Queue. No clip uploads before your approval.",
        link: "#/queue/review", automatic: false,
        counts: { preparing: 0, checking: 0, failed_check: 0, local_only: 0, ready: 0, scheduled: 0,
          planned_for_review: 1, review: 1 },
      }] };
      return route.fulfill({ json: status });
    }
    if (path === "/api/publish/accounts") return route.fulfill({ json: {
      youtube: channel, tiktok: { configured: false, connected: false, needs_reconnect: false, name: "", scopes: [] },
    } });
    if (path === "/api/autopilot/auto-publish") return route.fulfill({ json: {
      review_before_publish: true, youtube: { supported: true, enabled: false, can_enable: false,
        blocker: "Review mode waits for your approval", consent: { text: "Old permission remains recorded",
          settings: { visibility: "public" } } },
      tiktok: { supported: false, enabled: false, consent: null, note: "Your OK on each post" },
      channel: channel.name, timezone: "UTC", defaults: { daily_limit: 0, start_hour: 0, end_hour: 24 },
    } });
    if (path === "/api/autopilot/scheduled") return route.fulfill({ json: {
      items: new URL(request.url()).searchParams.get("view") === "history" ? [] : [post],
      timezone: "UTC", auto_publish: autoPublish, review_before_publish: true, counts: {},
    } });
    if (path === `/api/autopilot/scheduled/${post.id}`) return route.fulfill({ json: {
      item: post, timezone: "UTC", auto_publish: autoPublish, review_before_publish: true,
    } });
    if (path === `/api/clips/${post.clip_id}/versions`) return route.fulfill({ json: { active: "", versions: [] } });
    return route.continue();
  });
  return { writes, errors };
}

test("review mode replaces standing automatic approval with a simple review path", async ({ page, request }) => {
  const status = await (await request.get("/api/autopilot/status")).json();
  const { writes, errors } = await controlled(page, status);
  await page.goto("/#/settings");
  await expect(page.getByText("Prepare & schedule for review", { exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: "Review prepared posts", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: /Turn on automatic publishing/ })).toHaveCount(0);
  await expect(page.getByText("Old permission remains recorded")).toHaveCount(0);
  await page.goto("/#/missions");
  await expect(page.getByText("Finds videos, makes clips, checks them and plans posts. Nothing uploads until you review and approve each post.",
    { exact: true })).toBeVisible();
  const readiness = page.getByRole("region", { name: "Why clips are waiting to post" });
  await expect(readiness.getByText("Prepared posts need your review", { exact: true })).toBeVisible();
  await expect(readiness.getByLabel("YouTube posting stages")).toContainText("1 planned for review");
  await expect(readiness.getByLabel("YouTube posting stages")).toContainText("0 approved & scheduled");
  await capture(page, "missions-review");
  expect(writes).toEqual([]);
  expect(errors).toEqual([]);
});

test("a missing-permission draft appears in the schedule with its time and review status", async ({ page, request }) => {
  const status = await (await request.get("/api/autopilot/status")).json();
  const { writes, errors } = await controlled(page, status);
  await page.goto("/#/queue/scheduled");
  const row = page.locator('.post-row[data-id="controlled-review-post"]');
  await expect(row).toBeVisible();
  await expect(row.getByText("Needs your review", { exact: true })).toBeVisible();
  await expect(row).not.toContainText("Time not chosen yet");
  await expect(row).toContainText("No recorded permission");
  await expect(page.getByText(/have a planned time but cannot upload/)).toBeVisible();
  await capture(page, "queue-scheduled-review");
  await row.getByRole("link", { name: "Review", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Review for YouTube", exact: true })).toBeVisible();
  expect(writes).toEqual([]);
  expect(errors).toEqual([]);
});

test("unknown reuse needs a chosen basis and combined owner consent before exact-post approval",
async ({ page, request }) => {
  const status = await (await request.get("/api/autopilot/status")).json();
  const { writes, errors } = await controlled(page, status);
  await page.goto("/#/post/controlled-review-post");
  await expect(page.getByRole("group", { name: "Why I can reuse it", exact: true })).toContainText(
    "Saved only with this post. It is not added to Brain knowledge or used to teach future clips.");
  const approve = page.getByRole("button", { name: "Approve & schedule upload", exact: true });
  await expect(approve).toHaveAttribute("aria-disabled", "true");
  await page.getByRole("checkbox", { name: /^I watched this video/ }).check();
  await approve.click({ force: true }); // Also check the handler refuses an incomplete review.
  expect(writes).toEqual([]);
  await page.getByRole("radio", { name: "Other permission", exact: true }).check();
  await page.getByRole("textbox", { name: "Permission details", exact: true })
    .fill("The creator agreed in writing to this edit and public YouTube use.");
  const consent = page.getByRole("checkbox", { name: /^I watched this video/ });
  await expect(consent).not.toBeChecked(); // Changing the asserted basis needs a fresh combined review.
  await approve.click({ force: true });
  expect(writes).toEqual([]);
  await expect(consent).toHaveAccessibleName(/I checked I can reuse this clip/);
  await consent.check();
  await expect(approve).toHaveAttribute("aria-disabled", "false");
  await expect(page.getByText(/Your confirmation records your own review/)).toBeVisible();
  await capture(page, "post-reuse-review");
  await approve.click();
  await expect(page.getByRole("status").filter({ hasText: "Controlled review preview" })).toBeVisible();
  expect(writes).toEqual([{ path: "/api/autopilot/scheduled/controlled-review-post/approve", body: {
    title: "A complete story", description: "A complete story with a clear ending", expected_account_id: channel.account_id,
    reuse_confirmed: true, reuse_kind: "custom", reuse_basis: "The creator agreed in writing to this edit and public YouTube use.",
    tags: [], privacy: "public", made_for_kids: false, confirm: true,
  } }]);
  expect(errors).toEqual([]);
});

test("recorded reuse coverage remains distinct from a per-post owner confirmation", async ({ page, request }) => {
  const status = await (await request.get("/api/autopilot/status")).json();
  const post = item({ source: { id: "controlled-review-source", title: "Licensed source", rights_status: "LICENSED",
    rights_label: "Recorded creator agreement" }, reuse_review: { required: false, confirmed: false, basis: "",
    status: "LICENSED", explanation: "Recorded permission covers this platform and use." } });
  const { writes, errors } = await controlled(page, status, post);
  await page.goto("/#/post/controlled-review-post");
  await expect(page.getByText("Recorded creator agreement", { exact: true })).toBeVisible();
  await expect(page.getByRole("group", { name: "Why I can reuse it", exact: true })).toHaveCount(0);
  await expect(page.getByText("Reuse confirmed by you for this exact post", { exact: true })).toHaveCount(0);
  const approve = page.getByRole("button", { name: "Approve & schedule upload", exact: true });
  await expect(approve).toHaveAttribute("aria-disabled", "true");
  await page.getByRole("checkbox", { name: /^I watched this video/ }).check();
  await expect(approve).toHaveAttribute("aria-disabled", "false");
  // An optional TikTok manual package is reviewed too, but approval never claims it uploads through an API.
  await page.route("**/api/autopilot/scheduled/controlled-review-post", async route => {
    if (route.request().method() !== "GET") return route.fallback();
    return route.fulfill({ json: { item: { ...post, platform: "tiktok", privacy: "", options: { mode: "manual" } },
      timezone: "UTC", auto_publish: true, review_before_publish: true } });
  });
  await page.reload();
  await expect(page.getByRole("button", { name: "Approve for TikTok", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Approve & schedule upload", exact: true })).toHaveCount(0);
  await expect(page.getByText(/Nothing is sent to TikTok: you post it in the TikTok app/)).toBeVisible();
  expect(writes).toEqual([]);
  expect(errors).toEqual([]);
});

test("a passed planning time clearly warns that approval can start the next upload check", async ({ page, request }) => {
  const status = await (await request.get("/api/autopilot/status")).json();
  const { writes, errors } = await controlled(page, status, item({ planned_at: Math.floor(Date.now() / 1000) - 60 }));
  await page.goto("/#/post/controlled-review-post");
  await expect(page.getByText(/its planned time has arrived/)).toBeVisible();
  await expect(page.getByText(/on the next publishing check after you approve/)).toBeVisible();
  await expect(page.getByRole("button", { name: "Publish now…", exact: true })).toHaveCount(0);
  expect(writes).toEqual([]);
  expect(errors).toEqual([]);
});

test("editing a post with current owner reuse confirmation requires a new review for its actual approval payload",
async ({ page, request }) => {
  const status = await (await request.get("/api/autopilot/status")).json();
  const post = item({ status: "approved", approval_valid: false,
    approval: { scheme: 3, video_sha256: "controlled-file-fingerprint", hash: "earlier-owner-approval" },
    reuse_review: { required: true, confirmed: true, status: "MANUAL", basis: "Previous owner review of the saved post",
      explanation: "Your reuse confirmation covers the saved post without marking the source as licensed." } });
  const { writes, errors } = await controlled(page, status, post);
  await page.goto("/#/post/controlled-review-post");
  const reuse = page.getByRole("group", { name: "Why I can reuse it", exact: true });
  await expect(reuse).toHaveCount(0);
  await expect(page.getByText("Saved with this post only. It is not Brain knowledge or guidance for future clips.",
    { exact: true })).toBeVisible();
  await page.locator("#rv-title").fill("A complete story again");
  await expect(reuse).toBeVisible();
  const consent = page.getByRole("checkbox", { name: /^I watched this video/ });
  await expect(consent).not.toBeChecked();
  const approve = page.getByRole("button", { name: "Approve & schedule upload", exact: true });
  await expect(approve).toHaveAttribute("aria-disabled", "true");
  await reuse.getByRole("radio", { name: "Other permission", exact: true }).check();
  await reuse.getByRole("textbox", { name: "Permission details", exact: true })
    .fill("The creator's agreement covers this exact edit and revised public YouTube post.");
  await consent.check();
  await expect(approve).toHaveAttribute("aria-disabled", "false");
  await approve.click();
  await expect(page.getByRole("status").filter({ hasText: "Controlled review preview" })).toBeVisible();
  expect(writes).toEqual([{ path: "/api/autopilot/scheduled/controlled-review-post/approve", body: {
    title: "A complete story again", description: "A complete story with a clear ending", expected_account_id: channel.account_id,
    reuse_confirmed: true, reuse_kind: "custom", reuse_basis: "The creator's agreement covers this exact edit and revised public YouTube post.",
    tags: [], privacy: "public", made_for_kids: false, confirm: true,
  } }]);
  expect(errors).toEqual([]);
});

test("disabled dispatch still waits for an explicit Publish now after review", async ({ page, request }) => {
  const status = await (await request.get("/api/autopilot/status")).json();
  const { writes, errors } = await controlled(page, status, item(), false);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/#/post/controlled-review-post");
  await expect(page.getByRole("button", { name: "Approve for YouTube", exact: true })).toBeVisible();
  await expect(page.getByText(/it waits for you to press Publish now/)).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  expect(writes).toEqual([]);
  expect(errors).toEqual([]);
});
