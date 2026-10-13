import { expect, test } from "@playwright/test";

// Every request that could change account, settings or publishing state is intercepted before reaching the app.
test("TikTok form helper prepares least-permission drafts without claiming approval or exposing app secrets",
async ({ page }) => {
  const errors: string[] = [], writes: { path: string; body: any }[] = [];
  page.on("pageerror", e => errors.push(e.message));
  const formDrafts: any[] = [];
  await page.route("**/api/**", async route => {
    const request = route.request(), path = new URL(request.url()).pathname;
    if (path === "/api/publish/tiktok/setup" && request.method() === "POST") {
      const draft = request.postDataJSON(); formDrafts.push(draft);
      const scopes = ["user.info.basic", ...(draft.mode !== "direct" ? ["video.upload"] : []),
        ...(draft.mode !== "inbox" ? ["video.publish"] : []), ...(draft.read_stats ? ["video.list"] : [])];
      return route.fulfill({ json: {
        name: "ClipFoundry", category: "Video / video editing", platform: "Desktop",
        description: "ClipFoundry is a local-first, single-user desktop editor, not a public multi-user service.",
        redirect_uri: "http://127.0.0.1:8999/api/oauth/tiktok/callback", mode: draft.mode,
        read_stats: draft.read_stats, preferences: { tiktok_direct_post: draft.mode !== "inbox",
          tiktok_inbox_upload: draft.mode !== "direct", tiktok_read_stats: draft.read_stats },
        products: ["Login Kit (Desktop)", "Content Posting API", ...(draft.read_stats ? ["Display API"] : [])],
        scopes, scope_notes: {}, urls: draft,
        url_errors: draft.website.startsWith("http://") ? { website: "Use your real published HTTPS domain." } : {},
        url_check: "Format only; availability and ownership unverified.",
        review_explanation: "Personal-use eligibility is unresolved. No approval is claimed.",
        checklist: [{ id: "app", label: "Created the app in the portal.", completed: draft.completed.includes("app") }],
        completed_count: draft.completed.length, portal_status: "ClipFoundry cannot verify app review or audit status.",
        limits: ["Sandbox cannot post Public videos."], demo_steps: ["Demonstrate a real sandbox integration."],
        sources: { "App review": "https://developers.tiktok.com/doc/app-review-guidelines/" },
        icon: { dark_url: "/api/publish/tiktok/setup/icon/dark", light_url: "/api/publish/tiktok/setup/icon/light" },
      } });
    }
    if (request.method() !== "GET") {
      writes.push({ path, body: request.postDataJSON() });
      return route.fulfill({ status: 409, json: { detail: "Controlled preview; nothing was saved or connected." } });
    }
    if (path === "/api/settings") {
      const response = await route.fetch(), settings = await response.json();
      return route.fulfill({ json: { ...settings, tiktok_client_key: "", tiktok_client_secret: "",
        tiktok_direct_post: false, tiktok_inbox_upload: true, tiktok_read_stats: false, tiktok_app_audited: false } });
    }
    if (path === "/api/publish/accounts") return route.fulfill({ json: {
      youtube: { configured: false, connected: false, scopes: [], restriction: "" },
      tiktok: { configured: false, connected: false, scopes: [], restriction: "", audited: false },
    } });
    return route.continue();
  });
  await page.goto("/#/settings");
  await expect(page.getByRole("heading", { name: "TikTok", exact: true })).toBeVisible();
  expect(formDrafts).toEqual([]); // A closed helper never prepares a form in the background.
  await page.getByText("Help me fill out the TikTok app form", { exact: true }).click();
  const helper = page.getByTestId("tiktok-form-helper");
  await expect(helper.getByText("Approval is TikTok's decision.", { exact: true })).toBeVisible();
  await expect(helper.getByRole("radio", { name: /Send to my TikTok inbox/ })).toBeChecked();
  await expect(helper.getByLabel("App name", { exact: true })).toHaveValue("ClipFoundry");
  await expect(helper.getByLabel("Login Kit Desktop redirect address", { exact: true })).toHaveValue(
    "http://127.0.0.1:8999/api/oauth/tiktok/callback");
  await expect(helper.getByRole("textbox", { name: "Description", exact: true })).toHaveValue(
    /not a public multi-user service/);
  await helper.getByRole("radio", { name: /Direct Post only/ }).check();
  await expect(helper.locator(".tk-scope-card code")).toHaveText("user.info.basic, video.publish");
  await helper.getByRole("checkbox", { name: /Also read my posted-video statistics/ }).check();
  await expect(helper.locator(".tk-scope-card code")).toHaveText("user.info.basic, video.publish, video.list");
  await helper.getByText("Public website, Terms and Privacy fields", { exact: true }).click();
  await helper.getByRole("textbox", { name: "Website URL", exact: true }).fill("http://127.0.0.1:8999/legal/");
  await expect(helper.getByText("Use your real published HTTPS domain.")).toBeVisible();
  await expect(helper.getByRole("button", { name: "Download TikTok form pack", exact: true })).toBeDisabled();
  await expect(helper.getByText(/Fix the entered public website addresses before downloading/)).toBeVisible();
  await helper.getByText(/3\. My setup checklist/).click();
  await helper.getByRole("checkbox", { name: "Created the app in the portal." }).check();
  await expect(helper.getByText("3. My setup checklist (1/1)", { exact: true })).toBeVisible();
  await expect(helper.getByText(/ClipFoundry cannot verify app review or audit status/)).toBeVisible();
  expect(writes).toEqual([]);
  await helper.getByRole("button", { name: "Use these permissions in ClipFoundry", exact: true }).click();
  await expect(page.getByText(/Unsaved changes/)).toBeVisible();
  await page.getByRole("button", { name: "Save settings", exact: true }).click();
  await expect(page.getByText("Controlled preview; nothing was saved or connected.", { exact: true })).toBeVisible();
  expect(writes).toEqual([{ path: "/api/settings", body: {
    tiktok_direct_post: true, tiktok_inbox_upload: false, tiktok_read_stats: true,
  } }]);
  expect(formDrafts.at(-1)?.completed).toEqual(["app"]);
  expect(formDrafts.every(d => !Object.keys(d).some(k => /secret|key|token|audit/.test(k)))).toBe(true);
  expect(errors).toEqual([]);
});
