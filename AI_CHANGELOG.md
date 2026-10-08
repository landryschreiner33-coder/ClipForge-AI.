# AI changelog

Development checkpoints made by AI assistants, newest first. Each one says what changed, why, what was actually run
and what was not. The same checkpoints, in machine-readable form, are in `.clipfoundry/ai-change-log.jsonl` (shown
read-only in Settings → Advanced → Dev Log). Work before October 7, 2026 is not repeated here: it is recorded in
`docs/IMPLEMENTATION_STATUS.md` (plan, matrix and test log) and in the Git history.

Commit ids are snapshots of a branch at the time of writing; fetch before relying on them.

## 2026-10-08 · Public publishing, teachable Brain and complete robot office

* **Tool:** Codex. **Branch:** `claude/project-thread-vw1n9y`, existing draft PR #14. **Base:** `fea045d`.
  **Result:** the commit containing this entry. PR stays draft and unmerged.
* **What changed:** all 25 named robots remain readable with real job states, dependencies/handoffs and saved
  Follow system / Full / Reduced motion. Brain supports safe local document/good/bad example uploads, search,
  revision approval/edit/disable/delete, complete metadata/text/influence export and immutable later-plan influence.
  Approved typed preferences alter new blueprints; uploaded prose is inert and examples never become posting results.
  Discovery uses topic/language/freshness/relevance evidence and explains estimates and weak-story filters.
  Final checks send bounded repairs to the responsible stage. Video-only sources fail before Whisper; live
  segments with missing audio preserve the timeline and returning audio. Existing GPU execution paths remain.
  Explicit NEW Public YouTube automation uses channel/audience-bound consent, recorded project-audit confirmation,
  exact-file checks, limits and local due-time uploads without `publishAt`; old Private schedules remain Private.
  TikTok still needs eligible app/creator options/per-post consent, with truthful draft/manual fallbacks.
  Learning separates public/selected cohorts and waits 48 hours. Added stage timing report and isolated Windows launcher.
* **Final regression fixes:** Pause/Stop is checked atomically when claiming work; database migrations are serialized
  across threads/processes and committed before the next initializer; clearing the YouTube audit confirmation blocks
  new automatic Public approvals/uploads while preserving Private permissions; Brain export removes browsing caps.
  The Windows GPU-check command explicitly selects test data and distinguishes CUDA proof from NVENC render proof.
* **Why:** the owner's continuation prompt supersedes selected-only new uploads and hidden idle robots, while
  preserving existing visibility/data, platform restrictions and the unmerged PR.
* **Validation:** 641 passed, 7 deselected in 263.21 s. All seven slow cases and ten sandbox browser checks passed across initial
  runs and targeted reruns, with exact outcomes/fixture corrections in [IMPLEMENTATION_STATUS](docs/IMPLEMENTATION_STATUS.md).
  TypeScript/production build passed. Focused startup/core/office/TikTok: 66 passed; full Brain export: 8;
  public-audit/automatic-publishing recheck: 33; publishing: 44; returning-audio/recovery: 28.
  Disposable old-schema upgrade preserves rows/approval/media bytes. Before-fix reconstructions fail the new
  Stop/startup/export regressions. Tests use synthetic media/transcripts and local fake publishing, with real
  FFmpeg; no owner accounts/data or real uploads.
* **Evidence:** [screenshots, actual job animation, controlled motion demo and saved Brain influence](design/robot-office/screenshots/README.md).
  [Processing measurements/server advice](docs/PERFORMANCE.md) and [separate Windows ZIP test](docs/WINDOWS_PR14_TEST.md).
* **Not verified / blocked:** RTX 3050 CUDA/NVENC, Windows setup/fonts/scaling, real network intake and connected
  account scopes/project/app approvals/returned Public visibility. Official developer hosts returned proxy 403;
  current policies could not be freshly verified. Google's reachable official GitHub schema confirms only the
  `publishAt` field contract. Audit settings record owner confirmation, not programmatic approval.
  No server purchase, deployment, account permission changes or real posts occurred.

## 2026-10-08 · PR #14 review round

* **Tool:** Claude Code (cloud session). **Branch:** `claude/project-thread-vw1n9y` (draft PR #14), on top of
  `f71238c`. **Result commits:** `cf54204` (code) and the commit that adds this entry (docs).
* **What changed**
  * Public video importing stays on (owner, 2026-10-08). The beginner browser test now expects public videos to be
    clipped on the PC, to pass the final check and never to be planned or posted; the beginner answers *who
    watches* before anything is planned. A rule recorded after a video was clipped now reaches that video.
  * TikTok: a post-it-yourself page for the ready-to-post package (download, copy caption, steps, then link the post
    or mark it posted, `POST /scheduled/{id}/posted`); branded content only for Friends; a full inbox (5 pending
    drafts) holds TikTok posts for a day; labels that don't claim who could see a post. *I shared it* updates the
    post itself; held public posts can be sent to the selected viewers from their page.
  * Approvals and the automatic-publishing permission name the connected account; another account connected means a
    new approval. START pressed again before its work ran queues nothing new.
  * Brain and learner: uploads nobody else could watch are not evidence (*unconfirmed*), maturity counts from
    sharing, each platform rolls back on its own, a rollback or reset is not undone by the same results, 20 clips
    per side, identical results are inconclusive, the learner needs views and 5 videos.
  * Health: GPU errors and CPU fallback, accounts as information, *Unknown — not updating* when the feed is lost, a
    size-bounded `workers.log`, discovery stalls. Integration cards: Test connection, last check, rate limits.
  * Trend and Source Scores: missing parts count as neutral, with coverage, confidence and the missing parts stored.
    Video access failures carry one of 13 reasons; a named wait is honored, temporary problems are retried.
  * Robots: the crown badge of COMMAND and the managers, TRACKER green, SPARK's blue eye, PATCH's orange lamp;
    contact sheet re-captured. Setup and Sources text no longer say other people's videos are skipped.
  * Docs: privacy page (Test connection result, log sizes, the account an approval names, posts you made yourself),
    `docs/OFFICE.md`, `docs/PLATFORM_CAPABILITIES.md`, INSTALL and README (TikTok), AGENTS.md decisions, this file,
    `AI_HANDOFF.md`, `docs/IMPLEMENTATION_STATUS.md`.
* **Why:** the owner's follow-up of October 8, 2026 (compare with the spec, fix the beginner test without disabling
  public videos, recheck TikTok, verify the Brain, steps to test on the PC).
* **Tests run:** listed in the JSONL entry and in `docs/IMPLEMENTATION_STATUS.md` (test log).
* **Not verified:** GPU on the RTX 3050, real YouTube and TikTok accounts, TikTok's decision on the app, Windows.

## 2026-10-07 · The robot office screens, docs and handoff

* **Tool:** Claude Code (cloud session). **Branch:** `claude/project-thread-vw1n9y` (draft PR #14), on top of
  `26f6b8f`. **Result commit:** the commit that adds this entry.
* **What changed**
  * The app's places are now Office, Missions (the former Autopilot page), Clips (the former Library), Queue (the
    former Posts) and Settings; old addresses open the new pages in place.
  * Office: a pixel-art office (layout of reference image A) whose 25 robots stand where their real jobs are, walk
    and carry reports from the event feed, and rest in the Lounge; details panel (overview, robot, room), activity
    feed, bottom bar (Start, Pause, Resume, Stop all, Pause publishing), list view, Reduce animations, a stale mark
    when the feed is lost. Team roster (`#/office/team`) and developer gallery (`#/dev/robots`).
  * Settings → Integrations: who watches your uploads per platform (selected viewers, only you, keep on this PC),
    "My viewers changed", each connection's capabilities, NVIDIA AI setup with opt-in, check, small test and
    disconnect. Settings → Advanced: the Brain's limits and the Dev Log.
  * Clips → Test feedback; the Queue shows who each post is for, what really happened and whether results exist.
  * YouTube readings mirrored into the Brain now follow the 30-day YouTube data rule like the readings themselves.
  * Two slow video tests that `26f6b8f` missed now expect YouTube uploads as Private without `publishAt`.
  * Docs: `docs/OFFICE.md`, `design/robots/README.md`, this file, `AI_HANDOFF.md`, README beginner steps and NVIDIA
    setup, privacy page (NVIDIA excerpts, tester answers, office and learning records, audience records).
* **Why:** the owner's master prompt for the robot office (October 7, 2026), sections 15-23 and 26.
* **Tests run:** listed in the JSONL entry and in `docs/IMPLEMENTATION_STATUS.md` (test log).
* **Not verified here:** GPU transcription and rendering on the RTX 3050, real YouTube or TikTok uploads, real
  invitations, TikTok's audit, real NVIDIA requests, Windows-specific behavior.

## 2026-10-07 · Selected audience, office backend, Brain guards and optional NVIDIA AI (`26f6b8f`)

* **Tool:** Claude Code (cloud session). **Branch:** `claude/project-thread-vw1n9y`. **Base:** `eff96fb`.
* **What changed**
  * Uploads go only to a selected audience: YouTube Private without `publishAt`, with viewers you invite in YouTube
    Studio; TikTok followers or friends through an audited Direct Post, otherwise a ready-to-post package. Public,
    unlisted and Everyone are blocked on every path; posts planned before keep their audience and old public ones
    are held. Approvals and automatic uploads are bound to the audience stamp (`APPROVAL_SCHEME = 3`, Private-only
    consent v2). Pause publishing.
  * Office backend (`clipfoundry/office`): the cast registry, the event feed with a resume cursor, managers'
    reports, the Director's recorded decisions at four checkpoints, health readings, room details, controls,
    capability registry and integration cards.
  * Brain (`autopilot/brain.py`): observations with provenance, null kept apart from zero, idempotent CSV import
    with preview, corrections kept; strategy changes need 30 mature clips from 5 videos in one selected audience,
    move at most 10%, wait for new results and roll back. The older learner follows the same guards.
  * Optional NVIDIA text AI (`pipeline/nvidia.py`), off by default, with opt-in, budgets and local fallback.
* **Why:** the same master prompt, sections 9-14 and 21-22.
* **Tests run:** `pytest -m "not slow"`: 543 passed (new suites `test_audience`, `test_office`, `test_brain`,
  `test_nvidia`).
* **Not verified here:** as above.
