# Full videos: several cameras of one recording, and pictures in a corner

Added 2026-11-26 (batch 4b of "Majorly improve video editing quality", plan in
[EDITING_CRAFT_RESEARCH.md](EDITING_CRAFT_RESEARCH.md)). The code is `clipfoundry/studio/multicam.py` (the model,
lining up by sound, who speaks, the switching rules, corner geometry) and `clipfoundry/studio/camera_edits.py` (the
editor's camera edits), used by the full-video engine (`studio/engine.py`) for previews and finals, by
`studio/video_flow.py` (edits, the editor page's view, FilmCraft routing), by plain-words edit requests
(`studio/edit_requests.py`) and by the timeline export (`studio/interchange.py`).

## What the owner sees

**Cameras** (a panel in the video editor, shown once the media holds two videos or more). For a podcast, an
interview or a talk filmed with more than one camera:

- **Line up and switch to whoever speaks**, **Line up and change angles** or **Only line them up**. ClipForge finds
  where each other recording sits on the main one by their sound (any start order, any length) and says which files
  did not have the same sound. Each camera gets a guessed shot: **Wide shot**, **One person** or **Screen or
  other**, which the owner can change.
- **Switch cameras:** *To whoever is speaking* (the close camera of the person talking), *Another angle at pauses*
  (one person, several angles), *Off* (the recording's own camera only). Choosing a camera by hand shows *By hand*.
  The panel says how many camera changes there are.
- **In a corner:** one camera small in a corner over the whole recording (picture in picture), with **Corner** (top
  left, top right, bottom left, bottom right) and **Size** (small 20%, medium 30%, large 40%, or the usual size for the
  video's shape). It hides while that camera is the full picture.
- Each camera's **name**, **shot**, how it was lined up ("+2.00 s, sound match 54%") and **−1 frame / +1 frame**
  to line it up by hand (the measured clock drift stays); **Line up the other recordings**; **Back to one camera**
  (the recordings stay in the media).
- Parts the video already cut from another camera's own file, at moments the main recording also has, play from
  the main recording once that camera is lined up (its sound and words), with that camera shown: the cameras switch
  there like everywhere else, and the note says so.
- The **timeline** gets a **Cameras** row: which camera is on screen when, in each camera's colour; a dot marks a
  camera in the corner.
- A selected clip's panel gets **Camera** (one camera for the whole clip) and **Change camera at the split point**.
- **Pictures over the video** gets **Where**: the whole picture or small in a corner, and a size.

The sound and the captions always come from the main recording. The same edits can be asked in plain words: "switch
cameras to whoever is talking", "cut to the person speaking", "follow the speaker", "switch between camera angles",
"stop switching cameras", "go back to one camera", "use camera 2 for clip 3", "use the wide shot for the intro", "put
camera 2 in the bottom right corner", "picture in picture", "make the corner camera bigger", "move the corner camera
to the top left", "remove the corner camera". A request that names a camera the rules cannot pick ("the face cam"
with two close cameras) gets a "Which camera?" question; when more than one recording has cameras, a request that
names no clip gets "Which recording?". A request about a logo or captions in a corner, or one that moves or removes
a part, changes speed or the look ("remove the part where I put my camera in the corner", "put the wide shot in slow
motion") is left to the other rules and ClipForge AI. The proposal lists the camera changes (switching, camera
changes, the camera of each clip, the corner camera, place and size).

## What happens

### Lining up by sound (`multicam.line_up`)

Each recording's speech-band loudness (300-3,400 Hz, 100 values a second, `sound_profile`) is worked out once with
FFmpeg and kept in the data folder's cache (`cache/multicam/<file hash>-v1.npy`; the main recording's is made while
the media is prepared, when the video has two videos or more). The rises in loudness (onsets) of two recordings are
compared at every possible shift at once (FFT cross-correlation over the whole length, scored per second of overlap
and counting less below 20 s of overlap). A match must score at least 0.12 and beat the best match more than a second
away by 25%; the peak is refined between frames with a parabola. When the recordings overlap eight minutes or more,
seven one-minute stretches are matched again and a straight line fitted through them gives the drift between the two
clocks (cameras run a few tens of parts per million apart: 40 ppm is 144 ms an hour). The line must fit within 0.8
frame (rms) and stay under 500 ppm; drift under half a frame over the overlap is ignored. A camera's time is
`main + offset_ms + main × drift_ppm / 1e6`.

### Who speaks (`multicam.who_speaks`)

Each camera's sound (every camera that films people, the wide one included) is put on the main recording's frames
(`aligned`). For each word of the transcript, the louder half of its frames gives a level per camera; each word's levels minus their mean (so every camera's own gain
cancels out) are grouped with weighted k-means, one group per close camera to start with (a group left empty starts
again at the word furthest from its group). A group belongs to the camera that hears it loudest compared with the
other groups. Groups under 3% of the talk are dropped; any two people must be told apart by at least 4 dB, else the
two closest groups merge and it tries again. A word within 1 dB of halfway between two people is unclear. The groups
are found on the words every camera hears; a word that at least two cameras hear (a camera started late or stopped
early) is placed on the cameras that hear it. When the
cameras cannot tell people apart (one microphone for everybody), or there are no words yet, switching to the speaker
changes angles instead and says why. A wide shot whose microphone sits between everybody hears nobody loudest, so it
owns no group and shows the pauses; with one wide and one close camera, the close camera shows its person and the
wide shows the other. A camera ClipForge guessed to be a wide shot (its picture showed no face it could read) that
hears one person loudest becomes a close-up of that person, and the note says so; a shot the owner chose is kept.

### The switching rules (`multicam.plan_cuts`)

From the research (EDITING_CRAFT_RESEARCH.md, "Multicam"):

- Words less than 300 ms apart form a phrase. A turn under 2 s inside one person's talk (a quick "yeah") stays on
  that person; a short turn set apart by a pause of 2.5 s or more (a question after a silence) gets its own shot.
- The video **opens on the wide shot** for at least 3 s and **ends on it**: in the last 5 s, or right after the talk
  is over.
- A pause of 2.5 s or more goes to the **wide shot**; a close-up running 14 s or more gets a wide break of at least
  3 s at the next gap.
- **No shot under 2 s.** A cut lands **in the gap between words**, at most 150 ms before the new speaker's first word.
- A **jump cut** (a part of the recording removed) always gets another camera, so the cut does not jump.
- **Angles** (one person): each angle holds 3.5 to 12 s (median about 6 s, repeatable for the same recording),
  changes at a pause, prefers another shot size, and keeps changing where nothing is said.
- A camera is only chosen where its file has picture; anywhere a camera has no picture, the main camera shows.
- The changes are in the recording's own time, so a moment the video plays twice (a part used again, a teaser of a
  later moment) shows the cameras planned where it plays first; a later part plans only moments not planned yet, never
  replaces the opening wide shot, and leaves no shot under 2 s before moments planned already.

### Rendering (`engine.render`, `_piece`)

The cuts are in the main recording's time, so trimming, splitting, moving or speeding up a clip keeps every camera
change on its moment. Each piece of the video is cut again where the camera changes; the other camera's piece reads
its own file at the lined-up moment, through the clip's speed, framing (fill or fit, zoom, camera move) and colour
(the camera's own colour correction and look). A drifting camera is lined up again at least every minute. A camera
in the corner is read the same way at its box's size and padded with a light border (4 px at 1080 lines,
`0xF0F0F0`). Corner boxes keep the picture's own shape between 3:4 and 16:9 and never cover more than 45% of the
frame's height; on 9:16 they stay inside the safe box (clear of the captions and the app's buttons). The usual
corner and size depend on the video's shape: 16:9 bottom right 26%, 9:16 top right 42%, 1:1 bottom right 32%, 4:5
top right 36%. A picture over the video in the corner camera's corner moves to the other corner on that side, and
pictures are drawn above a corner camera. A dissolve or fade shows one camera per side: a camera change inside it
happens as the incoming clip's transition ends (or not at all while a clip goes out), as the editor's Cameras row
shows, and each side's corner camera comes and goes with its own side (never over a title card at full strength). A
plan without cameras renders exactly as before (same cache keys).

### Elsewhere

- **FilmCraft:** with "auto", finals that show another camera or anything in a corner stay on the built-in engine
  (`engine.cameras_in_use`); a FilmCraft render says it played the other cameras without ClipForge's framing and
  colour and left out the corner.
- **Export:** other cameras go on their own track, **Other cameras**, above Video 1, at the right frames of their own
  files; corner cameras and corner pictures go on a switched-off track, **In a corner (switched off: set Scale and
  Position)**, and the export's notes say so.
- **Validation** names what is wrong: a camera or main camera that cannot be read, a missing camera file, a camera that is the recording itself, an unknown shot,
  an offset over a day, too much drift, a camera change that cannot be read, a corner camera that is not one of the
  recording's, a corner place or size out of range.
- **Undo** and **versions** work as for every edit: a camera edit is a new version.
- **Edit it for me** again keeps the cameras (line-up, names, shots, corner, cameras chosen by hand); automatic
  switching is worked out again for the new cut, and the other cameras' files are not used as more footage.

## Storage

`plan["multicam"] = {main asset id: {"main": {"label", "shot"}, "cams": [{"id": "c2", "asset_id", "label", "shot",
"offset_ms", "drift_ppm", "match"}], "cuts": [[main file ms, camera id], ...], "corner": {"cam", "place"?, "size"?},
"switching": "speaker" | "angles" | "hand" | "off"}}`. Before the first cut the main camera shows. Overlays gain
`place` ("full" by default, or a corner) and `size` (0.15-0.5 of the frame's width). The editor page's view adds
`cameras` (each recording with other cameras: its cameras with file name and line-up, switching, changes, corner)
and `camera_timeline` (which camera is on screen when, in the video's time). The loudness cache is
`data/cache/multicam/`.

Editor edits (`camera_edits.OPS`): `cameras_add {of?, asset_ids?}`, `cameras_auto {of?, mode, asset_ids?}`,
`camera_set {clip_id, cam}`, `camera_cut {clip_id, offset_ms, cam}`, `camera_edit {of?, cam, field: shot | label |
offset_ms | nudge_ms, value}` (`offset_ms` lines up by hand and keeps the drift; `nudge_ms`, at most ±1 s, moves the
camera and keeps the drift and the sound match), `camera_corner {of?, cam | null, place?, size?}`, `cameras_remove
{of?}`; `overlay_set` takes `place` and `size`. Edit requests (and ClipForge AI's proposals) use `cameras {mode, of?}`,
`camera {clip_id, cam}` and `camera_corner {cam, place?, size?, of?}` (`of`: the recording, when more than one has
cameras).

## Tests

`tests/test_multicam.py`: 52 fast checks on a made-up conversation (two people taking turns, each close camera with
its own gain, a wide camera hearing both): line-up either way round, drift over 15 minutes, no match for other sound,
who speaks (97% of clear words right whatever the gains; refuses one shared microphone; goes on when one camera
stopped early), every switching rule, moments played twice (10 cases), cameras without picture, drifting pieces,
validation (also setups that cannot be read), corner boxes on every shape, the camera timeline at 2× speed and in a
dissolve, a picture in the corner camera's corner, the editor's edits (a one-frame nudge keeps the drift; odd edits
get a plain error; parts cut from a camera's file move to the main recording), plain words (requests that only
mention a camera stay with the other rules; two recordings with cameras), the AI's proposals, the editor page's view
and the export. Three real renders: three recordings of one numbered scene with the same sound are lined up to the
millisecond; every frame of a render with four camera changes (one clip at 2×) shows the right camera at the synced
scene frame, with camera 3 in the corner on its own synced frame (hidden while it is the full picture) inside the
light border; and in the dissolve from a title card the corner camera fades in with its clip. Also
`tests/test_studio_edit_requests.py` (a camera request proposed with its changes and applied) and
`tests/test_studio_smart_edit.py` ("Edit it for me" again keeps the cameras, by hand and automatic).

Not verified: real two-person podcast footage (the speaker test uses synthetic levels), real cameras' clock drift,
the editor panel in a browser beyond the demo.
