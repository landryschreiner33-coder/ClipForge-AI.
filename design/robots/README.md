# Robot assets

The office's 25 robots and the Brain Core are drawn in code, not stored as images. Each robot is a list of pixel
rectangles built from named parts, so the office map, the Team roster and the developer gallery draw exactly the same
art, nothing needs a paid image service, and every part can be edited as text.

| File | What it holds |
| --- | --- |
| `frontend/src/office/cast.ts` | The registry: id, name, title, rank, department, room, manager, palette, head, body, visor, top, gear, work loop, hand and base for every robot, plus CORE. `validateCast()` checks 1 Director, 8 managers, 16 workers, unique ids and that no two robots share head + visor + top + gear. |
| `frontend/src/office/sprites.ts` | The drawing: each part as rectangles on a transparent 48×64 cell, the four directions, the poses and their frame counts and timings (`FRAMES`). |
| `frontend/src/office/Portrait.tsx` | One sprite as a crisp canvas (Team roster, details panel, gallery). |
| `clipfoundry/office/roles.py` | The backend's copy of the same identities and which job kinds and stages each one owns. `tests/test_office.py` fails if the two lists differ. |
| `design/robots/contact-sheet.png` | A screenshot of the developer gallery (`#/dev/robots`, idle pose). |

## Rules the art keeps

* **Cell and anchor.** Every sprite is drawn on a 48×64 cell with its feet on row 61 and its center at column 24, so
  frames never jump. Bodies are sized by rank in whole pixels: workers, managers about 1.15×, the Director about
  1.35×. The office scales whole cells only (nearest neighbor), never by fractions.
* **Four directions, drawn, not mirrored.** Left and right are separate drawings, so a tablet held in the right hand
  stays in the right hand. Seen from behind (`up`) the face is hidden and the gear is behind the body.
* **Poses.** `idle` (2 frames), `work` (4, the role's own loop and speed), `walk` and `carry` (4, a result card in
  the hands), `review` (2), `wait` (2), `approved`, `rework`, `paused` and `unavailable` (1), `error` (2), `retry`
  (4). Every robot has every pose: the mechanics are shared (raised gear, a small state bubble above the head with
  a check, a revise mark, a warning, a retry arrow, waiting dots), the parts stay the robot's own. A paused robot
  only dims its eyes; an unavailable one is drawn faded.
* **Quiet idle.** Idle only blinks. A waiting robot waits, a paused robot stops typing, and nothing animates as if a
  search, an upload or a decision were happening when it is not.

## Adding or changing a robot

1. Edit its entry in `cast.ts` (and, for a new role, add the same id to `clipfoundry/office/roles.py` with the job
   kinds and stages it owns).
2. If it needs a new head, visor, top or gear, add the type name in `cast.ts` and its drawing in `sprites.ts` for all
   four directions.
3. Open `#/dev/robots` in the running app and check every direction and pose.
4. Run `python -m pytest tests/test_office.py` (the two registries must agree) and `npm run build` in `frontend/`.

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
