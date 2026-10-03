# ClipFoundry

**Local-first AI clipping for content creators.** Drop in a long video (podcast, stream, interview, lecture, vlog) and
ClipFoundry finds the strongest moments and exports ready-to-post **9:16, captioned MP4 shorts** for TikTok,
YouTube Shorts and Reels.

```
VIDEO → TRANSCRIPT → BEST MOMENTS → CLIPS → 9:16 → CAPTIONS → HOOKS → EXPORT
```

* Runs entirely on your computer: no ClipFoundry accounts, no cloud rendering, no subscription. Runtime cost is about
  **$0**. The only network use is optional: publishing and reading your own videos' statistics through the official
  YouTube and TikTok APIs.
* Paid AI APIs are optional and off by default. Local mode needs no API key.
* Personal tool, not a SaaS. Single user, local SQLite database, local files.

> **New: Autopilot.** ClipFoundry can now run as a persistent, local-first content opportunity engine: it finds
> trending opportunities, checks the rights of every source, clips and packages the best moments, schedules them in
> your time zone and publishes the posts you approve, then learns from the real results. Targets (3 sources, up to 5
> clips each, 15 posts a day) are never quotas. Setup is three steps: add your videos, choose how to work, set up
> posting (connect YouTube and, optionally, TikTok), then **Start Autopilot**; it only asks you what really needs you.
> See **[docs/AUTOPILOT.md](docs/AUTOPILOT.md)**.

> **Windows quick start:** install Python 3.11/3.12 and FFmpeg (`winget install Gyan.FFmpeg`), then double-click
> **`start.bat`**. The app opens at <http://127.0.0.1:8765>. Full instructions are in [INSTALL.md](INSTALL.md).

## Features

| Area | What you get |
| --- | --- |
| Input | On **Add video**, choose or drag & drop MP4, MOV, MKV, WEBM, M4V. Optional import from a public URL via yt-dlp (*Import from a link instead*). |
| Transcription | Local `faster-whisper` with word-level timestamps and VAD. Uses an NVIDIA GPU automatically (CUDA, float16). It falls back to the CPU (int8) only when a real CUDA attempt fails, and always says why; Autopilot pauses instead unless you allow its CPU fallback. `gpu-check.bat` proves the model initializes and runs on CUDA. You can also import an existing SRT/VTT to skip Whisper (Add video → *More options* → *Attach a transcript…*). |
| Moment discovery | **Stage 1** (fast, local): scores every sentence-bounded window of the full transcript plus loudness (hook, energy, payoff, standalone, topic relevance, pacing). **Stage 2**: measures only the strongest candidates on eleven Viral Potential factors, locally or blended with an optional LLM, then ranks them. |
| Clip quality | Cuts land on sentence boundaries padded into pauses, never mid-word. Each candidate's opening and ending are optimized: a warm-up line is dropped, the clip stops at its payoff, or runs one line longer instead of cutting before an answer. Clips prefer a **hook → context → payoff** structure and avoid slow openings, excessive setup, repetition, missing context, misleading cuts and weak endings. **Quality over quantity:** only clips that pass the quality bar are shown, so you may get 3 clips (or none) when you asked for 10. No filler is added. |
| Score | Every clip shows a **Viral Potential** score (0-100) with four sub-scores (**Hook Score, Retention Potential, Context Score, Engagement Potential**) and eleven factors. All of them are estimates used to rank clips, not a guarantee of views. |
| 9:16 reframing | Auto, Center, **Face tracking**, **Active-speaker tracking** (mouth-motion based, with a cut on speaker change), **Screen content** tracking, or a manual position. Smooth virtual-camera movement, instant re-framing on scene cuts, Fill (crop) or Fit (blurred background) layouts. |
| Captions | Burned-in styles **Clean, Bold, High energy, Minimal** with word-level highlighting. Adjustable position, size and highlight color. Editable text keeps the original timing. |
| Hooks & titles | One recommended hook and three alternatives per clip. Hooks are extracted from the clip's own words; LLM hooks are rejected if they mention names, numbers or topics that are not in the clip. |
| Post package | For every clip: **three title options** (one recommended), **three caption/description options**, hashtags, a short description, a call-to-action suggestion and hook text. All of it is written from the clip's own transcript. A grounding check rejects any number, name, claim or topic that is not in the clip, including an optional LLM's suggestions. Hashtags are words the speaker actually says. Everything is editable (Edit clip → **Post text**) before anything is published, and it is included in the export. |
| Polish | Light or strong silence cleanup that also cuts "um"/"uh" together with the pause around them, subtle push-ins on sentences with an emphasized word, optional key-word emphasis in the captions, adjustable pacing (up to 1.15×, same voice pitch), loudness normalization (-14 LUFS) and volume control. Active-speaker framing only switches while someone is actually talking, so a nod or a laugh during a pause never moves the camera. |
| Versions | In the clip editor (**Versions**, under the timeline), **Create versions…** renders **Faster pacing** (tighter pauses, no fillers, 8% faster), **Alternative hook** (another hook line from the clip, and a stronger first line when the clip has one) and **Alternative caption style** (contrasting style with key words emphasized) next to the **Original**. **Compare** them side by side (played together, sound from the one you pick) or one after another, then choose which one is published and exported (*Used for export and posts*). |
| Editor | Simple manual controls in the groups **Trim** (click transcript words), **Captions** (with the hook), **Layout** (framing), **Audio** and **Post text**, then **Save and render**. Deliberately not a Premiere clone. |
| Export | 1080×1920 MP4, H.264 + AAC. Download clips individually or as a ZIP of 3/5/10 clips, with SRT captions, a text sheet per clip, and `metadata.json` / `metadata.csv` (title, hook, alternatives, caption text, hashtags, source timestamp, score, category). |
| YouTube Shorts | **Connect YouTube** with OAuth (your own Google Cloud "Desktop app" client, PKCE, loopback redirect). The connected channel's name is shown. Resumable uploads through the official YouTube Data API v3 with title, description, tags, privacy (Public / Unlisted / Private) and the made-for-kids answer, with progress and success/failure status. Unaudited API projects are locked to Private by Google; ClipFoundry explains that before and after the upload. Passwords are never stored; tokens are encrypted with Windows DPAPI. |
| TikTok | **Connect TikTok** with TikTok's official Login Kit (desktop OAuth with PKCE). Posts through the official Content Posting API: **Direct Post** with caption and hashtags, the privacy options TikTok offers for your account (never pre-selected), comment/duet/stitch permissions and the commercial content disclosure, following TikTok's sharing guidelines; chunked upload with progress and status polling. Without TikTok's audit, Direct Post is limited to private accounts and "Only me"; the fallback is the official **Send to TikTok inbox** draft flow, or exporting and uploading in TikTok Studio. No scraping, no unofficial automation. |
| Prepare post | One page per clip (**Prepare post**): video preview, editable title, description/caption and hashtags (with the generated options one click away), YouTube *Who can see it* and made-for-kids, TikTok privacy/interactions/disclosure, and explicit **Publish to YouTube now…**, **Post to TikTok now…** (or **Send to TikTok inbox…**) and **Export** buttons. Every publish needs a confirmation. Status, progress and links for each upload stay listed there (*Uploads you started here*). |
| Performance | **Real numbers only.** For your uploads, ClipFoundry reads views, likes and comments (YouTube Data API), shares, watch time, average view duration and % viewed (YouTube Analytics API, when enabled) and views, likes, comments and shares (TikTok `video.query` for public posts). Each refresh stores a timestamped snapshot; a metric the platform does not report stays empty ("—") with the reason, never estimated. TikTok posts finished in the app can be linked by URL. **Posts → Results** shows totals with their coverage and, once 10+ uploads have view counts, how well Viral Potential ordered them. The data (scores at publish time next to real results) can be downloaded as CSV (**Download data (CSV)** under Posts → Results) or JSON as the basis for tuning the ranking later. |
| Autopilot | Durable background workers (Trend Scout, Source Scout, Rights and Content Safety Gate, Live Monitor, Clip Hunter, Deep Clip Analyzer with diversity selection, Packaging AI, Final Quality Gate, Smart Scheduler, YouTube Quota Manager, Publisher, Learning Worker) on a SQLite job queue that survives restarts. One heavy GPU job at a time on the existing CUDA path. Visible Trend, Source, Clip, Diversity, Packaging, Expected Retention, Publish Opportunity and Final Opportunity scores. A simple **Overview** (**Start Autopilot** / **Pause Autopilot**, this PC and the GPU, **Needs you**, what it is working on, your videos folder, upcoming posts and how they go out), an **Activity** tab (top opportunities, and what it did with each video it found) and **Permissions & sources**, with a three-step first-time setup (add your videos, choose how to work, set up posting, then **Start Autopilot**); workers, GPU, quota, jobs and learning under **Advanced**; **Stop all jobs…** always at hand. Details: [docs/AUTOPILOT.md](docs/AUTOPILOT.md). |
| Posts | Every planned and published post in one place, with the tabs **Needs review**, **Scheduled**, **Published** (canceled and replaced posts too, as History), **Problems** and **Results**. Each post opens as its own page: **Approve for YouTube** / **Approve for TikTok** (required by YouTube and TikTok), edit the text, **Change the time…**, **Cancel this post…**, **Try again…**, **Publish now…**, open the clip, the source video and the post, with the reasons behind each slot and score and an audit trail. |
| Rights | Every source has a status: Owned, Licensed, Creative Commons, Public domain, Allowlisted, Not covered or Blocked. Discovery is not authorization: only sources you have rights to are clipped automatically. |
| Library | **Home**, **Autopilot**, **Library** (your source videos and their clips), **Posts** and **Settings**, plus **Add video**. Everything (source video, transcript, candidates, clips, metadata) is stored locally. |

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
   model scores the factors it can judge from text and those are blended with the local measurements; it may also
   tighten the sentence range. Without one, the local analysis is used as-is.
4. **Viral Potential.** Each shortlisted candidate is measured on eleven factors: hook strength, opening strength,
   curiosity (an open loop that the clip closes), emotional intensity, information density, story/payoff, standalone
   context, pacing (speaking rate, dead air, filler), uniqueness (repetition inside the clip and overlap with the other
   candidates), speaker clarity (Whisper word confidence and how clearly speech stands out from the background) and
   retention potential. Appeal factors (hook, curiosity, emotion, payoff, retention) decide how interesting a clip is;
   quality factors decide how much of that survives. A clear hook → context → payoff structure earns a bonus. Nearby
   sentence ranges are compared too (one line earlier, up to three later, shorter or longer endings), and the best
   one is kept.
5. **Quality gate.** A clip is shown only when its Viral Potential reaches the minimum (Settings → Advanced →
   Rendering, AI scoring and system → *Minimum Viral Potential*, default 50) and it has no blocking problem: a
   misleading cut (ends right before the answer or the point), a topic change inside, a start that needs outside
   context, or an ending mid-sentence. Slow openings, excessive setup, repetition and weak endings lower the score. The
   source video page lists what was left out and why.
6. Selection keeps the best non-overlapping clips that pass, up to the requested count.

## Architecture

```
clipfoundry/            Python backend (FastAPI)
  api.py                REST API + serves the built UI
  jobs.py               single background worker (one heavy job at a time)
  db.py / config.py     SQLite persistence, settings with defaults
  pipeline/
    ffmpeg_utils.py     probe, audio extraction, encoder selection (NVENC / x264)
    cuda.py             NVIDIA GPU / CUDA library detection for faster-whisper
    models.py           Whisper model download, verification and automatic repair
    transcribe.py       faster-whisper (GPU/CPU plan + fallback) + SRT/VTT import
    audio.py            loudness envelope
    candidates.py       Stage 1 discovery
    virality.py         Viral Potential: 11 factors, sub-scores, structure, avoidance flags
    scoring.py, llm.py  Stage 2 evaluation, ranking and quality gate (local / Ollama / OpenAI-compatible / Claude)
    hooks.py            grounded hooks, titles, categories
    postpack.py         post packages (titles, captions, hashtags, description, CTA, hook) + grounding check
    reframe.py          face / speaker / screen tracking, smooth camera path (OpenCV YuNet, PySceneDetect)
    captions.py         ASS caption styles, SRT
    render.py           ffmpeg decode → OpenCV crop/zoom/layout → ffmpeg encode with burned captions (speed, fillers)
    versions.py         alternative versions (faster pacing, alternative hook, alternative caption style)
    export.py           ZIP + metadata
  publish/              official-API publishing: OAuth, uploads, background publisher
    youtube.py          YouTube Data API v3 (OAuth + PKCE, resumable upload, status)
    tiktok.py           TikTok Content Posting API (Login Kit desktop OAuth, Direct Post, inbox drafts)
    routes.py, jobs.py  publish endpoints (local-only, explicit confirmation) and the upload worker
    stats.py            real performance snapshots from the platform APIs (never estimated)
  learning.py           performance dataset (scores at publish time + real results) and ranking check
  gpu.py, locks.py      cross-process GPU manager (one heavy GPU job at a time, VRAM check) and file locks
  autopilot/            persistent workers: queue.py (durable jobs), host.py (worker threads/process), scout.py,
                        providers.py, trends.py, rights.py, quota.py, hunter.py, live.py, packaging.py,
                        scheduler.py, publisher.py, learner.py, routes.py (/api/autopilot)
  secure.py             token/secret storage (Windows DPAPI)
  assets/               bundled fonts (OFL) and the YuNet face model (MIT)
docs/                   AUTOPILOT.md (Autopilot guide) and legal/ (the website: product page, Privacy Policy, Terms)
frontend/               React + Vite + TypeScript UI (prebuilt into frontend/dist)
tests/                  unit + end-to-end tests
data/                   created at runtime: clipfoundry.db, projects/<id>/..., models/<model>/ (verified)
```

Per project on disk: `data/projects/<id>/source.*`, `audio.wav`, `transcript.json`, `loudness.json`,
`candidates.json`, `clips/<clip>/clip.mp4`, `thumb.jpg`, `captions.ass`, `captions.srt`, `framing.json`, and
`clips/<clip>/versions/<version>/` for alternative versions.

## Usage

* **Add video** (on Home or in the Library) → drop a video or **Choose a video** (or open *Import from a link
  instead*) → optionally open *More options* to choose 3 / 5 / 10 clips, length, caption style, framing →
  **Make clips**.
* Watch the progress on the video's page (Prepare → Transcribe → Find moments → Score & hooks → Render 9:16). The
  first run downloads the Whisper model.
* The source video page shows a card per clip with thumbnail, title, duration, Viral Potential (an estimate), category,
  and **Edit clip / Export / Prepare post** buttons; click the thumbnail to preview it. Select clips and **Download
  selected (ZIP)** or **Download all (ZIP)**.
* **Prepare post** (on a clip card, in the preview or the editor) opens one page with the video preview, editable
  title, description/caption and hashtags (pick any generated option or write your own), who can see it per platform,
  and the buttons **Publish to YouTube now…**, **Post to TikTok now…** (or **Send to TikTok inbox…**) and **Export**.
  Each publish button shows a summary to confirm first; progress and the result (with a link to the video) appear
  below under *Uploads you started here*. Connect the accounts once in Settings → Accounts (or right on this page).
* **Make clips again…** (in the source video page's More menu) reuses the transcript to try different clip counts or
  lengths.
* Headless / scripting: `python -m clipfoundry process my_video.mp4 --count 5 [--transcript subs.srt]`.
* GPU check: `python -m clipfoundry gpu-check [video]` (or `gpu-check.bat`) runs a real transcription and reports the
  device, compute type, speed and GPU utilization.

## AI scoring providers (Settings → Advanced → Rendering, AI scoring and system → AI scoring)

| Provider | Cost | Notes |
| --- | --- | --- |
| Local heuristic (default) | free, offline | No model needed. |
| Ollama | free, local | `ollama pull llama3.1:8b` (or `qwen2.5:7b`), then select Ollama. |
| LM Studio / OpenAI-compatible | free, local | Any local server exposing `/v1/chat/completions`. |
| Claude API | paid per use | Optional. Paste an API key; only the top candidates are sent (cap: *Max candidates*, same section). |

If a provider is unreachable, ClipFoundry falls back to the heuristic automatically and shows a notice.

## Development

```bash
python -m venv .venv && .venv/bin/pip install -r requirements-dev.txt   # Windows: .venv\Scripts\pip
.venv/bin/python -m clipfoundry            # API + built UI on :8765
cd frontend && npm install && npm run dev  # UI dev server on :5173 (proxies /api)
npm run build                              # rebuild frontend/dist (committed so users don't need Node)
.venv/bin/python -m pytest                 # unit + integration tests (integration needs ffmpeg; e2e needs espeak-ng)
.venv/bin/python -m pytest -m "not slow"   # skip the slow end-to-end render tests
.venv/bin/python -m clipfoundry workers    # run the Autopilot workers on their own (normally started by the app)
```

`tests/make_test_video.py` builds a synthetic talking-head video (espeak-ng speech + a moving face with scene cuts)
for exercising the whole pipeline.

## Responsible use

Only process videos you own or have permission to use. Finding a video (trending, public or downloadable) does not
make it reusable. Automatically discovered sources need reuse rights before clipping. Links you paste into
Autopilot may be clipped locally when the file can be obtained through supported access; this supplies no reuse or
publishing permission. Explicitly blocked videos are never processed. The optional URL import uses yt-dlp for
publicly accessible media only: ClipFoundry does not bypass DRM, paywalls, logins or other access controls, and it never
passes cookies or credentials. For YouTube-hosted videos it is off in Autopilot unless you enable it for sources you
have permission to download.

## Website and legal pages

The product page, **Privacy Policy** and **Terms of Service** are in [`docs/legal/`](docs/legal/) (`index.html`,
`privacy.html`, `terms.html`, `site.css`). They were written from what the code does, and the app serves them at
`/legal/`, `/legal/privacy` and `/legal/terms`. No lawyer has reviewed them. For the Google OAuth consent screen and the
TikTok developer app they must be public; see
[docs/AUTOPILOT.md](docs/AUTOPILOT.md#legal-pages-terms-of-service-and-privacy-policy). When the code changes what is
stored or sent, update these pages in the same change.

## Retro robot studio

The working app uses original pixel robots and a local heading font, with readable controls and original video
previews. Autopilot's four stations follow real activity; selecting one shows its task and reported progress.
Settings → Defaults → Appearance saves Reduce motion in this browser and also respects the operating system.
See [the design and actual screenshots](design/retro-studio/SPEC.md) and [Windows update steps](INSTALL.md#updating).

## Third-party assets

* Poppins and Anton fonts: SIL Open Font License 1.1 (`clipfoundry/assets/fonts/OFL-*.txt`).
* YuNet face detector (OpenCV Zoo): MIT (`clipfoundry/assets/models/README.txt`).
* Test fixture face photo: public-domain NASA image.
