# ClipFoundry: readable Windows setup

Download **ClipFoundry-Source-Setup.zip**, close the previous ClipFoundry/setup windows, right-click the ZIP
and choose **Extract All**. Open the extracted folder and double-click **Open-ClipFoundry.cmd**. Keep its
console open while setup finishes and the app runs. Use the same CMD file for later sessions.

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
certificate trust, firewall/router, Windows scheduled task or publishing permission is changed.

## Included application

The app is the unchanged, previously tested revision **718358f30110ab871e21059177f83ccd9ea3d3a9**. Its archive
SHA-256 is **2975806f4366bf2eba491b93e0634cf4f88083ce327657cf5ffc84456ac2d0cc**. Setup verifies the archive and
known start.bat hash before installing new code. Existing managed identity checks verify the marker and start
file, rather than claiming a full checksum of every file already present on the PC.

This build includes immediate finished-clip handoffs, bounded recovery of older eligible outputs, accessible
reusable discovery priority, YouTube-only audience/automatic-permission controls and **Missions → Why clips are
waiting to post**. Historical Private plans, manual edits, canceled work, exact-file checks and posting consent
remain protected. No TikTok connection is required for YouTube, and setup does not perform a real upload.

Enabled saved Brain guidance applies automatically to new clips, with Settings filling unspecified choices.
The optional **Settings → Integrations → Check from your phone** dashboard remains read-only and separate from
desktop/account/publishing controls. Setup does not install Tailscale or connect a phone automatically.

The app's final verification was 958 fast checks, eight actual-FFmpeg/synthetic-speech media/restart checks,
seven controlled browser checks and a production build. All 462 archived source files match the exact Git
revision, apart from six intentional BAT CRLF exports; all 17 browser-tested frontend file hashes match.
No owner Windows data, RTX3050 execution, actual account upload, real phone/Tailscale connection or 24-hour
unattended soak is claimed. The app source and dependency pins are unchanged by this delivery update.

## Rebuilding and verification

The readable installer and its disposable-profile checks are in launcher/plain_setup.py and
launcher/plain_setup_test.py. The builder checks the exact Python/bootstrap pins, archive/start bytes, safe
source-only paths and every packaged member; output is reproducible and replaced only after verification.
Generated launcher/app.zip is ignored by Git because the final source-setup ZIP already includes it.

Run these commands from this artifact branch:

    python launcher/plain_setup_test.py
    python launcher/build_plain_zip_test.py
    python launcher/build_plain_zip.py

For a future app revision, first independently verify and pin its archive using launcher/pin_bundle.py, then
update the readable installer's exact pins and retained release table and review them. The source builder refuses
out-of-sync launchers; pinning the historical PowerShell wrapper alone does not update the Python installer.
The older Go/PowerShell launcher sources remain available for history and inspection, not recommended delivery.

Current delivery evidence and limits are recorded in launcher/DELIVERY_CHANGELOG.md and
launcher/plain_setup_verification.json. Linux tests use disposable synthetic profiles, real local locks/ports
and mocked Windows APIs; they cannot establish native Windows or Defender acceptance.

## Checking the running PC

The separate ClipFoundry-Local-Check.zip remains a read-only optional diagnostic: extract it, keep ClipFoundry
open, and double-click Check-ClipFoundry.cmd. Enter the current browser port. Its bounded loopback GET report
excludes Brain text, media, account names, paths, tokens, job payloads and raw errors. It does not publish, change
Settings or install dependencies. Native Windows execution of that separate helper is also unverified.
