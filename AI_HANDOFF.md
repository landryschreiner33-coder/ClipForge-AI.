# AI handoff

Read [AGENTS.md](AGENTS.md), this file, [docs/OFFICE.md](docs/OFFICE.md) and
[docs/PLATFORM_CAPABILITIES.md](docs/PLATFORM_CAPABILITIES.md). Snapshot: 2026-10-09 (America/Chicago).
Fetch before trusting branch state.

## Current scope and branch

Latest social-pixel-office checkpoint starts at `5b1f7a9`: the owner asked to use better graphics tools and give
off-duty robots games, food and drinks. Six authored gestures animate arcade controls, board-game pieces, mugs,
bites, page turns and stretches. There are 29 exclusive activity places, 25 stable cast homes and at most two
recreational walkers. Identity-phased routines rotate through free destinations; work and confirmed document
handoffs take precedence, preserve real references and clear leisure props. State badges remain authoritative.
The owner explicitly authorized stopped-office recreation even when those off-duty roles are marked Paused.
An individual pause while Running or an unavailable role remains quiet; global Pause, Reduced, hidden and stale
views freeze recreation. Recovery does not replay missed leisure time or old job stages.

PixiJS 8.22.0 now uses cached BlurFilter light pools and distinct arcade/café/game/sofa zones. New dependency
GSAP 3.15.0 supplies pure gesture-easing functions on the office clock, without independent timelines; its standard
no-charge license notice is included (it is not MIT). Native image generation produced the original bundled skyline.
Optional skyline loading is bounded to 1.5 seconds; failure/stall leaves procedural windows, and late completion
cannot mutate the scene. Cropped textures are destroyed without deleting the shared asset source. Canvas retains
simpler phase-driven gestures and a frozen Brain cue cannot change its pixels when activity expires. Lounge names
are staggered on the whole map and compact in the close camera. Portrait caching and all 25 identities remain.
[Current evidence, provenance and editing guide](design/robot-office/lounge/README.md).
This follow-up changes no backend, media processing or publishing behavior. PR #14 stays draft/unmerged.

The preceding living-office checkpoint started at `a119dfd`: the owner asked for believable proportions, idle robots in a
lounge, seated work, actual document transfers and an animated Brain. This supersedes idle-at-station placement.
The 960×640 floor plan now gives all 25 identities individual lounge seats, room-sized desks/chairs and walkable
aisles. `OfficeMotion.ts` follows current snapshots and fresh confirmed report/stage events: both robots approach,
one document passes between them, then both return to their latest actual destination. It never delays a backend
job or guesses a future transition. Paused/unavailable roles rest; Reduced skips walking; stale/hidden views freeze
and recovery uses the current snapshot without replaying old transfers. `BrainCore.ts` has layered neural lobes,
synapse lights and depth-sorted orbits: ambient **Standby** is decorative, **Processing** follows actual Brain
state/events, and Paused/Reduced/offline still the art. A room camera makes the furniture and robots inspectable.
The Canvas compatibility renderer now uses the same floor plan, seats and transfer controller.
Evidence: [living office and labeled controlled preview](design/robot-office/living/README.md).
This frontend-only follow-up adds no dependencies or processing/publishing behavior. PR #14 stays draft/unmerged.

The preceding visual checkpoint started at `c33a291`: the owner chose **refined retro pixel art** and asked to use better
graphics tools. The office now uses pinned PixiJS 8.22.0 with authored cast-specific artwork, layered room furniture
and a scoped studio shell. Team/detail portraits share one cached offscreen renderer. Existing job snapshots and
events still control states, walks, reports and decisions; this adds no processing or publishing behavior.
Graphics initialization/module failure restores the original Canvas map. Full / Reduced / Follow system remain.
The Windows install screenshot showed nested archive folders exceeding the standard path limit: use fresh ZIP
contents directly in `C:\CF14`, with `test-isolated.bat` there, creating a new `.venv`. Do not copy a partial environment.
The launcher now explains this when a long root may cause dependency setup to fail; no registry change is required.
Visual evidence and tool/edit instructions: [refined office](design/robot-office/retro/README.md).

Continue existing draft PR #14 on `claude/project-thread-vw1n9y`; keep it unmerged. This continuation started at
`fea045d` (previous code review `cf54204`). Default remains `claude/wonderful-ritchie-909tq3` at `eff96fb`.
The owner explicitly superseded selected-only new uploads and hiding idle robots. New Public uploads require
explicit setup/consent and eligible platform capability. Existing posts and scheduled Private uploads retain their
visibility. Never send test videos to owner accounts, buy hosting, deploy, or change account permissions.

## Implemented in this continuation

* All 25 robot identities remain individually visible at desks or reserved lounge places, with named labels and
  overhead state icons. Task selection includes shared references, dependencies, blocked reason and next robot.
  Saved motion choices: Follow system / Full / Reduced; Full overrides OS reduced motion. Stale state stops
  animation. Decorative recreation preserves actual state, work priority and genuine document handoffs.
* Brain at `#/brain`: durable searchable documents/instructions/skill guides, good/bad example uploads and feature
  labels, revision approval, edit/disable/delete/export, performance history and recorded per-clip influence.
  `autopilot/knowledge.py`, `knowledge_routes.py`, additive `brain_knowledge`/`brain_influences` tables. Uploaded prose
  is reference text, not executable code or model fine-tuning. Only supported approved caption/pacing preferences
  affect new blueprints; topic tags scope them. Examples never become posting results. Export includes all saved
  metadata/text/influences, without browsing caps; original uploaded files are downloaded separately.
* Demonstration: actual document upload + approval → later validated/persisted blueprint changes bold captions to
  minimal. Both instruction and bad-example later-plan regression tests pass. Screenshot/proof JSON record the
  saved decision; Try a decision is separately labeled a preview.
* Discovery: audience/topic terms, exclusions, language evidence, source-score floor and complete-story filter;
  curated/manual inputs retained. Metadata audience relevance and clip potential are estimates, not verified US
  viewers or promises of virality. Automatic repetitive/weak/unsuitable-live candidates are declined with reasons.
* Final check returns bounded repair work to SPLICE / GLYPH / STORY / QUILL with exact reasons and shared references.
  Two repair attempts maximum; uploads already using a file and user edits/cancellation are protected. Timestamp
  checks detect A/V offset and duration problems, not semantic lip sync. Missing sound is detected before Whisper;
  silent live segments are retained/skipped and later audio resumes; mixed final recordings retain returning
  sound with silent timeline gaps, temporary assembly files are removed, and all-video-only sources fail clearly once.
* New Public YouTube uploads and standing automation use explicit audience confirmation, connected-channel and
  visibility-bound permission, audit confirmation, limits and exact-byte checks. Public lead is zero, so local
  uploads start at due time without `publishAt`. Existing Private schedules remain Private. Actual returned
  restrictions are reported. Clearing audit confirmation blocks new automatic Public approvals/uploads.
  TikTok Everyone remains eligible-app + creator-options + per-post consent; inbox
  drafts/manual packages are honest fallbacks. No standing TikTok automatic consent.
* Learning separates confirmed-public and selected-viewer cohorts; unconfirmed/requested visibility does not drive
  learning. Both learners require 48-hour maturity. Cached weights/styles/posting-time data cannot carry over when
  the configured audience changes. Existing bounded updates, rollback, source diversity and sample guards remain.
* Measured real stage intervals: `/api/office/performance`, `python -m clipfoundry performance --days 7`.
  Pause/Stop controls are re-read atomically when the worker claims a job, preventing a stale preliminary
  state read from starting new work after the control was committed. Two deterministic regressions reproduced
  the old race and now pass. Database first-use migrations share a cross-process/thread lock and commit before
  another initializer reads the schema; old-project preservation and concurrent startup regressions pass.
  Separate Windows launcher `test-isolated.bat`: own `data\pr14-test`, videos, `.venv` and port 8899.

## Validation

Latest lounge validation is recorded at the top of [IMPLEMENTATION_STATUS.md](docs/IMPLEMENTATION_STATUS.md).
The full fast suite passed **641 tests**, with seven slow cases deselected, in 280.30 s. All **23 focused browser
checks passed together in 6.4 min**. Final TypeScript/Vite build passed (5.83 s; existing lazy 904 KB graphics chunk
warning); all 14 distribution files are SHA-256 identical to the assets used in that final browser run.
Actual isolated desktop/laptop/mobile captures have 25 robots, visible laptop controls, no mobile horizontal
overflow and zero page errors. Both 1440×900 H.264 recordings have zero page errors: 33.24 s of actual stopped
off-duty animation, and 33.48 s of visibly labeled controlled work/Brain/stage fixtures. Only startup before the first
visible provenance banner was trimmed; animation was not retimed. Neither measures processing
speed. Prior slow media cases were not repeated for this frontend-only checkpoint.

At the preceding living-office checkpoint:
Production TypeScript/build passed; 17 office Python checks passed in 6.10 s and all 17 focused browser cases passed
together in 3.1 min. The browser cases cover lounge seats,
walk/sit/return, same-job document passing, event freshness/identity, Pause cancellation, Brain standby/processing/
pause, Reduced still frames, camera, fallback, portrait/navigation and desktop/laptop/mobile layout, plus current
sender recovery after hidden/paused stages and protection against reset-history replay. Evidence is
separated into actual isolated snapshots and visibly labeled controlled animations; neither is a GPU benchmark.

The preceding refined-art validation: TypeScript/production build passed, 17 office Python tests passed (7.20 s), and all ten focused motion/robot/
graphics browser cases passed together (59.3 s). Actual desktop/laptop/mobile captures recorded zero browser errors;
the separate animation video is visibly labeled as controlled test states. A pixel regression verifies COMMAND's
approval looks different from idle even in Reduced mode. Static floor/furniture is cached once; portrait cache is bounded.
The earlier 641-test and complete-media results below belong to `c33a291`; those suites were not repeated during
that refined-art checkpoint. The latest fast rerun above is separate. Windows batch execution, PC graphics/scaling
and GPU checks remain owner checks. That refined-art checkpoint added only PixiJS; the latest lounge also adds GSAP.
Playwright and GPU pins remain unchanged.

The original master-continuation results below belong to the earlier `c33a291` checkpoint, separately from the
latest fast rerun. Its complete fast suite passed **641 tests** (263.21 s; seven slow cases deselected).
All seven slow cases passed across the full run
(six passed) and the corrected complete-loop rerun (one passed); the test now waits for both durable published
schedules before advancing fake result maturity. Ten browser checks passed across the sandbox run and targeted
Brain/Public-loop reruns. The Public browser loop includes two posts, restart, results, live capture and pause.
Production frontend TypeScript/build passed. Focused startup/core/office/TikTok: 66 passed; publishing: 44;
knowledge/public: 17; full Brain export: 8; public-audit/automation: 33; timing/office: 19; returning-audio/recovery: 28.
A database made using `fea045d` opened under the new additive schema with project/clip/settings/private
schedule/audience/approval and media bytes unchanged. No owner data was accessed.

Visual assets: [design/robot-office/screenshots/README.md](design/robot-office/screenshots/README.md). It distinguishes
actual isolated app/jobs, synthetic transcripts, saved blueprint decisions, lookup previews and controlled animations.

## External limits and remaining owner checks

Official developer hosts returned proxy **403** in this continuation. Current YouTube/TikTok requirements could not
be freshly re-read. Google’s official GitHub discovery schema was reachable and confirms `publishAt` requires
Private; this is an API field check, not current policy approval. Earlier policy readings are labeled historical in
PLATFORM_CAPABILITIES. The audit settings record the owner’s confirmation, not programmatic proof of app approval.

Not verified here: RTX 3050 CUDA transcription / NVENC rendering; real accounts, scopes, Google project audit and
returned Public visibility; TikTok app eligibility and approval, real Direct Post/inbox; Windows setup, fonts,
scaling; live network access on the owner’s PC; real NVIDIA services. Run the
[Windows test guide](docs/WINDOWS_PR14_TEST.md) in a separate copy first. No real posts, purchase or deployment occurred.

[Server recommendation](docs/PERFORMANCE.md): keep the PC until its real timing/GPU report supports a comparison;
a server can improve uptime but does not remove platform restrictions. No general randomized experiment system,
unique-viewer/dominant-video rule, new Twitch/Kick/Reddit/X/Instagram/podcast connectors or preview-before-download
screen was added. Knowledge controls are intentionally typed; arbitrary prose does not automatically alter decisions.

## Do not break

Keep `.mcp.json`, GPU dependencies and `e2e/tests` unchanged; no Playwright pins. Commit built `frontend/dist`.
Preserve exact-file quality/approval hashes, reuse eligibility, access guards, account-bound consent, limits,
duplicate prevention/recovery and emergency stop. No silent CPU fallback in Autopilot. Never fabricate processing
progress, metrics or visibility; keep decorative recreation visibly separate from actual job activity.
PR #14 stays draft/unmerged until the owner decides otherwise.
