import { expect, test } from "@playwright/test";

// These browser preferences live only in Playwright's disposable context. No backend settings are written.
test("Animation mode applies immediately, survives reload, and synchronizes between tabs", async ({ page, context }) => {
  await page.emulateMedia({ reducedMotion: "no-preference" });
  const settingsWrites: string[] = [];
  page.on("request", (request) => {
    if (request.url().includes("/api/settings") && !["GET", "HEAD"].includes(request.method())) {
      settingsWrites.push(request.method());
    }
  });
  await page.goto("/#/settings/defaults");
  const control = page.getByRole("combobox", { name: "Animations", exact: true });
  await expect(control).toHaveValue("system");
  await control.selectOption("reduced");
  await expect(control).toHaveValue("reduced");
  await expect(page.locator("html")).toHaveAttribute("data-motion", "reduced");
  await expect(page.locator(".savebar")).toContainText("No changes");
  await expect(page.getByText("Saved for this browser. No need to press Save settings.")).toBeVisible();
  expect(await page.evaluate(() => localStorage.getItem("clipfoundry.animationMode"))).toBe("reduced");
  await page.reload();
  await expect(control).toHaveValue("reduced");
  await expect(page.locator("html")).toHaveAttribute("data-motion", "reduced");

  const other = await context.newPage();
  await other.emulateMedia({ reducedMotion: "no-preference" });
  await other.goto("/#/settings/defaults");
  await expect(other.getByRole("combobox", { name: "Animations", exact: true })).toHaveValue("reduced");
  await control.selectOption("full");
  await expect(other.getByRole("combobox", { name: "Animations", exact: true })).toHaveValue("full");
  await expect(other.locator("html")).toHaveAttribute("data-motion", "full");
  expect(settingsWrites).toEqual([]);
});

test("Follow system respects reduced motion and Full explicitly overrides it", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/#/settings/defaults");
  const control = page.getByRole("combobox", { name: "Animations", exact: true });
  await expect(control).toHaveValue("system");
  await expect(page.locator("html")).toHaveAttribute("data-motion", "reduced");
  await expect(page.getByText(/Your operating system requests reduced motion/)).toBeVisible();
  await control.selectOption("full");
  await expect(page.locator("html")).toHaveAttribute("data-motion", "full");
  // CSS decoration must respect the same override as canvas sprites.
  const animation = await page.evaluate(() => {
    const el = document.createElement("span");
    el.style.animation = "op-slide 2s linear infinite";
    document.body.append(el);
    const value = getComputedStyle(el).animationName;
    el.remove();
    return value;
  });
  expect(animation).toBe("op-slide");
  await page.reload();
  await expect(control).toHaveValue("full");
  await expect(page.locator("html")).toHaveAttribute("data-motion", "full");
  await control.selectOption("system");
  await expect(page.locator("html")).toHaveAttribute("data-motion", "reduced");
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
  const control = page.getByRole("combobox", { name: "Animations", exact: true });
  await expect(control).toBeVisible();
  await control.selectOption("reduced");
  await expect(control).toHaveValue("reduced");
  await expect(page.locator("html")).toHaveAttribute("data-motion", "reduced");
  await expect(page.getByText("Applied for this tab. Your browser prevented saving this preference.")).toBeVisible();
  await expect(page.locator(".savebar")).toContainText("No changes");
});
