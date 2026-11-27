# Short clips: punch-ins, a change every few seconds, sound effects and captions

Added 2026-11-26 (batch 2 of "Majorly improve video editing quality", plan in
[EDITING_CRAFT_RESEARCH.md](EDITING_CRAFT_RESEARCH.md)). The code is `clipfoundry/pipeline/moves.py`, used by the clip
renderer (`pipeline/render.py`) for every short clip, Autopilot clips included.

## What the owner sees

| Where | Choice |
| --- | --- |
| Settings → Clips → Extras | Punch-ins on cuts and a push-in on key words (on), Sound effects (on; one choice for clips and full videos) |
| Clip editor → Layout | Punch-ins on cuts and a push-in on key words |
| Clip editor → Audio | Sound effects, and what the last render did ("3 punch-ins on cuts, 1 push-in on a key word, 2 sound effects") |
| Settings → Clips → Extras | Loop endings: clips stop just after the last word and run straight back into the start (on) |
| Clip editor → Trim | Loop ending, and what the last render did ("the end runs back into the start 0.25 s after the last word, with a change of shot size like the other cuts") |

## What happens

- **Punch-ins on jump cuts.** Where silence cleanup or filler removal cut a pause out of continuous speech, the shot
  size changes on the cut itself: 1.00 and 1.10 alternate (1.06 for sources under 1080 lines, which are already
  enlarged). The zoom is centred on the tracked face. A cut closer than 0.6 s to the last change, or to the end, keeps
  the framing, so nothing flickers. The switch lands on exactly the first frame of the new shot at any speed: the
  renderer works out which output frame first shows each part (`render.Timeline.cut_frames`, the same arithmetic as
  its frame loop).
- **Something changes every few seconds.** No framing is held longer than 5 s: a long stretch without cuts gets an
  eased change (0.4 s) at the pause or sentence end nearest 3.5 s in.
- **Push-in on key words.** On a stressed word (numbers, strong words, the clip's hashtags; the same words the
  captions colour) the camera pushes in a further half step, starting 0.3 s before the word and landing on it, and
  lets go at the next change. At most one every 6 s, not in the first half second or the last second. When a jump cut
  falls in those 0.3 s, the push comes in with the cut instead (never an eased zoom across a cut), and a push that
  lets go on a cut does so on the cut's own frame.
- **Sound effects from the edit.** A soft whoosh lands with each push-in, a light pop with each key word that is
  coloured in the captions (Settings → "Emphasize key words in their own color"; the Minimal style colours none, so
  it gets no pops). Never two within 4 s, none in the first 0.3 s or the last second (so a loop back to the start is
  clean). Peaks at -24 dBFS (whoosh) and -22 dBFS (pop) for speech at -14 LUFS, so they sit about 18-20 dB under
  it; when the speech ends up quieter or louder (normalization held back by peaks, or off) they move with it
  (`moves.effects_gain`, measured once). They are made from noise and tones by the app itself (no sound files,
  nothing to license) and each one is slightly different. They join the speech after its loudness gain and before
  the clip's own volume (which turns the whole mix up or down), go through the same limiter, and their track is
  deleted after the encode. The Settings choice also covers the full-video editor's whooshes: it is one choice.
- **Captions.** A new caption page starts on a jump cut (when the page already has two words), so the words change with
  the picture (the cut times move with the 40 ms lead, so a word heard right after a cut is on the new page); each word
  lights up 40 ms (about a frame) before it is heard; the lines stay between x 150 and 930 of the 1080-wide frame, clear
  of the like and comment buttons on TikTok, Shorts and Reels; new pages pop in gently (from 92 % for Clean, 90 % for
  Bold, 80 % for High energy, none for Minimal).

The render notes keep what was done: `render_info.moves` = `{punch, on_cuts, eased, pushes, effects}`.

## Loop endings (batch 4c)

TikTok, Shorts and Reels play a clip again the moment it ends. The research's rule is to cut 100-150 ms after the
last word, with no fade and no end card, so the replay runs straight into the start and reads as one more cut. The
code is `clipfoundry/pipeline/loops.py`, used by the clip renderer (Autopilot clips included).

- **A tight seam.** The picture and sound that are played start 0.10 s before the first word and stop 0.15 s after
  the last sound, on the clip's frame grid (a little more is kept rather than less, so a word's first and last sounds
  survive). The end and the start then meet with about the pause people leave between two sentences (0.2-0.3 s). A
  laugh, a shout or a cheer right after the last word (or before the first; `render.heard`) counts as the last sound,
  so a reaction to the punchline stays.
- **Moments of their own stay.** More than 0.8 s of quiet before the first word, or 1.2 s after the last, is
  something else (a look, an action, a reveal) and is left as it is. A clip never gets shorter than a second.
- **The shot size changes on the seam.** With punch-ins on, the framing alternates between plain and punched in at
  every jump cut. The loop back to the start is a jump cut too, so when the clip would end on the size it started with
  (an even number of changes), it starts punched in instead (`moves.opens_tight`). A clip without any change keeps the
  plain framing (nothing to alternate with).
- **Only what is played changes.** The clip's start and end stay where they are (the editor's trim, the predictor's
  times); the tightening is done on the kept parts like silence cleanup, so the captions, punch-ins and effects follow
  it. Sound effects already stay out of the first 0.3 s and the last second, so the seam is clean.

The render notes keep it: `render_info.loop` = `{head_s, tail_s, seam_s, switch}` (seconds left out at each end, the
pause at the seam in the clip's own time, and whether the shot size changes there). `loop_ending` is a Setting (on), a
clip edit, part of the Full Cloud job settings and of the artifact's recorded settings.

## Tests

`tests/test_moves.py` (14 fast, 1 real render): switches on cuts and eased elsewhere, a change at least every 5 s at a
pause, no flicker near the end, the smaller step for small sources, rationed pushes landing on the word, which effects a
clip gets, their level, timing and variety, the caption pages, lead, margins and pop, the setting everywhere it is read,
the zoom switch on the first new frame at speeds 0.8-1.5 (against a copy of the frame loop), pushes at cuts, pages at
cuts, effects following the speech level and the clip volume, and a real render of a synthetic clip with three cut
pauses (punch-ins counted, effects present, at least 12 dB under the speech at their loudest, only now and then, their
track removed).

`tests/test_loops.py` (8 fast, 1 real render): the seam keeps 0.10 s before the first word and 0.15 s after the
last, on the frame grid; long quiet ends are left alone; a laugh after the last word stays; only the ends change (a
jump cut inside stays, a cut filler is not the last word); nothing changes without words or below a second; the seam
pause at the clip's speed; the shot size switches on the seam (an even number of changes starts tight, an odd one is
unchanged, none keeps the plain framing); the setting everywhere it is read; and a real render that stops just after
its last word with the captions moved with it.

## Not verified yet

How it feels on real talking-head footage: the cloud has only synthetic video. The levels and rates are the
research's starting values; they are constants at the top of `moves.py`.
