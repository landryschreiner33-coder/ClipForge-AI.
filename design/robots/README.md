# Robot assets

The office's 25 robots are authored pixel art built from their named identities and parts. The refined map uses
**PixiJS 8.22.0**; Team cards, robot details and the developer gallery share the same robot artwork through cached
Canvas portraits. **GSAP 3.15.0** provides pure easing curves for authored off-duty gestures, using the office's
visual clock without independent timelines. The Brain Core and original Canvas artwork remain available. No paid
image service, account or plugin connection is needed at runtime, and the drawing instructions can be edited as text.

| File | What it holds |
| --- | --- |
| `frontend/src/office/cast.ts` | The registry: id, name, title, rank, department, room, manager, palette, head, body, visor, top, gear, work loop, hand and base for every robot, plus CORE. `validateCast()` checks 1 Director, 8 managers, 16 workers, unique ids and that no two robots share head + visor + top + gear. |
| `frontend/src/office/StudioArt.ts` | Refined authored robot silhouettes, faces, shading, equipment, work poses and off-duty gestures/props. `createRobot()` builds a reusable rig for each existing identity; GSAP `parseEase` curves smooth the leisure gestures. |
| `frontend/src/office/StudioScene.ts` | Pixi office scenery, robot placement, department lights, health indicators and Brain Core. The map supplies actual feed-driven poses and handoffs. |
| `frontend/src/office/LoungeDecor.ts` | Authored arcade/café/board-game/sofa zones, optional cropped skyline windows, cached Pixi `BlurFilter` light pools and explicitly decorative game/steam ambience. |
| `frontend/src/office/OfficeMotion.ts` | Actual-state lounge/desk destinations and fresh document choreography: approach, pass, receive, then return to the latest destination. |
| `frontend/src/office/DepartmentDuty.ts` | Real-state attendance and honest work/support/supervisor duties. |
| `frontend/src/office/LoungeLife.ts` | Decorative identity-phased routines, exclusive activity reservations and at most two recreational visitors walking at once; no jobs or API writes. |
| `frontend/src/office/world.ts` | Department desks, 29 lounge activity places including 25 stable homes, room bounds, furniture footprints and walking routes. |
| `frontend/src/office/BrainCore.ts` | Authored neural sculpture with decorative standby, feed-driven processing and frozen paused/offline modes. |
| `frontend/src/office/LivingFallback.ts` | Original Canvas identities in the same floor plan, seated lounge/desk postures, document passes and simpler leisure props/gestures driven by the controller's activity phases. |
| `frontend/src/office/StudioPortraits.ts` | One lazy shared offscreen renderer for the roster, details and gallery; a bounded 512-frame cache of 48×68 Canvas images avoids a graphics context per portrait. |
| `frontend/src/office/Portrait.tsx` | A crisp Canvas portrait using the refined frame cache, with original artwork retained if the renderer/module cannot initialize. CORE uses its original drawing. |
| `frontend/src/office/sprites.ts` | Original artwork and pose definitions (`FRAMES`), retained for the complete Canvas fallback. Original cells are 48×64. |
| `frontend/public/office-art/skyline.png` | Original 2172×724 skyline generated once with native image generation, bundled locally as scenery. It is not robot art, job evidence or a runtime image-generation call. |
| `frontend/public/third-party-graphics.txt` | Bundled third-party notices, including GSAP 3.15.0's copyright header and standard no-charge license references. GSAP is not licensed under MIT. |
| `clipfoundry/office/roles.py` | The backend's copy of the same identities and which job kinds and stages each one owns. `tests/test_office.py` fails if the two lists differ. |
| `design/robots/contact-sheet.png` | A screenshot of the developer gallery (`#/dev/robots`, idle pose). |
| `design/robot-office/retro/README.md` | Evidence and provenance for the refined office graphics, kept separately from earlier captures. |
| `design/robot-office/living/` | New lounge, seated-work, room-camera and Brain evidence; actual isolated screenshots are separate from controlled visual transitions. |
| `design/robot-office/lounge/` | Later arcade/café/board-game/sofa evidence; controlled recreational recordings remain distinct from actual job or processing measurements. |
| `design/robot-office/departments/` | Complete-team, supervisor, Brain and receiver-office handoff evidence. |

## Rules the art keeps

* **Pixel geometry and anchor.** Refined robots use integer-sized parts, stepped silhouettes, highlights and shadows,
  with feet anchored at their desk or lounge place. Bodies and heads vary by identity and rank. Portraits use a 48×68
  image with feet positioned consistently; antialiasing and image smoothing are disabled. The map uses whole scale
  multiples when space permits and fits smaller windows with nearest-neighbor sampling.
* **Facing and identity.** The refined rig retains each robot's head shape, visor, top, gear and chosen hand. Side
  views shift the face, while the back view hides the face and shows its rear panel. The original fallback retains
  its separately drawn four directions.
* **Poses.** Both renderers consume the existing pose names: idle, work, walk, carry, review, wait, approved, rework,
  paused, unavailable, error and retry. The refined rig uses an eight-step walk, role-specific four-step work cues,
  a carried document, visible error accents and an approval check/raised hand. Both maps support standing, seated
  desk work and seated lounge rest; the fallback retains its original animation frames. Paused work poses dim their
  eyes unless explicitly showing off-duty recreation; unavailable robots fade. The HTML layer supplies truthful
  state icons.
* **Off-duty activities.** The 25 stable homes occupy five arcade, four café, eight board-game and eight sofa places;
  four extra guest places allow visits. Authored gestures show arcade controls, game pieces, lifting/tipping mugs,
  bites and plates, page turns, and rest. Robot identity, palette and equipment remain recognizable. Separate break
  activity/phase values drive these gestures; portraits default to their existing work/idle poses without recreation.
* **Department attendance.** Actual work or substantive assigned backlog gathers every department member into its
  room. A working robot appears immediately at its own desk; support teammates sit ready while remaining idle.
  Managers oversee from the `SUPERVISE` floor anchors with a clipboard and pointing gestures; their own jobs and
  real reviews use their desks. Quiet paused/unavailable peers retain their actual cues. Bare counts, stale paused
  tasks and unreferenced recurring timers do not summon a team. The `duty` field controls these visual differences
  without changing backend status. A completed worker remains while its team is busy, then returns to recreation.
* **Reservations and preemption.** Destinations are exclusive, with old and new places held until arrival. Phased
  15–28-second routines rotate eligible idle/waiting/retrying roles through free places, with at most two decorative
  walkers. Stopped-office paused roles may recreate while retaining their actual paused badge. An individually
  paused role while Running, or an unavailable role, stays quiet where department attendance places it. Work
  and genuine document transfers immediately release break reservations and take precedence; no leisure loop files
  reports, invents progress or changes durable jobs. Own jobs/reviews use desks; errors retain their cue.
* **Scenery and light.** Static floor, furniture backs, cropped skyline and softly blurred light pools are cached
  together once; blur is for lighting, not robot outlines. Arcade screens, café steam and board tokens are decorative
  room ambience. They freeze with the office's motion controls and never imply real processing. A missing skyline
  retains procedural window glass without disabling Pixi or the robots.
* **Document handoffs.** Fresh same-job stage changes keep the job kind and reference consistent. Cross-job
  transfers require the same reference, a 30-second window and one of three allowed pairs: hunt → analyze,
  package → quality check, or regenerate → package. Fresh reports can pass to the manager. Both robots meet inside
  the receiver's office, face each other, pass one document, show receipt and return to the latest desk/supervisor/
  lounge destination. A newer own job preempts leaving its office with an older outgoing document. Queued
  work alone and unrelated or old events create no transfer; paused/unavailable participants cancel it.
* **Brain sculpture.** CORE's slow standby orbit is decorative powered ambience. Brighter processing cues follow
  actual Brain work or fresh evaluation/lookup/strategy events. Clipped scan bands, travelling synapse trails,
  emitter sparks and orbital light trails do not measure progress. Paused and
  offline modes freeze it, and offline dims it. Reduced also freezes the art while its true state remains visible.
* **Real activity and motion choices.** Backend events and snapshots choose work poses and document handoffs. The art
  never creates work or progress. Follow system honors OS reduced motion, Full explicitly overrides it, and Reduced
  freezes movement and gestures while actual state indicators remain. Global Pause also freezes recreation; Reduced
  and Pause restore deterministic home positions. Hidden/stale views stop the leisure clock without catching up.
  Portrait frames share the same preference.
  Pause, Reduced, hidden tabs and stale feeds clear transfers. After suspension, a fresh authoritative snapshot
  restores the current sender before the next handoff. Feed-reset/backlog history is listed without animation;
  recent-looking historical stages and older snapshots cannot roll job ownership backward.
  The room camera magnifies a chosen room without changing work or robot state.
* **Fallback.** If the new scene module or graphics initialization fails, `OfficeMap.tsx` restores the original
  Canvas map, including all robot buttons, details and controls. It keeps simpler games, mug/food/book props and
  gestures on the same reserved places and controller phases; Full animates them and Reduced freezes them.
  Portrait module/context failures keep original Canvas sprites. No external setup is needed to activate either path.

## Adding or changing a robot

1. Edit its entry in `cast.ts` (and, for a new role, add the same id to `clipfoundry/office/roles.py` with the job
   kinds and stages it owns).
2. If it needs a new head, visor, top or gear, add the type name in `cast.ts`, its refined drawing in `StudioArt.ts`,
   and its original drawing in `sprites.ts` so the fallback stays complete.
3. Open the Office, Team and `#/dev/robots` in the running app; check every direction and pose, selection, Reduced
   motion and the original-art fallback. Check its unique default lounge place, seated desk, walking route, activity
   props and real-work preemption, whole-department attendance and manager supervision, plus room camera selection.
   Clear/reload after changing cached portrait artwork.
4. Run `python -m pytest tests/test_office.py` (the two registries must agree), `npm run build` in `frontend/`, and
   `sandbox/pixel-office.spec.ts`, `sandbox/living-office.spec.ts`, `sandbox/lounge-life.spec.ts` and
   `sandbox/department-office.spec.ts` with the isolated Playwright sandbox configuration. Record actual results
   separately; these instructions do not claim a passed run.

## Manifest

Generated from `cast.ts`; the gallery shows the same list.

| Id | Name | Role | Rank | Room | Manager | Head | Visor | Top | Gear | Work loop |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `command` | COMMAND | Director | director | boss | - | rounded-square | wide-cyan | crest | command-tablet | observe |
| `tracker` | TRACKER | Discovery Manager | manager | discover | command | radar-arch | binocular | radar-arch | map-tablet | map |
| `vector` | VECTOR | Analysis Manager | manager | analyze | command | trapezoid | split | bar-antennae | graph-badge | compare |
| `frame` | FRAME | Clip Studio Manager | manager | studio | command | director-helmet | horizontal | brim | clapper | scrub |
| `script` | SCRIPT | Caption Manager | manager | caption | command | keycap | bracket | none | proof-tablet | proofread |
| `clock` | CLOCK | Schedule Manager | manager | schedule | command | clock-ring | dial | side-dial | ticket-tablet | slot |
| `harbor` | HARBOR | Publish Manager | manager | dock | command | cargo | slit | mast | checklist | signal |
| `switch` | SWITCH | System Manager | manager | system | command | hex | lenses | none | tool-belt | inspect |
| `curator` | CURATOR | Learning Manager | manager | brain | command | dome | linked-dots | crown3 | cartridge | evaluate |
| `radar` | RADAR | Scout | worker | discover | tracker | oval | goggles | long-antenna | radar-pack | sweep |
| `archive` | ARCHIVE | Researcher | worker | discover | tracker | book | round-lenses | none | satchel | pages |
| `pulse` | PULSE | Trend Analyst | worker | analyze | vector | angular | equalizer | zigzag | graph-slate | plot |
| `gavel` | GAVEL | Source Judge | worker | analyze | vector | jaw | level | none | stamp | weigh |
| `spark` | SPARK | Moment Finder | worker | studio | frame | round | cyclops | star | waveform | markers |
| `story` | STORY | Story Editor | worker | studio | frame | soft-rect | panels | spine | storyboard | arrange |
| `boost` | BOOST | Viral Analyst | worker | analyze | vector | swept | angled | fins | curve-tablet | curve |
| `splice` | SPLICE | Video Editor | worker | studio | frame | wide | visor-band | ear-cups | reel-pack | render |
| `glyph` | GLYPH | Caption Agent | worker | caption | script | monitor | monitor-face | key-tabs | keyboard | type |
| `quill` | QUILL | Title Agent | worker | caption | script | slim-trapezoid | narrow | pencil | printer | draft |
| `check` | CHECK | Quality Control | worker | system | switch | square | inspection | none | scanner | scan |
| `lock` | LOCK | Audience Verification | worker | dock | harbor | steel-hex | lock | none | id-reader | verify |
| `dock` | DOCK | Publisher | worker | dock | harbor | box | square-eyes | uplink | parcel | load |
| `metric` | METRIC | Analytics Agent | worker | brain | curator | fin-round | display | bar-fins | notebook | collect |
| `synapse` | SYNAPSE | Learning Agent | worker | brain | curator | cap | soft | forked | node-pattern | connect |
| `patch` | PATCH | System Guardian | worker | system | switch | beacon | goggles | beacon | wrench | repair |

CORE (`core`, Brain Core) is a stationary object in the Brain Room, not a 26th robot. Department colors: Discover lime,
Analyze cobalt, Clip Studio magenta, Caption violet, Schedule orange, Upload Dock emerald, System amber, Brain lavender.
