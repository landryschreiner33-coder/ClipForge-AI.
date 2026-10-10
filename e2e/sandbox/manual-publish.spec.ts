import { expect, test } from "@playwright/test";

// Controlled browser responses describe an uncertain fake upload. No request reaches an account or writes data.
test("an unknown manual upload shows its hold and refreshes the existing outcome without another Publish",
async ({ page }) => {
  const errors: string[] = [], actions: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  const clip = { id: "unknown-clip", project_id: "unknown-project", status: "ready", has_video: true,
    title: "One confirmed clip", duration: 20, start: 0, end: 20, score: 80, version: 1, hashtags: [],
    post: { title: "One confirmed clip", caption: "The exact confirmed clip", hashtags: [] } };
  let publication: any = { id: "unknown-publication", clip_id: clip.id, platform: "youtube", mode: "direct",
    status: "processing", progress: 1, title: clip.title, description: clip.post.caption, tags: [],
    requested_privacy: "public", privacy: "", remote_id: "", url: "", version_id: "", options: {},
    created_at: Date.now() / 1000, updated_at: Date.now() / 1000,
    message: "YouTube may already have the video. Another upload is held to avoid a duplicate.",
    error: "The final upload reply was lost", fix: "Check YouTube Studio and use Refresh status.",
    info: { outcome_unknown: true, code: "outcome_unknown", studio_url: "https://studio.youtube.com/" },
    audience: { intent: "PUBLIC", visibility: "public" }, delivery: { transfer: "outcome_unknown" } };
  const account = { configured: true, connected: true, needs_reconnect: false, name: "Isolated test channel",
    account_id: "controlled-channel", verified: true, scopes: [], restriction: "" };
  await page.route("**/api/**", async route => {
    const request = route.request(), pathname = new URL(request.url()).pathname;
    if (request.method() !== "GET") {
      actions.push(`${request.method()} ${pathname}`);
      if (pathname === `/api/publications/${publication.id}/refresh`) {
        publication = { ...publication, status: "done", remote_id: "existing-video", privacy: "public",
          url: "https://www.youtube.com/watch?v=existing-video", error: "", fix: "",
          message: "The original upload was found; only the final reply was lost.",
          info: { ...publication.info, outcome_unknown: false, code: "" },
          delivery: { audience_setup: "public_api_verified",
            visibility: { requested: "public", returned: "public", evidence: "api" } } };
        return route.fulfill({ json: publication });
      }
      return route.fulfill({ status: 409, json: { detail: "This controlled test forbids another upload" } });
    }
    if (pathname === `/api/clips/${clip.id}`) return route.fulfill({ json: clip });
    if (pathname === `/api/projects/${clip.project_id}`)
      return route.fulfill({ json: { id: clip.project_id, name: "Controlled source", origin: "manual", clips: [] } });
    if (pathname === `/api/clips/${clip.id}/versions`)
      return route.fulfill({ json: { versions: [], active: "" } });
    if (pathname === `/api/clips/${clip.id}/publications`) return route.fulfill({ json: [publication] });
    if (pathname === "/api/publish/accounts")
      return route.fulfill({ json: { youtube: account, tiktok: { ...account, configured: false, connected: false } } });
    if (pathname === "/api/audience") return route.fulfill({ json: {
      youtube: { intent: "PUBLIC", visibility: "public", confirmed: true, label: "Public audience", group_version: 1 },
      tiktok: { intent: "LOCAL_ONLY", confirmed: false, label: "Local clips" } } });
    if (pathname === "/api/autopilot/scheduled") return route.fulfill({ json: { items: [], timezone: "UTC" } });
    if (pathname.startsWith(`/api/clips/${clip.id}/`)) return route.fulfill({ status: 404, body: "Fixture media" });
    return route.continue(); // Ordinary read-only status from the throwaway sandbox.
  });
  await page.goto(`/#/publish/${clip.id}`);
  await expect(page.getByRole("heading", { name: "Prepare post", exact: true })).toBeVisible();
  await expect(page.getByText("Upload outcome unknown", { exact: true })).toBeVisible();
  await page.getByRole("radio", { name: "No, it's not made for kids", exact: true }).check();
  const held = page.getByRole("button", { name: "Check upload outcome below", exact: true });
  await expect(held).toHaveAttribute("aria-disabled", "true");
  await held.click({ force: true });
  await expect(page.getByRole("dialog")).toHaveCount(0);
  expect(actions).toEqual([]);
  await page.getByRole("button", { name: "Refresh status", exact: true }).click();
  await expect(page.getByText("Public (platform confirmed)", { exact: true })).toBeVisible();
  await expect(page.getByText("Upload outcome unknown", { exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Publish to YouTube now…", exact: true }))
    .not.toHaveAttribute("aria-disabled", "true");
  expect(actions).toEqual(["POST /api/publications/unknown-publication/refresh"]);
  expect(errors).toEqual([]);
});
