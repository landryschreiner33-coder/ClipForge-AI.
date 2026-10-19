ClipFoundry source setup

1. Save edits and close the previous ClipFoundry/setup windows.
2. Right-click ClipFoundry-Source-Setup.zip and choose Extract All.
3. Open the extracted folder and double-click Open-ClipFoundry.cmd.
4. Keep its console open while setup prepares a short installation folder and opens the app.
   Use this same CMD file for later sessions.

Do not open the CMD from inside the ZIP. Keep Open-ClipFoundry.cmd, setup.py, app.zip and README.txt together.
Leave the inner app.zip zipped; setup opens it for you.

This package contains the exact app archive, readable Python setup.py and a plain CMD launcher. It uses your
installed Python. There is no custom EXE launcher, PowerShell loader or app-archive download. It changes no
antivirus, execution-policy, trust/certificate, firewall or Windows scheduled-task setting. This build requires
64-bit x86-64 CPython 3.12 or 3.11. The launcher checks installed runtimes, preferring 3.12 then 3.11, and does
not choose an unsupported newer or 32-bit Python from PATH. If none is found, install the Windows installer
(64-bit) from https://www.python.org/downloads/release/python-31210/, then reopen Open-ClipFoundry.cmd. Keep
other Python versions. ClipFoundry does not install a runtime automatically or change system PATH/registry.
FFmpeg is recommended. Python/GPU packages and later speech models may still need internet access.

Do not turn off antivirus or restore/allow the previously blocked EXE. If Windows also blocks the ZIP or an
extracted file, inspect Windows Security / Protection history for the detection name. Source/integrity checks
do not certify antivirus acceptance. Native Windows and Defender were unavailable in the build environment.

Verified prior managed installations under the same Windows account retain their original Brain knowledge,
accounts, settings, projects and saved media. Unknown ordinary ZIP installations are not adopted; their data
stays in place. No old files or virtual environments are copied over or deleted. An active app/profile lock,
multiple original profiles or unverifiable same-user managed revision stops setup. Missing/malformed JSON
markers are treated as unknown installations and left untouched.

The selected app folder's Python environment is checked before dependencies are installed. An incompatible
environment is preserved in a separate backup before a supported one is created. Brain knowledge, settings,
accounts and clips are outside that environment. An incompatible setup interpreter stops before profile or
installation writes; do not try to fix dependency resolution by deleting your saved data or changing GPU pins.

Application revision: 4fae46c82f5b14e3a54c451dee7ff5e3d948b21f
Included app.zip SHA-256: ab675182d3618c718a075b98f035a8cc5c0f8d2c702914f5659cd4f3de65fbae
Setup verifies the archive and known start.bat hash before installing or launching new app files.

New workflow: add a video, then make and upload clips
- Default intake is a video link or file you add in Missions. Automatic searching and watched-folder intake
  are off. No search API key is needed. Public recorded-video links must actually be accessible; private,
  protected, live and unavailable media is not bypassed.
- Connect the intended YouTube channel and confirm Who watches under Settings -> Integrations.
- In Missions, paste the link or choose a file and select Make & upload clips. The form shows the actual
  channel and saved Public/Private audience. Choose the correct made-for-kids answer, a truthful reuse basis
  covering video and sound, and confirm once for that submitted video.
- Relevant enabled Brain notes/example preferences guide supported selection/render choices, with Settings
  filling gaps. Passing finished clips schedule and upload automatically without separate per-clip review.
- The authorization covers only that submitted input. It does not approve older clips, other inputs or
  TikTok posts, and it does not change global platform toggles. Make clips only keeps results on this PC.
- Missions shows real progress and holds. Cancel video stops future work. Publishing pause, Stop, checks,
  posting windows, positive saved limits and actual provider waits remain active. Started/uncertain uploads
  keep their identity for recovery instead of restarting duplicates. Keep ClipFoundry open and the PC awake.
- Reuse answers stay outside Brain knowledge. Brain examples contribute measured duration and supported
  preferences/notes; their visual appearance is not learned from their pixels. Existing knowledge stays.

Audio and earlier changes remain included
- New renders use the same first audio track for transcription/output, downmix before normalization, preserve
  delayed starts/gaps and control peaks after gain. The checked output bytes are the bytes sent for upload.
- Synthetic-media checks cover decoded audio timing/frequency/peaks/distortion, real rendering through fake
  upload and restart recovery. Real YouTube transcoding is unverified. Already distorted source audio and
  previous uploads cannot be reconstructed by these filters; old clips need a newly checked render.
- Strict YouTube kids answers and audience evidence remain. Private/made-for-kids videos cannot have comments;
  other YouTube restrictions may apply. No audience is changed to force comments.
- Earlier Brain, office/handoff, selected-post review, live-capture and specific Windows socket-cleanup fixes
  remain. The phone dashboard is optional/read-only and still requires explicit pairing. TikTok keeps review.
- Optional discovery/key diagnostics remain under Settings -> Advanced -> Autopilot details -> Video input.
  Search keys are not required for submitted videos and do not grant upload authorization.

Current application validation: 1,489 fast checks passed (17 deselected, 527.16 s), including 38 focused
Windows-bootstrap checks (3.54 s in the focused run). All 203 frozen source/test/bootstrap/requirements
hashes stayed unchanged. Final delivery checks passed: 52 installer checks (1.500 s), 13 pin-helper checks
(0.514 s), 12 builder checks (0.012 s) and 10 exact-export-helper checks (0.426 s). The exact source export
verifies all 515 files and all 17 previously tested frontend hashes, with six declared BAT CRLF exports.
The builder verifies every outer ZIP member byte-for-byte and both archive CRCs. All eleven previous exact
managed release pins remain, plus the twelfth revision with the corrected start-file hash.

The previous submitted-video release passed 17 actual-media/restart checks and 59 built-browser checks.
These are historical results and were not rerun for this bootstrap-only update. Audio/render/upload/Brain
logic, dependency/GPU pins and all frontend source/build bytes are unchanged. New checks cover runtime
selection, environment preservation/rebuild/rollback and interpreter forwarding. Installer tests retain
historical release hashes and disposable Brain/accounts/media data. Native Windows execution is unverified.

CLAUDE_HANDOFF.md inside the app has code, evidence and continuation details; ask Claude to read it and
AGENTS.md. Never share account keys or private app data. No owner profile, real account upload, native Windows,
Defender, RTX3050, real phone/Tailscale connection or 24-hour unattended soak was verified in this environment.
GPU and other application dependency pins are unchanged.
