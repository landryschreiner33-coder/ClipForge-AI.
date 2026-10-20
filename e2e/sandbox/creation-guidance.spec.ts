import { expect, test } from "@playwright/test";

// All mutations are intercepted before reaching even the disposable sandbox's fake accounts.
test("a source reuse declaration carries through Queue and ordinary title edits", async ({ page }) => {
  const baseline = await (await page.request.get("/api/autopilot/status")).json();
  const account = { configured: true, connected: true, account_id: "test-channel", name: "My test channel",
    needs_reconnect: false, scopes: [], restriction: "" };
  const post = {
    id: "creation-post", clip_id: "creation-clip", platform: "youtube", status: "awaiting_approval",
    title: "A complete story", description: "A complete story with a clear ending", tags: [], privacy: "private",
    options: { made_for_kids: false }, planned_at: Date.now() / 1000 + 3600, timezone: "America/Chicago",
    status_note: "The submitted video already has reuse authorization. Check this clip's final quality.",
    approval: {}, approval_valid: false, audit: [], metadata_options: [], publication: null,
    audience: { intent: "OWNER_ONLY", visibility: "private", group_version: 1 }, audience_label: "Only you",
    clip: { id: "creation-clip", title: "A complete story", duration: 25, score: 85, status: "ready",
      has_thumbnail: false, video_url: "", caption_text: "A complete story" },
    source: { id: "creation-source", title: "My submitted video", rights_status: "MANUAL" },
    reuse_review: { required: true, confirmed: true, confirmed_from: "source_submission", status: "MANUAL",
      basis: "I own the original footage and sound.", explanation: "Reuse recorded when this video was submitted." },
    quality: { status: "passed", warnings: [], blockers: [], checks: [], checked_at: 100, sha256: "test-sha",
      coverage: {}, text_status: "passed", text_problems: [] },
  };
  const writes: string[] = [];
  await page.route("**/api/**", async route => {
    const request = route.request(), path = new URL(request.url()).pathname;
    if (request.method() !== "GET") {
      writes.push(path);
      return route.fulfill({ status: 409, json: { detail: "Controlled preview; nothing was saved or uploaded." } });
    }
    if (path === "/api/autopilot/status") return route.fulfill({ json: {
      ...baseline, platforms: { ...baseline.platforms, youtube: account },
    } });
    if (path === "/api/autopilot/scheduled/creation-post") return route.fulfill({ json: {
      item: post, timezone: "America/Chicago", auto_publish: true, review_before_publish: true,
    } });
    if (path === "/api/autopilot/scheduled") return route.fulfill({ json: {
      items: [post], timezone: "America/Chicago", counts: {}, auto_publish: true, review_before_publish: true,
    } });
    if (path === "/api/publish/accounts") return route.fulfill({ json: {
      youtube: account, tiktok: { connected: false, configured: false, scopes: [] },
    } });
    if (path.endsWith("/creation-clip/versions")) return route.fulfill({ json: { active: "", versions: [] } });
    return route.continue();
  });
  await page.goto("/#/post/creation-post");
  await expect(page.getByRole("heading", { name: "Review for YouTube", exact: true })).toBeVisible();
  const reuse = page.getByRole("region", { name: "Check reuse before approving", exact: true });
  await expect(reuse).toHaveCount(0);
  await page.getByRole("textbox", { name: /^Title/ }).fill("A complete story with a clear ending");
  await expect(reuse).toHaveCount(0);
  await expect(page.getByText("I own the original footage and sound.", { exact: true })).toBeVisible();
  // A later destination change remains a new decision; source authorization cannot silently cover it.
  await expect(page.getByRole("button", { name: /Approve/ }).first()).toBeVisible();
  expect(writes).toEqual([]);
});

test("the editor shows actual saved Brain ranking provenance", async ({ page }) => {
  const lesson = { knowledge_id: "lesson", revision: 2, snapshot: { title: "Standalone moments" },
    decisions: { ranking_priorities: { before: [], after: ["standalone"] } } };
  const clip = { id: "guidance-clip", project_id: "guidance-project", rank: 0, start: 0, end: 25, duration: 25,
    title: "How bread rises", caption_text: "Bread rises because yeast releases gas.", hook: "", hooks_alt: [],
    hashtags: [], category: "Education", score: 80, scores: {}, score_source: "local", reason: "Complete idea",
    edit: {}, status: "ready", progress: 1, error: "", selected: 1, render_info: {},
    analysis: { brain_knowledge: [lesson] }, post: {}, active_version: "", has_video: false,
    has_thumbnail: false, version: 1 };
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  await page.route("**/api/**", async route => {
    const request = route.request(), path = new URL(request.url()).pathname;
    if (request.method() !== "GET") return route.fulfill({ status: 409, json: { detail: "Preview only" } });
    if (path === "/api/clips/guidance-clip") return route.fulfill({ json: clip });
    if (path === "/api/projects/guidance-project") return route.fulfill({ json: {
      id: "guidance-project", name: "Baking bread", origin: "manual", status: "ready", duration: 25,
      width: 640, height: 360, fps: 24, info: {}, options: {}, clips: [clip], has_source: false,
    } });
    if (path.endsWith("/guidance-clip/versions")) return route.fulfill({ json: { active: "", versions: [] } });
    if (path.endsWith("/guidance-clip/words")) return route.fulfill({ status: 404, json: { detail: "No words" } });
    return route.continue();
  });
  await page.goto("/#/clip/guidance-clip");
  await expect(page.getByTestId("clip-brain-guidance")).toContainText("Standalone moments (revision 2)");
  await expect(page.getByTestId("clip-brain-guidance").getByRole("link", { name: "Open Brain" })).toBeVisible();
  expect(errors).toEqual([]);
});
