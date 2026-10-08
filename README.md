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

## Getting started (beginner steps)

1. **Start it.** In the ClipFoundry folder, double-click **`start.bat`**. The browser opens ClipFoundry at
   <http://127.0.0.1:8765>. Keep the black `start.bat` window open; closing it closes ClipFoundry.
2. **Check the graphics card once.** Double-click **`gpu-check.bat`** in the same folder. It should say the GPU (CUDA)
   was used. If it does not, see [INSTALL.md](INSTALL.md#nvidia-gpu-acceleration).
3. **Set it up.** The app opens on the **Office**. Press **Set up ClipFoundry**: put your videos in the videos folder,
   choose *Let Autopilot do it*, connect YouTube (and TikTok if you like), then press **Start Autopilot**.
4. **Say who watches.** Open **Settings → Integrations → Who watches**. For each platform choose *My invited viewers*
   (YouTube) or *My approved followers* (TikTok), tick *I understand…* and press **Confirm who watches**. Nothing is
   ever posted publicly:
   * **YouTube** uploads are Private. After an upload, open YouTube Studio, choose the video and share it privately
     with the people you pick (Visibility → Share privately). Then open the post in **Queue** and press
     **I shared it**.
   * **TikTok** posts are for your followers on a private account (TikTok app → Settings and privacy → Privacy →
     Private account; you approve each follower). Only a TikTok developer app that TikTok has audited may post to
     followers, and TikTok's rules turn down apps for personal use, so expect to post TikTok clips yourself:
     ClipFoundry prepares each one in **Queue → Problems → Ready for you to post on TikTok** (download the video, copy
     the caption, post it for **Followers** in the TikTok app, then paste its link).
5. **Watch the office.** Each robot shows real work: it stands at its desk while its job runs and rests in the Lounge
   when it has none. Click a robot or a room for details. The bar at the bottom has **Start**, **Pause**, **Resume**,
   **Stop all** and **Pause publishing** (clips are still made and checked, nothing is uploaded).
6. **Check posts in Queue.** *Needs review* holds posts waiting for your OK (TikTok always needs it). Each post says
   who it is for and what really happened.
7. **Tell it what your viewers thought.** **Clips → Test feedback**: enter what a tester said about a clip, or copy
   the numbers from YouTube Studio or TikTok. The Brain changes its clip length only after enough results (at least
   30 clips from 5 videos), by at most 10% at a time, and you can roll a change back (click the Brain Room on the
   Office).

**What keeps running.** Closing the browser does not stop anything: open <http://127.0.0.1:8765> again to look.
Closing the `start.bat` window stops ClipFoundry and its background work; it continues where it was at the next
start. While Autopilot is on, ClipFoundry asks Windows not to sleep. If the PC sleeps or is shut down anyway, nothing
runs meanwhile; at the next start interrupted steps run again and missed posts get a new time.

**Back up and export.** To back up, close ClipFoundry and copy the `data` folder. To keep a clip outside the app, use
**Export** on the clip, or **Download all (ZIP)** on the video's page in Clips.

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
| YouTube Shorts | **Connect YouTube** with OAuth (your own Google Cloud "Desktop app" client, PKCE, loopback redirect). The connected channel's name is shown. Resumable uploads through the official YouTube Data API v3 with title, description, tags and the made-for-kids answer, always as **Private** and never with a publishing time, so YouTube never makes them public. You share each video privately in YouTube Studio with the viewers you pick (the API cannot), then mark it shared. Passwords are never stored; tokens are encrypted with Windows DPAPI. |
| TikTok | **Connect TikTok** with TikTok's official Login Kit (desktop OAuth with PKCE). Posts through the official Content Posting API: **Direct Post** with caption and hashtags to your **followers or friends** (never "Everyone"; never pre-selected), comment/duet/stitch permissions and the commercial content disclosure, following TikTok's sharing guidelines; chunked upload with progress and status polling. Without TikTok's audit, Direct Post is limited to private accounts and "Only me"; the fallbacks are the official **Send to TikTok inbox** draft flow (if TikTok approved your app for it) and the ready-to-post package you post yourself (the usual case for a personal tool). No scraping, no unofficial automation. |
| Prepare post | One page per clip (**Prepare post**): video preview, editable title, description/caption and hashtags (with the generated options one click away), YouTube made-for-kids (the video is Private), TikTok followers or friends, interactions and disclosure, and explicit **Publish to YouTube now…**, **Post to TikTok now…** (or **Send to TikTok inbox…**) and **Export** buttons. Every publish needs a confirmation. Status, progress and links for each upload stay listed there (*Uploads you started here*). |
| Performance | **Real numbers only.** For your uploads, ClipFoundry reads views, likes and comments (YouTube Data API), shares, watch time, average view duration and % viewed (YouTube Analytics API, when enabled) and views, likes, comments and shares (TikTok `video.query` for public posts). Each refresh stores a timestamped snapshot; a metric the platform does not report stays empty ("—") with the reason, never estimated. TikTok posts finished in the app can be linked by URL. **Queue → Results** shows totals with their coverage and, once 10+ uploads have view counts, how well Viral Potential ordered them. The data (scores at publish time next to real results) can be downloaded as CSV (**Download data (CSV)** under Queue → Results) or JSON as the basis for tuning the ranking later. |
| Autopilot | Durable background workers (Trend Scout, Source Scout, Rights and Content Safety Gate, Live Monitor, Clip Hunter, Deep Clip Analyzer with diversity selection, Packaging AI, Final Quality Gate, Smart Scheduler, YouTube Quota Manager, Publisher, Learning Worker) on a SQLite job queue that survives restarts. One heavy GPU job at a time on the existing CUDA path. Visible Trend, Source, Clip, Diversity, Packaging, Expected Retention, Publish Opportunity and Final Opportunity scores. A simple **Overview** (**Start Autopilot** / **Pause Autopilot**, this PC and the GPU, **Needs you**, what it is working on, your videos folder, upcoming posts and how they go out), an **Activity** tab (top opportunities, and what it did with each video it found) and **Permissions & sources**, with a three-step first-time setup (add your videos, choose how to work, set up posting, then **Start Autopilot**); workers, GPU, quota, jobs and learning under **Advanced**; **Stop all jobs…** always at hand. Details: [docs/AUTOPILOT.md](docs/AUTOPILOT.md). |
| Queue | Every planned and published post in one place (formerly Posts), with the tabs **Needs review**, **Scheduled**, **Published** (canceled and replaced posts too, as History), **Problems** and **Results**. Each post opens as its own page: **Approve for YouTube** / **Approve for TikTok** (required by YouTube and TikTok), edit the text, **Change the time…**, **Cancel this post…**, **Try again…**, **Publish now…**, open the clip, the source video and the post, with the reasons behind each slot and score and an audit trail. |
| Rights | Every source has a status: Owned, Licensed, Creative Commons, Public domain, Allowlisted, Not covered or Blocked. Discovery is not authorization: only sources you have rights to are clipped automatically. |
| Places | **Office** (the robots and the controls), **Missions** (Autopilot), **Clips** (your source videos and their clips, and Test feedback), **Queue** (posts) and **Settings**, plus **Add video**. Everything (source video, transcript, candidates, clips, metadata) is stored locally. |
| Robot office | 25 pixel robots (a Director, 8 managers, 16 workers) and the Brain Core, each standing for one part of the real job system. They move only when real work starts, finishes or fails, and the office says when it cannot update. A list view and Reduce animations show the same without movement. See [docs/OFFICE.md](docs/OFFICE.md). |
| Who watches | One audience policy for every upload: YouTube Private shared with invited viewers, TikTok approved followers (or friends), *Only me* as staging, or keep clips on this PC. Public, unlisted and Everyone are blocked everywhere. Settings → Integrations. |
| Brain | Results with where they came from (platform, your import, tester feedback). It changes a strategy only with enough evidence from your selected viewers, at most 10% at a time, with rollback. |

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
                        scheduler.py, publisher.py, learner.py, brain.py (results and guarded strategy),
                        routes.py (/api/autopilot), brain_routes.py (/api/brain)
  office/               the robot office: roles.py (cast), feed.py (events, reports, decisions), view.py
                        (snapshot), health.py, capabilities.py (integration matrix), routes.py (/api/office)
  publish/audience.py   who may watch an upload (one policy for every path)
  pipeline/nvidia.py    optional NVIDIA-hosted text AI (off by default)
  secure.py             token/secret storage (Windows DPAPI)
  assets/               bundled fonts (OFL) and the YuNet face model (MIT)
docs/                   AUTOPILOT.md (Autopilot guide), OFFICE.md (robot office, audience, capabilities, Brain) and
                        legal/ (the website: product page, Privacy Policy, Terms)
frontend/               React + Vite + TypeScript UI (prebuilt into frontend/dist)
tests/                  unit + end-to-end tests
data/                   created at runtime: clipfoundry.db, projects/<id>/..., models/<model>/ (verified)
```

Per project on disk: `data/projects/<id>/source.*`, `audio.wav`, `transcript.json`, `loudness.json`,
`candidates.json`, `clips/<clip>/clip.mp4`, `thumb.jpg`, `captions.ass`, `captions.srt`, `framing.json`, and
`clips/<clip>/versions/<version>/` for alternative versions.

## Usage

* **Add video** (in Clips) → drop a video or **Choose a video** (or open *Import from a link
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
| NVIDIA AI | see below | Optional, off by default. Set it up in Settings → Integrations first. |

If a provider is unreachable, ClipFoundry falls back to the heuristic automatically and shows a notice.

## Optional NVIDIA AI

ClipFoundry works fully without it. When on, NVIDIA's hosted models can re-score and title the strongest clip
candidates from short transcript excerpts (never video, audio or account details). NVIDIA's terms, free access and
model list change; check them on NVIDIA's pages before you use it (this guide was not checked against them live).

1. Open <https://build.nvidia.com>, sign in, and open the page of the model you want (the default is
   `nvidia/nemotron-3.5-lightning-30b-a3b`, a candidate, not a promise it stays listed). Get an API key there through
   NVIDIA's own steps. Read NVIDIA's terms, including what they keep and whether you are eligible.
2. In ClipFoundry open **Settings → Integrations → NVIDIA AI (optional)**. Turn on **Use NVIDIA AI**, paste the key
   into **NVIDIA API key** (it is stored sealed on this PC; never paste it into a chat or a message), keep or change
   **Model**, leave **Mode** on *Development*, and press **Save settings**.
3. Read *What is sent*, tick the agreement and press **Save my agreement**.
4. In **Settings → Advanced → Rendering, AI scoring and system → AI scoring** choose *NVIDIA AI* and press **Save
   settings**.
5. Back in Integrations, press **Check the setup** (reads NVIDIA's model list), then **Run a small AI test** (one
   short made-up text, counted against today's limits).

Limits: a daily number of requests and tokens (Settings → Integrations, *Limits*). In *Development* mode it is only
used for videos you process yourself; Autopilot keeps using local analysis, because NVIDIA describes the catalog as
development and prototyping access. *Production* needs your own endpoint whose terms allow your use, its price and a
daily spending cap; ClipFoundry never assumes an unknown price is free. To stop: **Disconnect** removes the key and
your agreement and turns it off. Any failed or refused request falls back to local analysis for that step.

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

Browser tests: `cd e2e && npm install && npm test` (read-only, against a running app) and `npm run test:sandbox`
(a throwaway app with fake YouTube and TikTok). For AI assistants: start with [AGENTS.md](AGENTS.md), then
[AI_HANDOFF.md](AI_HANDOFF.md) and [AI_CHANGELOG.md](AI_CHANGELOG.md).

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

## Robot office

The app opens on the **Office**: an office of original pixel robots (layout and characters after the owner's
reference images) whose movements follow real jobs. **Team** lists all 25 robots and the Brain Core; the developer
gallery at `#/dev/robots` shows each one in four directions and every pose. How it works, the event feed and the
capability matrix: [docs/OFFICE.md](docs/OFFICE.md). The art and how to extend it:
[design/robots/README.md](design/robots/README.md). Screenshots (first run, working, waiting, after a restart,
paused, a controlled error state, Team): [design/robot-office/screenshots](design/robot-office/screenshots/README.md).

## Third-party assets

* Poppins and Anton fonts: SIL Open Font License 1.1 (`clipfoundry/assets/fonts/OFL-*.txt`).
* YuNet face detector (OpenCV Zoo): MIT (`clipfoundry/assets/models/README.txt`).
* Test fixture face photo: public-domain NASA image.
