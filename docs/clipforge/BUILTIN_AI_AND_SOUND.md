# Built-in model and sound cleanup (phase 1 of the smarter editor plan)

Phase 1 of the plan Landry approved on 2026-11-06 ("Start phase 1"): an AI that comes with ClipForge and runs on the
computer, and a "Clean up the sound" step for every clip and full video. The plan itself (all four phases) is the
Claude Doc linked from the project thread.

## Built-in model (`clipfoundry/builtin_ai.py`)

**What the user sees.** Settings → ClipForge AI lists "Built-in model" first (and picks it by default). It shows the
computer's memory and graphics memory, the recommended level, and one Download button. Nothing is downloaded until
then; the installer does not grow. After the download the built-in model becomes ClipForge AI's model (only if the model was
"None" or already built-in; a chosen Ollama, LM Studio or key is never replaced). "What gets downloaded" lists every
file and has Remove buttons.

| Level | Model (all Apache 2.0) | Download | Picked when |
|---|---|---|---|
| Basic | Qwen3-VL 2B (Q4_K_M + vision part) | about 1.6 GB | the default for smaller computers |
| Standard | Gemma 4 E4B (Q4_0 + vision part) | about 5.2 GB | a Mac with 16 GB, or a PC with an 8 GB graphics card, or 16 GB and a 4 GB card |
| Pro | Gemma 4 26B A4B (Q4_0 + vision part) | about 15.4 GB | only when chosen by hand |

**Engine.** llama.cpp's `llama-server`, release `b12017` (MIT), the official build for the platform (Mac Apple
silicon, Windows x64 Vulkan, Linux x64). It is downloaded once with the first level and its archive is checked against
a pinned SHA-256 before it is unpacked (no absolute paths, no `..`, links only inside its folder).

**Pinned downloads.** Every model file is fetched from Hugging Face at a pinned revision and checked against its
pinned size and SHA-256; a marker file is written only after every file of a folder passed. A damaged or tampered
file is deleted and the download says so. Downloads resume; a disk-space check keeps 2 GB free; cloud mode refuses.

**Running.** The engine starts on first use, on 127.0.0.1 with a free port and a random API key, with `--offline`
and no web UI. It stops after 10 idle minutes (Settings: `builtin_ai_idle_minutes`), when ClipForge quits (Windows job
object, Linux parent-death signal, `atexit`, the server's shutdown), and before transcription or another heavy GPU job
takes the graphics card (`gpu._make_room`; a Mac with 24 GB or more keeps it loaded). A pid file lets the Autopilot
worker share the running engine; a leftover engine whose owner died is stopped, and only if it really is the
installed engine program.

**Use.** `ai_provider = "builtin"` goes through the same `pipeline/llm.py` paths as Ollama (it counts as local, so
nothing leaves the computer): clip scoring, post text, the full-video AI editor and change requests, and the AI pass
that finishes final videos with FilmCraft's tools and EffectCraft shots (`craft/ai.py`, see
[CRAFT_APPS.md](CRAFT_APPS.md); its request is shortened to fit the 8,192-token context and it answers in JSON mode).

## Clean up the sound (`clipfoundry/pipeline/cleanup.py`)

**Setting.** `clean_sound`: Off, Auto (default), Gentle, Strong. In Settings (defaults), per clip in the clip editor's
Audio tab, and per video in the full-video editor's Sound panel (`plan.clean_sound`, set with
`{"op": "set", "field": "clean_sound"}`; without it, Settings decide).

**Auto** listens first (a 16 kHz decode of the range) and leaves the sound as it is when the range is mostly not
speech (words cover under 30%), when the pauses hold music (tonal peaks, mains hum excluded), or when it is silent.
Otherwise it uses Gentle.

**Steps, in order** (all on the CPU, cached):

1. Mic balance: when one channel is more than 15 dB quieter than the other, or the two cancel out (correlation below
   -0.3), only the live channel is used; otherwise both are mixed to mono.
2. Rumble and hum: a high-pass at 70 Hz (Strong: 80 Hz); 50 or 60 Hz mains hum is found in the pauses and each of its
   multiples that stands out gets a narrow notch.
3. Background noise: DeepFilterNet 3 (MIT or Apache-2.0), a 13 MB speech model, through ONNX Runtime, in 30-second
   blocks that run side by side (each starts 1 s early to settle; blocks meet with a 10 ms crossfade; the model's
   1,536-sample delay is removed). Gentle keeps 12 dB of the original under the cleaned voice so the room still
   sounds natural; Strong keeps 30 dB. The model is downloaded on first use from the pinned
   `wuxuedaifu/deepfilter-stream` release `model-dfn3-512-v1` and checked against three pinned SHA-256 hashes.
   Without it (offline, or ONNX Runtime missing) a spectral noise gate measured on the pauses does this step and the
   note says so; after a failed download the gate is used for an hour before trying again.
4. Levels: a slow gain that ignores pauses evens out quiet and loud passages (Gentle: half of the difference, -4 to
   +6 dB; Strong: 80%, -6 to +9 dB), and speech is brought to about -20 dBFS.
5. Breaths: sounds of 0.1 to 1 s in a pause, 12 to 40 dB under the voice, are turned down 6 dB (Strong: 12 dB).
6. Voice polish: de-esser, a compressor that only presses the louder syllables (above -18 dBFS, 2:1 or 3:1), a little
   presence at 4 kHz (and less mud at 300 Hz on Strong).

The result is a raw 48 kHz mono float file of exactly the range's length, so every cut, caption and frame stays where
it was (the filters' phase shift is under a millisecond). The renderer's own loudness normalization still sets the
final level. Clip renders clean `[start, end + 0.2 s]`; the full-video editor cleans each source file once, whole, and
every cut and preview reads from it. Files are cached under `data/cache/clean-sound` (4 GB cap, oldest removed first),
keyed by the file's path, size and time, the range, the level, the word timings and which denoiser was used.

**What it reports.** `render_info.audio_processing.clean_sound` (clips) and `clean_sound[asset_id]` (full videos):
noise below the voice before and after, hum, breaths softened, the channel used, the denoiser, and a one-sentence
summary shown under the clip's Audio settings. A failure never fails a render: the original sound is used and the
note says why.

**Before/after.** The clip editor's "Compare before and after" (`POST /api/clips/{id}/sound-check`) makes two WAV
files of the clip (at most 90 s), the original and the cleaned sound, matched in loudness so the switch compares
clarity rather than volume; the player keeps its place when switching. It uses the clip's saved trim and the render's
cache, so the next render reuses the cleaning.

## Checks

- `tests/test_builtin_ai.py`: downloads from a local stand-in for the release and Hugging Face, tampered and partial
  files, unsafe archives, disk space, the engine's key, idle stop, GPU hand-off, a leftover and a shared engine, the
  provider and the routes (a stand-in server in `tests/fake_llama_server.py`).
- `tests/test_clean_sound.py`: Auto's decisions (noisy speech, music, not speech, silence), hum, a dead and an
  inverted channel, levels, breaths, alignment, the cache and its cap, the verified model download, a clip render in
  sync, the before/after routes and the full-video editor. `test_the_real_voice_model` runs DeepFilterNet when
  `CLIPFORGE_TEST_DFN_DIR` points at its three files.
- `.github/workflows/builtin-ai-check.yml` (`scripts/builtin_ai_check.py`): on a Mac (macos-15), Linux and Windows
  runner, the real engine and the Basic level download, verify, start and answer a clip-scoring prompt as JSON and a
  picture question; load time and speed are reported. Linux also checks the whole catalog against Hugging Face and
  the llama.cpp release; Mac and Linux time the sound cleanup on a minute of synthesized speech.
- `macos/desktop_media_smoke.py` (run by `macos-desktop.yml`): inside the built Mac app, the bundled ONNX Runtime
  loads the downloaded voice model and cleans macOS speech with added noise and hum through the bundled FFmpeg.

**First measurements** (2026-11-06, `builtin-ai-check.yml` run 42160482511, Basic level, GitHub's test machines):

| Machine | Download + check | First load | Warm answer | Speed | Sound cleanup, 1 minute |
|---|---|---|---|---|---|
| Linux, 4 cores, 16 GB | 6.6 s | 1.6 s | 2.7 s | 35.7 tokens/s | 1.5 s |
| Windows, 4 cores, 16 GB | 12.9 s | 4.5 s | 2.8 s | 22.9 tokens/s | not run |
| Mac (virtual, 3 cores, 7 GB, no graphics access) | 14.5 s | 32.4 s | 19.6 s | 5.0 tokens/s | 6.0 s |

Every machine answered the scoring prompt as JSON and named the picture's color. The Mac runner cannot use the
graphics chip, which llama.cpp uses on a real Mac, so it is a lower bound.

## Not verified

- Real models on a physical Mac, Windows PC or graphics card (only GitHub's test machines, which have no usable GPU).
- Standard and Pro answers' quality; whether Basic's judgments are good enough to be the default for 8 GB computers.
- Listening tests on real recordings (the checks use synthesized speech and measured noise levels).
