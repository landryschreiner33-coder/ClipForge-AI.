import { expect, Page, test } from "@playwright/test";

// Only the disposable sandbox is used. Every write is intercepted: no audience answer or upload reaches an account.
const account = { configured: true, connected: true, needs_reconnect: false, name: "Comments test channel",
  account_id: "controlled-comments-channel", verified: true, scopes: [], restriction: "" };
const clip = { id: "comments-clip", project_id: "comments-project", status: "ready", has_video: true,
  title: "A complete story", duration: 30, start: 0, end: 30, score: 85, version: 1, hashtags: [],
  post: { title: "A complete story", caption: "A complete story with a clear ending", hashtags: [] } };
const post = (id: string, changes: Record<string, unknown> = {}) => ({
  id, platform: "youtube", clip_id: clip.id, status: "awaiting_approval", title: clip.title,
  description: clip.post.caption, tags: [], privacy: "public", planned_at: Date.now() / 1000 + 3600,
  local_time: "", status_note: "Planned for review", options: { made_for_kids: false },
  approval: {}, approval_valid: false, audit: [], audience_label: "Everyone (Public)", metadata_options: [],
  audience: { intent: "PUBLIC", visibility: "public", group: "public", group_version: 5 },
  clip: { ...clip, video_url: "", thumbnail_url: "", has_thumbnail: false, caption_text: clip.post.caption },
  source: { id: "comments-source", title: "Controlled source", rights_status: "LICENSED",
    rights_label: "Recorded creator agreement" },
  reuse_review: { required: false, confirmed: false, basis: "", status: "LICENSED",
    explanation: "Recorded permission covers this use." },
  quality: { status: "passed", warnings: [], blockers: [], checks: [], checked_at: 100,
    sha256: "controlled-comments-file", coverage: {}, text_status: "passed", text_problems: [] },
  ...changes,
});

async function controlled(page: Page, options: { private?: boolean; posts?: any[]; publications?: any[] } = {}) {
  const baseline = await (await page.request.get("/api/autopilot/status")).json();
  const posts = options.posts || [post("comments-post")];
  const writes: { path: string; body: any }[] = [], errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  await page.route("**/api/**", async route => {
    const request = route.request(), path = new URL(request.url()).pathname;
    if (request.method() !== "GET") {
      const body = request.postDataJSON();
      writes.push({ path, body });
      if (path === "/api/autopilot/scheduled/bulk-preview") return route.fulfill({ json: {
        token: "controlled-comments-preview", expires_at: Date.now() / 1000 + 600,
        items: body.ids.map((id: string) => {
          const item = posts.find(p => p.id === id);
          return { id, item, eligible: !!item, reason: "", needs_reuse_confirmation: false,
            needs_made_for_kids: item?.options.made_for_kids == null };
        }), eligible_ids: body.ids, reuse_options: [], account: { id: account.account_id, display_name: account.name },
        timezone: "UTC", auto_publish: true,
      } });
      return route.fulfill({ status: 409, json: { detail: "Controlled comments check. No upload was made." } });
    }
    if (path === "/api/autopilot/status") return route.fulfill({ json: {
      ...baseline, platforms: { ...baseline.platforms, youtube: account },
    } });
    if (path === "/api/publish/accounts") return route.fulfill({ json: { youtube: account,
      tiktok: { configured: false, connected: false, needs_reconnect: false, name: "", scopes: [] } } });
    if (path === "/api/audience") return route.fulfill({ json: {
      youtube: { intent: options.private ? "OWNER_ONLY" : "PUBLIC", visibility: options.private ? "private" : "public",
        confirmed: true, label: options.private ? "Only me" : "Everyone (Public)", group_version: 5 },
      tiktok: { intent: "LOCAL_ONLY", confirmed: false, label: "Local clips" },
    } });
    if (path === `/api/clips/${clip.id}`) return route.fulfill({ json: clip });
    if (path === `/api/projects/${clip.project_id}`) return route.fulfill({ json: {
      id: clip.project_id, name: "Controlled source", origin: "manual", clips: [],
    } });
    if (path === `/api/clips/${clip.id}/versions`) return route.fulfill({ json: { active: "", versions: [] } });
    if (path === `/api/clips/${clip.id}/publications`) return route.fulfill({ json: options.publications || [] });
    if (path === "/api/autopilot/scheduled") return route.fulfill({ json: {
      items: new URL(request.url()).searchParams.get("view") === "history" ? [] : posts,
      timezone: "UTC", auto_publish: true, review_before_publish: true,
    } });
    const found = posts.find(p => path === `/api/autopilot/scheduled/${p.id}`);
    if (found) return route.fulfill({ json: { item: found, timezone: "UTC", auto_publish: true,
      review_before_publish: true } });
    if (path.startsWith(`/api/clips/${clip.id}/`)) return route.fulfill({ status: 404, body: "Fixture media" });
    return route.continue();
  });
  return { writes, errors };
}

async function capture(page: Page, name: string) {
  if (process.env.CLIPFOUNDRY_BROWSER_SHOTS) await page.screenshot({
    path: `${process.env.CLIPFOUNDRY_BROWSER_SHOTS}/${name}.png`, fullPage: true,
  });
}

test("manual Public publishing explains the kids choice without promising comments and sends the chosen answer",
async ({ page }) => {
  const { writes, errors } = await controlled(page, { posts: [] });
  await page.goto(`/#/publish/${clip.id}`);
  await expect(page.getByRole("heading", { name: "Prepare post", exact: true })).toBeVisible();
  const group = page.getByRole("group", { name: /Made for kids/ });
  await expect(group.getByRole("radio", { name: "Yes, it's made for kids", exact: true })).not.toBeChecked();
  await expect(group.getByRole("radio", { name: "No, it's not made for kids", exact: true })).not.toBeChecked();
  await expect(group).toContainText("being suitable for all ages alone does not decide this");
  await group.getByRole("radio", { name: "Yes, it's made for kids", exact: true }).check();
  await expect(group).toContainText("Comments will be off: YouTube disables them on videos made for kids.");
  await group.getByRole("radio", { name: "No, it's not made for kids", exact: true }).check();
  await expect(group).toContainText("Channel defaults and YouTube restrictions can still turn comments off");
  await expect(group).not.toContainText("Comments will be off:");
  await page.getByRole("button", { name: "Publish to YouTube now…", exact: true }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  expect(writes).toEqual([]);
  await dialog.getByRole("button", { name: "Publish now", exact: true }).click();
  await expect.poll(() => writes.length).toBe(1);
  expect(writes[0].path).toBe(`/api/clips/${clip.id}/publish/youtube`);
  expect(writes[0].body).toMatchObject({ privacy: "public", made_for_kids: false, confirm: true,
    expected_account_id: account.account_id });
  expect(writes[0].body).not.toHaveProperty("comments_enabled");
  expect(errors).toEqual([]);
});

test("manual Private publishing warns that comments remain off after answering not made for kids", async ({ page }) => {
  const { writes, errors } = await controlled(page, { private: true, posts: [] });
  await page.goto(`/#/publish/${clip.id}`);
  const group = page.getByRole("group", { name: /Made for kids/ });
  await group.getByRole("radio", { name: "No, it's not made for kids", exact: true }).check();
  await expect(group).toContainText("Comments will be off: YouTube does not allow them on Private videos.");
  expect(writes).toEqual([]);
  expect(errors).toEqual([]);
});

test("single scheduled review updates its comment explanation with explicit kids and audience choices", async ({ page }) => {
  const { writes, errors } = await controlled(page);
  await page.goto("/#/post/comments-post");
  const group = page.getByRole("group", { name: /Made for kids/ });
  await expect(group.getByRole("radio", { name: "No, it's not made for kids", exact: true })).toBeChecked();
  await expect(group).toContainText("Channel defaults and YouTube restrictions can still turn comments off");
  await group.getByRole("radio", { name: "Yes, it's made for kids", exact: true }).check();
  await expect(group).toContainText("Comments will be off: YouTube disables them on videos made for kids.");
  await capture(page, "youtube-comments-single-review");
  expect(writes).toEqual([]);
  expect(errors).toEqual([]);
});

test("bulk review preserves individual Private and kids warnings and explains the missing-only common answer",
async ({ page }) => {
  const { writes, errors } = await controlled(page, { posts: [
    post("private", { privacy: "private", audience_label: "Only me" }),
    post("kids", { options: { made_for_kids: true } }), post("missing", { options: {} }),
  ] });
  await page.goto("/#/queue/review");
  await page.getByRole("checkbox", { name: "Select visible YouTube posts", exact: true }).check();
  await page.getByRole("button", { name: /^Approve selected/ }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByText("Comments off on YouTube: Private video.", { exact: true })).toBeVisible();
  await expect(dialog.getByText("Comments off on YouTube: made for kids.", { exact: true })).toBeVisible();
  const group = dialog.getByRole("group", { name: "Made for kids", exact: true });
  await expect(group).toContainText("Existing answers stay unchanged");
  await group.getByRole("radio", { name: "Yes, made for kids", exact: true }).check();
  await expect(group).toContainText("Comments will be off: YouTube disables them on videos made for kids.");
  await group.getByRole("radio", { name: "No, not made for kids", exact: true }).check();
  await expect(group).toContainText("Channel defaults and YouTube restrictions can still turn comments off");
  await expect(dialog.getByText("Comments off on YouTube: Private video.", { exact: true })).toBeVisible();
  await expect(dialog.getByText("Comments off on YouTube: made for kids.", { exact: true })).toBeVisible();
  await capture(page, "youtube-comments-bulk-review");
  expect(writes).toEqual([{ path: "/api/autopilot/scheduled/bulk-preview",
    body: { ids: ["private", "kids", "missing"] } }]);
  expect(errors).toEqual([]);
});

test("completed manual and scheduled posts show YouTube's returned comments restriction instead of claiming enabled",
async ({ page }) => {
  const note = "YouTube reports this video is made for kids, so comments are disabled. Check the audience in YouTube Studio.";
  const publication = { id: "comments-publication", clip_id: clip.id, platform: "youtube", mode: "direct",
    status: "done", progress: 1, title: clip.title, description: clip.post.caption, tags: [],
    requested_privacy: "public", privacy: "public", remote_id: "comments-video", url: "", version_id: "", options: {},
    created_at: Date.now() / 1000, updated_at: Date.now() / 1000, message: "Uploaded", error: "", fix: "",
    info: { youtube_audience: { made_for_kids: true, comments_note: note } },
    audience: { intent: "PUBLIC", visibility: "public" }, delivery: { audience_setup: "public_api_verified" } };
  const { writes, errors } = await controlled(page, { publications: [publication], posts: [
    post("comments-post", { status: "published", publication, delivery_state: "public_api_verified",
      planned_at: Date.now() / 1000 - 60 }),
    post("comments-early", { status: "published", publication, delivery_state: "public_api_verified" }),
  ] });
  await page.goto(`/#/publish/${clip.id}`);
  await expect(page.getByText(note, { exact: false })).toBeVisible();
  await page.goto("/#/post/comments-post");
  await expect(page.getByText(note, { exact: false })).toBeVisible();
  await page.goto("/#/post/comments-early");
  await expect(page.getByText(note, { exact: false })).toBeVisible();
  await capture(page, "youtube-comments-returned-status");
  expect(writes).toEqual([]);
  expect(errors).toEqual([]);
});
