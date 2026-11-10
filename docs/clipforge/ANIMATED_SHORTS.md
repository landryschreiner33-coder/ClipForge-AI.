# Animated shorts

ClipForge makes the "faceless" vertical shorts seen on TikTok, YouTube Shorts and Reels: a voice-over read over
moving pictures, with big word-by-word captions, music under the voice and a soft whoosh on the cuts. You paste a
script, or ClipForge AI writes one from a topic. Everything runs on this computer.

This document is the design and the contract between the parts. The user-facing words live in the app.

## What the owner does

1. **Make → Animated short** (`#/create/short`). Choose **Paste my script** or **Write it for me** (a topic, a tone and
   a length). Pick a look, a voice, music and captions (**Fits the look** uses the look's own caption style). Press
   **Make the short**.
2. ClipForge opens the video's editor page (`#/video/<id>`). The **Scenes** panel shows each scene as it is made:
   its words, its picture and where it is (voice, picture, motion, ready, or failed with the reason and **Try again**).
3. When the scenes are ready, the preview plays the short. Everything the editor does for any video still works:
   captions, music level, trims, the order, undo and redo, versions, rendering and FilmCraft.
4. A scene can be changed at any time: new words (new voice), a new picture, an earlier picture, the owner's own
   picture, a different camera move, moved, deleted or added. Each change makes the scenes that need it again and
   saves a new version of the plan (undo goes back). Until the build starts, the short says it is waiting to make
   the change (never "Ready" with a change still to make).
5. **Undo**, **Redo** and going back to a version put the scenes and the short's choices back with the video: the
   Scenes panel shows what the video shows, and the next change builds on it (an undone scene is never made again).
6. **Stop** (or **Stop all jobs**) stops the build; **Make the short** goes on. A scene another voice had to read
   (the chosen one did not work) says so and offers **Try again**; **Make the short** asks the chosen voice for all
   of them. When a picture maker is set up after the short was made with designed cards, **Draw real pictures**
   swaps them.

With **Let me check the script first**, ClipForge stops after writing the script so the owner can change lines;
**Make the short** then makes the voice and the pictures.

## The pipeline

```
script text or topic
  └─ scenes (scenes.py: one picture per 6-16 spoken words; [Visual: ...] lines become the picture)
       or ClipForge AI writes them (writer.py: title, main character, scenes with words and a picture idea)
  └─ for each scene, only what changed:
       voice   (voice.py: the local voice engine, else the computer's own voice) → WAV + timed words
       picture (pictures.py: the local picture engine, else a designed card from cards.py; or the owner's picture)
       motion  (motion.py: a slow push-in or pan on the still, or the video engine's motion) + the voice → MP4
       → stored as a private video asset with its words written as the asset's transcript
  └─ the plan (shorts.py: one clip per scene, cuts, centred highlighted captions, ducked music, whooshes)
  └─ the existing preview and render jobs (video_flow.py, engine.py)
```

Each scene's narration is inside its scene clip, and the clip's transcript (`transcript.json` in the asset's work
folder) holds the script's exact words with their times. So the engine's captions, word fixes, ducking (music dips
under the scene's own sound), previews, renders and FilmCraft export work without knowing that the video is a short.
The only engine change is optional: `captions.highlight` colours the word being spoken.

## Parts and files

| File | What it does |
|---|---|
| `clipfoundry/makers/looks.py` | The looks: style words for the picture engine, card colours and font, caption style |
| `clipfoundry/makers/local_engines.py` | The one door to `clipfoundry.engines` (made by the local-engines work); never raises |
| `clipfoundry/makers/scenes.py` | Pasted script → scenes; lengths; picture words from a scene's own words |
| `clipfoundry/makers/writer.py` | ClipForge AI writes a script from a topic, or picture ideas for a pasted script |
| `clipfoundry/makers/voice.py` | Voices: the engine's, macOS `say`, Windows SAPI, espeak-ng if installed; word times |
| `clipfoundry/makers/cards.py` | A designed picture for a scene when no picture engine is set up |
| `clipfoundry/makers/pictures.py` | The scene's picture: the engine, else a card |
| `clipfoundry/makers/motion.py` | Still picture + voice → a moving scene clip; engine video + voice → a scene clip |
| `clipfoundry/makers/shorts.py` | Projects, scenes, the build job, the plan, the editor page's `short` view |
| `clipfoundry/makers/routes.py` | `/api/studio/shorts/...` |
| `frontend/src/pages/MakeShort.tsx` | The Make page |
| `frontend/src/components/ShortScenes.tsx` | The Scenes panel on the editor page |
| `frontend/src/shorts.ts` | Types and API calls |

## Contracts

### looks.py

```python
@dataclass(frozen=True)
class Look:
    id: str; name: str; about: str
    prompt: str        # style words added to every picture prompt
    negative: str      # what the picture engine should avoid (on top of NEGATIVE_ALWAYS)
    top: str; bottom: str; accent: str; ink: str   # card colours (hex)
    font: str          # card font file in config.FONTS_DIR
    caption_style: str # engine caption style: "bold" | "high_energy" | "clean"
LOOKS: tuple[Look, ...]; BY_ID: dict[str, Look]; DEFAULT: str
NEGATIVE_ALWAYS: str
def get(look_id: str) -> Look                      # unknown id → the default look
def view() -> list[dict]                           # for the page: id, name, about, top, bottom, accent
def prompt_for(look: Look, picture: str, character: str = "") -> tuple[str, str]   # (prompt, negative)
```

### local_engines.py

```python
ROLES = ("image", "video", "voice")
def module()            # clipfoundry.engines, or None when this ClipForge does not have it
def available() -> bool
def status(role) -> dict          # {"ready", "engine", "why", "available"}; never raises
def errors() -> tuple[type[BaseException], ...]   # what an engine call may raise (EngineError and OSError)
```

The engines module (owned by the local-engines work, settings under `#/settings/makers`):
`status(role)`, `make_image(prompt, *, negative, style, width=1080, height=1920, seed, progress, cancel) -> Path`,
`make_video(prompt, *, image, seconds=4.0, width=720, height=1280, seed, progress, cancel) -> Path` (silent MP4),
`speak(text, *, voice, speed, lang, progress, cancel) -> {"path", "duration_s", "words": [{"text", "start_s",
"end_s"}] | None, "word_timing", "rule", ...}`, `voices() -> [{"id", "name", "lang", "gender", "about"}]`,
`EngineError`. `progress(fraction, message)` and `cancel() -> bool` everywhere. The makers ask for 1080x1920 pictures
and 720x1280 motion (the engine snaps them to sizes its model can make) and scale to 1080x1920 themselves; they copy
what they keep out of the engine's own folder. Word times the engine only estimated (`word_timing: "estimated"`) are
not used: listening or the estimate from the sound is better. `rule` is what the voice's licence asks of what it makes
(Supertonic, OpenRAIL-M: label it as machine-generated where it is posted); the short keeps it with each scene's voice,
lists it in **How this short was made** and shows it next to **Download** on the editor page.

### scenes.py

```python
LENGTHS = {"short": (15, 30, 22), "standard": (30, 60, 45), "long": (60, 90, 75)}   # min, max, target seconds
WPM = 175                       # words a minute at speed 1.0
SCENE_WORDS = (6, 16)           # a scene's spoken words (soft minimum, hard maximum when merging)
MAX_SCENES = 80; MAX_WORDS = 600  # 600 words in scenes of 6-16 words can need more than 40 scenes
class SceneError(ValueError)    # message for the owner
def split(text: str) -> list[dict]
    # [{"narration": str, "picture": str, "picture_from": "script" | ""}] in order. Spoken lines are cut into
    # sentences, long sentences are split at a comma or a joining word near the middle, short ones are merged up to
    # SCENE_WORDS; a blank line or a "Scene 3" heading ends a scene; a direction line ([Visual: ...], (b-roll ...),
    # "Show: ...") is the picture of the next scene, its label taken off. Raises SceneError: no spoken words, more
    # than MAX_WORDS words or MAX_SCENES scenes.
def split_narration(text: str) -> list[str]    # one narration into scene-sized pieces (the same rules)
def seconds(text: str, speed: float = 1.0) -> float     # how long the words take to say
def picture_words(narration: str, subject: str = "") -> str   # a picture idea from the scene's own words
def subject_of(narrations: list[str], title: str = "") -> str  # the thing the script is about, for every picture
```

### writer.py

```python
TONES = {"curious": ..., "dramatic": ..., "funny": ..., "spooky": ..., "inspiring": ..., "calm": ...}  # id → words
class WriterError(RuntimeError)   # message for the owner
def ready(settings: dict) -> dict   # {"configured": bool, "label": str, "local": bool}
def write(topic: str, *, tone: str, length: str, audience: str, look: Look, settings: dict, workspace_id: str,
          project_id: str = "", cancel=None, beat=None) -> dict
    # {"title", "character", "scenes": [{"narration", "picture"}], "notes": [str], "model": str, "local": bool,
    #  "memories": [ids], "knowhow": [ids]}
def picture_ideas(narrations: list[str], *, title: str, look: Look, settings: dict, workspace_id: str,
                  project_id: str = "", cancel=None, beat=None) -> dict
    # {"character": str, "pictures": [str, one per narration], "model", "local", "memories", "knowhow"}
```

The model answers one JSON object that follows a JSON schema (the built-in model follows it exactly). It reads the
owner's memories first (`brain.recall`, recorded as used in "short_script"), then the know-how playbooks for the
"short" task (`knowhow.select(topic, "short")`: the new "shorts" playbook, hooks, endings). An outro line is taken off
the last scene, a scene longer than 16 words is split, empty scenes are dropped, a script far from the asked length is
asked for once more. `beat(message)` keeps the job's lease alive while the model thinks; `cancel()` stops waiting.
Without a model, `write` raises WriterError with the way to set one up; `picture_ideas` raises and the caller uses
`scenes.picture_words`.

### voice.py

```python
def voices() -> list[dict]
    # [{"id", "name", "lang", "gender", "about", "engine"}]; "auto" first, then the engine's voices ("engine:<id>"),
    # then this computer's voices ("system:<name>": macOS say, Windows SAPI; "espeak:<voice>" when espeak-ng is
    # installed). Novelty voices are left out. Cached for ten minutes (half a minute when a listing failed). A voice
    # whose lang is "multilingual", "mul" or "" reads every language (the engine's voices say so).
def default_voice() -> str
def speak(text: str, out: Path, *, voice: str = "auto", speed: float = 1.0, lang: str = "en", cancel=None) -> dict
    # writes `out` (WAV, mono, 48 kHz, 16-bit, silence at both ends trimmed to 40 ms) and returns
    # {"path", "duration_s", "words": [{"w","start","end"}] | None, "engine": "engine" | "say" | "sapi" | "espeak",
    #  "voice": name, "fallback": why the asked voice was not used ("" when it was), "rule": what the voice's
    #  licence asks of what it makes ("" for none)}. Raises VoiceError.
def estimate_words(wav: Path, text: str) -> list[dict]
    # word times from the sound alone: the voiced stretch, its pauses matched to the text's punctuation, each phrase
    # shared out by syllables. Always works; the words are the script's words with their punctuation.
def align_words(text: str, heard: list[dict]) -> list[dict]
    # the script's words with the times of the words a speech model heard (matched in order; the rest interpolated)
def time_words(wav: Path, text: str, *, engine_words=None, settings=None, listen: bool = True, cancel=None,
               used: dict | None = None) -> tuple[list[dict], str]
    # (words, how): "engine" (the engine said), "listened" (the speech model is installed and downloaded: transcribed
    # and aligned; never downloads), "estimated". `cancel` stops the listening; used["model"] becomes True when the
    # speech model was asked (the build then gives its memory back even if no scene's times came from it)
class VoiceError(RuntimeError)
```

macOS: `say -v <name> -r 175 -f <text file> -o <file>.aiff`. Windows: PowerShell with System.Speech at its usual
rate (text, voice and paths passed in environment variables and a file, never in the command line). Linux and
anything else: `espeak-ng` (or `espeak`) when installed, run as its own program, `-s` 175 × speed. Speed 1.0 is
about 175 words a minute. `[[` and `]]` in the words are broken up before `say` (its commands) and espeak-ng
(phoneme codes), so a script is only ever read aloud. The engine and espeak-ng read at the speed asked; macOS and
Windows voices read at their usual pace and FFmpeg's `atempo` then sets the speed without changing the pitch,
because their own rate settings are uneven: on GitHub's Apple-silicon Mac, `say -r` at 1.3 times the words a minute
read 1.7 times as fast, and the Windows rate has only whole steps (Calm and Lively both read at the usual pace) and
read 1.44 times as fast for 1.3.

### cards.py

```python
def key_words(narration: str, limit: int = 4) -> str     # the scene's key words for its card
def make_card(text: str, look: Look, out: Path, *, index: int = 0, size=(1242, 2208), seed: int = 0) -> Path
    # PNG: the look's gradient, soft shapes placed by `index` and `seed` (New picture gives the scene a new seed),
    # the key words big between 18 and 42 percent of the height (clear of the centred captions and the apps'
    # buttons); a word too wide even at the smallest size gets smaller letters, never cut off. Larger than
    # 1080x1920 so a push-in stays sharp. Raises CardError in plain words.
```

### motion.py

```python
MOVES = ("zoom_in", "zoom_out", "pan_left", "pan_right", "pan_up", "pan_down", "still")
def pick_move(index: int) -> str                  # alternating: zoom_in, pan_right, zoom_out, pan_left, ...
def still_clip(picture: Path, audio: Path, out: Path, *, duration_s: float, move: str = "zoom_in", fps: int = 30,
               size=(1080, 1920), strength: float = 0.08, cancel=None, progress=None, background=None) -> dict
def video_clip(video: Path, audio: Path, out: Path, *, duration_s: float, fps: int = 30, size=(1080, 1920),
               cancel=None, progress=None) -> dict
    # both → {"path", "duration_s", "frames"}; an H.264 (BT.709, yuv420p) + AAC 48 kHz MP4 whose length is exactly
    # frames / fps; the audio is the voice, padded with silence to the end. Raises MotionError.
```

`still_clip` covers the frame with the picture and moves it with OpenCV (sub-pixel, so there is no jitter), frames
piped to FFmpeg. The picture is read with Pillow, upright: a see-through picture lies on `background` (the look's
bottom colour), a JPEG much larger than the move needs is decoded at an eighth, a quarter or half its size, and a
picture over Pillow's limit (about 180 million pixels) is refused in plain words. `video_clip` covers the frame with
the engine's video, slows it down up to 1.5 times when it is shorter than the voice and holds its last frame for the
rest. `pictures.make` opens the engine's picture all the way before using it; one that does not open (cut short by a
crash or a full disk) becomes a designed card with the reason.

### shorts.py (the job and the plan)

* `create(workspace_id, user_id, *, name, options) -> project` makes a `studio_projects` row with
  `workflow = "animated_short"` and its options in the new JSON column `short`; a pasted script is split into scenes
  at once (an error the owner must fix is raised before anything is saved). Queues `short_build`.
* Scenes are rows of the new table `short_scenes`. Each scene keeps keys of what it was made from (`voice_key`,
  `picture_key`, `clip_key`); a build makes again only what changed, so a restart or a repeated build is cheap.
* `short_build` (studio job, revision = the short's build number) writes the script when asked, stops for review
  when asked, makes each scene that needs it (one scene failing never stops the others), saves the plan as the next
  version and queues the preview. Voices are kept under the project's folder by key, so going back to earlier words
  reuses their voice.
* The plan: `maker: "animated_short"`, 9:16 at 30 fps, fill, straight cuts, one clip per ready scene (clip id = scene
  id), captions centred with the look's caption style and `highlight: true`, the chosen music bed from the built-in
  library at -20 dB with ducking, and a whoosh on every other cut (-14 dB, attached to its clip). A later build keeps
  the owner's edits: the order, trims of unchanged scenes, removed clips, captions, music level, tracks, word fixes
  of unchanged scenes and pictures placed over the video; ClipForge's own whooshes are placed again.
* Each version of the plan keeps, under `plan.short`, the scenes as they made the clips in it (`rows`: the fields in
  `ROW_STATE` and `info`; a scene not in the video yet keeps its status) and the short's choices (`options`).
  Undo, redo and restore (`video_flow._jump`) call `going_back`, which puts them back in the same database step
  that saves the version (`save_revision(..., also=...)`): scenes are put back, re-added or taken away, choices set
  back. A change the owner made after the version being left and not yet made stays and is made on top; a build
  that was waiting gets a new build number so it builds on what was put back. Versions saved before this have no
  `rows`: the scenes then stay as they are.
* Stopping: `studio.jobs.on_stop("short_build")` hears a canceled build and one given up after repeated
  interruptions; Stop all jobs cancels the studio job that is running too. `stopped(project_id, build)` only acts on
  a short still making or writing, and never for an older build. Writes that end a build (ready, failed, stopped)
  happen only when no newer build was asked for (`_patch_short(..., if_build=...)`), and an overtaken build saves no
  version of its own.
* Errors reach the owner in plain words (`_plain`): the voice, motion, card and upload messages are written for the
  owner; a full disk, a permission problem or another file problem, the video tool and anything else get a plain
  sentence, and the cause goes to the log.
* Tidying: every picture and clip a build stores goes on the short's list (table `short_files`) as soon as it is
  stored. At the start and the end of each build, a file on the list that nothing names any more is deleted (its row,
  its read-only copy and its folder with its transcript, thumbnail and maker's original): a clip a later build
  replaced before any version kept it (a build overtaken by a newer change saves no version), a picture that left a
  scene's earlier pictures, a deleted scene's files, a file a stopped build stored before a scene took it. A clip a
  build made and then threw away (its scene changed or went meanwhile) goes at once. "Names" means a scene (picture,
  earlier pictures, clip), any saved version (so undo can bring it back), any other video, clips project, upload,
  link, example, import, source note or another short's list: files are stored once, so the same bytes may be in use
  elsewhere, and then the file stays. It is checked again in the step that deletes the row. Working folders and
  half-recorded voices an app closed mid-build left are deleted once they are an hour old; the oldest recorded voices
  no scene uses go once a short has more than 120. Deleting the short (studio/project_delete.py) reaches every file on
  its list, also one no scene or version names.
* The makers on this computer (clipfoundry/engines) save what they make in `data/engines/made` with a note. What a
  short uses is taken out of there and kept with what the short made from it, so it goes when that does: a made
  picture becomes the scene's stored picture (its note is `maker.json` in the picture's folder), the video maker's
  clip and note go into the scene clip's folder (`maker.mp4`, `maker.json`), and the voice engine's recording and
  note go into the short's voice folder (`voice/maker/<voice key>.wav` and `.json`, tidied with that voice). A
  picture or video clip of the maker's that the short could not use is deleted with its note (the reason is kept
  with the scene). Voice samples (`voice-sample`) are not projects: their engine originals stay in engines/made.
* `view(project)` is the `short` part of the editor page's video (`GET /api/studio/videos/<id>`): the options, stage
  and message, the scenes in the plan's order, progress, seconds (the video's length plus an estimate for scenes
  not in it yet), engines, `cards_to_swap` (designed cards a ready picture maker would replace: **Draw real
  pictures**), the writer, `voice_rule` (shown next to Download) and notes (also the plan's notes).
* A change (`update_scene`, `add_scene`, `delete_scene`, `set_options`, `make`) bumps the build number, sets the stage
  to `making` ("Waiting to make the changes", or "Waiting to start" after **Make the short**) unless the short
  waits for the owner to check the script, and queues
  `short_build`; a build that finds a newer build number waiting leaves the last word to it.

### The API

| | |
|---|---|
| `GET /api/studio/shorts/options` | looks, voices, tones, lengths, captions ("" fits the look), music, speeds, what each engine can do, whether ClipForge AI can write |
| `POST /api/studio/shorts` | make a short (`mode` paste or write, `script` or `topic`, options) → the video |
| `POST /api/studio/shorts/voice-sample` | a few seconds of a voice (WAV); when another voice had to read it, the header `X-ClipForge-Note` says so (URL-encoded) and that sample is not kept |
| `PATCH /api/studio/shorts/{video_id}/scenes/{scene_id}` | words, picture idea, move, the owner's picture, an earlier picture, `again` |
| `POST /api/studio/shorts/{video_id}/scenes` | add a scene after another |
| `DELETE /api/studio/shorts/{video_id}/scenes/{scene_id}` | delete a scene |
| `POST /api/studio/shorts/{video_id}/make` | go on after checking the script, or make every scene that needs it |
| `PUT /api/studio/shorts/{video_id}/options` | voice, speed, look, music, captions, motion for the whole short |

Every change answers with the whole video (as `GET /api/studio/videos/<id>`), so the page updates at once.

## What stays as it is

* `video_flow`'s footage features ("Edit it for me", Script) say they are for filmed videos when used on a short.
* With the editing app setting on "auto", a short is rendered by the built-in engine (it keeps the highlighted
  captions); choosing FilmCraft for every final video still uses FilmCraft.
* Nothing is sent anywhere: the voice, pictures, motion and writing run on this computer (a cloud AI provider the
  owner chose in Settings is the only exception, and the page says so).

## Limits

* Without a picture engine, pictures are designed cards with the scene's key words. They are honest placeholders,
  not illustrations: the page says so and links to Settings → Pictures, video, voice (`#/settings/makers`).
* The computer's own voices are clear but plain; a local voice engine sounds better.
* Word times are exact when the engine gives them or the speech model is downloaded; otherwise they are estimated
  from the sound (pauses and syllables), close enough for captions but not frame-exact.
* A script is at most 600 words (about three and a half minutes) and 80 scenes.
* Real computers: `.github/workflows/shorts-check.yml` runs `scripts/shorts_check.py` on GitHub's macOS 15
  (Apple silicon), Windows and Ubuntu machines: it lists the computer's voices, reads with the one ClipForge picks
  and two more, checks that the speeds are even, then makes a short from a pasted script with designed cards and
  camera moves, renders it and checks the size, frame rate, sound, length and burnt-in captions. The Mac's own
  voices (Samantha, Daniel, Eddy), the Windows voices (Zira, David) and espeak-ng were checked this way.
* What could not be tried anywhere but the owner's Mac: the local picture, video and voice engines (they need the
  models), the Premium and Enhanced macOS voices the owner downloaded, ClipForge AI writing a real script (no model
  in the cloud) and word times from the speech model.
