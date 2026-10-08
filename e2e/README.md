# ClipFoundry browser tests (Playwright)

End-to-end tests that open ClipFoundry in a real Chromium on **your own PC** and check that every page
works: the Office and Team, Missions (Autopilot), Clips (Add video, the source video page, the clip editor and Test
feedback), the Queue and Settings. They also check that Autopilot and publishing refuse requests that do not come from the app itself.

They test the ClipFoundry that is **already running** on your computer, with your real data. That is why
they are **read-only**:

- Any request from the page that could change something (anything except reading from `/api/`) is
  blocked before it reaches ClipFoundry. A test that tries one fails and names the request.
- The tests never press Make clips, Delete, Save, Approve, Publish now, Start or Pause Autopilot,
  Stop all jobs, or any other button that starts or changes something. Dialogs they open are canceled.
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
| `npx playwright test -g "Posts"` | Tests whose name matches |
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
| `tests/app-shell.spec.ts` | Health API, the built UI is served, the top bar reaches Office, Missions, Clips, Queue and Settings (marked, focus on the title, tab title), Autopilot's state word, old addresses (`#/home`, `#/projects`, `#/library`, `#/posts/...`, `#/publish-center/...`, `#/autopilot/...`) open the new pages without trapping Back, unknown addresses, the skip link, the Menu on a narrow window, no sideways scrolling at phone size, Terms and Privacy |
| `tests/office.spec.ts` | The bottom bar shows the real state and only the controls that fit it (none pressed), rooms and robot states match the office API, on-duty robots stand at their stations, a robot's card and a room's details, Activity newest first, the overview's health headline, Team (25 robots and CORE), the developer gallery |
| `tests/autopilot.spec.ts` | The overview shows the real state and Stop all jobs asks first (the test cancels), Now, Progress, Next, Posts and This PC match the API, link intake and Needs you; Activity; Permissions & sources and its add dialogs (opened and canceled); System, Jobs and Learning under Advanced; section addresses |
| `tests/create.spec.ts` | Make clips only enabled with a video or an http(s) link, non-video files refused, a chosen video can be swapped, options start from your saved defaults and changing them does not save anything |
| `tests/library.spec.ts` | The Library matches the API, the name filter and chips, Delete and Make clips again ask first (the test cancels), a video and a clip open, leaving the editor with an unsaved change asks first, an unknown video or clip shows a message |
| `tests/posts.spec.ts` | Each tab lists the posts it should, tab counts, the time zone stated once, old Publish Center addresses, a post's row and page show the same status, Publish now only on an approved post, Cancel this post asks first (the test keeps the post), Results show real numbers or a dash with the reason, an unknown post |
| `tests/settings.spec.ts` | Accounts first, Defaults, Integrations (who watches, each connection's capabilities, NVIDIA AI) and Advanced (incl. the Brain and the Dev Log) sections, every setting has a place, data folder, Save only after a change (kept across the tabs) and leaving asks first, a field error blocks saving, secrets masked |
| `tests/api-guards.spec.ts` | Autopilot and publishing refuse state changes without the app's header, and requests addressed to another host name |

## Beginner flow and complete Autopilot loop (sandbox)

One more test goes through what a new user does: open ClipFoundry, press Set up ClipFoundry on the Office, choose
Autopilot and keep the suggested topics, connect YouTube and TikTok, press Start Autopilot, and watch Autopilot find
trending videos, create sources by itself and skip the ones nothing covers (listed in Activity, never asked about). The test then records
one agreement with a creator, naming the folder where they share their raw files, and Autopilot takes that
creator's video, finds its file in the folder and sends it on to the Clip Hunter by itself. It changes things, so it never runs against your real ClipFoundry: it starts its own **sandbox**
(`sandbox/run_sandbox.py`) with a temporary data folder, port 8799, **test connections** to local stand-ins
for Google's and TikTok's sign-in pages and APIs (nothing reaches the real platforms, nothing is posted) and a
synthetic transcript instead of Whisper (no model download).

A second isolated sandbox on port 8800 proves the full automatic loop: discovery, an unreadable source followed by
the next usable source, real audio extraction and captioned vertical renders, packaging, the full quality check,
scheduling, automatic YouTube upload to the fake platform, collection of its reported metrics, learning, and a
second discovery after the worker host restarts. Upload bytes must match the checked artifact's SHA-256. The test
also pastes a link through the page, pastes its alternate address to check duplicate handling, and keeps its locally
completed clip when publishing permission is unknown. An upcoming stream waits across another restart before real
segmented capture and post-live clipping finish it. It never approves an individual post or retries a failed job.

`sandbox/robot-office.spec.ts` checks how the Office draws real state, with controlled answers from the office API
in the browser only: all 25 identities remain visible at named stations, a report is carried to the manager, a
decision gets COMMAND's reaction, old events move nobody, paused and lost-connection states, and the layout at
1366×768, 1280×720 and narrow widths. `sandbox/motion.spec.ts` checks saved Follow system / Full / Reduced,
including Full overriding system reduced motion. `sandbox/brain-workspace.spec.ts` checks actual document upload,
approval, reload, lookup preview, disable/delete/export and responsive layout. The sandbox tests write the
screenshots in `design/robot-office/screenshots`.

The current beginner flow passes with public video discovery on. Uncovered videos can be clipped locally, but
cannot be automatically posted. The complete loop explicitly confirms Public YouTube setup and project audit,
gives channel-bound standing consent, and checks Public fake-account uploads without `publishAt`. Its sandbox-only
controls advance approved Public due times and result age; production Public uploads start locally at their due
time. [Current validation and remaining PC checks](../docs/IMPLEMENTATION_STATUS.md).

The full sandbox replaces external account APIs, fixture DNS, original-file access and Whisper. Rendering, quality
checks, approvals, queue dispatch, uploads and learning use the application itself. Small generated originals stand
in for the longer episodes described by the fake catalog. Simulated result age avoids waiting 48 hours; metrics still
come from the fake platform, and two posts correctly leave learning below its ten-post threshold. Fixture controls
under `/sandbox/` exist only in the sandbox executable. They are absent from the ordinary app.

The tests need `start.bat` to have run once (for `.venv`), ffmpeg/ffprobe, and **espeak-ng** or **espeak** on PATH to
generate speech with a matching transcript. They use CPU encoding and do not verify CUDA or real account uploads.

Double-click `e2e\run-beginner-test.bat`, or in a terminal:

```bat
cd e2e
npm run test:sandbox
```

`CLIPFOUNDRY_PYTHON` picks another Python (default `..\.venv\Scripts\python.exe`), and
`CLIPFOUNDRY_SANDBOX_PORT` another port; its successor is used by the complete-loop sandbox.
Screenshots of actual working, waiting, restart and paused states are saved under
`design/robot-office/screenshots/`, separately from Playwright's temporary test results. Its README labels actual
jobs, saved blueprint influence, lookup previews and controlled motion evidence separately.

The corresponding Python integration checks include an upcoming stream waiting across a worker restart, followed
by real segmented capture and post-live clipping when the fake platform reports it live:

```bat
.venv\Scripts\python.exe -m pytest tests/test_zero_touch_loop.py
```

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
