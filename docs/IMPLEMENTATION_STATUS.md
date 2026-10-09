# Implementation status

## PR #14 social pixel office — 2026-10-09

Starts at `5b1f7a9` on `claude/project-thread-vw1n9y`; PR #14 stays draft/unmerged. The owner requested better
graphics tools and off-duty games, food and drinks. Six authored arcade/board-game/snack/drink/read/rest gestures
use 29 exclusive places and 25 stable cast homes, with phased rotation and at most two recreational walkers.
Real work and confirmed document handoffs preempt breaks; state badges and job references remain authoritative.
The explicit stopped-office recreation exception preserves Paused badges. Individual pause during Running and
unavailable roles remain quiet; global Pause, Reduced, hidden and stale views freeze recreation.

Pinned GSAP **3.15.0** supplies pure easing on the existing office clock under its standard no-charge license.
PixiJS **8.22.0** caches soft BlurFilter light pools with static scenery in distinct arcade/café/game/sofa zones.
The original generated skyline is a local optional asset: loading is bounded to 1.5 seconds, failure/stall leaves
procedural windows, late completion cannot mutate the scene, and cropped textures are destroyed without deleting
the shared source. Canvas retains simpler controller-driven gestures, including frozen Brain cue expiry.
Whole-map lounge names are staggered; the closer camera uses compact labels. Backend, media and publishing
behavior are unchanged, as are shared portraits, all 25 identities and true job handoffs.

| Check | Result and scope |
| --- | --- |
| `.venv/bin/python -m pytest -m 'not slow'` | **641 passed**, seven slow cases deselected, in **280.30 s**. |
| `npm run build` in `frontend/` | Final TypeScript + Vite production build passed in **5.83 s**; all 14 distribution files are SHA-256 identical to the assets used in the final browser run. Built distribution included; existing lazy 904 KB graphics chunk warning remains. GSAP is the new frontend dependency. |
| Five-file focused browser suite | **23 passed together in 6.4 min**: lounge 6, living 7, motion 3, pixel 3, robot-office 4. |
| Geometry and controller checks | 2916 + 4770 route checks; 600 simulated seconds with all 25 identities rotating, exclusive reservations and at most two ambient walkers; 150 mixed-state transitions preserve safe returns and work/handoff priority. |
| Actual pixel checks | All six Full gestures change rendered pixels; Reduced drift is zero, actual work suppresses leisure props, and a frozen Canvas Brain does not change when its activity cue expires. |
| Final actual isolated captures | Desktop 1440×900, laptop 1280×720 and mobile 390 px List: all 25, visible laptop controls, no mobile horizontal overflow, zero page errors. Laptop map is 696×464; controls end at y=717 inside its 720 px viewport. |
| Final recordings | Both 1440×900 H.264/yuv420p, zero page errors: actual stopped recreation 33.24 s; visibly labeled controlled work/Brain/stage fixtures 33.48 s. Only startup before the visible provenance banner was trimmed, without retiming. Neither measures real processing speed. |

The focused browser run uses installed Linux Chromium, the disposable app on port 8844 and a scratch configuration
selecting `lounge-life.spec.ts`, `living-office.spec.ts`, `motion.spec.ts`, `pixel-office.spec.ts` and
`robot-office.spec.ts`, one worker and a 180-second timeout. A stalled skyline request verifies bounded startup;
a fresh failed scene bundle verifies animated Canvas recreation and Reduced stillness. The repository sandbox
configuration includes these cases without changing Playwright pins or the read-only `e2e/tests` suite.
The initial 23-case run passed in 5.9 min before the final fallback/label refinements; it is separate from the final
run above. An initial controlled recording timed out while three browsers competed, then succeeded standalone.

[Current evidence, provenance and editing guide](../design/robot-office/lounge/README.md). Previous living/refined
and master-continuation results below remain separate historical checkpoints. The seven slow media cases were not
repeated because this changes no backend/media behavior. Windows CMD/installation/fonts/scaling, RTX 3050 CUDA/NVENC
and real platform accounts remain owner checks. GPU files, `.mcp.json`, Playwright pins and `e2e/tests` are unchanged.
No real upload, account change, hosting purchase or deployment occurred.

## PR #14 living office follow-up

Starts at `a119dfd`, on the same draft/unmerged branch. The owner requested realistic furniture/robot proportions,
idle lounge rest, seated work, visible hand-to-hand transfers and a cooler animated Brain. This supersedes the
preceding idle-at-station placement. Existing PixiJS now paints the 960×640 furnished plan with 25 stable lounge
seats, scaled desks/chairs, seated rigs and furniture-aware aisle routes. The room camera shows each room up close.
Fresh actual job-stage/reference/report events drive both-party approach/pass/receipt, followed by the latest real
desk or lounge destination. No guessed next step or animation delay changes a backend job. Snapshot ownership,
event-cursor and timestamp guards keep skipped/replayed stages from inventing an outdated sender.

CORE is a layered neural sculpture with pixel hemispheres, synapses and orbiting lights. Decorative powered
Standby is labeled separately from Processing, which follows actual Brain state/events. Brain/global pause,
Reduced and offline freeze it. Canvas compatibility shares the layout, seating and transfer controller. Existing
portrait caching, saved motion choices, controls, task details and all 25 identities remain.

| Check | Result and scope |
| --- | --- |
| `npm run build` in `frontend/` | TypeScript + Vite production build passed; built distribution included. Existing lazy 904 KB graphics-library chunk warning remains. No dependency added. |
| `.venv/bin/python -m pytest -q tests/test_office.py` | 17 passed in 6.10 s; backend role/feed contracts unchanged. |
| Focused browser suite | **17 passed together in 3.1 min**: seven living-office, three motion, three pixel and four robot-office checks. |
| Actual isolated captures | 1440×900 desktop, 1280×720 laptop, 390 px mobile List; all 25, visible laptop controls, no mobile horizontal overflow, zero browser errors. Room cameras show actual standby Brain and lounge states. |
| Controlled preview | Browser-only running/evaluating snapshots and actual-format stage events; seated SPLICE/SYNAPSE, SPLICE→GLYPH approach/pass/receipt, GLYPH at its desk, sender back in lounge, active Brain and Reduced. Visible controlled-state banner; no real clip job or speed claim. |

The browser run uses installed Linux Chromium, the isolated app on port 8844 and a scratch Playwright configuration
selecting `living-office.spec.ts`, `motion.spec.ts`, `pixel-office.spec.ts` and `robot-office.spec.ts`, one worker,
180-second timeout. The repository sandbox config includes living-office without changing package pins. Two
initial 15-case runs passed before the recovery review added hidden/paused sender and reset-history regressions.
The final 17-case run passed together in 3.1 min, including both recovery fixes. Brain rendering checks use
actual pixels, including a frozen Brain crop while the rest of the office remains running.

[Latest evidence and editing guide](../design/robot-office/living/README.md). Earlier backend/media suite results
below belong to earlier checkpoints; those full suites were not rerun for this frontend-only change. Windows/PC
graphics/scaling and RTX 3050 CUDA/NVENC remain owner checks. GPU files, `.mcp.json`, Playwright pins, `e2e/tests`
and package dependencies were unchanged in this checkpoint. No real posts, purchases, account changes or deployment.

## PR #14 refined pixel office follow-up

Starts at `c33a291` on the same draft/unmerged branch. The owner chose refined retro pixel art and authorized using
graphics tools. PixiJS **8.22.0** now paints all 25 authored robots and their furnished rooms; one lazy shared
offscreen renderer and bounded frame cache deliver the same art to Team/detail portraits. The scoped office shell
keeps the full map, details and controls together at laptop sizes. Existing snapshots/events and motion preferences
drive activity; no backend, processing or publishing changes were made. An unavailable graphics bundle/context
restores the original Canvas map with a visible compatibility notice.

The posted Windows error comes from nested full-commit archive folders plus a long Anthropic SDK filename.
`start.bat` now gives nonblocking short-folder advice when setup is at risk. The test guide puts fresh ZIP contents
directly in `C:\CF14` and creates a fresh environment there; it never moves the partial `.venv` or normal data.

| Check | Result and scope |
| --- | --- |
| `npm run build` in `frontend/` | TypeScript + Vite production build passed; graphics library is lazy-loaded, built assets and third-party notices included. Vite reports the 904 KB graphics chunk size warning. |
| Office Python checks | `pytest -q tests/test_office.py`: 17 passed in 7.20 s. |
| Isolated browser checks | 10 passed in 59.3 s: motion (3), robot events/states/layout (4), Pixi navigation/fallback/portrait+approval pixels (3). |
| Actual app captures | Desktop 1440×900 and laptop 1280×720: all 25, matching selected portrait and visible controls; mobile List at 390 px has no horizontal overflow; no browser errors recorded. |
| Art/portrait checks | 25 Team and 100 gallery portraits rendered; Front→Back/gallery context count stable, zero page errors. Frozen Idle→Approved changes real pixels. |

Browser commands used the installed Chromium and an isolated app on port 8844. The scratch Playwright configuration
selected `motion.spec.ts`, `robot-office.spec.ts` and `pixel-office.spec.ts` from `e2e/sandbox`, one worker, 180-second
test timeout; the repository sandbox configuration allows 600 seconds. An earlier scratch run capped at 60 seconds
passed eight cases then timed out during the sequential laptop assertions; its browser session closed on timeout.
Nine cases passed with the corrected cap, then the final ten-case run passed after adding the visible approval
regression and caching the static scenery. No backend behavior changed and the full media/641-test suite was not
repeated for this follow-up. The preceding full-suite results below remain evidence for the earlier checkpoint.
[New visual evidence and how to edit it](../design/robot-office/retro/README.md).
Windows CMD execution and the owner's PC graphics, fonts/scaling, CUDA/NVENC remain unverified here. Only PixiJS
was added to frontend dependencies; GPU files, `.mcp.json`, Playwright versions and `e2e/tests` are unchanged.
Generated JavaScript retains the library's shader-string whitespace and is marked as generated in `.gitattributes`;
authored source/document whitespace checks passed.

<!-- PR14_CONTINUATION_START -->
## PR #14 continuation — 2026-10-08

Current branch: `claude/project-thread-vw1n9y`, started at `fea045d`; PR #14 stays draft and unmerged. This section
supersedes the earlier selected-only/new-upload and hidden-idle descriptions below. The historical record is retained.

Implemented: all 25 named robot stations, clear overhead states, actual task/dependency/handoff details and persisted
Follow system / Full / Reduced controls; Brain uploads/search/revision approval/edit/disable/delete/export with
per-clip saved influence; audience/topic/language/weak-story discovery filters with explicit estimate labels;
bounded responsible-stage QC repairs and A/V timestamp checks; pre-Whisper no-audio handling and preservation of
returning audio when stitching mixed live recordings; explicit NEW Public YouTube publishing and standing consent,
actual visibility reporting, preserved existing Private schedules, truthful TikTok per-post/manual blockers;
separate public/selected learning cohorts and 48-hour maturity; measured stage timings and isolated Windows launcher.

Final regression review also serializes database initialization across API threads and worker processes, rechecks
Public automation audit confirmation at approval/upload, and makes Brain export include every stored reference and
influence rather than silently limiting it to 500 rows. Atomic job claiming honors newly committed Pause/Stop.

| Check | Result and scope |
| --- | --- |
| `.venv/bin/python -m pytest -m 'not slow' -q --durations=12` | 641 passed, 7 deselected in 263.21 s |
| `.venv/bin/python -m pytest -m slow -q --durations=12` | 6 passed, 1 failed; corrected result-maturity fixture, then `tests/test_zero_touch_loop.py::test_worker_host_runs_complete_loop_and_repeats_after_restart` passed in 428.10 s. All seven cases passed across runs, not a single all-green run. |
| Sandbox browser checks | 8 passed in the sandbox run; corrected Brain selector then 1 passed (9.4 s); complete-loop recording dependency resolved with installed FFmpeg, then 1 passed (8.3 min). All ten checks covered across runs. |
| `npm run build` in `frontend/` | TypeScript + Vite production build passed; built assets committed. |
| Focused startup/core/office/TikTok | 66 passed (29.50 s), including concurrent old-schema startup in threads and a child process. |
| Other focused Python checks | Publishing 44; knowledge/public 17; full Brain export 8; public-audit/automation 33; timing/office 19; returning-audio/recovery 28. These overlap the fast suite. |
| Disposable `fea045d` database upgrade | Passed: preserved project/clip/settings/Private schedule/audience/approval/media bytes; rerun after initialization-lock change passed. |

Fast/media commands used installed FFmpeg and an isolated espeak-ng wrapper on `PATH`. Browser commands used
`CLIPFOUNDRY_E2E_CHROMIUM=/usr/bin/chromium`; the Public loop was
`npm run test:sandbox -- --project complete-loop`, with `PLAYWRIGHT_BROWSERS_PATH` pointing to a scratch recording
helper backed by installed FFmpeg. Brain's targeted rerun used a scratch Playwright config against the isolated
sandbox, running `sandbox/brain-workspace.spec.ts`. No package version or Playwright pin was changed.

The Public complete loop ran real media handlers and FFmpeg, two fake-account Public uploads with no `publishAt`,
restart recovery, mature fake-result collection, actual live/post-live handlers and deliberate pause. It advances
only the isolated fixture's approved Public due times and result age. It does not establish GPU/account/policy
verification. During validation a stale Stop claim and duplicate-column startup race were reproduced and fixed;
the slow fixture now waits for both durable published schedules before advancing simulated maturity.

The Brain proof uses a real document upload, approval, validated later blueprint and SQLite save: bold → minimal
captions. A bad-example upload also changes a later plan in its regression test. The UI lookup preview is labeled
separately. [Visual evidence and provenance](../design/robot-office/screenshots/README.md).

An old-schema database was created using `fea045d`, then opened with the new additive schema. Existing project,
clip, settings, Private schedule, audience stamp, approval and media bytes were identical. This used a disposable
fixture, never the owner's installation. Built frontend is included; `.mcp.json`, GPU dependency files, package
versions and `e2e/tests` are unchanged.

External limits: official Google/TikTok developer hosts returned proxy 403 in this continuation. Current policy
requirements could not be freshly re-read. Google's official GitHub discovery schema confirms `publishAt` needs
Private, an API field contract only. The audit settings record owner confirmation; real app approval and returned
visibility still need account checks. TikTok requires per-post consent and eligible app approval; drafts/manual
packages remain handoffs. No real videos were posted, hosting rented, account permissions changed or site deployed.

PC checks: Windows installation/scaling/fonts; RTX 3050 CUDA transcription and NVENC rendering, real-video captions
and sound sync; real account scopes, project/app audit decisions and visibility; live internet sources on the PC;
optional NVIDIA service/current terms. [Safe separate ZIP test](WINDOWS_PR14_TEST.md) and
[measured processing / server recommendation](PERFORMANCE.md). No server-speed claim is justified by this CPU-only
synthetic run. Unique-viewer/dominant-video guards, a general experiment framework and additional discovery
connectors remain outside this implementation.
<!-- PR14_CONTINUATION_END -->

Resume file for the "Audit, Finish, and Verify" task. Keep it current: another session must be able to continue
from here without repeating the audit.

## Checkpoint

| | |
| --- | --- |
| Audit date | 2026-09-28 |
| Starting commit | `3be586d` (branch `claude/ecstatic-shannon-wb1zq1`, identical to `claude/wonderful-ritchie-909tq3`) |
| Work branch | `claude/ecstatic-shannon-wb1zq1` |
| Environment of this session | Linux cloud container, Python 3.11, ffmpeg 6.1.1 (apt), espeak-ng, **no NVIDIA GPU**, Hugging Face blocked (no Whisper model download), `developers.google.com` / `developers.tiktok.com` blocked by the network policy |
| Branches (2026-09-29) | default `claude/wonderful-ritchie-909tq3`; PRs #1, #3, #2, #4 and #5 (`claude/finish-integrate-clipfoundry-zuf1xx`, plan items 10-13) merged into it |
| Overnight fix (2026-09-30) | branch `claude/fix-overnight-run-simplify-81jehi`, PR #6, merged into the default branch 2026-09-30 (the owner skipped the separate Windows test) |
| UI redesign (2026-10-01) | branch `claude/ui-redesign-prototype-f47izp`, PR #7: the owner approved the prototype (2026-09-30) and asked for the real screens, tested and merged into the default branch |
| Codex follow-up (2026-10-01) | `codex/fix-autopilot-idle` (one commit, `519c25f`, built on `97b5c9a`), integrated into the redesigned app on `claude/finish-clipfoundry-knj4r4`; see *Overnight-idle regressions* below |
| Website and legal pages (2026-10-01) | branch `claude/finish-clipfoundry-knj4r4`, PR #9: `docs/legal` is the public website (product page, Privacy Policy, Terms) written from a code audit, plus three fixes the audit found; public deployment waits for the owner's OK |
| Next concrete task | The checklist at the end (your PC, GPU and accounts); the public-video decision; then the TikTok inbox-draft decision |
| Robot office (2026-10-07/08) | branch `claude/project-thread-vw1n9y`, draft PR #14 (not merged), from the owner's master prompt on top of `eff96fb`: see *Robot office* below, `docs/OFFICE.md` and `AI_HANDOFF.md` |
| Link intake and retro studio (2026-10-02) | `codex/retro-robot-autopilot` (PR #11, ChatGPT/Codex, based on `992431e`): durable link intake and the retro robot studio. Final review on `claude/final-review-6u6bvj` (PR #12): PR #11's commit plus four fixes, see *Final review* below; both merged into the default branch |

Verification levels used below: **source reviewed** (read the code path and its callers), **unit/contract tested**
(pytest with fakes or fixtures), **local pipeline verified** (real ffmpeg render through the actual pipeline here),
**RTX 3050 verified**, **real account verified**. Imported/synthetic transcripts and fake platform adapters are
always labeled as such.

## Public internet video imports (2026-10-03)

Owner request: expand automatic pulling and local use beyond the prior reuse-covered-only discovery.
`autopilot_public_videos` defaults on: accessible HTTP/HTTPS discovery picks can be clipped locally without a
recorded reuse license. Turning it off restores restricted discovery. Explicit blocks and canceled sources still
win. Scheduling, publishing, channel confirmation, quality gates and platform approvals retain their existing rules.
Public links are not declared owned or licensed.

HTML video pages now use `media_import.public_extractor`, with native yt-dlp HTTP, recorded HLS and DASH segment
downloads. Every metadata request, redirect, manifest and fragment is DNS-pinned through `netguard`. Only local files
are handed to ffmpeg for merging. Unsupported/protected/live-native formats fail visibly. Live webpage extraction
uses the same guarded transport and the existing HLS relay. No browser credentials, saved cookies or DRM bypass.
Downloads stage in a separate folder and promote the completed container atomically; metadata and total download
bytes are bounded, cancellation and Retry-After are preserved, and a 2 GB disk reserve is checked while downloading.
YouTube metadata can fall back to public extraction without an API key; only official metadata verifies a channel.
Optional configured Tavily search adds public video pages within its existing allowance; search coverage is limited
to the configured providers, not every video on the internet. No GPU dependency changed. Frontend bundle rebuilt.

Legacy rights/discovery tests now explicitly exercise restricted mode; `test_public_video_import.py` covers the new
default, real yt-dlp generic-page extraction against a fake HTTP transport, completed download promotion, private
embedded media/redirect rejection, aggregate size caps, waits and reuse separation. Real website availability and
RTX 3050 execution must still be checked on the owner's PC.

## Baseline (before any change in this task)

| Command | Result |
| --- | --- |
| `python -m pytest -m "not slow"` | 207 passed. One earlier run failed `test_gpu_lock_is_shared_with_other_processes` (cold start); reproduced as a test race and fixed (see below). |
| `python -m pytest -m slow` | 4 passed in 404 s (synthetic espeak video, imported transcripts, real ffmpeg renders) |

## Overnight-idle regressions (2026-09-30)

The owner reported no visible progress overnight. The PC's database, Windows power state and logs are not accessible
in this session, so these are reproduced code defects, not a claim that the precise overnight cause is known.

Integration (2026-10-01): this work was built and tested on `97b5c9a` as `codex/fix-autopilot-idle`. It was then
brought into the redesigned app (PR #6's videos folder and keep-awake, PR #7's screens) on
`claude/finish-clipfoundry-knj4r4`. The backend fixes below were kept as they were. What changed in the integration:
search problems are in plain words on Autopilot → Overview (no "API calls", provider names or "quota"; the technical
line stays under Advanced → System); stopped background work is a Needs you item (first on Home) with what to do, and
not shown in the first minute after the app starts; *Needs videos* no longer says your own YouTube videos "belong to
other people" when they only lack a downloadable file; YouTube's daily limit is reported as such, not as an error. The
older screens of that branch were not used.

Found while checking the combined app (2026-10-01):
* With two posts waiting for an OK, the status line said *No covered videos found yet* because the latest finds were
  not covered. *No covered videos found yet* and *No usable video files yet* now show only while no found video was
  ever clipped (`test_skipped_finds_do_not_hide_videos_that_were_already_clipped`).
* Deleting a video left its clip scores, analysis, suggested post text and transcript windows in the database. They are
  now in `CLIP_CHILDREN`; the post history and clip fingerprints stay on purpose (they stop the same clip from being
  posted twice).

| Defect | Fix / evidence |
| --- | --- |
| Discovery only checked manually configured channels, even after an account or creator agreement was added | `scout.discovery_channels` also checks the connected YouTube channel and active, unexpired channel permissions. Every found video still needs platform-confirmed ownership/coverage and an allowed file-access method. |
| A shared folder recorded in an agreement was never scanned unless separately configured as a watch folder | `scout.discovery_feeds` scans agreement folders on the existing free folder cadence, deduplicates explicitly watched paths, and does not create extra persistent feeds or rights rules. |
| A known file becoming available (or stopping growth) did not trigger selection unless a new signal ID arrived | `feed_scan` rechecks existing entries and waiting files every three minutes, without extra web-search calls. |
| The first 80 missing files could permanently hide a later available file | Source selection examines the remaining candidates until the daily slots are filled, instead of repeatedly considering only those 80. |
| Crash recovery/cancellation could leave a source permanently ingesting/analyzing and consuming a daily slot | `reconcile_sources` marks a stopped source/project accurately after its job ends, under a transaction. Active leases/retries/waits are preserved; canceled jobs are not silently restarted. |
| A YouTube search API error discarded previously found chart results and skipped channel uploads | Per-call discovery errors preserve completed results. Requested Retry-After/network/auth stops prevent further calls; the wait remains durable. |
| Malformed Tavily replies and HTTP-200 Commons API errors looked like successful empty searches | Provider adapters report a failed search, allowing other discovery results to survive and exposing the problem. |
| The main page could say Starting/Looking indefinitely; it did not recognize library-only discovery | Main-page status now includes stopped background work, missing files/coverage, last/next search and search problems. Free library and agreement folders count as discovery options. |

Focused coverage: `tests/test_autopilot_idle.py` uses isolated databases and local HTTP platform stand-ins. The first
10 regressions failed against the original code; the search-limit and terminal-job cases also failed before their
fixes. No real publishing, account changes, GPU dependency changes or changes to `.mcp.json` were made.

## Requirement matrix

Status values: verified, implemented-but-unverified, partial, missing, externally-blocked, not-supported.

### Pipeline and clip quality

| Requirement | Existing file / symbol | Status | Evidence / test | Remaining work | External blocker |
| --- | --- | --- | --- | --- | --- |
| Manual workflow upload → transcribe → discover → edit → render → preview → export/publish | `api.py`, `jobs.py`, `pipeline/process.run_project`, `pipeline/export.py` | verified (local pipeline, synthetic espeak video) | `test_integration::full_api_flow` (slow), `test_editing`, `test_postpack` | keep green | — |
| CUDA faster-whisper transcription, model cache, word timestamps | `pipeline/transcribe.py`, `pipeline/cuda.py`, `pipeline/models.py`, `pipeline/audio.read_samples` (Whisper gets samples, not a path: PyAV 19 broke faster-whisper's decoder) | implemented-but-unverified on hardware (unit tested with fakes) | `test_gpu` (30), `test_models` (10) | run `gpu-check.bat` on the RTX 3050 | no GPU here |
| Visible CPU fallback in manual mode | `transcribe.transcribe` attempt list, `gpu.GpuManager.record_transcription` | verified (unit) | `test_gpu::cuda_failure_falls_back_to_cpu_loudly`, `test_autopilot_core::cpu_fallback_is_never_silent` | — | — |
| Strict-GPU Autopilot: CUDA failure pauses the job; CPU fallback only by explicit setting | `transcribe.transcribe(allow_cpu_fallback=...)`, `GpuTranscriptionFailed`, setting `autopilot_allow_cpu_fallback` (default off), `hunter.gpu_failed` (Wait 30 min + action item), live capture keeps recording and post-live re-transcribes | verified (unit, fake CUDA failures) | `test_gpu::test_strict_gpu_*` (3), `test_autopilot_analysis::test_strict_gpu_pauses_the_hunt_instead_of_using_the_cpu` | confirm on the RTX 3050 | no GPU here |
| Eleven-factor Viral Potential | `pipeline/virality.py` | verified (unit) | `test_virality` (17) | — | — |
| Broad candidate pool, staged ranking, boundary optimization, diversity/dedupe | `pipeline/candidates.py`, `deep.py`, `diversity.py`, `fingerprint.py`, `autopilot/hunter.py` | verified (unit + slow end-to-end) | `test_autopilot_analysis` (11) | — | — |
| Typed, versioned, validated **Clip Blueprint** persisted before rendering and consumed by the renderer | `pipeline/blueprint.py` (`Blueprint`, `build`, `validate`, `with_edit`, `for_render`), `autopilot/hunter.plan_clips` (analyzer and post-live), `live.make_live_clip`, `render.render_clip(blueprint=...)`, table `clip_blueprints` | verified (unit + local pipeline) | `tests/test_blueprint.py` (41, incl. two real multi-interval renders), `test_clip_hunter_and_analyzer_end_to_end` (slow) | no reordering (rejected, the renderer plays forwards) | — |
| Strategist cuts weak middle sentences out (multi-interval plans) only when safe; stays continuous otherwise | `blueprint.middle_cuts`, `with_middle_cuts`, `heard_fields`; `hunter.plan_clips`, `live.make_live_clip` | verified (unit + local pipeline, synthetic transcript) | `test_blueprint`: `weak_middle_parts_are_cut_out_in_order_at_sentence_boundaries`, `the_clip_stays_continuous_when_no_cut_is_safe` (7 cases), `only_sentences_that_say_nothing_are_weak`, `a_clip_with_its_weak_parts_cut_out_renders_captions_packages_and_passes_the_gate` (real render: final transcript, SRT, packaging, gate) | only filler, clear promotion and empty warm-up lines are cut (no tangents); needs a look and a listen on real videos (checklist) | — |
| Edit-decision time map (source → output) persisted; final transcript in output time | `pipeline/artifact.py` (`edit_decisions`, `final_words`, `record`), written by `render.render_clip` as `edl.json` + `transcript.final.json` | verified (local pipeline, synthetic video) | `test_artifact_quality::test_render_writes_the_artifact_record`, `test_final_transcript_keeps_only_what_is_heard` | — | — |
| Artifact metadata: path, hash, duration, codecs, dimensions, effective settings, captions, final transcript, blueprint version | `render_info["artifact"]` from `artifact.record` (with the followed blueprint's hash, intervals and unsupported list) | verified (local pipeline) | `test_render_writes_the_artifact_record`, `test_the_render_follows_a_plan_that_cuts_out_a_sentence` | — | — |
| Atomic artifact finalize | `render.render_clip` (`render.tmp.mp4` → `os.replace`) | verified (source reviewed) | — | — | — |
| Packaging after render from the edited transcript; several options; ≤3 AI retries; grounded fallback or block | `autopilot/packaging.py` (`clip_sentences` reads the final transcript of the active render; rows carry `artifact_sha256`), `pipeline/postpack.py` | verified (unit + local pipeline) | `test_autopilot_packaging` (6), `test_the_gate_decides_what_is_scheduled_and_uploaded` | a fallback with problems is still stored as selected, but the gate now marks that platform's text failed and it is not scheduled | — |
| Independent final quality gate (decodable, streams, duration/dimensions, caption bounds, black/frozen frames, silence) bound to the artifact hash; only passing artifacts schedule/publish | `pipeline/quality.py` (media checks), `autopilot/gate.py` (`quality_check` job, `quality_reports` table, `schedulable`, `verify_file`), wired into `scheduler.candidates`, `scheduler.approve`, `publisher.publish`; Publish Center badge and check list | verified (local pipeline, synthetic media: clean, truncated, wrong size, black, frozen+silent, frozen+speech, muted speech, late captions, mid-word cuts) | `tests/test_artifact_quality.py` (10), `test_autopilot_publish::test_only_files_that_passed_the_final_quality_gate_are_uploaded`, e2e `publish-center.spec.ts` | semantic checks are estimates from the selection-time analysis; no LLM review | — |
| Material edits invalidate packaging, quality report and consent | reports keyed by file (stamp + SHA-256); packaging rows keyed by artifact SHA-256 (stale → repackaged); `scheduler.approval_hash` for consent | verified (unit + local pipeline) | `test_the_gate_decides_what_is_scheduled_and_uploaded`, `approval_rules_and_invalidation` | — | — |

### Orchestration and resources

| Requirement | Existing file / symbol | Status | Evidence / test | Remaining work | External blocker |
| --- | --- | --- | --- | --- | --- |
| Durable jobs with states, attempts, capped backoff with jitter | `autopilot/queue.py` | verified (unit) | `test_autopilot_core` (22) | — | — |
| Retry-After handling (never shortened) | `publish.common.retry_after` (seconds or HTTP date, no upper limit) on every YouTube/TikTok API error (`PublishError.retry_after`); `common.asked_to_wait` (the platform's wait, else 60 s for a rate limit without one). Up to `SHORT_WAIT` (60 s) is waited out in place, exactly, in steps STOP can interrupt (`common.sleep_exactly`). Anything longer ends the attempt and the job runs again at exactly that time: in Autopilot `publisher._platform_wait` raises `queue.Wait` (no attempt used) and holds the platform's other posts until then (`block_platform`); a manual upload goes back to *queued* with `info.retry_at` and a timer that survives a restart (`PublishWorker.later` / `resume_waiting`) and can be cancelled. The YouTube upload session is kept, so the same upload continues from the offset YouTube confirms (`_resume_offset`, which also honors Retry-After); a finished TikTok upload is only asked about again, never re-uploaded (a rate-limited status check never starts a second upload). Downloads (`hunter._http_download`), web search (`web:wait_until`) and trend scans (`next:trend_scan`) wait the same way. `queue.claim` restarts the time limit on every run | verified (unit, fake platforms) | `test_youtube::test_retry_after_is_read_in_both_forms`, `test_upload_pauses_wait_exactly_as_asked_and_can_be_stopped`, `test_a_long_youtube_wait_is_not_shortened_and_the_upload_continues_then`, `test_a_waiting_upload_survives_a_restart_and_can_be_cancelled`, `test_tiktok::test_a_rate_limited_chunk_waits_as_long_as_tiktok_asks`, `test_autopilot_publish::test_a_platform_wait_is_never_shortened`, `test_after_a_long_youtube_wait_the_same_upload_continues`, `test_a_rate_limited_status_check_never_uploads_a_second_copy` | real platform answers (header presence is the platforms' choice) | — |
| Waiting (consent, quota, GPU) does not consume attempts | `queue.claim` (`bump = 0` after `waiting`) | verified (unit) | `waiting_jobs_resume_without_using_an_attempt` | — | — |
| Atomic claim | `queue.claim` (`BEGIN IMMEDIATE`) | verified (unit) | `idempotent_enqueue_and_priority` | — | — |
| Autopilot-off priority restriction **inside** the atomic claim | `queue.claim(min_priority=...)` (in the `BEGIN IMMEDIATE` transaction), `host.WorkerHost._claim` | verified (unit) | `test_the_priority_floor_is_part_of_the_claim`, `autopilot_off_only_runs_manual_jobs_and_stop_all_blocks_everything` | — | — |
| Stale workers cannot finalize reclaimed jobs | `queue._finish`/`renew` check the lease owner; `host.WorkerHost._token` gives every claim its own token | verified (unit) | `test_a_recovered_job_cannot_be_finished_by_its_old_thread`, `recovery_after_a_crash` | — | — |
| Crash between stage output and downstream handoff | handlers enqueue (idempotency keys) before `complete` | partial | source reviewed | replay re-runs the whole stage; `analyze_source` replay deletes and recreates the project's clips | — |
| Shutdown does not release exclusivity while old workers can still act | `WorkerHost.stop` keeps the host lock until every worker thread has exited | verified (unit) | `test_a_stopping_host_keeps_exclusivity_until_its_threads_are_done` | — | — |
| STOP ALL JOBS persistent across restart, stops dispatch, signals running work | `state.paused`, `routes.stop_all`, host heartbeat | verified (unit) | `cancel_and_stop_all`, `autopilot_off_only_runs_manual_jobs_and_stop_all_blocks_everything`, `test_an_upload_stopped_halfway_is_reconciled_with_the_platform` (an upload whose job was canceled is checked with the platform, never re-uploaded blindly) | — | — |
| One heavy GPU operation at a time across processes; recovery | `gpu.GpuManager.heavy`, `locks.FileLock` | verified (unit) | `gpu_lock_serializes_heavy_work`, `gpu_lock_is_shared_with_other_processes` (race in the test fixed) | — | — |
| GPU lock also covers GPU-using render steps (NVENC) | `render.render_clip` holds `gpu.manager.heavy("video encode")` around the decode/encode step when the encoder is `h264_nvenc`; x264 renders never wait; framing analysis and thumbnails stay outside the lock | verified (unit, x264 standing in for NVENC) | `test_artifact_quality::test_an_nvenc_encode_waits_while_the_gpu_is_transcribing`, `test_a_cpu_encode_does_not_wait_for_the_gpu` | confirm on the RTX 3050 (checklist 6) | no GPU here |
| VRAM detection and resource status | `gpu.GpuManager.memory` (nvidia-smi), `status` | implemented-but-unverified | `gpu_waits_for_free_memory_then_gives_up` (fake) | verify on the RTX 3050 | no GPU here |
| Bounded downloads / source size / duration | `netguard.download(max_bytes=...)`, `hunter.max_source_bytes`, `hunter.check_length`, yt-dlp `max_filesize` + duration filter (`jobs.download_url(max_bytes, max_seconds)`), free-disk reserve before a download; settings `autopilot_max_source_gb` (8) and `autopilot_max_source_minutes` (240) | verified (unit, local HTTP server) | `test_netguard.py` | CPU threads for Whisper are capped at 8 (existing); no global disk quota for renders | — |

### Discovery, rights and sources

| Requirement | Existing file / symbol | Status | Evidence / test | Remaining work | External blocker |
| --- | --- | --- | --- | --- | --- |
| Pluggable providers (YouTube Data API, watch folders, streams, signal feeds); unavailable ones shown as unavailable | `autopilot/providers.py`, `scout.py` | unit tested (fake API) | `test_autopilot_discovery` (14) | real API call on the user's key | API key; network |
| Metric provenance (observed / estimated / unavailable), missing = null, velocity needs time-separated observations | `autopilot/trends.py` | verified (unit) | `missing_metrics_are_never_filled_in`, `momentum_beats_size` | — | — |
| Rights statuses, basis, evidence URL, expiry; recheck at ingest, schedule, publish | `autopilot/rights.py` (`gate` re-evaluates rules each time) | partial | `rights_evaluation_order_and_policy`, `repeats_and_blocked_sources_are_never_scheduled`, `gates_before_every_upload` | allowed platforms and attribution are modeled for agreements only | — |
| A channel named by a list is only a claim: channel rules and ownership apply only after the platform confirms the exact video's channel (decided by the owner 2026-09-29: restrict) | `autopilot/verify.py` (YouTube Data API `videos.list`, or the Data API signal that found the video; TikTok oEmbed by video number); the link must lead to the same video; stored per source in `channel_check`, bound to platform, video, channel and link. `rights.evaluate`: Owned only when confirmed, channel rules and platform-host link rules skipped when not; an unconfirmed video is *Not covered* with the reason in the Activity log (no question, no popup) and is asked about again later (busy platform after 1 h, unknown video after 1 day). A confirmed channel still needs a rule or agreement. Checked again before every stage: `rights_check` / `confirm_channels` (maintenance) re-judge sources already queued and cancel their hunt, `select_for_today`, `hunt_source`, `analyze_source`, `live_capture`, *Clip now* and the publisher. A feed row can no longer overwrite what the YouTube API reported about a video | verified (unit, fake platforms) | `test_autopilot_channels.py` (7): false claims of your channel and of an allowed channel on YouTube, TikTok and an unsupported platform, a confirmed channel without a rule, queued-before sources, an unreachable platform, feed overwrites, link parsing | real Data API and oEmbed answers | TikTok oEmbed availability is TikTok's choice |
| Public local discovery separated from reuse/publishing; restricted discovery is optional | `rights.local_allowed`, `autopilot_public_videos` (on), `access.resolve`, `media_import.public_extractor` | unit/contract tested | `test_public_video_import.py`, restricted-mode rights/discovery suites | real website availability on the owner's PC | website login, DRM and platform restrictions |
| Remote media URLs and redirects checked against private/internal networks | `netguard.py` (`check`, `open_checked`, `download`, `get_text`, `ffmpeg_input`), used by `hunter._http_download`, `providers.signal_feed`, `live.input_args`; trust from `rights.url_typed_by_user` | verified (unit, local HTTP server, fake DNS) | `test_netguard.py` (18) | ffmpeg resolves stream hosts itself, so live stream URLs are checked but not pinned | — |

### Scheduling and publishing

| Requirement | Existing file / symbol | Status | Evidence / test | Remaining work | External blocker |
| --- | --- | --- | --- | --- | --- |
| UTC instants, America/Chicago display, active hours, gaps, per-platform limits | `autopilot/scheduler.py` | verified (unit) | `test_autopilot_scheduler` (11), `test_autopilot_integrity::test_planning_across_a_daylight_saving_change`, `missed_posts_are_replanned_once_each_without_a_burst_across_the_change` (both America/Chicago changes) | — | — |
| Missed slots re-planned without a burst | `scheduler.process_due` (`OVERDUE_MINUTES`) | verified (unit) | `due_processing` | — | — |
| Cold-start timing labeled; learned timing needs reliable groups | `scheduler.Timing`, `learner` | verified (unit) | `learned_timing_picks_your_best_hour` | — | — |
| Dynamic replacement: threshold, freeze window, audit; never after approval without re-approval | `scheduler.try_replace`, `replacement_blocked`, `approve`; table `slot_replacements` (backfilled on upgrade) | verified (unit) | `dynamic_replacement_with_audit_trail`, `approved_posts_are_only_swapped_after_approving_the_replacement`, `test_autopilot_integrity`: one pending swap per slot, declined swap not proposed again, cooldown follows the slot and its posts, full audit trail, DB upgrade | — | — |
| Approval bound to exact content and visibility | `scheduler.approval_record`, `approval_problem` (SHA-256 of the video, scheme 2), `publisher` re-check | verified (unit, fake platforms) | `approval_rules_and_invalidation`, `test_autopilot_integrity`: same size and time stamp with other bytes, across restarts, missing/unreadable file, approvals from before the hash, YouTube re-approved only after the gate checked the new bytes, TikTok always asks | — | — |
| Upload recovery without duplicates; uncertain outcome paused for review | `youtube.upload(on_final_chunk, may_be_complete)` raises `OUTCOME_UNKNOWN` instead of starting a second session once the last bytes may have arrived; `publisher.outcome_unknown` looks for the video among the channel's newest uploads (never an older one with the same title), else status `reconciling` + action item; `POST /api/autopilot/scheduled/{id}/resolve`; Publish Center buttons | verified (unit, fake platform) | `test_autopilot_publish::test_a_lost_answer_after_the_last_bytes_is_found_not_uploaded_twice`, `test_an_upload_that_cannot_be_confirmed_waits_for_you`, `interrupted_upload_resumes_without_a_duplicate` | TikTok: a publish ID is stored right after init, so its outcome is always read back; confirmed with real accounts pending | real accounts |
| Unique clips and platform publications counted separately | `routes.today_posts`, `scout.day_bounds`; Home and System details | verified (unit + e2e screenshot) | `the_dashboard_counts_unique_clips_and_platform_posts_separately`; sandbox: *Scheduled: 1 clip · 2 platform posts* | — | — |
| YouTube: OAuth PKCE, resumable upload, made-for-kids, publishAt, locked-private honesty | `publish/youtube.py`, `publish/jobs.py` | unit/contract tested (fake platform) | `test_youtube` (13), `test_autopilot_publish` (8) | real-account check | credentials; audit |
| TikTok: creator info, no default privacy, interactions, disclosure, music confirmation, inbox fallback | `publish/tiktok.py`, `components/approve.tsx` | unit/contract tested (fake platform) | `test_tiktok` (12) | Direct Post eligibility of a private single-user tool | externally-blocked (see `PLATFORM_CAPABILITIES.md`) |
| YouTube quota buckets (search.list, videos.insert, other units), reset Pacific, reserves, cache | `autopilot/quota.py` | verified (unit) | `quota_budgets_share_reserve_and_exhaustion` | budgets are settings, not a versioned config | project quota is not readable by API |

### Live, learning, security, data, UI

| Requirement | Existing file / symbol | Status | Evidence / test | Remaining work | External blocker |
| --- | --- | --- | --- | --- | --- |
| Live capture in segments, checkpoints, post-live analysis, supersede only unpublished | `autopilot/live.py` | verified (local, synthetic stream file) | `test_autopilot_live` (3, one slow) | — | real stream |
| Learning from real metrics only, minimum samples, shrinkage, frozen features at publish time | `autopilot/learner.py`, `publish/jobs.feature_snapshot`, `publish/stats.py` | verified (unit) | `test_autopilot_learning`, `test_performance` | — | real accounts |
| Local-only server, app header, DNS-rebinding guard | `api.py` (`local_only`, `app_request`) | verified (unit + e2e) | `test_youtube::publishing_only_from_this_computer_and_this_page`, `e2e/tests/api-guards.spec.ts` | — | — |
| Secrets: DPAPI on Windows, explicit unencrypted storage elsewhere; every secret setting sealed (AI keys too, older plaintext sealed at start); request addresses (a YouTube API key travels in one) kept out of the logs | `secure.py`, `config.SEALED_KEYS`, `db._migrate`, `__main__.setup_logging` | verified (unit, non-Windows path) | `test_youtube::secret_sealing_round_trip`, `test_autopilot_core::every_secret_setting_is_sealed_at_rest_including_older_saves`, `::request_addresses_stay_out_of_the_log` | DPAPI path verified only on Windows | — |
| YouTube 30-day data rule (hourly while Autopilot is on, and at every start; a found video's age counts from YouTube's last answer) | `scout.youtube_retention`, `api._youtube_retention` | verified (unit) | `youtube_data_is_deleted_after_30_days`, `youtube_data_age_counts_from_youtubes_last_answer`, `youtube_data_is_deleted_at_start_even_when_autopilot_is_off` | titles, channel and link of used videos, post IDs and the channel name are kept longer (stated on the Privacy Policy; owner to decide before any Google audit) | — |
| Website: product page, Privacy Policy, Terms (publisher, email and Minnesota law from the owner) | `docs/legal/`, `/legal/` routes | written from a code audit (52 corrections applied); not publicly deployed | `legal_pages_are_served`, `the_website_is_ready_to_publish` | public deployment (owner's OK); no lawyer review | owner decision |
| UI controls call real backend, correct after refresh | `frontend/src/pages/*` | read-only e2e suite + sandbox beginner flow | `e2e/tests` (42 read-only tests), `e2e/sandbox/beginner-flow.spec.ts` | — | — |

### Vertical slice (section 4 of the task)

| Step | Status |
| --- | --- |
| Create source → persist rights → enqueue job → transcript (imported fixture) → candidates → select → render MP4 | local pipeline verified (`test_autopilot_analysis::clip_hunter_and_analyzer_end_to_end`, synthetic espeak video, imported transcript) |
| Persist blueprint before rendering | verified (local pipeline) |
| Package from the edited transcript | verified (final transcript of the active render; rows bound to its SHA-256) |
| Validate artifact and metadata (final quality gate) | verified (local pipeline, synthetic media; see `test_artifact_quality.py`) |
| Persist publication intent, show in Publish Center | unit tested (`publish_center_api`) |
| Restart → consistent state → export | export verified in the slice test; restart covered by separate tests (`restarted_host_resumes_interrupted_work`, `manual_work_resumes_after_restart`), not inside the slice test |
| Whole slice in one test | `test_clip_hunter_and_analyzer_end_to_end` (slow): owned folder → rights rule → hunt (Whisper stand-in: imported transcript) → analyze → plan → render → package → gate → schedule (awaiting approval) → export |

### Zero-config Autopilot UX (2026-09-29)

Request: connect YouTube, connect TikTok, START AUTOPILOT, and ClipFoundry does the rest; technical controls only
under Advanced; ask the user only what really needs them. The backend and worker system were reused unchanged; new:
`autopilot/home.py` (plain-language view, START, one-click rights answer), `POST /api/autopilot/start`,
`POST /api/autopilot/sources/{id}/permission`, `status()["home"]`, `scout.still_needed` / `scout.rights_questions`.

| Requirement | Existing file / symbol | Status | Evidence / test | Remaining work | External blocker |
| --- | --- | --- | --- | --- | --- |
| First run: connect YouTube, connect TikTok, START AUTOPILOT (one platform is enough) | `Autopilot.tsx` `Onboarding`, `ConnectAction`, `accounts.SetupAndConnect`; `home.start` (uses the connected platforms) | verified (unit + sandbox e2e) | `test_autopilot_simple::a_fresh_user_connects_youtube_and_starts_without_adding_a_source`, `beginner-flow.spec.ts` | a real account on the user's PC | the user's own Google/TikTok developer app (platform rule, cannot be automatic) |
| No manual source needed; sources created internally from discovery | `scout.trend_scan` / `source_scout` with the connected account (existing) | verified (unit + sandbox e2e) | `autopilot_discovers_and_creates_sources_by_itself`, beginner flow | — | — |
| Missing optional providers never stop Autopilot or nag | `providers.UNAVAILABLE`, `home.needs_you` (quota notices stay under Advanced) | verified (unit) | `missing_optional_providers_do_not_stop_autopilot` | Tavily and Metricool do not exist in ClipFoundry (no integration to enable) | — |
| Defaults: US, English, 3 sources/day, 15/day target, 5 clips/source, replacement, learning, live monitoring, scheduling, publishing of approved posts | `config.DEFAULT_SETTINGS` (live monitoring now on by default) | verified (unit) | first test above checks every value | trend categories: YouTube's chart plus the broad default topics | — |
| Simple main page: today, currently, next post, accounts, Needs you, top opportunities, upcoming posts; empty states in plain words | `home.view`, `Autopilot.tsx` `Home` | verified (unit + e2e + screenshots) | `the_main_page_speaks_plainly_and_needs_no_configuration` (no jargon in any text), `autopilot.spec.ts` | — | — |
| Technical detail under Advanced (System details, Sources & rights, Jobs, Learning); old addresses still work | `Autopilot.tsx` `ADVANCED`, `OLD_SLUGS` | verified (e2e) | `autopilot.spec.ts` tabs tests, `advanced_controls_are_all_still_there` | — | — |
| Rights gate unchanged; questions only when needed | `scout.rights_questions` (only while today's plan is short, Source Score ≥ 50, at most 3, never a platform live stream that could not be recorded); `home.answer_rights` (Yes = Allowlisted for that video, No = Blocked) | verified (unit + sandbox e2e) | `rights_are_still_gated_and_answered_in_one_click`, `you_are_asked_only_about_strong_videos_and_only_when_needed`, `test_trend_and_source_scout` (adjusted: one question when one source is short) | — | — |
| YouTube-hosted videos are still not downloaded by default | `rights.download_allowed` (unchanged); Needs you → ADD THE VIDEO FILE | verified (unit + sandbox e2e) | same tests | this is the main remaining manual step for other creators' videos: the user's yes, then the original file (or the Advanced download setting, only with YouTube's and the rights holder's permission) | YouTube Terms of Service |
| Dropped accounts: one plain Needs you message | `home.needs_you` (`needs_reconnect`, or not connected while posts are planned; deduplicated with the publisher's own notice) | verified (unit) | `a_dropped_account_is_one_plain_needs_you_message` | — | — |
| Manual content stays optional and working | `+ Add content manually` (link, file, folder, upload); **bug fixed:** a source added by hand was never scored and was discarded as "unlikely to contain a strong clip" | verified (unit, failed before the fix) | `adding_content_by_hand_still_works` | — | — |
| Settings: General (accounts, on/off, daily target, automatic publishing) and Advanced (everything else) | `Settings.tsx`, `autopilotSettings.tsx` | verified (e2e) | `settings.spec.ts` | — | — |

### Hands-off Autopilot (2026-09-29)

Request: discover promising videos, obtain usable files, clip, schedule and publish with as little daily involvement
as possible; no per-video permission questions; automatic eligibility only from real coverage; access to the file
decided separately from reuse rights; an explicit automatic-publishing option where the platform allows it. New:
`autopilot/access.py` (how a file may be obtained), `autopilot/autopublish.py` (the stored permission),
`rights.add_agreement` (an agreement is stored as rights rules that carry its conditions), table `publish_consents`, `GET/POST/DELETE
/api/autopilot/agreements`, `GET /api/autopilot/activity`, `GET/POST/DELETE /api/autopilot/auto-publish`.

| Requirement | Existing file / symbol | Status | Evidence / test | Remaining work | External blocker |
| --- | --- | --- | --- | --- | --- |
| Discovery every few hours within quotas and a cost limit; originals behind short clips; dedupe of re-uploads | `providers.py` (YouTube originals, Tavily web search, Wikimedia Commons library), `trend_poll_minutes` 180, `discovery_monthly_budget_usd` (0 = never spend) | verified (unit, fake APIs) | `test_autopilot_auto.py` discovery tests (6) | real Tavily and Commons calls | Tavily key (optional) |
| Web search never invents TikTok statistics; provenance and observation time kept; estimates labeled | `trends.m`, providers | verified (unit) | `web_search_finds_tiktok_links_without_inventing_statistics` | — | — |
| Eligibility without per-video questions: owned, creator agreements with conditions, CC BY, public domain / CC0; unclear = skipped, activity log | `rights.py` (agreements, licenses, `rights_ask_per_video` off), `home.activity` | verified (unit + sandbox e2e) | agreement, expiry, non-commercial and library tests; beginner flow | — | — |
| Agreements do not clear third-party music | `gate.sound_rights_check`, `quality.py` | verified (unit) | `music_is_rejected_under_coverage_for_the_creators_own_material` | music detection is an estimate | — |
| File access separate from reuse rights; provenance stored with each file | `access.resolve` / `record`, `hunter` provenance.json | verified (unit + sandbox e2e) | `a_creator_folder_supplies_the_file_and_it_keeps_its_provenance`, `no_allowed_way_to_the_file_skips_to_the_next_video` | — | — |
| Framing checked from the render record | `render_info` crop width and layout, `quality.py` | verified (unit) | `framing_is_checked_from_the_render_record` | — | — |
| Explicit automatic publishing (YouTube): stored wording and settings, posts labeled *approved automatically*, off returns posts to review, held on warnings | `autopublish.py`, `scheduler.py`, `publisher.py`, `components/autoPublish.tsx` | verified (unit) | 5 publishing tests | real upload | Google audit keeps uploads private until then |
| TikTok: your OK on each post, shown as such | `autopublish.NOT_SUPPORTED` | verified (unit) | `one_complete_path...` (TikTok items wait) | — | TikTok's Content Sharing Guidelines |
| Posting window 9:00-21:00 America/Chicago, spread; no burst after downtime; DST | `scheduler.py`, `autopilot_active_end` 21 | verified (unit) | `after_downtime_missed_posts_are_spread_out_not_dumped`, DST tests | — | — |
| One complete path: discover → eligibility → file → render → check → schedule → approved automatically → uploaded and scheduled | all of the above | verified (sandbox: stand-in library and YouTube, synthetic transcript, real ffmpeg renders) | `one_complete_path_from_discovery_to_a_post_scheduled_on_youtube` (slow) | the same on real accounts | accounts |
| Main page: START / PAUSE, activity, how posts go out, PC-on note; topic step at setup | `Autopilot.tsx`, `home.view` | verified (unit + e2e) | `the_main_page_speaks_plainly_and_needs_no_configuration`, `autopilot.spec.ts`, beginner flow | — | — |

### Overnight run did nothing (2026-09-30)

Report: Autopilot was left on overnight and did nothing; make it simple enough for a 10-year-old. Reproduced here with
a simulated night (fake YouTube/TikTok/Commons, real worker threads, the default settings a new user gets): every
video discovery found belonged to other creators and was skipped, the free-license library returned only share-alike
or short videos, and the page said *Needs you: Nothing right now* all along. Nothing on the page said that Autopilot
had nothing it may use or what would help. Separately, nothing kept Windows from putting the PC to sleep. The logs of
the real night on the owner's PC were not available to this session.

| Requirement | Existing file / symbol | Status | Evidence / test | Remaining work | External blocker |
| --- | --- | --- | --- | --- | --- |
| Say plainly, once, when Autopilot has nothing it may use, and what helps | `home.needs_videos` (Needs you type `videos`); since PR #11 Home's lead (*Nothing needs you. Add a video to make clips.*), the overview's *Now* line and *Your videos* panel instead of a Needs you item | verified (unit + sandbox e2e) | `a_night_of_other_peoples_videos_says_so_and_your_own_video_is_clipped`, beginner flow | — | — |
| One obvious place for your own videos, created and watched on START, outside the app folder, Owned | `autopilot/myvideos.py`, `GET /api/autopilot/my-videos`, `POST /api/autopilot/my-videos/open`, `Autopilot.tsx` (step 4, *Your videos* card) | verified (unit + sandbox) | same test; `the_videos_folder_is_set_up_once_and_a_removal_is_respected`; sandbox: a dropped video was clipped and scheduled | File Explorer opening on Windows | — |
| Keep the PC awake while Autopilot is on (Windows) | `awake.py`, `host.Supervisor._keep_awake`, setting `autopilot_keep_awake` | verified (unit, fake kernel32) | `the_pc_is_kept_awake_while_autopilot_is_on` | real Windows sleep behavior | — |
| Say whether the PC is really kept awake; when Windows refuses, show it with steps, retry, clear it on success (review finding on `2836a44`) | `awake.KeepAwake.status`/`error`, `home.keep_awake`, `home.needs_sleep_fix` (Needs you type `sleep`), `host.Supervisor._keep_awake` | verified (unit, fake kernel32) | `a_refused_keep_awake_request_is_shown_with_what_to_do_until_a_retry_works`, `turning_autopilot_or_keep_awake_off_clears_the_sleep_warning`, `the_same_thread_asks_and_gives_up_keeping_the_pc_awake` | a real refusal on Windows was not seen | — |
| Show when it looks again and when posts go out; leave the window open | `home.next_look`, `home.pc_note`, `__main__._serve` | verified (unit) | `the_main_page_speaks_plainly_and_needs_no_configuration` | — | — |
| New posts that need your OK are listed right away (not one tick later) | `scheduler.remind_approvals` | verified (unit) | scheduler suites | — | — |
| A video that gave clips but fewer than expected is shown as used, with its clip count | `home.activity` | verified (sandbox) | simulated night | — | — |

### UI redesign (2026-10-01)

Request: a calm, simple look ("quiet dark studio") with four places (Home, Autopilot, Library, Posts) plus Settings,
built from the approved prototype in `design/ui-redesign/` (SPEC.md, ROUTE_MAP.md), keeping every feature, saved
data and publishing permission. Every row was checked in Chromium on Linux against the sandbox (fake YouTube and
TikTok, synthetic transcript); Windows rendering was not seen.

| Requirement | Existing file / symbol | Status | Evidence / test | Remaining work | External blocker |
| --- | --- | --- | --- | --- | --- |
| Five places in the sidebar, a Menu drawer on narrow windows, skip link, focus on the page title after moving | `App.tsx` | verified (e2e) | `app-shell.spec.ts` | look on Windows (checklist 15) | — |
| Old addresses keep working and Back does not bounce on them | `router.ts` `ALIASES` (replaceState) | verified (e2e) | `old addresses open the new pages…` | — | — |
| Leaving unsaved changes asks (links, Back, closing the window); Stay keeps history usable; going Home asks too | `router.ts` `useLeaveGuard`, `leaveTo`, `App.tsx` `LeaveDialog` | verified (e2e + browser script) | `library.spec.ts` (editor), `settings.spec.ts`; link → Stay → Back asks again → Discard goes back once | — | — |
| One shared status poll; a lost connection shows no green state | `status.tsx`, `ConnectionContext` | verified (browser script) | API refused for 8 s on Home and Autopilot: *ClipFoundry is not answering* shown, state *Unknown*, no green pill (4 before) | — | — |
| Home leads with the first Needs you item; welcome on first use; recent videos and clips; coming up | `Home.tsx`, `needsYou.tsx` | verified (e2e) | `home.spec.ts` | — | — |
| First-time setup in 3 steps; the choice is kept with the settings | `Setup.tsx`, setting `setup_mode`, `home.setup.mode` | verified (unit + sandbox e2e) | `a_fresh_user_connects_youtube…`, beginner flow | — | — |
| Autopilot overview with honest facts (kept awake only when Windows agreed, GPU vs the real mode), the video being worked on with the job's own progress | `Autopilot.tsx`, `home.working` | verified (unit + e2e) | `the_page_shows_the_video_being_worked_on…`, `autopilot.spec.ts` | real keep-awake and GPU states on Windows | — |
| Sidebar counts equal the Posts tabs (outdated approvals wait for review; failed and blocked are problems) | `home.post_counts` | verified (unit) | `the_page_shows_the_video_being_worked_on…` | — | — |
| Posts tabs and a page per post replacing the approval dialog (checkbox, every platform field, Publish now only when approved, unconfirmed uploads resolved by hand) | `Posts.tsx`, `PostReview.tsx`, `postShared.tsx`, `GET /api/autopilot/scheduled/{id}` | verified (unit + e2e) | `test_publish_center_api`, `posts.spec.ts` | real accounts | accounts |
| An approval made before a re-render asks again, in plain words | `postShared.tsx` (reads `approval_valid`, `approval.video_sha256`, `approval_invalidated`) | verified (sandbox) | post pages in the sandbox | — | — |
| Add video, Library (filter, chips, delete asks), source video page, clip editor (5 groups, versions, save does not render) | `Create.tsx`, `Library.tsx`, `ProjectView.tsx`, `ClipEditor.tsx` | verified (e2e + sandbox) | `create.spec.ts`, `library.spec.ts`; Save sends no render request | video playback (headless Chromium here cannot play H.264) | — |
| Settings: Accounts, Defaults, Advanced; every setting has a place; secrets masked with Replace | `Settings.tsx`, `settingsFields.tsx` | verified (e2e) | `settings.spec.ts` | — | — |
| Every page at 1440, 1366, 768 and 390 px: no sideways scrolling, one title, no "undefined", no serious axe finding | all pages | verified (browser script, axe-core) | 28 addresses × 4 sizes, 0 problems | 200% zoom and a screen reader | — |

## Durable Autopilot and retro robot studio (2026-10-02)

Built from verified remote default `992431e` on `codex/retro-robot-autopilot`; the default branch is unchanged.
The owner's two coding briefs replace ordinary per-video Autopilot interruptions with continued work and add a
retro studio across the working app. [Design and original assets](../design/retro-studio/SPEC.md) and
[actual sandbox screenshots](../design/retro-studio/screenshots/) document the result.

| Requirement | Implementation | Verification | Remaining external checks |
| --- | --- | --- | --- |
| Durable public video/stream intake, canonical duplicates, move-to-top, cancel/remove/retry | `autopilot/intake.py`, additive sources columns, identify_link job, apLinkIntake.tsx | intake/local-rights contracts; real manual-link browser intake | Real platform metadata/media access |
| Local retention without unknown reuse granting publishing permission | `rights.local_allowed`, fresh cancel/block gates, hunter/live/packaging | Explicit block/cancellation and fresh publishing tests; local unknown-rights clip passes gate without creating posts | Owner's real source permissions |
| Continue after ordinary failures; refill selection; preserve pause/stop; resume after crash | scout/queue/host/home, durable selection and stable clip IDs | Failed source followed by real checked upload; restart and second discovery; cancellation/recovery regressions | Overnight run on owner's PC |
| User links and manual work precede ordinary pending renders at safe boundaries | fresh source priority, queue.has_higher_priority_work, hunter.render_in_priority_order; post-live uses the same helper | Higher-priority work arrives after the first clip; continuation keeps its exact bytes and renders only the remainder without using another attempt | Hardware scheduling and latency on owner's PC |
| Closing the app preserves an in-progress upload and resumes the same session | publisher cooperative-shutdown guard + host restart Wait | Fake YouTube accepts the first chunk, host closes and resumes the same publication/session; exactly one uploaded video | Real account/network interruption |
| Manual startup recovery leaves automatic/live work to its durable owner | db.interrupted_work + explicit manual_render_pending provenance | Live/automatic pending clips, canceled work and explicit manual rerenders tested; manual versions preserved | Restart on owner's saved database |
| Failed restoration retains the last saved media; recovery preserves newer completed output | gate backup retention and render identity guards | ENOSPC copy failure retains backup; later restoration succeeds; completed renders at the same/new location survive recovery | Real disk/device failure |
| Live recording fairness, crash-safe segments/words, post-live reuse and graceful recorder ownership | `live.py`, bounded processing turns and OS source locks | Actual growing-file and upcoming→live→ended FFmpeg tests; wrapper EOF/normal exit regressions | Actual live server and RTX 3050 |
| Public HTTP/HLS checked redirects and nested resources | `stream_access.PublicStream`, pinned netguard relay | Security contracts plus actual encrypted HLS consumed by FFmpeg; bounded resources and durable Retry-After | DASH and pasted non-HTTP streams explicitly unsupported |
| Bounded automatic quality/text repair without changing the checked publishing artifact | gate regeneration/text repair, exact-file reports/consent retained | Recovery and artifact tests; sandbox upload SHA-256 equals passing report and approval | Real platform upload |
| True repeated loop through discovery, processing, quality, schedule, upload, results, learning | `tests/zero_touch_support.py`, `test_zero_touch_loop.py`, browser sandbox | Real local pipeline and scheduler; fake platform receives exact bytes and scheduled publishAt; learner observes 2/10 samples and invents no weights | CUDA Whisper and real platform metrics |
| Consistent cozy navy/slate/cream/amber screens, original robots and heading font | Shared tokens; Home/Autopilot/Library/source/editor/Posts/Settings/setup/dialog styles | Actual populated and empty/error captures, laptop and 200%-equivalent layout; 13-screen axe scan has zero WCAG violations | Physical 200% browser zoom and screen reader on Windows |
| Real simultaneous activity; brief attention/completion gestures; truthful progress and stopped states | Shared polling + current job_kind/fresh progress; RobotOffice.tsx | Worker API contracts and six motion/state browser checks; real pipeline activity capture | Real PC performance |
| Persistent Reduce motion; OS preference; hidden-tab pause | motion.tsx + Settings Defaults Appearance; browser local storage only | Keyboard, reload, cross-tab, OS changes, denied storage, hidden-tab checks | — |
| Existing navigation/routes/Back/unsaved editor guard, original video appearance and posting safeguards | Existing router and APIs preserved; grouped local-day agenda; exact render validity retained | 60 populated read-only browser checks, 1 fixture-dependent skip; source/editor/post-review captures | Owner's playback/hardware |

The first broad slow run caught a recorder wrapper shutdown defect (buffered stdin in a daemon thread). Raw
`os.read` fixed it and the original real growing-file capture/render case passed. The same early run imported stale
fixture adapters and a discovery slot shorter than production's idempotency period; correcting the adapters and
accelerating only the fake upstream cadence made both complete-loop tests pass. Browser setup navigation and
render-ready versus quality-ready waits were also corrected without relaxing outcome assertions.
The browser's real live case then exposed a production launch error when the recorder child started outside the
repository directory. The child now receives the trusted package root in `PYTHONPATH`; a real subprocess
regression and the fresh eight-test browser suite pass. Stream addresses still enter the child through stdin.
Automatic regeneration saves the original artifact and restores it after failure or an abandoned lease; bounded
repair never turns an uncertain upload into a new upload.
Final review reproduced and fixed two additional recovery defects: live projects were handed to the original manual
worker during app startup, and a failed restore could delete the saved backup. Explicit manual-render provenance
keeps manual work recoverable without reviving canceled automatic clips. A backup stays available if restoration
fails and cannot overwrite a newer completed render or an active manual rerender. Independent review repeated the
original reproductions successfully after the fixes.

No original user media, connections, settings, models, `.mcp.json` or GPU dependency declarations were changed.
The cloud has no NVIDIA GPU or Windows. Platform APIs, OAuth and metrics in these tests are local stand-ins;
transcripts are synthetic/imported and encoding/decoding/hash checks are real FFmpeg work. The evidence does not
claim real accounts, CUDA transcription, Windows keep-awake, human semantic quality or real-PC throughput.

### Final review (2026-10-02, PR #12)

A review of PR #11 (its code, Codex's two review comments and every test suite) found three defects and one dropped
feature. Each defect was reproduced with a failing test first.

| Finding | Fix | Test |
| --- | --- | --- |
| Codex P1: closing the app or pausing Autopilot while a live turn runs stopped the recorder, and the turn then either ended the broadcast (joined the recording, started the post-live analysis; ffmpeg exit 0) or used up an attempt as "interrupted" (exit 255 or 1) | `live.live_capture`: a recorder stopped for `restart` or `paused` raises `Wait`; the next turn records on after the saved minutes | `test_closing_or_pausing_during_a_turn_keeps_the_broadcast_open` (4 cases) |
| PR #11 made every canceled job final, so after **Stop all jobs** and **Resume jobs** a clip's check or package never ran again, and an approved post looped forever between "approved" and "publishing" without uploading; the same after canceling a waiting upload job, and *Publish now* did nothing | `queue.cancel_all` marks its jobs `wait_reason = 'stop_all'`, and `enqueue` revives those when asked again; a cancel by you stays final. `scheduler.process_due` and *Publish now* pass `revive_canceled` (the post decides; the publisher never uploads twice) | `test_work_held_by_stop_all_continues_after_resume_but_a_cancel_by_you_stays`, `test_an_approved_post_whose_upload_job_was_stopped_goes_out_at_its_new_time` (2 cases) |
| The complete-loop slow test checked the publish job right after the publication turned done; the job completes a moment later, so it failed by timing | the test waits for the publish job to complete | `test_worker_host_runs_complete_loop_and_repeats_after_restart` |
| PR #11 dropped the overview's note naming online searches that did not work (item 18) | restored under the overview's facts | read-only e2e `the overview has simple facts…` |

Kept as PR #11 built it (the owner's brief): Codex P2, a lack of videos is not a Needs you item (Home and the overview
say it and keep OPEN VIDEOS FOLDER); the GPU details moved from the overview to Autopilot → Advanced → System.

## Robot office (2026-10-07, master prompt)

The owner's master prompt (October 7, 2026) asked for the robot-office app: selected-audience uploads on both
platforms, a real organization of roles over the job system, a Brain with provenance and guarded learning, optional
NVIDIA AI, the office screens and robots, honest integration cards, and development history. How it works:
`docs/OFFICE.md`. Labels below: **Implemented and tested** (automated tests here, with fakes where a platform is
involved), **Implemented; live verification pending**, **Needs credentials/user action**, **Unsupported by the
current platform**, **Incomplete**.

| Requirement or dependency | Status | Evidence / what remains |
| --- | --- | --- |
| Selected audience on every upload path (no public, unlisted, Everyone; old public posts held; approvals bound to the audience stamp) | Implemented and tested | `tests/test_audience.py`, `test_autopilot_publish.py`, `test_youtube.py`, `test_tiktok.py`, sandbox complete loop |
| YouTube upload as Private without `publishAt` | Implemented and tested (fake YouTube); live verification pending | needs a real upload on the owner's account |
| YouTube viewer invitations | Unsupported by the current platform (no API) | handoff: the owner shares in YouTube Studio and presses *I shared it*; labeled as the owner's confirmation |
| TikTok Direct Post to followers or friends | Needs credentials/user action | needs TikTok's audit of the owner's developer app, unlikely for a personal tool that reposts other platforms' videos (TikTok's guidelines, rechecked 2026-10-08); until then "Only me" is staging and the clip becomes a ready-to-post package |
| TikTok ready-to-post package | Implemented and tested | the post's page: download, copy caption, steps, then *Link the post…* or *I posted it, no link* (`test_a_package_posted_without_a_link_is_recorded_as_your_word`); branded content Friends only; a full inbox holds TikTok posts for a day |
| Approvals bound to the connected account | Implemented and tested | `test_approvals_and_automatic_publishing_stay_with_the_account_they_were_given_for` |
| TikTok results for follower-only posts | Unsupported by the current platform | TikTok's video list covers public posts only; Clips → Test feedback instead |
| YouTube results for a private group | Implemented; live verification pending | the Data API counts are read; the Analytics API may report little for a small group |
| Office: cast registry (1 + 8 + 16, CORE separate), event feed with cursor, reports, decisions, health, controls | Implemented and tested | `tests/test_office.py`; `e2e/sandbox/robot-office.spec.ts` (placement, carry and review, decision reaction, old events ignored, paused, lost connection, Reduce animations, 1280×720 and 1366×768 fit, no sideways scroll at 683 and 390 px) |
| Office screens, Team, gallery, Integrations, Test feedback, Dev Log, new navigation | Implemented and tested | read-only `e2e` suite and sandbox flows; screenshots in `design/robot-office/screenshots` |
| Distinct robots (25, four directions, all poses) | Implemented; owner's visual review pending | `design/robots/contact-sheet.png`; compared with the reference sheets on 2026-10-08: crown badge for COMMAND and the managers, TRACKER, SPARK and PATCH colors fixed; simplified details listed in the review report |
| Brain: provenance, null ≠ 0, idempotent imports, corrections, cohorts, 30-clip / 10% guards, rollback, clip length used by the next videos | Implemented and tested (synthetic data) | `tests/test_brain.py` (21 tests; on 2026-10-08: uploads nobody could watch excluded, maturity from sharing, per-platform rollback, rollback not undone, 20 per side, identical results inconclusive); real learning needs 30 real clips from the owner's viewers |
| Brain: distinct people and one dominant video | Incomplete | plays are not people; one video can supply most clips once 5 videos exist; needs the owner's rule |
| Health readings, Test connection, rate-limit cards | Implemented and tested (fake platforms) | `tests/test_office_health.py`; a real check needs the owner's accounts |
| Trend and Source Score coverage and confidence; specific media-access reasons | Implemented and tested | `tests/test_scores_and_access.py` |
| Rework routed to the responsible stage; audio/video sync check; Queue states retrying, waiting for results, platform-verified audience; experiment framework | Incomplete | not in this version |
| Optional NVIDIA text AI | Implemented and tested (fake transport); Needs credentials/user action for live use | `tests/test_nvidia.py`; no real request was made, NVIDIA's current terms were not read live |
| GPU transcription and rendering on the RTX 3050 | Implemented; live verification pending | **GPU runtime not verified here** (no NVIDIA GPU in the cloud machine). On the PC: `gpu-check.bat`, or `.venv\Scripts\python.exe -m clipfoundry gpu-check` in the ClipFoundry folder |
| Twitch, Kick, Reddit, X, Instagram and podcast discovery connectors | Incomplete | not in this version (the capability matrix says so); a pasted public link still goes through the link importer where supported |
| Google Trends signal | Unsupported by the current platform | no supported public API; ClipFoundry does not scrape it |
| Preview-based screening before download, novelty and search signals, creator-relative baselines | Incomplete | Trend Score and Source Score (the Clip Opportunity Score) are documented in `docs/OFFICE.md#scores`; moments are judged from the transcript after the download |
| Development history (AI_CHANGELOG.md, AI_HANDOFF.md, `.clipfoundry/ai-change-log.jsonl`, Dev Log) | Implemented | entries start with this build; earlier work is in this file and the Git history |

End-to-end proof in the sandbox (`e2e/sandbox/zero-touch-loop.spec.ts`, fake YouTube and TikTok, a synthetic
transcript instead of Whisper, real ffmpeg rendering, no GPU): one Start discovers videos, makes clips that pass the
final check, uploads to the fake YouTube as Private (Needs you then asks to share it privately), reads results,
changes nothing with too few of them (2 of 30 posts with real numbers), waits for a stream link across a worker
restart and records it once the stream starts, with no duplicate upload, and the office shows the running,
waiting, restarted and paused states. The beginner flow passes with public video discovery on (the owner's decision
of 2026-10-08): public videos are clipped on the PC and pass the final check, are never planned or posted, a video
that cannot be downloaded is reported, the beginner chooses who watches, and an agreement makes a creator's video
plannable.

## Plan (highest priority first)

1. [x] Render artifact record: persist the edit-decision time map and the final transcript (output time), sha256 and
   an ffprobe of the output with every render. Additive; manual renders unchanged otherwise.
2. [x] Final quality gate (`pipeline/quality.py`): technical checks on the actual MP4 plus metadata re-validation,
   stored in a report bound to the artifact hash; a `quality_check` job between render and packaging; scheduler
   and publisher require a passing report for the current artifact; blockers shown in the Publish Center.
3. [x] Clip Blueprint: typed model with validation, persisted per clip, built by the analyzer, consumed by the
   renderer; unsupported instructions reported; the quality report binds the blueprint hash.
4. [x] Queue safety: `min_priority` inside the atomic claim; per-claim lease token; host keeps exclusivity while old
   threads run.
5. [x] Strict-GPU Autopilot setting (pause instead of CPU fallback).
6. [x] Remote media URL validation (private networks, redirects) and download size caps.
7. [x] Uncertain upload outcome → pause for review; "reconciling" state in the Publish Center.
8. [x] Take the GPU lock for NVENC encodes too (today only transcription and local LLM calls take it).
9. [x] Read Retry-After from YouTube/TikTok rate-limit answers and never shorten it; long waits are rescheduled.
10. [x] Dynamic replacement: a cooldown between replacements of the same slot (24 h default, persisted, one
    pending proposal per slot).
11. [x] Show platform publications next to unique clips on the dashboard.
12. [x] Scheduler tests across both daylight-saving changes in America/Chicago.
13. [x] Engagement Strategist: multi-interval plans that drop weak middle sentences when a cut is safe.
14. [x] Rights: channel rules and ownership only for channels the platform confirmed (your decision: restrict).
15. [x] Approvals bound to the SHA-256 of the rendered video (not its size and time stamp).
16. [x] Overnight run did nothing: your videos folder, a plain *Autopilot needs videos* item, keep the PC awake.
17. [x] UI redesign: Home, Autopilot, Library, Posts and Settings from the approved prototype (PR #7).
18. [x] Idle Autopilot fixes from `codex/fix-autopilot-idle`, brought into the redesigned app (PR #8).
19. [x] Website and legal pages from a code audit, with the fixes it found: AI keys sealed, request addresses out of
    the logs, YouTube clean-up at start and counted from YouTube's last answer (PR #9).
20. [ ] Publish the website on GitHub Pages (`gh-pages` branch with only the site files): waits for the owner's OK.
21. [x] Durable zero-touch Autopilot: direct link queue, lawful local retention, ordinary failure recovery,
    restart-safe live recording and verified repeated complete-loop sandbox.
22. [x] Retro robot studio across the working app: original artwork, real worker animation, motion preference,
    local-day Posts agenda, preserved editor controls and committed frontend bundle.
23. [x] Final review of PR #11: interrupted live recordings, work after Stop all jobs, a due post's canceled upload
    job, search problems on the overview (PR #12).
24. [x] Transcription on a fresh install (2026-10-02, found by the owner on the PC): faster-whisper 1.2.1 decodes a
    file path with PyAV and passes `metadata_errors`, which PyAV 19.0.0 removed, so every transcription failed with
    *open() got an unexpected keyword argument 'metadata_errors'*. The app now reads its own 16 kHz mono WAV
    (`audio.read_samples`) and hands Whisper the samples, the same values faster-whisper's decoder produced.
    Requirements are unchanged; an existing install can also run `pip install "av<19"`.
25. [x] Public internet video import (owner request 2026-10-03): default local discovery mode, public webpage
    extraction, bounded native downloads, safe live-page resolution, separate reuse/publishing gates, committed UI.
26. [x] Selected-audience uploads, office backend, Brain guards and optional NVIDIA AI (2026-10-07, `26f6b8f`).
27. [x] The robot office screens, Team and gallery, Integrations, Test feedback, Dev Log, new navigation, docs and
    handoff (2026-10-07/08, PR #14).
28. [ ] The owner's review of PR #14 and the checks on the PC below (GPU, real uploads, Who watches, the office look).
29. [x] The owner's public-video decision (keep it, 2026-10-08); `e2e/sandbox/beginner-flow.spec.ts` aligned.
30. [x] Review round of 2026-10-08 (`cf54204`): gaps against the master prompt, TikTok package flow, account-bound
    approvals, Brain guards, health and Test connection, score confidence, media-access reasons, robots.

## Test log

| Public internet import check (2026-10-03) | Result |
| --- | --- |
| Focused import checks | 12 passed, including real yt-dlp generic extraction and real recorded HLS imported through the guarded fake HTTP transport |
| Frontend `npm run build` | passes; committed bundle rebuilt |
| First fast suite after dependency setup | 489 passed, 7 slow deselected (205 s); final cookie-isolation regression added afterwards |
| Final `pytest -m "not slow"` | 490 passed, 7 slow deselected (218 s). An earlier run hit a concurrent test DB migration (`duplicate column rights_info`); the affected test and all 18 TikTok tests passed on rerun, then this full run passed. |
| `pytest -m slow` with real ffmpeg/eSpeak, synthetic transcripts and fake platforms | 6 passed, 1 clock-dependent complete-loop failure (762 s): its next post was outside the fixture's 12-hour upload lead. Production correctly waited. |
| Complete-loop rerun after fixing only the fake fixture's upload horizon | 1 passed (301 s). The fake YouTube fixture uses a 48-hour lead independent of wall-clock hour; production's 5–720 minute setting and scheduling behavior are unchanged. All seven media cases passed across these runs. No real GPU or accounts were used. |

| When | Command | Result |
| --- | --- | --- |
| Delivery media (2026-10-02) | `.venv/bin/python -m pytest -m slow -v` | 7 passed, 466 deselected (654.47 s), including repeated complete-loop upload/results and upcoming→restart→live→post-live. Collected before the final 2 manual-owner guard cases were added; both guards passed separately and in the final 468-test backend run. Clean log: `/workspace/scratch/retro-media-delivery-final.log`. |
| Delivery backend (2026-10-02) | `.venv/bin/python -m pytest -m "not slow" -q` | 468 passed, 7 deselected (209.74 s); includes the final startup/manual-ownership, restore failure, newer-file and active-manual-render guards. Clean log: `/workspace/scratch/backend-delivery-final.log`. |
| Independent recovery review | Targeted reproductions after startup and backup fixes | 7 passed (0.66 s); original live/manual-owner and ENOSPC backup-loss defects reproduced as resolved. The last queued/rendering manual-owner guard adds 2 passing cases (0.43 s), then the full 468-test backend run above. |
| Retro / durable Autopilot checkpoint (2026-10-02) | `.venv/bin/python -m pytest -m "not slow"` after intake deduplication | 453 passed, 7 deselected (214.53 s); later cooperative-priority/restart changes covered by the delivery runs above |
| Safe priority / upload restart checkpoint | `.venv/bin/python -m pytest -m "not slow"` | 459 passed, 7 deselected (215.31 s), including the exact-session fake YouTube upload restart; final review then added startup ownership and backup-restore error regressions |
| Full media checkpoint | `.venv/bin/python -m pytest -m slow -q` | 7 passed, 459 deselected (645.11 s); all original manual/Autopilot/live renders plus the two complete-loop cases. Follow-up startup and backup recovery validation above. |
| Retro / durable Autopilot media checkpoint | `pytest -m slow`, followed by the corrected growing-file test and `pytest tests/test_zero_touch_loop.py` | All 7 cases verified across runs: 4 unaffected cases, growing-file capture/post-live (191.01 s), 2 repeated-loop/live cases (344.14 s). Initial wrapper and fixture failures described above; not a claim that the initial broad run passed. |
| Retro build | `cd frontend && npm run build` | TypeScript and Vite passed; committed local font 8.41 KB, CSS 63.33 KB (12.64 KB gzip), JS 516.37 KB (153.53 KB gzip). No dependency changes. |
| Retro populated read-only browser | `CLIPFOUNDRY_URL=http://127.0.0.1:8814 npm test` in `e2e` | 60 passed, 1 fixture-dependent skip (53.9 s); isolated copied sandbox data, all API writes rejected by test fixture |
| Retro motion / activity contracts | `npx playwright test --config=playwright.sandbox.config.ts sandbox/motion.spec.ts sandbox/robot-office.spec.ts --project=chromium` | 6 passed (23.9 s); controlled status responses cover simultaneous jobs, reported percentage, completion, stale/stopped/attention states; motion checks cover keyboard, storage, OS preference and hidden tabs |
| Fresh complete-loop browser | `cd e2e && npm run test:sandbox` with system Chromium and local eSpeak wrapper | 8 passed (7.5 min), including the 6.5-min real-render repeated discovery/upload/results loop, upcoming stream, restart, segmented capture, post-live quality, local-only added link and saved Pause. Fake platform accounts and imported transcripts; actual artifact/byte/hash checks. |
| Retro accessibility and layout | axe-core WCAG 2 A/AA and 2.1 A/AA scans on 13 actual pages; 1366×768 and 683×384 CSS viewport inspection | Zero automated violations and no horizontal page overflow; 683×384 represents 200%-zoom layout, not physical Windows browser zoom or screen-reader validation |
| Cloud startup smoke | `/api/health`, `/api/projects`, served index on port 8765; `.venv/bin/python -m pip check`; `git diff --check` | Healthy CPU app, FFmpeg/FFprobe found, empty disposable development library, built interface served, installed dependencies consistent, no whitespace errors. Reusable cloud startup instructions saved. |
| baseline | `pytest -m "not slow"` | 207 passed (1 flaky failure seen once, see below) |
| baseline | `pytest tests/test_autopilot_core.py::test_gpu_lock_is_shared_with_other_processes` ×6 | 6 passed |
| baseline | `pytest -m slow` | 4 passed (404 s) |
| fix | old vs new version of that test with a 2.5 s cold `status()` injected | old fails at the same assertion as the baseline failure; new passes |
| artifact record | `pytest tests/test_artifact_quality.py` + scheduler, publish, editing, core, packaging suites | 3 new passed; 49 passed (the full fast suite ran at the next step) |
| final quality gate | `pytest -m "not slow"` | 217 passed (136 s) |
| final quality gate | `pytest -m slow` | 4 passed (414 s); the end-to-end Autopilot test now also runs the gate inside the worker host |
| final quality gate | `npm run build` in `frontend/` (tsc + vite) | passes; the committed `dist/` was first rebuilt from unchanged source and came out byte-identical |
| final quality gate | e2e suite (`e2e/`, 39 tests) against a scratch app seeded with one passing and one damaged Autopilot clip | 39 passed; screenshots of the Publish Center checked by eye |
| queue safety | the 3 new tests on the old `queue.py`/`host.py` | 3 failed (as expected) |
| queue safety | `pytest -m "not slow"` | 220 passed (121 s) |
| blueprint | `pytest -m "not slow"` | 240 passed (144 s) |
| blueprint | `pytest -m slow` | 4 passed (417 s); the end-to-end test now runs the whole slice through export |
| blueprint | manual inspection of one Autopilot render (synthetic espeak talk, `test_clip_hunter_and_analyzer_0`) | 1080x1920 H.264 + AAC 48 kHz stereo, 17.8 s, mean -20 dB / max -4.2 dB; frames every 4 s show the hook overlay then word-synced captions; final transcript = the planned sentences; payoff inside the range. Not listened to (no audio output here). |
| blueprint | after moving the filler count before the heard-words filter: blueprint, artifact/gate, editing (incl. its slow render test) and core suites | 54 passed |
| strict GPU | `pytest -m "not slow"` | 244 passed (131 s) |
| strict GPU | `pytest -m slow` (Whisper stand-ins now assert that Autopilot asks for strict GPU) | 4 passed (410 s) |
| network guard | `pytest -m "not slow"` | 262 passed (127 s) |
| network guard | `pytest -m slow` | 4 passed (409 s) |
| unconfirmed uploads | the previous uploader vs this one against the fake YouTube with the last chunk's answer lost and the session expired (8 s) | previous: 4 copies of the same video and still uploading (each first chunk reset its failure count, so it never gave up); now: 1 copy and "not uploaded again automatically" |
| unconfirmed uploads | `pytest -m "not slow"` | 265 passed (141 s) |
| unconfirmed uploads | `pytest -m slow` | 4 passed (413 s) |
| unconfirmed uploads | `npm run build`; e2e suite against the scratch app with a passing, a failed and an unconfirmed post | build passes; 39 passed; the unconfirmed post shows *Upload not confirmed* with *It is published* / *Upload again* (screenshot checked) |
| zero-config UX | `pytest tests/test_autopilot_simple.py` before the manual-source fix | `adding_content_by_hand_still_works` failed ('skipped' == 'queued'): a source added by hand was never scored |
| zero-config UX | `test_you_are_asked_only_about_strong_videos_and_only_when_needed` with the live-stream filter switched off | fails (the YouTube live stream would be asked about); passes with it |
| zero-config UX | `pytest -m "not slow"` | 274 passed (152 s) |
| zero-config UX | `pytest -m slow` | 4 passed (350 s) |
| zero-config UX | `npm run build`; `e2e` beginner flow (`npm run test:sandbox`: sandbox, test connections, synthetic transcript) | build passes; 1 passed (connect both, START, discovery, sources created, rights question, YES, file added, Clip Hunter takes it) |
| zero-config UX | read-only `e2e` suite against a sandbox after the beginner flow (main page with content, 2 posts awaiting approval) and against a fresh app (first-run screen) | 42 passed; 38 passed, 4 skipped (no projects) |
| zero-config UX | screenshots of the first-run screen, setup dialog, main page over time (the sandbox rendered, gated and scheduled one clip by itself), Add content dialog, Settings General/Advanced, System details | checked by eye; fixed a CSS clash with the project progress steps, a clip count shown as "No strong moments", "Currently" between two jobs of a video |
| hands-off | `pytest` (fast and slow together; ffmpeg and espeak-ng installed, nothing skipped) | 299 passed (554 s) |
| hands-off | `npm run build` in `frontend/` | passes |
| hands-off | `e2e` beginner flow (`npm run test:sandbox`, updated: uncovered videos skipped, one agreement with a shared folder, its video goes to the Clip Hunter) | 1 passed |
| hands-off | read-only `e2e` suite against a scratch app: first run, Autopilot on, Autopilot paused | 38 passed, 4 skipped (no projects) each time |
| NVENC lock | the new wait test on the previous `render.py` | fails: the encode never waits for the GPU (no "Waiting for the GPU" message) |
| Retry-After | the TikTok rate-limit test on the previous `publisher.py` | fails: waits 60 s instead of the asked 240 s |
| NVENC lock + Retry-After | `pytest -m "not slow"` | 272 passed (162 s) |
| NVENC lock + Retry-After | `pytest -m slow` | 4 passed (450 s) |
| confirmed channels | `rights.evaluate` for a YouTube video from another channel whose feed row claims an agreement channel, then your own channel, on PR #3's code (`a7c3ece`) vs this branch | PR #3: *Allowlisted* and *Owned*, both used automatically; now: *Not covered* (channel not confirmed) both times |
| confirmed channels + exact waits | `pytest tests/test_autopilot_channels.py` | 7 passed |
| confirmed channels + exact waits | `pytest -m "not slow"` on PR #3 + this branch combined | 312 passed (214 s) |
| confirmed channels + exact waits | `pytest -m slow` on the same combined code (ffmpeg, espeak-ng; includes the hands-off discovery-to-YouTube path) | 5 passed (461 s) |
| items 10-13 | the 14 new `test_autopilot_integrity.py` tests on PR #2's code (`248a664`) | 12 failed, 2 passed (the missed-post recovery across both DST changes already worked) |
| items 10-13 | `pytest -m "not slow"` on PR #2 + this branch (ffmpeg, espeak-ng; nothing skipped) | 347 passed (207 s) |
| items 10-13 | `pytest -m slow` on the same code | 5 passed (370 s) |
| items 10-13 | `npm run build` in `frontend/` | passes; `dist/` rebuilt and committed |
| items 10-13 | read-only `e2e` suite against a fresh scratch app (disposable data) | 38 passed, 4 skipped (no projects) |
| items 10-13 | `npm run test:sandbox` (beginner flow, test connections, synthetic transcript) | 1 passed |
| items 10-13 | read-only `e2e` suite against a sandbox after the beginner flow (it scheduled 1 clip for YouTube and TikTok) | 42 passed; Home shows *Scheduled: 1 clip · 2 platform posts* (screenshot checked) |
| items 10-13 | database made by the default branch's code (`f7426f0`: settings, a fake account, 4 clips, approved posts, one swap done, one pending), then opened by this code | integrity ok; every row kept; your settings kept, cooldown default 24 h added; both swaps backfilled; the old approval asks again (*approved before ClipFoundry checked the exact video file*); re-approval stores the file hash; second start changes nothing; `/api/autopilot/status` 200 |
| PR #4 | the old `.mcp.json` command vs `node e2e/playwright-mcp.mjs`, MCP handshake + `browser_navigate` to a local page (cloud container) | old: *Browser "chrome-for-testing" is not installed*; launcher: page title read, exits 0 when the client closes. Windows not run here |
| overnight run | simulated night on the default branch (`97b5c9a`): fake YouTube/TikTok/Commons, real worker threads, the settings a new user gets, both accounts connected, START | all 6 videos found were skipped (*Not covered: No agreement, license or ownership covers this video*), nothing usable from the library, *Needs you: Nothing right now* the whole time |
| overnight run | the same simulation on this branch, then a video dropped into the videos folder | before the drop: *Autopilot needs videos to work with*; the video was picked up at the next folder check (a file must be unchanged for 60 s, the folder is checked every 3 min), used as Owned, clipped, gated and planned for YouTube and TikTok; *2 posts waiting for your OK* showed at once (223 s in all) |
| overnight run | `pytest -m "not slow"` | 350 passed (246 s) |
| overnight run | `pytest -m slow` | 5 passed (493 s) |
| overnight run | `npm run build` in `frontend/` | passes; a second build reproduces the committed `dist/` |
| overnight run | `npm run test:sandbox` (beginner flow, now with the videos folder and the *needs videos* item) | 1 passed |
| overnight run | read-only `e2e` suite against a fresh scratch app, Autopilot off and then on | 38 passed, 4 skipped (no projects) each time |
| sleep-state review | review finding on `2836a44`: Windows refuses `SetThreadExecutionState` (fake kernel32 returning 0), Autopilot on | `2836a44`: not holding, but the page said *ClipFoundry stops the PC from going to sleep*, and nothing in Needs you; now: *Windows did not let ClipFoundry keep this PC awake* and a Needs you item with the power-settings steps |
| sleep-state review | the 5 new or changed keep-awake tests on `2836a44`'s code | 4 failed (no real state on the page, no refusal shown); the same-thread test passed there too |
| sleep-state review | `pytest -m "not slow"` | 354 passed (259 s) |
| sleep-state review | `pytest -m slow` | 5 passed (444 s) |
| sleep-state review | `npm run build` in `frontend/` | passes; `dist/` rebuilt and committed |
| sleep-state review | `npm run test:sandbox` (Chromium from `/opt/pw-browsers` via `CLIPFOUNDRY_E2E_CHROMIUM`) | 1 passed |
| sleep-state review | read-only `e2e` suite against a fresh scratch app, Autopilot off and then on | 38 passed, 4 skipped (no projects) each time |
| sleep-state review | a scratch app with a refusing fake kernel32, Autopilot page in Chromium | the red *Your PC may go to sleep and stop Autopilot* item with *What to do* steps, first in Needs you; the PC note says Windows refused (screenshot checked) |
| PC test without posting | the owner's test steps followed here: a "normal" install with both accounts connected (fakes), YouTube automatic publishing on and an approved TikTok post due now; a global `CLIPFOUNDRY_DATA` pointing at it; a separate test copy started with `CLIPFOUNDRY_DATA` and `CLIPFOUNDRY_VIDEOS` set to its own new folders | the test copy showed the first-time setup and no connected account; START, OPEN MY VIDEOS FOLDER and a dropped video gave 2 posts waiting for an OK (44 s); pressing Approve anyway: YouTube *not connected* (nothing sent), TikTok refused; the normal install's 20 files byte-identical afterwards |
| UI redesign | `pytest` (fast and slow together; ffmpeg and espeak-ng installed, nothing skipped) | 360 passed (591 s) |
| UI redesign | `npm run build` in `frontend/` (tsc + vite) | passes; `dist/` rebuilt and committed |
| UI redesign | `npm run test:sandbox` (beginner flow, now through Home → *Get started* → setup → *Start Autopilot*) | 1 passed |
| UI redesign | read-only `e2e` suite against a fresh sandbox | 51 passed, 9 skipped (no videos, no posts, Autopilot never started) |
| UI redesign | read-only `e2e` suite against a sandbox after the beginner flow and one added video (2 posts waiting for an OK) | 60 passed |
| UI redesign | every address (28, incl. each tab, a post, an unknown post and an unknown address) at 1440×900, 1366×768, 768×1024 and 390×844, filled-in sandbox; axe-core WCAG 2.1 AA | no sideways scrolling, one title per page, no "undefined"/"NaN", no console errors, 0 serious or critical findings |
| UI redesign | unsaved change in the editor, then a link Home → *Stay* → browser Back → *Discard and leave* → Forward | asked both times (Home was let through before the fix), Back after *Stay* was not a dead press, Discard went back one step |
| UI redesign | ClipFoundry stops answering (API refused for 8 s) on Home and Autopilot | *ClipFoundry is not answering* banner, Autopilot state *Unknown*, no green status left on screen |
| Codex checkpoint (on `97b5c9a`) | `pytest tests/test_autopilot_idle.py` | 16 passed; isolated databases and fake platforms |
| Codex checkpoint (on `97b5c9a`) | `pytest -m "not slow"` | 363 passed, 5 slow deselected (196 s) |
| Codex checkpoint (on `97b5c9a`) | `pytest -m slow` | 5 passed (247 s); real ffmpeg and eSpeak NG synthetic speech, imported transcripts and fake platforms; no NVIDIA GPU or real account validation |
| Codex checkpoint (on `97b5c9a`) | `npm run build` in `frontend/` | passes; committed bundle rebuilt |
| Codex checkpoint (on `97b5c9a`) | `npm run test:sandbox` | 1 passed (12 s); disposable data, fake platform connections, synthetic transcript |
| Codex checkpoint (on `97b5c9a`) | read-only `e2e` suite against a fresh disposable app | 38 passed, 4 skipped (no projects), 14 s |
| final integration (2026-10-01) | `pytest -m "not slow"` on the combined code (redesign + Codex fixes + the two fixes above) | 377 passed, 5 slow deselected (237 s) |
| final integration (2026-10-01) | `pytest -m slow` | 5 passed (402 s); real ffmpeg and eSpeak NG synthetic speech, fake platforms; no NVIDIA GPU or real account |
| final integration (2026-10-01) | `npm run build` in `frontend/` | passes; `dist/` rebuilt and committed; a second build reproduces it |
| final integration (2026-10-01) | `npm run test:sandbox` (beginner flow, Chromium from `/opt/pw-browsers`) | 1 passed |
| final integration (2026-10-01) | read-only `e2e` suite against a fresh sandbox | 51 passed, 9 skipped (no videos, no posts, Autopilot never started) |
| final integration (2026-10-01) | read-only `e2e` suite against a sandbox after the beginner flow and one video dropped into its videos folder (2 posts waiting for an OK) | 60 passed; the dropped copy of an already clipped video gave no new post (repeat stopped); screenshots of Home, Autopilot, Activity and a post's page checked by eye, which found the status line fixed above |
| website and legal pages (2026-10-01) | three reviewers checked every sentence of the product page, Privacy Policy and Terms against the code and YouTube's and TikTok's rules, each finding re-checked by a second reviewer; then a fresh check of the rewritten pages | 53 corrections, then 5 more; 4 code fixes (AI keys sealed, request addresses out of the logs, YouTube clean-up at start and counted from YouTube's last answer) |
| website and legal pages (2026-10-01) | `pytest -m "not slow"` on `b8951e1` | 382 passed, 5 slow deselected (227 s) |
| website and legal pages (2026-10-01) | `pytest -m slow` on `b90981a` (the later commits change only the YouTube clean-up and the pages) | 5 passed (392 s); real ffmpeg and eSpeak NG synthetic speech, fake platforms |
| website and legal pages (2026-10-01) | `npm run test:sandbox` on `4108a3f` (`CLIPFOUNDRY_E2E_CHROMIUM=/opt/pw-browsers/chromium`) | 1 passed |
| final review (2026-10-02) | `pytest -m "not slow"` on PR #11 as delivered (`639c674`) | 468 passed, 7 slow deselected |
| final review (2026-10-02) | the new tests for the three defects, run on `639c674`'s code first | each failed there (the broadcast ended or used an attempt; the post never uploaded after Stop all jobs) |
| final review (2026-10-02) | `pytest -m "not slow"` on `478bde3` | 475 passed, 7 slow deselected (233 s) |
| final review (2026-10-02) | `pytest -m slow` on `e81cd76` | 6 passed, 1 failed: the complete-loop test checked the publish job a moment too early (fixed in the test, `478bde3`) |
| final review (2026-10-02) | `pytest -m slow` on `478bde3` | 7 passed (674 s); real ffmpeg and eSpeak NG synthetic speech, fake platforms; no NVIDIA GPU or real account |
| final review (2026-10-02) | `npm run build` in `frontend/` | passes; `dist/` rebuilt and committed |
| final review (2026-10-02) | `npm run test:sandbox` on `478bde3` (`CLIPFOUNDRY_E2E_CHROMIUM=/opt/pw-browsers/chromium`) | 8 passed (6.8 min), incl. the beginner flow, reduced motion, the robot studio and the complete loop |
| final review (2026-10-02) | read-only `e2e` suite against a fresh sandbox | 52 passed, 9 skipped (no videos, no posts, Autopilot never started) |
| final review (2026-10-02) | read-only `e2e` suite against a sandbox after the beginner flow and one video dropped into its videos folder (4 posts waiting for an OK) | 61 passed |
| final review (2026-10-02) | a database made by `992431e` (settings, a source, a clip, a job) opened by `478bde3` | starts; settings, the clip and the job kept; the old source reads as not user-added; status, stats and Posts answer 200 |
| PyAV 19 fix (2026-10-02) | `test_whisper_gets_the_samples_so_a_newer_pyav_cannot_break_transcription` on `0aac33f`'s code (faster-whisper 1.2.1, PyAV 19.0.0 installed) | failed with the owner's error: *open() got an unexpected keyword argument 'metadata_errors'* |
| PyAV 19 fix (2026-10-02) | faster-whisper's own `decode_audio` with PyAV 13.1, 14.0, 15.1, 16.1, 17.0, 18.0, 18.1 and 19.0 | works up to 18.1; 19.0 refuses `metadata_errors` |
| PyAV 19 fix (2026-10-02) | `audio.read_samples` against faster-whisper's `decode_audio` (PyAV 18.0) on a WAV made by `extract_audio` from a synthetic video | identical float32 samples (320171, max difference 0) |
| PyAV 19 fix (2026-10-02) | `pytest -m "not slow"` on `d4f100c` | 478 passed, 7 slow deselected (242 s) |
| PyAV 19 fix (2026-10-02) | `pytest -m slow` on `d4f100c` | 7 passed (685 s); imported transcripts, so no real Whisper model (Hugging Face is blocked here) |
| robot office (2026-10-07) | `pytest -m "not slow"` on `26f6b8f` (backend wave) | 543 passed |
| robot office (2026-10-08) | `pytest -m "not slow"` on the screens-and-docs commit | 545 passed, 7 slow deselected (309 s) |
| robot office (2026-10-08) | `pytest -m slow` on the screens-and-docs commit | 5 passed, 2 failed (639 s): two video tests not updated by `26f6b8f` still expected `publishAt` on the YouTube upload; fixed to expect Private without it, then those 2 passed (334 s). Real ffmpeg and eSpeak NG, imported transcripts, fake platforms, no GPU |
| robot office (2026-10-08) | `npx tsc --noEmit` and `npm run build` in `frontend/` | pass; the build reproduces the committed `dist/` (index 614 kB) |
| robot office (2026-10-07) | read-only `e2e` suite against a sandbox after a complete loop (`CLIPFOUNDRY_E2E_CHROMIUM=/opt/pw-browsers/chromium`) | 62 passed, 2 failed, 1 skipped; both failures were test locators (a Team card name matched three cards; two settings the test did not know), fixed; the office, settings and shell files then 28 passed |
| robot office (2026-10-07) | `npm run test:sandbox` (Chromium at `/opt/pw-browsers/chromium`) | 7 passed, 2 failed: the complete loop still expected *2 of 10 posts* (now 30, fixed in the test) and the beginner flow (below) |
| robot office (2026-10-08) | `robot-office.spec.ts` and `zero-touch-loop.spec.ts` again after the fix | 5 passed (8.1 min) |
| robot office (2026-10-08) | `beginner-flow.spec.ts` on `eff96fb` itself, in a separate worktree | failed at *nothing uncovered is ever clipped*: the same failure exists before this work (public video discovery default on) |
| robot office (2026-10-08) | `beginner-flow.spec.ts` on this branch with `autopilot_public_videos` turned off by a temporary, uncommitted line | 1 passed (1.0 min) |
| review round (2026-10-08) | `beginner-flow.spec.ts` on this branch with public video discovery on (the default), after the test learned to confirm who watches in Settings → Integrations | 1 passed (4.0 min) |
| review round (2026-10-08) | new suites `test_brain.py` (21, 7 new), `test_office_health.py` (9), `test_scores_and_access.py` (29), the account-binding and START-twice tests | pass; the new ones failed before their fixes |
| review round (2026-10-08) | `pytest -m "not slow"` on `cf54204` | 597 passed, 7 slow deselected (329 s) |
| review round (2026-10-08) | `pytest -m slow` on `cf54204` | 7 passed (724 s); real ffmpeg and eSpeak NG, imported transcripts, fake platforms, no GPU |
| review round (2026-10-08) | `npx tsc --noEmit` and `npm run build` in `frontend/` | pass; committed `dist/` (index-C1kfHSbU.js) |
| review round (2026-10-08) | `npm run test:sandbox` on `cf54204` (Chromium at `/opt/pw-browsers/chromium`) | 9 passed (10.1 min): beginner flow, motion 3, robot office 4, complete loop |

## Checklist for the user's machine

Everything below needs your PC, your GPU or your accounts; none of it could be done in the cloud session.

| # | Action | Command / where | Expected evidence | Why |
| --- | --- | --- | --- | --- |
| 1 | Update and start (keep `data`, `.venv`, `tools`; see INSTALL.md → Updating) | `git pull` or the ZIP steps, then `start.bat` | App opens at http://127.0.0.1:8765; your videos (Library), settings and account connections are still there; Autopilot → Advanced → System lists 12 workers incl. *Final Quality Gate* | new tables (`slot_replacements` and earlier ones) are created on first start; posts approved before this version ask for approval once more |
| 2 | Real CUDA transcription | `gpu-check.bat` (or `python -m clipfoundry gpu-check some_video.mp4`) | "device: cuda", compute type float16 or int8_float16, speed several times realtime | this environment has no GPU; detection alone is not transcription |
| 3 | Strict GPU in Autopilot | temporarily break CUDA (e.g. rename the cuBLAS DLL folder), add an owned source | the hunt pauses; action item "Autopilot transcription is paused"; no CPU run; restore and the source continues | proves the pause on real hardware |
| 4 | Local vertical slice | Missions → Permissions & sources: watch folder of your own recordings marked Owned; turn Autopilot on | clips appear in Clips; Queue → Needs review shows the posts, and each post's page shows *Final check* with every check listed | the slice ran here only on synthetic espeak video |
| 5 | Look at and listen to one Autopilot clip | open it from a post's page in Queue | captions in sync, the hook line on screen, the payoff inside the clip, no cut mid-word, sound clear | automated checks cannot judge meaning; listening was not possible here |
| 6 | Measure throughput | time one 60-minute source through hunt → analyze (worker log `data/logs/workers.log`), watch VRAM in Task Manager | minutes per source, peak VRAM, disk used per source | whether 15 clips/day is plausible must be measured, not assumed |
| 7 | Browser tests | `e2e\run-tests.bat` with the app running; `e2e\run-beginner-test.bat` (sandbox, app need not run) | 60 passed (some skipped without videos or posts); beginner flow passed | read-only check of every page against your real data; the beginner flow on Windows |
| 8 | YouTube, real account | connect in first-time setup (step 3) or Settings → Accounts; Settings → Integrations → Who watches → *My invited viewers* → Confirm who watches; approve one post | the post's page in Queue shows it uploaded, *Awaiting viewer invitations*; YouTube Studio shows it Private with no scheduled publishing; after sharing it there and pressing *I shared it*, the post says *Audience set up (you confirmed)* | only fake platforms were used here |
| 9 | TikTok, real account | connect; approve one post with *Send to TikTok inbox* | the draft appears in the TikTok app | Direct Post eligibility of a single-user tool is TikTok's decision (`PLATFORM_CAPABILITIES.md`) |
| 10 | Re-read the platform pages | the URLs in `docs/PLATFORM_CAPABILITIES.md` | constraints still match; update "Last verified" | the documentation hosts were blocked from this session |
| 11 | Channel confirmation, real account | with YouTube connected, add a rule for a channel and let Autopilot find one of its videos | Activity shows the video used; a video from another channel is skipped with *channel not confirmed* | the YouTube and TikTok answers were faked here |
| 12 | Look at and listen to a clip with a cut | find a clip whose `blueprint.json` (next to the rendered file under `data\projects`) has a *cut out … in the middle* line under `reasons`, and play it | the jump is at a pause, nothing said is lost, captions skip the removed line | cuts were checked here only on synthetic video with a synthetic transcript |
| 13 | Approval follows the exact file | approve a post, re-render its clip | the post asks for approval again (YouTube with automatic publishing: approved again only after the final check) | checked here with fake platforms only |
| 14 | Overnight run | *Start Autopilot*, press *Open videos folder*, put one of your own videos in it, leave the PC plugged in overnight | next morning: clips in the Library, posts planned between 9 AM and 9 PM in Posts; the Autopilot overview's *This PC* says *Kept awake*, and Autopilot → Advanced → System events show *Keeping this PC awake*; `powercfg /requests` (admin prompt) lists python under SYSTEM while Autopilot is on | sleep prevention and File Explorer opening were not run on Windows here. If the page says *Windows did not let ClipFoundry keep this PC awake*, follow its Needs you steps. To try it before merging with no chance of posting, run a separate test copy with its own new data folder (`CLIPFOUNDRY_DATA`) and videos folder (`CLIPFOUNDRY_VIDEOS`), with the normal ClipFoundry closed |
| 15 | Look at the new screens on Windows | open the Office, Team, Missions, Clips, a clip in the editor, Queue and Settings → Integrations; make the window narrow | text fits, nothing scrolls sideways, the Menu button appears on a narrow window, your old bookmarks (`#/projects`, `#/publish-center`, `#/autopilot`) open the new pages | the screens were checked here in Chromium on Linux only (other fonts, no Windows display scaling) |
| 16 | The office follows real work | with Autopilot running on one of your videos, watch the Office for a few minutes; tick Reduce animations | robots go to their desks while their step runs and back to the Lounge after; a manager reviews after a report; with Reduce animations nothing moves; compare the robots with your reference sheets | movement was checked here only in the sandbox |
| 17 | Optional NVIDIA AI | README → *Optional NVIDIA AI*; Check the setup, then Run a small AI test | *Check* lists the model; the test answers; Today's usage counts one request | no real NVIDIA request was made here |
