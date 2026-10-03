import { expect, test } from "@playwright/test";

// These browser preferences live only in Playwright's disposable context. No backend settings are written.
test("Reduce motion applies immediately, survives reload, and synchronizes between tabs", async ({ page, context }) => {
  await page.emulateMedia({ reducedMotion: "no-preference" });
  const settingsWrites: string[] = [];
  page.on("request", (request) => {
    if (request.url().includes("/api/settings") && !["GET", "HEAD"].includes(request.method())) {
      settingsWrites.push(request.method());
    }
  });
  await page.goto("/#/settings/defaults");
  const control = page.getByRole("switch", { name: "Reduce motion", exact: true });
  await expect(control).toHaveAttribute("aria-checked", "false");
  await control.focus();
  await page.keyboard.press("Space");
  await expect(control).toHaveAttribute("aria-checked", "true");
  await expect(page.locator("html")).toHaveAttribute("data-motion", "reduced");
  await expect(page.locator(".savebar")).toContainText("No changes");
  await expect(page.getByText("Saved for this browser. No need to press Save settings.")).toBeVisible();
  expect(await page.evaluate(() => localStorage.getItem("clipfoundry.reduceMotion"))).toBe("true");
  await page.reload();
  await expect(control).toHaveAttribute("aria-checked", "true");
  await expect(page.locator("html")).toHaveAttribute("data-motion", "reduced");

  const other = await context.newPage();
  await other.emulateMedia({ reducedMotion: "no-preference" });
  await other.goto("/#/settings/defaults");
  await expect(other.getByRole("switch", { name: "Reduce motion", exact: true }))
    .toHaveAttribute("aria-checked", "true");
  await control.click();
  await expect(other.getByRole("switch", { name: "Reduce motion", exact: true }))
    .toHaveAttribute("aria-checked", "false");
  await expect(other.locator("html")).toHaveAttribute("data-motion", "full");
  expect(settingsWrites).toEqual([]);
});

test("The operating system's preference stays effective and hidden tabs pause decoration", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/#/settings/defaults");
  await expect(page.getByRole("switch", { name: "Reduce motion", exact: true }))
    .toHaveAttribute("aria-checked", "false");
  await expect(page.locator("html")).toHaveAttribute("data-motion", "reduced");
  await expect(page.getByText(/Your operating system also requests reduced motion/)).toBeVisible();
  await page.emulateMedia({ reducedMotion: "no-preference" });
  await expect(page.locator("html")).toHaveAttribute("data-motion", "full");
  await page.evaluate(() => {
    Object.defineProperty(document, "hidden", { configurable: true, value: true });
    document.dispatchEvent(new Event("visibilitychange"));
  });
  await expect(page.locator("html")).toHaveAttribute("data-page-hidden", "true");
  await page.evaluate(() => {
    Object.defineProperty(document, "hidden", { configurable: true, value: false });
    document.dispatchEvent(new Event("visibilitychange"));
  });
  await expect(page.locator("html")).toHaveAttribute("data-page-hidden", "false");
});

test("Blocked browser storage keeps the app usable and explains that the preference is temporary", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "no-preference" });
  await page.addInitScript(() => {
    Storage.prototype.getItem = () => { throw new DOMException("Storage is disabled", "SecurityError"); };
    Storage.prototype.setItem = () => { throw new DOMException("Storage is disabled", "SecurityError"); };
  });
  await page.goto("/#/settings/defaults");
  const control = page.getByRole("switch", { name: "Reduce motion", exact: true });
  await expect(control).toBeVisible();
  await control.click();
  await expect(control).toHaveAttribute("aria-checked", "true");
  await expect(page.locator("html")).toHaveAttribute("data-motion", "reduced");
  await expect(page.getByText("Applied for this tab. Your browser prevented saving this preference.")).toBeVisible();
  await expect(page.locator(".savebar")).toContainText("No changes");
});
