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
| Users must have final control over data published to YouTube and know what the app does in their name. | YouTube API Services Developer Policies | By default every YouTube post waits for your approval in the Publish Center. With **automatic publishing** turned on (an explicit, stored permission: which channel, what content, who can see it, how many a day, when), clips that passed every check are approved by that permission, labeled *Approved automatically*, never as approved by you, and each stays cancellable until it goes out. |
| TikTok apps may only upload after the user expressly consents, must show a preview, must let the user edit the text, must read the creator's options before posting and must not pre-select a privacy level. | TikTok Content Sharing Guidelines | Every TikTok post waits for your approval, made on a screen that shows the preview, the creator nickname and TikTok's options (privacy is never pre-selected). Automatic publishing is not offered for TikTok, and the app says why. Once approved, a post goes out at its time by itself. |
| API data must not be used to create derived data or metrics without Google's approval. | YouTube Developer Policies III.E.4; Additional policies for derived metrics | Momentum scores (view velocity, engagement rates) are computed from YouTube data only when you confirm that your Google Cloud project was granted this. Otherwise YouTube results are ranked by YouTube's own order and shown as YouTube reported them. |
| Stored YouTube API data must be refreshed or deleted within 30 days. Approved projects may keep statistics of the user's own videos (Authorized Data) longer. | YouTube Developer Policies; Additional policies for derived metrics and data storage | A maintenance job deletes YouTube data older than 30 days. With the approval setting on and the channel connected, only the statistics of your own videos are kept longer. |
| Content may only be downloaded from YouTube through means YouTube authorizes, or with permission from YouTube and the rights holders. | YouTube Terms of Service | Getting the file is decided separately from the right to reuse it (`autopilot/access.py`). Autopilot uses your own files, a folder or file links a creator shares with you under an agreement, a free-license library's own downloads, and direct links you configured. A connected account or a public link is never treated as permission to download. Downloading platform-hosted videos with the URL importer is off by default. |
| `chart=mostPopular` now covers the Trending Music, Movies and Gaming charts only. | YouTube Data API revision history (July 2025) | Broad discovery uses topic searches (their own 100-call daily quota bucket since June 2026) plus channels you follow. |
| Google Trends API is an application-gated alpha; TikTok has no trend API for general developers. | Google Search Central; TikTok for Developers | Not used. Shown as unavailable in the UI. ClipFoundry never scrapes either. |
| Unaudited API projects/apps can only publish privately. | YouTube API audit; TikTok Content Posting API | Shown before scheduling and after each upload. Autopilot never claims a post is public when the platform made it private. |

## Setting it up

The first time you open Autopilot it shows four steps, and that is all a normal user needs:

1. **Connect YouTube.** Autopilot uses the connected account to find trending videos and to post your Shorts.
2. **Connect TikTok** (optional: one platform without the other works too).
3. **Choose topics.** A suggestion is filled in; pick or type others if you like.
4. **START AUTOPILOT.** It turns Autopilot on for the accounts you connected and starts looking right away.

To let YouTube posts go out without reviewing each one, turn on **automatic publishing** afterwards (*Enable
automatic publishing* on the Autopilot page or Settings → General). It shows exactly what you allow: the channel, what
gets posted (only clips that passed every check, from videos you own or that an agreement or license covers), who can
see the posts, made for kids or not, how many a day and between which hours, and you confirm it. Turning it off sends
every post it approved that has not started uploading back to *waiting for your approval*. Until Google audits your
YouTube API project, YouTube keeps the uploads private whatever you choose.

Both platforms only let apps like ClipFoundry post through *your own* free developer app, so the first CONNECT on a
computer asks for that app's two codes once (the steps are shown next to the fields; see also
[INSTALL.md](../INSTALL.md)). After that, CONNECT is just the platform's own sign-in page.

You do not add sources, feeds, folders, rules or workers. Behind the scenes Autopilot uses whatever is available (the
connected YouTube account for discovery; watch folders and feeds only if you added some; Google Trends and TikTok
trends are not available to apps and are skipped without bothering you) and these defaults: United States, English,
all trending categories plus broad topics, 3 videos a day, up to 5 clips each, 15 clips a day as a target, posting times
chosen for you (America/Chicago, 9:00 to 21:00, spread over the day), a new look for videos every 3 hours, dynamic
replacement, live monitoring, learning, automatic scheduling and automatic publishing of the posts that are approved. Settings → General has the three choices most people touch
(Autopilot on/off, daily target, automatic publishing); everything else is under Settings → Advanced.

**The main Autopilot page** shows only: START / PAUSE AUTOPILOT, Today (clips made against the target), what Autopilot
is doing right now, the next post, whether YouTube and TikTok are connected, **Needs you**, the top opportunities it
found, the upcoming posts and how they go out, an optional **Activity** log (what it did with each video it found and
why it skipped any), and a reminder that the PC must be on and awake to find and render clips (a YouTube post that was
already uploaded goes out at its time even if the PC is off; TikTok posts need the PC on at their time). Workers, sources, feeds, rights rules, quota, jobs, scores and learning are under **Advanced** (the link at the
bottom), unchanged.

**Needs you** lists only what really needs you, in plain words:

| What | When | Your answer |
| --- | --- | --- |
| *ClipFoundry found a strong trending video. Can you use this content?* | **Off by default.** Only with Advanced → *Ask me about strong videos nothing covers* turned on: only while today's plan is short, only for strong videos (Source Score 50 or more), at most 3 at a time. | **YES, I HAVE PERMISSION** (recorded as *Allowlisted* for that video, with the date), **NO** (*Blocked*, never asked again) or **VIEW SOURCE**. Only say yes when the creator gave you permission; being public or trending is not permission. |
| *N posts waiting for your approval* | TikTok posts always; YouTube posts unless automatic publishing is on (and clips it holds for you because a check noted a possible problem). | **REVIEW POSTS** opens the Publish Center. |
| *Reconnect YouTube / TikTok* | The platform refused the stored sign-in, or it is not connected while posts are planned there. | **RECONNECT**. |
| *GPU transcription is not working* | Strict GPU paused transcription. | What to do is shown with it. |

Quota notices resolve themselves and stay under Advanced. A video nothing covers, or whose file cannot be obtained in
an allowed way, is not a question: it is skipped, listed in the Activity log with the reason (with *Add the file* when
you could supply the original), and Autopilot moves on to the next one.

**Adding content by hand** stays possible and optional: *+ Add content manually* on the Autopilot page (paste a link, a
video on this computer, a folder to watch, or upload a video on the Create page), with one question: is it your own
content, do you have the creator's permission, or should Autopilot ask later.

### Hands-off discovery, eligibility and files

**Discovery** runs every 3 hours by itself, within the providers' quotas and your cost limit:

* **YouTube** (Data API search and video details, the connected account or an API key): recent popular videos for
  your topics, and the **original long video behind a popular short clip** when the clip links to it or its channel
  has it.
* **Web search** (optional, [Tavily](https://tavily.com), your own API key under Settings → Advanced → Discovery):
  public TikTok links for your topics and originals behind clips. Web search gives titles and links, never TikTok
  statistics: those stay *unknown*. It uses the credits your plan includes (the free plan: 1,000 a month) and spends
  money only up to the monthly cost limit you set (0 by default: never).
* **A free-license library** (Wikimedia Commons, on by default): videos whose authors released them for reuse.

Duplicates and re-uploads of videos already processed are dropped. Every number keeps where it came from and when it
was observed; ClipFoundry's own scores are labeled as estimates.

**Eligibility without per-video questions.** A video is used automatically only when something real covers it, and
the evidence and conditions are stored with it (`autopilot/rights.py`):

* your own content (*Owned*);
* a **creator agreement** you record once (Advanced → Sources & rights → *Record an agreement*): the creator, their
  channel IDs or handles, what shows the agreement, and its conditions: credit line, commercial use, which platforms,
  end date, and whether it also covers other people's music or footage in their videos (by default it does not, and
  a clip with detected music under such coverage is rejected);
* a license that allows it: **CC BY** (a credit line is added to the description; share-alike, non-commercial and
  no-derivatives licenses are never used automatically) or **public domain / CC0**, as the library reports it.

Anything else is skipped and listed in the Activity log. Cropping, captions, a credit or a short duration never make
something usable, and no score is treated as legal clearance.

**Confirmed channels** (`autopilot/verify.py`). A channel named by a feed, a web search or any list is only a claim.
Before your own channel (*Owned*) or a channel rule or agreement is applied to a video, the platform itself must
confirm that this exact video belongs to that channel: YouTube through the Data API (a video Autopilot found through
the Data API already carries YouTube's answer; any other one costs 1 quota unit per 50 videos), TikTok through its
embed API (oEmbed), which answers by the video's number whatever name the link shows. The link the file would come
from must lead to that same video. A confirmed channel still has to match one of your rules or agreements:
confirmation only says who posted the video. A video that cannot be confirmed (another channel, a link to a different
video, a platform ClipFoundry cannot ask, YouTube not connected) is skipped with *channel not confirmed* and the
reason in the Activity log, and asked about again later (after 1 hour if the platform was busy or not connected,
after 1 day if the video was not found). The check runs again before every stage, so a video queued earlier cannot
get around it, and a feed can never overwrite what the YouTube API reported about a video.

**Getting the file** (`autopilot/access.py`) is a separate check: a file on this computer, the folder a creator shares
with you (named in the agreement; the file is found by the video's YouTube ID in its name, or by its title, once it has
finished syncing), a file link under the address the creator gave you, the library's own download, or a direct link
you configured. Each file is stored with a provenance record (where it came from, how it was obtained, the rights and
evidence, the license and credit). If there is no allowed way, the video is skipped and the next one is tried.

### Advanced setup (optional)

Everything from before is still there for advanced users:

* **Where sources come from** (Autopilot → Advanced → Sources & rights): *watch folders* of your own recordings (a
  file that is still growing is treated as a live recording), *YouTube channels* you follow (`UC...`), *stream URLs*
  you may use (HLS/RTMP/SRT), and *signal feeds* (JSON/CSV) you are authorized to use. A folder, channel or stream
  you add can carry a rights status; a feed row's channel is a claim that must be confirmed (above).
* **Rights rules** (same page): channels whose clipping program you joined (*Allowlisted*), licensed feeds
  (*Licensed*), folders of your own recordings (*Owned*), or anything you must never use (*Blocked*), each with its
  basis. Anything without a rule or an answer waits for you.
* **Discovery** (Settings → Advanced → Discovery): a YouTube Data API key instead of the connected account, region,
  language, topics, how often to look and how old a video may be.
* **Schedule and limits** (Settings → Advanced → Autopilot details): time zone, active hours, minimum gap, per-platform
  daily limits, sources per day, clips per source, minimum quality, platforms, replacement, live monitoring, learning,
  the worker process, quotas and GPU.

The worker runs in its own background process by default (Settings → Advanced → Autopilot details → Worker process), so a crash in a
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
             │   Approval: yours in the Publish Center, or your automatic-publishing permission (YouTube only)
             │                                                    │
             └────────── Learning Worker <── real results <── Publisher (official APIs, resumable, idempotent)
```

| Worker | Job kinds | What it does |
| --- | --- | --- |
| Trend Scout | `trend_scan` | Reads YouTube search/chart results (within its quota share), feeds and watch folders. Stores every signal with its history and a Trend Score. Metrics carry their provenance: *observed*, *estimated* or *unavailable*. |
| Source Scout | `source_scout`, `feed_scan` | Turns signals into sources, scores them (Source Score, expected strong clips) and picks up to 3 per day, skipping duplicates, weak and unavailable ones. |
| Rights and Content Safety Gate | `rights_check` | Applies your rules, agreements and licenses. Only *Owned*, *Licensed*, *Allowlisted*, *Creative Commons* (CC BY) and public-domain sources continue automatically (each kind can be turned off under Advanced); everything else is skipped and listed in the Activity log. The gate runs again before every later stage, before scheduling and before publishing, so a later *Blocked* rule stops a post and a source queued before a check cannot skip it. Channel claims are confirmed first (see *Confirmed channels*). |
| Live Monitor | `live_watch`, `live_capture`, `post_live` | Records authorized live sources in segments, transcribes each segment (one GPU job at a time), clips strong moments from a rolling 15-minute window, and after the stream ends runs a full pass that can replace weaker live clips that were not published yet. |
| Clip Hunter | `hunt_source` | Brings the source in (hard link or copy of a local file, a direct media URL, or the URL importer only when allowed), transcribes on the GPU and builds a large candidate pool. |
| Deep Clip Analyzer | `analyze_source` | Fast filter → semantic analysis → deep evaluation (Viral Potential, audio and visual features) → boundary optimization → diversity selection (MinHash text and perceptual video fingerprints against everything already made). Then the **Engagement Strategist** writes a Clip Blueprint for each chosen clip (see below) and the clip is rendered from it. Renders up to 5 clips that pass the quality bar. |
| Packaging AI | `package_clip` | Writes title/description/caption/hashtag options in six styles from the words heard in the rendered clip (its final transcript), optionally with an AI provider, validates grounding, repetition and duplicates, and scores them. Each option records which render it was written for. |
| Final Quality Gate | `quality_check` | Checks the exact file that would be published: SHA-256 against the render record, streams and codecs, 1080×1920, duration, a full decode (a truncated file still reports its full length), black, frozen and silent stretches judged in context, caption timing, cuts inside words, and the hook/context/payoff estimates. Re-checks each platform's selected text against what is heard in that file. The report is bound to the file's hash, final transcript and time map. Failures keep the clip out of the schedule; warnings are shown with the post. |
| Smart Scheduler | `schedule_tick` | Places packaged clips whose current file and text passed the Final Quality Gate on each platform's time grid within your active hours and limits, computes the Final Opportunity Score, replaces weaker unpublished posts with clearly stronger new ones (a slot is swapped at most once every 24 hours, and it never has more than one swap waiting for your approval), and hands due approved posts to the publisher. |
| YouTube Quota Manager | (inside every YouTube call) | Counts units and calls per bucket, keeps discovery within its share, and reserves the rest for uploads, statistics and account checks. Resets at midnight Pacific. |
| Publisher | `publish` | Hashes the file again and needs a passing Final Quality Gate report for exactly those bytes, then uploads approved posts with the existing YouTube and TikTok code. An interrupted upload resumes its stored session (YouTube) or checks its publish ID (TikTok) instead of posting twice. If the platform accepted every byte but its answer was lost and it can no longer say what happened, the post is never uploaded again automatically: it becomes *Upload not confirmed* until you check (the video is looked for among the channel's newest uploads first). **Waits** are never shortened: when YouTube or TikTok asks to wait (`Retry-After`, or 60 s for a rate limit that gives no time), up to 60 s is waited out in place; a longer wait puts the post back for exactly that time (no attempt used), holds the platform's other posts until then, and the same upload continues afterwards. |
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

**Cutting out weak middle parts.** The Strategist may cut up to two weak sentences out of the middle of a clip:
sentences made only of filler words ("Um, you know, like, yeah."), a clear promotional line ("Subscribe to the
channel for more.") or a warm-up phrase that says nothing of its own ("So anyway, moving on."). It cuts only when
every rule for a safe cut holds: a pause on both sides, complete sentences, the next sentence does not point back at
what was removed ("It has ten lessons."), the hook, payoff, questions and the first and last sentences stay, at most
35% of the clip goes, and the clip stays at least as long as the shortest clip you allow. Otherwise the clip stays
one continuous piece. The order never changes. The final transcript, the captions, the post text and the final
check all follow what is heard in the cut clip, and the plan's reasons say what was cut.

**GPU.** One heavy GPU operation at a time, across processes (a lock file), with a wait for free VRAM
(Settings → Advanced → *Free GPU memory needed*). Transcription uses exactly the existing faster-whisper/CTranslate2
CUDA path; Autopilot only waits for its turn. **Strict GPU:** when an NVIDIA GPU is expected and CUDA fails (or the
GPU is present but unusable), Autopilot does not fall back to the CPU: the job pauses for 30 minutes without using
an attempt and an action item says what failed and how to fix it. Live capture keeps recording meanwhile; the
post-live pass transcribes the whole recording again on the GPU. Settings → Advanced → *Allow CPU transcription*
lets it continue on the CPU instead (slower). Manual projects keep their visible CPU fallback. Local AI models (Ollama/LM Studio) share the same lock.

**Downloads and addresses.** Autopilot fetches media and signals from URLs that come from data (a feed's rows, a
discovered source, a redirect), so every such URL is checked first (`netguard.py`): only http/https for downloads and
network stream protocols for live capture (never `file:`, `concat:`, `pipe:` or `data:` in ffmpeg), and the host
must resolve to public addresses. Addresses you typed yourself (a source added by hand, a stream you configured, a
signal feed's own URL) may point into your own network. Every redirect is checked, a download connects to exactly the
address that was checked, and it stops at Settings → Advanced → *Largest source* (8 GB and 240 minutes by default;
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
  and shows TikTok's Music Usage Confirmation. An approval is bound to the exact video (its SHA-256, not its size or date) and
  text: editing either, or a new render, needs a new approval. With automatic publishing on, YouTube posts are
  approved again by themselves only after the final check passed on the new file; TikTok always asks you.
* **Edit**, **Reschedule**, **Cancel**, **Retry**, **Publish now**, **Open source**, **Open post**, and **Link TikTok
  post** for inbox drafts finished in the TikTok app.
* **Upload not confirmed**: the upload may have finished but the platform cannot confirm it (for example STOP ALL
  JOBS or a crash during the upload). ClipFoundry first checks with the platform; if it still cannot tell, it
  waits for you: **It is published** (paste the link) or **Upload again** (after you checked that it is not there). It never uploads a
  second copy on its own.
* YouTube posts are uploaded early (default 30 minutes) as Private with `publishAt`, so YouTube itself publishes them
  at the planned time.
* **Final check**: every post shows the Final Quality Gate's verdict on its exact file and text (*passed*, *N warnings*, *failed*, *text needs a fix* or *pending*), with every check listed and marked as measured or as an estimate. A post whose file failed cannot be approved or uploaded; fix the clip and render it again.
* Views: *Upcoming*, *Needs attention*, *Published*, *History*.

## Controls and emergency stop

* **AUTOPILOT ON/OFF**: off means queued work waits; jobs you start by hand still run.
* **STOP ALL JOBS** (Autopilot page): cancels queued work, asks running jobs to stop at their next safe point
  (including manual renders and uploads) and pauses everything until you press **Resume jobs**. Nothing is published
  while stopped. An upload that is already transferring stops between chunks; check the platform if one was in flight.
* Per job: **Cancel**, **Retry** and the job **Log** (Autopilot → Advanced → Jobs).
* Per source: **Rights**, **Clip now**, **Skip**, **Add file** (Autopilot → Advanced → Sources & rights).
* Settings → General has on/off, the daily target and automatic publishing; Settings → Advanced has every other target,
  limit and switch described above.

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

If Autopilot ran overnight without making clips, first look at **Currently**, **Last search**, **Next search**,
the search problems on the main page, and **Activity**. Posting hours limit when posts go out; they do not prevent
discovery or clipping overnight. A connected account alone does not supply downloadable original files. Discovery
also checks your connected YouTube channel, channels covered by active recorded permissions, and shared folders in
creator agreements. These still pass the same channel, rights, file-access and final-quality checks.

| Problem | What to do |
| --- | --- |
| "Connect YouTube to start finding content." | No discovery option is enabled. Connect YouTube, enable the free-license library, or add your recordings or a creator agreement with a shared folder. The free library does not require a YouTube account. |
| "Background work has stopped" | Restart with `start.bat` and reload the page. If it happens again, check Advanced → System details and `data/logs/workers.log` (under the configured data folder). |
| "No usable video files yet" | Some videos are covered, but their original files are unavailable. Use a creator's shared folder or **+ Add content manually**. Activity explains each skipped video. A public link or account connection is not a video download. |
| "No covered videos found yet" | The videos found so far do not pass your recorded permissions or supported licenses. Record an agreement you actually have, or provide your own recordings. |
| "Waiting for the next search" | The previous search finished; the next search time is shown. Known folders and waiting files are checked every three minutes while Autopilot is running. |
| A search problem is shown | Follow its displayed fix. Other working discovery options continue; results already found are kept. A rate limit keeps the platform's requested wait. |
| "No strong opportunities yet. ClipFoundry is still looking." | Discovery works, but nothing found so far is strong enough. It keeps looking; nothing to do. |
| Workers show *not running* (Advanced → System details) | Check Needs you. If the worker process cannot start, switch Settings → Advanced → Worker process to *Inside the app*. |
| Nothing gets clipped | Check Activity for rights, missing files, short videos, processing failures or quality holds. Unknown rights are skipped without per-video questions by default. Original files must be available through an allowed access method. |
| Jobs wait for the GPU | Another heavy GPU job (or another program) is using it; see the GPU card. Lower *Free GPU memory needed* only if you know the model fits. |
| "fell back to CPU" on the GPU card | Run `gpu-check.bat` and follow the fix it prints (see INSTALL.md). |
| "Autopilot transcription is paused: the GPU could not be used" | Run `gpu-check.bat` and follow the fix it prints. Until it is fixed, you can allow CPU transcription in Settings → Advanced → YouTube quota and GPU. |
| Discovery stopped: quota | The YouTube quota share for discovery is used up; it resumes after midnight Pacific. Publishing keeps its reserve. |
| Posts wait in *Needs approval* | Approve them in the Publish Center. YouTube can use the automatic-publishing permission you explicitly enable; TikTok still requires approval for each post. |
| YouTube posts end up Private | Your Google Cloud project has not passed the YouTube API audit. |
| TikTok: privacy options disabled | Your TikTok app is not audited; only *Only me* is possible, or use *Send to TikTok inbox*. |
| Something is running that should not | **STOP ALL JOBS**, then look at Autopilot → Advanced → Jobs and the job logs. |
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
