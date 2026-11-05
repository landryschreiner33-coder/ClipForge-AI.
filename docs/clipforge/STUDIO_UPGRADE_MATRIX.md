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
| CF2-02 | Studio: two choices, current work, integrated Office; no sideways scroll | **Implemented, tested** (screen checked by browser) | `pages/Studio.tsx` is the default page: Make clips, Make a YouTube video and Make clips from a video link; Needs you (only items with a fix: stopped projects, editor questions or proposals waiting for you, Autopilot's own list); the current project with its picture, the recorded step, a pill that says Working, Queued or Waiting for you, progress only when measured and the robots on it (each opens in the office); the office itself with an Expand link; recent projects and publishing. "Ready for your next video" with the input actions when nothing runs. Old addresses (`#/home`, `#/studio`, `#/studio/office`) redirect. Office data: `tests/test_office_owner_work.py` (15 tests). Browser checks at 1440 and 390 px: no sideways scroll, no console errors. |
| CF2-03 | YouTube URL variants import into the clip pipeline with recoverable progress | **Implemented, tested** | `studio/link_import.py`; `tests/test_studio_links.py` (variants, refusals, real yt-dlp on a fake transport, cancel, retry, restart). Real YouTube not reachable here. |
| CF2-04 | Full stories from a link: mode/guidance/destinations survive | **Implemented, tested** (import side) | Mode, style, choices and destinations are frozen before download (`test_link_enters_the_same_pipeline…`, `test_youtube_link_needs_no_search_key…`). Story splitting itself is the existing Full stories pipeline. |
| CF2-05 | 100+ mixed assets, no count rejection, bounded memory | **Implemented, tested** | Engine `ffmpeg-v2` renders in pieces (≤2 inputs per FFmpeg run), mixes audio in 10 s blocks, checks disk space first. `test_no_fixed_count_limit_on_files_clips_or_audio_items` (150 files, 400 audio items), slow `test_a_long_sequence_of_many_pieces_stays_in_sync_to_the_frame` (120 clips, 239 pieces, every element's tone checked). Uploads: 3 at a time, stop/resume per file. Not measured: peak RSS on a real 100-file project. |
| CF2-06 | Several voiceover/music/effect files as tracks | **Implemented, tested** | Plan schema 2: `audio` items on voiceover/music/effects tracks, track gain/mute, item gain/mute/fades/loop/clip attachment, measured ducking. `test_audio_tracks_gain_mute_fades_ducking_and_clip_attachment`; slow `test_voiceover_music_and_effects_tracks_are_heard_where_planned` (placement, ≥6 dB ducking under speech and voiceover, muted track silent). |
| CF2-07 | Whole project opens in the editor after the rough cut | **Implemented, tested** (screen checked by screenshot) | Editor: preview with stale label, to-scale timeline (picture + three audio lanes), sequence with per-clip inspector, Sound panel, media bin with uploads after the rough cut, Look, Versions. Slow `test_footage_and_voiceover_added_after_the_rough_cut_reach_the_checked_render`. Desktop 1440 px and phone 390 px screenshots: no sideways scroll, no console errors. |
| CF2-08 | Reorder/trim/split/replace/add, reopen, undo/redo | **Implemented, tested** | `insert`, `replace`, `add_media`; undo/redo/restore save new revisions (monotonic, stale tabs refused); named versions. `test_files_added_after_the_rough_cut_are_inserted_or_swapped_in`, `test_undo_redo_restore_and_named_versions_never_lose_work`, `test_editor_routes_undo_redo_name_and_media`. Ctrl+Z / Ctrl+Shift+Z in the editor. |
| CF2-09 | Supported correction → validated proposal → new revision → revert | **Implemented, tested** | Editor → **Tell the editor what to change** (`studio/edit_requests.py`). A request becomes a `clipforge.edit-proposal/v1` proposal with stable clip ids and source times, checked on the revision it was made for by the same edits and engine check as the manual controls, shown as a change list (order, trims, removals, captions, ducking, length), and applied only on Apply as a new revision that Undo reverts. Without any AI, rules understand the handoff's examples except "keep the second story together": silence at the start, "move the summit part before lunch" (parts found by what is said in them; neighbouring matches move together), music under speech, captions smaller and above the bottom controls, plus shorten the intro, remove or move a part or numbered clip, music level and transitions. An ambiguous part gets one short question with choices; no timestamp is guessed. Anything else goes to the AI service from Settings when one is set up. `test_the_handoffs_examples_work_without_any_ai_and_apply_as_undoable_revisions`, `test_ambiguous_or_unknown_parts_get_one_short_question_never_invented_times`, `test_an_ai_proposal_is_bounded_checked_applied_and_reverted`, `test_a_proposal_made_before_another_edit_is_refused_as_stale`. **Not verified:** a real model's answers (a fake AI service stands in; Ollama, LM Studio, Claude and NVIDIA are reached through the existing `pipeline/llm.py`). |
| CF2-10 | AI off/timeout/malformed: manual work unaffected | **Implemented, tested** | With no AI service, rule requests and every manual control work and nothing is sent. Text only is sent (clip list, words said, settings, Brain choices, request; never media, paths or keys), bounded to 14,000 characters, and the screen says what was sent and whether it stays on the computer. Timeout (default 60 s), cancel, provider errors, malformed JSON, unknown operations or clip ids, times outside a file, removing every clip and settings outside the allowed list all end with nothing changed and no retry. A restart while waiting reports it and does not send again. A daily limit (default 40 per workspace) and a per-request cache stop runaway calls. Words said in the video reach the AI as quoted data, and its answer is still checked. `test_malformed_or_unsafe_ai_answers_change_nothing_and_are_not_retried` (7 cases), `test_instructions_inside_the_transcript_stay_data`, `test_timeouts_failures_cancels_restarts_and_limits_leave_the_editor_working`, `test_routes_keep_requests_inside_their_workspace`. **Not built:** AI story segmentation or outlines (the existing Full stories pipeline is unchanged). |
| CF2-11 | Enabled style/skill changes a real plan/render field | Implemented and tested | Existing: `test_studio_guidance.py`, `test_studio_render.py`. New: Make a video no longer sends its pre-filled answers (shape, feel, captions, caption size/position, frame rate, music dip) as project choices, which used to override every style, skill and example for those fields; empty answers now come from the guidance and the screen shows "Used from your Brain". Example styles proven in the render: `test_studio_reference_render.py`. |
| CF2-12 | Project override wins; no global mutation | Implemented and tested | Same suites, plus `test_studio_reference.py::test_precedence_*` (project choice > chosen example > style > skills > examples that always apply > Brain notes > Settings) and the slow example test (a project shape overrides the example's). |
| CF2-13 | Reuse/publishing permission kept apart from Brain lessons | Implemented (existing) | `test_review_brain_separation.py`. |
| CF2-14 | Rename every bot including Core and managers | **Implemented, tested** (screen checked by browser) | All 25 robots and the Brain Core (`studio/prefs.py`, stable ids, roles never change). One editor (`office/RobotName.tsx`: Save, Reset name, Cancel, Escape, the server's message on refusal) in the robot details and on the Team page; Reset all names asks first and the server refuses an unconfirmed reset. Names are NFC-normalised, trimmed, at most 32 characters, control and format characters refused, shown as text; a duplicate name stays distinguishable by its role title. Names reach the map labels and their accessible names, the Brain Core label, the list, inspectors, handoff notes, activity, the Studio's team chips and tooltips. Renaming keeps the open robot. `tests/test_studio_prefs.py` (`test_every_robot_including_core_can_be_renamed_and_all_reset_with_confirmation`, workspace separation); browser: renamed from the details at 1440 and 390 px (`Tijeras ✂`), the Core from the Team page, reset all with confirmation. |
| CF2-15 | Run/pause/retry/cancel/restart: truthful rooms and states | **Implemented, tested** (office side) | The office now reads your own work as well as Autopilot's (`office/work.py`): Make clips projects by stage, clip and version renders, video links, rough cuts, renders, Find media imports, example-video analysis and editor requests, each from its recorded row. States: queued (assigned, not started), working, waiting (for you: an editor question or proposal; for a platform or a retry: Autopilot's reason), retrying, stopped by an error (30 minutes, then history), reviewing, paused (only when Autopilot was started and then stopped; your own work still runs), idle with a reason, unavailable. Progress only when measured; no invented times. Rooms follow the workflow (Intake, Media research, Story & analysis, Editing, Sound & captions, Brain, Quality & export, Publishing, Control room, Lounge); old room ids still resolve. `tests/test_office_owner_work.py`, `tests/test_office.py`, `tests/test_office_manager_handoffs.py`. **Not separate states:** waiting for a platform is shown as waiting with the platform's reason. |
| CF2-16 | Idle and restart a migrated discovery profile: no source searches | **Implemented, tested** | `config.DISCOVERY_RETIRED`, `db._migrate_discovery_retired`; `tests/test_discovery_retired.py`. Screens updated. Dormant engine code and its older suites remain (see below). |
| CF2-17 | Re-render after approval needs new approval | Implemented (existing) | Approval-hash suites. |
| CF2-18 | Audio regression set | Implemented (existing) | Slow audio suites: 21/21 on the baseline; the full-video suites pass on the new engine (`test_studio_video.py`, `test_studio_editor_render.py`). |
| CF2-19 | Multiple destinations, never the wrong account | Implemented (existing) | `test_multi_accounts.py`. |
| CF2-20 | Cross-workspace access refused | Implemented (existing) | `test_cloud_auth.py`. |
| CF2-21 | Customize studio with save/cancel/reset | Not started | Appearance settings exist; no Customize studio entry. |
| CF2-22 | Keyboard/reduced motion 320–1440 px | Partial (existing) | |
| CF2-23 | Verified native install/update | Not started | Needs Mac/Windows runners and owner approval to release. |
| CF2-24 | Published website download matches artifacts | Not started | Publishing needs owner approval. |
| CF2-25 | Reference video analysis covers the selected timeline | Implemented and tested | `studio/reference_analysis.py`: every frame at 10 fps of each selected range is compared (cuts, dissolves, fades); one still per shot plus one every 8 s of long shots (≤160) is read for framing and captions; the whole range's sound is read. Observations are labelled Measured or Estimate with confidence and playable timestamps. The example's footage and sound never enter a project. `test_studio_reference.py` (synthetic frames), `test_studio_reference_render.py` (real decode). |
| CF2-26 | Apply/edit/disable a learned example style | Implemented and tested | Example style = a style with revisions, linked to the example, its analysis revision, method and the owner's corrections. Used when chosen for a project, or for every project / some project types. Reanalysis adds a revision and never changes the saved style or a project's frozen snapshot. Disable, delete (keep or drop the style and file) and avoid examples covered. New supported fields `shot_length_s` and `duck_depth_db`. Slow test: the example's short shots, lower-third medium captions and 12 dB music dip appear in the new project's plan and the rendered sound (within 3 dB). |
| CF2-27 | No vision model / interrupted analysis: honest labels | Implemented and tested | Every analysis says it was measured locally and that no AI model watched or heard it; a configured AI service is named as text-only. Without a transcript, speech is estimated from sound and said so. The job is durable (restart, cancel keeps the previous analysis, failure keeps the last good one). **Not built:** sending stills to a vision-capable model (none of the configured providers is used with images by ClipForge); cached analyses are reused instead. |
| CF2-28 | Find and import an image and a sound effect | **Implemented, tested** (recorded provider responses) | Editor → **Find media** (Images, Footage/B-roll, Music, Sound effects) searches Openverse, Wikimedia Commons and Pexels together (`studio/media_sources.py`). Cards show a preview served through ClipForge, length or size, creator, source, license and restrictions, with shape, length and license filters. Picking a result copies the file into Your media through a durable, cancelable import with a provenance record kept apart from the Brain; putting it in the edit is a separate step. `test_an_image_and_a_sound_are_imported_with_provenance_and_credits`; slow `test_find_audition_add_place_reopen_and_render_offline` (the handoff's example: a landscape image and a rain sound are found, auditioned, imported and placed; the project is reopened with the source switched off and no network; the render shows the image and plays the rain at the placed time, with the credit in the render info and `credits.txt`). **Not verified:** the live provider APIs. Their hosts are unreachable here, so the tests use recorded responses shaped like the documented ones. |
| CF2-29 | Missing key, quota, removed source: useful errors, offline render | **Implemented, tested** | Pexels without a key shows "Needs a key" and how to get one. Keys are sealed like other secrets, never shown again, and checked with **Test connection**. A 429 with Retry-After pauses only that source and says when it resumes; the other sources' results still show. A rejected key, an outage and a removed item (404/410) each get their own message, and nothing is added. Searches are cached (15 min, 128 entries), one request at a time per source, 20 s timeout. Imported media keep working after the source is switched off or removes the item. `test_quota_retry_after_outage_and_cache_are_bounded`, `test_keys_are_sealed_tested_and_never_shown`, `test_bad_files_and_removed_items_add_nothing[removed]`, and the slow test above. |
| CF2-30 | Unknown license / malicious metadata | **Implemented, tested** | Unknown or incompatible terms (non-commercial when the project is commercial, no-derivatives, share-alike when not allowed) are labelled. Importing one needs the owner's written reason (at least 10 characters), stored with the source. Automatic mode never picks one, and automatic uploading is held while such media is in the render (`autopublish.after_render`). Titles, creators and descriptions are inert, length-limited text. Downloads go through `netguard` (address checked and pinned, redirects re-checked), with a size cap per kind, a content-type allow list and an FFmpeg decode check. `test_unknown_or_incompatible_terms_need_your_own_basis_and_hold_autoposting`, `test_untrusted_metadata_is_inert_text`, `test_bad_files_and_removed_items_add_nothing` (HTML, SVG, redirect to a local address, oversized, removed), `test_previews_are_bound_to_the_workspace_and_checked`. |
| CF2-31 | Automatic supporting media for one project | **Implemented, tested** | Make a video → **Supporting media** (off, suggest for review, add automatically), changeable per project in the editor along with "allow commercial use only" and "allow share-alike". After the rough cut, ClipForge searches for words said at least twice (no AI model), plus music when the brief asks for it. Suggest mode lists results. Automatic mode imports eligible items with known terms and adds them as **one new version**: images are inserted after the clip where the word is first said, music is looped and ducked, and the outline says each image is an illustration. Undo removes them, and only that project changes. `test_supporting_media_suggests_for_review_by_default`, `test_automatic_supporting_media_is_one_undoable_revision_for_that_project_only`. **Remaining:** no picture-in-picture or overlays (B-roll goes between clips), footage and sound effects are not placed automatically (images and music only), and topics come from word counts. |

## Studio and the Office (handoff sections 4 and 5)

- Navigation is Studio, Projects, Brain, Publishing, Accounts, Settings. The Office is part of the Studio page and
  opens larger at `#/office` (Studio · Office); the Team page lists every robot by room.
- What a robot shows comes from a recorded row: Autopilot's queue, or your own projects, renders, downloads, example
  analyses and editor requests (`office/work.py`), filtered to your workspace. Autopilot's own projects are counted
  once (its queue already shows them).
- Room ids changed with the new rooms; `office/roles.py` keeps `OLD_ROOMS` so `boss`, `dock`, `discover` and the
  others still open the room that replaced them.
- A rename re-mounts the page so every label updates; the open robot or room is kept across that.
- Clicking a robot (on the map or in the list) shows its name, role, manager, state, current task and the project or
  video it is for, and a **Log**: Autopilot's steps from the office feed plus your own work that ended in the last day,
  read from its own rows per workspace (`GET /api/office/robots/{id}/log`), because the shared feed has no workspace.
- Not built: separate states for waiting on a platform versus waiting on a retry timer (the reason text says which),
  and owner work in the shared activity feed (it shows in each robot's log instead).

## Tell the editor what to change (handoff section 9)

- Rules first, AI second: a request the rules understand never leaves the computer. A request they do not understand
  goes to the AI service chosen in Settings → AI (Ollama, an OpenAI-compatible local server, the Claude API or NVIDIA,
  through the existing `pipeline/llm.py`) only when one is set up, and Settings → AI has a daily limit and a timeout
  for it.
- The AI may answer with operations from a fixed list (remove, restore, trim, split, move, a short list of settings,
  clip volume, mute, fades and framing, track volume and mute, shorten the intro) or with one question. It cannot add
  or replace media, change the aspect or frame rate, or run anything.
- Not built: AI story segmentation and outlines, a model picker beyond the existing provider settings, and a preview
  render of a proposal before Apply (the change list and length are shown; the preview renders after Apply, and Undo
  reverts).

## Find media (handoff section 6, "Web media library")

- Sources: **Openverse** (images, music, sound effects; no key), **Wikimedia Commons** (images, footage, recorded
  sounds; no key), **Pexels** (images, footage; free key). Each can be switched off in Settings → **Media sources**,
  which is separate from social connections. Freesound sounds arrive through Openverse; no direct Freesound, Pixabay
  or paid stock integration was built.
- Licenses are reported by each source and are not verified by ClipForge. No source guarantees freedom from Content
  ID claims, and the screens say so. No commercial music is ripped; only openly licensed sources are searched.
- Credits: an editable list per project (copy, `credits.txt` beside every final render, and required credit lines
  appended to automatic upload descriptions). An edited credit that the license requires must still name the
  creator and the license; clearing an edit restores the generated wording.
- Not built: icon or overlay graphics, picture-in-picture B-roll, a provider cache shared between workspaces, and a
  check against the live provider APIs (not reachable from this environment).

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

## Example videos (handoff section 6, "Uploaded example videos")

- Brain → **Example videos**: upload (resumable), "What do you like about this example?" (overall, pacing, captions,
  framing, sound, own words), an optional part of the video, "example to avoid", and when it applies (only when chosen,
  every project, some project types). Then **What I noticed** (each line Measured or Estimate, with buttons that play
  the moment) and **What I can apply** (tick, correct a value, save once as an Example style).
- Make clips and Make a video have **Use an example**. The chosen example ranks right after the project's own choices.
- Measurements are calibrated on the editor's own captions and on synthetic footage. Real footage with on-screen
  signs or logos can be read as text: a line that never changes is reported as "not captions"; anything else is an
  estimate the owner can correct before saving.
- Remaining: adding an example from inside Make a video (the API supports project-only examples; the screen links to
  Brain), choosing several parts graphically on a timeline, the Brain graph redesign, and a vision-model pass.
