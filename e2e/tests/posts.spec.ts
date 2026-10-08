import { expect, getJson, test } from "../fixtures";

// Looks at the Queue (posts) and the post pages only. Approve, Publish now, Cancel post, Save, I shared it and the
// resolve and link buttons are never pressed; a dialog that is opened is closed with its cancel button or Escape.
// Writes are blocked anyway.

type Item = {
  id: string; status: string; planned_at: number | null; approval_valid: boolean; platform: string;
  publication: { status: string } | null;
};

/** Every post, the way the page loads them (the active ones, then the finished ones). */
async function allPosts(request: Parameters<typeof getJson>[0]): Promise<{ items: Item[]; timezone: string }> {
  const up = await getJson(request, "/api/autopilot/scheduled?view=upcoming&limit=500");
  const done = await getJson(request, "/api/autopilot/scheduled?view=history&limit=500");
  const seen = new Set<string>();
  const items = [...up.items, ...done.items].filter((p: Item) => !seen.has(p.id) && !!seen.add(p.id));
  return { items, timezone: up.timezone };
}

// The page's tabs, from the API's statuses (frontend/src/components/postShared.tsx VIEW_OF).
const now = () => Date.now() / 1000;
const onPlatform = (p: Item) => p.status === "published" && !!p.planned_at && p.planned_at > now();
const outdated = (p: Item) => p.status === "approved" && !p.approval_valid;
const VIEW: Record<string, (p: Item) => boolean> = {
  review: (p) => p.status === "awaiting_approval" || outdated(p),
  scheduled: (p) => (p.status === "approved" && !outdated(p)) || p.status === "publishing" || onPlatform(p),
  published: (p) => p.status === "published" && !onPlatform(p),
  history: (p) => (p.status === "published" && !onPlatform(p)) || ["canceled", "replaced"].includes(p.status),
  problems: (p) => ["reconciling", "failed", "blocked", "action_needed"].includes(p.status),
};
const EMPTY: Record<string, string> = {
  review: "Nothing waits for your OK", scheduled: "Nothing is scheduled", published: "Nothing uploaded yet",
  history: "No history yet", problems: "No problems",
};

test("every tab lists the posts it should", async ({ page, request }) => {
  for (const v of Object.keys(VIEW)) {
    await page.goto(`/#/queue/${v}`);
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Queue");
    const current = v === "history" ? "Published" : { review: "Needs review", scheduled: "Scheduled",
      published: "Published", problems: "Problems" }[v]!;
    await expect(page.getByRole("navigation", { name: "Queue sections" }).locator("[aria-current=page]"))
      .toContainText(current);
    await expect(async () => {
      const { items } = await allPosts(request);
      const n = items.filter(VIEW[v]).length;
      if (n === 0) await expect(page.getByRole("heading", { name: EMPTY[v] })).toBeVisible({ timeout: 1000 });
      else await expect(page.locator(".post-row")).toHaveCount(n, { timeout: 1000 });
    }).toPass();
  }
});

test("the tab counts match the posts that wait for you", async ({ page, request }) => {
  await page.goto("/#/queue/review");
  const tabs = page.getByRole("navigation", { name: "Queue sections" });
  await expect(async () => {
    const { items } = await allPosts(request);
    for (const [name, v] of [["Needs review", "review"], ["Problems", "problems"]] as const) {
      const n = items.filter(VIEW[v]).length;
      const count = tabs.getByRole("link", { name: new RegExp(`^${name}`) }).locator(".count");
      if (n) await expect(count).toHaveText(String(n), { timeout: 1000 });
      else await expect(count).toHaveCount(0, { timeout: 1000 });
    }
  }).toPass();
});

test("the time zone is stated once, under the title", async ({ page, request }) => {
  const { timezone } = await allPosts(request);
  await page.goto("/#/queue/review");
  await expect(page.locator(".page-head p")).toContainText(timezone);
});

test("old Publish Center and Posts addresses open the Queue", async ({ page }) => {
  for (const [from, to] of [["publish-center", "queue/review"], ["publish-center/problems", "queue/problems"],
    ["publish-center/history", "queue/history"], ["posts/no-such-tab", "queue/review"], ["posts/scheduled",
      "queue/scheduled"], ["queue/no-such-tab", "queue/review"]]) {
    await page.goto(`/#/${from}`);
    await expect(page).toHaveURL(new RegExp(`#/${to}$`));
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Queue");
  }
});

test("each post's row and page show the same status, and Publish now only on an approved post", async ({
  page, request,
}) => {
  const { items } = await allPosts(request);
  test.skip(items.length === 0, "no posts yet");
  // A few of each status, so every kind of post page is opened at least once.
  const sample = items.filter((p, i) => items.slice(0, i).filter((x) => x.status === p.status).length < 2);
  for (const p of sample) {
    const view = Object.keys(VIEW).find((v) => VIEW[v](p))!;
    await page.goto(`/#/queue/${view}`);
    const word = (await page.locator(`.post-row[data-id="${p.id}"] .post-meta .pill`).innerText()).trim();
    await page.goto(`/#/post/${p.id}`);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await expect(page.locator(".page-head .pill").first()).toHaveText(word);
    const valid = p.status === "approved" && p.approval_valid;
    await expect(page.getByRole("button", { name: "Publish now…" })).toHaveCount(valid ? 1 : 0);
    const needsOk = p.status === "awaiting_approval" || outdated(p);
    await expect(page.getByRole("button", { name: /^Approve for / })).toHaveCount(needsOk ? 1 : 0);
    if (needsOk) {
      // The OK is its own step: the checkbox starts unticked and the bar says what's missing.
      await expect(page.getByLabel("I watched this video and read its text.")).not.toBeChecked();
      await expect(page.locator("#ok-why")).toContainText("To approve:");
    }
    if (p.status === "reconciling") {
      await expect(page.getByRole("button", { name: /add its link/ })).toBeVisible();
      await expect(page.getByRole("button", { name: /upload again/ })).toBeVisible();
    }
  }
});

test("Cancel this post asks first and says what happens", async ({ page, request }) => {
  const { items } = await allPosts(request);
  const p = items.find((x) => ["awaiting_approval", "approved"].includes(x.status));
  test.skip(!p, "no planned post to look at");
  await page.goto(`/#/queue/${VIEW.review(p!) ? "review" : "scheduled"}`);
  await page.locator(`.post-row[data-id="${p!.id}"]`).getByRole("button", { name: /^More for this/ }).click();
  await page.getByRole("menuitem", { name: "Cancel this post…" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByRole("heading")).toHaveText(/^Cancel this (YouTube|TikTok) post\?$/);
  await expect(dialog).toContainText("It won't be posted.");
  await dialog.getByRole("button", { name: "Keep the post" }).click();
  await expect(dialog).toHaveCount(0);
});

test("Results show real numbers, or a dash with the reason", async ({ page, request }) => {
  const perf = await getJson(request, "/api/performance");
  await page.goto("/#/queue/results");
  await expect(page.getByRole("heading", { name: "Results", level: 2 })).toBeVisible();
  if (perf.published === 0) {
    await expect(page.getByText("Nothing published yet.")).toBeVisible();
    return;
  }
  await expect(page.locator("table.data tbody tr")).toHaveCount(perf.items.length);
  for (const dash of await page.locator("table.data .metric-missing").all()) {
    await expect(dash).toHaveAttribute("aria-label", /^Not available: /);
  }
});

test("an unknown post says so", async ({ page }) => {
  await page.goto("/#/post/no-such-post");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Post not found");
  await expect(page.getByRole("link", { name: "Open the Queue" })).toBeVisible();
});
