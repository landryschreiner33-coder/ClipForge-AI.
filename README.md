# ClipFoundry: bundled Windows setup

Download **ClipFoundry-Setup.exe**, close the previous launcher window, and
double-click the new file. Keep its console open while first-time setup finishes.
The app then opens in your browser. Use this same file for later sessions.

This executable includes the verified app archive. It makes no GitHub archive
request during installation. The previous Open-ClipFoundry.exe stopped after
three archive-download failures and hid their actual cause; this revision removes
that download step. The network-only BAT alternative now reports the real error.

The included app uses enabled saved Brain guidance automatically for new clips, with Settings filling every
unspecified choice. A bounded local interpreter recognizes caption/pacing goals and ranking priorities. Good
example lengths gently blend with the original target, once; raw uploaded appearance is not learned. The Brain
shows recognized choices and unsaved changes, with no separate Brain approval. Seven inactive integration
placeholder cards are removed. Real TikTok app/scope/per-post requirements and YouTube publishing consent remain.
Existing rendered clips and scheduled posts are preserved. The update retains prior managed 28aee85/7201047
profiles plus the 4838aa8 and 987ebb2 managed revisions and their original data folders; ordinary ZIP copies are not adopted.

The update also adds **Settings → Integrations → Check from your phone**. It starts an optional read-only
status dashboard on the PC's private address, separate from desktop/account/publishing controls. Tailscale on
both devices allows encrypted private access at home or away; trusted home Wi-Fi is optional. Open the shown
address on the phone and enter the PC's single-use pairing code. Codes expire after five minutes; hashed device
grants last up to 90 days and can be revoked from the PC. Keep the PC awake and ClipFoundry open. No Tailscale
installation, firewall/router change or publishing permission is made by this installer.

This revision fixes finished clips being left without post preparation after an interrupted render batch,
recovers eligible older handoffs, prioritizes accessible reusable sources, and stops parked permission/file waits
from blocking usable candidates. Stale YouTube consent cannot hide approval reminders. Setup includes explicit
audience and separate YouTube permission; Missions explains actual finished-clip stages and remaining holds.
No TikTok connection is required for YouTube. Existing audience choices, Private plans, canceled work, manual
edits, exact-file checks and owner data remain protected.

Python dependencies, GPU libraries and later speech-model downloads still need
internet access. This is not a complete offline distribution of those dependencies.
An existing Python installation and the usual FFmpeg requirements are unchanged.

The installer extracts the app into a fresh short folder, normally C:\CF14.
Occupied unknown folders are skipped; a writable local application folder is the
fallback. Upgrades from a verified copy created by this launcher use another
short folder and the **same original data folder**. Your Brain lessons, connected
accounts, settings, projects and saved media stay in place. Your old app files
and virtual environment also stay in place; the new app builds its own environment.
Close the previous ClipFoundry app/setup windows before opening the new installer.
A running managed copy or held profile lock stops setup without killing a process.

Ordinary ZIP installations and folders with an unknown or different-user marker
are not adopted. Accounts/settings from those copies are not migrated. Every
managed marker identifies its exact app revision and Windows user; its launcher
hash and original profile are checked before reuse. A modified or unverifiable
managed profile stops the upgrade rather than opening an empty replacement.

Installation roots stay at most 100 characters long. Archive paths are checked,
the generated wrapper folder is stripped, and installing over an existing folder
is refused. No administrator access, registry changes, Windows scheduled task or
publishing consent is created. A free local port is selected after dependency
setup. The same-user mutex covers setup and the running app.

## Integrity and verification

App revision: 718358f30110ab871e21059177f83ccd9ea3d3a9.
Included archive SHA-256:
2975806f4366bf2eba491b93e0634cf4f88083ce327657cf5ffc84456ac2d0cc.
The hash is checked before extracting any app files.

56 portable PowerShell checks passed, including zero archive-download requests
for good, missing and corrupt bundled inputs, owner-data preservation, occupied
ports, traversal refusal and proper error messages for network fallback. All 462
extracted app files match their archive hashes. Three Go tests verify preparing the
actual embedded payload/script, the pinned revision/start file, and preserving
existing files when preparation fails. Upgrade checks use synthetic Brain, token
and media files, two successive revisions and a real child process holding the
profile byte lock. Three Python build-helper checks cover retained old release
pins, matching BAT/script bytes and refusal of wrong revisions or traversal.
Core validation: 958 final fast tests, eight real-media/restart tests, seven final controlled browser checks,
and a production build passed. All 17 browser-tested frontend hashes match this archive. New focused cases cover
interrupted and old handoffs, cancellation, starvation, explicit YouTube-only setup, stale permission and read-only
posting-stage diagnostics. Actual FFmpeg/synthetic-speech loops verify Public/Private fake uploads, restart and live
recovery. No actual owner profile, Windows/RTX3050, real account upload or 24-hour soak was tested.
Native installer execution and actual phone/Tailscale connectivity remain unverified here.

The complete ZIP and bootstrap script were found byte-for-byte inside the built
Windows x64 console executable. The optional BAT script matches the embedded
bootstrap. Native Windows process discovery remains unverified; independent
source review found no blockers.

The executable is Windows x64 with the console subsystem, uses only Go's standard
library, and embeds both the checked setup script and complete app ZIP. Source is
in launcher/. It does not change execution-policy settings and is unsigned.
Native execution of this revised installer on Windows remains unverified here.
The user's previous screenshot confirmed the old Windows launcher reached its
archive-download step. The installer leaves existing app code and media intact;
GPU dependency pins remain unchanged.

## Rebuilding

Download and independently verify the exact revision ZIP from the app repository.
Pin it with the helper, which retains the previously known release hashes and
syncs the optional BAT bootstrap with the embedded PowerShell script:

    python launcher/pin_bundle.py --commit FULL_GIT_SHA --archive /path/to/verified-app.zip

The generated launcher/app.zip is not tracked separately in this artifact branch
because the executable already includes it. Run both sets of checks before building:

    powershell -NoLogo -NoProfile -File launcher/bootstrap_test.ps1
    go test launcher/main.go launcher/main_test.go
    python launcher/pin_bundle_test.py

Build using:

    GOOS=windows GOARCH=amd64 CGO_ENABLED=0 go build -trimpath -o ClipFoundry-Setup.exe launcher/main.go

Run the preparation checks with:

    go test launcher/main.go launcher/main_test.go

Executable SHA-256:
3fb98871f38dc9d0dffa126a16cfe9223e8cb5b6f3b8aebe4ba493f940e0cf26.

## Checking the owner's running PC

Download `ClipFoundry-Local-Check.zip`, extract it, keep ClipFoundry open, and double-click
`Check-ClipFoundry.cmd`. Press Enter for port 8765 or enter the browser's current app port. Send the resulting
JSON report in chat. It reads only the loopback app using bounded GET requests; it never tests a real platform,
posts, changes Settings or installs dependencies. A strict whitelist excludes note text, media, account names,
paths, tokens, job payloads and raw errors. Connected flags reflect saved app state, not a live account test.

Portable PowerShell syntax and synthetic tests verify the custom-port snapshot, GET-only requests, privacy
whitelist, missing-app and invalid-port handling. Native Windows execution remains unverified.

The source app's final full fast suite passed 814 checks (349.16 s); final focused regressions passed 96
(43.45 s). Eight synthetic media/restart cases passed (710.71 s) before the final duration/provenance review fixes,
which the final 814/96 checks cover. Eight final browser checks passed (45.5 s); production build passed (6.44 s).
No owner-PC/GPU, real account/model quality or actual 24-hour soak is claimed.
