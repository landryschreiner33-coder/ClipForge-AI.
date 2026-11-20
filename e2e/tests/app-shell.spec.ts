import { expect, getJson, test } from "../fixtures";

// The ClipForge places (docs/clipforge/ROUTE_MAP.md): Studio, Projects, Brain, Publishing, Accounts, Settings.
// Publishing adds a count. Studio combines the old Home and the Office (studio upgrade handoff, section 4): the
// office is drawn on the Studio page, and #/office, its expanded view, is marked as Studio in the navigation.
// Since the space studio (2026-11-19) the page's own heading is its name, read out but shown in the top bar.
const PAGES = [
  { nav: /^Studio$/, hash: "#/", heading: "Studio", title: "Studio · ClipForge" },
  { nav: /^Projects$/, hash: "#/projects", heading: "Projects", title: "Projects · ClipForge" },
  { nav: /^Brain$/, hash: "#/brain/styles", heading: "Brain", title: "Brain · ClipForge" },
  { nav: /^Publishing\b/, hash: "#/publishing/review", heading: "Publishing", title: "Publishing · ClipForge" },
  { nav: /^Accounts$/, hash: "#/accounts", heading: "Accounts", title: "Accounts · ClipForge" },
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
  await expect(page).toHaveTitle("Studio · ClipForge");
  await expect(page.locator(".cf-side").getByRole("link", { name: "ClipForge, Studio" })).toBeVisible();
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

// The owner, 2026-11-19: "make everything easily accessible so i can easly make all type of clips, make youtube video,
// make animated short, clip live stream as it goes". Studio and + Make offer the same four, in the same order. Since
// 8:47 PM that evening the Studio panel opens on Working on, and its Make tab holds the four.
const MAKE = [["Make clips", "#/create/clips"], ["Make a YouTube video", "#/create/video"],
  ["Make an animated short", "#/create/short"], ["Clip a live stream", "#/missions/live"]];

test("Studio and + Make offer the same four things to make", async ({ page }) => {
  await page.goto("/#/");
  const panel = page.getByRole("tablist", { name: "Studio panel" });
  await expect(panel.getByRole("tab", { name: /^Working on/ })).toHaveAttribute("aria-selected", "true");
  await expect(page.getByRole("tabpanel", { name: /^Working on/ })).toContainText("Next to publish");
  await panel.getByRole("tab", { name: "Make", exact: true }).click();
  await expect(panel.getByRole("tab", { name: "Make", exact: true })).toHaveAttribute("aria-selected", "true");
  const tiles = page.getByRole("navigation", { name: "Make something" }).getByRole("link");
  await expect(tiles).toHaveCount(MAKE.length);
  for (const [i, [name, hash]] of MAKE.entries()) {
    await expect(tiles.nth(i)).toContainText(name);
    await expect(tiles.nth(i)).toHaveAttribute("href", hash);
  }
  await page.getByRole("button", { name: "Make", exact: true }).click();
  const items = page.getByRole("menu", { name: "Make" }).getByRole("menuitem");
  await expect(items).toHaveCount(MAKE.length);
  for (const [i, [name, hash]] of MAKE.entries()) {
    await expect(items.nth(i)).toContainText(name);
    await expect(items.nth(i)).toHaveAttribute("href", hash);
  }
  await page.keyboard.press("Escape");
  await expect(page.getByRole("menu", { name: "Make" })).toHaveCount(0);
  // the arrow keys move between the panel's tabs
  await panel.getByRole("tab", { name: "Make", exact: true }).focus();
  await page.keyboard.press("ArrowLeft");
  await expect(panel.getByRole("tab", { name: /^Working on/ })).toBeFocused();
  await expect(panel.getByRole("tab", { name: /^Working on/ })).toHaveAttribute("aria-selected", "true");
});

// The owner, 2026-11-19 8:47 PM: "make sure im still able to talk to the AI". Talk to AI has its own place in the
// navigation, a Brain tab and a row on the Studio. (Opening the chat starts a conversation, a write, so this read-only
// test checks where the links go; e2e/sandbox opens it.)
test("Talk to AI is one press away: the navigation, the Brain's tabs and the Studio", async ({ page }) => {
  await page.goto("/#/");
  const nav = page.locator(".cf-side").getByRole("navigation", { name: "Main" });
  await expect(nav.getByRole("link", { name: "Talk to AI", exact: true })).toHaveAttribute("href", "#/brain/talk");
  await expect(page.getByRole("tabpanel", { name: /^Working on/ }).getByRole("link", { name: /^Talk to ClipForge AI/ }))
    .toHaveAttribute("href", "#/brain/talk");
  await page.goto("/#/brain/styles");
  await expect(page.getByRole("navigation", { name: "Brain sections" }).getByRole("link", { name: "Talk to AI" }))
    .toHaveAttribute("href", "#/brain/talk");
});

test("Make clips from + Make opens Make clips, which takes a file or a link", async ({ page }) => {
  await page.goto("/#/projects");
  await page.getByRole("button", { name: "Make", exact: true }).click();
  await page.getByRole("menuitem", { name: /^Make clips/ }).click();
  await expect(page).toHaveURL(/#\/create\/clips$/);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Make clips");
  const source = page.getByRole("radiogroup", { name: "Where the video comes from" });
  await expect(source.getByRole("radio", { name: "Video file" })).toBeChecked();
  await source.getByRole("radio", { name: "Video link" }).check();
  await expect(page.getByLabel("Link to one video")).toBeVisible();
  // the old "Add video from a link" address opens the same page with Video link chosen
  await page.goto("/#/create/link");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Make clips");
  await expect(source.getByRole("radio", { name: "Video link" })).toBeChecked();
});

test("the expanded office belongs to Studio", async ({ page }) => {
  await page.goto("/#/office");
  await expect(page).toHaveTitle("Studio · Office · ClipForge");
  const nav = page.locator(".cf-side").getByRole("navigation", { name: "Main" });
  await expect(nav.getByRole("link", { name: /^Studio$/ })).toHaveAttribute("aria-current", "page");
  await expect(nav.getByRole("link", { name: /^Office$/ })).toHaveCount(0);
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

test("an unknown address shows Studio with a note", async ({ page }) => {
  await page.goto("/#/no-such-page");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Studio");
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
