# Refined pixel robot office

This is the implemented PR #14 follow-up, built with **PixiJS 8.22.0**. No design service account or paid AI API is
needed. The artwork is authored in the app: each of the 25 robots keeps its own silhouette, equipment, palette and
rank. Layered rooms, wood desks, plants, monitors and a quieter navy shell make the office easier to read.

| Evidence | What it shows |
| --- | --- |
| [Desktop](office-desktop.png) | Actual isolated app, stopped, all 25 robots; 1440×900. |
| [Robot details](office-details.png) | Actual isolated RADAR state/details and matching refined portrait. |
| [Laptop](office-laptop.png) | Actual isolated app at 1280×720, map/details/controls together. |
| [Mobile](office-mobile.png) | Actual isolated app in List view at 390 px width. |
| [Cast](robot-cast.png) | All 25 authored robot identities rendered by Chromium/PixiJS; an art contact sheet. |
| [Animation preview](office-motion-controlled.mp4) | **Controlled browser test states/events**, visibly labeled: work, report carrying, a decision, then Reduced motion. This is not evidence of a processing job. |
| [Working preview](office-working-controlled.png) | Same controlled animation fixture, visibly labeled. |

Screenshots use the production frontend served by a disposable Linux sandbox with its own data and local fake
platform connections. They do not show owner accounts or real uploads. Earlier media/job and Brain evidence is
retained in [the previous checkpoint](../screenshots/README.md); those older images show its earlier art.

## Motion and compatibility

The actual app still animates from job snapshots and recorded events: work at the station, report handoffs to
managers and COMMAND's recorded decisions. It does not invent progress or activity. **Full** explicitly overrides
the OS motion preference; **Reduced** freezes the artwork; **Follow system** follows the OS. Paused/unavailable
robots stay still. An unavailable new graphics bundle/context leaves the original Canvas map and controls usable.
Team/detail portraits share one offscreen renderer and a bounded frame cache, avoiding a GPU context per card.
The static floor and furniture are cached once; room activity and robot poses remain separate live layers.
Verification: TypeScript/production build, 17 office Python tests and ten isolated motion/robot/graphics browser
cases passed. Browser screenshots recorded no errors. Windows installation, PC scaling and CUDA/NVENC were not
executed here; the controlled preview is not a hardware or processing benchmark.

## How to change the design

* [`StudioArt.ts`](../../../frontend/src/office/StudioArt.ts) defines pixel shapes, gear and pose offsets; the cast
  registry keeps the identity colors and features.
* [`StudioScene.ts`](../../../frontend/src/office/StudioScene.ts) defines furniture, floors and room lighting.
* [`studio.css`](../../../frontend/src/office/studio.css) styles the office header, panels, controls and responsive layout.
* The app's **Team** page shows every identity; `#/dev/robots` previews poses and directions. Change the source,
  then run `npm run build` in `frontend/` and include `frontend/dist` in the review build. Windows ZIP users need no Node.

PixiJS is the connected graphics library here; it needs no login or plugin connection. Figma could help plan later
layouts, and Rive could supply a separately authored rig, but neither is required by this implementation.
