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
| Slow suite on `6c3f8d9` | **21 passed**, 16 min 59 s, clean worktree, including both tests the handoff listed as failing (`test_zero_touch_loop.py` `[public]` and the upcoming-stream test). They did not reproduce here. |

## Acceptance scenarios

| ID | Scenario | Status | Evidence / what remains |
| --- | --- | --- | --- |
| CF2-01 | Dark before first paint; no light option; other preferences kept | Not started | Light/System themes still exist (`frontend/src/prefs.tsx`). |
| CF2-02 | Studio: two choices, current work, integrated Office; no sideways scroll | Partial (existing) | Home has the two choices and a robot team; Office is still a separate page. |
| CF2-03 | YouTube URL variants import into the clip pipeline with recoverable progress | **Implemented, tested** | `studio/link_import.py`; `tests/test_studio_links.py` (variants, refusals, real yt-dlp on a fake transport, cancel, retry, restart). Real YouTube not reachable here. |
| CF2-04 | Full stories from a link: mode/guidance/destinations survive | **Implemented, tested** (import side) | Mode, style, choices and destinations are frozen before download (`test_link_enters_the_same_pipeline…`, `test_youtube_link_needs_no_search_key…`). Story splitting itself is the existing Full stories pipeline. |
| CF2-05 | 100+ mixed assets, no count rejection, bounded memory | **Implemented, tested** | Engine `ffmpeg-v2` renders in pieces (≤2 inputs per FFmpeg run), mixes audio in 10 s blocks, checks disk space first. `test_no_fixed_count_limit_on_files_clips_or_audio_items` (150 files, 400 audio items), slow `test_a_long_sequence_of_many_pieces_stays_in_sync_to_the_frame` (120 clips, 239 pieces, every element's tone checked). Uploads: 3 at a time, stop/resume per file. Not measured: peak RSS on a real 100-file project. |
| CF2-06 | Several voiceover/music/effect files as tracks | **Implemented, tested** | Plan schema 2: `audio` items on voiceover/music/effects tracks, track gain/mute, item gain/mute/fades/loop/clip attachment, measured ducking. `test_audio_tracks_gain_mute_fades_ducking_and_clip_attachment`; slow `test_voiceover_music_and_effects_tracks_are_heard_where_planned` (placement, ≥6 dB ducking under speech and voiceover, muted track silent). |
| CF2-07 | Whole project opens in the editor after the rough cut | **Implemented, tested** (screen checked by screenshot) | Editor: preview with stale label, to-scale timeline (picture + three audio lanes), sequence with per-clip inspector, Sound panel, media bin with uploads after the rough cut, Look, Versions. Slow `test_footage_and_voiceover_added_after_the_rough_cut_reach_the_checked_render`. Desktop 1440 px and phone 390 px screenshots: no sideways scroll, no console errors. |
| CF2-08 | Reorder/trim/split/replace/add, reopen, undo/redo | **Implemented, tested** | `insert`, `replace`, `add_media`; undo/redo/restore save new revisions (monotonic, stale tabs refused); named versions. `test_files_added_after_the_rough_cut_are_inserted_or_swapped_in`, `test_undo_redo_restore_and_named_versions_never_lose_work`, `test_editor_routes_undo_redo_name_and_media`. Ctrl+Z / Ctrl+Shift+Z in the editor. |
| CF2-09 | Supported correction → validated proposal → new revision → revert | Partial (existing) | Four fixed phrases (`video_flow.parse_request`). |
| CF2-10 | AI off/timeout/malformed: manual work unaffected | Partial (existing) | No AI path in the editor yet. |
| CF2-11 | Enabled style/skill changes a real plan/render field | Implemented (existing) | `test_studio_guidance.py`, `test_studio_render.py`. |
| CF2-12 | Project override wins; no global mutation | Implemented (existing) | Same suites. |
| CF2-13 | Reuse/publishing permission kept apart from Brain lessons | Implemented (existing) | `test_review_brain_separation.py`. |
| CF2-14 | Rename every bot including Core and managers | Partial (existing) | Names exist (`studio/prefs.py`); coverage of every surface not verified. |
| CF2-15 | Run/pause/retry/cancel/restart: truthful rooms and states | Partial (existing) | |
| CF2-16 | Idle and restart a migrated discovery profile: no source searches | **Implemented, tested** | `config.DISCOVERY_RETIRED`, `db._migrate_discovery_retired`; `tests/test_discovery_retired.py`. Screens updated. Dormant engine code and its older suites remain (see below). |
| CF2-17 | Re-render after approval needs new approval | Implemented (existing) | Approval-hash suites. |
| CF2-18 | Audio regression set | Implemented (existing) | Slow audio suites: 21/21 on the baseline; the full-video suites pass on the new engine (`test_studio_video.py`, `test_studio_editor_render.py`). |
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

Slow failures the handoff reported: both passed on this baseline (21/21), so nothing was changed for them.

- `test_zero_touch_loop.py::test_worker_host_runs_complete_loop_and_repeats_after_restart[public]` exercises the
  discovery loop (trend scan → scout → hunt) with the retirement patched off. It is dormant-engine coverage; delete it
  with the engine code.
- `test_zero_touch_loop.py::test_added_upcoming_stream_waits_survives_restart_and_finishes_real_post_live` is a
  stream link the owner adds (not discovery). It passed here; the earlier timeout was probably machine load.

## Full-video editor (handoff section 8): what changed

- Plan schema 2 / engine `ffmpeg-v2` (details in [EDITOR_INTEGRATION.md](EDITOR_INTEGRATION.md)). Older revisions
  are read as schema 2 and never rewritten; their music bed becomes a music-track item.
- **Behaviour change, deliberate:** music ducking was a fixed sidechain compressor that dipped music about 6 dB under
  loud speech and **not at all** under speech at a normal recording level (measured). Ducking is now measured from
  the speech itself: 12 dB by default, adjustable 0–30 dB, the same for quiet and loud recordings.
- The export format is `clipforge.edit-plan/v2`.
- Remaining in section 8: true list virtualization (the sequence draws 60 rows at a time with "Show more"), waveform
  thumbnails, text overlays beyond the title card, per-join transition choice.
