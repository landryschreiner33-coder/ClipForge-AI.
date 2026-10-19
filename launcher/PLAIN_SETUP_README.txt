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
antivirus, execution-policy, trust/certificate, firewall or Windows scheduled-task setting. Python 3.11/3.12
and FFmpeg are recommended. Python/GPU packages and later speech models may still need internet access.

Do not turn off antivirus or restore/allow the previously blocked EXE. If Windows also blocks the ZIP or an
extracted file, inspect Windows Security / Protection history for the detection name. Source/integrity checks
do not certify antivirus acceptance. Native Windows and Defender were unavailable in the build environment.

Verified prior managed installations under the same Windows account retain their original Brain knowledge,
accounts, settings, projects and saved media. Unknown ordinary ZIP installations are not adopted; their data
stays in place. No old files or virtual environments are copied over or deleted. An active app/profile lock,
multiple original profiles or unverifiable same-user managed revision stops setup. Missing/malformed JSON
markers are treated as unknown installations and left untouched.

Application revision: fcd48aecece759ed676d871a9282d81b83f0ab92
Included app.zip SHA-256: c01eda46ba14dd26395f9f47dd83f6c4231815e0dff1de16497163e35e58d9ee
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

CLAUDE_HANDOFF.md inside the app has code, evidence and continuation details; ask Claude to read it and
AGENTS.md. Never share account keys or private app data. No owner profile, real account upload, native Windows,
Defender, RTX3050, real phone/Tailscale connection or 24-hour unattended soak was verified in this environment.
GPU and other application dependency pins are unchanged.
