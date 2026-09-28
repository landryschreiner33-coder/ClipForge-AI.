import { test as base, expect, type APIRequestContext } from "@playwright/test";

/**
 * These tests run against your real ClipFoundry and its real data, so they are read-only by construction:
 * every request from the page that could change something (anything but GET/HEAD to /api/) is blocked
 * before it reaches the app, and a test that tried one fails and names it.
 * Uncaught errors in the page fail the test as well.
 */
type Watch = { blockedWrites: string[]; browserErrors: string[] };

export const test = base.extend<{ watch: Watch }>({
  watch: [
    async ({ page }, use) => {
      const w: Watch = { blockedWrites: [], browserErrors: [] };
      await page.route("**/api/**", (route) => {
        const r = route.request();
        if (r.method() === "GET" || r.method() === "HEAD") return route.continue();
        w.blockedWrites.push(`${r.method()} ${new URL(r.url()).pathname}`);
        return route.abort("blockedbyclient");
      });
      page.on("pageerror", (e) => w.browserErrors.push(`Uncaught: ${e.message}`));
      page.on("console", (m) => {
        // A missing thumbnail and the like are logged as failed resources; those are not app errors.
        if (m.type() === "error" && !m.text().startsWith("Failed to load resource")) w.browserErrors.push(m.text());
      });
      await use(w);
      expect(w.blockedWrites, "the page tried to change data (blocked, nothing was changed)").toEqual([]);
      expect(w.browserErrors, "errors in the browser console").toEqual([]);
    },
    { auto: true },
  ],
});

export { expect };

/** GET a JSON API endpoint of the running app. */
export async function getJson<T = any>(request: APIRequestContext, path: string): Promise<T> {
  const res = await request.get(path);
  expect(res.status(), `GET ${path}`).toBe(200);
  return res.json();
}
