# Claude Code handoff — ClipForge studio upgrade

## Handoff: start here

Continue the existing **ClipForge** application, formerly ClipFoundry. This is an implementation handoff, not a request for another plan or a new app from scratch.

**Main goal:** a smart, easy-to-use studio that makes clips from videos the user supplies and edits their supplied footage into complete videos. It can analyze uploaded example videos to learn reusable editing preferences and find supporting sounds, music, images and footage on the web for the user's projects. The user must see what is happening, inspect the whole project, and change the result.

Keep reliability and bug prevention ahead of visual polish. Fix the failing baseline, preserve earlier repairs, build working end-to-end flows, and test them. Aim to keep the application bug-free; never claim every bug is fixed without evidence.

### Verify the latest source before changing anything

- Repository: https://github.com/landryschreiner33-coder/ClipForge-AI.
- Previous PR: https://github.com/landryschreiner33-coder/ClipForge-AI./pull/16 — GitHub reports it merged on November 4, 2026, at 18:24 UTC, merge commit `883913c84e5cb621d70093b2692083962c1580c6`.
- Start from the newest `codex/cloud-plan` and inspect follow-up branches. The old PR head is `claude/new-session-b9itcy`; the repository's default branch may be older.
- This handoff and the later renderer repair are on `codex/review-clipforge-pr16`, including repair commit `fc0664c`. Compare and carry forward needed changes; they were created after PR #16's merge and must not be assumed present in the merged app or installers. Discover later commits and read the newest handoff; do not reset to an old SHA.
- Previous review checkout: `/workspace/clipforge-pr16`. Treat that as a hint, not a required path.
- Read `AGENTS.md`, `AI_HANDOFF.md`, the top of `AI_CHANGELOG.md`, `docs/IMPLEMENTATION_STATUS.md`, `docs/clipforge/FEATURE_CHECKLIST.md`, `docs/clipforge/OWNER_GUIDE.md` and `docs/clipforge/WEBSITE_DEPLOYMENT.md`.
- Inspect the actual branch, PR state, dirty files, migrations and built frontend. Preserve unrelated work and use an isolated worktree if appropriate.
- Update `AI_HANDOFF.md` immediately with the verified state, working branch, failures and plan. Keep a requirement matrix marked implemented/tested/partial/blocked throughout.

### Existing work to extend and preserve

The source already has two creation flows, Full stories, styles, declarative skills, multiple social connections, robot naming, and owner-only cloud foundations. Extend these; do not duplicate them.

Preserve the earlier AAC packet-timing repair, framing work, Brain precedence/snapshots, account migrations, exact-artifact publishing approvals, upload deduplication, unknown-outcome reconciliation and compatible data/credential locations.

Recent merge-review fixes also hold automatic YouTube uploads longer than 15 minutes when channel eligibility is unknown; include cloud dependencies in test installs; correct misleading server-processing copy in local mode; and prevent secondary workspaces from reading the owner's Brain or using shared processing services.

The Sites website was updated as version 3. Claude subsequently added the shared GitHub Pages download site and its manifest lists November 4 Mac/Windows packages from source `06f459eb185b87ac344ad14e8dbd3f8e03be58d1`. That manifest was inspected, but those newer packages were not downloaded or retested in this handoff session. Read and verify current metadata before making release claims. **Neither static website means the application is hosted in the cloud.** Do not mistake source implementation, a merge, packaging, website publication and cloud deployment for the same event.

### Baseline failures: inspect the latest follow-up before proceeding

The review initially recorded 1,628 fast tests passing, 70 targeted cloud/studio/account checks passing after fixes, eight focused story tests passing, a successful frontend build and 12 app-shell browser checks passing. Website checks passed at 1440/1024/768/390/320 px.

The complete slow-media run then recorded **18 passed, three failed**:

1. `tests/test_studio_video.py::test_cf09_mixed_media_assembly_edits_reopen_and_server_render`: full-video preview failed in FFmpeg. A focused reproduction found `xfade` rejecting an invalid `1/0` frame rate. The follow-up restores constant frame-rate metadata and a common time base after timestamp edits and transitions. It also maps offline test transcripts by source identity instead of rounded container duration. The complete focused test now passes (1 passed in 85.12 seconds), covering preview, final render, revisions and raw audio clocks. The two other failures below remain unresolved; the complete slow suite has not been rerun after this fix.
2. `tests/test_zero_touch_loop.py::test_worker_host_runs_complete_loop_and_repeats_after_restart[public]`: the first post succeeded, but the later source was classified weak and the expected second post did not arrive.
3. `tests/test_zero_touch_loop.py::test_added_upcoming_stream_waits_survives_restart_and_finishes_real_post_live`: timed out during live capture/transcription. Media-process timeouts were also logged.

Previous logs were `/workspace/work/clipfoundry/pr16-*.log`. Verify whether later commits fixed these. Do not suppress failures or weaken useful checks to manufacture green results. When deliberately removing discovery/live-discovery features, document obsolete tests and replace their useful recovery/restart coverage with submitted-video tests.

## 1. Scope and execution rules

- Implement the features below; do not deliver only mockups, decorative buttons, placeholder AI, or another proposal.
- Work in focused commits. Stabilize intake, rendering and editing before optional decoration.
- Use disposable data, synthetic media and fake social accounts for automated testing. Never experiment on the owner's active database or publish real videos as a test without explicit authorization.
- Do not purchase API capacity, provision paid resources, install huge models, disclose secrets, disable system security or submit real social posts implicitly.
- Continue ordinary coding, debugging, checks and reversible setup without repeatedly asking permission.
- Preserve data and old addresses through tested migrations. Do not silently discard projects, media, Brain records, approvals or sign-ins.
- Use relevant connected tools when available: repository tools, Sites for the existing website, browser tools for real UI checks, and design/image tools for useful assets. Verify capabilities before claiming access to accounts or the owner's devices.

## 2. Product structure: two choices, one studio

Keep exactly two primary creation choices:

1. **Make clips** — a supplied video file or link; choose **Highlights** or **Full stories**.
2. **Make a YouTube video** — multiple supplied video/image/audio assets; build and refine a full edit.

**Full stories belongs inside Make clips.** For a long recording containing several narrated stories, create one complete vertical clip per story, preserving setup and ending. Let the user adjust estimated boundaries and check uncertain stories. Keep the full master when it exceeds a platform limit; never silently truncate or speed it up.

Suggested main navigation: **Studio**, **Projects**, **Brain**, **Publishing**, **Accounts**, **Settings**. Studio combines Home and Office. A global **Create** action offers the two creation choices. Redirect old addresses instead of breaking bookmarks.

Maintain multiple YouTube/TikTok connections, exact destinations and platform-required review. Keep **Make clips only** available. Automatic processing means working on the user's submitted projects. Project-specific supporting-media searches are allowed as described below; continuously hunting for new source videos to clip is being removed.

## 3. Dark-only visual redesign

Make the application simple, clean, professional and visually distinctive. Use a cohesive dark studio design with charcoal/navy surfaces, restrained purple/teal accents, readable typography, deliberate spacing and subtle depth. Keep the refined retro pixel-art robots and canonical icon.

- **Remove light mode.** Do not retain a System theme option that can produce light mode.
- Migrate saved Light/System preferences to the dark default without clearing other settings. Apply it before first paint; no bright startup flash.
- Restyle actual forms, dropdowns, dialogs, captions, controls, toasts and loading/empty/error states consistently. Avoid unstyled bright form fields.
- Use plain language and obvious next actions. Move advanced controls and technical logs behind disclosures.
- Avoid excessive cards, tiny labels, repeated counters, fake charts and controls that do nothing.
- Respect reduced motion, keyboard access, readable contrast and clear focus states. No sideways page scrolling at 320/390 px.
- Pause expensive animation in hidden tabs/off-screen panels and provide low-power mode. Reduced motion must not stop real jobs.

### Simple customization

Provide one **Customize studio** entry with a live preview, Save, Cancel and Reset to defaults:

- A few dark palette presets; accent selection with contrast safeguards.
- Comfortable/compact density and readable text sizing.
- Motion and decorative activity controls.
- Panel visibility/order, with good presets before optional drag-and-drop; keyboard reorder controls too.
- Pinned projects and a compact/expanded Office presentation.
- Robot names and optional cohesive color/badge variants without obscuring role/state.

Persist supported preferences per user/workspace. Use separate phone/tablet/desktop layouts instead of copying desktop coordinates onto a phone. Apply every offered setting to real screens; do not save inert preferences. Clearly distinguish local persistence from actual account sync.

## 4. Integrate Home and Office into Studio

### Home/Studio layout

- Top: **Make clips**, **Make a YouTube video**, and an obvious supplied-video-link action.
- Current project: thumbnail, actual stage, measured progress, responsible team and relevant next action.
- An integrated Office view showing the teams involved in current work, with an expanded view available.
- **Needs you** appears only when there is something actionable, with one clear explanation and fix per item.
- Recent projects and publishing status remain nearby without overshadowing creation.
- Empty state: “Ready for your next video” plus input actions.

Never count paused or idle robots as working. Distinguish queued, running, waiting for the user, waiting for a platform, retrying, failed, completed and idle. Do not invent percentages, estimated completion times or activity.

### Reorganize rooms for the real workflow

| Department | Actual responsibility |
| --- | --- |
| Intake | Supplied files/links, uploads, validation, indexing |
| Media research | Project-specific web assets, source/license records and managed downloads |
| Story & analysis | Transcription, highlights, complete stories, boundary checks |
| Editing | Assembly, framing, sequence and transitions |
| Sound & captions | Audio repair/mix/normalization, captions and sync |
| Brain | Retrieving guidance, resolving conflicts, recording applied choices |
| Quality & export | Final file/audio/framing checks and exports |
| Publishing | Review, scheduling, uploads and platform-status reconciliation |
| Control room | Coordination and actual problems |
| Lounge | Clearly decorative idle activities |

Remove discovery-centric rooms/signage and unnecessary props. Fit room sizes, doors, desks, chairs, robot scale and routes together with coherent proportions and professional composition.

- Rooms/robots must be driven by real backend job/stage events with stable project, job and stage IDs.
- Assemble the relevant department while it has work; managers oversee their teams. Working robots sit at the appropriate station.
- Handoffs follow actual stage completion and the responsible manager/team. No random routing or duplicate handoffs after retries/restarts.
- Handle queued, paused, canceled, failed and resumed work truthfully.
- Idle robots may play games, read, eat or drink in the lounge; decorative activity is not work or learning.
- Clicking a robot opens its name, permanent role, assignment, state and relevant project/log.
- Preserve accessible controls and an understandable list alternative. Keep animations off the critical processing path.
- Do not spawn fake jobs or uncontrolled LLM agents to make the office look busy.

## 5. Rename every bot

Support every director, manager, worker and Brain/Core character represented as a robot.

- Edit from a robot inspector and a simple Team list.
- Preserve stable IDs and permanent role labels; changing a name must not change routing, permissions or behavior.
- Apply names across map labels, team strips, inspectors, handoffs, tooltips, activity descriptions and accessible labels.
- Support Unicode/spaces, trim whitespace and enforce a sensible display length with a clear error.
- Render names as text, never HTML. Duplicate names must remain distinguishable by role.
- Provide reset-one and reset-all; confirm reset-all.
- Persist through restarts/upgrades and preserve existing custom names.

## 6. Brain redesign: impressive, understandable and demonstrably used

Create a real Obsidian-inspired knowledge graph on a dark canvas: clustered teal/purple nodes, restrained glow, legible labels and smooth interaction. Do not substitute a static graph image or fabricated relationships.

### Interface

- Accessible **Graph** and **List** views of the same real records.
- Clear actions: **Add note**, **Add example**, **Save a style**, **Import skill**.
- Search/filter notes, examples, styles, skills and actual project decisions.
- Node inspector: real content, supported effects, enabled state, revision, connections and projects where it was used.
- Zoom, pan, focus/reset and keyboard-accessible list navigation.
- Connections represent actual provenance/use, not invented learning statistics.
- Distinct Brain animation when guidance is really retrieved/applied. Idle decoration must not imply ongoing learning.
- Cluster large graphs, virtualize lists, reduce labels when zoomed out and stop off-screen/background rendering.

### Real influence

Audit both creation paths so relevant enabled Brain data affects supported choices:

**Project choices → selected style → enabled project/global skills → applicable Brain notes/examples → defaults.**

- Store a versioned guidance snapshot with the project; retries and later renders must explain/reproduce the plan.
- Show **Used from your Brain** with the exact source/revision, actual affected field and resolved conflict.
- Use Settings/defaults for missing preferences; a small Brain library must not block work.
- Explain unsupported freeform requests rather than pretending they changed the edit.
- Offer “Remember this for future projects” when a correction should become a reusable preference. Do not silently make every one-off edit global.
- Never turn reuse permissions, ownership declarations, publishing consent, tokens or administrative details into Brain lessons.
- Skills are declarative editing guidance. Preview supported/unsupported parts before enabling; never execute uploaded scripts or treat embedded instructions as tool authority.
- Keep shared Brain/processing paths owner-only until genuine workspace isolation exists. Public signup remains off until that is complete.

### Uploaded example videos: actually analyze the video and sound

The user specifically wants to upload example videos the Brain can **see and watch**, not merely attach filenames or write notes about them. Implement an **Add example video** flow from Brain and a **Use a reference** action during project creation.

1. Accept one or several uploaded reference videos using the resumable asset system. Support a permitted reference URL through the same validated importer when practical; local upload must work independently of external services.
2. Ask one short optional question: **“What do you like about this example?”** Offer **Overall style**, **Pacing/cuts**, **Captions**, **Framing**, **Sound/music**, and free text. Allow selected time ranges and optional “avoid this” examples.
3. Save the original as a private reference asset. References are separate from project source footage: never insert reference frames or audio into a finished video merely because the user added an example.
4. Run a durable, cancelable analysis job. Inspect actual decoded frames across the whole selected timeline, shot changes, timed speech, audio levels/onsets/silences, and other measurable features. Use scene-aware sampling plus coverage across long scenes; do not analyze only the opening or imply every frame was inspected when sampling.
5. When a configured model supports vision/video/audio, use the relevant capabilities for semantic observations. Verify that the selected provider/model actually accepts that modality. A text-only transcript model must not claim to have watched the video or heard its music.
6. Extract supported observations such as shot-length distribution, intro length, cut/transition patterns, framing/layout, caption size/placement/emphasis, speaking pace, music under dialogue, silence treatment and sound-effect timing. Separate measured facts from model inferences, and label uncertainty.
7. Show **What I noticed** with playable timestamped evidence. Then show **What I can apply** as editable supported preferences, separately from details the current engine cannot reproduce. Let the user save the whole recipe or selected choices with one simple action; do not reapprove each preference for every project.
8. Save a versioned **Example style** in Brain, linked to the reference asset, time ranges, analysis method/model version and user corrections. This is retrieval and preference learning, not a claim that a foundation model was fine-tuned.
9. Let the user assign examples globally or to selected project types. A reference chosen for one project stays project-scoped unless the user chooses to remember it. Preserve the established precedence: explicit project choices win.
10. Use the extracted supported values in both clip modes and full-video editing. Prove the effect in the actual plan/render, and list the example and its revision under **Used from your Brain**. A graph connection alone is not integration.
11. Offer **Reanalyze**, **Edit learned style**, **Disable**, and **Delete**. Reanalysis creates a new revision; it must not silently change a queued render's frozen guidance. Deletion honors the selected retention behavior and explains any impact on project reproducibility.
12. Cache analysis by content hash, selected range, options and analyzer version. Bound compute, provide progress and recovery, and disclose remote model processing before sending private reference media. Without a suitable model, keep references playable and offer honestly labeled measured analysis/manual style extraction; never fake visual understanding.

Acceptance example: upload a reference with short shots, lower-third captions and quieter music during speech; save those supported choices; create a new project; inspect the resulting cut durations, caption placement and ducking. The project must identify that reference as its source and allow overriding each choice.

### Web media library: sounds, music, images and more

Add a **Find media** panel in the editor and an optional **Find supporting media for this project** step. This supports the user's editing project; it must not revive background discovery of unrelated videos to clip.

**User experience**

- Search categories: **Images**, **Footage/B-roll**, **Music**, **Sound effects**, and optional **Icons/overlays** when a real supported source exists.
- Search manually or ask the editor for something specific: “Find a short rain sound here,” “Add a mountain image during this sentence,” or “Find quiet background music for this section.”
- Allow a clearly selected project-level mode: **Suggest for review** by default, or **Find and add eligible assets automatically** when the user chooses it. Automatic additions must be undoable project revisions and must pass the configured license/resource filters. Unrelated background searches remain off.
- Result cards include visual/audio preview, duration/dimensions where applicable, creator, source, license, attribution requirements and any relevant restrictions. Include useful type/orientation/duration/license filters and avoid result overload.
- Selecting a result downloads it into the managed media bin, then allows preview, trim, crop, volume/fades and insertion at a chosen timeline position. Separate selecting/previewing from adding to the final edit.
- Keep external media and generated suggestions editable and replaceable. Do not silently alter spoken meaning or label illustrative footage as a factual recording of the event.

**Provider implementation**

- Inspect available connectors and current official provider documentation before choosing integrations. Good candidates to evaluate include Wikimedia Commons/Openverse for images, Pexels/Pixabay for stock media, and Freesound or suitable stock libraries for effects/music. These are candidates, not a claim that every category/API is free or available.
- Ship at least one working image provider and one working sound/music provider, plus footage when a verified provider supports it. Use documented APIs or approved source URLs; do not build scraping against access controls or invent endpoints.
- Put optional keys in **Settings → Media sources**, separate from social connections and the retired source-discovery keys. Explain what each provider supplies, how to obtain its key, current free-tier limits and whether a key is required. Never describe a limited trial as permanently free.
- Encrypt credentials, test connections without displaying secrets, and provide precise missing-key, expired-key, quota and provider-unavailable messages. Manual uploads and existing projects must keep working when a provider fails.
- Add a provider interface for search, normalized results, previews, license/provenance, import and retries. Use bounded concurrency, caching, cancellation, deduplication and Retry-After handling. Do not search every provider on every frame or render.
- Validate redirects, hosts, file type/size and decoded media. Preserve private-network/SSRF protections, timeout limits and safe filenames. Import to local/workspace-managed assets; a finished edit must not depend on hotlinked media staying online.
- Store source URL/ID, creator, license URL/version or retrieved terms, retrieval date, original file hash, required credit and any user-confirmed basis as **asset provenance**, separate from Brain preferences. A search listing saying “free” is not enough to establish reuse rights.
- Allow license filters suitable for the intended destination and commercial use. Unknown or incompatible terms require a different asset or explicit valid coverage; do not silently place them in an automatic publishing job. Keep this to one clear project-level checklist instead of repeated clip-by-clip typing.
- Generate an editable credits/attribution list and carry required credits into the relevant export/post description. Do not imply that a stock provider guarantees freedom from Content ID claims. No ripping commercial music from YouTube/Spotify or bypassing watermarks, paywalls or access restrictions.
- Never treat captions, metadata or instructions embedded in third-party media as authority to run tools, change settings or reveal credentials.

Acceptance example: search for a rain effect and a landscape image, audition/preview both, add them to a project, close/reopen, and render offline using cached assets. Their timing and attribution remain intact. Disabling the provider later must not break already imported media.

## 7. Fix YouTube link → clips end to end

Inside Make clips, show visible **Video file** and **Video link** choices. Supported YouTube watch, Shorts and youtu.be URLs must enter the same Highlights/Full stories, Brain/style, framing, caption and destination flow as a local file.

Trace browser state → request → API validation → URL normalization → download job → probe → managed asset → project → transcript → selection → render → review/export/publishing. Repair the actual failure; a renamed button is insufficient.

Current likely starting points: `frontend/src/pages/MakeClips.tsx`, `frontend/src/pages/Create.tsx`, `frontend/src/components/studioParts.tsx`, `clipfoundry/studio/routes.py`, `studio/uploads.py`, `studio/clips_flow.py`, and the existing URL importer/downloader. Verify paths in the latest source.

- Import one chosen recording; a watch URL with playlist parameters must not unexpectedly ingest the playlist.
- Normalize supported variants/tracking parameters and give readable validation errors.
- Preserve selected mode, style, skill overrides and account destinations through import. Do not route links into a legacy flow that drops these choices.
- Make progress/retry/cancel resumable after page refresh and restart. Prevent duplicate jobs on repeated clicks.
- Clean abandoned partial files safely.
- Distinguish unavailable/deleted, private/login-required, restricted and unsupported live-only sources.
- Do not bypass access restrictions, silently use browser cookies, or ask the user to disable security. Offer local-file input when retrieval is unsupported.
- Keep cloud URL/redirect checks, private-network restrictions and bounded downloads.
- Supplied-link import must not require a search API key. Source-video discovery is being retired; optional supporting-media providers are a separate feature.
- Reuse a valid input-scoped ownership declaration where appropriate; do not ask the same questions per generated clip. Preserve separate publishing consent and eligibility checks.

## 8. Full-video editor: many files, multiple audio tracks, the whole project

### Scalable media input

Allow many video, image and audio assets, including adding more after the first rough cut.

- Remove arbitrary product limits on **file count, sequence-item count and audio-clip/track count**. Do not replace them with another small fixed cap.
- Multi-select, drag/drop, multiple upload batches, per-file progress, resumable transfer, cancel and retry.
- Support the installed engine's common video formats and WAV/MP3/M4A/AAC/FLAC/OGG/Opus audio where supported.
- Treat source audio, voiceover, music and effects as separate first-class assets, not a single optional music-file field.
- Use chunked transfers, streaming probes, proxies, cached thumbnails/waveforms and virtualized lists/timelines. Never decode/load every file into RAM.
- Reuse analysis/proxies/transcripts for unchanged media.
- No artificial count limit does not mean infinite disk, memory, paid API quota or platform duration. Keep resource monitoring, disk-space checks, bounded workers and configurable operational safeguards. Explain real limits before work is lost.
- Preserve corruption/path/URL validation and bounded encoders; do not remove safety checks to advertise “unlimited.”

### Creation controls

Keep a short initial questionnaire and useful defaults. Put advanced controls under **Customize**:

- Video purpose/type, audience and desired structure.
- Aspect ratio, resolution and supported frame rate.
- Pace, approximate length target, opening/ending.
- Must-keep moments, exclusions and transcript-driven selections.
- Caption style, size, position, emphasis and supported subtitle export.
- Fit/fill/blur framing and supported subject tracking.
- Transitions, title cards, chapters/text and restrained overlays.
- Source sound, voiceover, music/effects, per-clip gain/mute/fades and music ducking.
- Saved style plus explicit per-project overrides.

Expose only working engine capabilities. An unsupported option must not be silently saved and ignored.

### Completed project workspace

After generating a rough cut, open the **entire editable project**, not just an MP4 or a text summary:

- Media bin, complete sequence/timeline, story/outline view.
- Preview, playhead, timecode, zoom/fit controls.
- Clip/audio/text/framing inspectors.
- Render/export status and output revisions.

Required actions:

1. Reorder, trim, split, replace, include/exclude and remove sequence items without deleting original assets.
2. Add footage/audio after the rough cut and insert at a selected point.
3. Move/trim audio independently; change gain, mute, fades and ducking while preserving sync.
4. Edit captions, text, framing and supported transitions.
5. Undo/redo, autosave, visible saved state, named revisions and reopen after restart.
6. Inspect/restore an older revision without losing newer work.
7. Render a quick preview, then a full-quality export of the chosen revision. Label stale previews.
8. Freeze each render's revision; subsequent editing must not silently change the output being generated.

Keep the versioned engine boundary. Evaluate existing open-source editor components only when they fit licensing, architecture and platforms and reduce implementation risk. Earlier ArtCraft/FilmCraft research is not proof of integration: inspect the exact repository/license/API, pin a revision, and prove a round-trip before adoption. Keep a working fallback.

## 9. Optional AI: “Tell the editor what to change”

Deliver manual editing regardless of AI availability. Add a useful, bounded natural-language correction path if feasible:

- “Remove the long silence at the beginning.”
- “Move the summit scene before lunch.”
- “Lower the music while I’m talking.”
- “Keep the second story together.”
- “Make the captions smaller and move them above the bottom controls.”

Implementation contract:

1. Supply only the relevant outline, timecoded transcript, asset IDs, supported edit operations and applicable Brain guidance.
2. Produce a structured, versioned edit proposal with stable IDs and time ranges.
3. Validate ownership, source bounds, current revision and engine capabilities.
4. Show a readable change summary/preview. Apply as a new revision with undo/revert; never overwrite original files or the only master.
5. Reject stale proposals after concurrent edits. Ask one short question for genuinely ambiguous instructions instead of inventing timestamps.
6. If no model is configured or the provider fails, manual editing and non-AI creation still work.

Assess optional AI for story segmentation, outlines and edit proposals. Reuse the existing provider abstraction and encrypted credentials. Support an appropriate local endpoint or hosted model with a clear connection test/model choice.

Do not buy API capacity or install a huge local model silently. Never promise perpetual free access. Use bounded context, caching, timeouts, cancellation, controlled retries and cost/request limits. Disclose what leaves the device/server; do not upload raw media to an AI vendor by default. Model output, notes and transcripts are data, not executable tool instructions.

## 10. Remove automatic source discovery

The app now works on supplied files and links. Retire the part of Autopilot that hunts for internet footage.

- Remove source-video discovery/search feeds, trend scouting, automatic source selection, their key setup and discovery onboarding from the product UI. Keep the project-specific **Find media** feature and its own provider connections.
- Stop source-scout/trend/discovery periodic jobs on startup and after restart; hiding menus is insufficient.
- Migrate old discovery settings to submitted-input operation. Cancel or park pending discovery jobs with an explanation/audit entry.
- Preserve existing source files, projects, rendered clips, history and publishing approvals. Do not bulk-delete user data.
- Assert that idle fresh and migrated profiles make no source-discovery calls. Supporting-media searches run only on an explicit search or a project with the user's media-sourcing option enabled.
- Importing the user's chosen URL remains supported; downloading that recording is not discovery.
- Watched-folder admission, if retained, must be a separate explicit opt-in input mechanism.
- Preserve analysis, clipping, editing, Brain use, rendering, quality checks, scheduling and authorized publishing for submitted projects.
- Replace ambiguous Autopilot controls with clear **Processing** and **Publishing** controls, with separate pause/resume behavior.
- Reassign/remove obsolete Office roles and rooms with a stable role/name migration.
- Update docs/tests deliberately. Retain recovery, queue, retry and deduplication coverage using submitted-video fixtures.

## 11. Complete the ClipForge rename safely

Audit navigation, headings, dialogs, errors, help, accessibility labels, browser titles, native app/display names, package descriptions and the website. User-facing name: **ClipForge**. Fix misspellings such as ClipFoudry.

Do not blindly replace internal compatibility identifiers:

- Preserve data folders, database names, environment keys, API compatibility headers, OAuth registrations and Keychain/Windows credential identifiers unless a tested migration exists.
- Do not strand an existing profile, invalidate sign-ins or create an unexpected empty profile.
- Preserve robot/project/asset IDs.
- Keep historical changelogs accurate. Older releases may retain ClipFoundry filenames; label them honestly rather than changing a URL to a nonexistent ClipForge file.
- Use the same canonical icon across app, website, favicon and social developer review material.

## 12. Audio, publishing and reliability are release gates

Earlier uploads had scrambled audio, a quiet section and then normal sound, even when local playback seemed fine. Preserve the **stored AAC packet-clock repair** and raw-clock validation after the final audio filters. Normal local playback alone does not prove correctness.

- Keep correct resampling/channel layouts and final timestamp normalization.
- Avoid startup gain pumping, clipping, hidden ducking or unintended silence.
- Cover mixed sample rates, mono/stereo, variable-frame-rate sources, offsets, trimmed intros, transitions, voiceover, music and silent footage.
- Check duration, A/V offset, audible onset, loudness/peaks and monotonic raw AAC packets with automatic repair disabled during validation.
- Verify fake-platform uploaded bytes equal the approved artifact. Real platform-transcode/listening tests require explicit authorization and separate reporting.
- Preserve approval binding to file hash/revision/account/audience/kids answer. Editing/re-rendering invalidates prior approvals where appropriate.
- Never blindly resend after unknown upload outcomes; reconcile and deduplicate.
- Respect platform rate limits, Retry-After, duration/account eligibility and TikTok per-post requirements. No app daily cap does not bypass platform limits.
- Preserve truthful YouTube kids answers, intended privacy and comment settings.
- Preserve worker leases, cancellation, recovery, resumable input and bounded resources.
- Keep one authoritative job coordinator; robots represent real responsibilities, not uncontrolled autonomous publishers.

## 13. Website and real release downloads

After implementation and verification, update the shared public download website yourself:

**https://landryschreiner33-coder.github.io/ClipForge-AI./download/**

This is `download/` on the repository's `gh-pages` branch. Read that branch's `download/UPDATING.md`. Both assistants can update it with repository access; use a separate checkout/worktree and ordinary non-force pushes. Keep release metadata in `download/releases.json`; run `python3 download/build.py`, `--check` and `--verify` as documented. Preserve the root legal pages, canonical icon and platform verification files. Apply the user's dark-only design even if older instructions mention testing light mode.

The existing Sites address, **https://clipfoundry-studio.landryschreiner33.chatgpt.site**, is separate (Site ID `appgprj_6ae8b76d68108191bc36af565f138bed`). If the Sites tools/workspace are available, synchronize its presentation and link to the verified shared download page. If unavailable, finish GitHub Pages and explicitly report Sites as unchanged; do not claim to have published it or create a replacement Site.

- Read the latest website checkouts/publication records; retain both addresses and their public audiences.
- Improve the design to match the final dark ClipForge studio. Use sanitized current screenshots and short recordings of working flows.
- Explain the two creation outcomes, Full stories within Make clips, complete editor, example-video analysis, supporting-media search, Brain, robot team and multiple accounts. Remove automatic source-video-discovery marketing. Show these features as available only when actually implemented and packaged.
- Keep mobile navigation, accessible controls, FAQ, setup help, support and privacy/terms polished.
- Open Studio must point to a real authenticated deployment if one exists. Otherwise clearly say cloud hosting is not live; do not invent a login or imply the static website processes videos.
- **Build and verify updated installers before changing download links.** The package advertised as the new release must actually contain these changes.
- Test launch, icon, included source commit, data preservation, quit/reopen and packaging on supported Mac/Windows runners. Record filenames, sizes and SHA-256 hashes.
- Mac remains unsigned/ad-hoc-signed unless real Developer ID signing/notarization is available. Do not promise removal of the macOS opening warning or ask users to disable system security.
- Keep older verified links available until replacements are tested. If packaging is blocked, clearly label old packages and provide the tested source commit separately; never fake release completion.
- Verify the published links and keep the previous saved website version and download metadata for rollback.

## 14. Acceptance tests

| ID | Scenario | Required result |
| --- | --- | --- |
| CF2-01 | Fresh launch and migration from Light/System | Dark before first paint; no light option; other preferences retained |
| CF2-02 | Studio on desktop and phone | Two creation choices, current work and integrated Office are clear; no sideways scroll |
| CF2-03 | Supported YouTube URL variants | Import to the same clip pipeline as files, with recoverable progress and useful errors |
| CF2-04 | Full stories from a link | Mode/guidance/destinations survive import; complete stories become separate vertical clips |
| CF2-05 | Large batch, e.g. 100+ mixed assets | No arbitrary count rejection; responsive UI, bounded memory, resumable upload |
| CF2-06 | Several voiceover/music/effect files | Independent editable audio assets/tracks with timing, gain, mute and fades |
| CF2-07 | Complete a full-video rough cut | Whole project opens in editor: media, sequence, preview, captions and audio |
| CF2-08 | Reorder/trim/split/replace/add, then reopen | Correct persistence/export; undo/redo and revisions work |
| CF2-09 | Ask for a supported correction | Validated proposal; apply creates new revision; revert works |
| CF2-10 | AI disabled, timeout or malformed response | Manual/core workflow still works; no corrupt plan, runaway retry or extra upload |
| CF2-11 | Enable Brain style/skill | Real supported render/plan field changes; exact source/revision shown |
| CF2-12 | Override a preference for one project | Project wins; no global mutation without request; conflict readable |
| CF2-13 | Enter reuse/publishing permission | Consent retained separately; nothing added as Brain lessons |
| CF2-14 | Rename all bots including Core/managers | Names persist everywhere; role IDs/routing unchanged |
| CF2-15 | Run/pause/retry/cancel/restart | Correct rooms, states and handoffs; no fake work or duplicate processing/posts |
| CF2-16 | Idle and restart a migrated discovery profile | No source searches; existing data preserved; submitted inputs still run |
| CF2-17 | Re-render after approval | Changed artifact/revision requires appropriate new approval; uncertain uploads reconcile |
| CF2-18 | Audio regression set | Correct stored AAC clocks, onset, levels and A/V sync in final artifact |
| CF2-19 | Multiple destinations | Explicit correct account; disconnect/limit/retry never sends to another account |
| CF2-20 | Cross-workspace data access | Refused; no owner Brain/media leak; public signup remains disabled until isolation complete |
| CF2-21 | Customize/reset layout/palette/density/motion | Actual supported screens change; save/cancel/reset and keyboard controls work |
| CF2-22 | Keyboard/reduced-motion at 320–1440 px | Usable navigation/dialogs/editor/list alternative; no essential motion dependency |
| CF2-23 | Verified native install/update | Correct version/icon; prior data retained; launch/quit/reopen works |
| CF2-24 | Published website download | Feature descriptions match actual artifacts; checksums/cloud status accurate |
| CF2-25 | Upload a reference video with distinct sections | Analysis covers the selected timeline; timestamped evidence separates measured facts/inferences; reference footage is not reused implicitly |
| CF2-26 | Apply/edit/disable a learned example style | Supported plan and render settings change; precedence, versioned provenance and frozen queued renders remain correct |
| CF2-27 | No vision-capable model or interrupted analysis | Honest capability label; playable references/measured analysis remain available; resumable job, no invented observations |
| CF2-28 | Find and import an image plus audio effect | Real previews, managed assets, source/license records, editable timeline placement and required credit |
| CF2-29 | Missing key, exhausted quota or source removed | Useful error and bounded retry; manual media and cached projects still render offline |
| CF2-30 | Unknown license or malicious media/metadata | No unqualified automatic publishing; URL/file checks hold; embedded instructions cannot control tools or access secrets |
| CF2-31 | Enable automatic supporting media for one project | Eligible assets added as reversible revisions only to that project; no unrelated source discovery or other-workspace access |

Use reasonable stress fixtures; do not claim infinity was tested. Separate fake-platform verification from real-world platform results.

## 15. Implementation order and final handoff

1. Verify baseline and repair unexplained failures.
2. Unify supplied URL/file input; retire discovery triggers/UI through migration.
3. Build scalable media/audio/project editing and revision safety.
4. Implement real example-video analysis and applied Brain styles; add the supporting-media library/providers and bounded AI corrections.
5. Integrate Studio/Home/Office, reorganize teams, wire truthful states/handoffs and all-robot names.
6. Finish dark design/customization, accessibility and responsive behavior across every screen.
7. Run fast/slow/browser/recovery/audio checks and verify native packages.
8. Update/publish the website with real release links and rollback evidence.

Deliver working code and focused commits, built frontend, migrations, updated tests, user docs, a completed/partial/blocked matrix, verified release status and updated `AI_HANDOFF.md`, changelog and machine-readable log.

The final reply must explain what users can do now, what was tested, where to open/download it and what remains incomplete. Distinguish **source implemented**, **tested**, **merged**, **packaged**, **website published**, and **cloud deployed**. Never present one as proof of the others.
