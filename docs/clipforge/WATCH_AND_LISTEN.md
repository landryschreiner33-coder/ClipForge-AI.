# ClipForge AI watches and listens

November 2026. Landry asked for ClipForge AI to "actually watch the videos frame by frame and listen to the audio,
so it doesn't guess what's in a clip and the clips are better". Before this change clip picking read the words of
the transcript and guessed the rest: a "reaction" was any loud stretch without words (a laugh, but also a song, an
engine or a door), and the picture was looked at only for the six strongest finalists, after the clips were nearly
chosen. Now three senses run over the whole video before any clip is picked, everything on the owner's computer:

| Sense | What it does | Code | Kept in the project folder |
|---|---|---|---|
| **Listening** | names every sound, every 0.48 s of the whole track, with a sound model that ships inside ClipForge | `pipeline/listen.py` | `sounds.json` |
| **Watching** | decodes the whole video at 2 frames a second (1 over 20 minutes, 0.5 over 90) and measures every frame: movement, hard cuts, faces, light, sharpness, colour, an 8×8 thumbnail | `pipeline/watch.py` | `watch.json` |
| **Seeing** | the built-in model is shown every part of the video (4 frames per part, at most 8 seconds a part) and says what happens in it, most promising parts first, within a time budget | `pipeline/eyes.describe_video` | `seen.json` |

`pipeline/senses.py` puts the three together and is what the rest of ClipForge reads. Each sense is optional: off in
Settings, a missing model or a failure leaves it out, and clip picking goes on exactly as before without it. A sense
switched off also leaves out what an earlier run saved (`Senses.load(pdir, settings)`, `render.heard(...,
settings)`), and the model's descriptions count for clip picking only while the built-in model may describe the
video now and only the same model's words (`Senses.saved_seen`); ClipForge AI's chat may read them whichever
model wrote them, while Watching is on.

## The sound model

YAMNet (Google, Apache-2.0): a MobileNet trained on AudioSet that names 521 kinds of sound in 0.96 s of audio.
ClipForge ships it as `clipfoundry/assets/models/yamnet.onnx` (7.5 MB) next to its class list, so nothing is
downloaded. The file is built from Google's published weights (`storage.googleapis.com/audioset/yamnet.h5`, checked by
SHA-256) by `scripts/export_yamnet.py`: the batch norms are folded into the convolutions, TensorFlow's "same" padding
is written out, the weights are stored as float16. Its answers were compared with Google's own TensorFlow model on
four 30-second stretches of film sound: the same top classes, every score within 0.003. The features (`listen.log_mel`, `listen.patches`) follow
YAMNet's `features.py` exactly: 16 kHz mono, 25 ms windows every 10 ms, 64 mel bands from 125 to 7,500 Hz, log with
an offset of 0.001, 96-frame patches every 48 frames. It runs on the CPU through ONNX Runtime, which ClipForge
already uses; the app checks the file's SHA-256 before loading it.

The 521 classes are read as the kinds a video editor cares about (`listen.GROUPS`): speech, laughter, applause,
cheering, screaming, a gasp, crying, singing, music, explosions and gunshots, crashes, engines, alarms, animals,
sound effects and silence. A run of windows above a kind's threshold (`listen.THRESHOLD`; the run continues while
above 60% of it and bridges a one-window gap; music must last about two seconds) is an **event**, such as
"laughter 0:42-0:45".

What changes because of it:

- **Reactions are real now.** `virality.wordless_loud` (and through it `reaction_after`, `reaction_before`, the
  Payoff and Context checks, `deep.audio_features` and the cut's own end in `candidates.refine_bounds`) reads the
  events instead of loudness when the sound was named: laughter, applause, cheering, screaming, a gasp, an explosion
  or a crash where nobody speaks. A song, an engine or a door no longer passes for a reaction; a quiet laugh that
  loudness missed now counts. `render.heard` keeps both, so a cut never loses a reaction it kept before.
- **What is heard is part of each clip's score** (below).

## Watching every frame

One ffmpeg pass decodes the video at 320 pixels wide (on a Mac with VideoToolbox, the media engine) and OpenCV
measures each frame: the mean change from the frame before (after a light blur), a hard cut when the colour
histograms correlate below 0.55 (as `reframe.py`), faces with the YuNet detector ClipForge already ships (a face at
least 6% of the picture's height counts), brightness, sharpness (log of the Laplacian's variance), colour. From these
`watch.Watched` gives the shots, an **action** curve (movement against this video's own usual movement, plus cuts
nearby), the moments where the picture comes alive, long still stretches, the frames that show a stretch best
(`keyframes`: the sharpest frame near the middle of each shot, a face preferred), and the parts the model is shown
(`segments`: each shot cut into pieces of at most 8 seconds, with a flag when a part looks like the one before it:
the same still talking head).

## The model says what happens

With the built-in model (Settings → ClipForge AI; the Basic level is Qwen3-VL 2B, the Standard level Gemma 4, both
with a vision part), `eyes.describe_video` shows the model each part: four frames, the words said in it, the sounds
heard in it, and a JSON schema the engine enforces while it writes: one sentence of what happens, up to five tags
from a fixed list (`eyes.TAGS`: "laughing", "fight", "fall or crash", "explosion or fire", "sports play", "nothing
happens", ...), how many people, how much happens (0-10), text on screen. Parts are asked about in order of promise:
where the candidates found from the words are strongest and where most was heard and seen. A part that looks like
the one before it takes that part's answer instead of a new question. The budget is 40% of the video's length,
between 1.5 and 10 minutes (Settings: `ai_watch_budget_s`); the answers are kept per model, so the next run only
asks about the parts not yet described. Without the built-in model the picture is measured but not described.

## How clip picking uses them

1. **New candidates from what happened** (`candidates.from_senses`, `senses.anchors`). The strongest moments (at
   most 24, 8 seconds apart): reactions (the clip ends on the line the reaction answers; the cut keeps the reaction
   after it), explosions and crashes, bursts of action, and parts the model rated 7+ or tagged as exciting (the clip
   holds three quarters of its length before the moment). Each is snapped to whole sentences and scored like every
   other window; one that repeats a candidate already found marks it instead (+0.10 stage-1 at full strength).
   Where no line is near the moment (a fight, a chase, a goal nobody talks over), the clip is a stretch of time
   around it instead (`candidates._time_window`: the target length, its edges moved to a shot cut within 3 seconds
   and never through a word, kept only when under half of it is talk and at least 60/100 happens in it, so a lone
   sound over still end credits is not a clip), scored by how much happens in it. An action, a bang or a seen
   moment with only a shout or two around it gets this stretch even when lines are near; it stands next to the
   sentence windows there, and the selection keeps the better one. Before, such a moment could not become a clip
   at all unless the whole video had no speech. A video without speech is cut
   into the windows where most happens instead of the loudest ones.
2. **The rankings.** The fast and semantic stages add `8 × interest` (0-1: reactions, exciting sounds, action, the
   model's action); at least three of the deep stage's places go to moments built around what was seen and heard
   (a talk clip gives its place only while fewer than three are there, so a film full of action never pushes out
   its best lines).
3. **The Clip Score** gets one more bounded, explained part (`senses.adjust`), shown in "How the Clip Score came
   about":
   - heard, at most ±5: +2.5 when the clip ends on a reaction, +0.8 per reaction (at most 2), +0.6 per exciting
     sound (at most 1.5); −1.5 when it opens on a reaction whose cause came before it; −2 when it is mostly silence;
   - watched, at most ±3: action and opening action against this video's own usual; −2 for a picture that stands
     still without a face; −1 when it is mostly dark;
   - seen, at most ±4 (only when the model described at least 30% of the clip): the model's action against 4,
     +1.2 per exciting tag (at most 2), −3 × the share of parts where "nothing happens". An exciting tag counts
     only for a part the model also rated at least 5 of 10 for action (`senses.HOT_ACTION`), and repeats count once:
     on GitHub the 2B model tagged a man at a desk "fall or crash" five times with an action of 3;
   - all three together at most ±9 (when the parts add up to more, a line says what the cap took off, so the
     lines always add up to the points);
   - **little talk**: words say less about a clip that is talked through less than half of its time, so its score
     moves toward how much happens in it (`senses.show`, 0-100 from the same three senses), by up to half the
     difference when nobody talks at all, at most ±12, with its own line ("little is said here (12% of the time), so
     it is judged more on what happens in it"). A clip that is talked through keeps its words' score. A stretch of
     time built around a moment is already scored on what happens in it, so it is not moved a second time; its line
     says so ("little is said here (0% of the time), so it is scored on what happens in it (87/100 ...)").
4. **Autopilot and post-live.** With "Require a complete story" on, Autopilot keeps only clips whose transcript tells
   a story (hook, context, payoff), after the selection. A stretch of time built around a moment has no lines to
   tell one, so in those runs it does not compete for a place (`process.story_screened`); the talk clips keep
   theirs. With the setting off, it competes like any other clip.
5. **The model reads it too.** The scout's transcript lines carry ⟨seen: …; heard: laughter⟩ notes (only when
   something new is seen or heard), and the judge sees "Seen" and "Heard" lines under each finalist. The finalists'
   picture check (`eyes.look`) is shown the frames that show the clip best and told what was heard.

## Where you see it

- A clip's "Why" lists what happens in it, what is heard and the picture ("What happens: 0:03 the host trips over a
  cable"; "What is heard: 0:07 laughter"), and "Built around a moment" for a clip made from one.
- ClipForge AI's `clip` tool includes the same lines, and the new `watch` tool answers about a whole video, a clip or
  a moment ("what happens at 4:10?", "is there applause in clip 2?"); with the built-in model and a question it also
  looks at the frames again. About a whole video (anything over two minutes) it names every kind of sound with how
  often and when ("laughter 55 times, 0:09 to 54:09"), and a list it shortens says how much it left out; a moment
  past the end gets "the video is only 1:00 long".
- Settings → ClipForge AI → **Watching and listening**: a switch for each (`ai_listen`, `ai_watch`), whether the
  sound model runs on this computer, and whether the model describes the parts.

## Speed and limits

On a 4-CPU Linux computer: Tears of Steel (12 minutes 14 seconds, 1280×534) was listened to in 2.5 seconds and
watched (1,468 frames) in 41 seconds; Sintel (14 minutes 48 seconds) in 2.4 and 18.5 seconds. GitHub's Apple-silicon
Mac numbers are in the check's summary (below). Both run once per video; making clips again reads `sounds.json` and
`watch.json` back.

Everything here is an estimate and is labelled so: YAMNet confuses some sounds (a cheering crowd and a stadium
roar, a slam and a gunshot), the action curve cannot tell a dramatic camera move from a dramatic event, and a 2B
model's sentence about four frames can be wrong. That is why each part is bounded and explained, and why every
candidate still has to pass every stage on its words too.

## Checks

- `tests/test_watch_and_listen.py`: the model ships, loads and hears a tone and silence; the features follow
  YAMNet's framing; events and reactions leave out the words; a song is no longer a reaction but a laugh is;
  watching a real two-shot video finds the cut and the movement and is read back; still parts take the answer of
  the part before; describing asks about the likeliest parts first, keeps answers and stops when the time is up;
  anchors build clips that end on the laugh; the ±9 bound; the Clip Score line; the scout and judge prompts; the
  deep stage; ClipForge AI's answers; the Settings status.
- `.github/workflows/watch-listen-check.yml` (`scripts/watch_listen_check.py`): on GitHub's Apple-silicon Mac and on
  Linux, with Tears of Steel (Blender Foundation, CC BY 3.0) and its subtitles as the transcript: listening and
  watching times and findings, the built-in model describing the film (Linux), and the clips picked with watching
  and listening off and on. `--video` and `--subtitles` run it on another film (Sintel, CC BY 3.0, was checked the
  same way), and `--app` runs an older ClipForge checkout for the "before" picks.
