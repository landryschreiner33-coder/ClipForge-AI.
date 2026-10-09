# Robot assets

The office's 25 robots are authored pixel art built from their named identities and parts. The refined map uses
**PixiJS 8.22.0**; Team cards, robot details and the developer gallery share the same robot artwork through cached
Canvas portraits. The Brain Core and original Canvas artwork remain available. No paid image service, account or
plugin connection is needed, and the drawing instructions can be edited as text.

| File | What it holds |
| --- | --- |
| `frontend/src/office/cast.ts` | The registry: id, name, title, rank, department, room, manager, palette, head, body, visor, top, gear, work loop, hand and base for every robot, plus CORE. `validateCast()` checks 1 Director, 8 managers, 16 workers, unique ids and that no two robots share head + visor + top + gear. |
| `frontend/src/office/StudioArt.ts` | Refined authored robot silhouettes, faces, shading, equipment and pose animation. `createRobot()` builds a reusable rig for each existing identity. |
| `frontend/src/office/StudioScene.ts` | Pixi office scenery, robot placement, department lights, health indicators and Brain Core. The map supplies actual feed-driven poses and handoffs. |
| `frontend/src/office/StudioPortraits.ts` | One lazy shared offscreen renderer for the roster, details and gallery; a bounded 512-frame cache of 48×68 Canvas images avoids a graphics context per portrait. |
| `frontend/src/office/Portrait.tsx` | A crisp Canvas portrait using the refined frame cache, with original artwork retained if the renderer/module cannot initialize. CORE uses its original drawing. |
| `frontend/src/office/sprites.ts` | Original artwork and pose definitions (`FRAMES`), retained for the complete Canvas fallback. Original cells are 48×64. |
| `clipfoundry/office/roles.py` | The backend's copy of the same identities and which job kinds and stages each one owns. `tests/test_office.py` fails if the two lists differ. |
| `design/robots/contact-sheet.png` | A screenshot of the developer gallery (`#/dev/robots`, idle pose). |
| `design/robot-office/retro/README.md` | Evidence and provenance for the refined office graphics, kept separately from earlier captures. |

## Rules the art keeps

* **Pixel geometry and anchor.** Refined robots use integer-sized parts, stepped silhouettes, highlights and shadows,
  with feet anchored at their station. Bodies and heads vary by identity and rank. Portraits use a 48×68 image with
  feet positioned consistently; antialiasing and image smoothing are disabled. The map uses whole scale multiples
  when space permits and fits smaller windows with nearest-neighbor sampling.
* **Facing and identity.** The refined rig retains each robot's head shape, visor, top, gear and chosen hand. Side
  views shift the face, while the back view hides the face and shows its rear panel. The original fallback retains
  its separately drawn four directions.
* **Poses.** Both renderers consume the existing pose names: idle, work, walk, carry, review, wait, approved, rework,
  paused, unavailable, error and retry. The refined rig uses an eight-step walk, role-specific four-step work cues,
  a carried report card, visible error accents and an approval check/raised hand. The fallback retains its original frame counts. Paused robots
  stop movement and dim their eyes; unavailable robots fade. The office's HTML layer supplies truthful state icons.
* **Quiet idle.** Idle only blinks. A waiting robot waits, a paused robot stops typing, and nothing animates as if a
  search, an upload or a decision were happening when it is not.
* **Real activity and motion choices.** Backend events and snapshots choose work poses and report handoffs. The art
  never creates work or progress. Follow system honors OS reduced motion, Full explicitly overrides it, and Reduced
  freezes movement while actual state indicators remain. Portrait frames share the same preference.
* **Fallback.** If the new scene module or graphics initialization fails, `OfficeMap.tsx` restores the original
  Canvas map, including all robot buttons, details and controls. Portrait module/context failures keep original
  Canvas sprites. No external setup is needed to activate either path.

## Adding or changing a robot

1. Edit its entry in `cast.ts` (and, for a new role, add the same id to `clipfoundry/office/roles.py` with the job
   kinds and stages it owns).
2. If it needs a new head, visor, top or gear, add the type name in `cast.ts`, its refined drawing in `StudioArt.ts`,
   and its original drawing in `sprites.ts` so the fallback stays complete.
3. Open the Office, Team and `#/dev/robots` in the running app; check every direction and pose, selection, Reduced
   motion and the original-art fallback. Clear/reload the page after changing cached portrait artwork.
4. Run `python -m pytest tests/test_office.py` (the two registries must agree), `npm run build` in `frontend/`, and
   `sandbox/pixel-office.spec.ts` with the isolated Playwright sandbox configuration. Record actual results
   separately; the checks listed here are not a claim that this revision has passed them.

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
