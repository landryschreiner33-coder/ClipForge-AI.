# ClipFoundry: bundled Windows setup

Download **ClipFoundry-Setup.exe**, close the previous launcher window, and
double-click the new file. Keep its console open while first-time setup finishes.
The app then opens in your browser. Use this same file for later sessions.

This executable includes the verified app archive. It makes no GitHub archive
request during installation. The previous Open-ClipFoundry.exe stopped after
three archive-download failures and hid their actual cause; this revision removes
that download step. The network-only BAT alternative now reports the real error.

Python dependencies, GPU libraries and later speech-model downloads still need
internet access. This is not a complete offline distribution of those dependencies.
An existing Python installation and the usual FFmpeg requirements are unchanged.

The installer extracts the app into a fresh short folder, normally C:\CF14.
Occupied unknown folders are skipped; a writable local application folder is the
fallback. Existing installations, failed virtual environments, media and data are
left alone. Accounts/settings from an older copy are not migrated. Later launches
reuse only this launcher's revision/user marker and matching start.bat.

Installation roots stay at most 100 characters long. Archive paths are checked,
the generated wrapper folder is stripped, and installing over an existing folder
is refused. No administrator access, registry changes, Windows scheduled task or
publishing consent is created. A free local port is selected after dependency
setup. The same-user mutex covers setup and the running app.

## Integrity and verification

App revision: 7201047b795085f0cb608ea643efadf90074290c.
Included archive SHA-256:
90a197126d586d0b5ebcbb46fc08a4cd18a5f38f00f555612e6a73853ae7881a.
The hash is checked before extracting any app files.

30 portable PowerShell checks passed, including zero archive-download requests
for good, missing and corrupt bundled inputs, owner-data preservation, occupied
ports, traversal refusal and proper error messages for network fallback. All 416
extracted app files match their archive hashes. Two Go tests verify preparing the
actual embedded payload/script and preserving existing files when preparation
fails. Independent source review found no blockers.

The executable is Windows x64 with the console subsystem, uses only Go's standard
library, and embeds both the checked setup script and complete app ZIP. Source is
in launcher/. It does not change execution-policy settings and is unsigned.
Native execution of this revised installer on Windows remains unverified here.
The user's previous screenshot confirmed the old Windows launcher reached its
archive-download step. Default-branch app code and GPU pins are unchanged.

## Rebuilding

Save the exact revision ZIP from the app repository as launcher/app.zip and check
its SHA-256 above. That generated payload is not tracked separately in this
artifact branch because the executable already includes it. Build using:

    GOOS=windows GOARCH=amd64 CGO_ENABLED=0 go build -trimpath -o ClipFoundry-Setup.exe launcher/main.go

Run the preparation checks with:

    go test launcher/main.go launcher/main_test.go

Executable SHA-256:
98faf6aebf59f8696e938be8009692f492b0fff76d11dfff32944017b9107afc.
