# ClipFoundry handoff for Claude

Prepared October 15, 2026, America/Chicago. Read `AGENTS.md`, the latest `AI_HANDOFF.md` section and the top of
`AI_CHANGELOG.md` before changing anything. This is a local Windows desktop app, not a hosted service.

## Start here

The application repository is `landryschreiner33-coder/ClipForge-AI.` (including the final dot).
Work is on `codex/brain-graph-quality-discovery`, based on tested revision
`11bdb43523f9b01e82590d2dd9e67473d323c88d`. The commit containing this handoff adds the current fixes. Fetch and
inspect the branch and working tree before trusting a cached checkout; do not reset or discard someone else's work.
The earlier PR #14 is merged; this is later continuation work, not a request to recreate that PR or merge blindly.

The readable setup lives on `codex/clipfoundry-one-click` in a separate checkout. Its previous tested artifact
was `40393e4c2e30119d9dd70dc42d9770098f11202d`. The delivered artifact's
`launcher/plain_setup_verification.json` records the final exact app revision, ZIP hashes and test evidence.
Do not rebuild or recommend the previously blocked custom EXE, change antivirus settings or discard managed profiles.

Suggested opening prompt:

> Continue ClipFoundry from the current `codex/brain-graph-quality-discovery` branch. Read CLAUDE_HANDOFF.md,
> AGENTS.md and AI_HANDOFF.md first. Preserve the tested audio/comments/discovery/live/Windows fixes, Brain use,
> selected-post bulk approval and verified Windows profile reuse. Start with any owner-provided reproduction
> evidence still missing below. Use isolated data and fake accounts; do not publish real test videos.

## The owner's current request

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

Preserve review-before-publishing, exact-file/source/account/audience approval, selected-post bulk review up to
50 YouTube posts, required credit, uncertain-upload recovery and no-duplicate guarantees. Brain guidance cannot
grant publishing rights or consent. Never create real test posts, spend money, change account permissions,
delete owner media, force-push or deploy public pages without the corresponding owner instruction.
