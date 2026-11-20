import { expect, test } from "@playwright/test";

// The real app, isolated fixture data, and production graphics. No controls that start work are pressed.
// Since the space studio (2026-11-19) the office is the ship: office/StudioScene.ts paints it with Canvas 2D from the
// crew atlas (public/space/crew.png); PixiJS and its older canvas fallback are gone.
test("the ship keeps its full cast through navigation and repeated Map/List changes", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  await page.goto("/#/office");
  await page.getByRole("button", { name: "Map", exact: true }).click();
  await expect(page.locator(".office-map")).toHaveAttribute("data-renderer", "ship");
  await expect(page.locator('.robot-hit[data-id="command"]')).toHaveAttribute("data-room", "lounge");
  await expect(page.locator(".robot-hit")).toHaveCount(25);
  const painted = await page.locator(".office-world canvas").evaluate((source: HTMLCanvasElement) => {
    const copy = document.createElement("canvas");
    copy.width = source.width; copy.height = source.height;
    const ctx = copy.getContext("2d")!;
    ctx.drawImage(source, 0, 0);
    const data = ctx.getImageData(0, 0, copy.width, copy.height).data;
    const colors = new Set<number>();
    for (let i = 0; i < data.length; i += 32) if (data[i + 3]) colors.add((data[i] << 16) | (data[i + 1] << 8) | data[i + 2]);
    return colors.size;
  });
  expect(painted, "the actual ship is painted, rather than an empty canvas").toBeGreaterThan(30);
  for (let i = 0; i < 3; i++) {
    await page.getByRole("button", { name: "List", exact: true }).click();
    await expect(page.locator(".office-map")).toHaveCount(0);
    await page.getByRole("button", { name: "Map", exact: true }).click();
    await expect(page.locator('.robot-hit[data-id="radar"]')).toHaveAttribute("data-room", "lounge");
    await expect(page.locator(".office-map")).toHaveAttribute("data-renderer", "ship");
  }
  await page.locator('.robot-hit[data-id="radar"]').click();
  await expect(page.getByRole("complementary", { name: "Details" }).getByRole("heading", { level: 2 })).toHaveText("RADAR");
  await page.getByRole("link", { name: "Team", exact: true }).click();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Team");
  await page.goto("/#/office");
  await expect(page.locator(".robot-hit")).toHaveCount(25);
  await expect(page.locator('.robot-hit[data-id="command"]')).toHaveAttribute("data-room", "lounge");
  expect(errors).toEqual([]);
});

test("when the ship's pictures can't load, the rooms, robot details and controls stay usable", async ({ page }) => {
  await page.route("**/assets/StudioScene-*.js", route => route.abort());
  await page.goto("/#/office");
  await page.getByRole("button", { name: "Map", exact: true }).click();
  await expect(page.locator(".office-map")).toHaveAttribute("data-renderer", "plain");
  await expect(page.getByText("The ship pictures could not load.", { exact: false })).toBeVisible();
  await expect(page.locator(".robot-hit")).toHaveCount(25);
  await expect(page.locator(".office-world").getByRole("button", { name: /^Editing\./ })).toHaveCount(1);
  await page.locator('.robot-hit[data-id="radar"]').click();
  await expect(page.getByRole("complementary", { name: "Details" }).getByRole("heading", { level: 2 })).toHaveText("RADAR");
  await expect(page.getByRole("region", { name: "Autopilot controls" })).toBeVisible();
});

test("Team and the robot gallery draw every robot from the crew atlas, also with Reduced motion", async ({ page }) => {
  await page.goto("/#/office");
  await page.getByRole("combobox", { name: "Animations", exact: true }).selectOption("reduced");
  await page.getByRole("link", { name: "Team", exact: true }).click();
  await expect(page.locator(".team-card canvas.portrait")).toHaveCount(25);
  await page.goto("/#/dev/robots");
  const frames = await page.locator(".gallery thead th").count() - 1;
  expect(frames, "standing, blinking, looking, walking and four work frames").toBe(12);
  await expect(page.locator(".gallery canvas.portrait")).toHaveCount(25 * frames);
  const row = page.getByRole("row").filter({ has: page.getByRole("rowheader", { name: /COMMAND/ }) });
  const pixels = (i: number) => row.locator("canvas").nth(i).evaluate((canvas: HTMLCanvasElement) => canvas.toDataURL());
  // the work gesture is drawn: its frames differ from standing still
  expect(await pixels(frames - 1), "COMMAND's last work frame differs from standing").not.toBe(await pixels(0));
});
