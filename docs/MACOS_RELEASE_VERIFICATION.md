# Mac release verification

## Public downloads and Apple-silicon preview — 2026-11-02 (America/Chicago)

The owner explicitly requests a public download website and the full ClipFoundry workflow on an M5 Max.
Source branch: `codex/macos-download-site`, continued from 88386d6 with all prior Claude changes and the raw AAC
clock correction retained. Download-site source lives separately at `/workspace/sites/clipfoundry-downloads`;
Sites identity: `appgprj_6ae8b76d68108191bc36af565f138bed`, explicitly public. Its reserved address is
https://clipfoundry-studio.landryschreiner33.chatgpt.site . Publication/delivery records accompany the Mac ZIP.
The existing GitHub Pages/TikTok verification site, icon, Windows ZIP and blocked historical EXE are unchanged.

`macos/` builds a readable unsigned ZIP with a verified native ARM64 Python 3.12 runtime. First setup installs
Mac dependencies and obtains pinned FFmpeg/ffprobe directly from upstream, checking compressed and extracted
hashes. Code/environments are per-release; data stays in `~/Library/Application Support/ClipFoundry/data`.
Old releases/data are retained. Another running installation is not killed. First-run imports and a synthetic
H.264/AAC render with the production raw-clock check must pass before setup is marked complete.

New Mac credentials use AES-GCM and a per-profile login Keychain key, with no plaintext fallback. CPU Whisper
is a supported native path (no Metal ASR claim). Auto encoding checks VideoToolbox before choosing it, with
x264 fallback. Mac Autopilot uses a process-bound caffeinate request; the office no longer treats the absence
of an NVIDIA GPU as a Mac failure. YouTube/TikTok permission, review, limit and uncertain-upload behavior is unchanged.

Final Terminal-close correction: a real isolated POSIX watchdog test reproduced SIGHUP bypassing owned-app
cleanup. SIGHUP now follows the same shutdown path as Control+C. All 17 real-process launcher tests also passed
on native macOS ARM64, including Terminal-close cleanup. The final full suites passed against this correction.

**Verified:** complete fast suite **1,540 passed, 19 deselected in 528.40 s**; complete real-media/restart suite
**19 passed, 1,540 deselected in 1012.69 s**. No final failures or skips. Both ran on fresh public Ubuntu 24.04
CI runners against 18aacfe6cc6e893a9c5acdc15693775400a334ad. The native macOS 14 ARM64 job built the actual
package, installed its bundled runtime/dependencies, passed the production AAC timing check, performed a real
Keychain encryption round trip, acquired/released caffeinate, and served the HTTP API/bundled UI. Its virtual
runner did not expose VideoToolbox, so software fallback was exercised. CI evidence:
https://github.com/landryschreiner33-coder/ClipForge-AI./actions/runs/41492774348 . Release documentation added
after this run changes no tested application code. Frontend build passed. Website browser checks passed at
1440, 390 and 320 pixels with working keyboard setup tabs, no page errors and no horizontal overflow.

An earlier local full-suite run was interrupted by the resumed workspace; an initial slow run lacked the
speech-fixture tool on PATH. The tool was restored, and the slower local reruns were deliberately stopped after
fresh CI took over. Partial local results are not counted as passes. Native CI also independently passed on
7e30061. Mac archive contents and executable launcher modes are checked; no owner media, secrets, data folders,
virtual environments or design/test fixtures are bundled.

**Limits:** macOS version and Apple Developer membership remain unconfirmed. No physical M5 Max test,
Finder/quarantine interaction, Apple signing/notarization, real social upload, existing-upload repair, paid
enrollment or security-policy change was performed. Speech models download on first transcription; no Metal
speech acceleration is present. Reconnect Windows-protected accounts on Mac; existing profiles are not silently
migrated. Keep Terminal and the Mac awake. The stable Windows download remains at delivery fc7b199.
See `macos/README.md` and `docs/MACOS_RELEASE_VERIFICATION.md` for setup and verification details.
