# ClipFoundry

**Local-first AI clipping for content creators.** Drop in a long video (podcast, stream, interview, lecture, vlog) and
ClipFoundry finds the strongest moments and exports ready-to-post **9:16, captioned MP4 shorts** for TikTok,
YouTube Shorts and Reels.

```
VIDEO → TRANSCRIPT → BEST MOMENTS → CLIPS → 9:16 → CAPTIONS → HOOKS → EXPORT
```

* Runs entirely on your computer: no accounts, no cloud rendering, no subscription. Runtime cost is about **$0**.
* Paid AI APIs are optional and off by default. Local mode needs no API key.
* Personal tool, not a SaaS. Single user, local SQLite database, local files.

> **Windows quick start:** install Python 3.11/3.12 and FFmpeg (`winget install Gyan.FFmpeg`), then double-click
> **`start.bat`**. The app opens at <http://127.0.0.1:8765>. Full instructions are in [INSTALL.md](INSTALL.md).

## Features

| Area | What you get |
| --- | --- |
| Input | Upload or drag & drop MP4, MOV, MKV, WEBM, M4V. Optional import from a public URL via yt-dlp. |
| Transcription | Local `faster-whisper` with word-level timestamps and VAD. Uses an NVIDIA GPU automatically (CUDA, float16). It falls back to the CPU (int8) only when a real CUDA attempt fails, and always says why. `gpu-check.bat` proves the model initializes and runs on CUDA. You can also import an existing SRT/VTT to skip Whisper. |
| Moment discovery | **Stage 1** (fast, local): scores every sentence-bounded window of the full transcript plus loudness (hook, energy, payoff, standalone, topic relevance, pacing). **Stage 2**: re-scores only the strongest candidates with an optional LLM, or the offline heuristic. |
| Clip quality | Cuts land on sentence boundaries padded into pauses, never mid-word. Clips avoid running past the punchline or across topic changes, and snap to hard scene cuts. Clips are diverse (no two from the same moment). Weak moments are dropped, so you may get 3 clips when you asked for 10. |
| Score | Every clip shows an **AI estimate** (0-100) with its breakdown (hook, engagement, context, payoff, standalone). It is an estimate, not a guarantee of views. |
| 9:16 reframing | Auto, Center, **Face tracking**, **Active-speaker tracking** (mouth-motion based, with a cut on speaker change), **Screen content** tracking, or a manual position. Smooth virtual-camera movement, instant re-framing on scene cuts, Fill (crop) or Fit (blurred background) layouts. |
| Captions | Burned-in styles **Clean, Bold, High Energy, Minimal** with word-level highlighting. Adjustable position, size and highlight color. Editable text keeps the original timing. |
| Hooks & titles | One recommended hook and three alternatives per clip, plus title, hashtags and category. Hooks are extracted from the clip's own words; LLM hooks are rejected if they mention names, numbers or topics that are not in the clip. |
| Polish | Light or aggressive silence cleanup, subtle auto-zooms, loudness normalization (-14 LUFS) and volume control. |
| Editor | Simple manual controls: trim (click transcript words), framing, captions, hook, audio, then re-render. Deliberately not a Premiere clone. |
| Export | 1080×1920 MP4, H.264 + AAC. Download clips individually or as a ZIP of 3/5/10 clips, with SRT captions, a text sheet per clip, and `metadata.json` / `metadata.csv` (title, hook, alternatives, caption text, hashtags, source timestamp, score, category). |
| Library | Dashboard, Create, Projects and Settings. Everything (source video, transcript, candidates, clips, metadata) is stored locally. |

## How clip discovery works

1. **Transcribe** with word timestamps (cached per project, so regenerating clips is fast).
2. **Stage 1, local and cheap.** Sentences are built from the words. Every window that starts and ends on a sentence
   boundary and fits the length range is scored in O(1) using running aggregates:
   * *hook*: question openers, hook phrases ("here's the…", "nobody talks about…"), numbers, "you", punchiness, and
     loudness in the first seconds; penalties for dangling starts ("and", "so", "that…").
   * *engagement*: vocal energy and dynamics, emotional and intensity words, pacing.
   * *payoff*: complete final sentence, conclusion markers, story arc, a natural pause after, and not continuing
     past the punchline.
   * *standalone*: no dependence on earlier context, no dead air, no topic transitions inside (TextTiling-style
     topic-shift detection).
   * *context*: similarity to the video's main topics.

   The best windows are de-duplicated by time overlap and text similarity. **Long transcripts are never sent to an
   LLM.**
3. **Stage 2** evaluates only that short list. With a local LLM (Ollama / LM Studio) or the optional Claude API, the
   model's scores are blended with the heuristic scores and may tighten the sentence range. Without one, the heuristic
   scores are used as-is.
4. Selection keeps the best, non-overlapping clips above the minimum score (the single best clip is always kept).

## Architecture

```
clipfoundry/            Python backend (FastAPI)
  api.py                REST API + serves the built UI
  jobs.py               single background worker (one heavy job at a time)
  db.py / config.py     SQLite persistence, settings with defaults
  pipeline/
    ffmpeg_utils.py     probe, audio extraction, encoder selection (NVENC / x264)
    cuda.py             NVIDIA GPU / CUDA library detection for faster-whisper
    transcribe.py       faster-whisper (GPU/CPU plan + fallback) + SRT/VTT import
    audio.py            loudness envelope
    candidates.py       Stage 1 discovery
    scoring.py, llm.py  Stage 2 evaluation (heuristic / Ollama / OpenAI-compatible / Claude)
    hooks.py            grounded hooks, titles, hashtags, categories
    reframe.py          face / speaker / screen tracking, smooth camera path (OpenCV YuNet, PySceneDetect)
    captions.py         ASS caption styles, SRT
    render.py           ffmpeg decode → OpenCV crop/zoom/layout → ffmpeg encode with burned captions
    export.py           ZIP + metadata
  assets/               bundled fonts (OFL) and the YuNet face model (MIT)
frontend/               React + Vite + TypeScript UI (prebuilt into frontend/dist)
tests/                  unit + end-to-end tests
data/                   created at runtime: clipfoundry.db, projects/<id>/..., models/
```

Per project on disk: `data/projects/<id>/source.*`, `audio.wav`, `transcript.json`, `loudness.json`,
`candidates.json`, `clips/<clip>/clip.mp4`, `thumb.jpg`, `captions.ass`, `captions.srt`, `framing.json`.

## Usage

* **Create** → drop a video → choose 3 / 5 / 10 clips, length, caption style, framing → **CREATE CLIPS**.
* Watch the progress (Transcribe → Find moments → Score & hooks → Render). The first run downloads the Whisper model.
* Results show cards with thumbnail, title, duration, AI estimate, category, and **Preview / Edit / Download** buttons.
  Select clips and **Download selected** or **Download all (ZIP)**.
* **Regenerate** reuses the transcript to try different clip counts or lengths.
* Headless / scripting: `python -m clipfoundry process my_video.mp4 --count 5 [--transcript subs.srt]`.
* GPU check: `python -m clipfoundry gpu-check [video]` (or `gpu-check.bat`) runs a real transcription and reports the
  device, compute type, speed and GPU utilization.

## AI scoring providers (Settings → AI scoring)

| Provider | Cost | Notes |
| --- | --- | --- |
| Local heuristic (default) | free, offline | No model needed. |
| Ollama | free, local | `ollama pull llama3.1:8b` (or `qwen2.5:7b`), then select Ollama. |
| LM Studio / OpenAI-compatible | free, local | Any local server exposing `/v1/chat/completions`. |
| Claude API | paid per use | Optional. Paste an API key; only the top candidates are sent (cap in Settings). |

If a provider is unreachable, ClipFoundry falls back to the heuristic automatically and shows a notice.

## Development

```bash
python -m venv .venv && .venv/bin/pip install -r requirements-dev.txt   # Windows: .venv\Scripts\pip
.venv/bin/python -m clipfoundry            # API + built UI on :8765
cd frontend && npm install && npm run dev  # UI dev server on :5173 (proxies /api)
npm run build                              # rebuild frontend/dist (committed so users don't need Node)
.venv/bin/python -m pytest                 # unit + integration tests (integration needs ffmpeg; e2e needs espeak-ng)
.venv/bin/python -m pytest -m "not slow"   # skip the ~2 minute end-to-end render test
```

`tests/make_test_video.py` builds a synthetic talking-head video (espeak-ng speech + a moving face with scene cuts)
for exercising the whole pipeline.

## Responsible use

Only process videos you own or have permission to use. The optional URL import uses yt-dlp for publicly accessible
media only: ClipFoundry does not bypass DRM, paywalls, logins or other access controls, and it never passes cookies or
credentials.

## Third-party assets

* Poppins and Anton fonts: SIL Open Font License 1.1 (`clipfoundry/assets/fonts/OFL-*.txt`).
* YuNet face detector (OpenCV Zoo): MIT (`clipfoundry/assets/models/README.txt`).
* Test fixture face photo: public-domain NASA image.
