import { expect, test, Page, APIRequestContext } from "@playwright/test";

// Controlled response tests verify rendering contracts. Actual pipeline captures are in zero-touch-loop.spec.ts.
// These browser contexts never change application data or present synthetic statuses as observed workers.
async function controlled(page: Page, request: APIRequestContext) {
  const status = await (await request.get("/api/autopilot/status")).json();
  status.enabled = true;
  status.paused = false;
  status.home.setup.started = true;
  status.workers.host.alive = true;
  status.home.needs_you = [];
  for (const w of status.workers.workers) Object.assign(w, {
    status: "idle", stale: false, job_kind: "", job_id: "", message: "", progress: null,
  });
  await page.route("**/api/autopilot/status", (route) => route.fulfill({ json: status }));
  return status;
}

test("stations follow simultaneous active jobs, exact progress and completion", async ({ page, request }) => {
  const st = await controlled(page, request);
  const names = ["source_scout", "analyzer", "quality_gate", "publisher"];
  const kinds = ["identify_link", "analyze_source", "quality_check", "publish"];
  names.forEach((name, i) => Object.assign(st.workers.workers.find((w: any) => w.name === name), {
    status: "working", job_kind: kinds[i], job_id: `job-${i}`, message: `Reported step ${i}`, progress: i === 1 ? .37 : null,
  }));
  await page.goto("/#/autopilot");
  await expect(page.locator('.robot-station[data-state="working"]')).toHaveCount(4);
  const editor = page.locator(".station-editor");
  await editor.focus();
  await page.keyboard.press("Enter");
  await expect(editor).toHaveAttribute("aria-expanded", "true");
  await expect(page.locator(".office-activity")).toContainText("37% of this step");
  await expect(page.locator(".station-editor .robot-arm").first()).toHaveCSS("animation-name", "robot-type");
  st.workers.workers.find((w: any) => w.name === "analyzer").status = "completed";
  await expect(editor).toHaveAttribute("data-state", "completed", { timeout: 6000 });
  await expect(editor).toHaveAttribute("data-state", "waiting", { timeout: 3000 });
  await expect(page.locator(".office-activity [role=progressbar]")).toHaveCount(0);
});

test("stale, paused, stopped and disconnected states stop processing animation", async ({ page, request }) => {
  const st = await controlled(page, request);
  const live = st.workers.workers.find((w: any) => w.name === "live_monitor");
  Object.assign(live, { status: "working", job_kind: "live_watch", job_id: "watch", stale: true, progress: .9 });
  await page.goto("/#/autopilot");
  await expect(page.locator('.robot-station[data-state="working"]')).toHaveCount(0);
  live.stale = false;
  await expect(page.locator(".station-finder")).toHaveAttribute("data-state", "working", { timeout: 6000 });
  st.enabled = false;
  await expect(page.locator('.robot-station[data-state="paused"]')).toHaveCount(4, { timeout: 6000 });
  await expect(page.locator(".station-finder .robot-tool")).toHaveCSS("animation-name", "none");
  st.paused = true;
  await expect(page.locator('.robot-station[data-state="stopped"]')).toHaveCount(4, { timeout: 6000 });
  await page.unroute("**/api/autopilot/status");
  await page.route("**/api/autopilot/status", (route) => route.abort());
  await expect(page.locator('.robot-station[data-state="disconnected"]')).toHaveCount(4, { timeout: 10000 });
  await expect(page.getByText("ClipFoundry is not answering", { exact: true })).toBeVisible();
});

test("ordinary failures rest; genuine notices explain attention and respect reduced motion", async ({ page, request }) => {
  const st = await controlled(page, request);
  Object.assign(st.workers.workers.find((w: any) => w.name === "analyzer"), {
    status: "failed", last_error: "Unusable input", message: "Trying the next video",
  });
  st.home.needs_you = [{ key: "account:test", type: "account", title: "Sign in again",
    detail: "Your connection expired", fix: "Open Accounts to reconnect", link: "#/settings" }];
  await page.goto("/#/autopilot");
  await expect(page.locator(".station-editor")).toHaveAttribute("data-state", "waiting");
  const scheduler = page.locator(".station-scheduler");
  await expect(scheduler).toHaveAttribute("data-state", "attention");
  await expect(scheduler).toContainText("Sign in again");
  await scheduler.click();
  await expect(page.locator(".office-activity")).toContainText("Open Accounts to reconnect");
  await page.emulateMedia({ reducedMotion: "reduce" });
  await expect(page.locator(".station-scheduler .robot-arm").first()).toHaveCSS("animation-name", "none");
  await page.setViewportSize({ width: 1366, height: 768 });
  await expect(page.getByLabel("Paste a video or stream link")).toBeInViewport();
  await expect(page.getByRole("button", { name: "Pause Autopilot", exact: true })).toBeInViewport();
  await page.setViewportSize({ width: 683, height: 384 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
});
