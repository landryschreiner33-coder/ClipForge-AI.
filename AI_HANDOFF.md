# AI handoff

Where the newest work stands, for the next AI assistant or developer. Read [AGENTS.md](AGENTS.md) first (rules and
how to run things), then this, then [docs/OFFICE.md](docs/OFFICE.md). Snapshot of October 8, 2026: branch names,
commits and PR states below were true when written; fetch before trusting them.

## Current goal

The owner's master prompt of October 7, 2026: ClipFoundry as a robot office. Autopilot finds videos, makes and checks
clips, and uploads them **only to a selected audience** (YouTube Private shared with invited viewers, TikTok
approved followers), while an office of 25 pixel robots shows the real work, a Brain learns cautiously from real
results, and NVIDIA's hosted AI is an optional extra. Local-first; the GPU path must keep working.

## Branches

* `claude/wonderful-ritchie-909tq3` is the default ("usual") branch, at `eff96fb` (public video discovery, pushed
  from outside the project on 2026-10-03).
* `claude/project-thread-vw1n9y` (draft PR #14) holds this build: `26f6b8f` (backend) and the commit that adds this
  file (screens, docs). Not merged; merging needs the owner's word.
* `codex/retro-robot-autopilot` and `claude/ecstatic-shannon-wb1zq1` are unmerged outside work. Don't merge them
  without the owner's decision on public videos.

## Architecture in one screen

* Backend: FastAPI + SQLite. Durable job queue (`autopilot/queue.py`) with 12 workers. Office backend in
  `clipfoundry/office/` reads the queue and records events (`office_events`), reports (`office_reports`) and
  decisions (`office_decisions`). Audience policy in `publish/audience.py`. Brain in `autopilot/brain.py`. NVIDIA in
  `pipeline/nvidia.py`.
* Frontend: React + Vite. Places: Office (`pages/Office.tsx`, `office/*`), Missions (`pages/Autopilot.tsx`), Clips
  (`pages/Library.tsx`, `pages/Feedback.tsx`), Queue (`pages/Posts.tsx`, `pages/PostReview.tsx`), Settings
  (`pages/Settings.tsx`, `components/integrations.tsx`). The built `frontend/dist` is committed.
* The robots: `frontend/src/office/cast.ts` (registry) must match `clipfoundry/office/roles.py` (a test checks it);
  art in `sprites.ts`; floor plan in `world.ts`; event handling in `useOffice.ts` and `OfficeMap.tsx`.

## Verified here (cloud machine: Linux, Chromium, no GPU, no accounts)

* `pytest -m "not slow"`: 545 passed. `pytest -m slow`: 7 of 7 after updating two tests that still expected
  `publishAt`. Details in the test log of `docs/IMPLEMENTATION_STATUS.md`.
* Sandbox browser tests (`cd e2e && npm run test:sandbox`, Chromium at `/opt/pw-browsers/chromium`): robot office 4
  of 4, motion 3 of 3, complete loop 1 of 1 passed. Beginner flow: fails at its rights expectation (below).
* Read-only browser suite against a sandbox: passed after two locator fixes (see the test log).
* Screenshots: `design/robot-office/screenshots/` (README there says which are real and which controlled).

## Not verified (must be checked on the owner's PC)

GPU transcription and rendering on the RTX 3050 (**GPU runtime not verified here**; on Windows run `gpu-check.bat`
in the ClipFoundry folder), real YouTube and TikTok uploads, private sharing in YouTube Studio, TikTok's audit, real
NVIDIA requests and NVIDIA's current terms, Windows fonts and display scaling. Checklist: end of
`docs/IMPLEMENTATION_STATUS.md`.

## Known problems and open decisions

* **Public video discovery** (`autopilot_public_videos`, default on since `eff96fb`) clips videos nobody gave reuse
  rights to (they are never scheduled or posted). The owner has not confirmed this design in the project.
  `e2e/sandbox/beginner-flow.spec.ts` still expects such videos never to be clipped: it fails on `eff96fb` and on
  this branch, and passes with the setting off. Align the test after the owner decides.
* TikTok Direct Post to followers needs TikTok's audit, which a personal tool may not get; the ready-to-post package
  and inbox draft are the fallback.
* Not built from the prompt: discovery connectors for Twitch, Kick, Reddit, X, Instagram and podcasts; Google Trends
  (no supported API); preview-based screening before download. The capability matrix says so in the app.
* The website (`docs/legal`) is not deployed; that needs the owner's OK. The privacy page was updated for this build.

## Do not break

Everything in AGENTS.md → *Rules every change must keep*, especially rule 13 (selected audience only), rule 14 (the
office only shows what happened), no silent CPU fallback in Autopilot, publish exactly what was checked, never post
twice, secrets out of logs and the bundle. Don't change `.mcp.json`, don't pin Playwright, don't upgrade GPU
dependencies, keep `e2e/tests` read-only.

## Next useful work

1. The owner reviews PR #14 and runs the PC checklist (GPU check, one real Private upload, Who watches).
2. The public-video decision, then the beginner-flow test.
3. If the owner wants them: more discovery connectors where a platform offers a supported API, and a cheap preview
   screen (hook and payoff from a short excerpt) before the full download.
