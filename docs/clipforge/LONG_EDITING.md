# Full videos: split edits, clean cuts, room tone and music that ends on time

Added 2026-11-26 (batch 3 of "Majorly improve video editing quality", plan in
[EDITING_CRAFT_RESEARCH.md](EDITING_CRAFT_RESEARCH.md)). The code is `clipfoundry/studio/sound_joins.py`, used by the
full-video engine (`studio/engine.py`, the sound section of `render`) for every full video: made by hand, by
"Edit it for me", from a script, or with ClipForge AI.

## What the owner sees

Nothing new to set: these are how a full video's sound is put together now. The video editor's Sound panel says what
the last render did, for example "Last render: the sound leads or trails the picture by a few frames at 3 cuts
between recordings (J and L cuts); room sound under 4.0 s of titles and photos instead of silence; the music timed
to end on the last frame." The render's report (`info["sound_joins"]`) has the same facts.

## What happens

- **Split edits (J and L cuts).** At a straight cut between two different recordings, the sound edit moves 8, 6 or 4
  frames off the picture cut (research: 4-12 frames; the longest that fits wins). Usually the next recording's sound
  starts under the last frames of the outgoing picture (a J cut: you hear the new room before you see it); when the
  next recording has nothing before its in point, the outgoing room sound runs on into the new picture instead (an L
  cut). Only room sound ever moves: the frames that change hands must hold no word on either side, with 0.1 s to
  spare for transcript timing, so nobody is cut off or heard twice and the captions stay right. Each side keeps at
  least three times the split as its own sound. Not at jump cuts inside one recording (those stay tight), not at
  dissolves, not next to a muted clip, and not where a recording was never transcribed (then it is not known where
  the words are).
- **No clicks where two recordings meet.** The two sounds cross over 40 ms with an equal-power curve: two unrelated
  sounds keep their level through it, where a straight-line crossfade dips 3 dB. The crossfade only reaches into
  room sound: when the frames on one side of the cut hold a word that was cut out, it stays on the other side.
- **Room tone.** A title card, a photo or a video without its own sound used to leave digital silence, which sounds
  like a dropout. It now gets the room sound of the nearest recording (the one before it first): its quietest
  stretch between words (at least 0.5 s, kept 0.12 s clear of the words, up to 3 s), looped with crossfades and
  played backwards every other time so the seams do not repeat. A stretch quieter than -75 dB (digital silence) or
  louder than -38 dB (not room sound) is not used. A clip the owner muted stays silent. Room tone does not make the
  music dip.
- **Music that ends on the last frame.** A music bed set to repeat ("loop", the default for music) is started so that
  its own end lands on the video's last frame: a song's real ending, or the end of a library bed's last whole
  repeat, instead of wherever the video happens to stop. It therefore starts inside the music, so it fades in over at
  least 1 s. A song placed to play once from its start is left as placed; `back_time: false` on a music item keeps
  the old behaviour.
- **Hard cuts by default.** The "balanced" feel (the default) now joins clips with straight cuts, as editors do for
  talking videos; "calm" keeps its 0.8 s dissolves. "Edit it for me" turns on punch-ins (a wider and a tighter shot
  alternating at jump cuts) at its "smart" and "tight" levels, and its whooshes at changes of recording come at most
  every 15 s.
- **Shorts, small fixes.** A short's hook title is drawn on the very first frame (no fade-in, so the first frame,
  which is also the thumbnail some apps show, has it), and a clip made of one piece fades its sound in and out over
  10 ms so it never starts or stops on a click.

## Numbers

| What | Value | Where |
| --- | --- | --- |
| Split edit lengths tried | 8, 6, 4 frames | `sound_joins.SPLIT_FRAMES` |
| Margin around words | 0.1 s | `sound_joins.WORD_MARGIN_S` |
| Crossfade at a cut between recordings | 40 ms, equal power | `sound_joins.SCENE_XFADE_MS` |
| Room tone: shortest usable stretch, sample length, level range | 0.5 s, up to 3 s, -75 to -38 dB | `sound_joins.TONE_*` |
| Back-timed music fade-in | at least 1 s | `sound_joins.BACK_TIME_FADE_IN_MS` |
| Whooshes at changes of recording | at most one per 15 s | `smart_edit.WHOOSH_GAP_MS` |

## Tests

`tests/test_sound_joins.py`: J and L cuts and where none is made, the equal-power crossfade's level, room tone choice
and seamless looping, the back-time arithmetic, the editing defaults, rationed whooshes, and one real render (two
recordings with different room hums, a photo and a music bed with a marked last bar) that checks by ear-like
measurement that the next room is heard under the outgoing picture's last frames with no speech moved, that the
photo carries the room's sound at its level, that the music's last bar plays at the very end, and that it fades in.

Not verified: how it sounds on real recordings with real room noise (the cloud has no sample footage), and with
transcripts whose word times are off by more than 0.1 s.
