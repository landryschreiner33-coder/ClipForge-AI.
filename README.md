# ClipFoundry: readable Windows setup

Download **ClipFoundry-Source-Setup.zip**, close the previous ClipFoundry/setup windows, right-click the ZIP
and choose **Extract All**. Open the extracted folder and double-click **Open-ClipFoundry.cmd**. Keep its
console open while setup finishes and the app runs. Use the same CMD file for later sessions.

Do not open the CMD from inside the ZIP. In the extracted folder, keep **Open-ClipFoundry.cmd**, **setup.py**,
**app.zip** and **README.txt** together. Leave the inner **app.zip** zipped; setup opens it for you.

The ZIP contains those four inspectable files. It uses your installed Python and the normal application start
script, with no custom compiled launcher, PowerShell loader, app-archive download or administrator access.
This build requires 64-bit x86-64 CPython 3.12 or 3.11. The launcher checks installed interpreters and prefers
3.12, then 3.11; it does not select an unsupported newer or 32-bit Python just because it is on PATH. If none
is available, install the **Windows installer (64-bit)** from the official Python 3.12 release page:
https://www.python.org/downloads/release/python-31210/. Keep other Python versions and reopen the CMD afterward.
No Python runtime is installed automatically, and no system PATH or registry setting is changed by ClipFoundry.
FFmpeg is recommended. Python dependencies/GPU libraries and later speech-model downloads may still need
internet access. GPU and application dependency pins are unchanged.

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

The selected app folder's Python environment is checked before dependency setup. If it was created with an
unsupported Python, the app bootstrap preserves it in a separate backup and creates a supported environment.
Saved Brain knowledge, settings, accounts, source files and rendered clips are not part of that environment.
Setup stops before installation/profile writes if its own interpreter is incompatible.

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

Application revision: **4fae46c82f5b14e3a54c451dee7ff5e3d948b21f**
Included app.zip SHA-256: **ab675182d3618c718a075b98f035a8cc5c0f8d2c702914f5659cd4f3de65fbae**

Setup verifies the archive and known start.bat hash before installing new code. Existing managed identity
checks verify the marker and start file, rather than claiming a complete checksum of every installed file.
The new release retains all eleven prior exact managed-release pins and adds its own new start-file pin
(twelve total). Historical start-file SHA-256 remains
40cfe91a8c4818f6837d794beca0b610fa9d45863c381ea1dafd27c427e9f23c; the corrected launcher SHA-256 is
26f2cb1ee7fcbda369d160cb2c8d3d37506a3393fcb1be14e7b3b485cce6b8d1.

Current application validation: 1,489 fast checks passed (17 deselected, 527.16 s), including 38 focused
Windows-bootstrap checks (3.54 s in the focused run). All 203 frozen source/test/bootstrap/requirements
hashes stayed unchanged. Final delivery checks passed: 52 installer checks (1.500 s), 13 pin-helper checks
(0.514 s), 12 builder checks (0.012 s) and 10 exact-export-helper checks (0.426 s).

The previous submitted-video release passed 17 actual-media/restart checks and 59 built-browser checks.
Those are historical results, not reruns for this bootstrap-only update. Audio/render/publishing and Brain
logic, dependency/GPU pins and every frontend source/build byte are unchanged. The new focused checks cover
actual runtime rejection, safe environment preservation/rebuild/rollback and quoted interpreter forwarding;
the installer checks cover every historical start-file hash and unchanged disposable owner data. Official
PyPI Windows CPython 3.12 CTranslate2 wheel-resolution/hash evidence is recorded separately; no native Windows
runtime was available. The exact export verifies all 515 committed files and all 17 previously tested
frontend hashes, with six declared BAT CRLF exports and no extra or missing source files. The builder
verifies the four outer ZIP members byte-for-byte and both archive CRCs.

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
