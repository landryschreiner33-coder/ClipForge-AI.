# ClipFoundry redesign proposal (prototype only)

This folder is a **design proposal** for a calmer, simpler ClipFoundry interface. It holds a clickable prototype
with sample data, the design documents, and nothing else. **It does not change the app.** The app's entry points,
`frontend/src`, `frontend/dist`, the backend and the tests are untouched.

## Open the prototype

* Double-click `prototype/index.html`. It works straight from disk, with no install, build, or internet.
* Or serve the folder: `python -m http.server 8790 --directory design/ui-redesign/prototype`, then open
  http://127.0.0.1:8790/.
* The **Prototype controls** button (top right, dashed violet) switches between sample scenarios (first use, no usable
  videos, working, clips ready, problems). It can also change one state at a time: Autopilot on, paused or stopped;
  the five PC sleep states; GPU working, broken or falling back to the CPU; an expired YouTube sign-in; a lost
  connection to ClipFoundry; very long names; missing thumbnails; and the loading state.
  The controls are part of the prototype, not a proposed feature.

## What the prototype can and cannot do

* It never contacts ClipFoundry, YouTube, TikTok or anything else: there is no `fetch`, no API call, and no storage.
  A test run confirmed that the page makes no network requests.
* Buttons that would act on real things (approve, publish, connect, open folder, stop all jobs, delete) are marked
  **demo**. They only change the page's memory, and a message says so.
* A file you choose or drop is never read or uploaded. The page shows only its name and size.
* All names, channels, handles and numbers are invented and marked "Sample". No secret, token or real account is in
  the sample data; saved secrets appear only as `•••••••• (saved)`.

## Files

| File | What it is |
| --- | --- |
| [AUDIT.md](AUDIT.md) | What was inspected (repo, commits), the current routes, components and API, a feature-location map, and problems found. |
| [SPEC.md](SPEC.md) | The design specification: principles, tokens and contrast, components, every screen and state, accessibility, and copy rules. It also lists what already has data behind it and what would be new, plus the tradeoffs. |
| [ROUTE_MAP.md](ROUTE_MAP.md) | Old to new routes and features. Every current capability has a new place, and old links keep working. |
| [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) | The five phases, the tests each one changes, and coordination with PR #6. None of this work is authorized yet. |
| `prototype/tokens.css` | The shared visual tokens (colors, type, spacing, radius, sizes). |
| `prototype/prototype.css` | Components and layout, built only from the tokens. |
| `prototype/sample-data.js` | The marked sample data. Field names follow `frontend/src/api.ts` and `autopilot.ts`. |
| `prototype/app.js` | The prototype: router with the old-address aliases, all screens, dialogs and demo simulations. |

Screenshots of the prototype and of the current app are delivered with the proposal (in the project files, under
`clipfoundry/ui-redesign/`), not committed here.
