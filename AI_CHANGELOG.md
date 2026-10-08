# AI development changelog

Development work by AI assistants, newest first. This file records development, not runtime robot activity, which
belongs in the app's own event log. The same entries, in machine-readable form, are in
`.clipfoundry/ai-change-log.jsonl`, and the Office's Dev Log shows them read-only. Earlier work, before this file
existed, is summarized in `docs/IMPLEMENTATION_STATUS.md` and `AGENTS.md`; no history is invented here for it.

Format of an entry:

- UTC time
- tool/model (when known)
- branch
- base → result commit
- what changed and why
- tests actually run, with results
- limitations
- follow-ups

---

## 2026-10-07 — Selected audiences, the Brain, NVIDIA adapter, robot office

- **When:** 2026-10-07, 13:00–20:00 UTC (approximate).
- **Tool:** Claude Code (cloud session). Model identity is not recorded here, per repository policy.
- **Branch:** `claude/clipfoundry-office-audience`, draft PR #15. Base `eff96fb`; result is the branch head when the PR
  is marked ready.
- **Why:** the owner's brief, `ClipFoundry_Claude_Final_Master_Prompt_2.md` (2026-10-06): never public, selected
  test audiences on both platforms, real role collaboration, a test-audience Brain, the 25-robot office, an optional
  NVIDIA adapter, health states and handoff files.

**What changed**

- `clipfoundry/audience.py`: one audience policy (LOCAL_ONLY, OWNER_ONLY, SELECTED_AUDIENCE).
  - Public, unlisted, `PUBLIC_TO_EVERYONE` and `publishAt` are refused on every upload path.
  - Approvals are bound to `policy_version`.
  - Visibility drift halts a destination.
  - TikTok Followers/Friends go direct only for audited apps; otherwise a manual posting package is made.
  - Older settings migrate without widening anything.
  - Scheduler, publisher, publish routes and jobs were updated; YouTube uploads are always private with no publishAt.
- `clipfoundry/brain.py` and `/api/brain`:
  - Observations with provenance (platform_api, owner_import, tester_feedback), cohorts and versioned corrections.
  - CSV preview and idempotent commit, and tester ratings labeled self-reported.
  - Brain states, and per-clip analytics states.
  - Guarded clip-length learning: at least 30 clips from 10 sources, a 2-SE difference, at most 10% per step,
    rollback.
  - Deterministic experiment assignment.
  - The public learner now skips audience-tagged posts.
- `clipfoundry/pipeline/nvidia.py` and `/api/integrations`: optional NVIDIA text AI.
  - Off by default and opt-in; the key goes to the approved host only, with no redirects.
  - Request, token and spend budgets are reserved atomically before dispatch, and an unknown price blocks production
    use.
  - Never used for unattended Autopilot work in preview mode.
  - Answers are validated, with at most one repair, then the local fallback.
  - Breaker and cache.
- `clipfoundry/office.py`, `health.py`, `office_routes.py`:
  - Worker reports, manager reviews and Boss decisions are recorded from real job outcomes.
  - Office snapshot plus a cursor event feed with gap detection.
  - Control bar actions: start, pause, resume, stop, pause publishing.
  - Healthy, Degraded, Error or Unknown checks.
  - Read-only Dev Log API.
- `frontend/src/robots/`: 25 code-drawn pixel robots plus CORE (4 directions, 12 states), a roster and a dev gallery.
  Built by a parallel agent in its own worktree, then merged.
- `frontend/src/office/` and the rest of the app (built by a parallel agent in its own worktree, then merged):
  - Navigation: Office, Missions, Clips, Queue, Settings, with redirects from old addresses.
  - The Office page: rooms, robots on real state, detail panel, activity feed, control bar, "Selected audience"
    footer, list view and reduced motion.
  - Test feedback form and CSV import.
  - Integrations cards: audience, NVIDIA.
  - Queue: the manual posting package and the invited-viewers step.
- Docs:
  - New: `docs/AUDIENCE.md`, `BRAIN.md`, `NVIDIA.md`, `OFFICE.md`.
  - Updated: README, INSTALL, PLATFORM_CAPABILITIES, AGENTS.md (rules 13–15 and the handoff convention), and the
    privacy policy and terms.
  - Handoff files: `AI_HANDOFF.md`, this file and the JSONL log.

**Tests actually run** (Linux container, Python 3.12, ffmpeg, espeak-ng installed during the session, no GPU)

| Suite | Result |
| --- | --- |
| `pytest -m "not slow"` before any change | 490 passed, 7 deselected |
| `pytest -m "not slow"` on `ad054e5` | 549 passed, 1 failed, 7 deselected |
| After that failure was fixed | the failing file re-run: 11 passed |

The failure was an expected-message change in `test_approval_rules_and_invalidation`: the audience rule now answers
before TikTok's own rule.

**Slow tests (`pytest -m slow`)**

- Full run: 5 passed, 2 failed.
- The 2 failures were tests that assumed default posting or publishAt. Both were fixed and re-run individually: both
  pass.
- One earlier run could not build videos because espeak-ng was missing; it was then installed.

**Frontend:** `tsc --noEmit` passes and `npm run build` passes. The Office was checked in Chromium (Playwright)
against scratch backends: layouts, keyboard, list view, connection lost, controls and the report walk.

**Limitations**

- No GPU, no real YouTube or TikTok accounts and no NVIDIA key in this session. None of those paths was verified live.
- NVIDIA terms and the platform help pages were not re-read here.
- e2e specs were updated for the new navigation and Office (commit `5a251ce`). Results:
  - `npm run test:sandbox`: 8 passed.
  - Read-only `e2e/tests` against a throwaway sandbox (never real data): 61 passed, 1 skipped (no post was waiting
    for approval).
  - Both ran with the preinstalled Chromium 1194 via `CLIPFOUNDRY_E2E_CHROMIUM`.
- The beginner-flow spec turns off "Find public videos to clip" as a setup step, as `tests/test_autopilot_simple.py`
  does.

**Follow-ups:** listed in `AI_HANDOFF.md` under "Next useful work".
