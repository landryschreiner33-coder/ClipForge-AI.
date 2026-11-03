# Native ClipFoundry for Mac

This is the full local studio in a native app window. The canonical robot icon appears in Finder, the Dock,
the startup screen and About ClipFoundry. A DMG presents a drag-to-Applications installation.

**Release status:** Developer ID signing and Apple notarization are not configured yet. CI development builds
are ad-hoc signed so Apple-silicon machines can execute the test code. They are **not** approved downloads and
do **not** solve the downloaded-app Gatekeeper warning. Keep the public download unchanged until the release
workflow has produced a verified `mac-release.json` with both signing and notarization set to true.

## Normal use once the signed release is available

1. Open the DMG and drag ClipFoundry into Applications.
2. Launch ClipFoundry from Applications, Spotlight or the Dock.
3. Add your video and use the existing Brain, clipping, framing, captions, accounts and publishing workflow.

Python and video tools are inside the app. No Terminal, Homebrew, administrator password, global Python or
dependency installer is needed. The speech model downloads when first needed. Closing the window keeps the
local studio running; clicking the Dock icon brings it back. **ClipFoundry → Quit** stops its owned backend and
workers. Force Quit is detected by the parent guard and also stops the backend. The app must remain running
and the Mac awake for scheduled work. It does not promise unlimited platform posting or bypass upload reviews.

macOS 15 or newer and an Apple-silicon Mac are required. CPU transcription is supported; VideoToolbox is selected
only when the existing hardware encode probe succeeds. Physical M5 Max hardware has not been tested here.

## Data and updating

The app reuses `~/Library/Application Support/ClipFoundry/data`; replacing the .app does not replace Brain notes,
projects, schedules or settings. Mac account secrets retain their existing per-profile Keychain encryption.
Quit an older source-launcher session before opening the native app. An occupied profile or port produces an
explanation; it never kills another installation. Logs remain in `data/logs`. The native window's WebKit UI
preferences/cache are stored locally by macOS, separately from Safari/Chrome. No telemetry service is added.
OAuth opens in your default browser and returns to the existing local callback. The WebView has no native
JavaScript bridge, and only the owned loopback origin can navigate the studio window.

## Build and verify

On an Apple-silicon Mac with Xcode command-line tools:

```sh
brew install x264 libass dav1d pkg-config
python3 macos/build_desktop.py --work /tmp/clipfoundry-native-build
python3 macos/desktop_smoke.py --app /tmp/clipfoundry-native-build/ClipFoundry.app --evidence /tmp/clipfoundry-native-evidence
```

Homebrew is used **on the build machine only**. The builder compiles pinned FFmpeg 9.0.2, relocates its exact
runtime dylibs, and includes media licenses plus a matching source archive. It rejects nonfree FFmpeg builds.
Python wheels retain their installed notices; their exact URLs/hashes are recorded in `ThirdParty/python-install.json`.
The builder uses the committed application/frontend, not untracked data or personal media. CI exercises native
imports, H.264/AAC timing, Keychain, idle-sleep handling, the WebView and clean/forced shutdown on isolated profiles.

To make a development DMG, install `dmgbuild==1.6.7` in a separate build-only venv, then run:

```sh
python macos/package_desktop.py --app /tmp/clipfoundry-native-build/ClipFoundry.app --output /tmp/ClipFoundry-Development.dmg
```

That image is still **not notarized**. A DMG extension and an icon do not confer Apple trust.

## Finish Apple signing (owner setup, one time)

Check **Membership details** at https://developer.apple.com/account/ . An active Apple Developer Program membership
is required to create a **Developer ID Application** certificate. Apple documents the process at
https://developer.apple.com/developer-id/ and
https://developer.apple.com/documentation/security/notarizing-macos-software-before-distribution .
The owner must complete any enrollment/payment themselves. Never put passwords, certificates or private keys
in chat, repository files, issues, screenshots, or shell history.

For CI, create the GitHub environment `macos-release` and store these as encrypted environment secrets:

| Secret | Value |
| --- | --- |
| `DEVELOPER_ID_P12_BASE64` | Base64 of the exported Developer ID Application certificate **and private key** |
| `DEVELOPER_ID_P12_PASSWORD` | Export password protecting that P12 |
| `APPLE_SIGN_IDENTITY` | Full `Developer ID Application: … (TEAMID)` identity |
| `NOTARY_PRIVATE_KEY` | App Store Connect notarization API private key contents |
| `NOTARY_KEY_ID` | Matching Apple key ID |
| `NOTARY_ISSUER_ID` | Matching team API issuer ID |

The signed-release workflow accepts only a successful Native Mac desktop app run from this repository, uses its
exact app artifact, signs all nested native code with hardened runtime and timestamps, notarizes/staples the app,
tests that signed app, then creates/notarizes/staples/assesses the DMG. Signing material exists only in a temporary
CI keychain that is deleted afterward. It publishes nothing if credentials, signatures, Apple acceptance,
native tests, stapling, or Gatekeeper assessment fail. Keep corresponding source beside the DMG.

Alternatively, use `release_desktop.py` on a Mac with an existing Developer ID identity and securely stored
`notarytool` Keychain profile; `--help` lists paths and public identity arguments. No secret arguments are needed.

The download website should point to the resulting immutable release asset and show its exact SHA-256. Apple
may still show the normal first-open “downloaded from the Internet” confirmation; notarization removes the
unverified-developer override requirement, not all operating-system confirmations.
