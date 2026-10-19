# AI changelog

Development checkpoints made by AI assistants, newest first. Each one says what changed, why, what was actually run
and what was not. The same checkpoints, in machine-readable form, are in `.clipfoundry/ai-change-log.jsonl` (shown
read-only in Settings → Advanced → Dev Log). Work before October 7, 2026 is not repeated here: it is recorded in
`docs/IMPLEMENTATION_STATUS.md` (plan, matrix and test log) and in the Git history.

Commit ids are snapshots of a branch at the time of writing; fetch before relying on them.

## 2026-10-19 · Submitted videos to Brain-guided clips and automatic YouTube uploads

* **Changed:** Missions accepts a recorded-video link/file with **Make & upload clips** or **Make clips only**.
  Submitted input is now the default; periodic/queued search and watched-folder admission stop without deleting
  old data or removing optional discovery. Relevant supported Brain guidance uses Settings fallback.
* **Authorization:** one explicit input-scoped request records destination/audience, genuine kids answer and
  reuse basis outside Brain. Acquired original/project/current terms and every final file/payload are bound.
  Only its newly generated qualifying YouTube posts can auto-approve; old backlog/later inputs/TikTok stay separate.
  Source requests do not change ownership or global audience/standing consent. Stop/pause/cancel, credit, quality,
  source drift, waits and uncertain-session/no-duplicate handling remain. An accepted-input enqueue gap recovers
  durably without reviving attempted/canceled jobs. Retention keeps referenced source/audit records while
  clearing stale API data and ordinary unused discovery; its foreign key no longer interrupts maintenance.
* **Audio:** retain measured downmix/peak/clock/track corrections and exercise actual Brain-guided rendered AAC
  through the exact fake YouTube upload bytes and restart. Existing distortion and real platform processing are
  not guaranteed repaired. Existing media/uploads remain unchanged.
* **Validation:** Final full fast suite: 1,451 passed, 17 slow deselected, in 676.07 s. Final full real-FFmpeg/synthetic-media and restart suite: 17 passed, 1,451 deselected, in 934.97 s. TypeScript and the production build passed (10.00 s). All 59 final built-browser checks passed in 161.55 s. The final fast suite used 198 frozen Python source/test files. All production and selected media-test sources stayed unchanged during the full media run; 81 frontend source and 17 built-file hashes stayed unchanged through the final browser checks. A deselected fast retention fixture's timestamp setup was corrected before the final fast run; the media run's production/selected sources were unaffected. Focused checks also passed: 60 submission/consent, 79 final status/routes/legacy readiness, 29 advanced-route/legacy, 119 legacy intake/scheduler/publishing, three new actual-media and 26 legacy audio/quality and nine retention checks. The three new media cases use relevant saved Brain guidance, real caption/AAC rendering, exact fake-upload bytes and restart without duplicates, including the broad YouTube switch off and TikTok enabled. Earlier full attempts were interrupted before the final route/status/retention corrections and are not final evidence. Tests use isolated profiles, synthetic media and fake platforms only. The readable source setup is pinned separately to this committed app tree with the tested frontend manifest; its delivery verification records exact archive hashes and source revision.
  No real owner account/Windows/RTX3050/Defender/24-hour run verified.

## 2026-10-15 · Failed search keys and post-only reuse explanations

* **Tool:** Codex. **Branch:** `codex/brain-graph-quality-discovery`. **Base:** `0c2729d`.
* **What changed:** bounded same-account OAuth refresh, safe key setup/restriction errors, explicit uncached saved
  search tests, credential-current results, strict responses and quota-aware concurrency. Key whitespace handling,
  provider-specific/review-mode diagnosis and clear post-only reuse text with independent Brain boundary tests.
* **Why:** owner reports no clips, clarifies both keys fail and asks that reuse entries not be saved in Brain.
  They confirmed these appear only on the post. No automatic Brain write existed; deliberate notes stay intact.
* **Validation:** Final full fast suite: 1,373 passed, 14 slow deselected, in 755.18 s. Final full real-FFmpeg/synthetic-media and restart suite: 14 passed, 1,373 deselected, in 945.34 s. Final TypeScript and production build passed (5.17 s). All 51 final built-browser checks passed in 167.41 s, with all 17 built-file hashes unchanged. Focused provider verification: 77 passed in 7.83 s; focused diagnosis/health/phone: 88 passed in 11.26 s; independent saved-search/Brain separation checks: 113 passed in 22.43 s before the final wait-order correction, then 53 passed in 4.06 s including both same-key full-server-wait regressions. All 261 frozen production/frontend/Python-test hashes remained unchanged through final verification. Tests used isolated data, synthetic media, MockTransport and fake platforms. No owner keys, Windows profile/RTX3050, actual search-service account, real upload, Defender acceptance or 24-hour soak was verified. Permission answers were already post-only; the update clarifies and verifies that boundary.
* **Not verified:** owner keys/provider setup, Windows/profile/RTX3050, real uploads or a 24-hour soak.

## 2026-10-15 · Audio, comments, ongoing search and live/Windows recovery

* **Tool:** Codex. **Branch:** `codex/brain-graph-quality-discovery`. **Base:** `11bdb435`.
* **What changed:** stereo downmix before normalization, final post-gain peak control, shared audio-clock/track
  handling; strict real kids answers and truthful YouTube comments/audience explanations; independent provider
  waits, recurring capacity-aware search, bounded pagination and saved-signal refill; visible supported search
  keys/free-only controls; safe paired HLS and bounded empty-ended-stream archive recovery; scoped Windows
  10054 cleanup with Python-version-compatible detachment. Added concrete `CLAUDE_HANDOFF.md`.
  Health/phone cadence reads remain pure; host-only deadline reconciliation also handles a full queue draining.
* **Why:** owner confirmed distorted uploaded audio, comments off on some posts, searches stopping and the two
  supplied live/Windows errors. Concrete defects were reproduced locally; no owner media/account was accessed.
* **Validation:** Final full fast suite: 1,278 passed, 14 slow deselected, in 579.81 s. Real-FFmpeg/synthetic-speech media and restart verification covered all 14 scenarios across two runs: the full attempt passed 12 with 2 repeat-discovery timeouts (1,274 deselected, 1153.68 s); after correcting only the compressed-clock fixture's discovery-list cache expiry, both private/public repeat scenarios passed in 374.57 s. This was not a single all-green full-media run. Production cache/quota policy and all real render, final-report, exact-upload-byte and restart assertions were unchanged by that fixture correction. Final production build: 10.32 s; TypeScript passed. All 43 final built-browser checks passed in 93.25 s, with all 17 frontend hashes unchanged. Focused independent bugfix verification: 73 passed in 32.22 s, including measured encoded mono/surround audio, exact fake-upload bytes, real split-HLS synchronization and real asyncio cleanup compatibility. Windows/phone focused verification: 63 passed in 10.25 s; earlier discovery focused: 89 passed in 11.12 s. The final queue-drain deadline correction and surrounding discovery checks passed 61 tests in 9.13 s. Final comments/search checks after the current-label correction: 47 passed in 22.85 s. The final read-only health/phone/search correction passed 77 checks in 16.64 s, with database-unchanged assertions intact. The complete media run used the final audio/live/publishing code, preceding only the pure health-cadence refactor and its four new fast tests; all 39 media-scope source hashes remained unchanged. That refactor is covered by the final full fast run and 77 focused checks. The earlier interrupted suites preceded final deadline/returned-label corrections and are not final evidence. No real owner Windows profile/media, RTX3050, live provider key, account upload or 24-hour soak was tested.
* **Not verified:** owner Windows runtime/profile/original audio, RTX3050, real provider keys/accounts/uploads,
  actual platform comment settings, native Windows/Defender or a 24-hour unattended soak. Existing published
  audio is not rewritten and source distortion cannot be reconstructed.

## 2026-10-15 · Faster review, bulk approval and consistent Brain guidance

* **Tool:** Codex. **Branch:** `codex/brain-graph-quality-discovery`. **Base:** `ec20aec`.
* **What changed:** inline Queue video/text previews, Quick approve and selection of up to 50 YouTube posts.
  Permission presets replace required typing, and one combined consent replaces duplicate checkboxes. Batch
  approval uses a fixed, expiring, account/file/source/terms/payload/audience/check-bound preview, explicit common
  permission basis and any missing kids answer; each success receives its own manual approval. Future posts gain
  no permission. Final guarded writes reject changed or active work without hashing under the database lock.
  Partial results retain skipped posts for review; exact retries return prior results. Known credit, physical
  quality, grounded text, post audience/time, platform waits and duplicate protections remain. TikTok stays
  individual. Single review and current per-post assertions retain exact-payload confirmation.
  Brain matching now retains source-title/spoken context through candidate generation, ranking, planning and
  rendering, including resume/live. Natural caption declarations and example feature fields are recognized;
  disliked-example observations no longer become desirable ranking traits. Recognized effects/length hints are
  shown honestly, Settings remain the fallback and explicit clip edits win. Unsupported text stays searchable.
* **Why:** the owner finds repeated review too slow and reports saved Brain notes/examples not changing clips.
* **Validation:** Final full fast suite: 1,195 passed, 11 slow deselected, in 739.22 s. Final real-FFmpeg/synthetic-speech media and restart suite: 11 passed, 1,195 deselected, in 1024.81 s. This includes exact selected-post fake uploads/restart and two actual Brain-guided/owner-overridden caption renders with persisted provenance. Final production build: 9.44 s; TypeScript passed. All 31 final built-browser checks passed in 95.78 s, with all 17 frontend hashes unchanged. Focused checks: 42 bulk, 19 independent approval audit and 86 Brain/context checks passed. Browser fixture wording/details visibility and async readiness were corrected before the final run; earlier interrupted or fixture-correction runs are not final evidence.
* **Not verified:** the owner's PC/profile, native Windows/GPU, real social uploads or a 24-hour soak.

## 2026-10-14 · Prepare and schedule for individual reuse review

* **Tool:** Codex. **Branch:** `codex/brain-graph-quality-discovery`. **Base:** `d0b7102`.
* **What changed:** review before publishing defaults on. Bounded quality-first discovery and local posting plans
  can include accessible unblocked sources with unrecorded reuse terms. Rights labels remain truthful, and new
  posts wait for manual approval. Queue shows proposed times without calling them approved uploads; review drafts
  do not expire. Uncovered posts need an individual owner reuse statement and basis bound to the exact source,
  terms/credit, post, account, audience, platform, bytes/version, text and options. Known required credit and
  physical-media checks remain binding. Old unstarted automatic approvals return to review atomically, retaining
  time, text, privacy and publication identity. Queued work, retry and not-published recovery cannot restore an
  automatic upload grant. Unknown outcomes retain their session and use account-bound readback. Separate manual
  publishing cannot borrow an assertion. Explicitly disabling review restores the existing guarded automatic mode.
* **Why:** the owner wants to inspect finished clips and confirm reuse before approving publication, rather than
  have missing records prevent a review plan or let standing permission authorize new uploads.
* **Validation:** Final full fast suite: 1,112 passed, nine slow deselected, in 529.54 s. Final real-FFmpeg/synthetic-speech media and restart suite: nine passed, 1,112 deselected, in 879.93 s, including the new review/owner-confirmation/exact-byte upload/restart loop. Final production build passed in 8.79 s; 12 built browser checks passed in 40.23 s, with all 17 frontend file hashes unchanged. Focused checks: 95 publishing/reuse checks; 64 scheduler/public/manual checks; final 46 review/current-terms checks; 107 legacy recovery checks; and eight final independent audit/fixture checks. The initial full fast attempt found an older fixture approving an unverified channel claim; its corrected exact-video verification retains all connection, quota, hash, explicit-block and no-upload assertions. Earlier full attempts were stopped before final corrections and are not final suite evidence.
* **Not verified:** the owner's Windows profile, native Windows/GPU operation, real platform uploads or a 24-hour soak.

## 2026-10-13 · Continuous eligible uploading and Brain/manager handoffs

* **Tool:** Codex. **Branch:** `codex/brain-graph-quality-discovery`. **Base:** `718358f`.
* **What changed:** app daily source/clip/platform caps default to 0 (unlimited), with all-day earliest-slot
  posting. A recorded one-time volume amendment preserves existing account/audience/kids permission and old
  posts, while future owner limits persist. Bounded search/queue/quality/API/cost/platform holds remain active.
  Uploadable-only broad discovery prioritizes verified own/agreed/CC media and explains local-only clips;
  legacy local-only finds cannot monopolize capacity. Past-due eligible approval holds and lost replacement
  times recover; reported platform zero holds approved dispatch without disrupting an active transfer.
  Current reuse/credit checks bind to both reports and actual upload text. Missing credit returns to editable
  review; proven unstarted row synchronization retains upload identity, route and current feature evidence.
  Private/canceled/manual/started/uncertain work remains protected. Count-only real Brain consultations now
  appear separately from mature-result learning. Explicit fresh manager/boss handoffs respect newer checkpoint
  outcomes, actual job ownership and Pause/Reduced/hidden/offline/history guards. Quiet rooms explain idle state.
* **Why:** the owner reported missing-permission posting holds, requested no app daily cap and continuous work,
  and found the office's Brain/handoffs misleading. No missing reuse or account permission was fabricated.
* **Validation:** Final fast suite: 1,047 passed in 556.14 s; eight real-media/restart checks passed in 836.38 s.
  Final production build passed in 6.16 s; 11 final built browser checks passed in 94.42 s, matching all 17 file
  hashes. Earlier 12 choreography checks, six department, three motion and six lounge checks passed. Final
  reuse/publishing: 93 passed; public/manual publishing: 34 passed. New current-terms regressions: 26 passed;
  independent continuous: 12 passed. Root phone checks: 56 passed. Initial full fast run found ten stale fixtures;
  updated local-discovery/finite-plan/current-report fixtures retain all permission/bytes/version/quality/wait
  checks. No owner Windows/GPU, real platform upload or 24-hour soak was tested.
* **Not verified:** real owner Windows data/runtime, RTX3050, actual account posting/visibility or a 24-hour soak.
  No real publishing, account/privacy change, spending, media deletion, security exclusion or deployment occurred.

## 2026-10-13 · Finished clips reach YouTube scheduling

* **Tool:** Codex. **Branch:** `codex/brain-graph-quality-discovery`. **Base:** `987ebb2`.
* **What changed:** reusable accessible discovery candidates take priority; parked permission/file waits cannot
  monopolize the bounded workable queue or displace them. Finished recorded clips get immediate durable handoff
  before batch yielding. Bounded reconciliation recovers proven old handoffs while preserving canceled work,
  manual edits, live decisions and existing packaging states. Parent cancellation/Pause is rechecked after
  fingerprinting. Stale consent no longer hides pending approval reminders; Private permission requires a
  confirmed upload destination too. Setup embeds audience and separate YouTube permission controls for connected
  accounts. Read-only readiness/derived warnings explain finished-clip holds without depending on a working
  scheduler; unavailable times are not called scheduled, and newer preparation overrides historical failures.
* **Why:** the owner had finished clips after an all-day YouTube-only run, with no posts or Needs you explanation.
  The exact owner-PC hold remains unknown; code failures were reproduced on disposable data and corrected.
* **Validation:** Final full fast suite: 958 passed, eight slow deselected, in 489.73 s. Final real-FFmpeg/synthetic-speech
media and restart suite: eight passed, 958 deselected, in 695.71 s, including Public/Private and live recovery
loops. Final production build passed in 3.98 s; seven built-interface browser checks passed in 43.6 s. All 17
tested built-file hashes match. Final focused handoff/readiness/simple-page checks: 88 passed in 24.79 s.
Discovery focused checks: 99 passed in 19.36 s; four new behavior regressions fail on the original source.
Scheduler/consent checks: 73 passed, one slow deselected, in 78.53 s. Independent review found the late-
cancellation race; its three corrected regressions passed and no material findings remain. No real owner data,
Windows/RTX3050, platform upload or 24-hour soak was tested.
* **Not verified:** owner Windows data/runtime, RTX3050, real platform accounts or a 24-hour unattended soak.
  No real publishing, consent/account change, spending, firewall/router change or deployment occurred.

## 2026-10-13 · Private phone status companion

* **Tool:** Codex. **Branch:** `codex/brain-graph-quality-discovery`. **Base:** `4838aa8`.
* **What changed:** default-off Tailscale/home-Wi-Fi listener serves a mobile read-only dashboard, separate from
  desktop APIs and media. Guarded owner controls issue single-use expiring pairing codes, enable/disable access
  and revoke up to eight hashed 90-day device grants. Keys use authorization headers and opt-in browser storage;
  codes and keys never enter URLs/logs. Listener failures leave the desktop functional; custom desktop ports,
  restart and shutdown cleanup are covered. Counts, progress, status and attention policy follow actual app
  state. Mobile polling handles background/offline/reconnect/expiry, clears unauthorized data and escapes text.
  Desktop setup prevents old polls from overwriting newer actions. Setup/privacy/architecture docs are updated.
* **Why:** the owner wants to see how ClipFoundry is doing from a phone, including away from home.
* **Validation:** Final full fast suite: 869 passed, eight slow deselected, in 386.91 s. Final focused phone tests: 55 passed in 9.03
s; 75 existing local-guard/office/Autopilot regressions passed in 30.43 s before the final attention refinement.
Final built phone browser suite: ten passed in 12.6 s. Final built desktop setup/race checks: two passed in 27.6 s.
Production build passed in 3.85 s; all 17 built-file hashes were recorded. No actual phone, Windows/Tailscale
connection or real account was tested.
  Initial full fast suite: 865 passed before the final attention-policy refinement. No processing/publishing
  handler changed, so no new slow media run. Installer tests and exact bundle integrity are recorded separately.
* **Not verified:** native Windows/RTX3050, actual phone browsers, real Tailscale account connectivity/firewall
  behavior or platform accounts. No real upload, account change, router/firewall configuration or cloud hosting.

## 2026-10-13 · Automatic Brain guidance and supported integration cards

* **Tool:** Codex. **Branch:** `codex/brain-graph-quality-discovery`. **Base:** `28aee85`.
* **What changed:** enabled saved Brain material participates automatically in new clip selection/rendering,
  with Settings fallback. Local recognition covers supported caption/pacing controls and ranking priorities;
  explicit choices override prose. Good examples contribute measured duration hints blended once with the
  original target. Disabled/paused material remains inactive. Revision-specific selection/render decisions merge
  without mutating shared snapshots. Manual editor overrides retain precedence; existing clips/posts persist.
  Brain shows recognized choices, automatic activation and unsaved drafts, with no separate approval action.
  Integrations removes seven inactive connector placeholders while retaining real platform permission/limit
  messages. Raw Brain material is never executed or sent to an AI; only fixed priority names accompany its
  existing transcript payload. Privacy/product documentation describes the changed behavior.
* **Why:** the owner reported stored Brain material was not being used and requested automatic use even with
  sparse knowledge, combined with Settings, plus removal or repair of unsupported integration entries.
* **Validation:** Final full fast suite: 814 passed, eight slow deselected, in 349.16 s. Final focused Brain/provider/blueprint/artifact regressions: 96 passed in 43.45 s. Actual-FFmpeg/synthetic-speech media/restart suite: eight passed, 811 deselected, in 710.71 s before the final example-blending/provenance review fixes; those final fixes are covered by the final 814/96 runs. Final controlled browser batch: eight passed in 45.5 s against the final built interface. Build passed in 6.44 s. No real uploads, accounts, Windows/RTX3050 execution or 24-hour soak were tested.
  Final fast/focused coverage includes the last example-blending and shared-provenance fixes. Media ran before
  those last fixes; all eight passed using existing portable speech tools and adequate workspace temp storage.
  Eight final browser checks cover activation, real lookup, unsaved drafts, stale-revision recovery, graph
  accessibility/mobile/motion/bounds and removal of placeholders. The local report collector separately passes
  synthetic privacy/GET-only/custom-port/offline/invalid-port checks. Packaging integrity is recorded separately.
* **Not verified:** native Windows installation/runtime, RTX 3050 CUDA/NVENC, actual account grants/visibility,
  model quality with owner clips, visual learning from examples, or an actual 24-hour soak. No real posts,
  account-permission changes, dependency upgrades, purchases or deployment.

## 2026-10-13 · TikTok setup, visible Brain graph and focused discovery

* **Tool:** Codex. **Branch:** `codex/brain-graph-quality-discovery`. **Base:** `8999e5f` from the default branch;
  PR #14 is already merged. **Result:** the commit containing this entry.
* **What changed:** TikTok form helper supplies copyable app details, current-port Desktop callback, two 1024×1024
  PNG icons, products/scopes and a form-pack export with local draft website/legal pages. Inbox, Direct Post and
  optional statistics request only their chosen permissions after applying, saving and reconnecting. Exports
  exclude credentials, tokens, account identity and owner media; URL checks are syntactic, with no network fetch.
  The helper prepares drafts only when opened and does not claim registration, review approval, hosting or an
  actual integration demo.
  Brain's interactive graph shows actual saved notes/examples/preferences, shared tags and recorded readings and
  clip influence; notes/evidence open their stored records/provenance. Decorative glow and positions are not model
  thoughts.
  Add note is simpler; Teach preference retains explicit revision review/approval. Stale edits return 409 and keep
  unsaved text until explicit reload. Uploaded material does not fine-tune a model.
  Quality-first broad discovery defaults to three picks per pass, six unfinished picks including needs-rights,
  one known creator and two per topic. The existing default three-attempt daily budget remains; explicit inputs
  keep their behavior and weak estimates do not trigger unlimited attempts to fill the clip target.
  Tavily's optional free-key setup explains 1,000 monthly credits/no card and explicitly selects a $0 app spending
  limit when chosen, preserving other settings. No new graphics or browser dependency was added.
  One read-only Integrations assertion now expects the already implemented explicit Public audience choice,
  while Unlisted remains absent. Owner-data test flows and the HTTP write blocker are unchanged; no permission
  is selected or saved by that test.
* **Why:** the owner requested a finished app and Windows installer, clearer TikTok setup, an Obsidian-style view
  of saved Brain data and stronger discovery choices instead of chasing more clips.
* **Validation:** final full fast Python: **804 passed**, eight slow deselected, in **429.01 s**; Python is unchanged.
  All eight media cases passed across the initial run (seven passed, one environment disk-capacity failure,
  965.89 s) and unchanged live rerun (48.81 s) using workspace temp storage.
  **52 unique browser checks** are covered across runs: initial 42 passed/two failed in 12.7 min; final 19 passed
  in 1.1 min (11 changed UI, eight strict read-only Settings; ten overlap the initial batch); complete loop one
  passed in 7.0 min. The final lazy helper fixes background preparation; the old Public assertion was updated
  with read-only policy intact. Recorder/temp-storage prerequisites were fixed for the actual complete loop.
  Final build passed in **4.06 s**; all 14 tested/captured hashes match.
  [Desktop/mobile/empty previews](design/brain-workspace/README.md) use controlled records from the final run.
  Earlier interrupted outputs and historical checkpoint counts are separate evidence. The Windows installer
  has a separate bundle/integrity record on `codex/clipfoundry-one-click`; native Windows remains unverified.
* **Not verified:** Windows installation/execution, RTX 3050 CUDA/NVENC, real platform grants/visibility and an
  actual 24-hour soak. TikTok personal-tool eligibility, Sandbox/public limits and per-post consent remain external
  constraints. No real upload, app registration/review, account-permission change or website deployment occurred.

The PR #14 entries below retain their original branch status and evidence. PR #14 is now merged; earlier
draft/unmerged instructions are historical and do not govern this new checkpoint.

## 2026-10-11 · Final merge review and stable log-rotation check

* **Tool:** Codex. **Branch:** `claude/project-thread-vw1n9y`, PR #14. **Base:** `51984a3`.
  **Result:** the commit containing this entry. The owner authorized merge after the final review; the actual
  merge outcome is recorded on GitHub.
* **What changed:** the live log-rotation test now takes the standard logging handler lock while enumerating
  and measuring backup files. This prevents the test from inspecting an intermediate rename. The real child
  still writes enough output to rotate logs, stays running during the check, and is stopped afterward.
  Production code and the browser-tested frontend are unchanged.
* **Validation:** independent production review found no material blockers. The initial targeted run passed
  105 checks and failed this one snapshot race in 77.43 s; all 16 corrected launcher checks passed in 0.72 s.
  The fresh full fast suite passed **757 checks**, with **8 slow cases deselected**, in **301.90 s**.
  The worktree diff is clean and all 14 browser-tested build hashes match. GitHub reported no workflow runs,
  commit statuses, review submissions or review threads for the reviewed head; the PR had no conflicts.
* **Not verified:** Windows, RTX 3050, real platform accounts and an actual 24-hour soak remain owner checks.
  The preceding media/browser/crash-recovery evidence remains applicable. No real upload or deployment occurred.

## 2026-10-11 · Unattended Public operation and current YouTube policy

* **Tool:** Codex. **Branch:** `claude/project-thread-vw1n9y`, existing draft PR #14. **Base:** `61f6042`.
  **Result:** the commit containing this entry. PR stays draft/unmerged.
  Started October 10; final validation October 11.
* **What changed:** removed the obsolete API-project audit requirement for Public uploads, following official
  YouTube `videos.insert`/`videos` documentation updated October 8 and checked October 10. Explicit Public audience,
  account-bound approval/standing permission, rights, exact-file checks and actual visibility remain; old Private
  schedules are preserved. Midnight zero is retained so 0–24 scheduling works. OAuth Production/reconnect guidance
  distinguishes Testing's seven-day YouTube grants from API quota audits; private TikTok profiles cannot offer Everyone.
  Optional `run-unattended.bat` / `--unattended` restarts an unexpectedly exited app with bounded backoff, selected
  profile/port locks, owned descendant cleanup and explicit-stop handling. It preserves intentional Pause and
  permissions. Its local diagnostic log rotates at 5 MiB plus two backups; optional same-user login startup is
  documented.
  Only one app may use a data profile. The watchdog detects process exit, not a still-running hung main app.
* **Recovery fixes:** failed host initialization cleans up partial workers before releasing its lock; job setup
  errors clear phantom running/heartbeat entries. Bounded cancellable media reads/writes/waits kill/reap children;
  HTTP/live capacity checks retain a 2 GB reserve. Low disk yields Needs you and a durable wait, preserving saved
  segments and never implying stream EOF. Final assembly replaces a complete recording only after success.
  Scheduled pre-session waits recheck Pause/current permission/account/audience/final quality. Strict unknown-upload
  recovery requires an original-account, unique recent match with submitted metadata and reads actual visibility.
  Final-chunk crashes/cancellation/ambiguous errors hold another upload; manual restart recovery offers read-only
  Refresh status. Later reconnect, setup, scope or quota errors preserve the final-byte hold and publication
  identity. Existing valid sessions keep their exact confirmed bytes.
* **Why:** the owner requested all-day autonomous Public publishing from a personal setup and a final reliability
  review. This supports unattended YouTube operation after setup while preserving deliberate exception holds.
* **Validation:** full fast Python: 757 passed, eight slow deselected, in 390.67 s. All eight slow cases passed across
  the full run (six passed, two fixture setup failures, 786.85 s) and corrected Public (58.73 s) and upcoming-live
  (49.02 s) reruns. Public setup now uses `confirm=True` and asserts the confirmed response; its controlled scheduler
  cadence is five seconds. The live fixture uses a valid 0.5 GB capture cap on the small cloud temp disk; production's
  default 8 GB cap and 2 GB reserve remain. Production code did not change for these fixture corrections.
  All 32 isolated browser cases passed together in 8.1 min. TypeScript/Vite build passed in 4.37 s; all 14 tested
  file hashes match. Final fast verification includes recovery, media, launcher, policy and unknown-outcome
  regressions. Actual-app POSIX exit/restart/stop smoke passed in 11.98 s; Windows remains unverified.
  The real-media loop now tests Public and Private separately through repeat/restart,
  exact checked/uploaded bytes, mature fake results and actual live/post-live handlers. Public needs no invitation
  fixture. Earlier department/office test counts and animation evidence below remain historical.
* **Not verified:** actual 24-hour soak, Windows launcher/Task Scheduler/Job Objects, RTX 3050 CUDA/NVENC and real
  account scopes/quota/visibility/revocation. No real post, account change, purchase or deployment occurred. No new
  dependency; `.mcp.json`, GPU versions, Playwright versions and read-only `e2e/tests` are unchanged. The watchdog
  cannot make a powered-off PC work or bypass unknown outcomes, missing rights, expired access or resource holds.

## 2026-10-10 · Department attendance, manager supervision and reliability review

* **Tool:** Codex. **Branch:** `claude/project-thread-vw1n9y`, existing draft PR #14. **Base:** `e896632`.
  **Result:** the commit containing this entry. Requested October 9; resumed/completed October 10. PR stays unmerged.
* **What changed:** real jobs or substantive assigned backlog gather each complete department into its room.
  Workers appear immediately at their own desks; supporting peers remain honestly idle and ready. Managers stand
  facing the team with clipboard/pointing gestures, while their own jobs and real reviews take priority. Quiet
  paused/unavailable peers can attend; bare counts, stale paused tasks and unreferenced recurring timers cannot
  summon a team. A finished worker remains while its teammates work, then returns to lounge activities. Confirmed
  transfers meet inside the receiver's office and return to the latest department duty; a newer own job preempts
  carrying an older document away. Pixi and Canvas retain motion/freeze guards and all 25 identities.
  Brain Processing now has clipped scan bands, travelling synapse trails, rising sparks and orbital light trails.
  Added floor/contact/furniture polish and rebuilt frontend; existing Pixi/GSAP reused without new dependencies.
* **Reliability fixes:** lease-bound progress/host updates and transactional recovery protect current jobs from
  recovered handlers and heartbeat races; failed lock-file creation releases its mutex. Quality-check job identity
  includes the rule version. Regeneration checkpoints and restores video, captions, transcript, edit decisions,
  render plan and thumbnail, remaining non-Ready until rollback succeeds and retaining recovery copies on failure.
  Brain edits use atomic revision checks; paused learning collects results without changing/applying learned values,
  and confirmed audience drift cannot enter new selected-viewer readings. Manual publishing rechecks linked-source
  rights, platform coverage, current quality/version, confirmed bytes, connected account and emergency Pause.
  Unknown YouTube outcomes hold new uploads; strict original-account metadata lookup is read-only and ambiguity
  stays held. Already-processing entries only refresh status. The Publish page exposes the hold and Refresh status.
  Privacy text describes temporary recovery copies and approval-file fingerprints.
* **Why:** the owner requested full departments in their offices, a visible supervisor, a cooler Brain and a broad
  code review before delivery. Each backend fix addresses a reproduced fault found during that review.
* **Validation:** full fast Python: 685 passed, seven slow cases deselected, in 347.07 s. All seven slow media cases
  passed together, 685 fast deselected, in 676.84 s. All 31 isolated browser checks passed together in 7.8 min.
  Final TypeScript/Vite build passed in 5.96 s with the existing 904 KB lazy graphics warning;
  all 14 distribution files and file sets are identical to tested/captured SHA-256 manifests. Routing/controller
  checks cover 3,844 + 36,304 routes, 600 virtual seconds and 150 mixed transitions. Actual Brain/supervisor pixels
  animate and freeze in Reduced while real states update. All 32 touched/new code files meet 120 columns, and
  whitespace checks pass.
  Earlier 29/31-case browser runs each had one failure: a mismatched report fixture, then sampling the same Canvas
  idle frame twice. Matching job/kind/reference and polling across 900 ms frames corrected these; the production
  new-own-job guard remains intact. Those runs are distinct from the final all-green run above.
* **Evidence:** [department screenshots, controlled video and provenance](design/robot-office/departments/README.md):
  nine screenshots, one visibly labeled 37.40-second 1440×900 H.264 recording, 25 identities, visible laptop controls,
  no mobile horizontal overflow and zero page/console errors. The actual stopped-sandbox lounge capture is separate
  from controlled working/Brain/handoff states. All 14 captured production-file hashes are recorded. The recording
  demonstrates choreography, not real processing times, GPU performance or platform-account behavior.
* **Not verified:** Windows CMD/setup/fonts/scaling, RTX 3050 CUDA/NVENC and real platform accounts/uploads remain
  owner checks. No real post, owner account change, purchase or deployment occurred. GPU dependencies, `.mcp.json`,
  Playwright versions and read-only `e2e/tests` are unchanged. Earlier checkpoint results below remain historical.

## 2026-10-09 · Social pixel office and off-duty lounge life

* **Tool:** Codex. **Branch:** `claude/project-thread-vw1n9y`, draft PR #14. **Base:** `5b1f7a9`.
  **Result:** the commit containing this entry. PR stays draft/unmerged.
* **What changed:** six authored arcade/game/drink/snack/read/rest gestures in furnished lounge zones, with 29
  exclusive places, 25 stable cast homes, phased rotation and at most two recreational walkers. Real work and
  document transfers preempt breaks; job icons and references remain truthful. The owner's stopped-office
  recreation exception preserves Paused badges; individual pause while Running/unavailable remains quiet, and
  global Pause/Reduced/hidden/stale views freeze. Added pinned GSAP 3.15.0 pure easing with its standard no-charge
  license notice, cached Pixi BlurFilter light pools and an original locally bundled generated skyline. Optional
  image loading has a 1.5-second bound/procedural fallback and safe cropped-texture cleanup. Canvas has simpler
  phase-driven gestures; frozen Brain cues stay still on expiry. Dense whole-map names are staggered and the close
  lounge camera uses compact labels. Built frontend; no backend/media/publishing behavior changed.
* **Why:** the owner requested better graphics tools and off-duty robots that play, eat and drink while retaining
  the refined retro style and actual job behavior.
* **Validation:** full fast pytest: 641 passed, seven slow cases deselected, in 280.30 s. Final TypeScript/Vite build
  passed in 5.83 s with the existing 904 KB lazy graphics chunk warning. All 23 focused browser cases passed together
  in 6.4 min (lounge 6, living 7, motion 3, pixel 3, robot 4). All 14 distribution files are SHA-256 identical to the
  assets used in that final run after source-formatting cleanup.
  Geometry/controller checks covered 2916 + 4770 routes, 600 simulated seconds with all 25 identities rotating
  safely, exclusive reservations/max two walkers, and 150 mixed-state transitions. Actual rendered checks show
  all six Full gestures changing pixels, zero Reduced drift and real-work suppression of leisure props; frozen
  Canvas Brain pixels remain unchanged when an activity cue expires.
* **Evidence:** [actual isolated screenshots, labeled recordings and editing guide](design/robot-office/lounge/README.md).
  Final desktop/laptop/mobile captures retain all 25, visible laptop controls, no mobile overflow and zero page
  errors. Actual stopped lounge recording: 33.24 s; labeled controlled work/Brain/handoff recording: 33.48 s.
  Both are 1440×900 H.264 and have zero page errors. An initial controlled recording timed out with three browsers
  competing; its standalone rerun succeeded. Only startup before the provenance banner was trimmed, without retiming.
  These recordings do not measure clipping speed or GPU performance.
* **Not verified:** Windows CMD/installation/PC graphics/scaling, RTX 3050 CUDA/NVENC and real accounts/uploads.
  The seven slow media cases were not repeated for this frontend-only scope; prior results remain historical.
  GPU pins, `.mcp.json`, Playwright versions and `e2e/tests` remain unchanged. No real posts, account changes,
  hosting purchase or deployment occurred.

## 2026-10-08 · Living office, seated robots and animated Brain

* **Tool:** Codex. **Branch:** `claude/project-thread-vw1n9y`, draft PR #14. **Base:** `a119dfd`.
  **Result:** the commit containing this entry. PR stays draft/unmerged.
* **What changed:** a 960×640 furnished office with consistent robot/desk/chair proportions, clear aisles and 25
  individual lounge seats. Idle/waiting/paused/unavailable robots rest there; working/reviewing robots walk to
  their own desks and sit with bent knees and keyboard hand motion. Confirmed fresh job transitions and worker
  reports bring both robots together, pass one visible document and return them to the latest actual destination.
  Ownership/cursor recovery prevents outdated senders after hidden/paused/offline periods and history resets.
  The animated Brain has neural hemispheres, synapses and layered orbits; decorative Standby and true Processing
  are labeled separately. Paused/Reduced/offline states still the art. Added a room camera, matching Canvas
  compatibility layout, separated handoff names and built frontend. No new dependency or backend behavior.
* **Why:** the owner requested realistic proportions, idle lounge behavior, seated work, actual handoffs and a
  cooler animated Brain while keeping refined retro pixel art. Existing PixiJS supplies the needed tools.
* **Validation:** TypeScript/production build passed; 17 office Python checks passed in 6.10 s. All 17 focused browser
  checks passed together in 3.1 min. Browser coverage is seven
  living-office cases plus three motion, three pixel and four robot-office cases; exact final outcomes are at the
  top of [IMPLEMENTATION_STATUS.md](docs/IMPLEMENTATION_STATUS.md). Both suspension and reset sender regressions
  passed. Actual desktop/laptop/mobile captures reported zero browser errors; all 25 identities and laptop controls
  fit. The earlier full backend/media suites were not repeated for this frontend-only change.
* **Evidence:** [actual isolated screenshots, labeled controlled animation and editing guide](design/robot-office/living/README.md).
  The controlled video demonstrates graphics and event choreography, not real clipping time or GPU processing.
* **Not verified:** Windows CMD/PC graphics/scaling, RTX 3050 CUDA/NVENC and real connected accounts. Dependencies,
  GPU pins, `.mcp.json`, Playwright versions and `e2e/tests` are unchanged in this checkpoint. No real posts,
  account changes, purchases or deployment occurred.

## 2026-10-08 · Refined pixel office and Windows path recovery

* **Tool:** Codex. **Branch:** `claude/project-thread-vw1n9y`, existing draft PR #14. **Base:** `c33a291`.
  **Result:** the commit containing this entry. PR stays draft and unmerged.
* **What changed:** pinned PixiJS 8.22.0 paints the furnished office and all 25 refined robot rigs; Team/detail/gallery
  portraits share one lazy offscreen renderer with a bounded frame cache. Static scenery is cached separately from
  live robot/room layers. A scoped navy studio shell fits the map, details and controls at laptop sizes. Existing
  job events still govern work, walks, report handoffs and decisions; COMMAND visibly signals recorded approval.
  Motion preferences remain and graphics failure restores the original Canvas artwork and controls.
  Included third-party graphics notices and rebuilt distribution. No backend or publishing behavior changed.
  Windows setup now explains the long-path failure shown in the owner's screenshot and recommends fresh ZIP contents
  directly in a short folder (`C:\CF14`), creating a fresh `.venv` while preserving normal data. Both venv and pip
  failure branches include the guarded remedy; no registry changes or administrator settings.
* **Why:** the owner requested using better graphics tools and chose refined retro pixel art; their nested archive
  extraction also caused a Windows dependency installation failure.
* **Validation:** TypeScript/production build passed. Office Python: 17 passed in 7.20 s. Final isolated browser run:
  ten passed in 59.3 s (3 motion, 4 robot, 3 graphics/portrait/visible approval cases). The earlier scratch 60-second
  run timed out in the last sequential viewport check; a corrected timeout passed nine, then the final ten-case run
  passed with the approval pixel regression and scenery cache. Actual desktop/laptop/mobile captures recorded zero
  browser errors. 25 Team/100 gallery portraits rendered with a stable shared context count. Reduced-mode approval
  differs from idle in actual rendered pixels. Diff checks passed. Prior full/media results remain the preceding
  checkpoint's evidence and were not rerun in full for this graphics follow-up.
* **Evidence:** [screenshots, labeled controlled animation and source-editing guide](design/robot-office/retro/README.md).
  Pixi needs no account, plugin hookup or paid AI service. The video uses controlled test events, not real processing.
* **Not verified:** Windows CMD execution/installation, PC fonts/scaling/graphics, RTX 3050 CUDA/NVENC and real accounts.
  GPU dependencies, `.mcp.json`, Playwright versions and `e2e/tests` remain unchanged. No real posts, purchases,
  account permission changes or deployment occurred.

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
