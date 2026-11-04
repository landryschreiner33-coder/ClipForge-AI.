# ClipFoundry on Apple silicon

This preview includes the full workflow: Brain guidance, supplied video links/files, clip selection, moving
framing, captions, quality checks, scheduling, and supported YouTube/TikTok connections. TikTok retains its
individual platform review. Account/API setup and the platforms' limits still apply.

## Open it

1. Download **ClipFoundry-Mac-Apple-Silicon.zip** and double-click the ZIP to extract it.
2. Open the extracted folder and double-click **Open-ClipFoundry.command**. Keep the files together.
3. The first launch installs dependencies and downloads checksum-verified FFmpeg/ffprobe from their upstream
   distributor. It checks native imports and a synthetic H.264/AAC render, then opens your browser automatically.
4. Keep Terminal open while the app works. Use Control+C there before updating or shutting it down.

Requires an **Apple-silicon Mac (M1 or newer), macOS 14 or newer**, an internet connection for setup/models/accounts,
and free disk space for your original videos and rendered clips. M5 Max uses the native ARM64 runtime. Speech
recognition runs on Apple-silicon CPU through faster-whisper; it does not use Metal. Auto video encoding uses
VideoToolbox only after a successful hardware probe; x264 remains available.

This is an **unsigned setup preview**, not an Apple-notarized app. If macOS refuses to open it, read the alert and
use Apple's normal per-app opening instructions only if you trust this download. Do not disable Gatekeeper or
remove quarantine recursively. Apple guidance: https://support.apple.com/102445 . Native execution on an M5 Max
has not been verified by the Linux-based build/test environment; the launcher's native checks help expose issues.

## Your data and updates

The launcher keeps code/environments in `~/Library/Application Support/ClipFoundry/releases/` and data in
`~/Library/Application Support/ClipFoundry/data/`. Updates preserve previous releases and saved data. It does not
import or overwrite an existing manually installed profile. Windows-encrypted sign-ins cannot transfer to the Mac;
reconnect accounts there. New Mac credentials use an encryption key in your login Keychain. Allow the bundled
Python access when macOS asks, and keep that Keychain available.

Open the same launcher again to resume interrupted setup. Another active app is never killed automatically.
No global Python, Homebrew, administrator access, login item, or system power/security change is required. The app
can request protection from idle sleep while Autopilot runs; closing the lid, choosing Sleep, or turning the Mac
off still stops work. Whisper's model downloads on first transcription; that can add time to your first video.

The packaged runtime, dependency installation, synthetic audio-clock check, Keychain encryption, sleep request
and HTTP app startup passed on GitHub's native Apple-silicon macOS 14 runner. That virtual runner did not expose
VideoToolbox hardware encoding; Auto correctly used software encoding. Physical M5 Max and real account uploads
still need verification on the owner's Mac.

## Build provenance

`manifest.json` in the download records the full application commit and SHA-256 for the app, Python archive and
video tools. Python is the ARM64 python-build-standalone distribution; its included license files remain inside
the runtime archive. Video tools are fetched directly from the pinned upstream URLs, not redistributed in this
package. Optional AI services receive data only according to the app's settings and privacy policy.

For maintainers: `python macos/build_package.py --runtime-dir <verified-runtime-folder> --output <destination>`
packages only committed application files, the built UI, launcher and verified Python runtime. It rejects a dirty
source tree. Keep downloaded runtime files and package output outside the source repo.
