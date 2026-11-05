# ClipForge studio upgrade: requirement matrix

Source of the requirements: [CLIPFORGE_STUDIO_UPGRADE_CLAUDE_PROMPT.md](../CLIPFORGE_STUDIO_UPGRADE_CLAUDE_PROMPT.md)
(sections 1–15, acceptance scenarios CF2-01 to CF2-31). Working branch: `claude/project-thread-x72wkd`.

Status words:

- **Implemented**: the code exists in this branch.
- **Tested**: an automated test in this branch exercises it (named in Evidence). Fake platforms, fake HTTP transports and
  synthetic media only; nothing real was signed in to, uploaded, published or deployed.
- **Partial**: some of the requirement exists; the gap is named.
- **Not started**: nothing new yet (what already existed before this upgrade is described).
- **Blocked**: needs something this environment does not have; the missing thing is named.

Separate events, never implied by each other: source implemented → tested → merged → packaged → website published →
cloud deployed. As of this file, nothing from this branch is merged, packaged, published or deployed.

## Baseline (2026-11-05)

| Check | Result |
| --- | --- |
| Starting point | Default branch `claude/wonderful-ritchie-909tq3` @ `12afd01` (PR #16–#19 merged) plus `codex/review-clipforge-pr16` @ `0b723c0` (renderer repair `fc0664c`, this handoff), merged as `6c3f8d9`. |
| Fast suite on `6c3f8d9` | **1,630 passed**, 21 deselected (slow), 10 min 55 s, clean worktree. |
| Slow suite on `6c3f8d9` | Running; recorded in `AI_HANDOFF.md` when it finishes. |

## Acceptance scenarios

| ID | Scenario | Status | Evidence / what remains |
| --- | --- | --- | --- |
| CF2-01 | Dark before first paint; no light option; other preferences kept | Not started | Light/System themes still exist (`frontend/src/prefs.tsx`). |
| CF2-02 | Studio: two choices, current work, integrated Office; no sideways scroll | Partial (existing) | Home has the two choices and a robot team; Office is still a separate page. |
| CF2-03 | YouTube URL variants import into the clip pipeline with recoverable progress | **Implemented, tested** | `studio/link_import.py`; `tests/test_studio_links.py` (variants, refusals, real yt-dlp on a fake transport, cancel, retry, restart). Real YouTube not reachable here. |
| CF2-04 | Full stories from a link: mode/guidance/destinations survive | **Implemented, tested** (import side) | Mode, style, choices and destinations are frozen before download (`test_link_enters_the_same_pipeline…`, `test_youtube_link_needs_no_search_key…`). Story splitting itself is the existing Full stories pipeline. |
| CF2-05 | 100+ mixed assets, no count rejection, bounded memory | Not started | Uploads are resumable; the full-video engine builds one FFmpeg graph with every input. |
| CF2-06 | Several voiceover/music/effect files as tracks | Not started | One optional music file today. |
| CF2-07 | Whole project opens in the editor after the rough cut | Partial (existing) | Review page has preview, outline, sequence, versions. |
| CF2-08 | Reorder/trim/split/replace/add, reopen, undo/redo | Partial (existing) | Trim/move/split/include and revisions exist; replace, add after the rough cut, undo/redo do not. |
| CF2-09 | Supported correction → validated proposal → new revision → revert | Partial (existing) | Four fixed phrases (`video_flow.parse_request`). |
| CF2-10 | AI off/timeout/malformed: manual work unaffected | Partial (existing) | No AI path in the editor yet. |
| CF2-11 | Enabled style/skill changes a real plan/render field | Implemented (existing) | `test_studio_guidance.py`, `test_studio_render.py`. |
| CF2-12 | Project override wins; no global mutation | Implemented (existing) | Same suites. |
| CF2-13 | Reuse/publishing permission kept apart from Brain lessons | Implemented (existing) | `test_review_brain_separation.py`. |
| CF2-14 | Rename every bot including Core and managers | Partial (existing) | Names exist (`studio/prefs.py`); coverage of every surface not verified. |
| CF2-15 | Run/pause/retry/cancel/restart: truthful rooms and states | Partial (existing) | |
| CF2-16 | Idle and restart a migrated discovery profile: no source searches | **Implemented, tested** | `config.DISCOVERY_RETIRED`, `db._migrate_discovery_retired`; `tests/test_discovery_retired.py`. Screens updated. Dormant engine code and its older suites remain (see below). |
| CF2-17 | Re-render after approval needs new approval | Implemented (existing) | Approval-hash suites. |
| CF2-18 | Audio regression set | Implemented (existing) | Slow audio suites (rerun pending). |
| CF2-19 | Multiple destinations, never the wrong account | Implemented (existing) | `test_multi_accounts.py`. |
| CF2-20 | Cross-workspace access refused | Implemented (existing) | `test_cloud_auth.py`. |
| CF2-21 | Customize studio with save/cancel/reset | Not started | Appearance settings exist; no Customize studio entry. |
| CF2-22 | Keyboard/reduced motion 320–1440 px | Partial (existing) | |
| CF2-23 | Verified native install/update | Not started | Needs Mac/Windows runners and owner approval to release. |
| CF2-24 | Published website download matches artifacts | Not started | Publishing needs owner approval. |
| CF2-25 | Reference video analysis covers the selected timeline | Not started | |
| CF2-26 | Apply/edit/disable a learned example style | Not started | |
| CF2-27 | No vision model / interrupted analysis: honest labels | Not started | |
| CF2-28 | Find and import an image and a sound effect | Not started | Provider hosts are not reachable from this environment; fake providers will be used for tests. |
| CF2-29 | Missing key, quota, removed source: useful errors, offline render | Not started | |
| CF2-30 | Unknown license / malicious metadata | Not started | |
| CF2-31 | Automatic supporting media for one project | Not started | |

## Retired discovery: what stays in the source

Automatic discovery cannot run in the product, but its modules (`autopilot/scout.py`, `trends.py`, parts of
`hunter.py`, `live.py`'s `live_watch`) are still in the source because submitted videos share their queue, download,
analysis and publishing code. The suites that tested discovery itself run with `config.DISCOVERY_RETIRED`
patched off for that test only (`tests/conftest.py`, `_historical_discovery_contract`). They are dormant-engine
coverage, not product behaviour; delete them with the engine code. The submitted-input suites
(`test_review_submitted_*`, `test_studio_*`, `test_discovery_retired.py`) run with discovery retired.

Known slow failures inherited from the handoff (being rechecked on this baseline):

- `test_zero_touch_loop.py::test_worker_host_runs_complete_loop_and_repeats_after_restart[public]` exercises the
  discovery loop (trend scan → scout → hunt). It is obsolete as product behaviour; its restart/repeat coverage is to
  be replaced by a submitted-video loop.
- `test_zero_touch_loop.py::test_added_upcoming_stream_waits_survives_restart_and_finishes_real_post_live` is a
  stream link the owner adds (not discovery); its timeout is under investigation.
