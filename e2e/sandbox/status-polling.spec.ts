import { expect, test, APIRequestContext, Page, Route } from "@playwright/test";

// Responses are controlled in this browser only. The sandbox's accounts and Autopilot settings stay unchanged.
async function controlled(page: Page, request: APIRequestContext) {
  const status = await (await request.get("/api/autopilot/status")).json();
  status.enabled = true;
  status.paused = false;
  status.home.setup.started = true;
  status.home.needs_you = [];
  let hold = false;
  let calls = 0;
  const held: Route[] = [];
  await page.route("**/api/autopilot/status", (route) => {
    calls += 1;
    if (hold) held.push(route);
    else return route.fulfill({ json: status });
  });
  await page.clock.install();
  await page.goto("/#/autopilot");
  await expect(page.getByRole("heading", { name: "Autopilot is on", exact: true })).toBeVisible();
  await page.clock.pauseAt(new Date(await page.evaluate(() => Date.now()) + 1000));
  return { status, held, calls: () => calls, hold: (value: boolean) => { hold = value; } };
}

async function visible(page: Page, value: boolean) {
  await page.evaluate((shown) => {
    Object.defineProperty(document, "hidden", { configurable: true, value: !shown });
    document.dispatchEvent(new Event("visibilitychange"));
  }, value);
}

test("returning to a tab during a status request keeps one polling loop", async ({ page, request }) => {
  const poll = await controlled(page, request);
  poll.hold(true);
  await page.clock.runFor(3000);
  await expect.poll(() => poll.held.length).toBe(1);
  const before = poll.calls();
  for (let i = 0; i < 3; i += 1) {
    await visible(page, false);
    await visible(page, true);
  }
  await page.waitForTimeout(150);
  expect(poll.calls()).toBe(before);

  poll.hold(false);
  await poll.held[0].fulfill({ json: poll.status });
  await expect.poll(poll.calls).toBe(before + 1);
  await page.clock.runFor(3000);
  await expect.poll(poll.calls).toBe(before + 2);
  await page.waitForTimeout(150);
  expect(poll.calls()).toBe(before + 2);
});

test("an older status response cannot undo a successful Pause action", async ({ page, request }) => {
  const poll = await controlled(page, request);
  poll.hold(true);
  await page.clock.runFor(3000);
  await expect.poll(() => poll.held.length).toBe(1);
  const stale = structuredClone(poll.status);
  await page.route("**/api/autopilot/enable", (route) => {
    poll.status.enabled = false;
    return route.fulfill({ json: poll.status });
  });
  await page.getByRole("button", { name: "Pause Autopilot", exact: true }).click();
  const paused = page.getByRole("heading", { name: "Autopilot is paused", exact: true });
  await expect(paused).toBeVisible();
  poll.hold(false);
  await poll.held[0].fulfill({ json: stale });
  await page.waitForTimeout(150);
  await expect(paused).toBeVisible();
  await expect(page.locator("#top-state")).toHaveText("Autopilot: Paused");
});

test("an older failed poll cannot mark a successful Pause action disconnected", async ({ page, request }) => {
  const poll = await controlled(page, request);
  poll.hold(true);
  await page.clock.runFor(3000);
  await expect.poll(() => poll.held.length).toBe(1);
  await page.route("**/api/autopilot/enable", (route) => {
    poll.status.enabled = false;
    return route.fulfill({ json: poll.status });
  });
  await page.getByRole("button", { name: "Pause Autopilot", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Autopilot is paused", exact: true })).toBeVisible();
  await poll.held[0].abort();
  await page.waitForTimeout(150);
  await page.clock.runFor(3000);
  await expect.poll(() => poll.held.length).toBe(2);
  await poll.held[1].abort();
  await page.waitForTimeout(150);
  await expect(page.getByText("ClipFoundry is not answering", { exact: true })).toHaveCount(0);
  await page.clock.runFor(3000);
  await expect.poll(() => poll.held.length).toBe(3);
  await poll.held[2].abort();
  await expect(page.getByText("ClipFoundry is not answering", { exact: true })).toBeVisible();
});

test("hidden tabs poll every fifteen seconds and returning wakes the status", async ({ page, request }) => {
  const poll = await controlled(page, request);
  poll.hold(true);
  await page.clock.runFor(3000);
  await expect.poll(() => poll.held.length).toBe(1);
  await visible(page, false);
  const before = poll.calls();
  await poll.held[0].fulfill({ json: poll.status });
  await page.waitForTimeout(150);
  await page.clock.runFor(14999);
  expect(poll.calls()).toBe(before);
  await page.clock.runFor(1);
  await expect.poll(poll.calls).toBe(before + 1);
  await poll.held[1].fulfill({ json: poll.status });
  await page.waitForTimeout(150);
  await visible(page, true);
  await expect.poll(poll.calls).toBe(before + 2);
});
