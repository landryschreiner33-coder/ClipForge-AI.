# AI handoff

Start here if you are an AI assistant continuing work on ClipFoundry. Read [AGENTS.md](AGENTS.md) for the rules; this
file is the **current state**. Branch and commit references are a **snapshot** taken when this file was written
(see the date), not live repository state: check `git log` and the open PRs.

_Snapshot: 2026-10-07, branch `claude/clipfoundry-office-audience`, draft PR #15 into the default branch
`claude/wonderful-ritchie-909tq3`._

## Current goal

The owner's brief, `ClipFoundry_Claude_Final_Master_Prompt_2.md` (2026-10-06; it is not in the repository and was
attached to the request), asks for:

- selected-audience delivery on YouTube and TikTok, with public never allowed;
- real role collaboration (Director, managers and workers) over the durable queue;
- a test-audience Brain that learns carefully;
- the animated 25-robot office;
- an optional NVIDIA text-AI adapter;
- health states;
- this handoff system.

## Architecture in one screen

- **Backend.** A FastAPI app (`clipfoundry/api.py`) with SQLite (`db.py`) and a durable job queue
  (`autopilot/queue.py`). Worker threads live in the Autopilot host process (`autopilot/host.py`).
- **Who can see an upload.** `audience.py`. Every upload path calls `audience.check`.
- **Brain.** `brain.py` holds the observations (provenance, cohort, versioned corrections), the CSV import, and
  `evaluate_length`, the only automatic strategy. `hunter.project_options` → `brain.ranking_options` feeds new
  Autopilot projects. `autopilot/learner.py` keeps public-audience learning and hands audience-tagged results to the
  Brain.
- **Office.** `office.py` records a worker report, a manager review and a Boss decision from each job outcome,
  through hooks in `host._run`. It serves the snapshot and the cursor feed (`office_routes.py`).
- **Health.** `health.py`.
- **NVIDIA.** `pipeline/nvidia.py`. It is used through `llm.py` when the provider is `nvidia`, and has its own
  `rank_moments` with strict validation.
- **Frontend.** `frontend/src/office/` (Office page, feed hook, panels, Test feedback, Integrations) and
  `frontend/src/robots/` (sprite registry and art). Navigation: Office, Missions, Clips, Queue, Settings.

## Verified working (in a Linux cloud container, no GPU, no real accounts)

- Unit and contract tests with fake YouTube/TikTok (`tests/fake_platforms.py`). See the last entry of
  [AI_CHANGELOG.md](AI_CHANGELOG.md) for exact counts.
- Slow end-to-end tests with real ffmpeg renders, synthetic espeak speech and fake platforms. That covers the full
  Autopilot loop through a private YouTube upload and Brain observations.
- The Office UI was checked in Chromium against scratch backends at 1280×720, 1366×768 and 400 px wide. Screenshots
  are in `design/ui-office/screenshots/`.

## Not verified (needs the owner's PC or accounts)

- CUDA transcription on the RTX 3050. GPU code and dependencies were not changed.
- Real YouTube private upload plus Studio invitations; real TikTok Followers/Friends posting (needs an audited app)
  and the manual package flow on a phone.
- A live NVIDIA request. No key was used, and NVIDIA's current terms were not re-read in this session.
- Office frame rate and resource use with the pipeline active.

## Known problems and gaps

- Roles BOOST, GLYPH, LOCK and METRIC have no job kind of their own. Their work runs inside a neighbour's job, so
  they show idle. Splitting jobs would let them move truthfully.
- Manager reviews are deterministic rules over job outcomes (`office-rules.v1`). There is no QC visit to other
  departments yet beyond the Final Quality Gate's own job.
- `brain.assign_variant` / `compare_arms` exist and are tested, but no experiment is started automatically yet.
- `nvidia.rank_moments` is tested but not yet called from `pipeline/candidates.py`. The pipeline uses NVIDIA through
  `llm.evaluate` when the provider is `nvidia`.
- The old `components/RobotOffice.tsx` and `RobotArt.tsx` are unused and could be removed. The main JS bundle is
  about 657 kB.

## Do not break

The AGENTS.md rules, especially:

- 13: never public;
- 14: robots never invent work;
- 15: cloud AI is optional;
- 2: approval for every post;
- 3: publish exactly what was checked;
- 4: no silent CPU fallback.

Never upgrade GPU dependencies casually, never change `.mcp.json`, and keep `e2e/tests` read-only.

## Next useful work

1. Run the owner's-PC checklist at the end of `docs/IMPLEMENTATION_STATUS.md`, plus a real private YouTube upload
   with one invited viewer.
2. Wire `nvidia.rank_moments` into candidate ranking behind the same budget, then compare it with the local baseline
   on a small fixture set before recommending it.
3. Give LOCK, METRIC and GLYPH their own job steps where it is natural, so the office shows them truthfully.
