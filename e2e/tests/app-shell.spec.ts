import { expect, getJson, test } from "../fixtures";

// The five places of the robot office (docs/OFFICE.md): Office, Missions, Clips, Queue, Settings. Queue adds a count.
const PAGES = [
  { nav: /^Office$/, hash: "#/", heading: "Office", title: "ClipFoundry" },
  { nav: /^Missions$/, hash: "#/missions", heading: "Missions", title: "Missions · ClipFoundry" },
  { nav: /^Clips$/, hash: "#/clips", heading: "Clips", title: "Clips · ClipFoundry" },
  { nav: /^Queue\b/, hash: "#/queue/review", heading: "Queue", title: "Queue · ClipFoundry" },
  { nav: /^Settings$/, hash: "#/settings", heading: "Settings", title: "Settings · ClipFoundry" },
];

// Old addresses (bookmarks, links in older notes) open the new page in place.
const ALIASES = [
  ["#/home", "#/"],
  ["#/projects", "#/clips"],
  ["#/library", "#/clips"],
  ["#/publish-center", "#/queue/review"],
  ["#/publish-center/upcoming", "#/queue/review"],
  ["#/publish-center/published", "#/queue/published"],
  ["#/publish-center/history", "#/queue/history"],
  ["#/publish-center/problems", "#/queue/problems"],
  ["#/posts", "#/queue/review"],
  ["#/posts/scheduled", "#/queue/scheduled"],
  ["#/autopilot", "#/missions"],
  ["#/autopilot/overview", "#/missions/system"],
  ["#/autopilot/jobs", "#/missions/jobs"],
  ["#/settings/general", "#/settings"],
];

test("the API reports its health", async ({ request }) => {
  const h = await getJson(request, "/api/health");
  expect(h.version).toBeTruthy();
  expect(h.data_dir).toBeTruthy();
  expect(typeof h.busy).toBe("boolean");
  expect(h.whisper).toHaveProperty("mode");
});

test("the built interface is served", async ({ page }) => {
  await page.goto("/");
  await expect(page).toHaveTitle("ClipFoundry");
  await expect(page.locator(".topbar").getByRole("link", { name: "ClipFoundry, Office" })).toBeVisible();
  await page.goto("/#/clips");
  await expect(page.locator(".app-foot")).toContainText("Runs on this computer.");
});

test("the top bar reaches every place, marks it and moves focus to its title", async ({ page }) => {
  await page.goto("/");
  const nav = page.locator(".topbar").getByRole("navigation", { name: "Main" });
  for (const p of [...PAGES.slice(1), PAGES[0]]) {
    const link = nav.getByRole("link", { name: p.nav });
    await link.click();
    await expect(page).toHaveURL((u) => u.hash === p.hash);
    const h1 = page.getByRole("heading", { level: 1 });
    await expect(h1).toHaveText(p.heading);
    await expect(h1).toBeFocused();
    await expect(page).toHaveTitle(p.title);
    await expect(link).toHaveAttribute("aria-current", "page");
    await expect(nav.locator('a[aria-current="page"]')).toHaveCount(1);
  }
});

test("the Autopilot pill shows its state in a word", async ({ page, request }) => {
  const st = await getJson(request, "/api/autopilot/status");
  const word = st.paused ? "Stopped" : st.enabled ? "On" : st.home.setup.started ? "Paused" : "Off";
  await page.goto("/#/clips");
  await expect(page.locator("#top-state")).toContainText(`Autopilot: ${word}`);
  await expect(page.locator("#top-state")).toHaveAttribute("href", "#/");
});

test("Add video on Clips opens the Add video page", async ({ page }) => {
  await page.goto("/#/clips");
  await page.locator("main .page-head").getByRole("link", { name: "Add video" }).click();
  await expect(page).toHaveURL(/#\/create$/);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Add video");
});

test("old addresses open the new pages, and Back does not bounce on them", async ({ page }) => {
  await page.goto("/#/clips");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Clips");
  for (const [old, now] of ALIASES) {
    await page.evaluate((h) => (window.location.hash = h), old);
    await expect(page).toHaveURL((u) => u.hash === now || (now === "#/" && u.hash === ""));
    await page.goBack();
    await expect(page).toHaveURL((u) => u.hash === "#/clips");
  }
});

test("an unknown address shows the Office with a note", async ({ page }) => {
  await page.goto("/#/no-such-page");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Office");
  await expect(page.locator("main")).toContainText("That address does not exist");
});

test("the skip link jumps to the page", async ({ page }) => {
  await page.goto("/");
  await page.keyboard.press("Tab");
  const skip = page.getByRole("link", { name: "Skip to content" });
  await expect(skip).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.locator("main")).toBeFocused();
});

test("on a narrow window the Menu opens and closes like a dialog", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await expect(page.locator(".top-nav")).toBeHidden();
  const open = page.getByRole("button", { name: "Menu" });
  await open.click();
  const menu = page.getByRole("dialog", { name: "Menu" });
  await expect(menu.getByRole("link", { name: /^Clips$/ })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(menu).toBeHidden();
  await expect(open).toBeFocused();
  await open.click();
  await menu.getByRole("link", { name: /^Clips$/ }).click();
  await expect(menu).toBeHidden();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Clips");
});

test("no page scrolls sideways on a phone-sized window", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  for (const hash of ["#/", "#/office/team", "#/missions", "#/clips", "#/clips/feedback", "#/create",
    "#/queue/review", "#/settings", "#/settings/integrations"]) {
    await page.goto(`/${hash}`);
    await expect(page.getByRole("heading", { level: 1 })).toBeAttached();
    await page.waitForTimeout(300);
    const wide = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    expect(wide, `${hash} is wider than the window`).toBeLessThanOrEqual(0);
  }
});

test("the Terms and Privacy pages are served", async ({ page, request }) => {
  await page.goto("/#/clips");
  for (const name of ["Terms", "Privacy"]) {
    const link = page.locator(".app-foot .legal-links").getByRole("link", { name, exact: true });
    const href = await link.getAttribute("href");
    expect(href).toBe(`/legal/${name.toLowerCase()}`);
    const res = await request.get(href!);
    expect(res.status()).toBe(200);
    expect(res.headers()["content-type"]).toContain("text/html");
  }
});
