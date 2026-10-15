import { expect, Page, test } from "@playwright/test";

// Every write is intercepted. These checks exercise the built DOM and actual request bodies in a disposable app,
// never the owner's media, saved approvals or accounts. Exact-file/race validation has separate Python coverage.
const account = { configured: true, connected: true, needs_reconnect: false, name: "Batch review channel",
  account_id: "controlled-batch-channel", verified: true, scopes: [], restriction: "" };
const now = () => Math.floor(Date.now() / 1000);
const options = [
  { value: "owned", label: "My original content",
    basis: "I created this content and have permission for any other material included in this clip." },
  { value: "creator_permission", label: "Creator permission",
    basis: "The creator has given me permission to reuse this content, including the material in this clip." },
  { value: "licensed", label: "License allows this use",
    basis: "I have checked a license that permits this reuse, including any music or other material in this clip." },
  { value: "public_domain", label: "Public domain",
    basis: "I have checked that this content and the material inside this clip are in the public domain." },
  { value: "custom", label: "Other permission", basis: "" },
];
const post = (id: string, changes: Record<string, unknown> = {}) => ({
  id, platform: "youtube", clip_id: `clip-${id}`, status: "awaiting_approval", title: `Story ${id}`,
  description: `Complete description for Story ${id}`, tags: ["story"], privacy: "public", planned_at: now() + 3600,
  local_time: "", status_note: "Planned for review", options: { made_for_kids: false },
  approval: {}, approval_valid: false, audit: [],
  audience: { intent: "PUBLIC", visibility: "public", group: "public", group_version: 5 },
  audience_label: "Everyone (Public)", metadata_options: [], trend: null, publication: null,
  clip: { id: `clip-${id}`, title: `Story ${id}`, duration: 30, score: 85, status: "ready", has_thumbnail: false,
    video_url: `/controlled-media/${id}.mp4`, thumbnail_url: "", caption_text: `Complete story ${id}` },
  source: { id: `source-${id}`, title: `Source ${id}`, channel: "Test creator", rights_status: "MANUAL",
    rights_label: "No recorded permission", url: `https://example.com/source/${id}` },
  reuse_review: { required: true, confirmed: false, basis: "", status: "MANUAL",
    explanation: "Check that you can reuse this clip before approving." },
  quality: { status: "passed", warnings: [], blockers: [], checks: [], checked_at: now(),
    sha256: `controlled-file-${id}`, coverage: {}, text_status: "passed", text_problems: [] },
  ...changes,
});
type FakePost = ReturnType<typeof post>;
type Write = { path: string; body: any };

async function controlled(page: Page, initialStatus: any, initialPosts: FakePost[]) {
  const state = { posts: initialPosts, writes: [] as Write[], errors: [] as string[], previews: 0,
    nextApproval: null as null | { status: number; body: any },
    nextResults: null as null | { id: string; status: "approved" | "skipped"; reason: string }[] };
  page.on("pageerror", error => state.errors.push(error.message));
  await page.route("**/controlled-media/**", route => route.fulfill({ status: 204, contentType: "video/mp4" }));
  await page.route("**/api/**", async route => {
    const request = route.request(), path = new URL(request.url()).pathname;
    if (request.method() !== "GET") {
      const body = request.postDataJSON();
      state.writes.push({ path, body });
      if (path === "/api/autopilot/scheduled/bulk-preview") {
        state.previews++;
        const selected = body.ids.map((id: string) => state.posts.find(p => p.id === id));
        return route.fulfill({ json: { token: `controlled-preview-${state.previews}`, expires_at: now() + 300,
          items: selected.map((p: FakePost | undefined, i: number) => ({ id: body.ids[i], eligible: !!p,
            reason: p ? "" : "Post changed. Refresh the preview.", item: p || null,
            needs_reuse_confirmation: !!p?.reuse_review.required, needs_made_for_kids: p?.options.made_for_kids == null })),
          eligible_ids: selected.filter(Boolean).map((p: FakePost) => p.id),
          account: { id: account.account_id, display_name: account.name }, reuse_options: options, timezone: "UTC" } });
      }
      if (path === "/api/autopilot/scheduled/bulk-approve") {
        if (state.nextApproval) {
          const response = state.nextApproval; state.nextApproval = null;
          return route.fulfill({ status: response.status, json: response.body });
        }
        const previous = [...state.writes].reverse().find(w => w.path.endsWith("/bulk-preview"));
        const results = state.nextResults || previous!.body.ids.map((id: string) => ({ id, status: "approved", reason: "" }));
        state.nextResults = null;
        for (const result of results) if (result.status === "approved") {
          state.posts = state.posts.map(p => p.id === result.id ? { ...p, status: "approved", approval_valid: true } : p);
        }
        return route.fulfill({ json: { results, approved: results.filter(r => r.status === "approved").length,
          skipped: results.filter(r => r.status === "skipped").length } });
      }
      return route.fulfill({ status: 409, json: { detail: "Controlled single review. No real approval or upload." } });
    }
    if (path === "/api/autopilot/status") {
      const status = structuredClone(initialStatus);
      status.platforms.youtube = account;
      status.enabled = true; status.paused = false; status.workers_alive = true;
      status.settings.autopilot_review_before_publish = true;
      status.home.setup.started = true;
      return route.fulfill({ json: status });
    }
    if (path === "/api/publish/accounts") return route.fulfill({ json: { youtube: account,
      tiktok: { configured: false, connected: false, needs_reconnect: false, name: "", scopes: [] } } });
    if (path === "/api/autopilot/scheduled") return route.fulfill({ json: {
      items: new URL(request.url()).searchParams.get("view") === "history" ? [] : state.posts,
      timezone: "UTC", auto_publish: true, review_before_publish: true, counts: {},
    } });
    const found = state.posts.find(p => path === `/api/autopilot/scheduled/${p.id}`);
    if (found) return route.fulfill({ json: { item: found, timezone: "UTC", auto_publish: true,
      review_before_publish: true } });
    if (/\/api\/clips\/[^/]+\/versions$/.test(path)) return route.fulfill({ json: { active: "", versions: [] } });
    return route.continue();
  });
  return state;
}

const select = (page: Page, title: string) => page.getByRole("checkbox", { name: `Select YouTube post: ${title}`, exact: true });
const bulkOpen = (page: Page) => page.getByRole("button", { name: /^Approve selected/ });
const bulkDialog = (page: Page) => page.getByRole("dialog");
const batchAgree = (page: Page) => bulkDialog(page).getByRole("checkbox");
const batchApprove = (page: Page) => bulkDialog(page).getByRole("button", { name: /^Approve (?:\d+|selected)/ });
async function capture(page: Page, name: string) {
  if (process.env.CLIPFOUNDRY_BULK_SHOTS) await page.screenshot({
    path: `${process.env.CLIPFOUNDRY_BULK_SHOTS}/${name}.png`, fullPage: false,
  });
}

test("queue preview stays in place and visible selection excludes TikTok and later arrivals", async ({ page, request }) => {
  const status = await (await request.get("/api/autopilot/status")).json();
  const state = await controlled(page, status, [post("one"), post("two"), post("tiktok", { platform: "tiktok",
    privacy: "", options: { mode: "manual" } }) as FakePost]);
  await page.goto("/#/queue/review");
  await page.getByRole("button", { name: "Preview video: Story one", exact: true }).click();
  const first = page.locator('.post-row[data-id="one"]');
  await expect(first.locator("video")).toBeVisible();
  await expect(first.locator("video")).toHaveAttribute("controls", "");
  await expect(first).toContainText("Complete description for Story one");
  expect(new URL(page.url()).hash).toBe("#/queue/review");
  expect(state.writes).toEqual([]);
  await page.getByRole("checkbox", { name: "Select visible YouTube posts", exact: true }).check();
  await expect(select(page, "Story one")).toBeChecked();
  await expect(select(page, "Story two")).toBeChecked();
  await expect(page.locator('.post-row[data-id="tiktok"]').getByRole("checkbox")).toBeDisabled();
  await expect(page.locator('.post-row[data-id="tiktok"]').getByRole("checkbox")).not.toBeChecked();
  state.posts.push(post("later"));
  await expect(select(page, "Story later")).toBeVisible();
  await expect(select(page, "Story later")).not.toBeChecked();
  await capture(page, "bulk-queue-desktop");
  await bulkOpen(page).click();
  await expect(bulkDialog(page)).toBeVisible();
  await expect.poll(() => state.writes).toEqual([
    { path: "/api/autopilot/scheduled/bulk-preview", body: { ids: ["one", "two"] } },
  ]);
  expect(state.errors).toEqual([]);
});

test("one basis and common kids choice approve only the selected unchanged public and private plans", async ({ page, request }) => {
  const status = await (await request.get("/api/autopilot/status")).json();
  const state = await controlled(page, status, [post("public", { options: {} }), post("private", { privacy: "private",
    audience: { intent: "OWNER_ONLY", visibility: "private", group: "owner", group_version: 5 },
    audience_label: "Only me" })]);
  await page.goto("/#/queue/review");
  await page.getByRole("checkbox", { name: "Select visible YouTube posts", exact: true }).check();
  await bulkOpen(page).click();
  const dialog = bulkDialog(page);
  await expect(dialog.getByRole("heading", { name: "Review 2 YouTube posts", exact: true })).toBeVisible();
  await expect(dialog).toContainText("Public · anyone can watch");
  await expect(dialog).toContainText("Only me");
  await dialog.getByRole("button", { name: "Preview video: Story public", exact: true }).click();
  await dialog.getByRole("button", { name: "Preview video: Story private", exact: true }).click();
  await expect(dialog).toContainText("Complete description for Story public");
  await expect(dialog).toContainText("Complete description for Story private");
  await expect(dialog.locator("video")).toHaveCount(2);
  await expect(batchAgree(page)).not.toBeChecked();
  await expect(dialog.getByRole("radio", { name: /No.*made for kids/i })).not.toBeChecked();
  await dialog.getByRole("radio", { name: /No.*made for kids/i }).check();
  await dialog.getByRole("radio", { name: "Creator permission", exact: true }).check();
  await expect(dialog.getByRole("textbox", { name: "Permission details", exact: true })).toHaveCount(0);
  await batchAgree(page).check();
  await capture(page, "bulk-public-private-review");
  await batchApprove(page).click();
  await expect.poll(() => state.writes.filter(w => w.path.endsWith("/bulk-approve")).length).toBe(1);
  expect(state.writes[1]).toEqual({ path: "/api/autopilot/scheduled/bulk-approve", body: {
    token: "controlled-preview-1", confirm: true, reuse_confirmed: true,
    reuse_kind: "creator_permission", made_for_kids: false,
  } });
  // The bulk request has no privacy, text, tags, planned time, source grant or TikTok fields.
  expect(state.posts.find(p => p.id === "private")!.privacy).toBe("private");
  expect(state.errors).toEqual([]);
});

test("past-due plans warn about dispatch and custom basis still needs the combined consent", async ({ page, request }) => {
  const status = await (await request.get("/api/autopilot/status")).json();
  const state = await controlled(page, status, [post("past", { planned_at: now() - 60 })]);
  await page.goto("/#/queue/review");
  await select(page, "Story past").check();
  await bulkOpen(page).click();
  const dialog = bulkDialog(page);
  await expect(dialog).toContainText("Past due · can start now after approval");
  await expect(dialog).toContainText(/next publishing check|soon after.*approv/i);
  await dialog.getByRole("radio", { name: "Other permission", exact: true }).check();
  await dialog.getByRole("textbox", { name: "Permission details", exact: true })
    .fill("The creator's agreement covers this clip and its planned audience.");
  await expect(batchAgree(page)).not.toBeChecked();
  await expect(batchApprove(page)).toBeDisabled();
  expect(state.writes.filter(w => w.path.endsWith("/bulk-approve"))).toHaveLength(0);
  await batchAgree(page).check();
  await batchApprove(page).click();
  await expect.poll(() => state.writes.length).toBe(2);
  expect(state.writes[1].body).toMatchObject({ token: "controlled-preview-1", confirm: true, reuse_confirmed: true,
    reuse_kind: "custom", reuse_basis: "The creator's agreement covers this clip and its planned audience." });
  expect(state.errors).toEqual([]);
});

test("partial approval preserves skipped posts for a fresh review", async ({ page, request }) => {
  const status = await (await request.get("/api/autopilot/status")).json();
  const state = await controlled(page, status, [post("good"), post("changed")]);
  state.nextResults = [{ id: "good", status: "approved", reason: "" }, { id: "changed", status: "skipped",
    reason: "The video changed. Open a fresh preview and review it again." }];
  await page.goto("/#/queue/review");
  await page.getByRole("checkbox", { name: "Select visible YouTube posts", exact: true }).check();
  await bulkOpen(page).click();
  await bulkDialog(page).getByRole("radio", { name: "My original content", exact: true }).check();
  await batchAgree(page).check();
  await batchApprove(page).click();
  await expect(bulkDialog(page)).toContainText("The video changed. Open a fresh preview and review it again.");
  await bulkDialog(page).getByRole("button", { name: /Close|Done/ }).click();
  await expect(page.locator('.post-row[data-id="good"]')).toHaveCount(0);
  await expect(select(page, "Story changed")).toBeChecked();
  await bulkOpen(page).click();
  await expect(batchAgree(page)).not.toBeChecked();
  expect(state.writes.filter(w => w.path.endsWith("/bulk-approve"))).toHaveLength(1);
  expect(state.errors).toEqual([]);
});

test("an expired or changed preview cannot be approved again without a new preview and consent", async ({ page, request }) => {
  const status = await (await request.get("/api/autopilot/status")).json();
  const state = await controlled(page, status, [post("stale")]);
  state.nextApproval = { status: 409, body: { detail: "Preview expired. Refresh the preview and review it again." } };
  await page.goto("/#/queue/review");
  await select(page, "Story stale").check();
  await bulkOpen(page).click();
  await bulkDialog(page).getByRole("radio", { name: "My original content", exact: true }).check();
  await batchAgree(page).check();
  await batchApprove(page).click();
  await expect(bulkDialog(page)).toContainText("Preview expired. Refresh the preview and review it again.");
  await expect(batchAgree(page)).not.toBeChecked();
  await expect(batchApprove(page)).toBeDisabled();
  await bulkDialog(page).getByRole("button", { name: /Refresh preview/ }).click();
  await expect.poll(() => state.previews).toBe(2);
  await expect(batchAgree(page)).not.toBeChecked();
  expect(state.writes.filter(w => w.path.endsWith("/bulk-approve"))).toHaveLength(1);
  expect(state.errors).toEqual([]);
});

test("mobile keyboard selection is bounded to fifty and stays inside the viewport", async ({ page, request }) => {
  const status = await (await request.get("/api/autopilot/status")).json();
  const state = await controlled(page, status, Array.from({ length: 52 }, (_, i) => post(`bounded-${i + 1}`)));
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/#/queue/review");
  const all = page.getByRole("checkbox", { name: "Select visible YouTube posts", exact: true });
  await all.focus();
  await page.keyboard.press("Space");
  await expect(page.locator('.post-row input[type="checkbox"]:checked')).toHaveCount(50);
  await expect(select(page, "Story bounded-51")).not.toBeChecked();
  await expect(select(page, "Story bounded-51")).toBeDisabled();
  await select(page, "Story bounded-1").focus();
  await page.keyboard.press("Space");
  await expect(select(page, "Story bounded-51")).toBeEnabled();
  await select(page, "Story bounded-51").focus();
  await page.keyboard.press("Space");
  await expect(select(page, "Story bounded-51")).toBeChecked();
  await expect(select(page, "Story bounded-52")).toBeDisabled();
  await expect(page.locator('.post-row input[type="checkbox"]:checked')).toHaveCount(50);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await bulkOpen(page).click();
  await expect(bulkDialog(page).getByRole("heading", { name: "Review 50 YouTube posts", exact: true })).toBeVisible();
  await capture(page, "bulk-mobile-review");
  expect(state.writes[0].body.ids).toHaveLength(50);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  expect(state.errors).toEqual([]);
});

test("single-post presets remove typing but an edit clears the combined approval consent", async ({ page, request }) => {
  const status = await (await request.get("/api/autopilot/status")).json();
  const state = await controlled(page, status, [post("single")]);
  await page.goto("/#/post/single");
  const approve = page.getByRole("button", { name: "Approve & schedule upload", exact: true });
  await page.getByRole("radio", { name: "My original content", exact: true }).check();
  const consent = page.getByRole("checkbox", { name: /I watched this video/ });
  await expect(page.getByRole("textbox", { name: "Permission details", exact: true })).toHaveCount(0);
  await consent.check();
  await expect(approve).toHaveAttribute("aria-disabled", "false");
  await page.locator("#rv-title").fill("Revised Story single");
  await expect(consent).not.toBeChecked();
  await expect(approve).toHaveAttribute("aria-disabled", "true");
  await consent.check();
  await capture(page, "single-preset-review");
  await approve.click();
  await expect.poll(() => state.writes.length).toBe(1);
  expect(state.writes[0].path).toBe("/api/autopilot/scheduled/single/approve");
  expect(state.writes[0].body).toMatchObject({ title: "Revised Story single", expected_account_id: account.account_id,
    reuse_confirmed: true, confirm: true, privacy: "public", made_for_kids: false });
  expect(state.writes[0].body.reuse_kind).toBe("owned");
  expect(state.writes[0].body).not.toHaveProperty("reuse_basis");
  expect(state.errors).toEqual([]);
});

test("quick approval of a covered post needs one consent and keeps review on the Queue", async ({ page, request }) => {
  const status = await (await request.get("/api/autopilot/status")).json();
  const covered = post("covered", { source: { id: "source-covered", title: "Covered source", rights_status: "LICENSED",
    rights_label: "Creator agreement" }, reuse_review: { required: false, confirmed: false, basis: "",
    status: "LICENSED", explanation: "Recorded permission covers this use." } });
  const state = await controlled(page, status, [covered]);
  await page.goto("/#/queue/review");
  await page.locator('.post-row[data-id="covered"]').getByRole("button", { name: "Quick approve", exact: true }).click();
  await expect(bulkDialog(page).getByRole("heading", { name: "Review 1 YouTube posts", exact: true })).toBeVisible();
  await expect(bulkDialog(page).getByRole("radio")).toHaveCount(0);
  await expect(batchAgree(page)).not.toBeChecked();
  await batchAgree(page).check();
  await batchApprove(page).click();
  await expect(bulkDialog(page)).toHaveCount(0);
  expect(new URL(page.url()).hash).toBe("#/queue/review");
  expect(state.writes).toEqual([
    { path: "/api/autopilot/scheduled/bulk-preview", body: { ids: ["covered"] } },
    { path: "/api/autopilot/scheduled/bulk-approve", body: { token: "controlled-preview-1", confirm: true,
      reuse_confirmed: true } },
  ]);
  expect(state.errors).toEqual([]);
});
