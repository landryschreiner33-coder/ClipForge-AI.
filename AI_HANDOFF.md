# AI handoff

Read [AGENTS.md](AGENTS.md), this file, [docs/OFFICE.md](docs/OFFICE.md) and
[docs/PLATFORM_CAPABILITIES.md](docs/PLATFORM_CAPABILITIES.md). Snapshot: 2026-10-08. Fetch before trusting branch state.

## Current scope and branch

Latest visual checkpoint starts at `c33a291`: the owner chose **refined retro pixel art** and asked to use better
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

* All 25 robot identities remain individually visible at desktop stations, with named labels and overhead state
  icons. Task selection includes shared references, dependencies, blocked reason and next robot. Saved motion
  choices: Follow system / Full / Reduced; Full overrides OS reduced motion. Stale state stops animation.
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

The refined-art validation is recorded separately at the top of [IMPLEMENTATION_STATUS.md](docs/IMPLEMENTATION_STATUS.md).
Latest: TypeScript/production build passed, 17 office Python tests passed (7.20 s), and all ten focused motion/robot/
graphics browser cases passed together (59.3 s). Actual desktop/laptop/mobile captures recorded zero browser errors;
the separate animation video is visibly labeled as controlled test states. A pixel regression verifies COMMAND's
approval looks different from idle even in Reduced mode. Static floor/furniture is cached once; portrait cache is bounded.
The earlier 641-test and complete-media results below belong to the preceding `c33a291` checkpoint; they were not
re-run in full for this graphics-only follow-up. Windows batch execution, PC graphics/scaling and GPU checks remain
owner checks. PixiJS is the only deliberately added frontend dependency; Playwright and GPU pins remain unchanged.

Current final results and exact commands are recorded at the top of [IMPLEMENTATION_STATUS.md](docs/IMPLEMENTATION_STATUS.md).
The complete final fast suite passed **641 tests** (263.21 s; seven slow cases deselected). All seven slow cases passed across the full run
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
duplicate prevention/recovery and emergency stop. No silent CPU fallback in Autopilot. Never fabricate progress,
metrics, visibility or animation activity. PR #14 stays draft/unmerged until the owner decides otherwise.
