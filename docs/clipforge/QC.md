# Checking every render

Added 2026-11-27 (batch 5 of "Majorly improve video editing quality", plan in
[EDITING_CRAFT_RESEARCH.md](EDITING_CRAFT_RESEARCH.md)). Batch 5 checks each finished file and fixes what it can
without making the video again. It comes in three parts:

| Part | What | State |
| --- | --- | --- |
| 5a | The sound: how loud the finished file plays and how high its peaks go, fixed once when it missed | built 2026-11-27 |
| 5b | The picture: flat cartoons and graphics kept clean by automatic colour, colours kept inside the legal range | planned |
| 5c | The final quality check before publishing reads the same measurements | planned |

## 5a: the sound

The code is `clipfoundry/pipeline/loudness.py`. Both renderers use it: the clip renderer (`pipeline/render.py`,
every short clip, Autopilot clips included) and the full-video engine (`studio/engine.py`).

### What the owner sees

| Where | What |
| --- | --- |
| Clip editor → Sound | "Loudness of the last render: As loud as most videos (-14.0 LUFS, peaks -2.0 dBTP)." A warning shows in the warning colour, for example "Plays 9.3 dB quieter than most videos (-23.3 LUFS): its loudest peaks held it back." |
| Full-video editor → Sound | The same line for the version on screen |

The notes say why a file is quieter or louder than most videos: its loudest peaks held it back, a very quiet
recording was raised by the most allowed (24 dB), normalization is off, or the owner's own volume setting. A peak
over -1 dBTP says it may distort after the platform's own encoding. When the check corrected something, the line
says so ("Its level was corrected by +0.8 dB after the first try", or the peaks were held lower).

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
    difference corrected (at most 6 dB, and never more than the room left under the limiter's ceiling);
  - when its true peak is over -1 dBTP, its sound is made once more with the limiter's ceiling lowered 1.5 times as
    far as the peak went over, plus half a dB (between -3 and -6 dBFS): the encoder's overshoot shrinks by only
    0.7-1 dB for each dB the ceiling comes down.

  The picture is copied (`-c:v copy`), not encoded again. A clip's new file has its audio timing checked again,
  and its render record (`edl.json`, the final transcript, the SHA-256) is made from the fixed file. There is one
  extra try at most; whatever the second measurement says is what the note says.
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
- The final quality check before publishing (`pipeline/quality.py`) is unchanged until 5c.

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
