import { expect, Page, test } from "@playwright/test";

// Controlled responses isolate concurrent UI updates; every browser still runs against disposable sandbox data.
function link(id: string, title: string) {
  return { id, title, url: `https://example.com/${id}.mp4`, platform: "public", kind: "recorded",
    live_status: "", status: "waiting", status_label: "Waiting", detail: "", progress: 0, project_id: "",
    added_at: 1, scheduled_at: null, can_remove: true, can_cancel: true, can_retry: false, can_prioritize: true };
}

async function overview(page: Page) {
  const status = await (await page.request.get("/api/autopilot/status")).json();
  status.enabled = false;
  status.home.setup.started = true;
  await page.route("**/api/autopilot/status", (route) => route.fulfill({ json: status }));
}

test("ADD keeps a link that arrived through polling while the request was pending", async ({ page }) => {
  await overview(page);
  const concurrent = link("concurrent", "Arrived while adding");
  const added = link("added", "Requested video");
  let links = [link("first", "Existing video")];
  let releaseAdd: (() => void) | undefined;
  let holdRefresh = false;
  let releaseRefresh: (() => void) | undefined;
  await page.route("**/api/autopilot/links", async (route) => {
    if (route.request().method() === "POST") {
      links = [...links, concurrent];
      await new Promise<void>((resolve) => { releaseAdd = resolve; });
      links = [added, ...links];
      await route.fulfill({ json: { item: added, already_added: false } });
    } else {
      if (holdRefresh) await new Promise<void>((resolve) => { releaseRefresh = resolve; });
      await route.fulfill({ json: links });
    }
  });
  try {
    await page.goto("/#/autopilot");
    await expect(page.getByRole("heading", { name: "Existing video", exact: true })).toBeVisible();
    await page.getByLabel("Paste a video or stream link").fill(added.url);
    await page.getByRole("button", { name: "ADD", exact: true }).click();
    await expect(page.getByRole("heading", { name: concurrent.title, exact: true })).toBeVisible();
    holdRefresh = true;
    releaseAdd?.();
    await expect(page.getByRole("heading", { name: added.title, exact: true })).toBeVisible();
    await expect(page.getByRole("heading", { name: concurrent.title, exact: true }))
      .toHaveCount(1, { timeout: 500 });
  } finally {
    holdRefresh = false;
    releaseAdd?.();
    releaseRefresh?.();
  }
});

test("Remove keeps another link that arrived during the pending action", async ({ page }) => {
  await overview(page);
  const first = link("first", "Remove this video");
  const concurrent = link("concurrent", "Arrived while removing");
  let links = [first, link("existing", "Keep this video")];
  let releaseRemove: (() => void) | undefined;
  let holdRefresh = false;
  let releaseRefresh: (() => void) | undefined;
  await page.route("**/api/autopilot/links", async (route) => {
    if (holdRefresh) await new Promise<void>((resolve) => { releaseRefresh = resolve; });
    await route.fulfill({ json: links });
  });
  await page.route("**/api/autopilot/links/first/remove", async (route) => {
    links = [...links, concurrent];
    await new Promise<void>((resolve) => { releaseRemove = resolve; });
    links = links.filter((item) => item.id !== first.id);
    await route.fulfill({ json: { ...first, status: "removed", status_label: "Canceled" } });
  });
  try {
    await page.goto("/#/autopilot");
    await page.getByRole("button", { name: `Remove: ${first.title}`, exact: true }).click();
    await expect(page.getByRole("heading", { name: concurrent.title, exact: true })).toBeVisible();
    holdRefresh = true;
    releaseRemove?.();
    await expect(page.getByRole("heading", { name: first.title, exact: true })).toHaveCount(0);
    await expect(page.getByRole("heading", { name: concurrent.title, exact: true }))
      .toHaveCount(1, { timeout: 500 });
    await expect(page.getByRole("heading", { name: "Keep this video", exact: true })).toBeVisible();
  } finally {
    holdRefresh = false;
    releaseRemove?.();
    releaseRefresh?.();
  }
});
