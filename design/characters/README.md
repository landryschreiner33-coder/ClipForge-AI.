# Robot characters

The ClipFoundry crew: 1 director (COMMAND), 8 managers, 16 workers, plus CORE (the brain
chamber, a stationary object and not a robot). Reference sheets: "Boss & Managers" and
"Worker Bots". `MANIFEST.json` lists every role, its department, manager, art source,
directions and per-state frame timing. `screenshots/` holds contact sheets from the last review.

## How the art is built

All art is code in `frontend/src/robots/`, rendered as crisp SVG (`shapeRendering="crispEdges"`).

| File | What it holds |
| --- | --- |
| `registry.ts` | Identities: ids, names, jobs, duties, departments, managers, palettes, timing, `validateRegistry()` |
| `pixel.ts` | 48x64 pixel layers, outlined + auto-shaded shapes (light from top-left), tiny font, SVG path output |
| `rig.ts` | Shared skeleton: body proportions per rank, poses per state, legs, arms, eyes, task card, status markers, and `drawRobot()` which orders parts per view |
| `art/common.ts` | Head/torso builders, antennas, tablets, reels |
| `art/director.ts`, `art/managers.ts`, `art/workers.ts` | One `RobotDef` per role: only what makes that role unique |
| `core.ts` | CORE chamber (activities: idle, lookup, evaluating, updating) |
| `sprite.ts` | Composes a role/direction/state/frame into cached path runs; fallback rules |
| `RobotSprite.tsx` | `RobotSprite`, `RobotPortrait`, `CoreChamber`, shared animation clock |
| `TeamRoster.tsx`, `DevGallery.tsx` | Read-only roster; development contact sheet (`#/dev/characters`) |

Conventions:

- Cell is 48x64; feet rest on y=59 (bottom centre x=24) with a shared soft shadow. Workers' bodies are
  about 26x34, managers 1.15x, COMMAND 1.35x.
- Every shape gets a 1px dark outline; later parts draw over earlier ones, which gives internal lines.
- Profiles are drawn facing right; "left" is mirrored. Lettering ("CC", "Aa") is stamped after the
  mirror with `painter.text()` so it never reads backwards.
- Layers: `back` (shadow, card in back view) / `base` (robot) / `card` (tintable task card, colour
  tokens `@c @h @l @i`) / `over` (hands on the card, status markers).
- No randomness: animation phase offsets are a hash of the role id.

## Add a role

1. Add the id to `RoleId` and an entry to `ROLES` in `registry.ts` (keep one `id: "...", name: ...`
   line per role; the pytest reads it), and list it in its department in `DEPARTMENTS`.
2. Add a `RobotDef` in the matching `art/*.ts` file and export it in that file's `*_ART` object.
   Implement `head` and `torso`; optionally `pack`, `item`, `itemBack`, `shoulders`, `after`, `base`.
   Use `g.v` ("front" | "back" | "side") to vary the view and `g.p.work` for the work motion.
3. Regenerate `MANIFEST.json` (render every role/direction/state/frame and dump the registry) and
   run `pytest tests/test_robot_registry.py` (update the expected crew there if the team changes).
4. Check it in the dev gallery at 1x and 2x, from all four directions, and while carrying a card.

## Add a state

1. Add it to `AnimState` and `ANIM_STATES` and give it timing in `anim()` in `registry.ts`.
2. Describe its pose in `poseFor()` in `rig.ts` (arms, eyes, bob, card, marker). If it needs a new
   marker, add it to `drawMarker()`.
3. Roles inherit the pose automatically; only add role-specific drawing when the shared pose is not
   enough. Unknown states fall back to `idle`, unknown directions to `down`.
