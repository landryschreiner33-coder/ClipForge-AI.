# ClipFoundry Autopilot

Autopilot turns ClipFoundry into a persistent, local-first content opportunity engine: it discovers what is gaining
attention, checks whether each source may be used, finds the strongest moments, packages them for YouTube Shorts and
TikTok, schedules them, publishes the posts you approved through the official APIs, and learns from the real results.

Everything runs on your computer. The platform APIs are used only for discovery signals, publishing and reading your
own results. The daily numbers (3 sources, up to 5 clips per source, 15 clips a day) are **targets, never quotas**:
quality, rights, availability and platform limits always come first, so a day can end with fewer posts.

Contents: [platform rules](#what-the-platforms-allow-and-what-that-means-for-autopilot) ·
[setup](#setting-it-up) · [how it works](#how-it-works) · [scores](#scores) · [Publish Center](#publish-center) ·
[controls and emergency stop](#controls-and-emergency-stop) · [what is not possible](#blocked-or-limited-capabilities) ·
[legal pages](#legal-pages-terms-of-service-and-privacy-policy) · [troubleshooting](#troubleshooting)

## What the platforms allow (and what that means for Autopilot)

These rules come from the platforms, and they win over the 15-clips-a-day target and over full automation.

| Rule | Source | Effect in ClipFoundry |
| --- | --- | --- |
| Users must have final control over data published to YouTube; the app may only *suggest* titles, descriptions and privacy. | YouTube API Services Developer Policies | Every YouTube post waits for your approval in the Publish Center. After you approve it, it is published at its scheduled time without further clicks. |
| TikTok apps may only upload after the user expressly consents, must show a preview, must let the user edit the text, must read the creator's options before posting and must not pre-select a privacy level. | TikTok Content Sharing Guidelines | Every TikTok post waits for your approval, made on a screen that shows the preview, the creator nickname and TikTok's options (privacy is never pre-selected). |
| API data must not be used to create derived data or metrics without Google's approval. | YouTube Developer Policies III.E.4; Additional policies for derived metrics | Momentum scores (view velocity, engagement rates) are computed from YouTube data only when you confirm that your Google Cloud project was granted this. Otherwise YouTube results are ranked by YouTube's own order and shown as YouTube reported them. |
| Stored YouTube API data must be refreshed or deleted within 30 days. Approved projects may keep statistics of the user's own videos (Authorized Data) longer. | YouTube Developer Policies; Additional policies for derived metrics and data storage | A maintenance job deletes YouTube data older than 30 days. With the approval setting on and the channel connected, only the statistics of your own videos are kept longer. |
| Content may only be downloaded from YouTube through means YouTube authorizes, or with permission from YouTube and the rights holders. | YouTube Terms of Service | Autopilot ingests your own files (watch folders), stream URLs and direct media links you are allowed to use. Downloading platform-hosted videos with the URL importer is off by default and never happens for a source without a passing rights status. |
| `chart=mostPopular` now covers the Trending Music, Movies and Gaming charts only. | YouTube Data API revision history (July 2025) | Broad discovery uses topic searches (their own 100-call daily quota bucket since June 2026) plus channels you follow. |
| Google Trends API is an application-gated alpha; TikTok has no trend API for general developers. | Google Search Central; TikTok for Developers | Not used. Shown as unavailable in the UI. ClipFoundry never scrapes either. |
| Unaudited API projects/apps can only publish privately. | YouTube API audit; TikTok Content Posting API | Shown before scheduling and after each upload. Autopilot never claims a post is public when the platform made it private. |

## Setting it up

1. **Connect the accounts** you want to publish to (Settings → Publishing; see [INSTALL.md](../INSTALL.md)). Autopilot
   works without them, but then it only prepares posts.
2. **Tell Autopilot where sources come from** (Autopilot → Sources & rights → *Where sources come from*):
   * *Watch folder*: a folder with your own recordings. New videos become sources; a file that is still growing is
     treated as a live recording.
   * *YouTube channel*: a channel you follow (its channel ID, `UC...`). New uploads become candidate sources.
   * *Stream URL*: an HLS/RTMP/SRT stream you are allowed to use (for live clipping).
   * *Signal feed*: a JSON/CSV file or URL of trend signals you are authorized to use.
   Each feed can carry a rights status for what it finds (for example, a watch folder of your recordings as *Owned*).
3. **Record your rights** (Autopilot → Sources & rights → *Rights rules*): channels whose clipping program you joined
   (*Allowlisted*), licensed feeds (*Licensed*), folders of your own recordings (*Owned*), or anything you must never use
   (*Blocked*). Every rule needs a basis (what gives you the right). Anything without a rule waits for your decision.
4. **Optional: discovery with the YouTube Data API.** Paste an API key of your Google Cloud project in Settings →
   Autopilot → Discovery (or just connect YouTube). Set the region, language and topics.
5. **Check the schedule** in Settings → Autopilot: time zone (default America/Chicago), active hours, the minimum gap
   between posts, per-platform daily limits and the daily target.
6. **Turn Autopilot on** (the switch on the Autopilot page or in Settings). Approve posts in the Publish Center as they
   arrive; approved posts are published at their time.

The worker runs in its own background process by default (Settings → Autopilot → Worker process), so a crash in a
worker cannot take the app down. It is started and stopped with the app: when the app closes, the worker notices the
missing heartbeat and exits within a minute. It can also be started on its own with `python -m clipfoundry workers`.

## How it works

```
Trend Scout ─┐                                   ┌─ Live Monitor (live sources, rolling window, post-live pass)
Feeds ───────┼─> Source Scout ─> Rights Gate ─> Clip Hunter ─> Deep Clip Analyzer ─> Diversity Selection
             │                                                                          │
             │                                               Packaging AI <─────────────┘
             │                                                    │
             │                                            Final Quality Gate (file + text)
             │                                                    │
             │                   Smart Scheduler (America/Chicago, limits, replacement)
             │                                                    │
             │                         Publish Center: YOUR APPROVAL (required by both platforms)
             │                                                    │
             └────────── Learning Worker <── real results <── Publisher (official APIs, resumable, idempotent)
```

| Worker | Job kinds | What it does |
| --- | --- | --- |
| Trend Scout | `trend_scan` | Reads YouTube search/chart results (within its quota share), feeds and watch folders. Stores every signal with its history and a Trend Score. Metrics carry their provenance: *observed*, *estimated* or *unavailable*. |
| Source Scout | `source_scout`, `feed_scan` | Turns signals into sources, scores them (Source Score, expected strong clips) and picks up to 3 per day, skipping duplicates, weak and unavailable ones. |
| Rights and Content Safety Gate | `rights_check` | Applies your rules. Only *Owned*, *Licensed*, *Allowlisted* (and *Creative Commons* if you allow it) sources continue automatically; everything else becomes an action item. The gate runs again before scheduling and before publishing, so a later *Blocked* rule stops a post. |
| Live Monitor | `live_watch`, `live_capture`, `post_live` | Records authorized live sources in segments, transcribes each segment (one GPU job at a time), clips strong moments from a rolling 15-minute window, and after the stream ends runs a full pass that can replace weaker live clips that were not published yet. |
| Clip Hunter | `hunt_source` | Brings the source in (hard link or copy of a local file, a direct media URL, or the URL importer only when allowed), transcribes on the GPU and builds a large candidate pool. |
| Deep Clip Analyzer | `analyze_source` | Fast filter → semantic analysis → deep evaluation (Viral Potential, audio and visual features) → boundary optimization → diversity selection (MinHash text and perceptual video fingerprints against everything already made). Then the **Engagement Strategist** writes a Clip Blueprint for each chosen clip (see below) and the clip is rendered from it. Renders up to 5 clips that pass the quality bar. |
| Packaging AI | `package_clip` | Writes title/description/caption/hashtag options in six styles from the words heard in the rendered clip (its final transcript), optionally with an AI provider, validates grounding, repetition and duplicates, and scores them. Each option records which render it was written for. |
| Final Quality Gate | `quality_check` | Checks the exact file that would be published: SHA-256 against the render record, streams and codecs, 1080×1920, duration, a full decode (a truncated file still reports its full length), black, frozen and silent stretches judged in context, caption timing, cuts inside words, and the hook/context/payoff estimates. Re-checks each platform's selected text against what is heard in that file. The report is bound to the file's hash, final transcript and time map. Failures keep the clip out of the schedule; warnings are shown with the post. |
| Smart Scheduler | `schedule_tick` | Places packaged clips whose current file and text passed the Final Quality Gate on each platform's time grid within your active hours and limits, computes the Final Opportunity Score, replaces weaker unpublished posts with clearly stronger new ones, and hands due approved posts to the publisher. |
| YouTube Quota Manager | (inside every YouTube call) | Counts units and calls per bucket, keeps discovery within its share, and reserves the rest for uploads, statistics and account checks. Resets at midnight Pacific. |
| Publisher | `publish` | Hashes the file again and needs a passing Final Quality Gate report for exactly those bytes, then uploads approved posts with the existing YouTube and TikTok code. An interrupted upload resumes its stored session (YouTube) or checks its publish ID (TikTok) instead of posting twice. |
| Learning Worker | `learn` | Reads the real results of your posts (snapshot near 48 h), and once there are at least 10, adjusts posting-time lifts, style bonuses, score weights and the retention estimate, using only groups with enough data. |
| Maintenance | `maintenance`, `selftest` | Recovers stale jobs, applies the YouTube 30-day data rule, cleans caches. |

**Durable jobs.** Every job is a row in `worker_jobs` (SQLite) with a state (`queued`, `running`, `waiting`,
`completed`, `failed`, `canceled`, `retrying`), an idempotency key, a lease that the worker renews, a timeout, attempt
counts and a structured log (`job_logs`). Claims are atomic (`BEGIN IMMEDIATE`). If the app, the worker or the PC stops,
leases expire and the jobs are picked up again after restart; a job that was halfway never runs twice for the same key.
Jobs you start by hand (for example *Clip now*) run even while Autopilot is off.

**Clip Blueprint.** Before a clip is rendered, the Engagement Strategist stores a typed, versioned plan for it
(`pipeline/blueprint.py`, table `clip_blueprints`, `blueprint.json` next to the render): the source intervals in
seconds of the original, speed, framing, captions, the words to stress, audio adjustments, the hook and the payoff
line, and why the moment was chosen. A plan the renderer could not follow faithfully is rejected before rendering
(intervals outside the source, reversed, overlapping or out of order, a cut inside a word, unsupported speed or
options, emphasis outside the kept intervals, on-screen text that is not said in the clip). Instructions the renderer
does not support are listed as unsupported and left out, never claimed as applied. The renderer follows the plan
exactly and records the plan's hash with the file; your edits and alternative versions are applied on top as a new,
stored plan. Manual projects have no plan and render as before.

**GPU.** One heavy GPU operation at a time, across processes (a lock file), with a wait for free VRAM
(Settings → Autopilot → *Free GPU memory needed*). Transcription uses exactly the existing faster-whisper/CTranslate2
CUDA path; Autopilot only waits for its turn. **Strict GPU:** when an NVIDIA GPU is expected and CUDA fails (or the
GPU is present but unusable), Autopilot does not fall back to the CPU: the job pauses for 30 minutes without using
an attempt and an action item says what failed and how to fix it. Live capture keeps recording meanwhile; the
post-live pass transcribes the whole recording again on the GPU. Settings → Autopilot → *Allow CPU transcription*
lets it continue on the CPU instead (slower). Manual projects keep their visible CPU fallback. Local AI models (Ollama/LM Studio) share the same lock.

**Downloads and addresses.** Autopilot fetches media and signals from URLs that come from data (a feed's rows, a
discovered source, a redirect), so every such URL is checked first (`netguard.py`): only http/https for downloads and
network stream protocols for live capture (never `file:`, `concat:`, `pipe:` or `data:` in ffmpeg), and the host
must resolve to public addresses. Addresses you typed yourself (a source added by hand, a stream you configured, a
signal feed's own URL) may point into your own network. Every redirect is checked, a download connects to exactly the
address that was checked, and it stops at Settings → Autopilot → *Largest source* (8 GB and 240 minutes by default;
longer videos are not processed). A download that would leave less than 2 GB free on the data drive waits with an
action item.

## Scores

All scores are 0-100 estimates computed by ClipFoundry to rank opportunities. They are not platform metrics and not
predictions of views.

| Score | Meaning |
| --- | --- |
| Trend Score | How much attention a signal is gaining: velocity, acceleration, engagement, recency, live status, size and recurrence. For YouTube data without Google's derived-metrics approval it is YouTube's own order only. |
| Source Score | How promising a source is: trend strength, expected clip potential (learned yield per minute), creator history, freshness, live status and topic results. |
| Clip Score | Viral Potential of the clip plus bounded adjustments from audio/visual/semantic analysis and trend relevance. |
| Diversity Score | How different the clip is from the other selected clips and from everything you already made. |
| Packaging Score | Quality of the chosen title/caption: curiosity, emotion, clarity, natural wording, platform fit, searchability, uniqueness, click appeal, plus a learned style bonus. |
| Expected Retention | Retention Potential, calibrated with your real average % viewed once enough results exist. |
| Publish Opportunity | How good the planned time is (learned time-of-day lift, gaps, freshness of the trend). |
| Final Opportunity | Weighted sum of the above (clip 35%, packaging 15%, trend 15%, source 10%, diversity 10%, retention 10%, publish opportunity 5%); the weights adapt within ±50% when your results show a different pattern. |

Each scheduled post shows *Why this slot and score* with the explanation and an audit trail.

## Publish Center

Every scheduled post, in order, with its video, text, platform, rights status, time and scores.

* **Approve**: required for every post by both platforms. For YouTube you confirm the title, description, tags,
  visibility and the made-for-kids answer. For TikTok the dialog reads your creator info first, shows your nickname,
  lets you choose the privacy (never pre-selected), interactions (off by default), the commercial content disclosure,
  and shows TikTok's Music Usage Confirmation. An approval is bound to the exact video and text: editing either needs a
  new approval.
* **Edit**, **Reschedule**, **Cancel**, **Retry**, **Publish now**, **Open source**, **Open post**, and **Link TikTok
  post** for inbox drafts finished in the TikTok app.
* YouTube posts are uploaded early (default 30 minutes) as Private with `publishAt`, so YouTube itself publishes them
  at the planned time.
* **Final check**: every post shows the Final Quality Gate's verdict on its exact file and text (*passed*, *N warnings*, *failed*, *text needs a fix* or *pending*), with every check listed and marked as measured or as an estimate. A post whose file failed cannot be approved or uploaded; fix the clip and render it again.
* Views: *Upcoming*, *Needs attention*, *Published*, *History*.

## Controls and emergency stop

* **AUTOPILOT ON/OFF**: off means queued work waits; jobs you start by hand still run.
* **STOP ALL JOBS** (Autopilot page): cancels queued work, asks running jobs to stop at their next safe point
  (including manual renders and uploads) and pauses everything until you press **Resume jobs**. Nothing is published
  while stopped. An upload that is already transferring stops between chunks; check the platform if one was in flight.
* Per job: **Cancel**, **Retry** and the job **Log** (Autopilot → Jobs).
* Per source: **Rights**, **Clip now**, **Skip**, **Add file**.
* Settings → Autopilot has every target, limit and switch described above.

## Blocked or limited capabilities

These are not simulated; the UI shows them as unavailable or explains the restriction.

| Capability | Status |
| --- | --- |
| Google Trends data | Not available: the official Google Trends API is an application-gated alpha. Not scraped. |
| TikTok trends and TikTok discovery | Not available: TikTok offers no trend or search API for general developers. TikTok is never scraped. |
| YouTube momentum metrics (velocity, engagement rates, derived totals, learning from YouTube results) | Only with Google's approval under the additional policies for derived metrics; enable the setting only if your project was approved. |
| Broad YouTube trending | `chart=mostPopular` covers Music, Movies and Gaming only; general discovery uses topic searches within the 100-call search bucket. |
| Downloading YouTube or other platform videos | Off by default. YouTube's Terms allow downloads only through YouTube's own features or with permission. Use your original files, YouTube Studio downloads of your own videos, or turn it on only with permission. |
| Fully unattended publishing | Not allowed: YouTube and TikTok require the user's approval of each post. Once approved, publishing at the planned time is automatic. |
| Public posts from unaudited apps | YouTube locks unaudited projects to Private; TikTok Direct Post from unaudited apps is limited to private accounts and *Only me*. Use the audit, or TikTok's inbox draft flow. |
| 15 posts/day on both platforms | Subject to the YouTube quota (by default 100 upload calls a day, shared with anything else your Google Cloud project uploads), TikTok's per-creator posting limits and your own limits. |
| TikTok retention metrics | Not available from TikTok's API. |

## Legal pages (Terms of Service and Privacy Policy)

Templates live in [`docs/legal/`](legal/): `terms.html`, `privacy.html` and an `index.html`. **They require review by
a qualified lawyer** and every placeholder must be replaced: `[OWNER NAME]`, `[LEGAL BUSINESS NAME]`,
`[CONTACT EMAIL]`, `[BUSINESS ADDRESS IF REQUIRED]`, `[GOVERNING LAW JURISDICTION]`, `[LICENSE TERMS]` and `[DATE]`.
The privacy policy covers what the YouTube API Services and TikTok require (the data accessed, how it is used and
stored, the 30-day rule, links to the YouTube Terms and Google Privacy Policy, and how to revoke access).

Where they are served:

* **In the app:** <http://127.0.0.1:8765/legal/terms> and <http://127.0.0.1:8765/legal/privacy> (linked in the sidebar).
  These are only reachable on your PC, so they are not enough for the developer consoles.
* **Public URLs (needed for the Google OAuth consent screen and the TikTok developer app):** publish the `docs/legal`
  folder, for example with GitHub Pages: repository Settings → Pages → *Deploy from a branch* → your branch and the
  `/docs` folder. The pages are then at `https://<user>.github.io/<repo>/legal/terms.html` and
  `.../legal/privacy.html`. Any static host works (Netlify, Cloudflare Pages, your own domain). Enter those URLs in
  Google Cloud (OAuth consent screen → App information) and TikTok for Developers (app details), and keep them online.

## How the existing code is reused

| Requirement | Built on |
| --- | --- |
| Persistent state | `clipfoundry/db.py` (SQLite, WAL, migrations with `CREATE TABLE IF NOT EXISTS` + `ADDED_COLUMNS`) |
| Workers | New durable queue `autopilot/queue.py` on SQLite; the existing single render worker (`jobs.py`) keeps handling manual projects and now resumes after a restart |
| GPU | `pipeline/cuda.py` detection + a new `gpu.py` manager that serializes heavy GPU work across processes; `pipeline/transcribe.py` is not modified |
| Clip Hunter / Deep Analyzer | `pipeline/candidates.py` (windows), `pipeline/virality.py` (11 factors, unchanged weights), `pipeline/scoring.py` (staged evaluation), new `pipeline/deep.py` and `pipeline/diversity.py` |
| Packaging | `pipeline/postpack.py` (grounding checks) extended by `autopilot/packaging.py` |
| Publisher | `publish/youtube.py`, `publish/tiktok.py`, `publish/jobs.py` runners, reused by the autopilot publisher |
| Learning | `learning.py` and `publish/stats.py` (real metrics only) |

## Troubleshooting

| Problem | What to do |
| --- | --- |
| Workers show *not running* | Check the action items on the Autopilot page. If the worker process cannot start, switch Settings → Autopilot → Worker process to *Inside the app*. |
| Nothing gets clipped | Sources need a passing rights status (Autopilot → Sources & rights) and a video file or allowed URL. *Needs file* means: add the file (*Add file*) or a watch folder. |
| Jobs wait for the GPU | Another heavy GPU job (or another program) is using it; see the GPU card. Lower *Free GPU memory needed* only if you know the model fits. |
| "fell back to CPU" on the GPU card | Run `gpu-check.bat` and follow the fix it prints (see INSTALL.md). |
| "Autopilot transcription is paused: the GPU could not be used" | Run `gpu-check.bat` and follow the fix it prints. Until it is fixed, you can allow CPU transcription in Settings → Autopilot. |
| Discovery stopped: quota | The YouTube quota share for discovery is used up; it resumes after midnight Pacific. Publishing keeps its reserve. |
| Posts wait in *Needs approval* | That is required by the platforms; approve them in the Publish Center. |
| YouTube posts end up Private | Your Google Cloud project has not passed the YouTube API audit. |
| TikTok: privacy options disabled | Your TikTok app is not audited; only *Only me* is possible, or use *Send to TikTok inbox*. |
| Something is running that should not | **STOP ALL JOBS**, then look at Autopilot → Jobs and the job logs. |
| After an update | Close the old console window, start again, reload the page (Ctrl+F5). |

## Phases

1. Plan (this document).
2. Persistent tables.
3. Worker framework, restart recovery, GPU resource manager.
4. Trend Scout, Source Scout, trend scoring, rights gate, YouTube quota manager.
5. Clip Hunter, staged analysis, boundary optimization, diversity selection.
6. Packaging and grounding validation.
7. Scheduler, publication queue, dynamic replacement.
8. Live Monitor.
9. Publisher integration and Autopilot controls.
10. Learning worker.
11. Autopilot dashboard, Publish Center, legal pages, documentation.
12. End-to-end validation.
