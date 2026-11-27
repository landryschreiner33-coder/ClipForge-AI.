# Steadying shaky footage

Added 2026-11-27 (batch 4d of "Majorly improve video editing quality", plan in
[EDITING_CRAFT_RESEARCH.md](EDITING_CRAFT_RESEARCH.md)). The code is `clipfoundry/pipeline/steady.py`, used by the
clip renderer (`pipeline/render.py`, every short clip, Autopilot clips included) and by the full-video engine
(`studio/engine.py`).

## What the owner sees

| Where | Choice |
| --- | --- |
| Settings → New clips → Steady shaky footage | On: clips and new full videos steady handheld shake (also an editing choice a Brain skill can set) |
| Clip editor → Colour | Steady shaky camera footage, and what the last render did ("steadied 4.2 s of shaky footage, 6 % closer to hide the edges") |
| Full-video editor → Colour | Steady shaky camera footage (the whole video), and what the last render steadied in each clip |
| Full-video editor → a clip | Steady this clip when it shakes (off keeps that clip as shot) |
| Plain words in the full-video editor | "the footage is too shaky", "I don't like how shaky it is", "stop it from shaking", "stabilize it"; "keep the handheld shake", "don't stabilize it", "turn off stabilization" |

## What happens

- **Only footage that shakes.** The camera's move between frames is measured on a small grey copy of the picture
  (480 wide): corners are followed from frame to frame and the move most of them agree on is the camera's (a shift
  and a tilt). Its path is smoothed (a Gaussian of 0.45 s), so hand shake (2-12 Hz) goes while a pan, a tilt or a
  walk stays. A shot is steadied when what is left shakes by at least 0.25 % of the width (about 5 pixels at 1920)
  or tilts by 0.25° (both as RMS).
- **Only the camera.** A shot is left alone when most of the followed points do not move together or they span
  less than 40 % of the picture (a person moving in front of a still camera or a plain wall: steadying would pin the
  person and float the frame). When they do not reach at least 3 of the picture's 4 corners (plain sky, a plain
  wall, a flat cartoon background), a person filling a plain-walled shot looks just like a camera moving, so the
  shake must also hold hand tremor: at least 35 % of it above 4 Hz. A person's own sway and nods are slower; a
  camera held by hand shakes faster too.
- **Nothing fixed on top.** A shot is left alone when, in a third of its frames or more, some point stays put where
  the camera's move should have shifted it by a pixel or more (a game's HUD, a screen's toolbar, a channel logo:
  steadying would make them shake). A roll moves the edges more than the middle, so this is judged point by point,
  and a small move between frames (60 fps) is looked at over a few frames. A shaky shot whose picture never moved
  enough to look for such points is left alone ("cannot tell"). A clip with a face cam layout (split, picture in
  picture, game) shows a screen and is never steadied.
- **No edges.** Each shot is enlarged just enough to hide the moving edges (at most 10 %), chosen so 98 % of its
  frames get their whole correction; the few that would need more are corrected as far as the edges allow. A shot
  of a clip that does not shake is not enlarged (a full-video clip uses the largest zoom of its shots).
- **Shots.** A frame where the picture cannot be followed or jumps by a fifth of its width starts a new shot; each
  shot is smoothed and decided on its own, so a calm shot next to a shaky one stays as it is.
- **What the clip shows.** The measured stretch runs on a little past the clip (half a second after a short clip,
  a second either side of a full-video clip, so the smoothed path has room), but only the clip's own frames decide
  whether a shot shakes and how much it is enlarged, and the notes count only them, in the clip's own seconds
  (after cuts and speed changes).
- **Measured whole.** A stretch up to 2 minutes (every short clip) is measured whole, so a shaky insert between two
  tripod shots is always found. A longer one (a long recording in a full video) is first sampled, 2 s every 6 s;
  when every sample is calm nothing more is read (a shaky shot of 7 s or more always holds a whole sample). The
  measurement is kept in the clip's folder (short clips) or the video's folder (full videos, shared by previews and
  finals), so a re-render reads nothing.

In short clips each decoded frame is moved back onto the smoothed path with one `cv2.warpAffine` before the framing.
The face tracking reads the picture before it is steadied, so the framing's centre is moved by the same enlargement
(`Plan.framed`), not by the shake taken out (the framing is smoothed already: following the shake would bring it
back); punch-ins and captions work on the steadied picture. In full videos a `sendcmd` file drives FFmpeg's `rotate`
(only when the footage tilts) and `crop` filters frame by frame, right after the file is read and before speed
changes, so a slowed or sped-up clip is steadied on its own frames. There the measurement reads the file's own
frames (frame k is the one nearest `t0 + k / fps`, whatever the file's frame rate and wherever the clip starts), as
the corrections are timed by the file's frame times. A camera of another recording (several
cameras, or one in a corner) is not steadied with this one's moves.

The render notes keep it: `render_info.steady` (short clips) and the full video's `steady` = `{seconds, zoom,
shake_pct, shots}` by clip. `stabilize` is a Setting (on), an editing choice (`studio/capabilities.py`, so Settings and Brain skills reach new
full videos through `guidance`), a clip edit, part of the Full Cloud job settings and of
the artifact's recorded settings; full videos keep their choice in the plan's `color.steady` (new plans from
Settings; plans made before 2026-11-27 have none and render as they did) and a clip's `steady: false`. A final that
steadies a clip stays on the built-in engine with Editing apps on "auto" (FilmCraft cannot steady), and a FilmCraft
render says so.

## Tests

`tests/test_steady.py` (11 fast, 2 real renders): synthetic footage made of busy shapes, filmed by a camera that
shakes at 3 and 7 Hz and tilts. Shaky footage is found and steadied to under a fifth of its shake with no edge
showing, also under a plain sky (hand tremor in the shake); a tripod shot, a smooth pan and a person moving in front
of a still camera (busy or plain wall, and a close-up filling half a plain-walled picture) are left alone; a HUD over shaky gameplay is never steadied, also when
the shake is nearly all roll and at 60 fps with a small HUD in a 1280x720 picture (the same footage without it is
steadied); a pan stays while the shake goes; a violent shake is capped at the largest zoom; a cut splits the shots
and only the shaky one is steadied; only the part a clip shows decides and is reported (in its own seconds), a jolt
after its end changes nothing, a shake with nothing to tell a HUD by is left alone, and the framing's centre follows
the enlargement; the full-video measurement reads the file's own frames at 25 and 30 fps from starts between two
milliseconds; a clip is measured whole (a shaky insert between tripod shots is found) and a long calm stretch only
sampled and remembered; the full-video filter graph shows the same picture as the clip renderer's warp after a
seek; the setting everywhere it is read (Settings through the editing choices, clip edits, Full Cloud, plans, the
editors, plain words: complaints steady, a "no" to steadying keeps the shake, "a steady zoom" or "a handheld look"
are not this, and each change is listed so it can be applied); a real short clip renders under a third as shaky; a
full video steadies its shaky 25 fps clip read from 1.367 s and leaves the steady one as it is.

## Not verified yet

Real handheld phone footage (rolling shutter wobble is not corrected), walking shots and real games: the cloud has
only synthetic video. The thresholds are constants at the top of `steady.py`. A shot with plain sky or wall in two
corners is steadied only when its shake holds hand tremor (above 4 Hz); a slow handheld wobble under a plain sky is
left alone, and a person whose rigid moves are that fast in front of a plain wall would be steadied. Whether 35 % is
right needs real footage.
