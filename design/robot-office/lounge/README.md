# Social pixel office

This follow-up starts at `5b1f7a9` on draft, unmerged PR #14. The owner requested better graphics tools and
off-duty robots that play, eat and drink. The refined retro style now has five original arcade cabinets,
two shared board-game tables, a café and reading sofas, with warm light pools and a custom dusk city panorama.

Open **Office → Map → Full animations → Camera: Lounge**. Robots operate joysticks, press buttons, reach for
game pieces, lift and tilt mugs, take bites, turn pages and stretch. Each keeps its cast identity. There are
29 reserved activity places for 25 robots; at most two decorative walkers change activities at once. Work
and actual document transfers take priority and clear leisure props. Job icons and accessible labels retain
the real status, including stopped workers marked Paused. Recreation never starts or changes a job.

**Reduced**, actual global **Pause**, hidden tabs and disconnected views freeze recreation. Individually
paused workers during a running session and unavailable workers remain quiet. Actual job/report events still
drive seated work and document passing; old events are never replayed as live transfers.

## Graphics tools used

* **PixiJS 8.22.0** paints authored pixel furniture and robot rigs. Its BlurFilter supplies soft light pools;
  static scenery is cached, and moving props use the existing bounded office render loop.
* **GSAP 3.15.0** supplies pure easing functions for articulated gestures. It adds no autonomous animation
  clock. Its no-charge standard license and copyright notice are included in
  [third-party-graphics.txt](../../../frontend/public/third-party-graphics.txt).
* **OpenAI image generation** created the original fictional dusk panorama. The untouched 2172×724 image is
  bundled locally as [skyline.png](../../../frontend/public/office-art/skyline.png). Source provenance is in
  [office-art/README.txt](../../../frontend/public/office-art/README.txt). No stock/game pack or design account
  is needed at runtime. An absent or stalled optional image leaves procedural windows and usable controls.
* **Chromium/Playwright** checks actual painted pixels, motion freezes, current job states and layout.

The Canvas compatibility renderer shares the same controller, spots and phases, with simpler furniture and
gestures. A failed graphics bundle still leaves robot details, motion controls and the office usable.

## Captures and provenance

The production frontend is captured in Linux Chromium against a disposable app on port 8844. Actual screenshots
use the stopped sandbox snapshot, without injected role/health states. Its NVIDIA health error is real for
this environment. Windows graphics/scaling and RTX 3050 CUDA/NVENC remain PC checks.

| File | What it shows |
| --- | --- |
| [office-desktop.png](office-desktop.png) | Actual 1440×900 office, refined rooms, all 25 identities and true states. |
| [lounge-games.png](lounge-games.png) | Full-motion lounge camera with arcades, shared tables, café and sofas. |
| [lounge-coffee.png](lounge-coffee.png) | A later actual animation frame with controller-driven leisure gestures. |
| [brain-room.png](brain-room.png) | Actual decorative standby Brain and dusk window. |
| [office-details.png](office-details.png) | Actual selected RADAR and its matching status/detail panel. |
| [office-laptop.png](office-laptop.png) | Actual 1280×720 layout with all 25 and visible controls. |
| [office-mobile.png](office-mobile.png) | Actual 390 px List view without horizontal overflow. |
| [lounge-life.mp4](lounge-life.mp4) | Actual stopped snapshot: decorative activities and roaming, Brain camera, then Reduced stillness. |
| [handoff-controlled.png](handoff-controlled.png) | Browser-only controlled stage event: one document passes from SPLICE to GLYPH. |
| [office-work-controlled.mp4](office-work-controlled.mp4) | Labeled browser-only running/Brain/stage fixtures: seated work, document approach/pass/receipt and return. |

The lounge video has an **OFF-DUTY ANIMATION · ACTUAL STOPPED SANDBOX** banner. The work preview and controlled
captures show **ANIMATION PREVIEW · CONTROLLED TEST STATES**. Neither measures clipping speed or GPU performance.
No owner account, normal data, job start or real upload is used. Earlier evidence stays in
[living](../living/README.md) and [screenshots](../screenshots/README.md).

## Editing the result

| Source | What to change |
| --- | --- |
| `frontend/src/office/LoungeDecor.ts` | Arcade/café/game/sofa furniture, decorative screens and cached light pools. |
| `frontend/src/office/world.ts` | Activity anchors, real desk positions, ground footprints and obstacle-aware routes. |
| `frontend/src/office/LoungeLife.ts` | Reservations, fair activity rotation and controller-owned gesture clocks. |
| `frontend/src/office/StudioArt.ts` | Authored robot gestures, props, easing and cast identities. |
| `frontend/src/office/StudioScene.ts` | Pixi lifecycle, room decor, real state lights and render integration. |
| `frontend/src/office/OfficeMotion.ts` | Real work priority, current-state destinations and confirmed document transfers. |
| `frontend/src/office/LivingFallback.ts` | Simpler Canvas scenery and matching controller-driven leisure. |
| `frontend/src/office/studio.css` | Scoped shell, camera and robot labels. |

Keep artwork, spot anchors and ground footprints aligned. Do not use decorative motion to manufacture progress.
Run the five-file focused browser command in [e2e/README.md](../../../e2e/README.md), then build and commit
`frontend/dist`. Exact checkpoint results: [IMPLEMENTATION_STATUS.md](../../../docs/IMPLEMENTATION_STATUS.md).
