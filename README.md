# ClipFoundry: readable Windows setup

Download **ClipFoundry-Source-Setup.zip**, close the previous ClipFoundry/setup windows, right-click the ZIP
and choose **Extract All**. Open the extracted folder and double-click **Open-ClipFoundry.cmd**. Keep its
console open while setup finishes and the app runs. Use the same CMD file for later sessions.

Do not open the CMD from inside the ZIP. In the extracted folder, keep **Open-ClipFoundry.cmd**, **setup.py**,
**app.zip** and **README.txt** together. Leave the inner **app.zip** zipped; setup opens it for you.

The ZIP contains those four inspectable files. It uses your installed Python and the normal application start
script, with no custom compiled launcher, PowerShell loader, app-archive download or administrator access.
Python 3.11/3.12 and FFmpeg are recommended. Python dependencies/GPU libraries and later speech-model downloads
may still need internet access. GPU and application dependency pins are unchanged.

Windows blocked the prior ClipFoundry-Setup.exe download. Its detection name is unknown, so a false positive
is not established. The historical unsigned executable is no longer the recommended download; do not restore
or allow it, disable antivirus or add exclusions. This source ZIP is a readable delivery method, not an
antivirus certification. If Windows blocks the ZIP or its extracted files, inspect the reported detection.
Native Windows execution and Defender acceptance were not available in this Linux environment.

## Existing installations and data

Verified installations created by the earlier managed launcher, under the same Windows account, retain their
original data folder. Brain lessons, connected accounts, settings, projects and saved media stay in place.
New app code goes into a fresh short folder with its own virtual environment. Old app files, data and virtual
environments are neither copied over nor deleted. Ordinary ZIP installations and unknown/different-user
markers are left untouched and are not automatically adopted; their data is not migrated.

Managed markers use the same Windows SID, v1/v2 formats, exact release/start-file pins and original profile
identity as the earlier launcher. Multiple original profiles, unverifiable same-user managed revisions,
linked profile paths or held profile locks stop setup. Missing/malformed JSON markers are treated as unknown
installations and left untouched. A same-user named mutex covers setup and the running app. An active managed
Python process prevents a second app from opening the same data; no process is terminated.

Installation roots are at most 100 characters, normally under C:\CF14, with a writable local application
folder as fallback. Occupied unknown destinations are skipped. Owned staging, checked archive paths and an
exclusive directory move prevent merging into an existing root. Setup runs before selecting a free loopback
port. The original data directory remains the CLIPFOUNDRY_DATA location. No execution-policy, antivirus,
certificate-trust, firewall/router or Windows scheduled-task setting is changed.

## Add your video, then make and upload clips

Automatic searching and watched-folder intake are off by default. In **Missions**, paste a publicly accessible
recorded-video link or choose a file. This workflow needs no YouTube search key or Tavily key. Media access,
model downloads and the connected YouTube upload account still need their normal setup and network access.
Live/private/protected/unavailable links are not bypassed.

Connect the intended YouTube channel in **Settings → Integrations**, then confirm **Who watches**. Back in
Missions, choose **Make & upload clips**. The form shows the actual channel and saved Public or Private
audience. Answer whether these clips are made for kids, choose a truthful reuse basis covering the video and
sound, and confirm once for this submitted video.

ClipFoundry consults relevant enabled Brain notes and example preferences, uses Settings for unspecified
choices, selects strong moments, renders vertical clips with captions, checks the finished output and schedules
qualifying clips for automatic YouTube upload. There is no separate approval for each qualifying clip from
this input. A request applies only to that submitted video; it does not authorize old review backlog or other
inputs, change global platform toggles, or grant TikTok publishing approval. **Make clips only** keeps the
results on this PC for editing, export or later review.

Missions shows actual creation/upload counts and hold reasons. **Cancel video** stops future work; publishing
pause, emergency Stop, quality checks, missing/changed media, account/audience changes, posting windows,
configured positive caps and actual platform waits still apply. An already started or uncertain upload keeps
its original identity for reconciliation rather than starting a duplicate. Keep the app open and the PC awake.
Zero daily caps mean no app daily cap, not unlimited platform quota or guaranteed clips from weak input.

Reuse explanations stay with the submitted video's upload authorization or exact reviewed posts, outside
Brain knowledge. Brain examples supply measured duration and supported saved preferences/notes; the app does
not learn their visual appearance from their pixels. General reference text remains searchable. Explicit
clip-editor changes take priority. Existing Brain content and rendered/uploaded clips are retained.

## Audio and earlier fixes

New renders select the same first audio track for transcription and output, downmix before normalization,
preserve delayed starts and gaps in clip-relative time, and apply final peak control after volume changes.
Final checks inspect the exact output before upload; upload uses the checked bytes. Synthetic-media tests
measure decoded AAC timing, frequency, peaks and distortion, and exercise real render-to-fake-upload plus
restart recovery. They do not establish a real YouTube transcode result. Distortion already present in the
source or earlier uploaded clips cannot be repaired by a limiter. Existing clips need a newly checked render
to receive these processing fixes.

YouTube made-for-kids answers remain actual Yes/No values. Private and made-for-kids videos cannot receive
comments; YouTube may also restrict comments for other reasons. The app does not change audience/kids choices
to force comments, and the upload API has no general guaranteed enable-comments switch.

Earlier fixes remain included: Brain guidance through selection/render, realistic office worker/manager/boss
handoffs, quick single/bulk YouTube review for old posts, live separate-track capture and bounded ended-recording
recovery, specific Windows disconnected-socket cleanup, and the optional read-only phone dashboard. TikTok keeps
individual review and supported manual/inbox/direct routes. The phone dashboard still requires explicit pairing.

Optional discovery remains available under **Settings → Advanced → Autopilot details → Video input**. Its
saved-key diagnostics and bounded recurring provider-local searches remain available in that mode. Search
connection tests make explicit credential checks without importing or uploading videos. Optional keys and
provider allowances are not needed for the default submitted-video workflow. Never share keys or private app
data in chat or a Claude handoff.

## Exact application and verification

Application revision: **fcd48aecece759ed676d871a9282d81b83f0ab92**
Included app.zip SHA-256: **c01eda46ba14dd26395f9f47dd83f6c4231815e0dff1de16497163e35e58d9ee**

Setup verifies the archive and known start.bat hash before installing new code. Existing managed identity
checks verify the marker and start file, rather than claiming a complete checksum of every installed file.
All ten prior exact managed-release pins are retained, plus this new revision (eleven total).

Final application validation: 1,451 fast checks passed (17 deselected, 676.07 s); all 17 actual-media and
restart checks passed together (1,451 deselected, 934.97 s). All 59 final built-browser checks passed in
161.548 s; TypeScript and the production build passed (10.00 s). All 17 tested frontend files and 81 frontend
source files stayed unchanged. The final fast run retained all 198 frozen backend/test hashes. The media run
used identical production and selected-media-test bytes; an unrelated fast retention fixture was corrected
before the final fast run. Seven screenshot-framing-only rechecks passed in 13.332 s with no product or
contract-assertion changes.
Final delivery validation: 48 installer checks (1.480 s), 13 pin-helper checks (0.518 s), 12 builder checks
(0.012 s) and 10 exact-export helper checks (0.396 s) passed. The builder checks all four outer ZIP members
byte-for-byte and both archive CRCs.
All 513 archived source files match the committed Git revision except six intentional BAT CRLF exports;
all 17 browser-tested frontend files match. The pinned app.zip is 42,001,568 bytes. No extra/missing source
files, EXE/DLL or runtime/credential paths are included. An independent exact-export check verifies the
pinned archive against Git and the final browser manifest.

Tests use isolated data, synthetic media and fake platforms. Native Windows/Defender, the owner's data or
RTX3050, real account uploads, phone/Tailscale pairing and a 24-hour unattended soak remain unverified.
The included **CLAUDE_HANDOFF.md** records the implementation, evidence and remaining checks; ask Claude to read
that file and AGENTS.md before continuing. Current delivery evidence is recorded in
launcher/DELIVERY_CHANGELOG.md and launcher/plain_setup_verification.json.

## Rebuilding

The readable installer and disposable-profile checks are in launcher/plain_setup.py and
launcher/plain_setup_test.py. The builder verifies exact Python/bootstrap pins, safe source-only paths,
archive/start bytes, all four package members and both archive CRCs; it replaces output only after verification.
Generated launcher/app.zip is ignored by Git because the final source-setup ZIP already includes it.

Run from this artifact branch:

    python launcher/plain_setup_test.py
    python launcher/pin_bundle_test.py
    python launcher/build_plain_zip_test.py
    python launcher/build_plain_zip.py

For future app revisions, independently export/verify committed app bytes and the browser-tested frontend,
then use launcher/pin_bundle.py. It updates readable Python and historical PS/BAT source pins together while
retaining prior release hashes. The older Go/PowerShell launcher sources remain available for inspection;
they are not the recommended delivery.

The separate **ClipFoundry-Local-Check.zip** remains an optional read-only diagnostic: extract it, keep the app
open and double-click Check-ClipFoundry.cmd. Enter the current browser port. Its bounded loopback GET report
excludes Brain text, media, account names, paths, tokens, job payloads and raw errors. It does not publish,
change Settings or install dependencies. Native Windows execution of that helper is also unverified.
