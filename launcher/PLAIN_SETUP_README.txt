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

Application revision: 88386d6cd4f4ede321d6f4d2fca406de67eba1cc
Included app.zip SHA-256: 0cc389b2933c1ba5459267e19c7baedef49967f9785e7121277767fedc77aeb8
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

Brain guidance, framing and upload timing
- General Brain lessons tagged TikTok or YouTube Shorts can apply across subjects; actual topic tags still
  narrow relevance. The editor shows the lesson titles/revisions actually used. Unsupported prose remains
  reference material, Settings fills unspecified choices, and explicit clip edits take priority.
- Auto framing uses face/speaker tracks where available and measured visual motion when tracks are missing
  or lost. The quality report labels motion fallback as an estimate. Center and Manual remain as chosen.
  These changes apply to newly rendered clips; saved files and existing uploads are not rewritten.
- The default posting gap is 30 minutes, with no new daily cap. A one-time migration updates the old saved
  zero; positive custom gaps and later choices remain. Change the gap in Settings; zero disables pacing.
  Automatic collisions and queued uploads stay spaced after restarts/platform waits. Explicit rescheduled
  times and started/uncertain upload identities remain; account cooldown can delay an upload past its time.
- Queue carries an existing valid Make & upload clips input's reuse answer onto its exact new posts so you
  need not retype it during quality/manual review. Repaired generated output needs fresh passing checks.
  Owner edits, changed destinations, old backlog and inputs without a valid request can still need review.
  A local file alone grants no permission. TikTok keeps its per-post review.

Audio and earlier changes remain included

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

Current validation: 1,524 fast tests passed (1777.86 s); all 19 real-media/restart cases passed (2168.08 s), with no final failures or skips. Nine new raw-clock regressions pass. All 204 frozen Python source/test files match. The 17 previously built frontend files are unchanged. The supplied original fails the raw-clock check; a separate private copy passes after timing-only repair, with encoded video/audio packets and decoded audio unchanged. Owner media is excluded from the 524-file exact app export. Native Windows and a real corrected YouTube upload remain unverified.
The final source export matches the committed app and tested frontend, with six declared BAT CRLF
exports. The builder verifies every outer ZIP member byte-for-byte and both archive CRCs. Final pinning retains
all fourteen previous exact managed identities and adds the new revision (fifteen total). Earlier
Windows runtime-selection/environment-preservation, audio and consistent TikTok-icon fixes remain included.
This continuation does not redeploy the public website. Native Windows execution remains unverified.

CLAUDE_HANDOFF.md inside the app has code, evidence and continuation details; ask Claude to read it and
AGENTS.md. Never share account keys or private app data. No owner profile, real account upload, native Windows,
Defender, RTX3050, real phone/Tailscale connection or 24-hour unattended soak was verified in this environment.
GPU and other application dependency pins are unchanged.
