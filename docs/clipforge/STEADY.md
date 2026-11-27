# Steadying shaky footage

Added 2026-11-27 (batch 4d of "Majorly improve video editing quality", plan in
[EDITING_CRAFT_RESEARCH.md](EDITING_CRAFT_RESEARCH.md)). The code is `clipfoundry/pipeline/steady.py`, used by the
clip renderer (`pipeline/render.py`, every short clip, Autopilot clips included) and by the full-video engine
(`studio/engine.py`).

## What the owner sees

| Where | Choice |
| --- | --- |
| Settings → New clips → Steady shaky footage | On: clips and new full videos steady handheld shake |
| Clip editor → Colour | Steady shaky camera footage, and what the last render did ("steadied 4.2 s of shaky footage, 6 % closer to hide the edges") |
| Full-video editor → Colour | Steady shaky camera footage (the whole video), and what the last render steadied in each clip |
| Full-video editor → a clip | Steady this clip when it shakes (off keeps that clip as shot) |
| Plain words in the full-video editor | "the footage is too shaky", "fix the camera shake", "stabilize it", "keep the handheld shake" |

## What happens

- **Only footage that shakes.** The camera's move between frames is measured on a small grey copy of the picture
  (480 wide): corners are followed from frame to frame and the move most of them agree on is the camera's (a shift
  and a tilt). Its path is smoothed (a Gaussian of 0.45 s), so hand shake (2-12 Hz) goes while a pan, a tilt or a
  walk stays. A shot is steadied when what is left shakes by at least 0.25 % of the width (about 5 pixels at 1920)
  or tilts by 0.25° (both as RMS).
- **Only the camera.** A shot is left alone when most of the followed points do not move together, or they span
  less than 40 % of the picture (a person moving in front of a still camera or a plain wall: steadying would pin
  the person and float the frame), or when points stay put while the picture moves (a game's HUD, a screen's
  toolbar, a channel logo: steadying would make them shake). A clip with a face cam layout (split, picture in
  picture, game) shows a screen and is never steadied.
- **No edges.** Each shot is enlarged just enough to hide the moving edges (at most 10 %), chosen so 98 % of its
  frames get their whole correction; the few that would need more are corrected as far as the edges allow. A shot
  of a clip that does not shake is not enlarged (a full-video clip uses the largest zoom of its shots).
- **Shots.** A frame where the picture cannot be followed or jumps by a fifth of its width starts a new shot; each
  shot is smoothed and decided on its own, so a calm shot next to a shaky one stays as it is.
- **Cheap when calm.** A stretch of footage is first sampled (2 s every 20 s, at least three samples); when every
  sample is calm nothing more is read. The measurement is kept in the clip's folder (short clips) or the video's
  folder (full videos, shared by previews and finals), so a re-render reads nothing.

In short clips each decoded frame is moved back onto the smoothed path with one `cv2.warpAffine` before the framing
(face tracking, punch-ins and captions work on the steadied picture). In full videos a `sendcmd` file drives FFmpeg's
`rotate` (only when the footage tilts) and `crop` filters frame by frame, right after the file is read and before
speed changes, so a slowed or sped-up clip is steadied on its own frames. A camera of another recording (several
cameras, or one in a corner) is not steadied with this one's moves.

The render notes keep it: `render_info.steady` (short clips) and the full video's `steady` = `{seconds, zoom,
shake_pct, shots}` by clip. `stabilize` is a Setting (on), a clip edit, part of the Full Cloud job settings and of
the artifact's recorded settings; full videos keep their choice in the plan's `color.steady` (new plans from
Settings; plans made before 2026-11-27 have none and render as they did) and a clip's `steady: false`. A final that
steadies a clip stays on the built-in engine with Editing apps on "auto" (FilmCraft cannot steady), and a FilmCraft
render says so.

## Tests

`tests/test_steady.py` (9 fast, 2 real renders): synthetic footage made of busy shapes, filmed by a camera that
shakes at 3 and 7 Hz and tilts. Shaky footage is found and steadied to under a fifth of its shake with no edge
showing; a tripod shot, a smooth pan and a person moving in front of a still camera (busy or plain wall) are left
alone; a HUD over shaky gameplay is never steadied; a pan stays while the shake goes; a violent shake is capped at
the largest zoom; a cut splits the shots and only the shaky one is steadied; a long calm stretch is only sampled
and remembered; the full-video filter graph shows the same picture as the clip renderer's warp after a seek; the
setting everywhere it is read (Settings, clip edits, Full Cloud, plans, the editors, plain words); a real short clip
renders under a third as shaky; a full video steadies its shaky clip and leaves the steady one as it is.

## Not verified yet

Real handheld phone footage (rolling shutter wobble is not corrected), walking shots and real games: the cloud has
only synthetic video. The thresholds are constants at the top of `steady.py`.
