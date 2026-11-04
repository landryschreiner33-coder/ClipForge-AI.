import { expect, Page, test } from "@playwright/test";
import type { Knowledge, KnowledgeInput, Workspace } from "../../frontend/src/brain";

// Saved memory is controlled data. All writes are intercepted; no owner data, account or platform is changed.
const at = 1791766800;
function note(id: string, title: string, kind: Knowledge["kind"] = "reference", tags = ["science"]): Knowledge {
  return {
    id,
    title,
    kind,
    tags,
    content: `Saved notes for ${title}.`,
    features: {},
    preferences: {},
    example_label: kind === "example" ? "good" : "",
    enabled: true,
    revision: 1,
    approved: false,
    approved_at: null,
    state: kind === "example" ? "saved_example" : "reference",
    filename: "",
    has_asset: false,
    asset_sha256: "",
    media: {},
    created_at: at,
    updated_at: at,
  };
}
async function memory(page: Page, initial: Knowledge[] = []) {
  let rows = structuredClone(initial);
  const writes: { path: string; body: Record<string, unknown> }[] = [];
  const observations: Workspace["observations"] = initial.length
    ? [
        {
          id: "reading-1",
          clip_id: "test-clip",
          clip_title: "Memory and sleep",
          platform: "youtube",
          cohort: "public",
          provenance: "owner_import",
          observed_at: at,
          metrics: { views: 120, likes: null },
          note: "Controlled imported reading",
        },
      ]
    : [];
  const influences: Workspace["influences"] =
    initial.length && initial[0].kind !== "reference"
      ? [
          {
            id: "decision-1",
            clip_id: "test-clip",
            clip_title: "Memory and sleep",
            knowledge_id: initial[0].id,
            revision: 1,
            knowledge_exists: true,
            created_at: at,
            snapshot: { title: initial[0].title, kind: initial[0].kind, example_label: "", features: {} },
            decisions: { caption_style: { before: "clean", after: "minimal" } },
          },
        ]
      : [];
  await page.route("**/api/**", async (route) => {
    const request = route.request(),
      path = new URL(request.url()).pathname;
    if (request.method() === "GET") {
      if (path === "/api/brain/knowledge") return route.fulfill({ json: rows });
      if (path === "/api/brain/knowledge/workspace")
        return route.fulfill({
          json: {
            counts: {
              total: rows.length,
              approved: rows.filter((row) => row.approved && row.enabled).length,
              examples: rows.filter((row) => row.kind === "example").length,
            },
            brain: {
              label: "Learning from results",
              message: "Controlled results",
              min_clips: 30,
              max_step: 0.1,
              observations: { youtube: observations.length },
            },
            observations,
            influences,
            history: [],
          },
        });
      return route.continue();
    }
    const body = request.postDataJSON() as Record<string, unknown>;
    writes.push({ path, body });
    if (path === "/api/brain/knowledge" && request.method() === "POST") {
      const input = body as unknown as KnowledgeInput;
      const row = { ...note(`created-${rows.length + 1}`, input.title, input.kind, input.tags), ...input };
      if (Object.keys(row.preferences).length) row.state = "active";
      row.effective_preferences = row.preferences;
      rows = [...rows, row];
      return route.fulfill({ json: row });
    }
    const id = path.split("/")[4],
      item = rows.find((row) => row.id === id);
    if (item && path.endsWith("/approve")) {
      if (body.revision !== item.revision)
        return route.fulfill({ status: 422, json: { detail: "This knowledge changed." } });
      item.approved = true;
      item.approved_at = at;
      item.state = "approved";
      return route.fulfill({ json: item });
    }
    if (item && request.method() === "PATCH") {
      if (body.expected_revision !== item.revision) {
        return route.fulfill({ status: 409, json: { detail: "This knowledge changed. Reload the saved note." } });
      }
      const { expected_revision: _expected, ...changes } = body;
      Object.assign(item, changes, {
        revision: item.revision + 1,
        approved: false,
        approved_at: null,
        state: body.enabled === false ? "disabled" : Object.keys(item.preferences).length ? "active" : "reference",
        effective_preferences: item.preferences,
      });
      return route.fulfill({ json: item });
    }
    return route.fulfill({ status: 409, json: { detail: "Only controlled Brain writes are accepted in this test." } });
  });
  return { writes, rows: () => rows };
}

test("the graph exposes saved notes, shared topics and actual decision/result provenance", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  const fixture = await memory(page, [
    note("guide", "Quiet science captions", "instruction"),
    note("sleep", "The science of sleep"),
    note("cooking", "Cooking story", "example", ["cooking"]),
  ]);
  await page.goto("/#/brain");
  const graph = page.getByRole("group", { name: "Interactive Brain graph", exact: true });
  await expect(graph).toBeVisible();
  const preference = graph.getByRole("button", { name: "Preference: Quiet science captions", exact: true });
  await preference.focus();
  await preference.press("Enter");
  const inspector = page.getByRole("complementary", { name: "Selected connection", exact: true });
  await expect(inspector.getByRole("heading", { name: "Quiet science captions", exact: true })).toBeVisible();
  await expect(inspector).toContainText("Applied revision 1");
  await inspector.getByRole("button", { name: "Memory and sleep Applied revision 1", exact: true }).click();
  await expect(inspector).toContainText("An actual preference decision");
  await expect(inspector).toContainText("clean → minimal");
  await graph.getByRole("button", { name: "result: Memory and sleep", exact: true }).click();
  await expect(inspector).toContainText("owner import");
  await expect(inspector).toContainText("likes: Not measured");
  await page.getByRole("button", { name: "Zoom in", exact: true }).click();
  await expect(page.getByLabel("Graph zoom", { exact: true })).toHaveText("125%");
  await page.getByRole("button", { name: "Fit graph", exact: true }).click();
  await expect(page.getByLabel("Graph zoom", { exact: true })).toHaveText("100%");
  const before = await graph.getAttribute("viewBox");
  await graph.focus();
  await graph.press("ArrowRight");
  expect(await graph.getAttribute("viewBox")).not.toBe(before);
  await page.getByLabel("Search knowledge graph", { exact: true }).fill("cooking");
  await expect(graph.getByRole("button", { name: "Note: The science of sleep", exact: true })).toHaveCount(0);
  await expect(graph.getByRole("button", { name: "Example: Cooking story", exact: true })).toBeVisible();
  await page.getByLabel("Search knowledge graph", { exact: true }).fill("no saved item matches");
  await expect(page.getByText("No connections match", { exact: true })).toBeVisible();
  await page.goto("/#/brain/examples");
  await expect(
    page
      .getByRole("navigation", { name: "Knowledge collections", exact: true })
      .getByRole("button", { name: "Your examples", exact: true }),
  ).toHaveAttribute("aria-pressed", "true");
  await expect(graph.getByRole("button", { name: "Example: Cooking story", exact: true })).toBeVisible();
  await expect(graph.getByRole("button", { name: "Note: The science of sleep", exact: true })).toHaveCount(0);
  expect(fixture.writes).toEqual([]);
  expect(errors).toEqual([]);
});

test("a stale edit stays visible until the owner explicitly reloads the saved revision", async ({ page }) => {
  const fixture = await memory(page, [note("stale", "Reviewed lesson", "instruction")]);
  await page.goto("/#/brain");
  await page
    .getByRole("group", { name: "Interactive Brain graph", exact: true })
    .getByRole("button", { name: "Preference: Reviewed lesson", exact: true })
    .click();
  await page.getByRole("button", { name: "Open & edit", exact: true }).click();
  await page
    .getByRole("textbox", { name: "Notes / instructions", exact: true })
    .fill("My unsaved changes must stay visible.");
  const saved = fixture.rows()[0];
  saved.revision = 2;
  saved.content = "The current saved revision from another tab.";
  saved.approved = true;
  saved.approved_at = at;
  saved.state = "approved";
  await page.getByRole("button", { name: "Save changes", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("This knowledge changed");
  await expect(page.getByRole("textbox", { name: "Notes / instructions", exact: true })).toHaveValue(
    "My unsaved changes must stay visible.",
  );
  expect(fixture.writes.at(-1)?.body.expected_revision).toBe(1);
  expect(saved.content).toBe("The current saved revision from another tab.");
  await page.getByRole("button", { name: "Reload saved note (discard edits)", exact: true }).click();
  await expect(page.getByRole("textbox", { name: "Notes / instructions", exact: true })).toHaveValue(saved.content);
  await expect(page.getByLabel("Title", { exact: true })).toHaveValue(saved.title);
});

test("simple notes derive a title; saved preferences activate without a separate approval", async ({
  page,
}, info) => {
  const fixture = await memory(page);
  await page.goto("/#/brain");
  await expect(page.locator("[data-brain-node]")).toHaveCount(1);
  await expect(page.getByText("A space for your ideas", { exact: true })).toBeVisible();
  await page.screenshot({ path: info.outputPath("brain-graph-empty.png"), fullPage: true, animations: "disabled" });
  await page.getByRole("button", { name: "Add note", exact: true }).click();
  await expect(page.locator(".brain-editor-details")).not.toHaveAttribute("open");
  await page
    .getByRole("textbox", { name: "Notes / instructions", exact: true })
    .fill("Keep the speaker's original facts.\nPrefer complete stories.");
  await page.getByRole("button", { name: "Save knowledge", exact: true }).click();
  await expect(page.getByLabel("Title", { exact: true })).toHaveValue("Keep the speaker's original facts.");
  expect(fixture.writes[0].body.kind).toBe("reference");
  expect(fixture.writes[0].body.preferences).toEqual({});
  await page.getByRole("button", { name: "Teach preference", exact: true }).click();
  await page.getByLabel("Title", { exact: true }).fill("Calm captions");
  await page.getByRole("combobox", { name: "Caption style", exact: true }).selectOption("minimal");
  await page.getByRole("button", { name: "Save knowledge", exact: true }).click();
  const item = fixture.rows().find((row) => row.title === "Calm captions")!;
  expect(item.approved).toBe(false);
  await expect(page.locator(".brain-editor .brain-pill")).toHaveText("Used automatically");
  await expect(page.getByRole("button", { name: "Review & approve", exact: true })).toHaveCount(0);
  expect(fixture.writes.some((write) => write.path.endsWith("/approve"))).toBe(false);
  await page.getByRole("textbox", { name: "Notes / instructions", exact: true }).fill("My updated preference notes.");
  await page.getByRole("button", { name: "Save changes", exact: true }).click();
  await expect(page.locator(".brain-editor .brain-pill")).toHaveText("Used automatically");
  expect(item.revision).toBe(2);
  expect(item.approved).toBe(false);
  await page.getByRole("button", { name: "Graph view", exact: true }).click();
  await expect(page.getByRole("group", { name: "Interactive Brain graph", exact: true })).toBeVisible();
  await expect(page.getByRole("complementary", { name: "Selected connection", exact: true })).toContainText(
    "Used automatically",
  );
});

test("a populated graph fits mobile and pauses decorative motion for reduced or hidden views", async ({
  page,
}, info) => {
  const rows = Array.from({ length: 60 }, (_, index) =>
    note(
      `note-${index}`,
      `Saved idea ${index + 1}`,
      index % 3 === 0 ? "instruction" : index % 3 === 1 ? "reference" : "example",
      [`topic-${index % 8}`],
    ),
  );
  await memory(page, rows);
  await page.goto("/#/brain");
  // 60 items + 8 tags + 4 groups + core + 2 evidence leaves.
  await expect(page.locator("[data-brain-node]")).toHaveCount(75);
  await expect(page.getByRole("region", { name: "Knowledge graph", exact: true })).toHaveAttribute(
    "data-animation",
    "decorative-glow",
  );
  await page.getByRole("button", { name: "Pause glow", exact: true }).click();
  await expect(page.getByRole("region", { name: "Knowledge graph", exact: true })).toHaveAttribute(
    "data-animation",
    "still",
  );
  await page.getByRole("button", { name: "Resume glow", exact: true }).click();
  await page.emulateMedia({ reducedMotion: "reduce" });
  await expect(page.getByRole("region", { name: "Knowledge graph", exact: true })).toHaveAttribute(
    "data-animation",
    "still",
  );
  await page.emulateMedia({ reducedMotion: "no-preference" });
  await page.evaluate(() => {
    Object.defineProperty(document, "hidden", { configurable: true, get: () => true });
    document.dispatchEvent(new Event("visibilitychange"));
  });
  await expect(page.getByRole("region", { name: "Knowledge graph", exact: true })).toHaveAttribute(
    "data-animation",
    "still",
  );
  const paused = await page
    .locator(".brain-node-aura")
    .evaluateAll((nodes) => nodes.every((node) => getComputedStyle(node).animationPlayState === "paused"));
  expect(paused).toBe(true);
  await page.evaluate(() => {
    Object.defineProperty(document, "hidden", { configurable: true, get: () => false });
    document.dispatchEvent(new Event("visibilitychange"));
  });
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 900 });
    await expect(page.getByRole("group", { name: "Interactive Brain graph", exact: true })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
    await page.screenshot({
      path: info.outputPath(`brain-graph-${width}.png`),
      fullPage: true,
      animations: "disabled",
    });
  }
});

test("graph limits are explicit and saved items beyond the cap still open in the editor", async ({ page }) => {
  const rows = Array.from({ length: 164 }, (_, index) =>
    note(`large-${index}`, `Real saved note ${index + 1}`, "reference", [`topic-${index}`]),
  );
  await memory(page, rows);
  await page.goto("/#/brain");
  await expect(page.locator("[data-brain-node]")).toHaveCount(196);
  await expect(page.getByText("136 more items, topics or readings remain", { exact: false })).toBeVisible();
  const sidebar = page.getByRole("complementary", { name: "Saved knowledge", exact: true });
  await sidebar.getByRole("button", { name: "Real saved note 164", exact: true }).click();
  await expect(page.getByLabel("Title", { exact: true })).toHaveValue("Real saved note 164");
  await expect(page.getByRole("button", { name: "List & editor", exact: true })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
});
