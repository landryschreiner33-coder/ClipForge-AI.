# Living pixel office

The owner requested believable proportions, lounge rest, seated work, visible document handoffs and an animated
Brain while retaining refined retro pixel art. This checkpoint starts at `a119dfd` on draft PR #14. It adds no
dependencies: the existing pinned PixiJS 8.22.0 renders authored geometry and robot rigs. No design account,
plugin connection or paid animation service is needed.

## What to try

Open **Office → Map**, select **Full** animations, and choose a room in **Camera** for a close view.
All 25 robots retain a stable identity and individual lounge seat. Idle, waiting, retrying, paused and unavailable
robots rest there; working/reviewing robots walk to their own desks and sit. Errors stay at their responsible desk.
Desks, chair heights, robot scale and clear corridors share a 960×640 floor plan. Table fronts cover seated laps
while bent knees, hands and typing remain visible. Room decor includes windows, books, plants, rugs and lamps.

A fresh confirmed job-stage change can bring two robots together. The sender carries one document, both stop and
face each other, the document passes hand to hand, and the receiver takes it. Both then return to the desk or
lounge seat required by the latest snapshot. Names and state icons stay accessible. Animation never delays work.
Cross-job transitions require the same fresh reference and a supported actual transition; predictions are not
animated. Old, queued and unrelated events do not invent a transfer. Pause or stale state cancels it; waking or
reconnecting starts from an authoritative snapshot, without replaying history or keeping an outdated sender.

The **Brain Room** contains a suspended neural sculpture with two pixel hemispheres, synapses and three depth
layers of orbiting lights. **CORE · Standby** is decorative powered ambience; **CORE · Processing** follows actual
Brain state/events. Brain pause, Reduced motion and offline state freeze the sculpture. Clicking CORE opens the
Brain workspace. The room camera and brighter processing mode do not change the Brain's learning behavior.

## Captures and provenance

Captured from the committed production frontend in Linux Chromium, against a disposable local app on port 8844.
No owner installation, account or normal data was used. The sandbox has no NVIDIA GPU, so its visible GPU error is
an actual health result. Windows font/scaling/graphics and RTX 3050 CUDA/NVENC remain PC checks.

| File | What it shows |
| --- | --- |
| [office-desktop.png](office-desktop.png) | Actual isolated snapshot at 1440×900: Autopilot stopped, 25 paused/unavailable/waiting robots resting, standby Brain, honest health. |
| [office-laptop.png](office-laptop.png) | Actual isolated snapshot at 1280×720 with a selected robot and visible bottom controls. |
| [office-details.png](office-details.png) | Actual RADAR selection, matching portrait and state/task details. |
| [office-mobile.png](office-mobile.png) | Actual List view at 390 px; no horizontal overflow. |
| [lounge.png](lounge.png) | Camera close view of actual individual lounge seats and states. |
| [brain-room.png](brain-room.png) | Camera close view of actual standby Brain; Reduced mode is selected. |
| [seated-work-controlled.png](seated-work-controlled.png) | Browser-only controlled running snapshot: SPLICE and SYNAPSE seated at their real station positions. |
| [handoff-controlled.png](handoff-controlled.png) | Browser-only controlled render→caption transition: SPLICE meets GLYPH and transfers the document. The phase badge identifies the captured phase. |
| [caption-desk-controlled.png](caption-desk-controlled.png) | Controlled GLYPH seated at the keyboard after receipt, while SPLICE returns to its lounge seat. |
| [brain-active-controlled.png](brain-active-controlled.png) | Controlled evaluating Brain and working SYNAPSE; Processing label and neural animation. |
| [living-office-controlled.mp4](living-office-controlled.mp4) | 35-second labeled controlled visual sequence: seated work, two-party document transfer, receiver at its desk, sender back in the lounge, Brain processing, lounge camera and Reduced stillness. |

Every controlled capture/recording has a visible **ANIMATION PREVIEW · CONTROLLED TEST STATES** banner. It injects
snapshots/events into the browser only, with the same job IDs, kinds, references and stage fields the actual API
uses. It verifies drawing/choreography and is not a real clipping run or a processing-speed benchmark. Actual
isolated screenshots above have no injected role or health state. Prior actual job and Brain-influence evidence
remains in [the earlier evidence folder](../screenshots/README.md).

## Editing and checking the design

| Source | Responsibility |
| --- | --- |
| `frontend/src/office/world.ts` | Room dimensions, robot scale, desks, stable lounge seats, furniture-aware routes. |
| `frontend/src/office/StudioArt.ts` | Authored cast identities, standing/seated/rest poses, hand and typing motion. |
| `frontend/src/office/StudioScene.ts` | Cached room decor, furniture depth, health/work lights and the single passing document. |
| `frontend/src/office/BrainCore.ts` | Layered sculpture, orbit/synapse animation and standby/active/paused/offline modes. |
| `frontend/src/office/OfficeMotion.ts` | Actual-state placement, bounded fresh transfers, ownership recovery and event ordering. |
| `frontend/src/office/OfficeMap.tsx` | Shared controller, DOM robot controls, room camera, labels and renderer lifecycle. |
| `frontend/src/office/LivingFallback.ts` | Matching Canvas compatibility floor plan, seating, Brain and document passes. |
| `frontend/src/office/studio.css` | Scoped shell, camera and legible labels. |

The canvas is decorative; DOM controls preserve each named robot's actual status and task details. Static scenery
is cached, the renderer is lazy, and existing shared portrait caching remains. Initialization/module failure
uses Canvas compatibility. Changes to room dimensions must keep workstations, rest seats, doors and routing in
sync. Keep Full / Reduced / Follow system, paused/offline stillness and accessible controls when changing the art.
Run the focused suite in [the e2e guide](../../../e2e/README.md) and rebuild/commit `frontend/dist`.

Exact validation results: [IMPLEMENTATION_STATUS.md](../../../docs/IMPLEMENTATION_STATUS.md).
