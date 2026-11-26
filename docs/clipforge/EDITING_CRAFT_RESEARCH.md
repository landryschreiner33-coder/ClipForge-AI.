# How good editors work, and what ClipForge does with it

Landry, 2026-11-26: "Do deep research on how to edit videos and what goes into it and majorly improve the editing for
the software". This is the summary of that research (four areas, about 70 techniques with their numbers and sources,
read from editors' books and talks, platform guides, broadcast standards and FFmpeg's own documentation and tests),
and the plan it led to. Where a number is an editor's taste rather than a measurement, the research marked it as
opinion; those are starting values, not rules.

## Short clips (TikTok, Shorts, Reels)

- **Frame 0 is complete.** Open on the strongest line, face visible, hook text already drawn; no fade-in, no logo
  (a logo on screen cut 6-second view-through by 14 % in TikTok's own data). First word 2-4 frames after frame 0.
- **Captions inside the safe box** of every platform's buttons and text: x 120-888, y 288-1248 at 1080×1920. Heavy
  outline; word highlight up to 2 frames *before* the word is heard, never more than 1 frame after (sound leading
  picture is noticed from 45 ms). Page breaks at pauses and cuts.
- **Pace:** pauses between phrases 200-300 ms (natural), 100-150 ms (fast). Keep 30-50 ms before a word and 60-100 ms
  after, so first and last sounds survive.
- **Punch-ins:** alternate 1.00 and 1.10-1.15 at every jump cut inside continuous speech, plus a rationed emphasis
  punch (one motion style per clip), anchored on the face, eased, never more upscaling than the source allows.
- **Something changes every 2-5 s** (a cut, a punch, a caption page, a cutaway, an emoji), rotating the kind.
- **Cutaways** 1.5-3 s, 10-35 % of the clip, never over the hook or the payoff, captions stay on top.
- **Sound:** effects from the edit's own events (pop on a keyword, whoosh peaking on a cut), 15-20 dB under speech,
  rate-limited and varied; an optional instrumental bed 15-20 LU under speech.
- **Ending:** cut 100-150 ms after the last word, no fade, no end card; when the last line flows into the first, the
  clip loops.

## Long videos (YouTube)

- **Hard cuts** are 95-99 % of edits. A dissolve (10-15 frames) means time passing or a place change; a dip to black
  a bigger jump; never a dissolve inside one recording's talk.
- **Split edits (J and L cuts):** at speaker changes and B-roll exits the picture moves 4-12 frames off the sound
  edit; at a new section the next sound leads by 0.5-2 s.
- **Multicam:** cut to the active speaker in the gap between turns, hold each shot at least 2-3 s, use the wide at
  the start, the end and during silence.
- **Structure:** cold open, body with re-hooks, an abrupt payoff, valid chapters (first at 0:00, three or more, each
  at least 10 s).
- **Shot lengths** drift naturally (a right-skewed spread, median about 3 s), keeping natural speech gaps instead of
  removing all air. Alternate wide and tight at single-camera jump cuts (a cut-in needs at least one shot size step).
- **Music** back-timed so its real ending lands on the last frame; lengths fitted by whole bars in the middle.
- **Murch's rule of six** for choosing a cut frame (emotion 51 %, story 23 %, rhythm 10 %, eye-trace 7 %, then the
  screen plane and space); never cut on a closed eye; keep the point of attention in the same place across a cut.
- **Lip sync** checked after every split edit, speed change or frame-rate change (+15 / −45 ms).

## Picture

- **Colour tags right at every step**: untagged HD is BT.709 (FFmpeg's default BT.601 turns skin and reds wrong);
  deliver BT.709 limited range, tagged.
- **Phone HDR** (HLG/PQ) tone-mapped to SDR: reference white 203 nits, Mobius tone curve, BT.2020 to BT.709.
- **White balance, levels, matching** per shot or recording, never per frame, each capped and partial; skin tones
  protected (Cb 77-127, Cr 133-173).
- **Looks** as table functions with a strength; one 33³ table per shot, applied in 16-bit.
- **Noise** measured (Immerkær) before cleaning; `fftdnoiz` has the best quality per CPU among built-in filters.
- **Stabilise** only shaky footage (OpenCV feature tracking keeps the licence clean); sharpen once, at the output
  size, after denoise.
- **Scopes after every render** (signalstats) with pass/fail rules and an automatic back-off.

## Sound

- **Voice chain in a fixed order:** repair (declip, plosives), high-pass 80 Hz, hum notches only when hum is found,
  denoise about 10-12 dB, subtractive EQ, de-ess, compress, presence, phrase levelling, then loudness.
- **Room tone** under every cut: a jump cut never drops to digital silence. Short crossfades on every speech edit.
- **Music** set against measured speech loudness (15-20 LU under), ducking built from word timings with lookahead.
- **Loudness:** two-pass linear loudnorm, −14 LUFS and −1 dBTP for YouTube, checked after the render.

Much of the sound chain already exists (Clean up the sound, `pipeline/cleanup.py`; measured ducking in
`studio/engine.py`).

## The plan (one pull request per batch)

| Batch | What | State |
| --- | --- | --- |
| 1 | Colour: phone HDR, automatic correction, matching, looks, grain ([COLOUR.md](COLOUR.md)) | built 2026-11-26 |
| 2 | Short clips: punch-in alternation and emphasis, caption pop and safe box, effects from edit events, a visual-change scheduler ([SHORTS_EDITING.md](SHORTS_EDITING.md)); loop endings moved to batch 4 | built 2026-11-26 |
| 3 | Long videos: J and L cuts, room tone, crossfades between recordings, hard cuts by default, music back-timed, wide/tight alternation ([LONG_EDITING.md](LONG_EDITING.md)) | built 2026-11-26 |
| 4a | Range in full videos: speed changes and speed ramps (sound keeps its pitch), freeze frames, slow zooms and pans, from the editor and plain-words requests ([RANGE_EDITING.md](RANGE_EDITING.md)) | built 2026-11-26 |
| 4b | Picture in picture, multicam with active speaker | planned |
| 4c | Loop endings for shorts, stabilising | planned |
| 5 | Automatic quality check after every render (scopes and loudness) with a back-off | planned |
