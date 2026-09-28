import { expect, getJson, test } from "../fixtures";

const PAGES = [
  { nav: "Dashboard", hash: "#/", heading: /Turn long videos into\s*ready-to-post shorts\./ },
  { nav: "Create", hash: "#/create", heading: "Create clips" },
  { nav: "Projects", hash: "#/projects", heading: "Projects" },
  { nav: "Autopilot", hash: "#/autopilot", heading: "Autopilot" },
  { nav: "Publish Center", hash: "#/publish-center", heading: "Publish Center" },
  { nav: "Settings", hash: "#/settings", heading: "Settings" },
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
  await expect(page.locator(".sidebar .brand")).toHaveText("ClipFoundry");
  await expect(page.locator(".sidebar")).toContainText("Runs on this computer.");
});

test("the sidebar reaches every page", async ({ page }) => {
  await page.goto("/");
  const sidebar = page.locator(".sidebar");
  for (const p of PAGES) {
    const link = sidebar.getByRole("link", { name: p.nav, exact: true });
    await link.click();
    await expect(page).toHaveURL((u) => u.hash === p.hash);
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(p.heading);
    await expect(link).toHaveClass(/\bactive\b/);
    await expect(sidebar.locator("a.nav-item.active")).toHaveCount(1);
  }
});

test("the sidebar Create clips button opens Create", async ({ page }) => {
  await page.goto("/");
  await page.locator(".sidebar").getByRole("link", { name: "Create clips" }).click();
  await expect(page).toHaveURL(/#\/create$/);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Create clips");
});

test("an unknown address falls back to the Dashboard", async ({ page }) => {
  await page.goto("/#/no-such-page");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(PAGES[0].heading);
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
