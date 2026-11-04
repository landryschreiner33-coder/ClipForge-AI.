import { expect, getJson, test } from "../fixtures";

// The ClipForge places (docs/clipforge/ROUTE_MAP.md): Home, Projects, Brain, Publishing, Accounts, Office, Settings.
// Publishing adds a count. The Office's title is for screen readers only (the map fills the page).
const PAGES = [
  { nav: /^Home$/, hash: "#/", heading: "What are you making today?", title: "Home · ClipForge" },
  { nav: /^Projects$/, hash: "#/projects", heading: "Projects", title: "Projects · ClipForge" },
  { nav: /^Brain$/, hash: "#/brain/styles", heading: "Brain", title: "Brain · ClipForge" },
  { nav: /^Publishing\b/, hash: "#/publishing/review", heading: "Publishing", title: "Publishing · ClipForge" },
  { nav: /^Accounts$/, hash: "#/accounts", heading: "Accounts", title: "Accounts · ClipForge" },
  { nav: /^Office$/, hash: "#/office", heading: "Office", title: "Office · ClipForge" },
  { nav: /^Settings$/, hash: "#/settings/appearance", heading: "Settings", title: "Settings · ClipForge" },
];

// Old addresses (bookmarks, links in older notes) open the new page in place.
const ALIASES = [
  ["#/home", "#/"],
  ["#/clips", "#/projects"],
  ["#/library", "#/projects"],
  ["#/clips/feedback", "#/projects/feedback"],
  ["#/publish-center", "#/publishing/review"],
  ["#/publish-center/upcoming", "#/publishing/review"],
  ["#/publish-center/published", "#/publishing/published"],
  ["#/publish-center/history", "#/publishing/history"],
  ["#/publish-center/problems", "#/publishing/problems"],
  ["#/posts", "#/publishing/review"],
  ["#/posts/scheduled", "#/publishing/scheduled"],
  ["#/queue", "#/publishing/review"],
  ["#/queue/published", "#/publishing/published"],
  ["#/autopilot", "#/missions"],
  ["#/autopilot/overview", "#/missions/system"],
  ["#/autopilot/jobs", "#/missions/jobs"],
  ["#/settings/general", "#/settings"],
  ["#/settings/accounts", "#/accounts"],
  ["#/create", "#/create/clips"],
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
  await expect(page).toHaveTitle("Home · ClipForge");
  await expect(page.locator(".cf-side").getByRole("link", { name: "ClipForge, Home" })).toBeVisible();
  await page.goto("/#/projects");
  await expect(page.locator(".side-foot")).toContainText(/Runs on this computer\.|Your private ClipForge studio\./);
});

test("the top bar reaches every place, marks it and moves focus to its title", async ({ page }) => {
  await page.goto("/");
  const nav = page.locator(".cf-side").getByRole("navigation", { name: "Main" });
  for (const p of [...PAGES.slice(1), PAGES[0]]) {
    const link = nav.getByRole("link", { name: p.nav });
    await link.click();
    await expect(page).toHaveURL((u) => u.hash === p.hash);
    const h1 = page.getByRole("heading", { level: 1 }).first();
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
  await page.goto("/#/projects");
  await expect(page.locator("#top-state")).toContainText(`Autopilot: ${word}`);
  await expect(page.locator("#top-state")).toHaveAttribute("href", "#/missions");
});

test("Home offers exactly the two ways to make something", async ({ page }) => {
  await page.goto("/#/");
  const choices = page.locator("main .make-choice");
  await expect(choices).toHaveCount(2);
  await expect(choices.nth(0)).toContainText("Make clips");
  await expect(choices.nth(1)).toContainText("Make a YouTube video");
});

test("Make clips on Projects opens Make clips, which links to adding from a link", async ({ page }) => {
  await page.goto("/#/projects");
  await page.locator("main .page-head").getByRole("link", { name: "Make clips" }).click();
  await expect(page).toHaveURL(/#\/create\/clips$/);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Make clips");
  await page.getByRole("link", { name: "Add it from a link instead" }).click();
  await expect(page).toHaveURL(/#\/create\/link$/);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Add video");
});

test("old addresses open the new pages, and Back does not bounce on them", async ({ page }) => {
  await page.goto("/#/projects");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Projects");
  for (const [old, now] of ALIASES) {
    await page.evaluate((h) => (window.location.hash = h), old);
    await expect(page).toHaveURL((u) => u.hash === now || (now === "#/" && u.hash === ""));
    await page.goBack();
    await expect(page).toHaveURL((u) => u.hash === "#/projects");
  }
});

test("an unknown address shows Home with a note", async ({ page }) => {
  await page.goto("/#/no-such-page");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("What are you making today?");
  await expect(page.locator("main")).toContainText("That address does not exist");
});

test("the skip link jumps to the page", async ({ page }) => {
  await page.goto("/");
  // Nothing is drawn until the app knows whether you are signed in (cloud mode), so wait for the page first.
  await expect(page.locator("main")).toBeAttached();
  await page.keyboard.press("Tab");
  const skip = page.getByRole("link", { name: "Skip to content" });
  await expect(skip).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.locator("main")).toBeFocused();
});

test("on a narrow window the Menu opens and closes like a dialog", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await expect(page.locator(".cf-side")).toBeHidden();
  const open = page.getByRole("button", { name: "Menu" });
  await open.click();
  const menu = page.getByRole("dialog", { name: "Menu" });
  await expect(menu.getByRole("link", { name: /^Projects$/ })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(menu).toBeHidden();
  await expect(open).toBeFocused();
  await open.click();
  await menu.getByRole("link", { name: /^Projects$/ }).click();
  await expect(menu).toBeHidden();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Projects");
});

test("no page scrolls sideways on a phone-sized window", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  for (const hash of ["#/", "#/office", "#/office/team", "#/missions", "#/projects", "#/projects/feedback",
    "#/create/clips", "#/create/video", "#/create/link", "#/brain/styles", "#/brain/skills", "#/publishing/review",
    "#/accounts", "#/settings/appearance", "#/settings/integrations"]) {
    await page.goto(`/${hash}`);
    await expect(page.getByRole("heading", { level: 1 })).toBeAttached();
    await page.waitForTimeout(300);
    const wide = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    expect(wide, `${hash} is wider than the window`).toBeLessThanOrEqual(0);
  }
});

test("the Terms and Privacy pages are served", async ({ page, request }) => {
  await page.goto("/#/projects");
  for (const name of ["Terms", "Privacy"]) {
    const link = page.locator(".side-foot .legal-links").getByRole("link", { name, exact: true });
    const href = await link.getAttribute("href");
    expect(href).toBe(`/legal/${name.toLowerCase()}`);
    const res = await request.get(href!);
    expect(res.status()).toBe(200);
    expect(res.headers()["content-type"]).toContain("text/html");
  }
});
