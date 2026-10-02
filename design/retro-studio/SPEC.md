# ClipFoundry retro studio

Implemented from the owner's 2026-10-02 written brief, on default commit `992431e`.
No mockup images were attached to this session. The written palette and behavior requirements guide the artwork.

The studio uses navy #0B1421, slate #152236, cream #F4EBD7 and amber #F5B94C.
Original pixel robots, scenery, desks and the local Foundry Pixel heading font are repository assets;
there are no external art, font requests, animation libraries, sound, canvas loops or GPU filters.
`generate_font.py` is optional development tooling, using fontTools to reproduce the committed original font.
All controls, dates, forms and supporting text use the system font. Video previews retain their original rendering.
Measured contrast is 13.48:1 for cream on slate, 8.57:1 for supporting text on raised panels, 6.64:1 for muted
text on raised panels, 9.69:1 for primary-button text and 4.65:1 for control borders on slate. Decorative panel
separators use a quieter color; controls and visible keyboard focus use stronger edges.

## Real activity mapping

All stations share the existing status poll. The backend supplies the current job kind and fresh progress.

| Station | Existing jobs |
| --- | --- |
| Finder | trend_scan, source_scout, feed_scan, identify_link, live_watch |
| Editor | hunt_source, analyze_source, regenerate_clip, live_capture, post_live, package_clip |
| Checker | rights_check, quality_check, maintenance, selftest |
| Scheduler | schedule_tick, publish, learn |

Multiple fresh active jobs can animate concurrently. A stale heartbeat, terminal/missing job, unavailable host,
paused/stopped app or lost connection stops processing animation. Waiting jobs rest with their reason. Genuine
Needs you items cause a brief wave and steady warning; normal failures remain in Activity. An observed
working-to-completed transition gives one brief success gesture, then rests. A completed job missed between polls
is not invented. Each station is an ordinary keyboard-accessible button that reveals its activity and any reported
percentage. A file handoff is omitted when the backend cannot confirm an individual transition.

Operating-system reduced motion and Settings → Defaults → Appearance each disable motion. The app preference is
saved in local browser storage and synchronizes across tabs. Hidden tabs pause decoration. There is no sound.

## Screens and safeguards

Home puts blocking action items first, followed by a compact studio and recent clips/posts. Autopilot leads with
Start/Pause, then the studio alongside durable link intake at laptop width. Activity, Permissions & sources,
Advanced, actual keep-awake, search times and posting distinctions remain available. On narrow windows link intake
moves above the studio, and robot stations wrap. Library searches source name/file/address and distinguishes
original videos and generated clips. Posts group by the configured local calendar day, keeping history and exact
publishing states. The editor keeps its vertical preview, timeline, five tool sections, versions, dirty-state and
render validity. Shared styling covers setup, forms, account connections, dialogs, empty/loading/error states.

Routes, aliases, browser Back, unsaved-change guards, user settings/data, CUDA dependencies, consent, rights,
exact-file checks and upload reconciliation are preserved.

## Verification artifacts

`screenshots/` contains actual Chromium captures of the implemented application using disposable local data.
The populated pages use real FFmpeg output from the complete-loop sandbox and synthetic imported transcripts;
accounts and metrics are local platform stand-ins. The disconnected capture deliberately refuses status requests
in that browser. Empty/error/resting captures use a fresh disposable app. Reduced-motion captures use the browser's
OS preference. A 683×384 CSS viewport represents the layout available at 200% zoom on a 1366×768 display.

`e2e/sandbox/robot-office.spec.ts` uses controlled responses for state/animation contracts; those responses are not
claims of live work. `zero-touch-loop.spec.ts` captures actual worker activity during real local pipeline work.
All screenshot fixtures are synthetic; no user projects, credentials or real account information are included.
See `docs/IMPLEMENTATION_STATUS.md` for final checks and counts.

Representative captures: `home.png`, `working.png`, `waiting.png`, `restarted.png`, `paused.png`,
`disconnected.png`, `library.png`, `source-video.png`, `editor.png`, `posts-agenda.png`, `post-review.png`,
`settings.png`, `setup.png`, `add-video.png`, `error.png`, `autopilot-reduced-motion.png` and
`autopilot-zoom-200.png`. Empty-page and editor zoom captures are also retained.

Real RTX 3050 performance, Windows keep-awake, real Whisper CUDA and actual platform uploads cannot be measured
in this Linux CPU cloud environment. No GPU dependency changes were made.
