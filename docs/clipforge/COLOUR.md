# Colour: phone HDR, automatic correction, matching and looks

Added 2026-11-26 (batch 1 of "Majorly improve video editing quality", plan in
[EDITING_CRAFT_RESEARCH.md](EDITING_CRAFT_RESEARCH.md)). Every clip and every full video now goes through one colour
step, worked out once per recording and applied by FFmpeg as a single 3D colour table.

## What the owner sees

| Where | Choices |
| --- | --- |
| Settings → Defaults | Automatic colour (on), Look (Natural), Look strength (100 %), Clean up grainy footage (on) |
| Clip editor → Colour tab | The same four for one clip, and what the last render changed |
| Make a YouTube video → Colour panel | Look, Strength, Correct each recording, Match the recordings of people, Clean up grainy footage; what the last preview changed in each recording |
| "Tell the editor what to change" | "make it black and white", "give it a cinematic look", "make it warmer", "fix the colours", "keep the original colours", "make the colours match", "remove the noise", "tone down the look" (rules, no AI needed); the AI service is told the same choices |

Looks: Natural, Clean and bright, Warm, Cool, Film, Teal and orange, Moody, Vintage, Black and white. Each is clearly
recognisable at 100 % and protects skin tones; the strength mixes it with the corrected picture.

## How it works (clipfoundry/pipeline/grade.py)

1. **Reading the file right.** The colour tags are read with ffprobe (`source_colour`). Untagged HD video is read
   as BT.709 (FFmpeg's default is BT.601 for everything, which shifts reds and greens), every picture leaves as
   BT.709 limited range and is tagged that way.
2. **Phone HDR** (HLG, what iPhones and most Android phones record, and PQ) is always converted, even with automatic
   colour off: BT.2100 HLG OOTF (system gamma 1.2, 1000-nit display) or the PQ curve, reference white 203 nits,
   BT.2020 to BT.709 in linear light, FFmpeg's Mobius tone curve on the brightest channel, a soft gamut clip toward
   grey, BT.1886 encoding. Before this, an HDR phone clip came out flat and grey.
3. **Automatic correction**, measured on 10 frames spread over the parts that are used (cached next to the clip or
   the video's pieces), never per frame, so nothing flickers:
   - white balance from the greyest fifth of the pixels (grey things show a cast; a blue sky or green grass is just
     coloured), only when the brightest pixels agree, 70 % of the cast (35 % when they only roughly agree, 60 % of
     that for a cast over 10 degrees), nothing under 1 degree or over 16 degrees (a sunset, a stage, neon), gains
     0.85-1.18, half for a game or screen recording (almost no skin tones);
   - levels only when clearly off: foggy blacks, dim whites, very dark or bright mid-tones (half way), at most half a
     stop; a gentle S-curve on flat (log-like) footage; levels change brightness only, so colours keep their
     saturation; washed-out colour gets vibrance with skin tones protected.
   A well-exposed, colourful picture is left almost alone (a test checks the lighthouse picture changes under 5
   codes on average).
4. **Matching** (full videos): recordings with people in them are nudged toward the one that plays longest (mid-tone
   colour and brightness, 70 %, capped), so cutting between two cameras does not jump in colour.
5. **Look** and **strength**, then the gamut clip.
6. **Grain:** the noise is measured on the flattest parts of three full-size frames (Immerkær). Under 1.5 codes
   nothing is done; moderate grain gets `atadenoise`, heavy grain `fftdnoiz` (both LGPL, in every FFmpeg build).

Steps 2-5 are baked into one 33×33×33 `.cube` (`data/cache/luts/grade-<hash>.cube`, made once per grade) applied
with `lut3d` (tetrahedral) on 16-bit RGB. The Mac FFmpeg has no zscale or zimg, so the maths is done in numpy and only
`lut3d`, `scale` and the denoisers are needed. The clip renderer applies it while decoding (`rgb_filters`); the
full-video engine inside each piece's picture chain (`yuv_filters`), and the grade's hash is part of the piece key, so
changing a look re-renders only what changed.

A full-video plan keeps its choices in `plan["color"]` (`{auto, match, look, strength, clean}`); a plan made before
colour existed has none and only gets the HDR conversion (`engine.color_options`). Edits: `{"op": "set", "field":
"look" | "look_strength" | "auto_color" | "match_color" | "clean_picture", "value": V}` and `{"op": "color_grade",
"look": L, "strength": N}`. Clip edits use `auto_color`, `look`, `look_strength`, `clean_picture`.

## Tests

`tests/test_grade.py` (fast, 15): HDR maths and order, tags, an HLG file through FFmpeg against the numpy maths
(mean error under 0.5 codes), casts reduced, deliberate colours and screen recordings kept, a good picture left alone,
levels keep saturation, skin under vibrance, matching, looks and strength, the table and its cache, noise, the
measurement cache, the choices in Settings, the editor and edit requests. `tests/test_grade_render.py` (slow, 2): a
full render with a blue-cast recording and an HLG recording (tags, cast, HDR average against the maths), an old plan,
black and white, pieces reused; and the clip renderer's chain.

## Not verified yet

Real phone footage (iPhone HLG, Android, Dolby Vision) and real low-light webcam grain: the cloud has no sample media
(the sample hosts are blocked), so the checks use synthetic HLG made with the BT.2100 inverse and pictures with a
known cast. On the Mac, `lut3d` is in the bundled FFmpeg, but the colour step has not been run on Landry's Mac yet.
The before/after video (`/mnt/project-files/editing-upgrade/colour-before-after.mp4`) is made from Landry's
lighthouse picture with a simulated cast and simulated HDR, rendered by the real engine.
