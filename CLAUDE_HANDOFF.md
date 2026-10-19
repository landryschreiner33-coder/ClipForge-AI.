# ClipFoundry handoff for Claude

Prepared October 19, 2026, America/Chicago. Read `AGENTS.md`, the latest `AI_HANDOFF.md` section and the top of
`AI_CHANGELOG.md` before changing anything. This is a local Windows desktop app, not a hosted service.

## Start here

The application repository is `landryschreiner33-coder/ClipForge-AI.` (including the final dot).
Work is on `codex/brain-graph-quality-discovery`, based on tested revision
`fcd48aecece759ed676d871a9282d81b83f0ab92`. The commit containing this handoff repairs Windows setup without changing the submitted-video workflow. Fetch and
inspect the branch and working tree before trusting a cached checkout; do not reset or discard someone else's work.
The earlier PR #14 is merged; this is later continuation work, not a request to recreate that PR or merge blindly.

The readable setup lives on `codex/clipfoundry-one-click` in a separate checkout. Its previous tested artifact
was `39c58577b86c806d04bf3db5e15596c4415efced`. The delivered artifact's
`launcher/plain_setup_verification.json` records the final exact app revision, ZIP hashes and test evidence.
Do not rebuild or recommend the previously blocked custom EXE, change antivirus settings or discard managed profiles.

Suggested opening prompt:

> Continue ClipFoundry from the current `codex/brain-graph-quality-discovery` branch. Read CLAUDE_HANDOFF.md,
> AGENTS.md and AI_HANDOFF.md first. Preserve actual supported Windows Python verification and nondeleting
> environment recovery; do not change GPU pins or owner profiles. The current default is submitted video link/file → relevant supported Brain
> guidance plus Settings → creation/checks → automatic YouTube upload under that input's explicit Make & upload
> request. Preserve old backlog/manual review, TikTok per-post consent, exact-file/source/account/audience checks,
> measured audio/live/Windows fixes and managed-profile reuse. Use isolated data and fake accounts; no real test posts.

## Latest request: CTranslate2 setup cannot find a matching distribution

The latest owner screenshot shows pip resolution failing for CTranslate2. It does not prove which Python,
architecture, index or network setup was used. Current CPython 3.13/3.14 Windows AMD64 wheels exist; do not claim
those versions inherently lack support. ClipFoundry deliberately selects its standard, supported Windows runtime:
**64-bit CPython 3.12**, then **3.11**, `win-amd64`, not free-threaded. Native ARM64/32-bit lack the applicable wheel.

New `windows_bootstrap.py` is standard-library-only. `--runtime-json` exposes nonsensitive actual runtime traits;
`--check-python` is the authoritative success/failure check; `--prepare-venv APP_FOLDER` verifies/reuses an existing
compatible environment or safely preserves and replaces it. The readable installer checks before profile/app
writes and forwards `CLIPFOUNDRY_BOOTSTRAP_PYTHON`; `start.bat` validates it again or probes supported selectors.
Do not revert to generic `py -3` or trust labels instead of actual runtime output. The outer installer and bundled
helper must remain pinned together.

Incompatible/unverifiable `.venv` becomes a unique `.venv-backup-*`; failed creation is preserved separately as
`.venv-failed-*`, with prior environment restoration where possible. Known active `.venv` Python processes block
replacement; the helper inspects without terminating processes. Never automatically delete environments or app
data. Compatible environments, Brain notes, account grants, clips, submitted-video behavior and GPU/dependency
pins remain intact. With no supported interpreter, install official python.org **Windows installer (64-bit)**
Python 3.12 side by side and reopen; no automatic global install/removal, PATH/registry/security modification.

**Validation:** Full fast regression suite: 1,489 passed, 17 slow deselected in 527.16 s. All 203 frozen source/test/bootstrap/dependency hashes matched. The 38 focused bootstrap checks passed in 3.54 s, including real disposable-host venv creation, reuse and replacement, preserved dependency markers/data, failure rollback, active-process and concurrency guards, exact runtime checks and read-only probes. A 19,230,360-byte CPython 3.12 Windows AMD64 CTranslate2 4.8.3 wheel was downloaded and its SHA-256 matched PyPI (b5daf0758d522a422c76e53eb02ce9f42465a9aba938a86b27249fb5db2571b9). No dependency/GPU pins, app pipeline or frontend files changed; all 17 previously browser-tested built files retain their hashes. The previous 17 media and 59 browser results apply to unchanged scopes and were not rerun. The readable setup is separately pinned to this exact app commit; its delivery proof records installer/helper tests, full source hashes, managed-release history and immutable download readback. This is evidence for one wheel, not actual Windows installation/CUDA execution. A full cross-platform pip dry run on Linux uses Linux markers and is not a
Windows dependency proof. Previous `fcd48aecece759ed676d871a9282d81b83f0ab92` media (17) and built-browser (59)
results below apply to unchanged code, not reruns here. Native Windows CMD/process/venv behavior, owner PC/
RTX3050, real account uploads, Defender acceptance and a 24-hour run remain unverified.

## Previous request: supplied video to automatic YouTube clips

The owner no longer wants the default workflow to find videos. They supply a recorded-video link/file and want
creation, supported Brain guidance and automatic upload. `autopilot_input_mode=submitted` is the default, with a
one-time old-profile migration that preserves later explicit choices. Optional discovery remains available in
Advanced; its periodic and stale queued discovery handlers and watched-folder admission are inactive in submitted
mode. Earlier discovery-key fixes remain included but are not a prerequisite for this input workflow.

Missions → **Add a video** offers **Make & upload clips** and **Make clips only**. Upload requires an actual
connected YouTube account, confirmed audience, real kids answer, source reuse basis and one explicit checkbox.
The action covers only this input's newly generated qualifying clips, not old backlog, future inputs or TikTok.
The chosen source request can target YouTube even if broad schedule/publish/platform toggles are off, without
changing those globals. Stop all jobs, Pause publishing, cancellation, quality/grounding/credit, source/account/
audience/terms drift and real waits still hold. Keep manually edited/canceled and active/uncertain work intact.

`autopilot/submissions.py` owns strict options, bounded file copy, canonical new-source insertion, source grant,
original/project binding, final per-post automatic approval and progress. `source_submissions` stores wording and
options outside Brain, including source identity/hash/project/current terms. Files copied under `data/submitted/`
remain after project deletion/cancellation until the data folder is removed; project outputs have their own
normal deletion. Source assertions do not verify ownership or rewrite source rights. The accepted source, grant
and enabled worker state commit together; `recover_unstarted` closes only a no-job enqueue gap, never a prior
attempt/cancellation. Re-adding a known video refuses to give old media a fresh grant. Link acquisition uses
supported guarded media import without discovery credentials or login/access bypass; new live links are rejected.

`packaging.platforms(settings, source)` and the gate honor the explicit per-input YouTube target. The scheduler
restricts new plans to submitted sources in this mode, with `approval.by=submission` for exact final bytes/text
covered by that request. Publisher rechecks original consent/account/audience/quality before starting, while
started/uncertain sessions retain their existing identity and reconcile. A fresh render/edit can require manual
review. Source request and per-post reuse records never teach Brain. Relevant supported notes/example choices
use source title/spoken context with Settings fallback; uploaded examples are not model fine-tuning or visual
style inference. Existing explicit editor overrides remain.

**Focused validation so far:** 99 mode/diagnosis/continuous-search/office-health/phone checks passed (36.02 s);
60 submission-routes/consent-audit checks passed (35.02 s); three new actual-media cases passed (53.82 s);
26 legacy packaging/quality/audio checks passed (68.03 s). New measured AAC cases include actual Brain-guided
caption rendering, exact fake-upload bytes and restart without duplicates, including global YouTube toggle off.
Final full fast suite: 1,451 passed, 17 slow deselected, in 676.07 s. Final full real-FFmpeg/synthetic-media and restart suite: 17 passed, 1,451 deselected, in 934.97 s. TypeScript and the production build passed (10.00 s). All 59 final built-browser checks passed in 161.55 s. The final fast suite used 198 frozen Python source/test files. All production and selected media-test sources stayed unchanged during the full media run; 81 frontend source and 17 built-file hashes stayed unchanged through the final browser checks. A deselected fast retention fixture's timestamp setup was corrected before the final fast run; the media run's production/selected sources were unaffected. Focused checks also passed: 60 submission/consent, 79 final status/routes/legacy readiness, 29 advanced-route/legacy, 119 legacy intake/scheduler/publishing, three new actual-media and 26 legacy audio/quality and nine retention checks. The three new media cases use relevant saved Brain guidance, real caption/AAC rendering, exact fake-upload bytes and restart without duplicates, including the broad YouTube switch off and TikTok enabled. Earlier full attempts were interrupted before the final route/status/retention corrections and are not final evidence. Tests use isolated profiles, synthetic media and fake platforms only. The readable source setup is pinned separately to this committed app tree with the tested frontend manifest; its delivery verification records exact archive hashes and source revision.
Prior sections' final counts are historical. No real YouTube transcode/upload, owner media,
native Windows/RTX3050, Defender acceptance or 24-hour soak was verified. Source distortion is not reconstructible
by the final peak limiter. Preserve all earlier audio/comment/live/Windows fixes below.

## Earlier request: failing search keys and post-only permission records

The owner reports no clips and clarifies **both API keys fail**; no exact service error or owner-PC access was
provided. They confirm reuse text appears **only in the clip's approval/reuse details**. These records already
stay with the exact post, not Brain. No automatic permission-to-knowledge write was found; do not invent one or
delete/filter deliberately saved references. Single/bulk approval and real learner projection tests verify this
boundary. Forms and post details now explain it explicitly.

YouTube discovery refreshes a rejected same-account OAuth token once, with every request counted and no override
of quota or Retry-After. Saved optional API keys stay explicitly selected. Static errors distinguish invalid keys,
application restrictions and a disabled API. Remove a bad optional key and save to use the connected account.
Legacy and new keys trim outer whitespace; API saves reject internal whitespace/control characters without echo.
Tavily busy-server Retry-After becomes a durable provider-local wait; other providers/folders can continue.

Settings → Integrations → Search connections has **Test saved YouTube connection** / **Test saved Tavily connection**.
New `autopilot/search_connections.py` plus local-page-only integration POSTs perform bounded checks: YouTube makes
an uncached general-quota `videos.list` read; Tavily GETs `/usage` with its key in the Authorization header, no
query/body/search. Both validate actual response shape. Checks retain safe results/times and a nonpublic credential
fingerprint, handle waits/local budgets/concurrency and mark changed credentials stale. GET is strictly read-only.
A passed check proves credential/API access at that time, not available search credits, downloadable media,
passing quality checks or posting permission. No express zero-credit guarantee was found for Tavily `/usage`.

Home and health no longer use YouTube reset advice for Tavily/Commons, blame missing reuse coverage in review
mode or call configured failing searches healthy. They preserve independent work and static safe diagnosis.

Official contracts checked: https://docs.tavily.com/documentation/api-reference/endpoint/usage and
https://developers.google.com/youtube/v3/docs/videos/list .

**Latest validation:** Final full fast suite: 1,373 passed, 14 slow deselected, in 755.18 s. Final full real-FFmpeg/synthetic-media and restart suite: 14 passed, 1,373 deselected, in 945.34 s. Final TypeScript and production build passed (5.17 s). All 51 final built-browser checks passed in 167.41 s, with all 17 built-file hashes unchanged. Focused provider verification: 77 passed in 7.83 s; focused diagnosis/health/phone: 88 passed in 11.26 s; independent saved-search/Brain separation checks: 113 passed in 22.43 s before the final wait-order correction, then 53 passed in 4.06 s including both same-key full-server-wait regressions. All 261 frozen production/frontend/Python-test hashes remained unchanged through final verification. Tests used isolated data, synthetic media, MockTransport and fake platforms. No owner keys, Windows profile/RTX3050, actual search-service account, real upload, Defender acceptance or 24-hour soak was verified. Permission answers were already post-only; the update clarifies and verifies that boundary.
The owner's keys/configuration and Windows run remain unverified. After installing, test both saved connections
and use the actual sanitized failure to guide setup; never ask the owner to paste keys or tokens. Preserve all
audio/live/Brain/bulk-review fixes below. Do not claim every possible bug or a 24-hour run was verified.

## Earlier audio/search/live request, retained in this update

1. Uploaded audio is **distorted**. This clarification is confirmed; the owner has not supplied an affected file
   or link, or confirmed whether the same distortion is present in the local preview.
2. Comments are off on some YouTube videos.
3. Discovery searches many times and then stops; it should continue when capacity and service allowances permit.
   Provide places to connect useful free search API keys.
4. Two screenshots: repeated Python 3.13 Windows Proactor `_call_connection_lost` WinError 10054 errors; live
   capture rejects separate audio/video formats and fails after an ended stream has no local recording.
5. Provide this Claude handoff.

## Implemented fixes and their boundaries

### Distortion and audio timing

`pipeline/render.py`, `pipeline/ffmpeg_utils.py`, `tests/test_upload_audio.py`.

- Real FFmpeg reproductions found post-normalization gain clipping and default-settings surround downmix
  overloading: normalization ran before final stereo conversion. Downmix now happens first; a final lookahead
  peak limiter follows normalization, speed and gain. Automatic gain boosting is disabled and limiter latency
  is compensated. Tests measure actual samples, tonal purity and encoded AAC output.
- Delayed audio starts and mid-recording timestamp gaps are represented as silence before transcription and
  rendering rather than independently resetting speech to time zero.
- Transcription explicitly selects the same first audio track that probe/render use; automatic FFmpeg selection
  could choose a different higher-channel track and transcribe different speech.
- Real cut/speed renders and exact bytes received by a fake YouTube uploader are verified. Upload itself does
  not transcode audio. A limiter cannot reconstruct audio already distorted in the original source.
- Existing renders, uploaded posts and cached transcripts are not silently rewritten. Validate a fresh source
  import for the timing fix. Older transcripts produced from shifted audio may need fresh processing. Previously
  uploaded bad videos require an owner-reviewed new render/upload; do not delete or replace posts automatically.

### Comments and the made-for-kids answer

`publish/youtube.py`, `publish/jobs.py`, `publish/routes.py`, `autopilot/scheduler.py`, `autopublish.py`,
`autopilot/routes.py`, shared `frontend/src/components/YouTubeComments.tsx`, and review/publish controls.

- Genuine booleans remain unchanged. Strings such as `"false"` previously became truthy in a low-level serializer;
  malformed strings/numbers/missing answers are now rejected or held rather than guessed.
- Private YouTube videos and videos made for kids do not support comments. Review explains this before approval
  and distinguishes being intended for children from merely being suitable for all ages.
- Existing upload/status responses retain returned `madeForKids` and `selfDeclaredMadeForKids` evidence without
  extra requests. The UI explains known restrictions or directs the owner to YouTube Studio when unknown.
  The actual returned label takes precedence over a declaration, and historical requested=True is used only
  when neither current flag is available. Refresh after a Studio correction must not repeat the old label.
- There is no enable-comments switch in the video upload API. YouTube/channel defaults or platform restrictions
  may still disable comments on a public video marked not made for kids. Do not change the owner's real audience
  answer or visibility to force comments. Check Studio → Content → video → Audience and Show more → Comments.

### Recurring searches and optional keys

`autopilot/scout.py`, `providers.py`, `quota.py`, integration/discovery settings, and
`tests/test_review_continuous_search.py`.

- Provider-specific durable waits replace YouTube waits that previously postponed every search service.
  A one-time migration preserves any old potential YouTube wait while independent searches can wake again.
- With queue capacity and remaining configured source allowance, checks recur within 15 minutes. Busy queues
  retain the regular configured interval. The free feed cadence can wake saved active signals without new rows.
  When a full queue drains, shorten its already-persisted regular deadline too; changing only the interval leaves
  the old three-hour deadline in place. Repeated polling must not postpone the shortened deadline.
  Health and phone status use a pure cadence calculation; only the periodic host reconciles deadlines/migration.
  Status GETs must not write scheduling state or make the phone into a control surface.
- YouTube and Commons rotate provider-returned positions through at most five pages per query, one page per
  normal pass. Preserve original rank position and the exact time boundary associated with a YouTube page token.
- Keep quality floors, bounded admission, cancellation, explicit owner caps, API quotas, exact Retry-After,
  free-credit and paid-budget controls. Continuous does not mean unlimited calls or bypassing a service wait.
- Settings → Integrations → Search connections exposes the existing sealed YouTube Data API and Tavily keys.
  Saving a key does not test it or connect an upload account. Secrets stay masked and are not echoed after save.
- Tavily's official docs currently state 1,000 monthly free credits without a credit card; this app uses basic
  search at one credit. The free-plan button sets the included allowance to 1,000 and paid budget to $0.
  This is an app allowance, not a live provider balance. Other apps using the same key consume that allowance too.
- YouTube keys use the project's quota, not unlimited additional searches; keep official API restrictions.
  Commons and local folders require no API key. No new provider or paid service was added.

Official references checked for this release:

- https://docs.tavily.com/documentation/api-credits
- https://developers.google.com/youtube/v3/getting-started
- https://console.cloud.google.com/apis/library/youtube.googleapis.com

### Live capture and ended recordings

`autopilot/live.py`, `stream_access.py`, `tests/test_live_capture_fixes.py`.

- Compatible separate HLS renditions share one synthetic local master and relay, preserving their common clock.
  Both entry URLs, redirects and nested resources retain public-URL checks, shared byte limits and exact waits.
  FFmpeg receives local relay URLs. The actual paired capture test measures flash/tone alignment.
- Only an empty ended platform capture checks for an ordinary public archive through the existing guarded
  importer. Up to eight availability checks and a six-hour window are durable across restart, while a longer
  server-requested wait is not shortened. Access refusals remain refusals.
- Existing partial captures keep their saved segments and original timeline. Recovery keeps the same project
  and one post-live handoff. A newly recovered full archive invalidates only the empty generated live transcript/
  loudness caches so the real recording is transcribed.
- A platform must actually expose a public recording. Private, protected, deleted, unavailable or unsupported
  media cannot be repaired by retries. Add the owner's recording or retry when the public archive exists.

### Windows reset traceback

`asyncio_windows.py`, desktop/phone lifespans, `test_review_windows_disconnect.py`,
`test_review_reliability_audit.py`.

- The screenshot is a CPython Proactor socket shutdown failure after protocol notification. The scoped handler
  matches native WinError 10054 at the exact stdlib cleanup callback, closes the socket and finishes detachment;
  it does not merely silence all ConnectionResetError logs or notify the protocol twice.
- Python 3.11/3.12 and 3.13 have different server-detach signatures. Select the valid call before invoking it;
  never retry after a TypeError that could already have changed server state.
- Other errors, protocol failures and cleanup failures use the previous/default handler. Restore handlers when
  a server stops. The phone companion's own lifespan starts no desktop workers and remains read-only.
- Tests use actual asyncio transport/Server cleanup and a native local socket shutdown, emulating only Windows'
  error code. Native Windows execution was not available; do not claim the owner's screenshot was retested there.

## Verification

Final full fast suite: 1,278 passed, 14 slow deselected, in 579.81 s. Real-FFmpeg/synthetic-speech media and restart verification covered all 14 scenarios across two runs: the full attempt passed 12 with 2 repeat-discovery timeouts (1,274 deselected, 1153.68 s); after correcting only the compressed-clock fixture's discovery-list cache expiry, both private/public repeat scenarios passed in 374.57 s. This was not a single all-green full-media run. Production cache/quota policy and all real render, final-report, exact-upload-byte and restart assertions were unchanged by that fixture correction. Final production build: 10.32 s; TypeScript passed. All 43 final built-browser checks passed in 93.25 s, with all 17 frontend hashes unchanged. Focused independent bugfix verification: 73 passed in 32.22 s, including measured encoded mono/surround audio, exact fake-upload bytes, real split-HLS synchronization and real asyncio cleanup compatibility. Windows/phone focused verification: 63 passed in 10.25 s; earlier discovery focused: 89 passed in 11.12 s. The final queue-drain deadline correction and surrounding discovery checks passed 61 tests in 9.13 s. Final comments/search checks after the current-label correction: 47 passed in 22.85 s. The final read-only health/phone/search correction passed 77 checks in 16.64 s, with database-unchanged assertions intact. The complete media run used the final audio/live/publishing code, preceding only the pure health-cadence refactor and its four new fast tests; all 39 media-scope source hashes remained unchanged. That refactor is covered by the final full fast run and 77 focused checks. The earlier interrupted suites preceded final deadline/returned-label corrections and are not final evidence. No real owner Windows profile/media, RTX3050, live provider key, account upload or 24-hour soak was tested.

Focused independent checks before full verification: 73 passed in 32.22 s across the new audio, live, continuous
search, comments and Windows/audit suites. Separate frontend discovery setup checks passed seven tests using
isolated data; final built-browser evidence below supersedes that development-server run.

Standard commands (Linux checkout; use `.venv\Scripts\python` on Windows):

```bash
TMPDIR=/workspace/work/clipfoundry/bulk-test-temp PATH=/workspace/work/clipfoundry/tools:$PATH \
  .venv/bin/python -m pytest -q -m 'not slow'
TMPDIR=/workspace/work/clipfoundry/bulk-test-temp PATH=/workspace/work/clipfoundry/tools:$PATH \
  .venv/bin/python -m pytest -q -m slow
cd frontend && npm run build
```

Use a throwaway sandbox for browser writes. Normal `e2e/tests` remain read-only because they may target the owner's
actual installation. Keep the final built frontend manifest when exporting the exact committed source archive.
Update `AI_HANDOFF.md`, `AI_CHANGELOG.md`, `.clipfoundry/ai-change-log.jsonl`, implementation status and privacy
documentation with meaningful changes. Keep GPU dependencies and `.mcp.json` unchanged.

## Owner-PC follow-up still needed

- Obtain one affected original and local rendered clip, or a public YouTube link, to distinguish source distortion
  from rendering or YouTube processing. Do not ask the owner to paste keys, tokens or private account dumps.
- Confirm a fresh corrected render sounds right locally before approving a new real upload. Existing published
  audio does not change when the app is updated.
- Check one comments-disabled video in Studio: actual visibility, intended audience/YouTube override, channel
  defaults and comment settings. This environment has not accessed the owner's Windows profile or account.
- Observe an owner's long run: queue admission, provider-specific next times and actual service responses.
  A 24-hour unattended soak, real provider keys, Windows/RTX3050 and real account uploads remain unverified.
- Deliver the verified readable source ZIP: close the old app, **Extract All** the outer ZIP, then open the
  extracted `Open-ClipFoundry.cmd` beside `setup.py`, `app.zip` and `README.txt`. Leave inner app.zip zipped.
  Verified earlier same-Windows-user managed installs keep their original data; unknown ordinary ZIP profiles
  are not automatically adopted. Never alter security settings or recommend the historical blocked EXE.

Preserve review-before-publishing outside explicit submitted-source requests, exact-file/source/account/audience
approval, selected-post bulk review up to 50 YouTube posts, required credit, uncertain-upload recovery and
no-duplicate guarantees. Brain guidance cannot
grant publishing rights or consent. Never create real test posts, spend money, change account permissions,
delete owner media, force-push or deploy public pages without the corresponding owner instruction.
