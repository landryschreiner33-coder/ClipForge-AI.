# Phased implementation plan (done)

**Done (2026-10-01).** The owner approved the design and asked for all of it at once, so the five phases below went
into one pull request (PR #7) after PR #6 was merged. The test results are in the test log of
`docs/IMPLEMENTATION_STATUS.md`. Not done from this plan: README screenshots, and checks only the owner's PC can do
(Windows fonts and display scaling, 200% zoom, a screen reader).

**Order with PR #6.** PR #6 changes `Autopilot.tsx`, `autopilot.ts`, `styles.css` and the status document. Phase 1
should start only after PR #6 is merged (or closed), so that no thread edits the same files at the same time.
Phase 2 builds directly on PR #6's `home.keep_awake` and `home.my_videos`.

## Phase 1: tokens, controls, navigation and route aliases

* Put `tokens.css` into `frontend/src` (replacing the color and spacing variables in `styles.css`). Restyle the
  existing classes for buttons (sentence case), pills, panels, inputs, switches, segmented controls, dialogs, toasts
  and the focus ring.
* New shell: Home, Autopilot, Library, Posts, then Settings. Below 1024 px, a labeled Menu drawer. A skip link.
  Focus moves to the H1 after navigation.
* Router: add `#/library`, `#/posts/*`, `#/post/:id`, `#/setup/*`, `#/autopilot/activity`, `#/settings/defaults`, and
  the aliases in [ROUTE_MAP.md](ROUTE_MAP.md) using `replaceState`. Old pages mount under the new addresses until
  their phase (Posts shows today's Publish Center, Library shows today's Projects).
* Tests: update `e2e/tests/app-shell.spec.ts` (nav labels, the "Create clips" link), add alias and Back tests, and
  keep the e2e suite read-only.

## Phase 2: Home, Autopilot and setup

* Home: the lead card from `home.needs_you` (first item), "Also needs you", recent videos and clips, Coming up.
  Remove the hero, stat cards and the system panel.
* Autopilot overview as specified: the status panel with the four facts (the five sleep states, GPU vs actual mode),
  Needs you, Working on, Your videos, Coming up, How posts go out, and "Pause or stop everything". Move Activity to
  its own view.
* Backend (small): expose the running job or project in `home` for the current-work thumbnail and steps, and extend
  `test_autopilot_simple.py` so the new field keeps plain words.
* Setup: `#/setup` in 3 steps, reusing ConnectButton, TopicChoice and the start endpoint.
* Tests: `e2e/tests/dashboard.spec.ts` and `autopilot.spec.ts` (headings, "START AUTOPILOT" and "STOP ALL JOBS"
  become sentence case, "CLIPFOUNDRY AUTOPILOT", "AUTOPILOT ON"), plus a unit test that no status reads green while
  the poll is failing.

## Phase 3: Add video, Library and editor

* Add video: the drop area, "Choose a video", the link import and More options behind disclosures, real upload
  progress.
* Library: the new cards, the name filter and status chips (client-side), the More menu with delete confirmation
  (the existing 409 "Cancel processing before deleting" becomes a disabled item that says why).
* Source video page: the kind label, stages, an honest clip-count sentence, selection and ZIP, and the More menu.
  Fix "undefinedx realtime".
* Editor: the preview with its version badge, timeline, word strip, the five groups, Versions moved in from Publish,
  the save bar (unsaved, saved-not-rendered, rendering), and the unsaved-change guard on links, Back and unload.
* Tests: `create.spec.ts` and `projects.spec.ts` selectors ("Subtle auto-zoom" and "Hook overlay" switches), plus
  new tests for the guard and for "Save doesn't render".

## Phase 4: Posts, Settings, diagnostics and performance

* Posts: the tabs, grouped problems, rows with one action and a More menu, the Post review page replacing the
  ApproveDialog (it keeps the confirm checkbox, every platform field and audit restriction, Publish now only after
  approval, the reconciling resolution, and the link step), and Results (moved from the Dashboard, with "—" and
  reasons).
* Check how the API reports an approval invalidated by a new render, and show that exact wording.
* Prepare post: "Posts of this clip" (a join on `clip_id`), and the confirm dialogs stating consequences.
* Settings: Accounts, Defaults and Advanced; masked secrets with Replace; the sticky save bar with field errors;
  account and GPU banners. Accounts are no longer repeated under Advanced.
* Diagnostics stay in Autopilot → Advanced, restyled only.
* Tests: `publish-center.spec.ts` ("Open Publish Center", view headings) and `settings.spec.ts`.
  `test_autopilot_publish.py` mentions Publish Center in its text only.

## Phase 5: responsive and accessibility cleanup, tests and build

* Check each page at 1440×900, 1366×768, 768 and 390: no sideways scroll, and state plus next action visible without
  scrolling on desktop.
* axe-core in the e2e suite (read-only pages), keyboard walks (dialogs, menus, tabs), reduced motion, and 200% zoom.
* Performance: long libraries (lazy thumbnails) and poll-driven re-renders.
* Remove the unused styles, update `README.md` screenshots and `AGENTS.md` (the UI section), rebuild `dist`, and
  run the full test log.

## Risks

* **Owner habits:** "Publish Center" and "Dashboard" disappear from the sidebar. The aliases cover old links; the
  first release notes should say where things went.
* **The e2e suite runs against real data:** new selectors must stay read-only (never Approve, Publish, Delete,
  Save, Stop all or the Autopilot switch).
* **Windows look:** only verifiable on the owner's PC (Segoe UI, DPI scaling, the RTX 3050 states).
