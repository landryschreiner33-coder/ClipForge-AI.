# ClipFoundry: readable Windows setup

Download **ClipFoundry-Source-Setup.zip**, close the previous ClipFoundry/setup windows, right-click the ZIP
and choose **Extract All**. Open the extracted folder and double-click **Open-ClipFoundry.cmd**. Keep its
console open while setup finishes and the app runs. Use the same CMD file for later sessions.

Do not open the CMD from inside the ZIP. In the extracted folder, keep **Open-ClipFoundry.cmd**, **setup.py**,
**app.zip** and **README.txt** together. Leave the inner **app.zip** zipped; setup opens it for you.

The ZIP contains four inspectable files: the CMD launcher, Python setup.py, the exact app app.zip, and
README.txt. It uses your installed Python and normal application start script. No custom compiled launcher,
PowerShell loader, app-archive download or administrator access is needed. Python 3.11/3.12 and FFmpeg are
recommended; installing Python dependencies/GPU libraries and later speech models may still need internet.

Windows blocked the prior ClipFoundry-Setup.exe download. The detection name is unknown, so a false positive
is not established. That historical unsigned executable is no longer the recommended download; do not restore
or allow it, disable antivirus or add exclusions. The source ZIP is a different, readable delivery method,
not an antivirus certification. If Windows also blocks its ZIP or extracted files, stop and inspect the reported
detection. Native Windows execution and Defender acceptance could not be tested in this Linux environment.

## Existing installations and data

Verified installations created by the earlier managed launcher, under the same Windows account, retain their
original data folder. Brain lessons, connected accounts, settings, projects and saved media stay in place.
The new code goes into a fresh short folder and creates its own virtual environment. Old app files, data and
virtual environments are neither copied over nor deleted. Ordinary ZIP installations and unknown/different-user
markers are left untouched and are not automatically adopted; their data is not migrated.

Managed markers use the same Windows SID, v1/v2 formats, release/start-file pins and original profile identity
as the earlier launcher. Multiple original profiles, unverifiable same-user managed revisions, linked profile
paths and held profile locks stop setup. Missing/malformed JSON markers are treated as unknown installations
and left untouched. A same-user named mutex covers setup and the running app. A running managed Python process
also prevents opening the same data through a second copy; no process is terminated.

Installation roots are at most 100 characters, normally under C:\CF14, with a writable local application
folder as fallback. Occupied unknown destinations are skipped. Owned staging, checked archive paths and an
exclusive directory move prevent merging into an existing root. Setup runs before selecting a free loopback
port. The original data directory remains the CLIPFOUNDRY_DATA location. No execution-policy, antivirus,
certificate trust, firewall/router or Windows scheduled task is changed. No missing account/audience permission
is created.

## Included application

The app is the tested revision **0c2729d0a1e148e22da5bcdbd6db4ccb490dafa7**. Its archive
SHA-256 is **b7af499e03b140f374abcaa3b1c2cf3c9127719ee1f17fc336203a70acb10ccf**. Setup verifies the archive and
known start.bat hash before installing new code. Existing managed identity checks verify the marker and start
file, rather than claiming a full checksum of every file already present on the PC.

This update addresses distorted audio in new renders by downmixing the chosen audio track before processing,
using clip-relative audio timing and limiting peaks after gain. It does not repair distortion already present
in a source or change previously rendered/uploaded clips. Preview a new clip before approving it; an existing
clip needs a fresh render and final checks before its corrected bytes can be approved.

YouTube made-for-kids answers now require an actual Yes/No value instead of interpreting text such as "false"
as Yes. The review screens explain that made-for-kids and Private videos cannot receive comments. ClipFoundry
does not change an audience or kids designation to turn comments on. YouTube may also restrict comments for
other reasons; check an affected video's settings in YouTube Studio. There is no general YouTube Data API
switch that guarantees comments stay enabled.

Discovery continues in bounded scans while Autopilot is running. A provider's rate limit pauses that provider,
while other available providers and folder checks continue. When preparation has spare capacity and the saved
source budget allows more work, scans run at most 15 minutes apart, or at your faster configured interval.
A busy queue retains the configured regular cadence. Search pagination is bounded, and Missions explains the
actual next search/wait. Quality, saved owner limits, app cost allowances and platform quotas still apply;
this is not a promise of nonstop API calls.

Open **Settings → Integrations → Search connections** to enter an optional YouTube Data API key or Tavily key.
A connected YouTube account already supports search; a key does not add posting permission or bypass its quota.
Tavily's free plan currently includes 1,000 credits each month without a credit card; the app uses one credit per
basic request. Choose **Use free Tavily plan limits** to set 1,000 included credits and a $0 paid-search allowance,
then save. This is an app allowance, not a live provider balance; usage in other apps counts at Tavily too.
Wikimedia Commons provides a no-key free-license library. Enter keys only in the app, never in chat. Search
results do not grant reuse rights or guarantee a better clip.

The live-capture fixes accept supported separate HLS video/audio tracks and perform bounded checks for an
ended stream's recording. Some streams never publish a usable archive; those still finish with an explanation.
The Windows disconnected-socket cleanup fix handles the specific WinError 10054 cleanup path without hiding
unrelated failures. Native Windows execution remains unverified here.

The application includes **CLAUDE_HANDOFF.md** with the release's code changes, verification and remaining
checks. Ask Claude to read that file and AGENTS.md before continuing the project. Keep account keys and your
private app data out of any handoff you share.

Autopilot prepares clips and assigns proposed posting times for your review. Missing recorded reuse permission
does not stop a clip from reaching the review queue. A proposed time is local to ClipFoundry; the app does not
upload it to YouTube or send it to a platform scheduler until you approve it.

After updating, check **Missions → Prepare & schedule for review**. In **Queue**, play clips directly from
their cards. Check the source and valid reuse permission, caption, destination and proposed posting time.
Use **Quick approve** for one YouTube post, or select reviewed YouTube posts and choose **Approve selected**
for a batch of up to 50. The dialog shows the exact posts and their audiences and times.

Choose a reuse-permission basis when requested. Presets avoid repeated typing; **Other permission** accepts
your explanation. Choose a basis that truthfully covers all selected clips, or approve separate groups with
different bases. Answer the made-for-kids question if requested, confirm the review once and approve. Each
successful approval belongs to its own reviewed post; anything needing correction stays in review with a
reason. New arrivals are not selected or approved automatically.

An approved YouTube post can publish at its scheduled time. Review past-due times before approving: those
posts can upload on the next publishing check. Clips awaiting review stay on your PC. Individual **Post
review** also offers presets and one combined confirmation. TikTok retains individual per-post review;
manual handoff uses **Approve for TikTok**, with separate controls for supported inbox/direct uploads.

This update stops standing automatic approval. Existing uploads that have already started or have an uncertain
platform result keep their identity so recovery cannot upload the same clip twice. Existing posted videos are
unchanged. No TikTok connection is required for YouTube.

Earlier fixes remain: app daily source/clip/platform caps default to 0 (unlimited), with any-hour earliest
eligible posting times, bounded recovery of older outputs, Brain guidance and clear Missions explanations.
Owner caps, platform/API limits and quality checks still apply. A source being public is not recorded reuse
permission; review makes that decision explicit before publishing. Audience choices and made-for-kids answers
remain required, and private/unlisted account settings are not a substitute for per-video visibility.

Real Brain guidance consultations and ordered worker/manager/boss handoffs now appear in the office. Quiet rooms
explain their actual waits. Current reuse/required-credit checks also bind to actual post text, with safe editable
review and recovery of provably unstarted uploads. Started/uncertain sessions retain their original identity.

Enabled saved Brain guidance applies automatically to new clips, with Settings filling unspecified choices.
Topic matching follows source context and spoken content through clip selection and supported rendering
choices, so a topic-tagged note is not lost when a generated clip title uses different wording. Recognized
guidance takes priority for its supported choices; explicit clip-editor changes still take priority. Example
videos provide measured duration and their saved preferences or notes; they are not a visual-style training
model. General reference text remains searchable, and unsupported requests do not become editing controls.
Check a new clip's Brain influence to see which saved items actually changed its plan or render. Existing
rendered clips are not silently rewritten.

The optional **Settings → Integrations → Check from your phone** dashboard remains read-only and separate from
desktop/account/publishing controls. Setup does not install Tailscale or connect a phone automatically.

Final application validation: 1,278 fast checks passed in 579.81 s; 43 final built-browser checks passed
in 93.25 s, with all 17 tested frontend hashes unchanged; production build passed in 10.32 s.
All 14 media/restart scenarios passed across full and targeted runs: the full attempt passed 12
with two repeat-discovery fixture timeouts in 1153.68 s; after a fixture-only compressed-clock
cache correction, the two private/public repeat scenarios passed in 374.57 s. This was not one
all-green full-media run. The final pure health-cadence refactor is covered by the full fast suite
and 77 focused checks; all 39 media-scope source hashes were unchanged. Detailed evidence is in
the application CLAUDE_HANDOFF.md and launcher/plain_setup_verification.json.
Exact committed-source archive verification: 498 files with the six declared BAT CRLF
exports; 17 browser-tested frontend files. Final delivery validation:
48 installer checks (1.576 s), 13 pin-helper checks (0.598 s), 12 builder checks (0.019 s)
and 10 exact-export helper checks (0.739 s) passed; the pinned archive was independently verified
against exact committed Git source and the final tested frontend manifest. Final evidence and hashes are recorded
in launcher/plain_setup_verification.json and launcher/DELIVERY_CHANGELOG.md.
No owner Windows data, RTX3050 execution, actual account upload, real phone/Tailscale connection or 24-hour
unattended soak is claimed. GPU and other app dependency pins are unchanged.

## Rebuilding and verification

The readable installer and its disposable-profile checks are in launcher/plain_setup.py and
launcher/plain_setup_test.py. The builder checks the exact Python/bootstrap pins, archive/start bytes, safe
source-only paths and every packaged member; output is reproducible and replaced only after verification.
Generated launcher/app.zip is ignored by Git because the final source-setup ZIP already includes it.

Run these commands from this artifact branch:

    python launcher/plain_setup_test.py
    python launcher/pin_bundle_test.py
    python launcher/build_plain_zip_test.py
    python launcher/build_plain_zip.py

For a future app revision, independently verify and pin its archive using launcher/pin_bundle.py, which updates
the readable Python and historical PS/BAT source together and retains exact prior release hashes. Review the
updated pins and run all three Python suites; the source builder refuses out-of-sync launchers.
The older Go/PowerShell launcher sources remain available for history and inspection, not recommended delivery.

Current delivery evidence and limits are recorded in launcher/DELIVERY_CHANGELOG.md and
launcher/plain_setup_verification.json. Linux tests use disposable synthetic profiles, real local locks/ports
and mocked Windows APIs; they cannot establish native Windows or Defender acceptance.

## Checking the running PC

The separate ClipFoundry-Local-Check.zip remains a read-only optional diagnostic: extract it, keep ClipFoundry
open, and double-click Check-ClipFoundry.cmd. Enter the current browser port. Its bounded loopback GET report
excludes Brain text, media, account names, paths, tokens, job payloads and raw errors. It does not publish, change
Settings or install dependencies. Native Windows execution of that separate helper is also unverified.
