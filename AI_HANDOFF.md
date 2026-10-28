# AI handoff

## Supplied audio sample investigation — 2026-10-28 (America/Chicago)

The owner supplied a finished 23.067-second MP4 and its matching YouTube Shorts URL. The local MP4 fully
decodes without reported errors: H.264 video and AAC-LC stereo at 48 kHz, audio/video starting at zero,
matching 23.066667-second container lengths, and continuous audio packet timestamps. There is no opening
silent stretch of 100 ms at either -50 or -60 dBFS. One-second channel correlation stays positive; this
sample does not establish a phase-cancellation cause. This is structural/sample analysis, not a listening
assessment or proof about platform playback.

The exact supplied file (8,906,887 bytes) passed three local fake-YouTube transfers using the production
8 MiB chunk size: normal, interruption after the first chunk followed by resume, and retry after HTTP 503.
All three delivered byte-identical media through one session and produced one fake video. Secondary local
128 kbps AAC and Opus encodes of this real sample preserved the first ten seconds: sample correlation >0.9975
and maximum active 100 ms-window RMS drop <0.167 dB. These are not real YouTube transcode tests.

**Still unresolved:** the browser service could not fetch either Shorts or watch playback (throttled), and the
workspace proxy rejected YouTube access with HTTP 403. Do not work around that access policy. Request the
posted copy downloaded through YouTube Studio, or a playback recording if that copy does not reproduce it.
An optional question about replay on another device/browser is pending. The app source still has no confirmed
upload-only defect. No speculative processing change, new installer, real upload or owner-account action was
performed. Supplied media and derived audio remain in the private workspace, outside Git and release packages.

## Upload-only audio clarification — 2026-10-23 (America/Chicago)

**Unresolved:** The owner now clarifies that the video sounds fine before upload and becomes distorted/quiet
only after upload. The earlier normalization defect is real, but it is not a confirmed explanation or fix for
this reported upload-only problem. Do not claim the prior download fixes this case without comparing the actual
finished local MP4 with its matching platform playback. It remains unknown whether the local preview means the
original source, the finished clip, or another rendered version; the platform/link has been requested.

Follow-up on app revision `58770e2242c8a84a6b6394048abde55a5065dc23`: traced selected-file resolution, content-hash
checks, and YouTube/TikTok binary upload paths. The encoders are not invoked by the uploaders. Six focused
resumable/interrupted/chunk tests passed (50 deselected, 6.63 s). A retained synthetic render has AAC-LC stereo
at 48 kHz, with audio/video starting at zero and both container durations 11.600 s. Four local secondary encodes
(AAC/Opus, mono/stereo, 128 kbps) retained clean initial tone and stable repeated passages: initial-to-later
RMS change remained within 0.007 dB and initial tone purity exceeded 99.99%. These are local FFmpeg tests,
not YouTube/TikTok processing tests and not evidence about the owner's particular media.

No functional code, media, platform account or release package changed in this follow-up. Next evidence needed:
the exact exported finished MP4 that sounds correct locally and the corresponding affected uploaded-video link
(or the platform-processed file if the link cannot be accessed). Compare the same version, initial decoded
samples, channel phase/downmix, timestamps and platform output before choosing another processing change.
The cloud workspace has no owner-PC VPN/account connection and its network policy does not currently grant
YouTube/TikTok access. Do not bypass that policy or ask for account credentials.

## Audio startup and volume stability — 2026-10-23 (America/Chicago)

Base: `2eda06afe16b9dbfd22a2f42c3056d08c88c7094`, verified as the latest pushed source on both
`claude/sharp-rubin-zmg6tx` and `codex/brain-graph-quality-discovery` before work. All 18 remote branch heads
were checked. This update continues from that source and preserves the earlier Brain, framing, scheduler,
submitted-video, Python setup and robot-office changes.

The previous single-pass loudness normalizer could boost a quiet opening by about 50 dB, then reduce the same
quiet signal by over 24 dB after a loud moment. This is a reproduced processing defect, not proof that every
reported distorted source has this cause. The owner has not supplied an affected original/render/platform pair.
The uploaders transfer the rendered MP4 bytes without changing the audio.

New normalized renders measure the complete kept audio timeline after first-track selection, clock repair,
trims/joins, stereo downmix and speed changes. The encode uses one constant gain targeting -14 LUFS, limited
by the measured -1.5 dB true-peak headroom and a maximum 24 dB boost. Highly dynamic recordings can therefore
finish quieter than -14 LUFS rather than pumping or flattening their dynamics. Silent/ungated material receives
no guessed boost. Explicit gain and the existing compensated final limiter remain. Normalization off skips the
measurement pass. Failed/malformed measurements stop rendering; cancellation and time bounds apply. Numeric
measurements and the applied gain are retained in local `render_info.audio_processing`; no extra audio recording
is saved or sent to a service. The editor describes -14 LUFS as a target, not a guaranteed platform standard.

Existing files, approvals and uploads are not rewritten or posted again. To apply the fix to an older clip,
render it again from its source, preview it, and let its new exact-file checks/approval run before uploading.
Already damaged source samples cannot be reconstructed by changing loudness normalization.

**Validation:** Full fast suite: 1,515 passed, 19 slow deselected in 573.11 s. Full real-media/restart suite: 19 passed, 1,515 deselected in 890.51 s. No failures or skips in these final runs. The first media attempt lacked espeak on PATH (12 passed, four skipped, three fixture-setup failures); the existing isolated speech tool was added to that test process's PATH and all 19 cases were rerun without code changes. TypeScript/Vite production build passed (Vite 4.88 s); two existing built-browser creation/editor checks passed (11.6 s). All 202 frozen Python source/test files and 17 built files match. New regressions verify stable AAC startup and repeated quiet passages, noise/silence, exact kept intervals and speed, invalid-measurement/cancellation handling, a full 1080x1920 render from AAC 44.1 kHz, and byte-identical transfers through fake YouTube and TikTok. Before/after output measurement reduced an artificial 24.42 dB drop on identical quiet audio to 0.0013 dB. Real platform transcoding and the owner's affected original remain unverified.

No owner data/profile, native Windows/RTX3050, real YouTube/TikTok upload or platform transcoding was tested.
The local privacy text describes the added measurements; public Pages is not redeployed by this update.


Read [AGENTS.md](AGENTS.md), this file, [docs/OFFICE.md](docs/OFFICE.md) and
[docs/PLATFORM_CAPABILITIES.md](docs/PLATFORM_CAPABILITIES.md). Snapshot: 2026-10-23 (America/Chicago).
Fetch before trusting branch state.

## Latest continuation: Brain use, moving framing, spaced uploads and input reuse

Date: 2026-10-19 (America/Chicago). Base: `82784dd41463dc3559082b9c8e252e20051d789e`, on
`codex/brain-graph-quality-discovery`. The owner reports Brain not affecting clips, fixed framing, simultaneous
posting times and Queue asking again for supplied-video reuse permission. The supplied example note is
"Find strong standalone moments across topics for TikTok and YouTube Shorts. Prioritize:".

* Brain platform/workflow tags no longer require those literal words in spoken content. Remaining topic tags
  still narrow relevance. That example note supplies the recognized standalone ranking priority. Manual clip
  creation now retains actual ranking revision/decision snapshots, and rendering combines them with the
  supported caption/style guidance. The editor lists the lessons actually used. Disabled lessons, explicit clip
  edits, local raw-note privacy and reference-only unsupported prose remain unchanged.
* Auto framing uses measured motion/edge activity when face detection has no usable subject, including long
  tracking dropouts. Equally good visual crop windows centre the measured activity rather than pinning it to a
  crop edge. The framing cache version is 3. The final gate recognizes motion only with recorded analysis
  coverage/activity evidence and labels the result an estimate. Explicit Center/Manual and uncropped portrait
  frames remain steady. Existing files and old uploads are not silently rewritten or uploaded again.
* Default spacing is 30 minutes. A one-time migration repairs the old saved zero; positive custom gaps and later
  explicit choices survive. There is no new daily cap. Local replans serialize; pending automatic collisions are
  spaced without changing valid content approvals, owner-rescheduled times or started/uncertain sessions. A
  durable per-account atomic reservation also spaces already queued transfers after a restart/platform wait.
  Actual new starts refresh pacing after a long wait, and completions extend it after slow uploads. Rechecking/
  resuming the same logical transfer retains its identity; platform waits and all publishing gates bind.
* An existing unique source-submission record remains discoverable if an older intake refresh lost its marker.
  Queue can carry that input's reuse statement onto its exact new post, avoiding retyping during quality/manual
  review and ordinary text edits. It does not become a verified ownership/license rule or Brain knowledge.
  Auto-repaired generated output can receive fresh exact-file authorization only after new checks, with the
  generated metadata intact and no owner edit/cancel or selected alternate version. Input account/audience/kids/terms/source-byte binding,
  old-backlog exclusion, explicit blocks and TikTok per-post consent remain. A clip with no valid saved upload
  request still needs the owner's actual approval; a local file alone creates no grant.

**Validation:** Final full fast suite: 1,504 passed, 18 slow deselected in 687.23 s. All 18 selected real-FFmpeg/synthetic-media and restart cases passed: 15 in 766.75 s before stopping the remaining legacy zero-gap fixture wait, then its corrected three cases in 455.55 s. TypeScript/production build passed (6.03 s); all 61 built-browser checks passed in 170.29 s. All 204 other frozen Python/source/test/bootstrap/dependency files and 17 tested built files retain their hashes. Only the slow-loop fixture changed after the fast/first-15-media checks, to explicitly select zero spacing for compressed test time; all its three affected cases were rerun. Production source stayed unchanged. The final 205-file manifest matches the delivered source. The final source adds the reviewed alternate-version repair guard, covered by the final full suites and 62 focused checks; the already completed browser run covers unchanged frontend paths. Earlier full attempts stopped for evidence/pacing/version corrections are not final evidence. Actual moving-frame output, saved Brain ranking influence, input-bound reuse, concurrent/restarted pacing, platform waits and exact fake uploads were checked in disposable profiles. No owner profile, real social upload, native Windows/RTX3050 or 24-hour soak was tested.

The readable setup is pinned separately after this exact source checkpoint, retaining every prior managed
release identity and the historical blocked EXE unchanged. It includes the prior Python compatibility, audio,
submitted-video and TikTok icon fixes. Close the desktop app before updating; new framing applies to new renders.
Native Windows/RTX3050, the owner's actual Brain/profile and real YouTube/TikTok delivery are not verified here.
Public Pages remains at its separately deployed icon correction; this task does not redeploy public legal pages.

## Latest continuation: consistent TikTok app, website and tab icon

Date: 2026-10-19 (America/Chicago). Base: `4fae46c82f5b14e3a54c451dee7ff5e3d948b21f`, on
`codex/brain-graph-quality-discovery`. TikTok's reviewer rejected Basic information because its robot icon did
not match the older filmstrip on the public site and browser tab.

The unchanged submitted dark robot PNG (`design/tiktok/app-icon-dark.png`, 1024 x 1024 RGB, 9,382 bytes,
SHA-256 `b4dae127e333ec936c29acc6d9baabebda2caaf724689a2435591a7652e077fa`) now supplies the app's Logo and
favicon, all three legal-page headers and PNG favicons, and the current helper's single recommended download.
Legacy dark/light API endpoints remain for existing clients. Form packs contain `app-icon.png` and complete
website assets, including that exact PNG and an ICO with six nearest-neighbor frames (16 through 256 pixels).
The local `/legal/` allowlist serves those images with their proper types; no credentials or app data are exported.

Published the narrow branding correction to existing `gh-pages` as
`80a6a3f4782de64fed88a06d9db54533de4869bd`. The site's existing product/legal text, `.nojekyll` and TikTok URL
verification file are unchanged. [Pages run 39347822850](https://github.com/landryschreiner33-coder/ClipForge-AI./actions/runs/39347822850)
succeeded for that exact revision and reports https://landryschreiner33-coder.github.io/ClipForge-AI./ . All eight
published source files were read back byte-for-byte. Direct live-site HTTP is unverified because `github.io` is
outside this environment's network policy; exact-source browser checks and successful deployment were verified.
No desktop reinstall is needed to correct the public website. The existing readable installer remains pinned to
its earlier app revision; this checkpoint does not rebuild or replace it. The owner can use the exact published
`app-icon.png` in TikTok Basic information and resubmit. TikTok approval remains its own decision; no portal
submission, real account connection, scope change or post was performed.

**Validation:** TypeScript/production build passed (5.11 s). Final affected Python suites: 41 passed in 6.89 s.
Twelve Chromium checks cover all three public pages at desktop/mobile widths in light/dark mode; the built app
header, favicon, helper preview and download also match the exact submitted PNG. All six ICO frames match nearest-
neighbor canonical pixels. The broad fast run completed with 1,489 passed, one obsolete website-readiness fixture
failure and 17 slow deselected in 537.24 s. It had already collected the older fixture, which forbade added assets
and all image elements. The corrected fixture permits only the bundled canonical image and passes in both the
41-case affected-suite rerun and a final individual rerun. All 326 frozen code/test/build/website hashes match.
Exact published source readback and successful Pages deployment were verified. The media/Autopilot pipeline and
dependency/bootstrap files are unchanged; slow media and broad browser suites were not rerun for this branding
correction.

## Latest continuation: Windows Python selection and safe environment recovery

Date: 2026-10-19 (America/Chicago). Base: `fcd48aecece759ed676d871a9282d81b83f0ab92`, on
`codex/brain-graph-quality-discovery`. The owner reports pip cannot find a matching CTranslate2 distribution.
The screenshot alone does not identify the actual runtime, architecture or package index; do not assign an
unverified cause. Current CTranslate2 CPython 3.13/3.14 Windows AMD64 wheels exist. The app's supported Windows
policy is standard 64-bit CPython 3.12, then 3.11 (`win-amd64`, non-free-threaded); native ARM64/32-bit lack the
applicable wheel.

`start.bat` probes candidates by executing new standard-library-only `windows_bootstrap.py --check-python`,
instead of selecting a generic latest `py -3`. The readable source installer performs the same authoritative
check before app/profile writes and forwards the verified executable in `CLIPFOUNDRY_BOOTSTRAP_PYTHON`.
The app rechecks that interpreter and the actual `.venv` interpreter. Compatible `.venv` is reused; an
incompatible/unverifiable one is preserved as unique `.venv-backup-*`, then a fresh supported environment is
created and verified. Creation failures preserve partials under `.venv-failed-*` and roll back the old environment
where possible. Setup refuses to replace a known active environment and never kills its processes or deletes old copies.
If no candidate qualifies, install official 64-bit Python 3.12 side by side, then reopen; no automatic global
Python installation/removal, PATH/registry/security changes or owner-data deletion is introduced.

Brain, accounts, clips and the data profile are not migrated or rewritten by this repair. GPU/dependency pins,
frontend, media/rendering and submitted-video/Autopilot behavior remain unchanged. The installer artifact is pinned
separately after this source checkpoint; preserve managed-profile revision history and the historical blocked EXE.

**Validation:** Full fast regression suite: 1,489 passed, 17 slow deselected in 527.16 s. All 203 frozen source/test/bootstrap/dependency hashes matched. The 38 focused bootstrap checks passed in 3.54 s, including real disposable-host venv creation, reuse and replacement, preserved dependency markers/data, failure rollback, active-process and concurrency guards, exact runtime checks and read-only probes. A 19,230,360-byte CPython 3.12 Windows AMD64 CTranslate2 4.8.3 wheel was downloaded and its SHA-256 matched PyPI (b5daf0758d522a422c76e53eb02ce9f42465a9aba938a86b27249fb5db2571b9). No dependency/GPU pins, app pipeline or frontend files changed; all 17 previously browser-tested built files retain their hashes. The previous 17 media and 59 browser results apply to unchanged scopes and were not rerun. The readable setup is separately pinned to this exact app commit; its delivery proof records installer/helper tests, full source hashes, managed-release history and immutable download readback. A Linux cross-platform full pip dry run evaluates host markers and is not native Windows dependency
proof. The prior submitted-video release's 17 media and 59 built-browser checks below remain historical evidence
for unchanged scopes, not reruns for this setup repair. Native Windows CMD/process inspection/venv creation,
owner installation/RTX3050, real uploads, Defender acceptance and a 24-hour soak remain unverified.

## Latest continuation: submitted videos, Brain-guided creation and automatic YouTube upload

Date: 2026-10-19 (America/Chicago). Base: `ab666fd5f2c4ca9c84a4fe9a2e874bc852437231`, on
`codex/brain-graph-quality-discovery`. The owner replaces unreliable video finding with a link/file they supply,
then wants Brain-guided creation and automatic upload without per-clip approval.

Default `autopilot_input_mode=submitted` suppresses periodic/queued discovery and automatic watched-folder
admission. Existing sources, media, keys, Brain and post history remain. A one-time migration records this default
for old profiles without overriding a later explicit choice. Optional discovery is still selectable in Advanced.
Missions offers **Make & upload clips** and **Make clips only**, with actual per-input counts and hold reasons.

The upload action requires the actual connected YouTube channel, confirmed audience, genuine kids answer, source
reuse basis and one explicit checkbox. `source_submissions` stores its exact wording/options separately from
Brain/standing consent. A supplied file is copied to `data/submitted/<id>/`; acquisition binds original SHA,
project and current terms/credit. Accepted source/request creation is atomic; the scheduler recovers only an
unstarted enqueue gap, never deliberate cancellation. Retention preserves source rows referenced by submission
audits while clearing stale API metrics/cache and ordinary unused discovery rows. Re-adding an existing video
cannot grant old backlog access.
Guarded links need no search key; private/protected/unavailable/live media is not bypassed.

Relevant supported Brain notes and example preferences are consulted with source/spoken context and Settings
fallback, retaining explicit editor overrides. Raw notes/examples stay local; unsupported references and measured
example lengths are described honestly. Submission/reuse text never becomes Brain guidance or ownership/license.
Each qualifying new YouTube post gets an exact-file/payload approval labeled `by=submission`, tied to its input
request. It may schedule/dispatch despite broad scheduling/publishing/YouTube toggles being off, without changing
those globals. Old backlog and later inputs remain unapproved; local-only inputs create no automatic posts;
TikTok keeps per-post consent. Stop, Pause publishing, cancellation, source/hash/account/audience/terms drift,
credit, final quality, quotas/waits and active/uncertain upload recovery remain binding. Manual edits can require
manual review rather than being overwritten by automatic approval.

The prior downmix-before-normalization, final peak control, first-track and delayed/gapped-clock fixes remain.
Actual synthetic FFmpeg/AAC and exact fake-upload checks exercise the new path, including Brain-guided caption
rendering and restart without duplicate uploads. A limiter cannot reconstruct preexisting source distortion.

**Validation:** Final full fast suite: 1,451 passed, 17 slow deselected, in 676.07 s. Final full real-FFmpeg/synthetic-media and restart suite: 17 passed, 1,451 deselected, in 934.97 s. TypeScript and the production build passed (10.00 s). All 59 final built-browser checks passed in 161.55 s. The final fast suite used 198 frozen Python source/test files. All production and selected media-test sources stayed unchanged during the full media run; 81 frontend source and 17 built-file hashes stayed unchanged through the final browser checks. A deselected fast retention fixture's timestamp setup was corrected before the final fast run; the media run's production/selected sources were unaffected. Focused checks also passed: 60 submission/consent, 79 final status/routes/legacy readiness, 29 advanced-route/legacy, 119 legacy intake/scheduler/publishing, three new actual-media and 26 legacy audio/quality and nine retention checks. The three new media cases use relevant saved Brain guidance, real caption/AAC rendering, exact fake-upload bytes and restart without duplicates, including the broad YouTube switch off and TikTok enabled. Earlier full attempts were interrupted before the final route/status/retention corrections and are not final evidence. Tests use isolated profiles, synthetic media and fake platforms only. The readable source setup is pinned separately to this committed app tree with the tested frontend manifest; its delivery verification records exact archive hashes and source revision.
No owner Windows/profile/RTX3050, real YouTube transcode/account upload, Defender acceptance or 24-hour soak has
been verified. Prior release results below are historical, not proof for this new checkpoint.

## Latest continuation: failed search keys and separate post-only reuse records

Base: `0c2729d0a1e148e22da5bcdbd6db4ccb490dafa7`, on `codex/brain-graph-quality-discovery`.
The owner reports no clips and says both search keys fail; exact provider errors and owner-PC access were not
available. They confirm permission text appears only on the clip's approval/reuse details. That already belongs
to the exact post, not Brain; no automatic permission-to-knowledge leak was found or claimed.

YouTube discovery refreshes rejected same-account OAuth once, counting requests and preserving waits. Key errors
distinguish invalid/restricted keys and disabled APIs without reflecting credentials. No automatic credential
substitution occurs. A request lock protects the discovery allowance against concurrent probes. Copied outer key
whitespace is trimmed; new saves reject extra lines/control characters safely. Tavily server waits stay durable.

Settings → Integrations → Search connections adds explicit saved-connection tests. YouTube makes an uncached
general-quota read (one more if sign-in refreshes); Tavily reads `/usage` without running a search. Strict responses,
bounded repeated/concurrent checks, provider waits and credential-current results apply. GET stays read-only.
Only safe results/times and a private credential fingerprint persist. The tests cannot prove search quota,
downloadable originals or publishing readiness; no guaranteed-zero-credit claim is made for Tavily `/usage`.

Missions/health distinguish each provider's waits and review mode from reuse blocks. Failed configured searches
degrade health while independent sources continue; removed keys stop adding stale health failures. Forms/details
say reuse answers stay with those posts and never teach Brain. Single/bulk and learning regressions verify that
ordinary owner notes, all Brain evidence and exact-post approval remain separate and intact.

**Validation:** Final full fast suite: 1,373 passed, 14 slow deselected, in 755.18 s. Final full real-FFmpeg/synthetic-media and restart suite: 14 passed, 1,373 deselected, in 945.34 s. Final TypeScript and production build passed (5.17 s). All 51 final built-browser checks passed in 167.41 s, with all 17 built-file hashes unchanged. Focused provider verification: 77 passed in 7.83 s; focused diagnosis/health/phone: 88 passed in 11.26 s; independent saved-search/Brain separation checks: 113 passed in 22.43 s before the final wait-order correction, then 53 passed in 4.06 s including both same-key full-server-wait regressions. All 261 frozen production/frontend/Python-test hashes remained unchanged through final verification. Tests used isolated data, synthetic media, MockTransport and fake platforms. No owner keys, Windows profile/RTX3050, actual search-service account, real upload, Defender acceptance or 24-hour soak was verified. Permission answers were already post-only; the update clarifies and verifies that boundary.
Owner Windows/profile/keys and actual provider access remain unverified. Preserve prior fixes and managed-install
history; pin the source delivery only after the final commit and tested frontend export.

## Latest continuation: audio distortion, comments, ongoing search and live/Windows recovery

Base: `11bdb43523f9b01e82590d2dd9e67473d323c88d`, on `codex/brain-graph-quality-discovery`.
The owner confirmed distorted audio, comments disabled on some YouTube uploads, discovery stopping, and two
screenshots of Windows Proactor reset cleanup and split/ended live capture failures. The concrete Claude
continuation guide is [CLAUDE_HANDOFF.md](CLAUDE_HANDOFF.md); preserve its verification limits and owner-PC follow-up.

Real audio reproductions found default surround downmix and boosted gain clipping, lost delayed starts/gaps and
different transcription/render tracks. Downmix now precedes normalization, final latency-compensated peak control
follows gain, timestamps become real silence before processing and first-track selection is consistent. Existing
renders/uploads/transcripts are not silently rewritten. A limiter cannot restore distortion already in a source.

Made-for-kids values are strictly real booleans through all upload paths; malformed legacy/API values wait for
a real answer. UI explains kids/Private comment restrictions, returned YouTube audience flags are retained without
extra requests, and unknown comment availability points to Studio. No owner answers/visibility are auto-flipped;
the upload API has no enable-comments control. Provider-specific waits, capacity-aware recurring checks, bounded
five-page cursors and free feed refill prevent unrelated services and saved signals from stalling. Existing
encrypted YouTube/Tavily keys and free-only allowances are visible in Search connections; no new provider added.
When a busy queue drains, the persisted search deadline shortens as well as its interval; polling does not extend
the shortened deadline or alter an individual provider's wait.
Health and phone status use a pure cadence calculation. Only the periodic host updates deadlines/migration;
viewing status cannot change scheduling state. Existing phone database-unchanged checks remain binding.

Split HLS uses one guarded local A/V relay with common clocks/shared budgets. Empty ended platform captures have
finite, restart-safe public-archive recovery; partial timelines/project identity/single handoff remain intact.
The Windows handler finishes only the known native 10054 stdlib cleanup, supports differing Python detach
signatures, preserves other errors and restores handlers. Phone's own lifespan starts no desktop workers.

**Validation:** Final full fast suite: 1,278 passed, 14 slow deselected, in 579.81 s. Real-FFmpeg/synthetic-speech media and restart verification covered all 14 scenarios across two runs: the full attempt passed 12 with 2 repeat-discovery timeouts (1,274 deselected, 1153.68 s); after correcting only the compressed-clock fixture's discovery-list cache expiry, both private/public repeat scenarios passed in 374.57 s. This was not a single all-green full-media run. Production cache/quota policy and all real render, final-report, exact-upload-byte and restart assertions were unchanged by that fixture correction. Final production build: 10.32 s; TypeScript passed. All 43 final built-browser checks passed in 93.25 s, with all 17 frontend hashes unchanged. Focused independent bugfix verification: 73 passed in 32.22 s, including measured encoded mono/surround audio, exact fake-upload bytes, real split-HLS synchronization and real asyncio cleanup compatibility. Windows/phone focused verification: 63 passed in 10.25 s; earlier discovery focused: 89 passed in 11.12 s. The final queue-drain deadline correction and surrounding discovery checks passed 61 tests in 9.13 s. Final comments/search checks after the current-label correction: 47 passed in 22.85 s. The final read-only health/phone/search correction passed 77 checks in 16.64 s, with database-unchanged assertions intact. The complete media run used the final audio/live/publishing code, preceding only the pure health-cadence refactor and its four new fast tests; all 39 media-scope source hashes remained unchanged. That refactor is covered by the final full fast run and 77 focused checks. The earlier interrupted suites preceded final deadline/returned-label corrections and are not final evidence. No real owner Windows profile/media, RTX3050, live provider key, account upload or 24-hour soak was tested.
No owner Windows profile/media, native Windows/RTX3050, real provider key/account upload or 24-hour soak was tested.
Pin source delivery only after the final commit/build manifest; preserve earlier managed profile history and EXE bytes.

## Latest continuation: fast selected-post approval and consistent Brain use

Base: `ec20aec76825a284393af00d812ec4a08a8beca3`, on `codex/brain-graph-quality-discovery`.
The owner requested fewer navigation/typing steps and mass approval. Queue now provides inline video/full-text
previews, Quick approve, selection of visible YouTube posts (up to 50), and Approve selected. A fixed batch preview
shows actual posts, account, audiences and times. Reuse presets or one custom basis cover only the selected posts
that need assertions; one explicit combined consent covers the reviewed files/text/audiences/reuse. Missing
made-for-kids answers may be filled once, while existing answers stay intact. Single-post review shares these
presets and one combined consent. TikTok retains its individual platform review.

The owner also reports saved Brain notes/examples not affecting clips. Source title and spoken-word topic context
now follows candidate generation (including cached/resumed and live paths), ranking, blueprint and render. Tagged
example length is consulted after transcription, while per-candidate priorities avoid leaking unrelated transcript
topics. Natural caption declarations and named example feature fields are recognized. Bad-example observations
no longer promote unwanted traits; explicit corrective preferences remain usable. Settings fill unspecified
choices, owner duration bounds remain binding and explicit editor overrides win. Public lesson metadata/UI show
recognized effects and measured example length; unsupported material stays searchable without changing edits.
No video appearance recognition, new external model calls, raw-note transmission, old-media rewrite or publishing
permission is implied. The earlier docs/AUTOPILOT.md Brain-approval instructions were corrected to match save activation.

Batch previews are bounded in-memory snapshots with ten-minute validity, at most 64 entries and no future-post
grant. Expired/old entries are evicted on later previews or app exit. Confirmation rechecks actual bytes/version,
current source terms/credit, row/text/options, account/audience, posting mode/timing and passing final checks.
A final SQLite write guard prevents an active job/state change from being overwritten, with hashing outside the
write lock. Changed, blocked, unchecked, replacement or active/uncertain-upload work is skipped with a reason.
Each success receives its own manual approval and exact-post assertion if needed; repeated identical requests
return their prior result. No source is marked owned/licensed by a preset. Future arrivals are never selected
automatically. Partial success keeps failed selections for review and cannot silently retarget or rewrite posts.

Review-before-publishing stays the default. Required credit, file/media/grounding checks, explicit account/audience/
kids choices, exact approval binding, platform waits and duplicate protections remain. Selected due posts can start
after approval; disabled dispatch still waits for Publish now. The readable source setup must preserve verified
same-user managed profiles and the entire earlier application; do not recommend the blocked EXE or change security.

**Validation:** Final full fast suite: 1,195 passed, 11 slow deselected, in 739.22 s. Final real-FFmpeg/synthetic-speech media and restart suite: 11 passed, 1,195 deselected, in 1024.81 s. This includes exact selected-post fake uploads/restart and two actual Brain-guided/owner-overridden caption renders with persisted provenance. Final production build: 9.44 s; TypeScript passed. All 31 final built-browser checks passed in 95.78 s, with all 17 frontend hashes unchanged. Focused checks: 42 bulk, 19 independent approval audit and 86 Brain/context checks passed. Browser fixture wording/details visibility and async readiness were corrected before the final run; earlier interrupted or fixture-correction runs are not final evidence.
No owner Windows profile, native Windows/RTX3050, real account uploads or 24-hour soak was accessed or verified.

## Latest continuation: local schedules, owner reuse review and manual approval

Base: `d0b7102e8273cee068531da554c8d83f3fa43f8f`, on `codex/brain-graph-quality-discovery`.
The owner now wants preparation and scheduling followed by individual reuse review and approval.
`autopilot_review_before_publish` defaults on for new and existing profiles that have no explicit choice.
Accessible unblocked sources can enter the bounded quality-first queue without recorded reuse coverage;
their rights status remains truthful. Exact-file and grounded-text checks still precede local posting plans.
All new plans wait for owner approval. Standing YouTube permission is suspended in review mode. Future explicit
mode choices persist; approved-post dispatch, source limits, audience choices and other saved settings stay intact.

Queue shows proposed times with Needs review, separately from approved uploads. Review drafts do not expire after
48 hours. Uncovered posts additionally require an owner reuse statement and basis, bound to the exact post/source,
current terms and required credit, account, platform, audience, file/version, text and options. This assertion does
not create source ownership/license or cover another post. Required credit cannot be waived. Changes invalidate
the assertion and approval. Source-sound uncertainty is reviewable; physical-media failures still block use.
After explicit approval the existing scheduled dispatcher or Publish now can upload, with original audience,
made-for-kids/platform choices and exact-file, quality, duplicate and Retry-After checks.

Old automatic approvals for provably unstarted transfers return to review atomically with their payload, time,
privacy and publication identity preserved. A queued job cannot bypass the review guard. Retry and confirmed
not-published recovery require new owner approval in review mode. Active or uncertain outcomes keep their original
session; unknown outcomes use account-bound readback before local policy changes. Existing published videos and
saved media remain intact. Separate manual Publish cannot borrow a scheduled post's assertion.

If review mode is explicitly disabled, recorded coverage and separate standing YouTube permission again govern
automatic approval. Tests for that historical contract explicitly select it; new `test_review_*` suites exercise
the actual default. The inspectable Windows source setup remains the delivery route; preserve all verified prior
managed profiles and do not recommend the blocked EXE or change antivirus settings.

**Validation:** Final full fast suite: 1,112 passed, nine slow deselected, in 529.54 s. Final real-FFmpeg/synthetic-speech media and restart suite: nine passed, 1,112 deselected, in 879.93 s, including the new review/owner-confirmation/exact-byte upload/restart loop. Final production build passed in 8.79 s; 12 built browser checks passed in 40.23 s, with all 17 frontend file hashes unchanged. Focused checks: 95 publishing/reuse checks; 64 scheduler/public/manual checks; final 46 review/current-terms checks; 107 legacy recovery checks; and eight final independent audit/fixture checks. The initial full fast attempt found an older fixture approving an unverified channel claim; its corrected exact-video verification retains all connection, quota, hash, explicit-block and no-upload assertions. Earlier full attempts were stopped before final corrections and are not final suite evidence.
No owner Windows profile, RTX3050, real social upload or 24-hour soak was accessed or verified.

## Latest continuation: continuous eligible uploads and real Brain/manager activity

Base: `718358f30110ab871e21059177f83ccd9ea3d3a9`, on `codex/brain-graph-quality-discovery`.
The owner confirmed Missions reports missing reuse permission for the finished clips. That is a real posting
hold. Automatic broad discovery now defaults to uploadable sources for a connected destination, with verified
own/agreed channels before broad quota use, actual Creative Commons metadata checks and fixed source guidance.
Explicit public local imports remain available. Inactive old local-only picks cannot starve eligible work;
history and completed media remain saved. No permission is inferred from public availability or Brain prose.

App source/day, unique-clip/day and platform daily caps default to zero (unlimited), with 0–24 posting hours and
no forced gap. Work remains bounded per search and by active queue capacity, quality floors, API/cost allowances
and platform responses. A one-time recorded volume amendment updates prior app limits and existing YouTube
permission without changing its channel/audience/kids answer or creating a missing grant. Future explicit caps
persist. Historical posts/times and Private visibility remain unchanged. Continuous planning picks the earliest
eligible time; old past-due permission holds and lost replacement slots now recover. A reported platform zero
holds even an already-approved post until capacity returns, without touching an existing upload session.

Final checks bind to current reuse terms and required source credit. Stale terms, including a previously failed
sound-rights check, request bounded fresh checks. Required credit is checked in the actual upload payload;
missing credit returns an old post to editable review without replacing its text/privacy. Owner correction and
approval can update a provably unstarted publication snapshot, retaining its ID; started or uncertain transfers
keep their session/payload. TikTok mode and current features follow that unstarted approved snapshot too.
Manual edits, canceled jobs, existing post approvals and protected uploads cannot be silently repackaged.

Real saved-guidance use in selection, ranking, plans and renders records count-only consultation events.
Preview/graph/status reads remain read-only; disabled/empty/paused/canceled work emits no fake activity.
Brain consultation is distinct from mature-results learning, whose thresholds are unchanged. Fresh report and
checkpoint paths now pass through the responsible manager and boss, with linked real next work dispatched
through its manager. Explicit empty paths suppress inferred transfers. Newer held/rejected checkpoints cannot
reuse older approvals. Managers' own work/errors and unrelated workers keep priority; quiet rooms say why idle.
Pause, Reduced motion, hidden/offline/history guards and lounge recreation remain intact.

**Validation:** Final fast suite: 1,047 passed, eight slow deselected, in 556.14 s. Final real-FFmpeg/synthetic-speech
media/restart suite: eight passed, 1,047 deselected, in 836.38 s, including Public/Private fake uploads,
restart and live recovery. Final production build passed in 6.16 s; 11 final built browser checks passed
in 94.42 s, with all 17 frontend hashes unchanged. Earlier 12 choreography checks passed in 209.87 s;
six department, three motion and six lounge checks also passed. Final focused reuse/publishing checks:
93 passed in 90.79 s; public/manual publishing: 34 passed in 40.59 s. New reuse-context: 26 passed in
9.36 s. Independent continuous checks: 12 passed in 9.28 s; broader review batches: 60 and 83 passed
(one slow deselected), plus 17 packaging/artifact checks. Root phone checks: 56 passed in 9.06 s.
The first complete fast run passed 1,037 and exposed ten old fixtures assuming optional charts,
three-source plans or reports made before terms were attached; corrected cases retained all access,
Retry-After, permission, byte/version and quality assertions. Earlier office locator/route fixtures
were corrected to match actual consultation IDs, room-sign selection and manager paths. Controlled
screenshots/GIF are in design/robot-office/continuous. No actual owner profile, Windows/GPU or real
platform upload was tested.

No actual owner profile, Windows/RTX3050, real social upload or 24-hour soak was accessed or verified. The new
source ZIP must be pinned only after final tests/build and preserve verified earlier launcher-created profiles.
Do not recommend the blocked EXE or change antivirus/security settings. App publishing consent and exact-file,
reuse, quality, duplicate and Retry-After guards remain required.

## Latest continuation: finished clips reach YouTube scheduling

Base: `987ebb288ae9097bedbd80d0adee2b3c05c4271f`, on `codex/brain-graph-quality-discovery`.
The owner reported an all-day YouTube-only run with finished clips, no schedules/uploads and no Needs you.
The owner's actual Windows database was not accessed. Isolated reproductions identified and fixed these paths:

* Parked reuse-permission/file waits filled the six-find backlog forever; high-estimate local-only finds could
  take every daily attempt before reusable media. Bounded workable/parking lanes retain saved history and daily
  budgets while giving accessible, covered candidates priority. Explicit input and quality floors stay intact.
* Analysis waited for every render before fingerprint/package handoff. Each completed recorded output now hands
  off before any priority yield. Scheduler/maintenance recover bounded older proven outputs exactly once, using
  saved validated plans, selection evidence and existing files. Failed/canceled packaging and manual edits remain
  untouched. Live replacements finish their decisions first. Cancellation/Pause are rechecked after fingerprinting.
* A stored consent for a different channel/audience could suppress approval reminders even when unusable.
  Availability now controls reminders; existing Private plans retain valid original permission. Private automatic
  consent also requires a confirmed, non-local destination. Setup exposes audience confirmation and separate
  automatic YouTube permission together, filtered to connected platforms, with no automatic grant or audience change.
* Read-only posting readiness and derived setup warnings show post text, final checks, local-only rights and
  scheduling/permission holds even if the scheduler never wrote an action item. Recent stage counts sample at most
  200 finished automatic clips; the total counts all. An approved item without a posting time is a wait, not a schedule.
  Latest preparation state wins over older failures. Phone attention retains its fixed-description whitelist.

**Validation:** Final full fast suite: 958 passed, eight slow deselected, in 489.73 s. Final real-FFmpeg/synthetic-speech
media and restart suite: eight passed, 958 deselected, in 695.71 s, including Public/Private and live recovery
loops. Final production build passed in 3.98 s; seven built-interface browser checks passed in 43.6 s. All 17
tested built-file hashes match. Final focused handoff/readiness/simple-page checks: 88 passed in 24.79 s.
Discovery focused checks: 99 passed in 19.36 s; four new behavior regressions fail on the original source.
Scheduler/consent checks: 73 passed, one slow deselected, in 78.53 s. Independent review found the late-
cancellation race; its three corrected regressions passed and no material findings remain. No real owner data,
Windows/RTX3050, platform upload or 24-hour soak was tested.
An independent review's late-parent-cancellation finding was fixed and its three regressions pass. Earlier test
runs were stopped before that correction and are not final suite evidence. One UI test had an in-flight mocked
response disposed at teardown; seeding its status fixture before browser polling resolved it. The old plain-text
test now projects the visible posting title/detail rather than treating a machine stage enum as user text.
No real upload, account-permission change, Windows/RTX3050 execution, owner-data inspection or 24-hour soak is
claimed. The installer retains verified prior managed profiles; ordinary unknown ZIP profiles are not adopted.

## Latest continuation: private phone status dashboard

Base: `4838aa897e59b68a1365dd7ed7f4d60f52dfcc8c`, on `codex/brain-graph-quality-discovery`.
The owner asked to check ClipFoundry's progress from a phone. Settings → Integrations → **Check from your phone**
now controls an optional, default-off companion listener. Tailscale is the recommended private connection;
trusted home Wi-Fi is also supported, with an explicit unencrypted-HTTP explanation. The app never installs
Tailscale, signs into it, changes a firewall/router or rebinds the desktop listener. Literal private IPv4
binding and actual CLI desktop-port tracking preserve listener isolation, including restart/custom-port cases.

The separate FastAPI app serves only three phone assets, single-use pairing and an authenticated status snapshot.
Owner-only localhost controls enable/disable, issue a five-minute eight-digit code and revoke all grants.
Pairing attempts are rate limited globally and per peer. At most eight random device keys last 90 days;
SQLite stores only their SHA-256 hashes. Codes/keys never enter URLs or logs. Normal restarts retain grants;
disabling stops access, revoking removes grants. The phone uses session storage by default, opt-in local storage
for Remember this phone, and clears its displayed status/key after revocation/expiry. Disconnect clears that
browser only; the PC's Unpair all phones revokes copied keys too.

The mobile dashboard reports actual current work, measured/unknown progress, local-day unique clip counts,
separate platform-post counts, next planned post, posting queue and health statuses. It uses the desktop attention
policy, suppresses routine retry alerts and maps only fixed descriptions for derived account/worker/sleep holds.
No media, raw diagnostics, credentials, account identities, Brain text or desktop controls are exposed.
Polling pauses in the background, shows stale/offline readings plainly, backs off and resumes on reconnection.
Desktop setup ignores old polls after newer actions. [Setup and architecture](docs/PHONE_DASHBOARD.md).

**Validation:** Final full fast suite: 869 passed, eight slow deselected, in 386.91 s. Final focused phone tests: 55 passed in 9.03
s; 75 existing local-guard/office/Autopilot regressions passed in 30.43 s before the final attention refinement.
Final built phone browser suite: ten passed in 12.6 s. Final built desktop setup/race checks: two passed in 27.6 s.
Production build passed in 3.85 s; all 17 built-file hashes were recorded. No actual phone, Windows/Tailscale
connection or real account was tested.
The initial complete suite passed 865 checks before the attention-policy refinement. Independent review found
and prompted fixes for that refinement and an older-poll/new-action race. Media/Autopilot handlers are unchanged;
the slow media suite was not repeated for this feature. Native Windows, actual phone browsers, Tailscale account
connectivity, Windows firewall behavior, RTX3050 and real platform accounts remain device checks.
The bundled installer is pinned and integrity-checked separately on `codex/clipfoundry-one-click`.

## Latest continuation: automatic Brain guidance and useful integrations

Base: `28aee85b4ef239584da296cec900bc3d8dde4399`, on `codex/brain-graph-quality-discovery`.
The owner requested all saved Brain material to participate automatically, combined with Settings, and inactive
integration placeholders removed. This supersedes the older separate Brain-approval workflow below; publishing
consent and platform restrictions are unchanged.

Enabled saved notes, document text, explicit preferences and described examples are consulted for new clip
selection and rendering. A bounded local interpreter recognizes caption choices, continuous/safe-cut pacing and
known hook/payoff/context/ranking priorities. Explicit controls win over prose; instructions precede examples,
then references, newest saved item first. Settings supply missing choices. Good example durations blend with the
owner's original target by n/(n+3), capped at 60% and constrained by configured length limits. The original target
is retained between source/candidate stages so the hint cannot be counted twice. Selection provenance is copied
and merged by knowledge ID/revision, without mutating another clip's saved decision. Existing clips/posts remain
intact. Manual per-clip overrides win over Brain caption choices. Disabled/paused guidance stays inactive.

Brain shows recognized choices, ranking priorities, automatic activation and unsaved-draft status; it has no
separate approval button. Unrecognized material remains searchable, with actionable help. Raw notes/examples
stay local, no prose executes, and videos do not teach visual appearance or fine-tune a model. Only fixed known
priority labels accompany the existing excerpt sent to an already selected/authorized text AI. The NVIDIA
sending explanation and Privacy page describe this.

Integrations now lists YouTube, TikTok, Tavily, Wikimedia Commons and NVIDIA. Twitch, Kick, Reddit, X, Instagram,
podcasts and Google Trends placeholder cards are removed. Real connection, scope, audit, consent and quota holds
remain visible; no account permission or posting behavior was changed.

**Validation:** Final full fast suite: 814 passed, eight slow deselected, in 349.16 s. Final focused Brain/provider/blueprint/artifact regressions: 96 passed in 43.45 s. Actual-FFmpeg/synthetic-speech media/restart suite: eight passed, 811 deselected, in 710.71 s before the final example-blending/provenance review fixes; those final fixes are covered by the final 814/96 runs. Final controlled browser batch: eight passed in 45.5 s against the final built interface. Build passed in 6.44 s. No real uploads, accounts, Windows/RTX3050 execution or 24-hour soak were tested.
Early runs exposed old approval/placeholder assertions and a malformed new sentence fixture; these were
corrected without weakening write/local-only/platform guards. The first media run lacked the existing portable
speech fixture tool (three failures, four skips); the corrected environment produced all eight passes above.
The earlier 811-check run preceded three additional regression cases; it is not the final complete count.
The standalone local diagnostic collector is separately verified with portable PowerShell: GET-only/custom-port
snapshot, strict privacy whitelist, missing-app and invalid-port behavior. Native Windows remains unverified.
The installer carries this exact source snapshot and has a separate integrity record.

## Current scope and branch

Current work is on `codex/brain-graph-quality-discovery`, starting at
`8999e5fb29a0e1455d8fccff4037d6f089f9091b` from the default branch. PR #14 is merged. Its draft/unmerged notes and
test counts below describe historical checkpoints and are superseded by this branch's status.

The owner requested a finished app and Windows installer, simpler TikTok app setup, a visible Brain graph and
quality before quantity in discovery. Settings now includes **Help me fill out the TikTok app form**: copyable
details, the actual Desktop callback for the current local port, two 1024×1024 PNG icons, scope explanations and
a form-pack ZIP with local draft website/legal pages. Inbox uses `user.info.basic,video.upload`; Direct Post uses
`user.info.basic,video.publish`; optional statistics adds `video.list` and Display API. Applying choices, saving
Settings and reconnecting are separate steps. Existing permission choices are preserved until explicitly changed.
The helper prepares a draft only when opened. It checks URL format locally, does not submit a review or deploy pages,
and excludes app credentials,
tokens, account identities and owner media from the export. TikTok's personal-tool eligibility, Sandbox limits,
per-post consent and private-profile restriction still apply. See [the setup guide](docs/TIKTOK_APP_SETUP.md).

Brain now opens an interactive graph with saved notes, approved preferences, examples, shared topic tags,
recorded clip influence and result readings. Selecting a note or evidence opens its stored record and provenance.
Category/tag edges organize knowledge; influence edges identify the applied revision. Positions and glow are decorative,
not hidden AI thoughts. The graph is bounded to 160 saved items, 32 topics and 48 recent evidence records; list,
editor, history and full knowledge export retain access to the other saved data. **Add note** starts a simple note,
with an optional title derived from its text. **Teach preference** presents supported choices used automatically when saved enabled; the latest
continuation above supersedes its previous separate review/approval step. Documents and examples do not fine-tune a model.
The editor sends its displayed revision; stale edits return HTTP 409 and preserve the draft until explicit reload.

**Missions → Permissions & sources → Quality before quantity** enables focused broad-search discovery by default:
three new candidates per pass, six unfinished automatic search picks including `needs_rights`, one known creator
per pass and two per topic. The existing daily attempt budget remains three by default; weak outcomes do not
justify more attempts to fill the clip target. Explicit links, chosen folders/channels and manual work retain
their existing behavior. Scores and expected clips remain estimates until full analysis and final-file checks.
Optional Tavily setup explains its free 1,000-credit monthly plan without a card; saving a new key with the free
option explicitly sets the app allowance to 1,000 and its monthly spending limit to $0. Other settings are retained.

**Current validation:** the final full fast suite passed **804 checks**, with **8 slow cases deselected**, in
**429.01 s**; Python source is unchanged. All eight media cases are covered by seven initial passes (965.89 s,
one environment disk-capacity failure) and the unchanged live case passing in 48.81 s on workspace temp storage.
Final browser coverage is **52 unique checks across runs**: the initial 44-case batch had 42 passes/two failures
in 12.7 min; the final 11 changed-UI plus eight strict read-only Settings cases all passed in 1.1 min; the complete
loop passed in 7.0 min. Ten cases overlap between the initial/final batches. Lazy helper preparation fixes the
background preview request; one stale Public-visibility assertion was maintained without changing read-only
flows. Recorder/temp-storage environment fixes preserved the full loop. The latest build passed in **4.06 s**;
all 14 tested/captured file hashes match. Current graph previews came from the final run. Earlier interrupted
outputs are not final passes. Installer integrity is tracked separately on `codex/clipfoundry-one-click`.
Final results are recorded at the top of
[IMPLEMENTATION_STATUS.md](docs/IMPLEMENTATION_STATUS.md). See the
[desktop/mobile/empty graph previews](design/brain-workspace/README.md) for controlled-data provenance.
Windows execution, RTX 3050 CUDA/NVENC, real platform accounts/grants/visibility and an actual 24-hour soak remain
unverified. No real upload, account-permission change or website deployment is claimed by this checkpoint.

## Historical PR #14 scope and branch

The owner authorized merging PR #14 after one final pass on October 11. This pre-merge checkpoint follows
`51984a3`; check GitHub for the actual merge state. Independent review found no material blocker, and the
14 browser-tested frontend files still match their recorded hashes. The fresh targeted run passed 105 checks
and exposed one test-only race: inspecting log backups during an active rename. The test now takes the logging
handler's lock for its file snapshot; production code is unchanged. All 16 launcher checks passed in 0.72 s.
The fresh full fast suite passed **757 checks**, with **8 slow cases deselected**, in **301.90 s**.
The earlier real-media, browser, build and actual-app restart evidence remains applicable. Windows, real accounts
and an actual 24-hour soak remain unverified; merge authorization does not change those limits.

The preceding unattended-Public checkpoint started at `61f6042` on the then-draft/unmerged PR #14.
Work ran October 10–11.
The owner requested autonomous all-day Public publishing from a personal setup. Designed unattended YouTube operation
keeps explicit Public setup, account/visibility-bound standing permission, reuse eligibility, exact-file checks and
honest readback. Existing Private schedules stay Private; Public results need no Studio invitations. Midnight **0** now
survives scheduling/consent reads, so **0–24** covers the full day without changing daily limits.

Official YouTube `videos.insert`/`videos` documentation updated October 8 and freshly checked October 10 permits
Public uploads from unverified projects. The obsolete project-audit Public gate is removed; API audit concerns
quota increases. OAuth publishing status is separate: External Testing YouTube refresh grants expire after seven
days; choose Production, then reconnect. Personal use may be exempt from OAuth verification, but authorization can
still be revoked. TikTok retains eligible-app/per-post consent limits; a private TikTok profile cannot offer Everyone.
See [current platform evidence](docs/PLATFORM_CAPABILITIES.md) and [unattended setup](docs/UNATTENDED.md).

The optional `run-unattended.bat` / `python -m clipfoundry --unattended` watches app process exit and restarts with
bounded backoff. It preserves the selected data profile and saved Pause/permissions, owns its app/worker/media tree,
uses profile/port locks and stops without restarting on explicit Ctrl+C. Local app/watchdog diagnostics rotate at
5 MiB plus two older copies. Same-user Windows login startup is documented, never installed automatically.
Run only one app per data profile, including across different ports. This watchdog detects process exit; it does
not detect a still-running, hung main app.
Worker startup cleanup retains its lock until partial workers finish; setup failures do not keep phantom leases.
Bounded cancellable media pipe/process I/O and 2 GB disk-reserve checks keep low-space failures from blocking a
worker forever. Low-disk live capture waits without declaring EOF or deleting saved segments; final assemblies
replace complete recordings only after success.

Scheduled pre-session work rechecks Pause, current consent/account/audience and final quality even after a local
publication row exists. Existing sessions retain their confirmed bytes. Strict original-account, unique recent
submitted-metadata recovery reads actual visibility before reporting success. Final-chunk crash/cancellation or
ambiguous outcomes keep duplicate holds; manual startup recovery shows an unknown outcome with read-only Refresh.
Once final-byte evidence is saved, later reconnect, setup, scope or quota errors preserve that same hold and
publication identity rather than permitting another upload.
The real-media full-loop fixture now covers Public and Private independently, including repeat/restart/exact-byte
checks. This remains synthetic/fake-account verification, not real account or 24-hour operation proof.

Privacy documents local unattended diagnostic retention. No new dependency, real posting, account change, purchase
or deployment occurred. Windows/RTX 3050/accounts and an actual 24-hour soak remain owner checks. Deliberate rights,
quota, authorization, disk and unknown-outcome holds can still need attention; restarting does not bypass them.

The preceding department-office and reliability checkpoint starts at `e896632`, requested October 9 and completed
October 10 on the same draft/unmerged PR #14. Real working/reviewing jobs or substantive assigned backlog gather
the whole department into its own room. Actual workers appear immediately at their own desks; idle teammates sit
ready without typing, progress or invented jobs. Managers oversee from safe floor positions with clipboard checks
and brief pointing gestures; their own jobs and real report reviews take priority. Quiet paused/unavailable peers
may attend, but stale paused tasks, bare queue counts and unreferenced recurring timers do not summon a team.
A completed robot stays ready while another teammate has work, then resumes its reserved lounge activities.
Confirmed handoffs meet inside the receiver's office and return both robots to their latest department assignment.
A newer own job preempts carrying an older document out of its office. Actual badges and task details stay truthful.

The Brain's Processing animation now adds clipped holographic scans, travelling synapse trails, emitter sparks and
orbital light trails. Standby remains visibly decorative; Brain/global Pause, Reduced, hidden and stale views still
the art. Pixi and Canvas share department duties and supervisor cues. No dependency was added; the existing PixiJS
8.22.0 and GSAP 3.15.0 remain. [Latest department evidence and provenance](design/robot-office/departments/README.md).

The owner's full-code-review request also uncovered and fixed concrete backend faults:

* Job progress and host state now reject recovered lease owners and finished/pending jobs; recovery chooses an
  expired lease under the same write transaction as its update, protecting concurrent heartbeat/cancellation.
  Failed lock-file creation releases the in-process mutex, allowing the next GPU/startup lock acquisition.
* Final-check job identity includes the quality-rule version. Regeneration saves/restores the video and complete
  captions, transcript, edit decisions, render plan and thumbnail together. Interrupted rollback remains non-Ready
  until restoration succeeds, retaining its checkpoint on failure. Validated future plans are preserved.
* Brain edits use atomic revision checks, including enable/disable, so a delayed edit cannot overwrite a reviewed
  lesson or re-enable a disabled rule. Paused learning still collects results but preserves learned values and
  applies no cached learned weights/calibration. Confirmed audience drift is excluded from new cohort readings;
  prior observations keep their original provenance.
* Manual publishing checks linked-source rights, platform coverage, current quality/version and exact confirmed
  file bytes before a new transfer. Ordinary manual clips retain their existing workflow. Account binding survives
  TikTok options; emergency Pause also holds queued manual transfers while existing sessions may finish.
  An unknown manual YouTube outcome blocks another upload. Refresh status only reads the original account and
  requires one recent candidate with matching submitted metadata; ambiguity keeps the hold. Already-processing
  queue entries only read status. The Publish page exposes the hold and its refresh action.

Privacy documentation now covers local recovery copies and confirmed-file fingerprints. `.mcp.json`, GPU files,
Playwright versions and read-only `e2e/tests` remain unchanged. No real posts or owner account changes occurred.

The preceding social-pixel-office checkpoint starts at `5b1f7a9`: the owner requested better graphics tools and
off-duty games, food and drinks. Six authored gestures animate arcade controls, board-game pieces, mugs,
bites, page turns and stretches. There are 29 exclusive activity places, 25 stable cast homes and at most two
recreational walkers. Identity-phased routines rotate through free destinations; work and confirmed document
handoffs take precedence, preserve real references and clear leisure props. State badges remain authoritative.
The owner explicitly authorized stopped-office recreation even when those off-duty roles are marked Paused.
An individual pause while Running or an unavailable role remains quiet; global Pause, Reduced, hidden and stale
views freeze recreation. Recovery does not replay missed leisure time or old job stages.

PixiJS 8.22.0 now uses cached BlurFilter light pools and distinct arcade/café/game/sofa zones. New dependency
GSAP 3.15.0 supplies pure gesture-easing functions on the office clock, without independent timelines; its standard
no-charge license notice is included (it is not MIT). Native image generation produced the original bundled skyline.
Optional skyline loading is bounded to 1.5 seconds; failure/stall leaves procedural windows, and late completion
cannot mutate the scene. Cropped textures are destroyed without deleting the shared asset source. Canvas retains
simpler phase-driven gestures and a frozen Brain cue cannot change its pixels when activity expires. Lounge names
are staggered on the whole map and compact in the close camera. Portrait caching and all 25 identities remain.
[Current evidence, provenance and editing guide](design/robot-office/lounge/README.md).
This follow-up changes no backend, media processing or publishing behavior. PR #14 stays draft/unmerged.

The preceding living-office checkpoint started at `a119dfd`: the owner asked for believable proportions, idle robots in a
lounge, seated work, actual document transfers and an animated Brain. This supersedes idle-at-station placement.
The 960×640 floor plan now gives all 25 identities individual lounge seats, room-sized desks/chairs and walkable
aisles. `OfficeMotion.ts` follows current snapshots and fresh confirmed report/stage events: both robots approach,
one document passes between them, then both return to their latest actual destination. It never delays a backend
job or guesses a future transition. Paused/unavailable roles rest; Reduced skips walking; stale/hidden views freeze
and recovery uses the current snapshot without replaying old transfers. `BrainCore.ts` has layered neural lobes,
synapse lights and depth-sorted orbits: ambient **Standby** is decorative, **Processing** follows actual Brain
state/events, and Paused/Reduced/offline still the art. A room camera makes the furniture and robots inspectable.
The Canvas compatibility renderer now uses the same floor plan, seats and transfer controller.
Evidence: [living office and labeled controlled preview](design/robot-office/living/README.md).
This frontend-only follow-up adds no dependencies or processing/publishing behavior. PR #14 stays draft/unmerged.

The preceding visual checkpoint started at `c33a291`: the owner chose **refined retro pixel art** and asked to use better
graphics tools. The office now uses pinned PixiJS 8.22.0 with authored cast-specific artwork, layered room furniture
and a scoped studio shell. Team/detail portraits share one cached offscreen renderer. Existing job snapshots and
events still control states, walks, reports and decisions; this adds no processing or publishing behavior.
Graphics initialization/module failure restores the original Canvas map. Full / Reduced / Follow system remain.
The Windows install screenshot showed nested archive folders exceeding the standard path limit: use fresh ZIP
contents directly in `C:\CF14`, with `test-isolated.bat` there, creating a new `.venv`. Do not copy a partial environment.
The launcher now explains this when a long root may cause dependency setup to fail; no registry change is required.
Visual evidence and tool/edit instructions: [refined office](design/robot-office/retro/README.md).

Continue existing draft PR #14 on `claude/project-thread-vw1n9y`; keep it unmerged. This continuation started at
`fea045d` (previous code review `cf54204`). Default remains `claude/wonderful-ritchie-909tq3` at `eff96fb`.
The owner explicitly superseded selected-only new uploads and hiding idle robots. New Public uploads require
explicit setup/consent and eligible platform capability. Existing posts and scheduled Private uploads retain their
visibility. Never send test videos to owner accounts, buy hosting, deploy, or change account permissions.

## Historical PR #14 implementation

* All 25 robot identities remain individually visible at desks or reserved lounge places, with named labels and
  overhead state icons. Task selection includes shared references, dependencies, blocked reason and next robot.
  Saved motion choices: Follow system / Full / Reduced; Full overrides OS reduced motion. Stale state stops
  animation. Decorative recreation preserves actual state, work priority and genuine document handoffs.
* Brain at `#/brain`: durable searchable documents/instructions/skill guides, good/bad example uploads and feature
  labels, revision approval, edit/disable/delete/export, performance history and recorded per-clip influence.
  `autopilot/knowledge.py`, `knowledge_routes.py`, additive `brain_knowledge`/`brain_influences` tables. Uploaded prose
  is reference text, not executable code or model fine-tuning. Only supported approved caption/pacing preferences
  affect new blueprints; topic tags scope them. Examples never become posting results. Export includes all saved
  metadata/text/influences, without browsing caps; original uploaded files are downloaded separately.
* Demonstration: actual document upload + approval → later validated/persisted blueprint changes bold captions to
  minimal. Both instruction and bad-example later-plan regression tests pass. Screenshot/proof JSON record the
  saved decision; Try a decision is separately labeled a preview.
* Discovery: audience/topic terms, exclusions, language evidence, source-score floor and complete-story filter;
  curated/manual inputs retained. Metadata audience relevance and clip potential are estimates, not verified US
  viewers or promises of virality. Automatic repetitive/weak/unsuitable-live candidates are declined with reasons.
* Final check returns bounded repair work to SPLICE / GLYPH / STORY / QUILL with exact reasons and shared references.
  Two repair attempts maximum; uploads already using a file and user edits/cancellation are protected. Timestamp
  checks detect A/V offset and duration problems, not semantic lip sync. Missing sound is detected before Whisper;
  silent live segments are retained/skipped and later audio resumes; mixed final recordings retain returning
  sound with silent timeline gaps, temporary assembly files are removed, and all-video-only sources fail clearly once.
* New Public YouTube uploads and standing automation use explicit audience confirmation, connected-channel and
  visibility-bound permission, limits and exact-byte checks. Public lead is zero, so local
  uploads start at due time without `publishAt`. Existing Private schedules remain Private. Actual returned
  restrictions are reported. API-project audit status is informational; it no longer gates Public uploads.
  TikTok Everyone remains eligible-app + creator-options + per-post consent; inbox
  drafts/manual packages are honest fallbacks. No standing TikTok automatic consent.
* Learning separates confirmed-public and selected-viewer cohorts; unconfirmed/requested visibility does not drive
  learning. Both learners require 48-hour maturity. Cached weights/styles/posting-time data cannot carry over when
  the configured audience changes. Existing bounded updates, rollback, source diversity and sample guards remain.
* Measured real stage intervals: `/api/office/performance`, `python -m clipfoundry performance --days 7`.
  Pause/Stop controls are re-read atomically when the worker claims a job, preventing a stale preliminary
  state read from starting new work after the control was committed. Two deterministic regressions reproduced
  the old race and now pass. Database first-use migrations share a cross-process/thread lock and commit before
  another initializer reads the schema; old-project preservation and concurrent startup regressions pass.
  Separate Windows launcher `test-isolated.bat`: own `data\pr14-test`, videos, `.venv` and port 8899.

## Historical PR #14 validation

Latest unattended-Public validation is recorded at the top of
[IMPLEMENTATION_STATUS.md](docs/IMPLEMENTATION_STATUS.md). Full fast Python passed 757 tests, eight slow deselected,
in 390.67 s. All eight slow cases passed across the full run (six passed, two fixture setup failures, 786.85 s) and
the corrected Public (58.73 s) and upcoming-live (49.02 s) reruns. Production code stayed unchanged for those
corrections.
All 32 isolated browser cases passed together in 8.1 min. TypeScript/Vite build passed in 4.37 s; all 14 tested file
hashes match. Final fast verification includes the recovery, media, launcher, policy and unknown-outcome regressions.
The actual-app POSIX exit/restart/stop smoke passed in 11.98 s; Windows behavior remains unverified.

At the preceding department/reliability checkpoint:
[IMPLEMENTATION_STATUS.md](docs/IMPLEMENTATION_STATUS.md). Full fast Python passed 685 tests, seven slow deselected,
in 347.07 s. All seven slow media cases passed together in 676.84 s, with 685 fast cases deselected. All 31 isolated
browser checks passed together in 7.8 min. Final TypeScript/Vite build passed in 5.96 s with the existing 904 KB
lazy graphics warning.
All 14 build files and file sets match both tested and captured SHA-256 manifests. Routing/controller checks cover
3,844 + 36,304 routes, 600 virtual seconds and 150 mixed transitions. Actual Brain/supervisor pixels animate and
freeze in Reduced while true states update. All 32 touched/new code files meet 120 columns; whitespace checks pass.
Earlier 29/31-case browser runs each had one fixture/sampling failure, corrected without weakening the new-job
guard; the implementation log records their details separately from the final 31-case pass.
The new evidence has nine screenshots and one 37.40-second 1440×900 H.264 recording. Controlled work, supervisor,
Brain and handoff fixtures are visibly labeled separately from an actual stopped-sandbox lounge screenshot.
All 25 identities, laptop controls and mobile List/Studio layout were inspected, with no horizontal mobile overflow
and zero page/console errors. Evidence records all 14 captured production-file hashes. The recording documents
animation and confirmed-event choreography, not actual video-processing speed, Windows or RTX 3050 performance.

At the preceding lounge checkpoint:
The full fast suite passed **641 tests**, with seven slow cases deselected, in 280.30 s. All **23 focused browser
checks passed together in 6.4 min**. Final TypeScript/Vite build passed (5.83 s; existing lazy 904 KB graphics chunk
warning); all 14 distribution files are SHA-256 identical to the assets used in that final browser run.
Actual isolated desktop/laptop/mobile captures have 25 robots, visible laptop controls, no mobile horizontal
overflow and zero page errors. Both 1440×900 H.264 recordings have zero page errors: 33.24 s of actual stopped
off-duty animation, and 33.48 s of visibly labeled controlled work/Brain/stage fixtures. Only startup before the first
visible provenance banner was trimmed; animation was not retimed. Neither measures processing
speed. Prior slow media cases were not repeated for this frontend-only checkpoint.

At the preceding living-office checkpoint:
Production TypeScript/build passed; 17 office Python checks passed in 6.10 s and all 17 focused browser cases passed
together in 3.1 min. The browser cases cover lounge seats,
walk/sit/return, same-job document passing, event freshness/identity, Pause cancellation, Brain standby/processing/
pause, Reduced still frames, camera, fallback, portrait/navigation and desktop/laptop/mobile layout, plus current
sender recovery after hidden/paused stages and protection against reset-history replay. Evidence is
separated into actual isolated snapshots and visibly labeled controlled animations; neither is a GPU benchmark.

The preceding refined-art validation: TypeScript/production build passed, 17 office Python tests passed (7.20 s), and all ten focused motion/robot/
graphics browser cases passed together (59.3 s). Actual desktop/laptop/mobile captures recorded zero browser errors;
the separate animation video is visibly labeled as controlled test states. A pixel regression verifies COMMAND's
approval looks different from idle even in Reduced mode. Static floor/furniture is cached once; portrait cache is bounded.
The earlier 641-test and complete-media results below belong to `c33a291`; those suites were not repeated during
that refined-art checkpoint. Subsequent fast runs above are separate. Windows batch execution, PC graphics/scaling
and GPU checks remain owner checks. That refined-art checkpoint added only PixiJS; the latest lounge also adds GSAP.
Playwright and GPU pins remain unchanged.

The original master-continuation results below belong to the earlier `c33a291` checkpoint, separately from the
subsequent reruns. Its complete fast suite passed **641 tests** (263.21 s; seven slow cases deselected).
All seven slow cases passed across the full run
(six passed) and the corrected complete-loop rerun (one passed); the test now waits for both durable published
schedules before advancing fake result maturity. Ten browser checks passed across the sandbox run and targeted
Brain/Public-loop reruns. The Public browser loop includes two posts, restart, results, live capture and pause.
Production frontend TypeScript/build passed. Focused startup/core/office/TikTok: 66 passed; publishing: 44;
knowledge/public: 17; full Brain export: 8; public-audit/automation: 33; timing/office: 19; returning-audio/recovery: 28.
A database made using `fea045d` opened under the new additive schema with project/clip/settings/private
schedule/audience/approval and media bytes unchanged. No owner data was accessed.

Visual assets: [design/robot-office/screenshots/README.md](design/robot-office/screenshots/README.md). It distinguishes
actual isolated app/jobs, synthetic transcripts, saved blueprint decisions, lookup previews and controlled animations.

## External limits and remaining owner checks

Earlier October 8 developer-host requests returned proxy **403**; those verification limits remain historical.
October 10 official documentation was reachable and freshly checked: YouTube's October 8 update permits Public
from unverified projects, API audits cover quota increases, and External Testing grants have a seven-day lifetime
for YouTube scopes. Current sources and remaining TikTok restrictions are recorded in PLATFORM_CAPABILITIES.

Not verified here: RTX 3050 CUDA transcription / NVENC rendering; real accounts, scopes, quota grants and
returned Public visibility; TikTok app eligibility and approval, real Direct Post/inbox; Windows setup, fonts,
scaling; Windows Task Scheduler/process-tree cleanup; a real 24-hour unattended soak; live network access on the
owner’s PC; real NVIDIA services. Run the
[Windows test guide](docs/WINDOWS_PR14_TEST.md) in a separate copy first. No real posts, purchase or deployment occurred.

[Server recommendation](docs/PERFORMANCE.md): keep the PC until its real timing/GPU report supports a comparison;
a server can improve uptime but does not remove platform restrictions. No general randomized experiment system,
unique-viewer/dominant-video rule, new Twitch/Kick/Reddit/X/Instagram/podcast connectors or preview-before-download
screen was added. Knowledge controls are intentionally typed; arbitrary prose does not automatically alter decisions.

## Do not break

Keep `.mcp.json` and GPU dependencies unchanged; no Playwright pins. Preserve the owner-data browser tests'
read-only workflows and request blocker. One stale Integrations assertion now matches the already implemented
Public choice; it does not select an audience, grant permission or issue a write. Commit built `frontend/dist`.
Preserve exact-file quality/approval hashes, reuse eligibility, access guards, account-bound consent, limits,
duplicate prevention/recovery and emergency stop. No silent CPU fallback in Autopilot. Never fabricate processing
progress, metrics or visibility; keep decorative recreation visibly separate from actual job activity.
PR #14 is merged; follow the current scope and branch recorded above.
