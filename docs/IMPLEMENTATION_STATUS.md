# Implementation status

Resume file for the "Audit, Finish, and Verify" task. Keep it current: another session must be able to continue
from here without repeating the audit.

## Checkpoint

| | |
| --- | --- |
| Audit date | 2026-09-28 |
| Starting commit | `3be586d` (branch `claude/ecstatic-shannon-wb1zq1`, identical to `claude/wonderful-ritchie-909tq3`) |
| Work branch | `claude/ecstatic-shannon-wb1zq1` |
| Environment of this session | Linux cloud container, Python 3.11, ffmpeg 6.1.1 (apt), espeak-ng, **no NVIDIA GPU**, Hugging Face blocked (no Whisper model download), `developers.google.com` / `developers.tiktok.com` blocked by the network policy |
| Next concrete task | Plan item 8 (GPU lock for NVENC encodes); the user's checklist at the end needs your PC and accounts |

Verification levels used below: **source reviewed** (read the code path and its callers), **unit/contract tested**
(pytest with fakes or fixtures), **local pipeline verified** (real ffmpeg render through the actual pipeline here),
**RTX 3050 verified**, **real account verified**. Imported/synthetic transcripts and fake platform adapters are
always labeled as such.

## Baseline (before any change in this task)

| Command | Result |
| --- | --- |
| `python -m pytest -m "not slow"` | 207 passed. One earlier run failed `test_gpu_lock_is_shared_with_other_processes` (cold start); reproduced as a test race and fixed (see below). |
| `python -m pytest -m slow` | 4 passed in 404 s (synthetic espeak video, imported transcripts, real ffmpeg renders) |

## Requirement matrix

Status values: verified, implemented-but-unverified, partial, missing, externally-blocked, not-supported.

### Pipeline and clip quality

| Requirement | Existing file / symbol | Status | Evidence / test | Remaining work | External blocker |
| --- | --- | --- | --- | --- | --- |
| Manual workflow upload → transcribe → discover → edit → render → preview → export/publish | `api.py`, `jobs.py`, `pipeline/process.run_project`, `pipeline/export.py` | verified (local pipeline, synthetic espeak video) | `test_integration::full_api_flow` (slow), `test_editing`, `test_postpack` | keep green | — |
| CUDA faster-whisper transcription, model cache, word timestamps | `pipeline/transcribe.py`, `pipeline/cuda.py`, `pipeline/models.py` | implemented-but-unverified on hardware (unit tested with fakes) | `test_gpu` (24), `test_models` (10) | run `gpu-check.bat` on the RTX 3050 | no GPU here |
| Visible CPU fallback in manual mode | `transcribe.transcribe` attempt list, `gpu.GpuManager.record_transcription` | verified (unit) | `test_gpu::cuda_failure_falls_back_to_cpu_loudly`, `test_autopilot_core::cpu_fallback_is_never_silent` | — | — |
| Strict-GPU Autopilot: CUDA failure pauses the job; CPU fallback only by explicit setting | `transcribe.transcribe(allow_cpu_fallback=...)`, `GpuTranscriptionFailed`, setting `autopilot_allow_cpu_fallback` (default off), `hunter.gpu_failed` (Wait 30 min + action item), live capture keeps recording and post-live re-transcribes | verified (unit, fake CUDA failures) | `test_gpu::test_strict_gpu_*` (3), `test_autopilot_analysis::test_strict_gpu_pauses_the_hunt_instead_of_using_the_cpu` | confirm on the RTX 3050 | no GPU here |
| Eleven-factor Viral Potential | `pipeline/virality.py` | verified (unit) | `test_virality` (17) | — | — |
| Broad candidate pool, staged ranking, boundary optimization, diversity/dedupe | `pipeline/candidates.py`, `deep.py`, `diversity.py`, `fingerprint.py`, `autopilot/hunter.py` | verified (unit + slow end-to-end) | `test_autopilot_analysis` (11) | — | — |
| Typed, versioned, validated **Clip Blueprint** persisted before rendering and consumed by the renderer | `pipeline/blueprint.py` (`Blueprint`, `build`, `validate`, `with_edit`, `for_render`), `autopilot/hunter.plan_clips` (analyzer and post-live), `live.make_live_clip`, `render.render_clip(blueprint=...)`, table `clip_blueprints` | verified (unit + local pipeline) | `tests/test_blueprint.py` (20, incl. a real two-interval render), `test_clip_hunter_and_analyzer_end_to_end` (slow) | the Strategist plans one interval per clip today (multi-interval plans render correctly but are not generated yet); no reordering (rejected, the renderer plays forwards) | — |
| Edit-decision time map (source → output) persisted; final transcript in output time | `pipeline/artifact.py` (`edit_decisions`, `final_words`, `record`), written by `render.render_clip` as `edl.json` + `transcript.final.json` | verified (local pipeline, synthetic video) | `test_artifact_quality::test_render_writes_the_artifact_record`, `test_final_transcript_keeps_only_what_is_heard` | multi-interval blueprint cuts (see blueprint row) | — |
| Artifact metadata: path, hash, duration, codecs, dimensions, effective settings, captions, final transcript, blueprint version | `render_info["artifact"]` from `artifact.record` (with the followed blueprint's hash, intervals and unsupported list) | verified (local pipeline) | `test_render_writes_the_artifact_record`, `test_the_render_follows_a_plan_that_cuts_out_a_sentence` | — | — |
| Atomic artifact finalize | `render.render_clip` (`render.tmp.mp4` → `os.replace`) | verified (source reviewed) | — | — | — |
| Packaging after render from the edited transcript; several options; ≤3 AI retries; grounded fallback or block | `autopilot/packaging.py` (`clip_sentences` reads the final transcript of the active render; rows carry `artifact_sha256`), `pipeline/postpack.py` | verified (unit + local pipeline) | `test_autopilot_packaging` (6), `test_the_gate_decides_what_is_scheduled_and_uploaded` | a fallback with problems is still stored as selected, but the gate now marks that platform's text failed and it is not scheduled | — |
| Independent final quality gate (decodable, streams, duration/dimensions, caption bounds, black/frozen frames, silence) bound to the artifact hash; only passing artifacts schedule/publish | `pipeline/quality.py` (media checks), `autopilot/gate.py` (`quality_check` job, `quality_reports` table, `schedulable`, `verify_file`), wired into `scheduler.candidates`, `scheduler.approve`, `publisher.publish`; Publish Center badge and check list | verified (local pipeline, synthetic media: clean, truncated, wrong size, black, frozen+silent, frozen+speech, muted speech, late captions, mid-word cuts) | `tests/test_artifact_quality.py` (10), `test_autopilot_publish::test_only_files_that_passed_the_final_quality_gate_are_uploaded`, e2e `publish-center.spec.ts` | semantic checks are estimates from the selection-time analysis; no LLM review | — |
| Material edits invalidate packaging, quality report and consent | reports keyed by file (stamp + SHA-256); packaging rows keyed by artifact SHA-256 (stale → repackaged); `scheduler.approval_hash` for consent | verified (unit + local pipeline) | `test_the_gate_decides_what_is_scheduled_and_uploaded`, `approval_rules_and_invalidation` | — | — |

### Orchestration and resources

| Requirement | Existing file / symbol | Status | Evidence / test | Remaining work | External blocker |
| --- | --- | --- | --- | --- | --- |
| Durable jobs with states, attempts, capped backoff with jitter | `autopilot/queue.py` | verified (unit) | `test_autopilot_core` (22) | — | — |
| Retry-After handling | `queue.Retry(delay=...)`; publisher uses a fixed 60 s for rate limits | partial | source reviewed | read Retry-After from platform responses | — |
| Waiting (consent, quota, GPU) does not consume attempts | `queue.claim` (`bump = 0` after `waiting`) | verified (unit) | `waiting_jobs_resume_without_using_an_attempt` | — | — |
| Atomic claim | `queue.claim` (`BEGIN IMMEDIATE`) | verified (unit) | `idempotent_enqueue_and_priority` | — | — |
| Autopilot-off priority restriction **inside** the atomic claim | `queue.claim(min_priority=...)` (in the `BEGIN IMMEDIATE` transaction), `host.WorkerHost._claim` | verified (unit) | `test_the_priority_floor_is_part_of_the_claim`, `autopilot_off_only_runs_manual_jobs_and_stop_all_blocks_everything` | — | — |
| Stale workers cannot finalize reclaimed jobs | `queue._finish`/`renew` check the lease owner; `host.WorkerHost._token` gives every claim its own token | verified (unit) | `test_a_recovered_job_cannot_be_finished_by_its_old_thread`, `recovery_after_a_crash` | — | — |
| Crash between stage output and downstream handoff | handlers enqueue (idempotency keys) before `complete` | partial | source reviewed | replay re-runs the whole stage; `analyze_source` replay deletes and recreates the project's clips | — |
| Shutdown does not release exclusivity while old workers can still act | `WorkerHost.stop` keeps the host lock until every worker thread has exited | verified (unit) | `test_a_stopping_host_keeps_exclusivity_until_its_threads_are_done` | — | — |
| STOP ALL JOBS persistent across restart, stops dispatch, signals running work | `state.paused`, `routes.stop_all`, host heartbeat | verified (unit) | `cancel_and_stop_all`, `autopilot_off_only_runs_manual_jobs_and_stop_all_blocks_everything`, `test_an_upload_stopped_halfway_is_reconciled_with_the_platform` (an upload whose job was canceled is checked with the platform, never re-uploaded blindly) | — | — |
| One heavy GPU operation at a time across processes; recovery | `gpu.GpuManager.heavy`, `locks.FileLock` | verified (unit) | `gpu_lock_serializes_heavy_work`, `gpu_lock_is_shared_with_other_processes` (race in the test fixed) | — | — |
| GPU lock also covers GPU-using render steps (NVENC) | `render.render_clip` does not take the lock | partial | source reviewed | decide: take the lock for NVENC encodes | — |
| VRAM detection and resource status | `gpu.GpuManager.memory` (nvidia-smi), `status` | implemented-but-unverified | `gpu_waits_for_free_memory_then_gives_up` (fake) | verify on the RTX 3050 | no GPU here |
| Bounded downloads / source size / duration | `netguard.download(max_bytes=...)`, `hunter.max_source_bytes`, `hunter.check_length`, yt-dlp `max_filesize` + duration filter (`jobs.download_url(max_bytes, max_seconds)`), free-disk reserve before a download; settings `autopilot_max_source_gb` (8) and `autopilot_max_source_minutes` (240) | verified (unit, local HTTP server) | `test_netguard.py` | CPU threads for Whisper are capped at 8 (existing); no global disk quota for renders | — |

### Discovery, rights and sources

| Requirement | Existing file / symbol | Status | Evidence / test | Remaining work | External blocker |
| --- | --- | --- | --- | --- | --- |
| Pluggable providers (YouTube Data API, watch folders, streams, signal feeds); unavailable ones shown as unavailable | `autopilot/providers.py`, `scout.py` | unit tested (fake API) | `test_autopilot_discovery` (14) | real API call on the user's key | API key; network |
| Metric provenance (observed / estimated / unavailable), missing = null, velocity needs time-separated observations | `autopilot/trends.py` | verified (unit) | `missing_metrics_are_never_filled_in`, `momentum_beats_size` | — | — |
| Rights statuses, basis, evidence URL, expiry; recheck at ingest, schedule, publish | `autopilot/rights.py` (`gate` re-evaluates rules each time) | partial | `rights_evaluation_order_and_policy`, `repeats_and_blocked_sources_are_never_scheduled`, `gates_before_every_upload` | allowed platforms, attribution requirements and audio/music restrictions are not modeled per rule. **Found in this audit:** a channel rule without a platform matches any source claiming that channel id, and a signal feed's rows can claim any channel id (and platform), so a feed you added could inherit an Allowlisted channel's status. Proposed: channel rules match only sources whose channel id comes from a verified provider (YouTube API), or require the rule's platform. Not changed yet: it changes rights semantics | — |
| Discovery-only kept separate from media eligibility; no platform downloads by default | `rights.download_allowed`, `rights_allow_remote_download` | verified (unit) | `folder_rules_and_download_policy` | — | — |
| Remote media URLs and redirects checked against private/internal networks | `netguard.py` (`check`, `open_checked`, `download`, `get_text`, `ffmpeg_input`), used by `hunter._http_download`, `providers.signal_feed`, `live.input_args`; trust from `rights.url_typed_by_user` | verified (unit, local HTTP server, fake DNS) | `test_netguard.py` (18) | ffmpeg resolves stream hosts itself, so live stream URLs are checked but not pinned | — |

### Scheduling and publishing

| Requirement | Existing file / symbol | Status | Evidence / test | Remaining work | External blocker |
| --- | --- | --- | --- | --- | --- |
| UTC instants, America/Chicago display, active hours, gaps, per-platform limits | `autopilot/scheduler.py` | verified (unit) | `test_autopilot_scheduler` (11) | DST transition test | — |
| Missed slots re-planned without a burst | `scheduler.process_due` (`OVERDUE_MINUTES`) | verified (unit) | `due_processing` | — | — |
| Cold-start timing labeled; learned timing needs reliable groups | `scheduler.Timing`, `learner` | verified (unit) | `learned_timing_picks_your_best_hour` | — | — |
| Dynamic replacement: threshold, freeze window, audit; never after approval without re-approval | `scheduler.try_replace`, `approve` | partial | `dynamic_replacement_with_audit_trail`, `approved_posts_are_only_swapped_after_approving_the_replacement` | no cooldown between replacements | — |
| Approval bound to exact content and visibility | `scheduler.approval_hash`, `approval_valid` | verified (unit) | `approval_rules_and_invalidation` | bind to the artifact content hash (today: size+mtime) | — |
| Upload recovery without duplicates; uncertain outcome paused for review | `youtube.upload(on_final_chunk, may_be_complete)` raises `OUTCOME_UNKNOWN` instead of starting a second session once the last bytes may have arrived; `publisher.outcome_unknown` looks for the video among the channel's newest uploads (never an older one with the same title), else status `reconciling` + action item; `POST /api/autopilot/scheduled/{id}/resolve`; Publish Center buttons | verified (unit, fake platform) | `test_autopilot_publish::test_a_lost_answer_after_the_last_bytes_is_found_not_uploaded_twice`, `test_an_upload_that_cannot_be_confirmed_waits_for_you`, `interrupted_upload_resumes_without_a_duplicate` | TikTok: a publish ID is stored right after init, so its outcome is always read back; confirmed with real accounts pending | real accounts |
| Unique clips and platform publications counted separately | `routes.status` counts unique clips | partial | source reviewed | show publications count too | — |
| YouTube: OAuth PKCE, resumable upload, made-for-kids, publishAt, locked-private honesty | `publish/youtube.py`, `publish/jobs.py` | unit/contract tested (fake platform) | `test_youtube` (13), `test_autopilot_publish` (8) | real-account check | credentials; audit |
| TikTok: creator info, no default privacy, interactions, disclosure, music confirmation, inbox fallback | `publish/tiktok.py`, `components/approve.tsx` | unit/contract tested (fake platform) | `test_tiktok` (12) | Direct Post eligibility of a private single-user tool | externally-blocked (see `PLATFORM_CAPABILITIES.md`) |
| YouTube quota buckets (search.list, videos.insert, other units), reset Pacific, reserves, cache | `autopilot/quota.py` | verified (unit) | `quota_budgets_share_reserve_and_exhaustion` | budgets are settings, not a versioned config | project quota is not readable by API |

### Live, learning, security, data, UI

| Requirement | Existing file / symbol | Status | Evidence / test | Remaining work | External blocker |
| --- | --- | --- | --- | --- | --- |
| Live capture in segments, checkpoints, post-live analysis, supersede only unpublished | `autopilot/live.py` | verified (local, synthetic stream file) | `test_autopilot_live` (3, one slow) | — | real stream |
| Learning from real metrics only, minimum samples, shrinkage, frozen features at publish time | `autopilot/learner.py`, `publish/jobs.feature_snapshot`, `publish/stats.py` | verified (unit) | `test_autopilot_learning`, `test_performance` | — | real accounts |
| Local-only server, app header, DNS-rebinding guard | `api.py` (`local_only`, `app_request`) | verified (unit + e2e) | `test_youtube::publishing_only_from_this_computer_and_this_page`, `e2e/tests/api-guards.spec.ts` | — | — |
| Secrets: DPAPI on Windows, explicit unencrypted storage elsewhere | `secure.py` | verified (unit, non-Windows path) | `test_youtube::secret_sealing_round_trip` | DPAPI path verified only on Windows | — |
| YouTube 30-day data rule | `scout.youtube_retention` | verified (unit) | `youtube_data_is_deleted_after_30_days` | — | — |
| Terms / Privacy templates with placeholders | `docs/legal/` | implemented; not publicly deployed | `legal_pages_are_served` | owner fills placeholders; lawyer review; public hosting | owner decision |
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
8. [ ] Take the GPU lock for NVENC encodes too (today only transcription and local LLM calls take it).
9. [ ] Read Retry-After from YouTube/TikTok rate-limit answers (today a fixed 60 s).
10. [ ] Dynamic replacement: a cooldown between replacements of the same slot.
11. [ ] Show platform publications next to unique clips on the dashboard (today: unique clips only).
12. [ ] Scheduler test across a daylight-saving change in America/Chicago.
13. [ ] Engagement Strategist: propose multi-interval plans (drop a weak middle sentence); the renderer already follows them.
14. [ ] Rights: your decision on channel rules (see the Rights row).

## Test log

| When | Command | Result |
| --- | --- | --- |
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

## Checklist for the user's machine

Everything below needs your PC, your GPU or your accounts; none of it could be done in the cloud session.

| # | Action | Command / where | Expected evidence | Why |
| --- | --- | --- | --- | --- |
| 1 | Update and start | `git pull`, then `start.bat` | App opens at http://127.0.0.1:8765; Autopilot page lists 12 workers incl. *Final Quality Gate* | new tables (`quality_reports`, `clip_blueprints`) are created on first start |
| 2 | Real CUDA transcription | `gpu-check.bat` (or `python -m clipfoundry gpu-check some_video.mp4`) | "device: cuda", compute type float16 or int8_float16, speed several times realtime | this environment has no GPU; detection alone is not transcription |
| 3 | Strict GPU in Autopilot | temporarily break CUDA (e.g. rename the cuBLAS DLL folder), add an owned source | the hunt pauses; action item "Autopilot transcription is paused"; no CPU run; restore and the source continues | proves the pause on real hardware |
| 4 | Local vertical slice | Autopilot → Sources & rights: watch folder of your own recordings marked Owned; turn Autopilot on | clips appear in the project; Publish Center shows posts with "Final check passed" and every check listed | the slice ran here only on synthetic espeak video |
| 5 | Look at and listen to one Autopilot clip | open it from the Publish Center preview | captions in sync, the hook line on screen, the payoff inside the clip, no cut mid-word, sound clear | automated checks cannot judge meaning; listening was not possible here |
| 6 | Measure throughput | time one 60-minute source through hunt → analyze (worker log `data/logs/workers.log`), watch VRAM in Task Manager | minutes per source, peak VRAM, disk used per source | whether 15 clips/day is plausible must be measured, not assumed |
| 7 | Browser tests | `e2e\run-tests.bat` with the app running; `e2e\run-beginner-test.bat` (sandbox, app need not run) | 42 passed (some skipped without projects); beginner flow passed | read-only check of every page against your real data; the beginner flow on Windows |
| 8 | YouTube, real account | connect in Autopilot (step 1) or Settings → General → Accounts, approve one post as Private | video ID in the Publish Center; YouTube Studio shows it Private/scheduled | only fake platforms were used here |
| 9 | TikTok, real account | connect; approve one post with *Send to TikTok inbox* | the draft appears in the TikTok app | Direct Post eligibility of a single-user tool is TikTok's decision (`PLATFORM_CAPABILITIES.md`) |
| 10 | Re-read the platform pages | the URLs in `docs/PLATFORM_CAPABILITIES.md` | constraints still match; update "Last verified" | the documentation hosts were blocked from this session |
| 11 | Decide on channel rules | see the Rights row above | keep, or restrict channel rules to verified providers | changes rights semantics: your decision |
