import { expect, test } from "@playwright/test";

// The real app, isolated fixture data, and production graphics. No controls that start work are pressed.
test("the Pixi office keeps its full cast through navigation and repeated Map/List changes", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  await page.goto("/#/office");
  await page.getByRole("button", { name: "Map", exact: true }).click();
  await expect(page.locator(".office-map")).toHaveAttribute("data-renderer", "pixi");
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
  expect(painted, "the actual scene is painted, rather than an empty graphics context").toBeGreaterThan(30);
  for (let i = 0; i < 3; i++) {
    await page.getByRole("button", { name: "List", exact: true }).click();
    await expect(page.locator(".office-map")).toHaveCount(0);
    await page.getByRole("button", { name: "Map", exact: true }).click();
    await expect(page.locator('.robot-hit[data-id="radar"]')).toHaveAttribute("data-room", "lounge");
    await expect(page.locator(".office-map")).toHaveAttribute("data-renderer", "pixi");
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

test("an unavailable graphics bundle keeps the original map, robot details and controls usable", async ({ page }) => {
  await page.route("**/assets/StudioScene-*.js", route => route.abort());
  await page.goto("/#/office");
  await page.getByRole("button", { name: "Map", exact: true }).click();
  await expect(page.locator(".office-map")).toHaveAttribute("data-renderer", "canvas");
  await expect(page.locator(".robot-hit")).toHaveCount(25);
  await expect(page.locator('.robot-hit[data-id="radar"]')).toHaveAttribute("data-room", "lounge");
  await expect(page.getByText("Original artwork · new graphics unavailable in this browser")).toBeVisible();
  await page.locator('.robot-hit[data-id="radar"]').click();
  await expect(page.getByRole("complementary", { name: "Details" }).getByRole("heading", { level: 2 })).toHaveText("RADAR");
  await expect(page.getByRole("region", { name: "Autopilot controls" })).toBeVisible();
});

test("Team uses the refined cast and COMMAND visibly reacts to approval even with Reduced motion", async ({ page }) => {
  await page.goto("/#/office");
  await page.getByRole("combobox", { name: "Animations", exact: true }).selectOption("reduced");
  await page.getByRole("link", { name: "Team", exact: true }).click();
  await expect(page.locator('.team-card canvas[data-art="studio"]')).toHaveCount(25);
  await page.getByRole("button", { name: "Back", exact: true }).click();
  await expect(page.locator('.team-card canvas[data-art="studio"]')).toHaveCount(25);
  await page.goto("/#/dev/robots");
  await expect(page.locator('.gallery canvas[data-art="studio"]')).toHaveCount(100);
  const front = page.getByRole("row").filter({ has: page.getByRole("rowheader", { name: /COMMAND/ }) }).locator("canvas").first();
  const image = () => front.evaluate((canvas: HTMLCanvasElement) => canvas.toDataURL());
  const idle = await image();
  await page.getByRole("combobox", { name: "Pose", exact: true }).selectOption("approved");
  await expect.poll(image, { message: "the approval changes rendered pixels, rather than just a pose attribute" }).not.toBe(idle);
  const approved = await image();
  await page.waitForTimeout(600);
  expect(await image(), "the visible approval cue stays still in Reduced mode").toBe(approved);
});
