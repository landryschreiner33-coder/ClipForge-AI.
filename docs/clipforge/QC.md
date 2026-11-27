# Checking every render

Added 2026-11-27 (batch 5 of "Majorly improve video editing quality", plan in
[EDITING_CRAFT_RESEARCH.md](EDITING_CRAFT_RESEARCH.md)). Batch 5 checks each finished file and fixes what it can
without making the video again. It comes in three parts:

| Part | What | State |
| --- | --- | --- |
| 5a | The sound: how loud the finished file plays and how high its peaks go, fixed once when it missed | built 2026-11-27 |
| 5b | The picture: flat cartoons and graphics left as drawn by automatic colour; every colour change tried on the recording's own pixels first and eased where it would lose detail | built 2026-11-27 |
| 5c | The final quality check before publishing reads the same measurements: loudness, true peak, picture levels, colour tags | built 2026-11-27 |

## 5a: the sound

The code is `clipfoundry/pipeline/loudness.py`. Both renderers use it: the clip renderer (`pipeline/render.py`,
every short clip, Autopilot clips included) and the full-video engine (`studio/engine.py`).

### What the owner sees

| Where | What |
| --- | --- |
| Clip editor → Sound | "Loudness of the last render: As loud as most videos (-14.0 LUFS, peaks -2.0 dBTP)." A warning shows in the warning colour, for example "Plays 9.3 dB quieter than most videos (-23.3 LUFS): its loudest peaks held it back." |
| Full-video editor → Sound | The same line for the version on screen |

The notes say why a file is quieter or louder than most videos: its loudest peaks held it back, a very quiet
recording was raised by the most allowed (24 dB), normalization is off, or the owner's own volume setting (named
as the reason only when the file would be on target without it; otherwise "…, and your volume setting takes 1.0 dB
off"). A peak over -1 dBTP says it may distort after the platform's own encoding. When the check corrected
something, the line says so ("Its level was corrected by +0.8 dB after the first try", or the peaks were held
lower). A file whose sound could not be measured says so; a silent one shows nothing.

### What happens

- **Measuring** uses FFmpeg's `ebur128` filter (ITU-R BS.1770: K-weighted, gated integrated loudness, loudness
  range, and the true peak from 4x oversampling). Before 2026-11-27 the clip renderer read `loudnorm`'s
  `input_i`, which was up to 0.75 LU off on speech with level jumps.
- **One constant gain** brings the sound to -14 LUFS (YouTube's reference: it turns louder videos down and never
  turns quieter ones up), unless that would take the true peak over -1.5 dBTP; at most +24 dB and -24 dB. The sound
  is never squashed to get louder: that pumps and flattens speech (the distorted-audio report of 2026-10-15/23).
  `gain_for` also says what held the gain short: the peaks, or the 24 dB cap.
- **The limiter** runs at 192 kHz (4x), so it also catches the peaks between samples, with its ceiling at
  -2 dBFS (EBU Tech 3344 asks for -2 dBTP before a lossy codec). Before, it ran at 48 kHz with a -1.5 dBFS
  ceiling, and synthetic hot speech reached -0.5 dBTP after AAC at 256 kbps and +2.0 dBTP at 128 kbps.
- **After the encode** the finished file is measured again:
  - when it missed the level the render aimed at by more than 0.5 LU, its sound is made once more with the
    difference corrected (at most 6 dB, never more than the room left under the limiter's ceiling, and never up
    for a very quiet recording already raised by the most allowed: more of it passes the measurement's gate after
    the boost, so it reads a little under);
  - when its true peak is over -1 dBTP, its sound is made once more with the limiter's ceiling lowered 1.5 times as
    far as the peak went over, plus half a dB (between -3 and -6 dBFS): the encoder's overshoot shrinks by only
    0.7-1 dB for each dB the ceiling comes down.

  The picture is copied (`-c:v copy`), not encoded again. The new file has its audio timing checked again, and a
  clip's render record (`edl.json`, the final transcript, the SHA-256) is made from the fixed file. There is one
  extra try at most; whatever the second measurement says is what the note says. The check never fails a render
  that made its file: when it cannot measure ("unmeasured") or the second try fails or times out, the first file
  stays. A failed or cancelled render leaves neither its unfinished file nor its sound effects track behind.
- **FilmCraft versions** (`craft/finish.py`): FilmCraft sets its own export's level (-14 LUFS); its file is
  measured and judged the same way (`loudness.judge`) but never changed.
- **What is kept:** a clip's `render_info.qc = {version: 1, sound: {status, note, lufs, lra, tp, expected_lufs,
  fixed_db, ceiling_dbfs (only when lowered)}}`, and its `render_info.audio_processing` (version 2:
  `integrated_lufs`, `true_peak_dbfs`, `loudness_range_lu`, `normalization_gain_db`, `peak_limited`,
  `boost_capped`). A full video's version (`studio_artifacts.info.qc.sound`) also keeps `source_lufs`,
  `source_tp`, `peak_limited` and `boost_capped`. Numbers only, kept with the clip or video on this computer (or
  the owner's own worker with Full Cloud).

### What it does not do

- It never makes the picture again and never fails a render: a file it cannot fix keeps a warning in its note.
- Speech whose peaks are much louder than its average (plosives, a shout) stays quieter than -14 LUFS. "Clean up
  the sound" (on Auto by default) evens such speech out before this step.
- It measures the file ClipForge made, not what YouTube or TikTok make of it after the upload.
- The final quality check before publishing (`pipeline/quality.py`) measures the file again on its own (5c).

### Measured (synthetic sources, 10 s, through the clip renderer's chain and AAC at 256 kbps)

| Source | Gain | Finished file | Note |
| --- | --- | --- | --- |
| Speech-like noise, -29.5 LUFS | +14.9 dB | -14.9 LUFS, -2.0 dBTP | pass |
| The same with plosives | +3.8 dB (peaks) | -23.3 LUFS, -2.0 dBTP | quieter: its loudest peaks held it back |
| The same with a shout | +4.9 dB (peaks) | -22.3 LUFS, -2.0 dBTP | quieter: its loudest peaks held it back |
| Very quiet, -69.1 LUFS | +24 dB (cap) | -45.7 LUFS | quieter: a very quiet recording |
| Hot, -11.4 LUFS | -2.6 dB | -14.2 LUFS, -4.4 dBTP | pass |
| Any of them with the owner's +9 dB | | true peak -1.2 to -1.9 dBTP | louder than most videos (your volume setting) |

Tests: `tests/test_loudness.py` (reading FFmpeg's summary, the gain, the notes, the bounded fix, the limiter through
AAC at 128 and 256 kbps, a clip render's report, a hot peak made again with the same picture, a full video's missed
level made again); `tests/test_audio_start_regression.py` (a broken measurement still stops the render).

## 5b: the picture

The code is in `clipfoundry/pipeline/grade.py` (the colour step, see [COLOUR.md](COLOUR.md)). Both renderers use it:
the clip renderer through `grade.for_footage`, the full-video engine through `engine.grades`: there each recording's
correction is checked before the recordings are matched to each other (so matching aims at what will really be
shown), and everything again after it, matching and the look included.

### What the owner sees

Nothing new to set. The colour notes the editors already show (Clip editor → Colour, Full-video editor → Colour: what
the last render changed) say what this step did:

- "Flat colours (a cartoon or graphics): left as drawn"
- "Colour correction eased: it would have lost detail in the brightest parts" (or "… left out: …" when no gentler
  version was safe; the other reasons are the darkest parts, washed out strong colours and bands in smooth gradients)
- "The Teal and orange look eased to 60%: at 100% it would have lost detail in the brightest parts"

### What happens

- **Flat cartoons and graphics** (the animated shorts, slides, title cards) are left as drawn. A picture counts as
  flat when its 8 commonest exact colours cover 80% of the predicted check's real pixels (below). A camera's noise
  spreads even a plain wall or a dark night sky over many colours, while a drawing repeats its own exactly; counted
  on averaged frames, dark camera footage seemed to have few colours and was taken for a drawing (found in review).
  Measured: drawn cartoons 0.86-0.99 (0.83 for the talk show at 480p and the strongest compression), camera-like
  pictures 0.01-0.47, a noise-free synthetic gradient darkened to near black 0.72. Before, a cartoon's dark navy
  background read as an underexposed picture: the whites were lifted up to +20% and the mid-tones brightened, which
  raised every drawn colour by up to 27 codes and pushed the orange characters to full scale. A look the owner chose
  still applies. A cartoon or slide is not matched to the recordings of people in a full video, nor they to it.
- **Dim whites are judged by the brightest channel**, not by brightness: a saturated orange or red is dim in
  brightness but already at full scale in one channel, and lifting it would clip it (and the soft gamut clip then
  washed it toward grey). Deepening washed-out blacks keeps the brightest channel where it was, too.
- **The predicted check.** When a recording is measured, 4 of its frames are also read at 320 pixels wide with every
  pixel a real one (nearest-neighbour, not averaged), and up to 16,384 of those pixels are kept with its statistics
  (`check_px`, 8-bit, about 64 KB as text in the measurement's cache). Before the colour table is made, the grade is
  applied to them (`check_grade`):
  - **lost detail in the brightest parts:** the share of pixels newly at full scale that were visibly below it
    (under 97%), leaving out a flat area made all one level (the pixels within 3 codes of the commonest level: a
    cartoon's white sky or a slide's background has no detail to lose);
  - **lost detail in the darkest parts:** the same for pixels newly at black (luma 17 or less that were over 20);
  - **washed out strong colours** (the correction only): colourful pixels (saturation over 0.25 of their brightest
    channel) losing more than a fifth of it, against the white-balanced picture (taking a cast away is meant to change
    colours); a colour made darker or brighter keeps its saturation and does not count;
  - **bands in smooth gradients:** the steepest part of the brightness curve over the levels the picture uses (over
    1.8, neighbouring 8-bit levels land two or more apart).

  Limits: 0.5% of the pixels for the brightest parts, 1% for the darkest, 3% of the colourful pixels, a slope of 1.8.
  A correction over a limit is eased one step at a time on the setting that causes it (the lift toward white, the
  S-curve, the black level, vibrance, the mid-tones; otherwise everything half way), at most 4 steps, then left out.
  A look is judged only on what it adds to the corrected picture and only for detail and bands, never for being a
  look: it is eased to 60%, then 30% of the owner's strength, never further. `guard` in `grade.py`.
- A look alone (automatic colour and cleanup off) is measured and checked too. A measurement whose pixel sample
  could not be read is used for that render but not kept, so the next render measures again.
- Recordings measured before this (no `check_px`) are measured again: `grade.VERSION` is 2, and it is part of the
  measurement's cache key and of the full-video engine's piece key.

### What it does not do

- It never stops a render and never changes a look's choice in the plan or the clip's settings: only that render's
  table is eased, and the note says so.
- It does not measure the finished file's picture (5c does: the final quality check before publishing).
- "Colours kept inside the legal range" needed no new step: the table's output is clipped to 0-1 and every picture
  leaves as BT.709 limited range (16-235); 5c measures it on the finished file.

### Measured (the same test pictures before and now, automatic colour only)

Change in brightness of the 99th-percentile pixel (`p99 |dY|`, 8-bit luma codes), the share of pixels newly at full
scale (under 97% before), and the share of colourful pixels washed out:

| Picture | Before | Now |
| --- | --- | --- |
| Cartoon, dark navy background, characters cover a quarter | gamma 0.95: 4.4 codes | left as drawn: 0 |
| Cartoon, small characters (two backgrounds) | gain 1.2 and an S-curve: 26.8 codes, 0.6% clipped, 1.6% washed out | left as drawn: 0 |
| The talk-show cartoon (demo) | whites lifted 1.2x, mid-tones brightened | left as drawn |
| Dim photo, dim cinematic still, eerie still | 11.3-19.0 codes (a real correction) | the same |
| Well-exposed photo, the look pictures | 0.0-10.2 codes | the same, within 0.6 codes |

Looks, at 100% on the 14 test pictures: Teal and orange eased to 60% on 2 bright illustrations (storybook 2.2% of
the pixels lost highlight detail; comic 0.8%), Warm eased to 60% on 3 (flat 3.3%, paper 1.1%, comic 0.7%); every
other look and picture untouched.

Tests: `tests/test_picture_check.py` (flat cartoons at three sizes and backgrounds left as drawn while dim natural
footage is still brightened, the brightest channel, the pixel sample kept and read back, a correction eased and left
out with its notes, darker colours not counted as washed out, a look eased only where it loses detail and never
below 30%, a cartoon recording through FFmpeg unchanged, a dark night shot and a plain wall with camera noise not
taken for drawings, the white balance note after easing, a look alone checked, a failed sample not kept, the engine
checking corrections before matching and everything after it, cartoons left out of matching).

## 5c: the final quality check before publishing

The code is in `clipfoundry/pipeline/quality.py` (the final quality gate: Autopilot, Make & upload, the Brain's
"check this clip", every scheduled post). It decodes the whole file once; that one pass now also measures what 5a and
5b care about, so the gate and the renderers read the same numbers.

### What the owner sees

Three more lines in the final check's report (Publish Center, the post's checks):

| Check | Passes | Warns |
| --- | --- | --- |
| Loudness | "As loud as most videos (-14.0 LUFS, peaks -2.0 dBTP)." | "Plays 1.9 dB quieter than most videos (-15.9 LUFS)." / "Louder than most videos (…): platforms will turn it down." / "Peaks reach 6.9 dBTP: they may distort after the platform's own encoding." |
| Picture levels | "Within the broadcast range (16 sampled frames)." | "Colours outside the broadcast range in 5 of 16 sampled frames (worst at 5.5 s: 1.2% of the picture); players clip them." / "The blacks and whites go past the video range in most of the clip (full-range picture in a limited-range file?): it will look harsher after upload." |
| Colour tags | "BT.709, limited range" | "Tagged matrix smpte170m, … (ClipForge makes BT.709 limited range): players may show other colours." |

All three only warn: they never block scheduling or publishing, and they are not among the warnings that hold a clip
for review instead of publishing it automatically (`autopublish.HOLD_ON`). Platforms publish no loudness target, and
a level a little outside the broadcast range is clipped by the player, not lost.

### What happens

- **One pass.** The detectors' chain (black, freeze, silence) runs as before, its frames still all counted for the
  decode check; a `split` keeps 2 frames a second at a quarter of the width and height (an area average, which also
  stands in for EBU R103's low-pass filter) and sends them through a pipe, measured as they arrive (nothing large is
  written to the disk, and the pipe is always read to the end); the sound goes through `silencedetect` and then
  `ebur128` (`loudness.FILTER`) in a graph of its own, so a stitched file whose picture changes size part-way is
  still measured whole (in one graph with the picture the measurement started again). Measured on an 8 s 1080x1920
  clip: 0.9-1.3 s for the whole check, as before.
- **Loudness** is judged by `loudness.check` against -14 LUFS (pass within 1 LU) and -1 dBTP, exactly as the
  renderers judge their own file, without trusting what the renderer said. A silent clip or one without sound skips
  it (the "Sound" check covers silence).
- **Picture levels** (EBU R103): a sampled frame is outside when more than 1% of it has luma outside codes 14-241
  (-1% to 103%) or any of R, G, B outside -5% to 105%, read with the file's matrix as players read it (its tag;
  untagged: BT.709 from 720 lines up, BT.601 under that). One such frame is a warning. When most frames have
  over 5% of their luma under 16 or over 235, the warning says it looks like a full-range picture in a limited-range
  file. A legal test pattern through ClipForge's path: 0% outside; the same pattern expanded to full range: 96% of
  each frame outside the RGB limits.
- **Colour tags:** a tag other than BT.709 / limited range warns; a missing tag passes (players read HD video as
  BT.709; the note says BT.601 for an untagged SD file).
- `GATE_VERSION` is 4: every stored report is checked again once (about a second a clip).

Tests: `tests/test_gate_levels.py` (the one pass still counts every frame and keeps 2 frames a second, the gate's
loudness equals the renderers' measurement, -14 LUFS passes, hot sound, a full-range picture, oversaturated colours in
part of a clip, SD tags and an untagged file all only warn, no sound and silence skip it, a picture that changes
size half way keeps the whole file's loudness, untagged SD read as BT.601, the small frames read to the end even when
measuring them fails);
`tests/test_artifact_quality.py` (a clean render passes the new checks too).
