# ClipFoundry browser tests (Playwright)

End-to-end tests that open ClipFoundry in a real Chromium on **your own PC** and check that every page
works: Dashboard, Create, Projects and the clip editor, Autopilot, Publish Center and Settings. They also
check that Autopilot and publishing refuse requests that do not come from the app itself.

They test the ClipFoundry that is **already running** on your computer, with your real data. That is why
they are **read-only**:

- Any request from the page that could change something (anything except reading from `/api/`) is
  blocked before it reaches ClipFoundry. A test that tries one fails and names the request.
- The tests never press CREATE CLIPS, Delete, Save, Approve, Publish now, the AUTOPILOT switch,
  STOP ALL JOBS, or any other button that starts or changes something.
- The Autopilot tests check that Autopilot's on/off and paused state are the same before and after.
- Tests that need a project or a ready clip are skipped when your library has none.

## Run them (Windows)

1. Start ClipFoundry as usual with `start.bat` and leave its window open.
2. Double-click `e2e\run-tests.bat`.

The first run installs Playwright and its Chromium (needs [Node.js](https://nodejs.org/) LTS). If a test
fails, the HTML report opens in your browser with a screenshot of the failure; `npm run report` in the
`e2e` folder shows it with a step-by-step trace as well.

Or from a terminal:

```bat
cd e2e
npm install
npx playwright install chromium
npm test
```

| Command | What it does |
| --- | --- |
| `npm test` | Run everything headless |
| `npm run test:headed` | Same, with the browser window visible |
| `npm run test:ui` | Playwright's UI mode: pick tests, watch them step by step |
| `npx playwright test tests/create.spec.ts` | One file |
| `npx playwright test -g "Publish Center"` | Tests whose name matches |
| `npm run report` | Open the last HTML report |

### Another address or port

The tests use `http://127.0.0.1:8765`, ClipFoundry's default. If you start it on another port, set
`CLIPFOUNDRY_URL` first:

```bat
set CLIPFOUNDRY_URL=http://127.0.0.1:8766
npm test
```

Use `127.0.0.1` or `localhost`, not your network address: Autopilot and publishing only answer the
computer ClipFoundry runs on, so those tests would fail.

## What is covered

| File | Checks |
| --- | --- |
| `tests/app-shell.spec.ts` | Health API, the built UI is served, sidebar navigation to every page, unknown addresses, Terms and Privacy |
| `tests/dashboard.spec.ts` | Stat cards and recent projects match the API, System card matches `/api/health` |
| `tests/create.spec.ts` | CREATE CLIPS only enabled with a video or an http(s) URL, non-video files refused, options start from your saved defaults and changing them does not save anything |
| `tests/projects.spec.ts` | Library matches the API, Delete asks first (the test says no), a project and a clip editor open, an unknown project shows an error |
| `tests/autopilot.spec.ts` | Switch and STOP ALL JOBS reflect the real state, Overview cards, tabs and their addresses, Jobs list matches the queue |
| `tests/publish-center.spec.ts` | Each view matches the queue, approval count, time zone and auto-publish note, each post shows the final quality check of its file |
| `tests/settings.spec.ts` | All sections, data folder, Save only after a change and nothing saved when you leave, secrets masked |
| `tests/api-guards.spec.ts` | Autopilot and publishing refuse state changes without the app's header, and requests addressed to another host name |

## Maintaining the tests

- Import `test` and `expect` from `../fixtures`, not from `@playwright/test`. That keeps the write
  blocker and the browser-error check on every test.
- Find elements the way a person does: by role and visible text (`getByRole("button", { name: "Save settings" })`).
  When wording changes in the UI, update the matching text here.
- Compare what the page shows with what the API returns (`getJson(request, "/api/...")`) instead of
  expecting fixed numbers: your data changes. Wrap the comparison in `expect(async () => ...).toPass()`
  when the numbers can move while ClipFoundry is working.
- Keep new tests read-only. A test that has to create, publish or delete something does not belong in
  this suite, because it would run against your real library and accounts.
- Browser-error check: a missing thumbnail and similar resource errors are ignored; uncaught exceptions
  and other `console.error` messages fail the test.
- `CLIPFOUNDRY_E2E_CHROMIUM` can point at an existing Chromium instead of Playwright's download. You do
  not need it on Windows.
