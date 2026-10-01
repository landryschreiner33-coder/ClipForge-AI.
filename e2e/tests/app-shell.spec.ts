import { expect, getJson, test } from "../fixtures";

// The four places plus Settings. Nav names start with the place; Autopilot and Posts add a state word or a count.
const PAGES = [
  { nav: /^Home$/, hash: "#/", heading: "Home", title: "ClipFoundry" },
  { nav: /^Autopilot\b/, hash: "#/autopilot", heading: "Autopilot", title: "Autopilot · ClipFoundry" },
  { nav: /^Library$/, hash: "#/library", heading: "Library", title: "Library · ClipFoundry" },
  { nav: /^Posts\b/, hash: "#/posts/review", heading: "Posts", title: "Posts · ClipFoundry" },
  { nav: /^Settings$/, hash: "#/settings", heading: "Settings", title: "Settings · ClipFoundry" },
];

// Old addresses (bookmarks, links in older notes) open the new page in place.
const ALIASES = [
  ["#/projects", "#/library"],
  ["#/publish-center", "#/posts/review"],
  ["#/publish-center/upcoming", "#/posts/review"],
  ["#/publish-center/published", "#/posts/published"],
  ["#/publish-center/history", "#/posts/history"],
  ["#/publish-center/problems", "#/posts/problems"],
  ["#/posts", "#/posts/review"],
  ["#/autopilot/overview", "#/autopilot/system"],
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
  await expect(page.locator(".sidebar").getByRole("link", { name: "ClipFoundry, Home" })).toBeVisible();
  await expect(page.locator(".sidebar")).toContainText("Runs on this computer.");
});

test("the sidebar reaches every place, marks it and moves focus to its title", async ({ page }) => {
  await page.goto("/");
  const sidebar = page.locator(".sidebar");
  for (const p of [...PAGES.slice(1), PAGES[0]]) {
    const link = sidebar.getByRole("link", { name: p.nav });
    await link.click();
    await expect(page).toHaveURL((u) => u.hash === p.hash);
    const h1 = page.getByRole("heading", { level: 1 });
    await expect(h1).toHaveText(p.heading);
    await expect(h1).toBeFocused();
    await expect(page).toHaveTitle(p.title);
    await expect(link).toHaveAttribute("aria-current", "page");
    await expect(sidebar.locator('a[aria-current="page"]')).toHaveCount(1);
  }
});

test("the Autopilot link shows its state in a word", async ({ page, request }) => {
  const st = await getJson(request, "/api/autopilot/status");
  const word = st.paused ? "Stopped" : st.enabled ? "On" : st.home.setup.started ? "Paused" : "Off";
  await page.goto("/");
  await expect(page.locator(".sidebar").getByRole("link", { name: /^Autopilot\b/ })).toContainText(word);
});

test("Add video on the Library opens the Add video page", async ({ page }) => {
  await page.goto("/#/library");
  await page.locator("main .page-head").getByRole("link", { name: "Add video" }).click();
  await expect(page).toHaveURL(/#\/create$/);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Add video");
});

test("old addresses open the new pages, and Back does not bounce on them", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Home");
  for (const [old, now] of ALIASES) {
    await page.evaluate((h) => (window.location.hash = h), old);
    await expect(page).toHaveURL((u) => u.hash === now);
    await page.goBack();
    await expect(page).toHaveURL((u) => u.hash === "#/");
  }
});

test("an unknown address shows Home with a note", async ({ page }) => {
  await page.goto("/#/no-such-page");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Home");
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
  await expect(page.locator(".sidebar")).toBeHidden();
  const open = page.getByRole("button", { name: "Menu" });
  await open.click();
  const menu = page.getByRole("dialog", { name: "Menu" });
  await expect(menu.getByRole("link", { name: /^Library$/ })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(menu).toBeHidden();
  await expect(open).toBeFocused();
  await open.click();
  await menu.getByRole("link", { name: /^Library$/ }).click();
  await expect(menu).toBeHidden();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Library");
});

test("no page scrolls sideways on a phone-sized window", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  for (const hash of ["#/", "#/autopilot", "#/library", "#/create", "#/posts/review", "#/settings"]) {
    await page.goto(`/${hash}`);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    const wide = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    expect(wide, `${hash} is wider than the window`).toBeLessThanOrEqual(0);
  }
});

test("the Terms and Privacy pages are served", async ({ page, request }) => {
  await page.goto("/");
  for (const name of ["Terms", "Privacy"]) {
    const link = page.locator(".sidebar .legal-links").getByRole("link", { name, exact: true });
    const href = await link.getAttribute("href");
    expect(href).toBe(`/legal/${name.toLowerCase()}`);
    const res = await request.get(href!);
    expect(res.status()).toBe(200);
    expect(res.headers()["content-type"]).toContain("text/html");
  }
});
