# ClipFoundry: bundled Windows setup

Download **ClipFoundry-Setup.exe**, close the previous launcher window, and
double-click the new file. Keep its console open while first-time setup finishes.
The app then opens in your browser. Use this same file for later sessions.

This executable includes the verified app archive. It makes no GitHub archive
request during installation. The previous Open-ClipFoundry.exe stopped after
three archive-download failures and hid their actual cause; this revision removes
that download step. The network-only BAT alternative now reports the real error.

The included app adds TikTok developer-form preparation, a simpler teachable Brain
with an interactive knowledge graph, and discovery that selects fewer stronger
videos. TikTok permissions and approval are still controlled by TikTok; the
installer does not connect an account or grant publishing consent.

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

App revision: 28aee85b4ef239584da296cec900bc3d8dde4399.
Included archive SHA-256:
7341bd5f506d79f608c31317dc631f540e117dff55a92e7ceb456c3e5d1de338.
The hash is checked before extracting any app files.

56 portable PowerShell checks passed, including zero archive-download requests
for good, missing and corrupt bundled inputs, owner-data preservation, occupied
ports, traversal refusal and proper error messages for network fallback. All 438
extracted app files match their archive hashes. Three Go tests verify preparing the
actual embedded payload/script, the pinned revision/start file, and preserving
existing files when preparation fails. Upgrade checks use synthetic Brain, token
and media files, two successive revisions and a real child process holding the
profile byte lock. Three Python build-helper checks cover retained old release
pins, matching BAT/script bytes and refusal of wrong revisions or traversal.
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
628f4ae43d72ece92cc42545c97d1712564cf1efdaf6f7a16f3f0c858a2457c0.
