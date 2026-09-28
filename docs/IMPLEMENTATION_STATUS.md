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
| Next concrete task | see "Plan" below; the first unchecked item |

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
| Strict-GPU Autopilot: CUDA failure pauses the job; CPU fallback only by explicit setting | none: Autopilot uses the manual fallback | missing | — | setting + pause with action item | — |
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
| STOP ALL JOBS persistent across restart, stops dispatch, signals running work | `state.paused`, `routes.stop_all`, host heartbeat | verified (unit) | `cancel_and_stop_all`, `autopilot_off_only_runs_manual_jobs_and_stop_all_blocks_everything` | submitted uploads should show "reconciling", not "cancelled" | — |
| One heavy GPU operation at a time across processes; recovery | `gpu.GpuManager.heavy`, `locks.FileLock` | verified (unit) | `gpu_lock_serializes_heavy_work`, `gpu_lock_is_shared_with_other_processes` (race in the test fixed) | — | — |
| GPU lock also covers GPU-using render steps (NVENC) | `render.render_clip` does not take the lock | partial | source reviewed | decide: take the lock for NVENC encodes | — |
| VRAM detection and resource status | `gpu.GpuManager.memory` (nvidia-smi), `status` | implemented-but-unverified | `gpu_waits_for_free_memory_then_gives_up` (fake) | verify on the RTX 3050 | no GPU here |
| Bounded downloads / source size / duration | `hunter._http_download` (no size cap), `jobs.download_url` (yt-dlp, no max size) | missing | source reviewed | size and duration caps | — |

### Discovery, rights and sources

| Requirement | Existing file / symbol | Status | Evidence / test | Remaining work | External blocker |
| --- | --- | --- | --- | --- | --- |
| Pluggable providers (YouTube Data API, watch folders, streams, signal feeds); unavailable ones shown as unavailable | `autopilot/providers.py`, `scout.py` | unit tested (fake API) | `test_autopilot_discovery` (14) | real API call on the user's key | API key; network |
| Metric provenance (observed / estimated / unavailable), missing = null, velocity needs time-separated observations | `autopilot/trends.py` | verified (unit) | `missing_metrics_are_never_filled_in`, `momentum_beats_size` | — | — |
| Rights statuses, basis, evidence URL, expiry; recheck at ingest, schedule, publish | `autopilot/rights.py` (`gate` re-evaluates rules each time) | partial | `rights_evaluation_order_and_policy`, `repeats_and_blocked_sources_are_never_scheduled`, `gates_before_every_upload` | allowed platforms, attribution requirements and audio/music restrictions are not modeled per rule | — |
| Discovery-only kept separate from media eligibility; no platform downloads by default | `rights.download_allowed`, `rights_allow_remote_download` | verified (unit) | `folder_rules_and_download_policy` | — | — |
| Remote media URLs and redirects checked against private/internal networks | none | missing | source reviewed | resolve and reject private/loopback/link-local targets on every redirect | — |

### Scheduling and publishing

| Requirement | Existing file / symbol | Status | Evidence / test | Remaining work | External blocker |
| --- | --- | --- | --- | --- | --- |
| UTC instants, America/Chicago display, active hours, gaps, per-platform limits | `autopilot/scheduler.py` | verified (unit) | `test_autopilot_scheduler` (11) | DST transition test | — |
| Missed slots re-planned without a burst | `scheduler.process_due` (`OVERDUE_MINUTES`) | verified (unit) | `due_processing` | — | — |
| Cold-start timing labeled; learned timing needs reliable groups | `scheduler.Timing`, `learner` | verified (unit) | `learned_timing_picks_your_best_hour` | — | — |
| Dynamic replacement: threshold, freeze window, audit; never after approval without re-approval | `scheduler.try_replace`, `approve` | partial | `dynamic_replacement_with_audit_trail`, `approved_posts_are_only_swapped_after_approving_the_replacement` | no cooldown between replacements | — |
| Approval bound to exact content and visibility | `scheduler.approval_hash`, `approval_valid` | verified (unit) | `approval_rules_and_invalidation` | bind to the artifact content hash (today: size+mtime) | — |
| Upload recovery without duplicates; uncertain outcome paused for review | `publisher.recover`, `publish/jobs.py` | partial | `interrupted_upload_resumes_without_a_duplicate` (fake platform) | an upload whose outcome cannot be determined resumes instead of pausing for review | — |
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
| UI controls call real backend, correct after refresh | `frontend/src/pages/*` | read-only e2e suite | `e2e/` (38 tests, validated against a scratch app) | — | — |

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
5. [ ] Strict-GPU Autopilot setting (pause instead of CPU fallback).
6. [ ] Remote media URL validation (private networks, redirects) and download size caps.
7. [ ] Uncertain upload outcome → pause for review; "reconciling" state in the Publish Center.

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

## Checklist for the user's machine

| Action | Command | Expected evidence | Why |
| --- | --- | --- | --- |
| Real CUDA transcription | `gpu-check.bat` (or `python -m clipfoundry gpu-check some_video.mp4`) | "device: cuda", compute type float16/int8_float16, speed ×realtime | this environment has no GPU; detection alone is not transcription |
| Platform documentation re-check | open the URLs in `docs/PLATFORM_CAPABILITIES.md` | constraints still match the recorded ones | the documentation hosts were blocked from this session |
