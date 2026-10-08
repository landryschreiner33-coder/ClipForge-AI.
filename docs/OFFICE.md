# The robot office

How ClipFoundry's robot office works: the five places of the app, the cast and what each robot stands for, the event
feed that moves them, the controls, health, who may watch an upload on YouTube and TikTok, what each integration can
really do, how the scores are made, and the Brain's guards. Written for the version on branch
`claude/project-thread-vw1n9y` (October 2026); the code is the source of truth where they differ.

The robots are a picture of the real job system (`clipfoundry/autopilot/queue.py`). A robot is a responsibility,
not a separate program or AI: it walks because a real job started, carries a card because a real job finished, and
rests because nothing of its kind is running. Nothing in the office starts, approves or finishes work.

## The five places

| Place | Address | What is there |
| --- | --- | --- |
| Office | `#/` | The office map, the details panel (overview, a robot, or a room), the activity feed and the bottom bar (Start, Pause, Resume, Stop all, Pause publishing). A list view and Reduce animations are above the map. |
| Team | `#/office/team` | All 25 robots and the Brain Core, read-only, with their job, room and manager. |
| Missions | `#/missions` (+ `/activity`, `/sources`, `/system`, `/jobs`, `/learning`) | The former Autopilot page: Needs you, what it works on, your videos, coming up, Activity, Permissions & sources, and the technical tabs. |
| Clips | `#/clips`, `#/clips/feedback` | The former Library (your videos and their clips) and Test feedback (tester answers and numbers you copy from YouTube Studio or TikTok). |
| Queue | `#/queue/review` (+ `/scheduled`, `/published`, `/history`, `/problems`, `/results`) | The former Posts page: every planned and uploaded post, who it is for and what really happened. |
| Settings | `#/settings`, `/defaults`, `/integrations`, `/advanced` | Integrations holds who watches your uploads, each connection's real capabilities and NVIDIA AI. Advanced holds the Brain's limits and the Dev Log. |
| Robot gallery | `#/dev/robots` | Developer page: every robot in four directions and every pose. Not in the menu; it shows no real activity. |

Old addresses still open the right page and are replaced in place (`frontend/src/router.ts`): `#/home` → `#/`,
`#/library` and `#/projects` → `#/clips`, `#/posts/*` and `#/publish-center/*` → `#/queue/*`, `#/autopilot/*` →
`#/missions/*` (`#/autopilot/overview` → `#/missions/system`).

## The cast

One Director, eight managers and sixteen workers (25 robots), plus the Brain Core, an object in the Brain Room. The
backend registry is `clipfoundry/office/roles.py`; the drawings are `frontend/src/office/cast.ts` (see
[design/robots/README.md](../design/robots/README.md)). `tests/test_office.py` fails if the two lists differ.

| Room | Manager | Workers (the job kinds and stages they stand for) |
| --- | --- | --- |
| Boss Hub | COMMAND, Director | Records the decision at four checkpoints: source, clip, quality check, upload. |
| Discover | TRACKER (`trend_scan`) | RADAR (searches, feeds, live checks), ARCHIVE (pasted links, live recording, transcription) |
| Analyze | VECTOR | PULSE (trend scoring), GAVEL (`rights_check`), BOOST (`analyze_source` scoring) |
| Clip Studio | FRAME | SPARK (moments), STORY (clip plans), SPLICE (rendering, re-renders) |
| Caption | SCRIPT | GLYPH (captions), QUILL (`package_clip`: titles, descriptions, hashtags) |
| Schedule | CLOCK (`schedule_tick`) | none: the scheduler is CLOCK's own job, and no worker is invented to fill a chair |
| Upload Dock | HARBOR | LOCK (audience check before upload), DOCK (`publish`) |
| System | SWITCH | CHECK (`quality_check`, the Final Quality Gate), PATCH (maintenance, self-test) |
| Brain Room | CURATOR | METRIC (result readings), SYNAPSE (`learn`: compares results) |

`roles.role_for(kind, stage)` maps every job (and the stage it reports) to exactly one role.

### Reports and decisions

* **Reports.** When a job finishes or fails, `office/feed.report()` files a short report from the worker to its
  manager (`office_reports`): what was done, the result and, on failure, the fix. Routine runs that change nothing
  (the minute-by-minute schedule check, an empty folder scan) do not file one. The manager shows *reviewing* for a
  few seconds after a real report.
* **Decisions.** `feed.decide()` records COMMAND's decision (`office_decisions`) where the code already decides, with
  the rules' version and the evidence: `source` (hunter.py: use or skip a video), `clip` (keep or reject a moment),
  `qc` (gate.py: pass, render again, or fail), `upload` (publisher.py: approved, held or rejected). The deterministic
  checks make the decision; the record says which one and why. The same decision for the same subject is not
  recorded twice.

## The event feed

Contract (`clipfoundry/office/feed.py`, `/api/office`, `frontend/src/office/useOffice.ts`):

* `GET /api/office/snapshot` returns the current truth: `cursor` (the newest event id), `run` (`state` running,
  paused or stopped, `label`, the allowed `actions`, `publishing_paused`), `roles` (each robot's `state`, its current
  `task` with a measured `progress` or none, counts, the latest `error` and `last` report), `health`, `audience`
  (the footer line), `next_upload`, `today`, `needs_you` and `brain`.
* `GET /api/office/events?after=<cursor>&limit=` returns the events after the cursor, oldest first, with `cursor`,
  `latest`, `more`, `reset` and `server_time`. Event types: `job_started`, `job_stage`, `job_done`, `job_failed`,
  `job_retry`, `job_waiting`, `job_canceled`, `report`, `decision`, `control`, and the Brain's `brain_observation`,
  `brain_evaluation`, `brain_evaluated`, `strategy_changed`, `strategy_rolled_back`, `brain_lookup`.
* The page reads the snapshot, then polls the events every 1.5 s (8 s in a hidden tab) and re-reads the snapshot
  every 10 s. Duplicate ids are dropped. `reset` (the cursor is older than the kept history, or from another
  database) or a backlog over 150 events reloads the snapshot instead of replaying. Only events from the last 30
  seconds move robots; older ones are listed in Activity, never walked. After two missed answers the page says *The
  office is not updating* and marks the map stale.
* Kept: the newest 20,000 events, at most 14 days; reports 90 days; decisions until the data folder is deleted.

### Where a robot stands

* A worker stands at its station while it is `working`, `waiting`, `retrying`, `error` or `reviewing`, and when it is
  `unavailable` (DOCK, LOCK and HARBOR when no platform can upload). Idle or paused workers go to the Lounge (six
  places; the rest are counted there). Managers and COMMAND stay at their stations.
* A manager is `working` while its department has running work and `reviewing` after a real report. COMMAND reviews
  after a decision. A failed job shows `error` on its robot for 30 minutes unless newer work of that robot started.
* When Autopilot is paused or stopped, robots that are not running a job show `paused`.
* A fresh `report` event makes the worker carry a card to its manager, who then reviews; a fresh `decision` gives
  COMMAND an approved, rework or rejected reaction. Progress bars show only progress a job measured.
* Reduce animations (and the operating system's reduced-motion setting) stops all movement: robots are drawn at their
  places in their state, and the list view shows the same information as text.

## Controls

`POST /api/office/control` with `start`, `pause`, `resume`, `stop`, `pause_publishing` or `resume_publishing`. Only
the actions that fit the state are accepted (Start when stopped, Pause and Stop all when running, Resume and Stop all
when paused). Each one calls the same code as the Missions buttons, so no check is skipped:

* **Pause:** running steps finish, nothing new starts. **Resume** continues.
* **Stop all:** queued work is canceled and held until you start again (`queue.STOP_ALL`).
* **Pause publishing:** clips are still found, made and checked; nothing new is uploaded until you resume.

## Health

`GET /api/office/health` (`clipfoundry/office/health.py`): the scheduler, the oldest waiting job, the GPU, ffmpeg,
disk space, the database, the accounts, audience incidents and API quotas, each Healthy, Degraded, Error or Unknown
with the reason and what to do. The overall status is the worst reading; Unknown appears only when nothing is worse.

## Who may watch an upload (selected audience)

One policy for every upload path (`clipfoundry/publish/audience.py`): Autopilot, your own uploads from Prepare post,
retries, resumed uploads, and posts planned before this version.

* **Intents.** *Selected viewers* (the default), *Only me* (staging) and *Keep clips on this PC*. Public, unlisted
  ("anyone with the link") and TikTok's "Everyone" are blocked everywhere. Posts planned as public before this
  version are held, never widened or narrowed silently.
* **YouTube: Private with invited viewers.** Every upload is Private and never carries `publishAt`, so YouTube never
  makes it public later. You share it in YouTube Studio with the people you choose; the YouTube Data API has no call
  for those invitations, so the post shows *Awaiting viewer invitations* until you press *I shared it*. That is your
  confirmation, not a platform check. Comments are not promised on private videos.
* **TikTok: approved followers.** Posts go to your Followers (or Friends) on a private account. Only an app TikTok
  has audited may Direct Post to those groups. An unaudited app can only post *Only me*, which is staging for you and
  is never shown as delivered to viewers. Without an eligible route the clip becomes a ready-to-post package
  (*Ready for you to post on TikTok*) that you post in the TikTok app.
* **Confirmation.** Before any upload you confirm, once per platform in Settings → Integrations, how your audience
  works. *My viewers changed* makes earlier approvals stale. Every approval is bound to the exact file, the text and
  the audience stamp (policy version and group version, `scheduler.APPROVAL_SCHEME = 3`), and automatic YouTube
  uploads need the Private-only permission (consent version 2).
* **Delivery truth.** Each post says what really happened: uploaded, only you can see it, awaiting invitations,
  audience set up (you confirmed), restricted audience (platform confirmed), ready to post on TikTok, awaiting viewer
  results, blocked, failed, retrying or *Upload not confirmed*. If the platform reports a wider audience than asked,
  publishing stops for that platform until you check it (*I checked it*).
* ClipFoundry never invites people, approves followers or changes an account's privacy.

## What each integration can do

Settings → Integrations shows, per connection, three separate things: whether this version implements a capability,
whether an account or key is connected, and whether the capability is available now. A connected account does not
make every capability available, and signing in never grants downloads or full analytics. The registry is
`clipfoundry/office/capabilities.py` (`GET /api/integrations` returns it with the cards):

| Platform | Capability | State | What it means |
| --- | --- | --- | --- |
| YouTube | Finds videos | Implemented | Popular and searched videos through the YouTube Data API (your connected channel or an API key). |
| YouTube | Reads titles and numbers | Implemented | Title, channel, duration, views, likes and comments as YouTube reports them. |
| YouTube | Transcript | On this PC | Made on this PC with Whisper on your GPU; YouTube captions are not downloaded. |
| YouTube | Gets the video file | Implemented | A pasted link or a found video is downloaded only where access is allowed; your connection to YouTube does not grant downloads. |
| YouTube | Uploads | Implemented | Resumable upload through the YouTube Data API. |
| YouTube | Who can watch | Implemented | Private only. You invite your viewers in YouTube Studio (no API for that). |
| YouTube | Your OK | Implemented | Your OK on each post, or the automatic-upload permission (Private only). |
| YouTube | Checks the result | Implemented | Upload processing and the returned privacy are read back after each upload. |
| YouTube | Results | Needs platform approval | Views, likes and comments are shown; using them for learning needs Google's derived-metrics approval. Average percentage viewed needs the Analytics scope and may be empty for a small private group. |
| YouTube | Limits | Implemented | Daily API quota units (an upload costs about 1,600), counted on this PC. |
| TikTok | Finds videos | Implemented | Links to public TikTok videos found by web search (needs a Tavily key); TikTok has no open discovery API for this. |
| TikTok | Reads titles and numbers | Implemented | Creator and title from TikTok's public embed endpoint; no view counts. |
| TikTok | Transcript | On this PC | Made on this PC with Whisper. |
| TikTok | Gets the video file | Implemented | Only where the video is accessible to the link importer; nothing is bypassed. |
| TikTok | Uploads | Needs platform approval | Direct Post to your followers needs TikTok's app audit. Without it ClipFoundry sends a draft to your TikTok inbox or prepares a ready-to-post package. |
| TikTok | Who can watch | Needs platform approval | Followers or friends on a private account (audited apps); an unaudited app can only post 'Only me', which is staging, not a test. |
| TikTok | Your OK | Implemented | Your OK on every post (TikTok requires it). |
| TikTok | Checks the result | Implemented | The post's publish status is read back; follower-only posts may not return a link. |
| TikTok | Results | Unsupported by the platform | TikTok's video list API covers public posts only, so results of follower-only posts are unavailable here; enter them in Clips → Test feedback. |
| TikTok | Limits | Implemented | TikTok's posting caps per creator per day, as TikTok reports them. |
| Web search (Tavily) | Finds videos | Implemented | Tavily web search finds public video links and the originals behind clips (paid credits beyond the free plan; capped by your monthly budget). |
| Web search (Tavily) | Reads titles and numbers | Implemented | Only what the search result says; no statistics. |
| Web search (Tavily) | Gets the video file | Implemented | Through the link importer, where accessible. |
| Web search (Tavily) | Limits | Implemented | Free credits per month, then your discovery budget ($0 by default). |
| Wikimedia Commons | Finds videos | Implemented | Wikimedia Commons videos with free licenses. |
| Wikimedia Commons | Reads titles and numbers | Implemented | License, author and credit line as the library records them. |
| Wikimedia Commons | Gets the video file | Implemented | Direct download from upload.wikimedia.org. |
| Your folders | Finds videos | On this PC | Your videos folder and any watch folders you add. |
| Your folders | Gets the video file | On this PC | The files themselves. |
| Live streams | Finds videos | Implemented | Live streams of watched YouTube channels and stream links you add. |
| Live streams | Gets the video file | Implemented | HTTP/HLS recording within a time and size limit; protected streams are skipped. |
| Twitch | Finds videos | Not in this version | No Twitch connector in this version. A public Twitch link you paste can still be imported where the link importer supports it. |
| Kick | Finds videos | Not in this version | No Kick connector in this version. A public Kick link you paste can still be imported where the link importer supports it. |
| Reddit | Finds videos | Not in this version | No Reddit connector in this version. A public Reddit link you paste can still be imported where the link importer supports it. |
| X | Finds videos | Not in this version | No X connector in this version. A public X link you paste can still be imported where the link importer supports it. |
| Instagram | Finds videos | Not in this version | No Instagram connector in this version. A public Instagram link you paste can still be imported where the link importer supports it. |
| Podcasts | Finds videos | Not in this version | No podcast connector in this version. A public podcast link you paste can still be imported where the link importer supports it. |
| Google Trends | Finds videos | Unsupported by the platform | Google Trends has no supported public API; ClipFoundry does not scrape it. Trend signals come from the platforms' own numbers. |

## Scores

All scores are 0-100 ranking estimates made by ClipFoundry, not platform numbers and not probabilities of going
viral. Each one lists its parts, their weights and what was not counted.

* **Trend Score** (`autopilot/trends.py: score`). Weights: velocity 0.35, recency 0.18, engagement 0.12, acceleration
  0.10, live 0.10, recurrence 0.10, size 0.05. Only the parts with data count, and the total is divided by their
  weights; a missing velocity, engagement or recency is named under the score.
  * *Velocity* is observed only from two readings at least 20 minutes apart (change in views ÷ hours between them).
    Without two readings it is views ÷ hours since upload, labeled *average since upload* (an estimate).
  * *Acceleration* needs a third reading at least 20 minutes before the previous one.
  * YouTube numbers without Google's derived-metrics approval are not scored at all: the score is YouTube's own
    order (`PLATFORM_ORDER`).
* **Clip Opportunity Score** is the **Source Score** (`autopilot/scout.py: score_source`), computed before anything
  is downloaded: trend 0.35, clip potential 0.30 (expected strong clips from the video's length and the yield
  learned per category), creator history 0.15, topic results 0.15, freshness 0.10, live 0.10. It decides which
  videos are worth downloading and transcribing.
* After transcription each moment gets its **Clip Score** (Viral Potential with eleven factors and the hook →
  context → payoff structure), and each planned post a **Final Opportunity Score** (docs/AUTOPILOT.md#scores).

Not implemented from the brief: creator-relative baselines beyond the learned yield per creator, novelty and search
signals, and a preview-based screening of hook and payoff before the download (moments are judged from the
transcript after it).

## The Brain

`clipfoundry/autopilot/brain.py`, `/api/brain`, Clips → Test feedback, Missions → Learning.

* **Evidence with provenance.** Each observation is *Platform (API)*, *Your import* (CSV or typed in from YouTube
  Studio or TikTok) or *Tester feedback (self-reported)*. A missing number stays missing; a measured zero stays
  zero. Imports are previewed, then imported once; the same reading entered twice counts once, and a correction
  keeps the earlier values. One answer per tester per clip. Mirrored YouTube API readings follow the 30-day rule.
* **Audiences kept apart.** Results are grouped by platform, audience (selected viewers, only you, earlier public
  posts) and audience-group version. Only selected-viewer results may change a strategy, and only for that group.
* **Guards.** A strategy changes only with at least 30 mature clips (48 hours old) from at least 5 videos in one
  group, with at least 10 on each side of the comparison; it moves at most 10% per update
  (`brain_min_clips` ≥ 30, `brain_max_step` ≤ 0.10, Settings → Advanced → Brain); it waits for results of the new
  setting before moving again, and rolls back when later results are worse. You can pause it, roll back a change or
  reset it. CORE cannot override privacy, credentials, cost limits, stop controls or the safety checks.
* **What it changes.** The clip length the next videos Autopilot starts are cut for. The older learner
  (`learner.py`, score weights) follows the same 30-post and 10% guards.

## Optional NVIDIA AI

Off by default and never needed (`clipfoundry/pipeline/nvidia.py`, Settings → Integrations → NVIDIA AI). It may only
score and title clip candidates from short transcript excerpts; the deterministic code keeps every decision. Setup is
in the [README](../README.md#optional-nvidia-ai). Guards: explicit opt-in, development mode only for work you start
(Autopilot stays local), daily request, token and (production) spending caps reserved atomically before each
request, https to the configured host only with no redirects, `Retry-After` honored, a circuit breaker, one
formatting repair, a 30-day answer cache, and local analysis whenever a request is not sent or fails.

## Development history

`AI_CHANGELOG.md` (what changed per checkpoint), `AI_HANDOFF.md` (where things stand) and
`.clipfoundry/ai-change-log.jsonl` (one JSON object per checkpoint: `at`, `tool`, `model`, `branch`, `base`,
`result`, `checkpoint`, `summary`, `files`, `tests`, `verified`, `not_verified`). Settings → Advanced → Dev Log shows
the JSONL read-only. Runtime robot activity is not development history and is never written there.
