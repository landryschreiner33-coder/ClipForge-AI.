# Full videos: split edits, clean cuts, room tone and music that ends on time

Added 2026-11-26 (batch 3 of "Majorly improve video editing quality", plan in
[EDITING_CRAFT_RESEARCH.md](EDITING_CRAFT_RESEARCH.md)). The code is `clipfoundry/studio/sound_joins.py`, used by the
full-video engine (`studio/engine.py`, the sound section of `render`) for every full video: made by hand, by
"Edit it for me", from a script, or with ClipForge AI.

## What the owner sees

Mostly nothing to set: this is how a full video's sound is put together now. The video editor's Sound panel says
what the last render did, for example "Last render: the sound leads or trails the picture by a few frames at 3 cuts
between recordings (J and L cuts); room sound under 4.0 s of titles and photos instead of silence; the music timed
to end on the last frame." The render's report (`info["sound_joins"]`) has the same facts. A music item set to Loop
has a new choice, **End on the last frame** (on for ClipForge's own music, off for your own songs).

## What happens

- **Split edits (J and L cuts).** At a straight cut between two different recordings, the sound edit moves 8, 6 or 4
  frames off the picture cut (research: 4-12 frames; the longest that fits wins). Usually the next recording's sound
  starts under the last frames of the outgoing picture (a J cut: you hear the new room before you see it); when the
  next recording has nothing before its in point, the outgoing room sound runs on into the new picture instead (an L
  cut). Only room sound ever moves: the frames that change hands must hold no word on either side, with 0.1 s to
  spare for transcript timing, so nobody is cut off or heard twice and the captions stay right. Each side keeps at
  least three times the split as its own sound. Not at jump cuts inside one recording (those stay tight), not at
  dissolves, not next to a muted clip, and not where a recording was never transcribed (then it is not known where
  the words are). The app's own edits keep only 0.10-0.16 s around the words, which is less than a split plus its
  margin, so in practice splits come where the edit leaves a real pause (a hand-trimmed clip, a breath before a new
  scene); every other cut between recordings still gets the crossfade below.
- **No clicks where two recordings meet.** The two sounds cross over 40 ms with an equal-power curve: two unrelated
  sounds keep their level through it, where a straight-line crossfade dips 3 dB. The crossfade only reaches into
  room sound: when the frames on one side of the cut hold a word that was cut out, it stays on the other side.
- **Room tone.** A title card, a photo or a video without its own sound used to leave digital silence, which sounds
  like a dropout. It now gets the room sound of the nearest recording (the one before it first): its quietest
  stretch between words (at least 0.5 s, kept 0.12 s clear of the words, up to 3 s), looped with crossfades and
  played backwards every other time so the seams do not repeat, at the volume that recording plays at (its clip's
  and the source track's). A stretch quieter than -75 dB (digital silence) or louder than -38 dB (not room sound) is
  not used. A clip the owner muted stays silent, and nothing is added where a voiceover plays (the narration has its
  own room): the tone fades out over 0.1 s just before the voiceover and back in after it, and an element a
  voiceover covers from end to end gets none. Next to a clip whose own sound fades in or out, the room tone runs on under that fade and fades the other
  way, so the background never dips to silence and back. It is written a block at a time (an hour costs no more
  memory than a second), and it does not make the music dip.
- **Music that ends on the last frame.** ClipForge's own music beds (made in whole bars, nothing to lose at the
  start) are started so that their own end lands on the video's last frame, instead of being cut wherever the video
  happens to stop; they then start inside the music, so they fade in over at least 1 s. Only music set to Loop that
  plays to the video's end is moved; music set to play for a few seconds keeps its start. Your own song keeps its
  start (often why it was chosen) unless you tick End on the last frame (`back_time` on the item; unticking it turns
  it off for a bed too). Looping music is decoded once and that exact pass is repeated: FFmpeg's own looping of an
  AAC or MP3 file drifts by the encoder's padding on every repeat until it pads in about 0.1 s of silence every 5
  repeats, which put gaps in long music and cut a back-timed ending short.
- **Finals sound like the preview.** FilmCraft's timeline has none of this. With Settings → Editing apps on "auto",
  a final that would use any of it (a straight cut between two recordings with sound, a title, photo or silent video
  that gets room tone, a back-timed bed) is rendered by the built-in engine, like the preview the owner approved
  (`engine.sound_joins_in_use`, next to the colour rule `engine.colour_in_use`). Whether room tone was found and the
  music moved is only known by measuring, so the preview of the same version decides (its report); without one,
  anything that could get them counts. With FilmCraft chosen in Settings, the version says what FilmCraft could not
  apply. A version finished by hand in FilmCraft's editor is FilmCraft's in the preview too, so nothing is said.
- **Hard cuts by default.** The "balanced" feel (the default) now joins clips with straight cuts, as editors do for
  talking videos; "calm" keeps its 0.8 s dissolves. "Edit it for me" now punches in a little (a wider and a tighter
  shot alternating at jump cuts) at its normal level as well as Fast-paced ("Zoom in a little on every other cut"
  turns it off), and its whooshes at changes of recording come at most every 15 s.
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
| Room tone fade around a voiceover | 0.1 s, outside the voiceover | `sound_joins.TONE_DUCK_MS` |
| Back-timed music fade-in | at least 1 s | `sound_joins.BACK_TIME_FADE_IN_MS` |
| Music back-timed by default | names starting "ClipForge music - " | `sound_joins.LIBRARY_MUSIC_PREFIX` |
| Whooshes at changes of recording | at most one per 15 s | `smart_edit.WHOOSH_GAP_MS` |

## Tests

`tests/test_sound_joins.py`: J and L cuts and where none is made, the equal-power crossfade's level, room tone choice,
seamless looping and its block-by-block writing, which music is back-timed, room tone stepping aside where a
voiceover plays, the editing defaults, rationed whooshes, and three real renders. The first (two recordings with different room hums, a
photo and a music bed with a marked last bar) checks by measurement that the next room is heard under the outgoing
picture's last frames with no speech moved, that the photo carries the room's sound at its level (the clip turned
down 6 dB, the tone with it) and that the music's last bar plays at the very end and fades in; it fails when any of
the three sound features is turned off. The second checks that the room never dips where a clip's own sound fades
into or out of a photo (it dipped 13 dB before the fix) and that a photo keeps its room until a voiceover starts
part-way through it, with nothing added under the voiceover. The third loops a 1 s AAC bed about 12 times and checks
there is no gap anywhere and its own last 0.1 s plays at the very end (FFmpeg's own looping failed both).
`tests/test_craft.py` checks the FilmCraft routing, with and without a preview's report.

Not verified: how it sounds on real recordings with real room noise (the cloud has no sample footage), and with
transcripts whose word times are off by more than 0.1 s.
