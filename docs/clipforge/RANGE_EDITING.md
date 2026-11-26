# Full videos: speed changes, speed ramps, freeze frames and slow camera moves

Added 2026-11-26 (batch 4a of "Majorly improve video editing quality", plan in
[EDITING_CRAFT_RESEARCH.md](EDITING_CRAFT_RESEARCH.md)). The code is `clipfoundry/studio/retime.py`, used by the
full-video engine (`studio/engine.py`) for previews and finals, by the video editor's own edits
(`studio/video_flow.py`), by plain-words edit requests (`studio/edit_requests.py`) and by the timeline export
(`studio/interchange.py`).

## What the owner sees

In the video editor, a selected clip has new choices (Video review → the clip's panel):

- **Speed** for a recording: Very slow (25%), Slow motion (50%), A little slower (75%), Normal, A little faster
  (125%), Faster (150%), Twice as fast, Three times, Four times. Any speed from 0.25× to 4× can be set by an edit
  request or ClipForge AI.
- **Speed ramp** for a recording: Slow motion in the middle, Fast, slow, fast, Slow down to the end, Speed up to the
  end. The panel says how long the clip now plays for ("Plays for 6.4 s").
- **Split or freeze**: "Freeze here" (at a time in the file) and "Hold the last frame". A freeze frame is a clip of
  its own in the sequence, so it can be moved, removed or given a camera move; its panel shows which moment it holds
  and "Holds for (s)".
- **Camera move** for recordings, freeze frames and photos: Slow zoom in, Slow zoom out, Pan left, right, up or down.
  Choosing a fixed zoom turns the move off and the other way round.

The sequence list shows each clip's length as it plays and a note such as "· 0.5×" or "· slow motion in the
middle". The same edits can be asked in plain words in the edit box, for example "put clip 3 in slow motion",
"speed up the intro", "play the second clip at 2x", "add a speed ramp to the jump", "freeze the last frame for 2
seconds", "freeze frame at the end of clip 2", "slowly zoom in on clip 2", "pan left on the photo", or "remove the
slow motion from clip 3" (also: normal speed, no freeze frame, no zoom). The change list after an edit says what
moved, for example "Clip 2 “Jump”: 0.5× (was normal speed), 10.0 s → 20.0 s".

The rules read a clip by number ("clip 3", "clip three"), by place ("the second clip", "the last clip"), as the
intro or the ending (the first or last playing clip), as the photos, or by words said in it or in its name. Any other
phrase ("set the volume of clip 3 to 50%", "make it faster", "zoom in on my face at 0:30") goes to ClipForge AI,
which reads the request whole. "Remove the slow motion" only touches slowed clips, "remove the fast forward" only
sped-up ones, and "remove the zoom" also takes off a still punch-in. A photo asked to change speed or freeze gets
a plain answer.

## What happens

- **One time map per clip.** A clip's playback rate (1 / speed) runs smoothly between the ramp's points (an S-curve,
  so a ramp never jumps), and the map from video time to file time has a closed form; its inverse is found by
  halving. The picture uses it through FFmpeg `setpts` (a piecewise expression for ramps) followed by
  `fps=…:round=up`, reading from 100 ms before the piece's first moment, so every output frame shows exactly the file
  frame on screen at the moment the map says (also when the in point falls inside a frame). A constant speed is the
  same map with one rate, and speed 1 is exactly the old path.
- **Ranges.** A ramp's curve covers `speed_ramp.range` (the part of the file it was made for) and a camera move's
  covers `motion.range` (its share of the move). A split gives each half its own part of the same curve, so the two
  halves play exactly as the whole did, to the microsecond; past a ramp's range its edge speed continues.
- **Sound keeps its pitch.** A sped-up or slowed clip's own sound is decoded at normal speed and stretched with WSOLA
  (21 ms frames, each allowed to move up to 8 ms to join its neighbour smoothly), so voices do not turn into
  chipmunks or growls. Where the map runs at normal speed the sound comes out unchanged. It takes about 18 ms of work
  per second of output and the files are mapped, not read whole. The clip's fades and crossfades with its neighbours
  are applied as before; split edits (J and L cuts) are not made next to a retimed clip, because its sound and
  picture move at another rate.
- **Freeze frames** hold one frame of a recording for at least 0.2 s (2 s by default). They have no sound of their
  own, so like a photo they get the room sound of the nearest recording (batch 3's room tone), never digital silence.
  Frames are found on the file's own frame grid (from its frame rate), never past the picture's last frame (a phone's
  sound often runs on a little longer). "Hold the last frame" holds the last frame the clip shows; a freeze less than
  0.5 s before a clip's end ends the clip on the held frame instead of jumping back to it. "Freeze here" inside a
  clip splits it, puts the freeze between the halves with straight cuts, and the clip goes on from the same frame
  afterwards. A freeze of a moving clip keeps the framing the move had at that moment. The engine reads 0.2 s
  before the moment and holds the last frame at or before it, so the held picture is never an empty frame.
- **Slow camera moves** are 2 to 6 keyframes of zoom (1.0 to 1.5) and centre, eased smoothly (or linearly). The
  picture is first scaled to the output size times the deepest zoom, so a move never shows soft pixels, then moved
  frame by frame. The pans run at zoom 1.2 from one edge to the other. The move counts output frames (a recording
  at normal speed is brought to the output frame rate first), so a 2 s move takes 2 s on 24, 30 or 60 fps footage.
- **Everything follows the new timing.** Captions (word times), overlays and pictures placed on a clip, sound items
  anchored to a clip, chapters, the cold open and "Edit it for me"'s picture placement all use the clip's time map,
  so a caption still appears when its word is heard. Attached things keep file time inside the clip and move to the
  second half of a split (or past a freeze put inside the clip). A lead before a moment is video time at any speed:
  a whoosh 540 ms before a cut is a negative offset, and the swish 270 ms before a picture appears is the anchor's
  `lead_ms`. The editor's "Starts after its clip (s)" shows and takes video time (`audio_move` with
  `out_offset_ms`; ClipForge AI's `offset_ms` stays file time). Two halves of a slowed or ramped clip that meet in
  the same file are joined with a 40 ms straight crossfade, so the join does not click. Trimming checks that what is
  left plays for at least 0.5 s.
- **Finals look like the preview.** FilmCraft's timeline carries one constant speed per clip and no camera moves, so
  with Settings → Editing apps on "auto" a final that uses any of this is rendered by the built-in engine, like the
  preview the owner approved (`engine.retiming_in_use`, next to the colour and sound-join rules). With FilmCraft
  chosen in Settings, the version says what FilmCraft could not apply. The timeline export
  (`studio/interchange.py`) carries a speed as a linear time warp (a ramp at its average speed) and a freeze as a
  freeze-frame effect, and lists what it could not carry (ramps, stretched voice, room sound under freezes, camera
  moves).
- **Checks.** The plan check (`engine.validate`, `retime.problems`) says in plain words what is wrong: a speed or a
  ramp point outside 0.25× to 4×, a ramp that does not run from the start of the clip to its end, a freeze shorter
  than 0.2 s or outside its file, a speed on a photo, a move outside its zoom range.

## Numbers

| What | Value | Where |
| --- | --- | --- |
| Speed range | 0.25× to 4× | `retime.SPEED_RANGE` |
| Ramp points | 2 to 8 | `retime.RAMP_POINTS` |
| Ramp presets | middle 0.35×; 2× / 0.4× / 2×; down to 0.35×; up to 2.5× | `retime.RAMPS` |
| Freeze frame | at least 0.2 s, 2 s by default | `retime.FREEZE_MIN_MS`, `FREEZE_DEFAULT_MS` |
| Camera move zoom, keys | 1.0 to 1.5, 2 to 6 keys | `retime.MOTION_ZOOM`, `MOTION_KEYS` |
| Pans | at zoom 1.2, centre from 0.42 to 0.58 | `retime.MOTIONS` |
| Sound stretch frame, search | 1024 samples (21 ms), ±384 samples (8 ms) | `retime.WSOLA_FRAME`, `WSOLA_TOL` |

## Tests

`tests/test_retime.py`: the time map (normal speed is exact, constant speeds, each ramp preset there and back, the
edge speed past a clip's ends), freeze frames, the plan check's messages, the time line, captions, overlays, sound
items and chapters on retimed clips, no split edits at retimed cuts, the pitch-keeping stretch (a 440 Hz tone stays
at 440 Hz at 2×; normal speed comes out unchanged), and the editor's own edits (speed, a trim that would leave too
little, splitting a ramp, freeze frames at the end, inside and at the start, hold length, zoom and move replacing
each other). Four real renders use a test video whose every frame shows its own number: at double speed each frame
shows the file frame it should (±1) and the sound bands change at the right moments; a slow-in-the-middle ramp
followed by a freeze shows the mapped frame at every point (±1.5), the freeze holds exactly one frame for exactly its
length with the clip going on from there, and the sound follows the picture within 50 ms; a slow zoom and a pan move
smoothly on a video and a photo (measured from the picture itself); and changing only a clip's speed renders just
that clip again. `tests/test_studio_edit_requests.py` covers the plain-words requests and `tests/test_craft.py` the
FilmCraft routing.

## Review (2026-11-26)

A review of the batch with real renders found 15 problems, all fixed before merging, each with a test:

- Picture timing: a freeze at a clip's end could hold an empty frame past the picture's end (sound longer than
  picture); camera moves ran twice as fast on 60 fps footage and stopped at 80 % on 24 fps; slow motion from an in
  point inside a frame showed the next frame early; a 24 fps freeze was refused or held the wrong frame; a freeze in a
  clip's last half second jumped back to it; a freeze of a moving clip lost its framing.
- Splits: re-eased ramps and moves (now ranges, exact); attached pictures, sounds and chapters stayed on the first
  half; a click where two halves of a slowed clip met.
- Leads: the whoosh and swish leads were scaled by the clip's speed; the editor's attached-sound start was file time.
- Plain words: speed on photos failed with a server error; ordinary requests ("set the volume of clip 3 to 50%",
  "make it faster") were caught by the speed rules and answered with a wrong question; "zoom in clip 2", "the second
  clip", "the intro" and "freeze frame for 3 seconds" were not understood; "remove the slow motion" also reset
  sped-up clips, and "remove the zoom" missed a still punch-in.

The added tests: exact splits for every ramp preset and moves, attached things through a freeze, leads at 0.25× to
4×, 24 fps freezes (file end, inside, near the end, moving clip), the rules' review cases; and three real renders
(a freeze at the end of a file whose sound runs 0.2 s longer holds frame 89 for exactly 60 frames; 0.25× from in
points 1000, 1010 and 1030 ms shows exactly the mapped frame at every output frame; slow zooms on 24 and 60 fps
footage reach 1.1 at half time and 1.2 at the end; a split slowed or ramped clip joins without a click).

Not verified: how the stretched voice sounds on real speech at extreme speeds (0.25× and 4× are allowed but sound
artificial on any tool), and real phone footage with variable frame rate (the time map works on time stamps, so it
should hold).
