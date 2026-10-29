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

## Brain guidance, framing and upload timing

General Brain lessons tagged with platforms such as TikTok or YouTube Shorts can apply across subjects;
actual topic tags still narrow relevance. Recognized preferences guide selection and rendering, with Settings
filling unspecified choices. The clip editor shows the saved lesson titles and revisions actually used.
Unsupported prose remains reference material rather than becoming an editing command.

Automatic framing follows usable face/speaker tracks and can use measured visual motion when those tracks
are missing or lost. The quality report identifies that fallback as an estimate. Explicit Center and Manual
framing stay as chosen. These changes apply to newly rendered clips; existing files and uploads are preserved.

The default posting gap is **30 minutes**, without adding a daily cap. A one-time migration updates the old
saved zero; positive custom gaps and later explicit choices remain. Settings can change the gap or set it to
zero to disable pacing. Automatic pending collisions and already queued uploads are spaced across restarts
and platform waits. Explicit rescheduled times, valid content approvals and started/uncertain transfer
identities are preserved; a due post can still wait for its account's upload cooldown.

Queue can carry a valid **Make & upload clips** input's reuse statement onto its exact new posts, avoiding
retyping it when a clip needs quality or manual review. Freshly repaired generated output still needs passing
checks for its new bytes. Owner edits, changed destinations, old backlog and inputs without a valid saved
request can still require review. A local file alone grants no permission, and TikTok keeps per-post review.

## Audio and earlier fixes

This update fixes the invalid audio packet timestamps found in the supplied original clip.
Normal local playback could hide the damage; the matching YouTube copy contained a 2.22-second silent gap.
New renders rebuild the final clock from actual audio samples and check the stored timestamps independently.
The final quality gate now rejects this defect and refreshes old cached checks before a fresh upload starts.
Re-render affected local clips after updating. Already uploaded videos cannot regain their missing audio
without a corrected replacement. A real YouTube re-upload has not been tested.


The previous normalizer could boost a quiet opening and then sharply reduce the volume after a loud moment.
New normalized renders measure the entire edited audio timeline first and use one constant volume adjustment,
with peak headroom and a bounded boost. Initial silence, speech timing, first-track selection, speed changes,
stereo downmix and the final limiter are preserved. Very dynamic clips may be quieter than the -14 LUFS target.
Re-render an older affected clip from its source, preview it, and let fresh file checks run before uploading.
Existing uploads are not changed. The original source must itself contain usable audio.

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

Application revision: **88386d6cd4f4ede321d6f4d2fca406de67eba1cc**
Included app.zip SHA-256: **0cc389b2933c1ba5459267e19c7baedef49967f9785e7121277767fedc77aeb8**

Setup verifies the archive and known start.bat hash before installing new code. Existing managed identity
checks verify the marker and start file, rather than claiming a complete checksum of every installed file.
The release retains all fourteen prior exact managed-release pins and adds its own identity (fifteen total). Historical start-file SHA-256 remains
40cfe91a8c4818f6837d794beca0b610fa9d45863c381ea1dafd27c427e9f23c; the corrected launcher SHA-256 is
26f2cb1ee7fcbda369d160cb2c8d3d37506a3393fcb1be14e7b3b485cce6b8d1.

Current validation: 1,524 fast tests passed (1777.86 s); all 19 real-media/restart cases passed (2168.08 s), with no final failures or skips. Nine new raw-clock regressions pass. All 204 frozen Python source/test files match. The 17 previously built frontend files are unchanged. The supplied original fails the raw-clock check; a separate private copy passes after timing-only repair, with encoded video/audio packets and decoded audio unchanged. Owner media is excluded from the 524-file exact app export. Native Windows and a real corrected YouTube upload remain unverified.

The exact source export matches the committed app and tested frontend, with only the six declared BAT
CRLF exports. Final assembly verifies the four outer ZIP members byte-for-byte and both archive CRCs. Earlier
Windows runtime-selection, environment-preservation, audio and consistent TikTok-icon fixes remain included;
application/GPU dependency pins are unchanged. This continuation does not redeploy the public website.

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
