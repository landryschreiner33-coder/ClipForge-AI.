# ClipFoundry Autopilot

Autopilot turns ClipFoundry into a persistent, local-first content opportunity engine: it discovers what is gaining
attention, checks whether each source may be used, finds the strongest moments, packages them for YouTube Shorts and
TikTok, schedules them, publishes the posts you approved through the official APIs, and learns from the real results.

> **Names since the robot office (October 2026):** Home is now the **Office**, the Autopilot page is **Missions**,
> the Library is **Clips**, Posts is the **Queue**, and **Brain** has its own workspace; old addresses still open
> the right page. New uploads can be Public after explicit setup and eligible platform permission. Existing Private
> schedules stay Private. TikTok needs per-post consent or a manual handoff. See
> [OFFICE.md](OFFICE.md) for the office, the audience policy, the capability matrix and the Brain.

Everything runs on your computer. The platform APIs are used only for discovery signals, publishing and reading your
own results. The daily numbers (3 sources, up to 5 clips per source, 15 clips a day) are **targets, never quotas**:
quality, rights, availability and platform limits always come first, so a day can end with fewer posts.

Contents: [platform rules](#what-the-platforms-allow-and-what-that-means-for-autopilot) ·
[setup](#setting-it-up) · [how it works](#how-it-works) · [scores](#scores) · [Posts](#posts) ·
[controls and emergency stop](#controls-and-emergency-stop) · [what is not possible](#blocked-or-limited-capabilities) ·
[unattended operation](UNATTENDED.md) ·
[legal pages](#legal-pages-terms-of-service-and-privacy-policy) · [troubleshooting](#troubleshooting)

## What the platforms allow (and what that means for Autopilot)

These rules come from the platforms, and they win over the 15-clips-a-day target and over full automation.

| Rule | Source | Effect in ClipFoundry |
| --- | --- | --- |
| Users must have final control over data published to YouTube and know what the app does in their name. | YouTube API Services Developer Policies | By default every YouTube post waits for your approval in Posts (*Needs review*). With **automatic publishing** turned on (an explicit, stored permission: which channel, what content, who can see it, how many a day, when), clips that passed every check are approved by that permission, labeled *Approved automatically*, never as approved by you, and each stays cancellable until it goes out. |
| TikTok apps may only upload after the user expressly consents, must show a preview, must let the user edit the text, must read the creator's options before posting and must not pre-select a privacy level. | TikTok Content Sharing Guidelines | Every TikTok post waits for your approval, made on the post's own page, which shows the preview, the creator nickname and TikTok's options (privacy is never pre-selected). Automatic publishing is not offered for TikTok, and the app says why. Once approved, a post goes out at its time by itself. |
| API data must not be used to create derived data or metrics without Google's approval. | YouTube Developer Policies III.E.4; Additional policies for derived metrics | Momentum scores (view velocity, engagement rates) are computed from YouTube data only when you confirm that your Google Cloud project was granted this. Otherwise YouTube results are ranked by YouTube's own order and shown as YouTube reported them. |
| Stored YouTube API data must be refreshed or deleted within 30 days. Approved projects may keep statistics of the user's own videos (Authorized Data) longer. | YouTube Developer Policies; Additional policies for derived metrics and data storage | A maintenance job deletes YouTube data older than 30 days. With the approval setting on and the channel connected, only the statistics of your own videos are kept longer. |
| Content may only be downloaded from YouTube through means YouTube authorizes, or with permission from YouTube and the rights holders. | YouTube Terms of Service | Getting the file is decided separately from the right to reuse it (`autopilot/access.py`). Autopilot uses your own files, a folder or file links a creator shares with you under an agreement, a free-license library's own downloads, and direct links you configured. A connected account or a public link is never treated as permission to download. Downloading platform-hosted videos with the URL importer is off by default. |
| `chart=mostPopular` now covers the Trending Music, Movies and Gaming charts only. | YouTube Data API revision history (July 2025) | Broad discovery uses topic searches (their own 100-call daily quota bucket since June 2026) plus channels you follow. |
| Google Trends API is an application-gated alpha; TikTok has no trend API for general developers. | Google Search Central; TikTok for Developers | Not used. Shown as unavailable in the UI. ClipFoundry never scrapes either. |
| YouTube project status | Current API docs | Unverified projects may upload Public; audits cover more quota. |
| Unaudited TikTok apps | Content Posting API | Direct Post stays restricted; approval and per-post consent matter. |

YouTube's [videos.insert](https://developers.google.com/youtube/v3/docs/videos/insert) and
[videos](https://developers.google.com/youtube/v3/docs/videos) documentation, updated October 8, 2026 and checked
October 10, now permit Public uploads from unverified projects. API audits apply to quota increases. ClipFoundry
still requires explicit Public setup and appropriate account-bound approval/permission, then reports actual returned
visibility. TikTok's app audit remains separate; a private TikTok account cannot offer Everyone.

## Setting it up

### Adding a video or stream while Autopilot runs

On Overview, paste a public link into **Add a video or stream** and press **ADD**. **Added by you** shows its durable
status immediately. No feed configuration is needed. The same video's supported URL aliases return **Already added**
and point to the existing item. Submitted links have priority over discovered work after the current safe step;
manual **Clip now** remains first. You can cancel, retry, move an item to the top, or remove it before processing.
Completed clips remain in the Library. Discovery keeps running alongside submitted work.

Upcoming streams wait without consuming a processing turn; live streams capture and search recorded segments,
then analyze the recording after the stream ends. Queue records, finished clips and stream state survive app
restarts. Autopilot resumes automatically when it was on; an intentional pause or Stop all jobs stays in effect.
Temporary failures wait and retry, unusable or weak videos release their turn, and ordinary failures stay in
Activity. **Needs you** is reserved for missing account access, required approvals, resource problems and outcomes
that cannot safely be decided automatically.

Submitting a link expresses local processing intent. If supported access is available, its clips can be saved and
quality-checked even when reuse permission is unknown. An explicit block still wins. Publishing requires its own
rights, quality, account and approval checks. Platform downloads remain subject to the existing download setting;
the app never uses cookies or credentials to bypass private content, DRM, paywalls or authentication.

The first time, **Get started** on Home (or **Set up Autopilot** on the Autopilot page) opens a setup in three steps
(`#/setup`), and that is all a normal user needs:

1. **Add your videos.** *Open videos folder* opens your videos folder (see below); put videos you made in it. *Choose
   a video* makes clips from one video right away instead. You can do this any time later.
2. **Choose how to work.** Choose *Let Autopilot do it*, then the topics: a suggestion is filled in; pick or type
   others if you like.
3. **Set up posting.** **Connect YouTube**: Autopilot uses the connected account to post your Shorts and to look for
   videos. **Connect TikTok** is optional: one platform without the other works too. Then **Start Autopilot**: it
   turns Autopilot on for the accounts you connected and starts looking right away.

**Your videos folder.** Videos from other people's channels are never used without an agreement or a license, so
with only a connected account Autopilot usually finds nothing it may clip. The simplest way to give it work is your
videos folder: `Videos\ClipFoundry` in your Windows user folder (`ClipFoundry videos` in your user folder if there is no
Videos folder). **Start Autopilot** creates it and watches it (`autopilot/myvideos.py`). It is outside the ClipFoundry
folder, so updating ClipFoundry never deletes it. Every video you put there is clipped by itself and counts as your own
content (*Owned*), like a video added on the Add video page, so only put videos there that you made or may use. It is
an ordinary watch folder under Autopilot → Permissions & sources (*Where videos come from*): turning it off there
keeps it off, and removing it there keeps it removed until you press *Open videos folder* again.

**Keeping the PC awake.** While Autopilot is on, ClipFoundry asks Windows not to put the PC to sleep (the screen may
still turn off). The request ends by itself when ClipFoundry closes. A laptop still sleeps when you close its lid.
Settings → Advanced → Autopilot details → *Keep the PC awake* turns it off. On macOS and Linux nothing is changed.
Autopilot → Overview says what is really happening (the *This PC* fact and the note under it; `home.keep_awake`, from
`awake.KeepAwake.status`), not what the setting asks for: *Kept awake* (*is keeping this PC from going to sleep*)
only after Windows accepted the request, *Asking Windows* for the few seconds before that, and when Windows refuses,
*Windows said no* (*did not let ClipFoundry keep this PC awake*) with a Needs you item that says how to turn off sleep
in Windows' power settings. It asks again every minute (not every few seconds), the refusal is logged once (Autopilot
→ Advanced → System → *Recent events*), and the item goes away by itself when a retry works or Autopilot or the
setting is turned off. The same app thread asks and gives up the request, because Windows ties it to that thread.

To let YouTube posts go out without reviewing each one, turn on **automatic publishing** afterwards (*Turn on
automatic publishing…* under *How posts go out* on Autopilot → Overview, or in Settings → Accounts → YouTube). It
shows exactly what you allow: the channel, what gets posted (only clips that passed every check, from videos you own
or that an agreement or license covers), who can see the posts, made for kids or not, how many a day and between
which hours, and you confirm it. Turning it off (*Turn off…*) sends every post it approved that has not started
uploading back to Posts → *Needs review*, where it waits for your OK. Permission is bound to the connected channel
and confirmed audience: new Public uploads require fresh Public permission; existing Private posts stay Private.
Selected-viewer Private uploads still need you to share them in YouTube Studio. Public posts need no invitations.

For all-day scheduling, choose **0–24** as the posting window; this does not raise the daily limit or override
quality, rights, quota or duplicate checks. For long-running Google access, an External OAuth app in Testing has
seven-day refresh grants for YouTube scopes. Set its OAuth publishing status to Production, then reconnect for a
fresh grant. Personal-use apps may be exempt from OAuth verification; Production and API quota audits are separate.
Authorization can still expire or be revoked. [UNATTENDED.md](UNATTENDED.md) covers the optional app-exit watchdog,
same-user Windows login startup and local diagnostic logs. It preserves intentional Pause/Stop and consent holds.
Run only one app per data profile, including across different ports. The watchdog detects process exit, not a
still-running hung main app.

Both platforms only let apps like ClipFoundry post through *your own* free developer app, so the first **Connect
YouTube** or **Connect TikTok** on a computer asks for that app's two codes once (the steps are under *How to get
these codes*; see also [INSTALL.md](../INSTALL.md)). After that, **Connect** is just the platform's own sign-in page.

You do not add sources, feeds, folders, rules or workers. Behind the scenes Autopilot uses whatever is available (the
connected YouTube account for discovery; your videos folder; other watch folders and feeds only if you added some;
Google Trends and TikTok trends are not available to apps and are skipped without bothering you) and these defaults:
United States, English, all trending categories plus broad topics, 3 videos a day, up to 5 clips each, 15 clips a day
as a target, posting times chosen for you (America/Chicago, 9:00 to 21:00, spread over the day), a new look for videos
every 3 hours, dynamic replacement, live monitoring, learning, automatic scheduling and automatic publishing of the
posts that are approved. Autopilot is turned on and off with **Start Autopilot** / **Pause Autopilot** on the
Autopilot page; Settings → Defaults has the daily target, the posting hours and the topics, and Settings → Accounts
has automatic publishing; everything else is under Settings → Advanced.

**The Autopilot page** has four tabs. **Overview** shows only: whether Autopilot is on, with **Start Autopilot** /
**Pause Autopilot**; four facts (*This PC*: whether it is kept awake; *Processing*: the GPU or the CPU; *Next online
search*: when it next looks for new videos online; *Your videos folder*: whether it is checked) and a reminder that
the PC must stay on with the ClipFoundry window open to find and render clips, and when posts go out (a YouTube post
that was already uploaded goes out at its time even if the PC is off; TikTok posts need the PC on at their time);
**Needs you**; **Working on** (what Autopilot is doing right now, step by step); **Your videos** (how many videos your
videos folder holds, whether it is watched, *Open videos folder* and *Show folder location*); **Coming up** (the
upcoming posts) and **How posts go out** (automatic publishing, and whether YouTube and TikTok are connected); and
**Pause or stop everything**. **Activity** has the top opportunities it found (*What Autopilot found*) and the
activity log (what it did with each video it found and why it skipped any). **Permissions & sources** has creator
agreements, watch folders, feeds, permission rules and every video it found. Workers, quota, jobs, today's numbers
against the target, the next post, scores and learning are under **Advanced** (System, Jobs, Learning). **Home**
shows the most urgent thing that needs you, your recent videos and clips, and the next posts.

**Needs you** (on Autopilot → Overview; Home shows the first item) lists only what really needs you, in plain words:

| What | When | Your answer |
| --- | --- | --- |
| *ClipFoundry found a strong trending video. Can you use this content?* | **Off by default.** Only with Settings → Advanced → Discovery and rights → *Ask me about strong videos nothing covers* turned on: only while today's plan is short, only for strong videos (Source Score 50 or more), at most 3 at a time. | **Yes, I have permission…** (recorded as *Allowlisted* for that video, with the date), **No, don't use it** (*Blocked*, never asked again) or **View the video**. Only say yes when the creator gave you permission; being public or trending is not permission. |
| *N posts waiting for your OK* | TikTok posts always; YouTube posts unless automatic publishing is on (and clips it holds for you because a check noted a possible problem). | **Review posts** opens Posts → Needs review. |
| *Reconnect YouTube / TikTok* | The platform refused the stored sign-in, or it is not connected while posts are planned there. | **Reconnect YouTube** / **Reconnect TikTok**. |
| *GPU transcription is not working* | Strict GPU paused transcription. | What to do is shown with it; **Open GPU settings** opens Settings → Advanced. |
| *Your PC may go to sleep and stop Autopilot* | Autopilot and *Keep the PC awake* are on, but Windows refused to keep the PC awake. | Turn off sleep in Windows' power settings (the steps are shown with it). It goes away by itself when ClipFoundry's next try (every minute) works. |
| *Autopilot needs videos to work with* (or *has used all your videos*) | Autopilot is on and has looked, but nothing it may use is waiting or being clipped, and it made no clip in the last 24 hours. It says how many videos it skipped because they belong to other people. | **Open videos folder**, then put videos you made in it (or **Add a video yourself**). |

Quota notices resolve themselves and stay under Autopilot → Advanced → System. A video nothing covers, or whose file
cannot be obtained in an allowed way, is not a question: it is skipped, listed in Autopilot → Activity with the reason
(with *Add the file…* when you could supply the original), and Autopilot moves on to the next one.

**Adding content by hand** stays possible and optional: under Autopilot → Permissions & sources, *Add…* → *A video,
link or folder of yours…* (a link, a file on this computer, a folder to watch, or *Upload a video*, which opens the
Add video page), with one question, *Can ClipFoundry use it?*: it's your own content, you have the creator's
permission, or you're not sure (then it isn't used until you decide).

### Hands-off discovery, eligibility and files

**Discovery** runs every 3 hours by itself, within the providers' quotas and your cost limit:

* **YouTube** (Data API search and video details, the connected account or an API key): recent popular videos for
  your topics, and the **original long video behind a popular short clip** when the clip links to it or its channel
  has it.
* **Web search** (optional, [Tavily](https://tavily.com), your own API key under Settings → Advanced → Discovery and
  rights → *Web search (Tavily) key*): public TikTok links for your topics and originals behind clips. Web search
  gives titles and links, never TikTok statistics: those stay *unknown*. It uses the credits your plan includes (the
  free plan: 1,000 a month) and spends money only up to the monthly cost limit you set (0 by default: never).
* **A free-license library** (Wikimedia Commons, on by default): videos whose authors released them for reuse.

Duplicates and re-uploads of videos already processed are dropped. Every number keeps where it came from and when it
was observed; ClipFoundry's own scores are labeled as estimates.

**Eligibility without per-video questions.** A video is used automatically only when something real covers it, and
the evidence and conditions are stored with it (`autopilot/rights.py`):

* your own content (*Owned*);
* a **creator agreement** you record once (Autopilot → Permissions & sources → *Record an agreement…*): the creator,
  their channel IDs or handles, what shows the agreement, and its conditions: credit line, commercial use, which
  platforms, end date, and whether it also covers other people's music or footage in their videos (by default it does
  not, and a clip with detected music under such coverage is rejected);
* a license that allows it: **CC BY** (a credit line is added to the description; share-alike, non-commercial and
  no-derivatives licenses are never used automatically) or **public domain / CC0**, as the library reports it.

Anything else is skipped and listed in Autopilot → Activity. Cropping, captions, a credit or a short duration never make
something usable, and no score is treated as legal clearance.

**Confirmed channels** (`autopilot/verify.py`). A channel named by a feed, a web search or any list is only a claim.
Before your own channel (*Owned*) or a channel rule or agreement is applied to a video, the platform itself must
confirm that this exact video belongs to that channel: YouTube through the Data API (a video Autopilot found through
the Data API already carries YouTube's answer; any other one costs 1 quota unit per 50 videos), TikTok through its
embed API (oEmbed), which answers by the video's number whatever name the link shows. The link the file would come
from must lead to that same video. A confirmed channel still has to match one of your rules or agreements:
confirmation only says who posted the video. A video that cannot be confirmed (another channel, a link to a different
video, a platform ClipFoundry cannot ask, YouTube not connected) is skipped with *channel not confirmed* and the
reason in Autopilot → Activity, and asked about again later (after 1 hour if the platform was busy or not connected,
after 1 day if the video was not found). The check runs again before every stage, so a video queued earlier cannot
get around it, and a feed can never overwrite what the YouTube API reported about a video.

**Getting the file** (`autopilot/access.py`) is a separate check: a file on this computer, the folder a creator shares
with you (named in the agreement; the file is found by the video's YouTube ID in its name, or by its title, once it has
finished syncing), a file link under the address the creator gave you, the library's own download, or a direct link
you configured. Each file is stored with a provenance record (where it came from, how it was obtained, the rights and
evidence, the license and credit). If there is no allowed way, the video is skipped and the next one is tried.

### Advanced setup (optional)

Everything from before is still there for advanced users:

* **Where videos come from** (Autopilot → Permissions & sources, *Add…* → *A channel, stream or trend list…*):
  *folders* of your own recordings (a file that is still growing is treated as a live recording), *YouTube channels*
  you follow (`UC...`), *streams* you may use (HLS/RTMP/SRT), and *trend lists* (JSON/CSV) you are authorized to use.
  A folder, channel or stream you add can carry a permission; a trend list row's channel is a claim that must be
  confirmed (above).
* **Permission rules** (same page, *Add rule…*): channels whose clipping program you joined (*Allowlisted*), licensed
  feeds (*Licensed*), folders of your own recordings (*Owned*), or anything you must never use (*Blocked*), each with
  its basis. Anything without a rule or an answer waits for you.
* **Discovery** (Settings → Advanced → Discovery and rights): a YouTube Data API key instead of the connected account,
  region, language, how often to look and how old a video may be. The topics are on Settings → Defaults (*Topics to
  look for online*).
* **Schedule and limits** (Settings → Advanced): *Autopilot details* has the time zone, sources per day, clips per
  source, minimum quality, platforms, replacement, live monitoring, learning and the worker process; *Autopilot
  posting* has the minimum gap and the per-platform daily limits; the quotas are under *Discovery and rights* and the
  GPU under *Transcription and GPU*. The active hours are the posting hours on Settings → Defaults.

The worker runs in its own background process by default (Settings → Advanced → Autopilot details → *Worker
process*: *Own process*), so a crash in a worker cannot take the app down. It is started and stopped with the app:
when the app closes, the worker notices the missing heartbeat and exits within a minute. It can also be started on
its own with `python -m clipfoundry workers`.

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
             │   Approval: yours in Posts, or your automatic-publishing permission (YouTube only)
             │                                                    │
             └────────── Learning Worker <── real results <── Publisher (official APIs, resumable, idempotent)
```

| Worker | Job kinds | What it does |
| --- | --- | --- |
| Trend Scout | `trend_scan` | Reads YouTube search/chart results (within its quota share), feeds and watch folders. Stores every signal with its history and a Trend Score. Metrics carry their provenance: *observed*, *estimated* or *unavailable*. |
| Source Scout | `source_scout`, `feed_scan` | Turns signals into sources, scores them (Source Score, expected strong clips) and picks up to 3 per day, skipping duplicates, weak and unavailable ones. |
| Rights and Content Safety Gate | `rights_check` | Applies your rules, agreements and licenses. Only *Owned*, *Licensed*, *Allowlisted*, *Creative Commons* (CC BY) and public-domain sources continue automatically (each kind can be turned off in Settings → Advanced → Discovery and rights → *Use automatically*); everything else is skipped and listed in Autopilot → Activity. The gate runs again before every later stage, before scheduling and before publishing, so a later *Blocked* rule stops a post and a source queued before a check cannot skip it. Channel claims are confirmed first (see *Confirmed channels*). |
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
leases expire and work can resume/retry after restart, using its idempotency key and saved state to avoid duplicating
completed work. Saved upload sessions and uncertain-outcome holds prevent blind repeat uploads.
Jobs you start by hand (for example *Clip now*) run even while Autopilot is off.

**Recovery and resource limits.** Failed worker initialization stops partially started workers before releasing its
host lock. Job setup failures clear their running/heartbeat entry instead of retaining a phantom lease. Media
subprocess timeouts and cancellation can interrupt blocked pipe reads/writes and waits, killing and reaping the
children. Disk checks keep a 2 GB reserve: unknown-size downloads budget for their configured maximum, and live
capture rechecks free space while recording. Low disk shows Needs you and a durable 30-minute wait, retaining saved
segments and completed files; it is not treated as the stream ending. Final assemblies replace a completed recording
only after the temporary assembly succeeds. No owner media is automatically deleted to make room.

Before a new scheduled upload session begins, Pause, standing permission, account/audience and final-file checks
run again even if a local publication row already exists. A valid existing session continues with its original
confirmed bytes. Final-chunk crashes, cancellation or ambiguous platform replies retain an unknown-outcome hold;
later reconnect, setup, scope and quota errors preserve that hold and publication identity after final-byte evidence.
Recovery requires an original-account, unique recent match with the submitted title, description and tags, then
reads actual returned visibility. A mismatch stays held for the existing Queue resolution; a restart grants no
permission to upload another copy. Manual unknown uploads expose **Refresh status** without starting a transfer.

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
(Settings → Advanced → Transcription and GPU → *Free GPU memory needed*). Transcription uses exactly the existing
faster-whisper/CTranslate2 CUDA path; Autopilot only waits for its turn. **Strict GPU:** when an NVIDIA GPU is expected
and CUDA fails (or the GPU is present but unusable), Autopilot does not fall back to the CPU: the job pauses for 30
minutes without using an attempt and an action item says what failed and how to fix it. Live capture keeps recording
meanwhile; the post-live pass transcribes the whole recording again on the GPU. Settings → Advanced → Transcription
and GPU → *Allow CPU transcription in Autopilot* lets it continue on the CPU instead (slower). Manual projects keep
their visible CPU fallback. Local AI models (Ollama/LM Studio) share the same lock.

**Downloads and addresses.** Autopilot fetches media and signals from URLs that come from data (a feed's rows, a
discovered source, a redirect), so every such URL is checked first (`netguard.py`): only http/https for downloads and
network stream protocols for live capture (never `file:`, `concat:`, `pipe:` or `data:` in ffmpeg), and the host
must resolve to public addresses. Addresses you typed yourself (a source added by hand, a stream you configured, a
signal feed's own URL) may point into your own network. Every redirect is checked, a download connects to exactly the
address that was checked, and it stops at Settings → Advanced → Autopilot details → *Largest source* (8 GB and 240
minutes by default; longer videos are not processed). A download that would leave less than 2 GB free on the data
drive waits with an action item.

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

Each planned post's page shows *Why this time and score (estimates)* with the explanation, and *History of this post*
(the audit trail).

## Posts

**Posts** lists every planned and published post (one clip on one platform), in order, with its video, text,
platform, permission, time and final check. Each post opens as its own page with its scores.

* **Approve for YouTube** / **Approve for TikTok** (on the post's page, after ticking *I watched this video and read
  its text*): each post needs your approval or valid standing YouTube permission. For YouTube you confirm the title,
  description, tags, made-for-kids answer and explicit Public/Private audience. For TikTok the page reads creator info
  first, shows your nickname and lets you choose the privacy options it returns, without preselection. Everyone
  needs a public TikTok account and eligible app; followers/friends/Only me depend on the account and app. It also shows
  interactions (off by default), the commercial content disclosure,
  and shows TikTok's Music Usage Confirmation. An approval is bound to the exact video (its SHA-256, not its size or
  date) and text: editing either, or a new render, needs a new approval. With automatic publishing on, YouTube posts
  are approved again by themselves only after the final check passed on the new file; TikTok always asks you.
* On the post's page: edit the text (**Save changes**, or **Save the text without approving**), **Change the
  time…**, **Cancel this post…**, **Try again…**, **Publish now…** (on an approved post), and **Link the post…** for
  inbox drafts finished in the TikTok app. A post's More menu in the list also has **Open the clip**, **Open on
  YouTube** / **Open on TikTok** and **Open the source video**.
* **Upload not confirmed**: the upload may have finished but the platform cannot confirm it (for example **Stop all
  jobs** or a crash during the upload). ClipFoundry first checks with the platform; if it still cannot tell, it waits
  for you: **It's on YouTube: add its link…** (or TikTok) or **It's not there: upload again…** (after you checked
  that it is not there). It never uploads a second copy on its own.
* New confirmed Public YouTube posts upload locally when due, without `publishAt`. Existing Private schedules stay
  Private and may upload ahead of time (default 30 minutes). Selected-viewer posts show *Awaiting viewer invitations*
  until you share them in Studio and press **I shared it**. Legacy unconfirmed public/unlisted plans remain held.
* **Final check**: every post shows the Final Quality Gate's verdict on its exact file and text (*passed*, *passed,
  N warnings*, *failed*, *the text needs a fix* or *not done yet*), with every check listed (*All N checks of this
  exact file*) and marked as measured or as an estimate. A post whose file failed cannot be approved or uploaded; fix
  the clip and render it again.
* Tabs: *Needs review*, *Scheduled*, *Published* (tick *Also show canceled and replaced posts* for the history),
  *Problems* and *Results* (the real numbers of your posts).

## Controls and emergency stop

* **Start Autopilot** / **Pause Autopilot** (Autopilot → Overview): paused means queued work waits; jobs you start by
  hand still run.
* **Stop all jobs…** (Autopilot → Overview → *Pause or stop everything*): cancels queued work, asks running jobs to
  stop at their next safe point (including manual renders and uploads) and pauses everything until you press
  **Resume jobs** (in the *All jobs are stopped* banner). No new transfer starts while stopped. An upload that is
  already transferring stops at its next safe point; the platform may have accepted its final bytes already, so
  check the existing outcome if one was in flight.
* Per job: **Cancel…**, **Retry** and the job **Log** (Autopilot → Advanced → Jobs).
* Per found video: **Permission…**, and in its More menu **Clip now**, **Skip this video** and **Add the file…**
  (Autopilot → Permissions & sources → *Found videos and their permission*).
* On/off is on the Autopilot page; Settings → Defaults has the daily target (and the posting hours and topics),
  Settings → Accounts has automatic publishing; Settings → Advanced has every other target, limit and switch described
  above.

## Blocked or limited capabilities

These are not simulated; the UI shows them as unavailable or explains the restriction.

| Capability | Status |
| --- | --- |
| Google Trends data | Not available: the official Google Trends API is an application-gated alpha. Not scraped. |
| TikTok trends and TikTok discovery | Not available: TikTok offers no trend or search API for general developers. TikTok is never scraped. |
| YouTube momentum metrics (velocity, engagement rates, derived totals, learning from YouTube results) | Only with Google's approval under the additional policies for derived metrics; enable the setting only if your project was approved. |
| Broad YouTube trending | `chart=mostPopular` covers Music, Movies and Gaming only; general discovery uses topic searches within the 100-call search bucket. |
| Downloading YouTube or other platform videos | Off by default. YouTube's Terms allow downloads only through YouTube's own features or with permission. Use your original files, YouTube Studio downloads of your own videos, or turn it on only with permission. |
| Unattended YouTube publishing | Designed for it after setup and standing permission; deliberate holds still apply. |
| Unattended TikTok publishing | Each post still needs your consent; packages/drafts need completion in TikTok. |
| Public from an unverified YouTube project | Current API permits it; check actual returned visibility and quota. |
| Public from a private TikTok profile | Everyone is unavailable; this app does not change your profile privacy. |
| 15 posts/day on both platforms | Subject to the YouTube quota (by default 100 upload calls a day, shared with anything else your Google Cloud project uploads), TikTok's per-creator posting limits and your own limits. |
| TikTok retention metrics | Not available from TikTok's API. |

## Legal pages (Terms of Service and Privacy Policy)

[`docs/legal/`](legal/) holds the public website: `index.html` (product page), `privacy.html`, `terms.html` and
`site.css`. The pages were written from an audit of the code (what is stored, what is sent where, how long it is kept,
disconnecting and deleting) and name the publisher, contact email and governing law. **No lawyer has reviewed them.**
`tests/test_autopilot_discovery.py` checks that the folder holds only these four files, with no placeholders, scripts,
forms or outside resources. When a change alters what ClipFoundry stores or sends, update the pages with it.

Where they are served:

* **In the app:** <http://127.0.0.1:8765/legal/>, `/legal/privacy` and `/legal/terms` (linked at the bottom of the
  sidebar). These are only reachable on your PC, so they are not enough for the developer consoles.
* **Public website (needed for the Google OAuth consent screen and the TikTok developer app):** GitHub Pages from a
  separate `gh-pages` branch that holds only the four files and an empty `.nojekyll`, so nothing else in the
  repository is published. The addresses are then `https://<user>.github.io/<repo>/`, `.../privacy.html` and
  `.../terms.html`; open them once before entering them in Google Cloud (OAuth consent screen → App information) and
  TikTok for Developers (app details). Publishing needs the owner's OK.
* **Keep the website addresses separate from the sign-in addresses.** The OAuth redirect addresses stay on your own
  PC (`http://127.0.0.1:8765/api/oauth/youtube/callback` and `.../api/oauth/tiktok/callback`, the TikTok one as
  Settings → Accounts shows it); the website is never a redirect address.

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

If Autopilot ran overnight without making clips, first look at Autopilot → Overview: the line under the headline
(what it is doing, or why nothing is being clipped), *Next online search* (with the last search), any search that did
not work, **Needs you**, and **Activity**. Posting hours limit when posts go out; they do not prevent
discovery or clipping overnight. A connected account alone does not supply downloadable original files. Discovery
also checks your connected YouTube channel, channels covered by active recorded permissions, and shared folders in
creator agreements. These still pass the same channel, rights, file-access and final-quality checks.

| Problem | What to do |
| --- | --- |
| "Connect YouTube to start finding content." (Autopilot → Activity) | No way to find videos is on: the free-license library is off, YouTube is not connected and no folder is watched. Connect YouTube, turn the library back on (Settings → Advanced → Discovery and rights), or add a folder or a creator agreement with a shared folder under Autopilot → Permissions & sources. |
| "Autopilot's background work has stopped" (Needs you; *Background work has stopped* on Overview) | The app answers, but its workers have not for over a minute and could not be restarted. Close the black ClipFoundry window and start ClipFoundry again with `start.bat`. If it happens again, see Autopilot → Advanced → System and `data/logs/workers.log`. |
| "No usable video files yet" (Overview) | Videos it may use were found, but there is no file it is allowed to get (YouTube does not let apps download videos, even your own). Put the original in your videos folder, use a creator's shared folder, or **Add the file** in Activity. |
| "No covered videos found yet" (Overview) | The videos found so far belong to other people and no agreement or license covers them. Put your own videos in your videos folder, or record an agreement you really have. |
| "Waiting for the next search" (Overview) | The last online search finished; *Next online search* shows when the next one is. Your videos folder and waiting files are checked every 3 minutes meanwhile. |
| "Some searches did not work" (Overview, with the search and what to do) | Follow its fix. The other searches keep working and what was already found is kept. A platform's wait (Retry-After) is never shortened. |
| "No strong opportunities yet. ClipFoundry is still looking." | Discovery works, but nothing found so far is strong enough. It keeps looking; nothing to do. |
| Workers show *Not running* (Autopilot → Advanced → System) | Check Needs you. If the worker process cannot start, switch Settings → Advanced → Autopilot details → *Worker process* to *Inside the app*. |
| Nothing gets clipped | Check Activity: it says for each video why it was skipped (not covered, no allowed way to get the file, too short, a repeat) or where it stopped. Unknown rights are skipped without questions by default. Your own recordings are clipped without questions when you add them as your own content (your videos folder, or *Add…* → *A video, link or folder of yours…* under Autopilot → Permissions & sources). |
| Jobs wait for the GPU | Another heavy GPU job (or another program) is using it; see the *GPU* panel (Autopilot → Advanced → System). Lower *Free GPU memory needed* (Settings → Advanced → Transcription and GPU) only if you know the model fits. |
| "Ran on the CPU instead of the GPU" in the *GPU* panel (or *CPU (slower) for the last video* on Autopilot → Overview) | Run `gpu-check.bat` and follow the fix it prints (see INSTALL.md). |
| "GPU transcription is not working" (Needs you), or "Autopilot transcription is paused: the GPU could not be used" (Autopilot → Advanced → System) | Run `gpu-check.bat` and follow the fix it prints. Until it is fixed, you can turn on *Allow CPU transcription in Autopilot* in Settings → Advanced → Transcription and GPU. |
| Discovery stopped: quota ("YouTube's daily limit for searches is used up" on Overview) | The YouTube quota share for discovery is used up; it resumes after midnight Pacific. Publishing keeps its reserve. |
| Posts wait in *Needs review* (*Needs your OK*) | Open each one in Posts and approve it (**Approve for YouTube** / **Approve for TikTok**). YouTube can instead use the automatic-publishing permission you turned on; TikTok always needs your OK on each post. |
| YouTube reports Private for a requested Public upload | Check its returned restrictions and YouTube Studio. |
| TikTok: privacy options disabled | Your TikTok app is not audited; only *Only me* is possible, or use *Send to TikTok inbox*. |
| Something is running that should not | **Stop all jobs…** (Autopilot → Overview), then look at Autopilot → Advanced → Jobs and the job logs. |
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
