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
* `claude/project-thread-vw1n9y` (draft PR #14) holds this build: `26f6b8f` (backend), `f71238c` (screens, docs),
  `cf54204` (the review round of October 8) and its docs commit. Not merged; merging needs the owner's word after
  the PC checks.
* `codex/retro-robot-autopilot` and `claude/ecstatic-shannon-wb1zq1` are unmerged outside work. The owner did not ask
  for them to be merged.

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

* On `cf54204`: `pytest -m "not slow"` 597 passed; `pytest -m slow` 7 passed (724 s); sandbox browser tests
  (`cd e2e && npm run test:sandbox`, Chromium at `/opt/pw-browsers/chromium`) 9 passed (10.1 min), including the
  beginner flow with public video discovery on. Details in the test log of `docs/IMPLEMENTATION_STATUS.md`.
* Screenshots: `design/robot-office/screenshots/` (README there says which are real and which controlled).

## Not verified (must be checked on the owner's PC)

GPU transcription and rendering on the RTX 3050 (**GPU runtime not verified here**; on Windows run `gpu-check.bat`
in the ClipFoundry folder), real YouTube and TikTok uploads, private sharing in YouTube Studio, TikTok's audit, real
NVIDIA requests and NVIDIA's current terms, Windows fonts and display scaling. Checklist: end of
`docs/IMPLEMENTATION_STATUS.md`.

## Known problems and open decisions

* **Public video discovery** stays on (owner, 2026-10-08): public videos are clipped on the PC, never planned or
  posted without reuse coverage. The beginner flow tests exactly that.
* TikTok: the audit for Direct Post is unlikely (TikTok's guidelines turn away personal tools and apps that repost
  other platforms' videos); inbox drafts need app approval too. The ready-to-post package, posted by the owner and
  linked or marked posted on the post's page, is the realistic path.
* Open gaps against the master prompt (report of 2026-10-08 in the project files and `IMPLEMENTATION_STATUS.md`):
  rework does not return to the responsible stage, no audio/video sync check, the Queue does not show retrying,
  waiting-for-results or platform-verified audience states, no general experiment framework, the Brain's
  plays-versus-people and one-dominant-video limits, the learner's 20-hour readings, simplified robot details.
* Not built from the prompt: discovery connectors for Twitch, Kick, Reddit, X, Instagram and podcasts; Google Trends
  (no supported API); preview-based screening before download. The capability matrix says so in the app.
* The website (`docs/legal`) is not deployed; that needs the owner's OK. The privacy page was updated for this build.

## Do not break

Everything in AGENTS.md → *Rules every change must keep*, especially rule 13 (selected audience only), rule 14 (the
office only shows what happened), no silent CPU fallback in Autopilot, publish exactly what was checked, never post
twice, secrets out of logs and the bundle. Don't change `.mcp.json`, don't pin Playwright, don't upgrade GPU
dependencies, keep `e2e/tests` read-only.

## Next useful work

1. The owner runs the PC test steps (`/mnt/project-files/clipfoundry/pc-test-steps-pr14.md` in the project files:
   a separate copy with its own data, no accounts) and reviews PR #14.
2. The open gaps above, in the order the owner picks.
3. If the owner wants them: more discovery connectors where a platform offers a supported API, and a cheap preview
   screen (hook and payoff from a short excerpt) before the full download.
