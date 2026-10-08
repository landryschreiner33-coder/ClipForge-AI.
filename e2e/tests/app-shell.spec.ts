import type { Page } from "@playwright/test";
import { expect, getJson, test } from "../fixtures";

// The places in the top bar: Office, Missions (Autopilot), Clips (the library), Queue (posts) and Settings. Queue adds
// a count when posts wait for you. The page titles of Missions and Clips still say what they hold.
const PAGES = [
  { nav: /^Office$/, hash: "#/", heading: "Office", title: "Office · ClipFoundry" },
  { nav: /^Missions$/, hash: "#/missions", heading: "Autopilot", title: "Missions · ClipFoundry" },
  { nav: /^Clips$/, hash: "#/clips", heading: "Library", title: "Clips · ClipFoundry" },
  { nav: /^Queue\b/, hash: "#/queue/review", heading: "Queue", title: "Queue · ClipFoundry" },
  { nav: /^Settings$/, hash: "#/settings", heading: "Settings", title: "Settings · ClipFoundry" },
];
const topNav = (page: Page) => page.locator(".appbar").getByRole("navigation", { name: "Main" });

// Old addresses (bookmarks, links in older notes) open the new page in place.
const ALIASES = [
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
  ["#/autopilot/activity", "#/missions/activity"],
  ["#/autopilot/overview", "#/missions/system"],
  ["#/settings/general", "#/settings"],
];

test("the API reports its health", async ({ request }) => {
  const h = await getJson(request, "/api/health");
  expect(h.version).toBeTruthy();
  expect(h.data_dir).toBeTruthy();
  expect(typeof h.busy).toBe("boolean");
  expect(h.whisper).toHaveProperty("mode");
});

test("the built interface is served, and opens on the Office", async ({ page }) => {
  await page.goto("/");
  await expect(page).toHaveTitle("Office · ClipFoundry");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Office");
  await expect(page.locator(".appbar").getByRole("link", { name: "ClipFoundry, Office" })).toBeVisible();
  // The Office fills the window; the other pages end with what ClipFoundry is
  await page.goto("/#/clips");
  await expect(page.locator("main .sidebar-foot")).toContainText("Runs on this computer.");
});

test("the top bar reaches every place, marks it and moves focus to its title", async ({ page }) => {
  await page.goto("/");
  const nav = topNav(page);
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

test("the Autopilot link in the top bar shows its state in a word and opens Missions", async ({ page, request }) => {
  await page.goto("/#/clips");
  const link = page.locator(".appbar").getByRole("link", { name: /^Autopilot: / });
  await expect(async () => {
    const st = await getJson(request, "/api/autopilot/status");
    const word = st.paused ? "Stopped" : st.enabled ? "On" : st.home.setup.started ? "Paused" : "Off";
    await expect(link).toHaveText(`Autopilot: ${word}`, { timeout: 1000 });
  }).toPass();
  await link.click();
  await expect(page).toHaveURL(/#\/missions$/);
  await expect(topNav(page).getByRole("link", { name: "Missions" })).toHaveAttribute("aria-current", "page");
});

test("Add video on Clips opens the Add video page", async ({ page }) => {
  await page.goto("/#/clips");
  await page.locator("main .page-head").getByRole("link", { name: "Add video" }).click();
  await expect(page).toHaveURL(/#\/create$/);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Add video");
});

test("old addresses open the new pages, and Back does not bounce on them", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Office");
  for (const [old, now] of ALIASES) {
    await page.evaluate((h) => (window.location.hash = h), old);
    await expect(page).toHaveURL((u) => u.hash === now);
    await page.goBack();
    await expect(page).toHaveURL((u) => u.hash === "#/");
  }
});

test("an unknown address shows the Office with a note", async ({ page }) => {
  await page.goto("/#/no-such-page");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Office");
  await expect(page.locator("main")).toContainText("That address does not exist");
  await expect(page.locator("main")).toContainText("so the Office is shown instead");
});

test("the old Home is the Summary page", async ({ page }) => {
  await page.goto("/#/home");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Summary");
  await expect(page).toHaveTitle("Summary · ClipFoundry");
  // It belongs to the Office in the top bar
  await expect(topNav(page).getByRole("link", { name: "Office" })).toHaveAttribute("aria-current", "page");
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
  await expect(topNav(page)).toBeHidden();
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
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Library");
});

test("no page scrolls sideways on a phone-sized window", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  for (const hash of ["#/", "#/home", "#/missions", "#/clips", "#/create", "#/queue/review", "#/settings"]) {
    await page.goto(`/${hash}`);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    const wide = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    expect(wide, `${hash} is wider than the window`).toBeLessThanOrEqual(0);
  }
});

test("the Terms and Privacy pages are served", async ({ page, request }) => {
  await page.goto("/#/clips");
  for (const name of ["Terms", "Privacy"]) {
    const link = page.locator("main .legal-links").getByRole("link", { name, exact: true });
    const href = await link.getAttribute("href");
    expect(href).toBe(`/legal/${name.toLowerCase()}`);
    const res = await request.get(href!);
    expect(res.status()).toBe(200);
    expect(res.headers()["content-type"]).toContain("text/html");
  }
});
