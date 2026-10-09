# The robot office

How ClipFoundry's robot office works: the five places of the app, the cast and what each robot stands for, the event
feed that moves them, the controls, health, who may watch an upload on YouTube and TikTok, what each integration can
really do, how the scores are made, and the Brain's guards. Written for the version on branch
`claude/project-thread-vw1n9y` (October 2026); the code is the source of truth where they differ.

The robots are a picture of the real job system (`clipfoundry/autopilot/queue.py`). A robot is a responsibility,
not a separate program or AI. Work poses and document handoffs follow actual state and fresh events; off-duty lounge
games, food, drinks and reading are decorative. Nothing in the office drawing starts, approves or finishes work.

## Places

| Place | Address | What is there |
| --- | --- | --- |
| Office | `#/` | The office map, the details panel (overview, a robot, or a room), the activity feed and the bottom bar (Start, Pause, Resume, Stop all, Pause publishing). A list view, room camera and Follow system / Full / Reduced animations are above the map. |
| Team | `#/office/team` | All 25 robots and the Brain Core, read-only, with their job, room and manager. |
| Missions | `#/missions` (+ `/activity`, `/sources`, `/system`, `/jobs`, `/learning`) | The former Autopilot page: Needs you, what it works on, your videos, coming up, Activity, Permissions & sources, and the technical tabs. |
| Clips | `#/clips`, `#/clips/feedback` | The former Library (your videos and their clips) and Test feedback (tester answers and numbers you copy from YouTube Studio or TikTok). |
| Queue | `#/queue/review` (+ `/scheduled`, `/published`, `/history`, `/problems`, `/results`) | The former Posts page: every planned and uploaded post, who it is for and what really happened. |
| Brain | `#/brain` | Searchable saved knowledge and good/bad examples, approved preferences, clip influence, decisions and performance history. |
| Settings | `#/settings`, `/defaults`, `/integrations`, `/advanced` | Integrations holds who watches your uploads, each connection's real capabilities and NVIDIA AI. Advanced holds the Brain's limits and the Dev Log. |
| Robot gallery | `#/dev/robots` | Developer page: every robot in four directions and every pose. Not in the menu; it shows no real activity. |

Old addresses still open the right page and are replaced in place (`frontend/src/router.ts`): `#/home` → `#/`,
`#/library` and `#/projects` → `#/clips`, `#/posts/*` and `#/publish-center/*` → `#/queue/*`, `#/autopilot/*` →
`#/missions/*` (`#/autopilot/overview` → `#/missions/system`).

## The cast

One Director, eight managers and sixteen workers (25 robots), plus the Brain Core, an object in the Brain Room. The
backend registry is `clipfoundry/office/roles.py`; the visual identities are `frontend/src/office/cast.ts` (see
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

### Refined pixel studio

The map now uses **PixiJS 8.22.0**, bundled with the frontend. `StudioScene.ts` draws the office's floors, furniture,
desk screens and Brain Core; `StudioArt.ts` authors the 25 robots from their existing identities. Stepped metal
silhouettes, shaded bodies, different faces and role-specific equipment distinguish the cast. This is drawn pixel
art, with crisp edges and anchored feet; it is not an external image service or a separate AI running each robot.

**GSAP 3.15.0** supplies easing curves for the authored lounge gestures: controller/button presses, moving a game
piece, lifting and tipping a mug, taking a bite, turning a page and resting. The art uses pure `parseEase` functions
driven by the office's own visual clock, without independent animation timelines. These tools are bundled with the
frontend; they do not require a plugin connection, paid account or live graphics service.
GSAP uses its standard no-charge license; the bundled copyright/license notice and links to its terms are in
[third-party-graphics.txt](../frontend/public/third-party-graphics.txt).

`LoungeDecor.ts` authors distinct arcade, café, board-game and sofa areas. Pixi's `BlurFilter` softens decorative
light pools; the static floor, furniture backs and lighting are cached once, while robot outlines stay crisp.
Windows crop the locally bundled `office-art/skyline.png`, an original skyline generated once with native image
generation. Missing optional skyline art leaves procedural glass and the Pixi office available. Ambient arcade
screens, café steam and game pieces are decorative, separate from actual department work lights and health readings.

`OfficeMap.tsx` and `OfficeMotion.ts` supply the renderer with the poses, positions, document handoffs and reactions
derived from the backend feed. Department screen lighting follows actual working roles, and rack indicators follow
the health readings. Rendering does not start jobs or invent measurements. The HTML layer retains one selectable
button per robot and per room, the state icons, details and controls; all 25 roles remain present when idle or paused.

Team cards, robot details and the developer gallery use the same authored robot art through `Portrait.tsx`.
`StudioPortraits.ts` owns one shared offscreen renderer and a bounded cache of rendered frames, copied into ordinary
Canvas portraits. Opening the roster does not create a separate graphics context for each robot. CORE retains its
original portrait drawing.

The Pixi scene loads when the map opens. If its module or graphics initialization fails, the map restores the
original Canvas artwork through `LivingFallback.ts` and shows *Original artwork · new graphics unavailable in this
browser*. This path retains the furnished floor plan, lounge places, seated desks and document transfers, with
simpler Canvas game, food, drink and reading gestures driven by the same controller phases. Robot selection,
details, state indicators and controls remain available. Portraits also retain their original Canvas
artwork when the refined renderer cannot load. Neither renderer needs an account, plugin connection or additional setup.

Follow system uses the operating system's reduced-motion preference; **Full overrides it explicitly**. Reduced
freezes movement and animated drawing while current state information still updates. Hidden tabs and a stale feed
also stop motion. Earlier refined-art evidence remains in
[design/robot-office/retro/README.md](../design/robot-office/retro/README.md); the seated-work and Brain captures are in
[design/robot-office/living/](../design/robot-office/living/). The later recreational lounge evidence belongs in
[design/robot-office/lounge/](../design/robot-office/lounge/), with controlled animation captures labeled separately.

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
  database) or a backlog over 150 events reloads the snapshot instead of replaying. Recent-looking events fetched
  as history do not move robots or replace the current job's owner. Only new events from the last 30 seconds move
  robots; older ones are listed in Activity, never walked. After two missed answers the page says *The
  office is not updating* and marks the map stale.
* Kept: the newest 20,000 events, at most 14 days; reports 90 days; decisions until the data folder is deleted.

### Where a robot stands

* All 25 robots have their own default lounge place and their own department desk. Idle, waiting, retrying, paused
  and unavailable roles stay in the lounge when off duty. Working and reviewing robots walk to their desks and sit;
  a robot with an error remains at its station with an error cue. State icons and selection expose the actual job,
  source/project/clip identifiers, dependencies, blocked reason and next role. No overflow counter hides the cast.
* A manager is `working` while its department has running work and `reviewing` after a real report. COMMAND reviews
  after a decision. A failed job shows `error` on its robot for 30 minutes unless newer work of that robot started.
* When Autopilot is paused or stopped, robots that are not running a job show `paused`. A stopped office may still
  show explicitly decorative recreation; its icons and details continue to say paused, never working.
* A fresh `job_stage` can pass a document between the roles handling the same job, kind and source/clip reference.
  Across jobs, only `hunt_source` → `analyze_source`, `package_clip` → `quality_check` and `regenerate_clip` →
  `package_clip` may transfer a document for the same reference within 30 seconds. A fresh `report` can also pass
  from its worker to its manager. Queued work alone, unrelated references and old events do not create a handoff.
* Both sender and receiver approach the meeting point, face each other, pass one document and show its receipt.
  They then return to the desk or reserved lounge place dictated by the latest state, even if it changed during the
  transfer. Paused or unavailable participants cancel it; Pause, Reduced, a hidden tab or a stale feed clears it.
  After a hidden tab, pause or lost connection, the map waits for a fresh authoritative snapshot and recovers each
  running job's current role before accepting the next handoff. Missed transfers are not replayed, and an older
  snapshot or historical stage cannot move ownership backward. These walks never delay durable jobs.
* A fresh `decision` gives COMMAND an approved, rework or rejected reaction. Progress bars show only progress a job
  measured.
* Follow system honors the operating system’s motion preference. Full explicitly overrides reduced motion.
  Reduced stops movement; truthful state icons and the list view remain. The saved choice survives reloads.

The **Office camera** selects the whole office or a closer view of any room, including the lounge and Brain Room.
It changes only the view; robot selection and the details panel still use the same actual state.

### Off-duty lounge life

The lounge has 29 activity places: five arcade cabinets, four café places, eight board-game seats, eight sofa
places for reading, drinks, snacks or rest, and four extra guest places. The first 25 give the cast stable individual
homes. `LoungeLife.ts` reserves destinations exclusively, holding both old and new places until arrival so two robots
cannot claim the same spot. Each identity has its own phased routine; after roughly 15–28 seconds of visible full
animation it can visit another free activity. At most two recreational visitors walk at once, along furniture-aware
routes. Activity names are identified as *lounge animation*, while the state badge still comes from the backend.

Idle, waiting and retrying roles may take breaks. The stopped office also permits recreation for its otherwise
paused off-duty roles, as requested by the owner. An individually paused role while the office is running, or an
unavailable role, does not perform recreational gestures or rotate activities; it can finish returning to its
reserved resting place. Actual work and document handoffs preempt recreation as soon as their state/event arrives,
release the lounge reservation and preserve the same robot identity and real job references. A completed worker
can return to a free lounge place afterward.

Global Pause, Reduced, hidden tabs and a stale feed freeze recreational movement and gestures. Reduced and Pause
restore the stable home arrangement with a still frame; hidden/stale views do not catch up missed leisure time on
return. Full still overrides the operating system's reduced-motion preference. Recreation never sends API writes,
starts a job, changes progress, files a report or creates a document handoff.

CORE is a decorative neural sculpture. Its slow **Standby** orbit means the office display is powered, not that a
job is running. **Processing** uses brighter, faster neural cues only while the snapshot reports Brain evaluation
or working Brain roles, or after a fresh Brain evaluation, lookup or strategy-change event. Pausing the Brain or
office freezes the sculpture; Reduced freezes its drawing without changing the reported state. A stale feed shows
**Offline**, dims CORE and stops motion. Selecting CORE opens the Brain workspace. These effects are not measured
learning progress, result quality or video-processing time.

## Controls

`POST /api/office/control` with `start`, `pause`, `resume`, `stop`, `pause_publishing` or `resume_publishing`. Only
the actions that fit the state are accepted (Start when stopped, Pause and Stop all when running, Resume and Stop all
when paused). Each one calls the same code as the Missions buttons, so no check is skipped:

* **Pause:** running steps finish, nothing new starts. **Resume** continues.
* **Stop all:** queued work is canceled and held until you start again (`queue.STOP_ALL`).
* **Pause publishing:** clips are still found, made and checked; nothing new is uploaded until you resume.

## Health

`GET /api/office/health` (`clipfoundry/office/health.py`): the scheduler, the oldest waiting job, discovery, the
GPU, ffmpeg, disk space, the database, the accounts, audience incidents and API quotas, each Healthy, Degraded, Error
or Unknown with the reason and what to do. A GPU error newer than the last GPU transcription is Error; a CPU fallback
is Degraded. No connected account is information, not a problem. Discovery is Error when Autopilot is on with nowhere
to look, and Degraded when the last search is more than twice its period overdue. The overall status is the worst
reading that counts. When the office loses its connection, every reading shows *Unknown — not updating* instead of
its last value.

## Who may watch an upload

One audience policy applies to manual uploads, Autopilot, retry and recovery. Defaults affect new posts only.
Public requires explicit confirmation; old selected/owner-only stamps and scheduled Private visibility remain.
Legacy public plans held by the prior migration are not silently revived.

* YouTube: Public uploads require an explicit Public audience. Standing automation is bound to the connected
  channel, visibility and audience revision; public automation additionally requires the owner’s recorded audit
  confirmation. Eligible exact files upload at their due time, without `publishAt`. Returned Private restrictions
  are reported as restricted, never public delivery. Private selected-viewer sharing remains a Studio step.
* TikTok: Everyone requires an eligible audited app, fresh creator options and per-post consent. No privacy is
  preselected. Inbox drafts and ready-to-post packages remain honest handoffs until the owner finishes posting.
* Results distinguish requested visibility, the API’s answer and the owner’s confirmation. Public and selected
  cohorts cannot reuse each other’s strategies or timing data. Unsupported/unconfirmed results do not drive learning.

[Platform requirements and the blocked official-documentation recheck](PLATFORM_CAPABILITIES.md).

## What each integration can do

Settings → Integrations shows, per connection, three separate things: whether this version implements a capability,
whether an account or key is connected, and whether the capability is available now. A connected account does not
make every capability available, and signing in never grants downloads or full analytics. The registry is
`clipfoundry/office/capabilities.py` (`GET /api/integrations` returns it with the cards). Each connected account's
card has **Test connection** (`POST /api/integrations/youtube/test` or `/tiktok/test`): one read with the stored
account (YouTube `channels.list`, 1 quota unit; TikTok `creator_info`, or user info without Direct Post) that never
uploads or changes anything. The card shows the last successful check, a failed check's reason and what to do, and a
platform's wait (*Rate limited until*) read from where the code records it:

| Platform | Capability | State | What it means |
| --- | --- | --- | --- |
| YouTube | Finds videos | Implemented | Popular and searched videos through the YouTube Data API (your connected channel or an API key). |
| YouTube | Reads titles and numbers | Implemented | Title, channel, duration, views, likes and comments as YouTube reports them. |
| YouTube | Transcript | On this PC | Made on this PC with Whisper on your GPU; YouTube captions are not downloaded. |
| YouTube | Gets the video file | Implemented | A pasted link or a found video is downloaded only where access is allowed; your connection to YouTube does not grant downloads. |
| YouTube | Uploads | Implemented | Resumable upload through the YouTube Data API. |
| YouTube | Who can watch | Implemented | Explicit Public or Private. Private invitations stay in YouTube Studio (no API for that). |
| YouTube | Your OK | Implemented | Your OK on each post, or the account/visibility-bound automatic-upload permission. |
| YouTube | Checks the result | Implemented | Upload processing and the returned privacy are read back after each upload. |
| YouTube | Results | Needs platform approval | Views, likes and comments are shown; using them for learning needs Google's derived-metrics approval. Average percentage viewed needs the Analytics scope and may be empty for a small private group. |
| YouTube | Limits | Implemented | Daily API quota units (an upload costs about 1,600), counted on this PC. |
| TikTok | Finds videos | Implemented | Links to public TikTok videos found by web search (needs a Tavily key); TikTok has no open discovery API for this. |
| TikTok | Reads titles and numbers | Implemented | Creator and title from TikTok's public embed endpoint; no view counts. |
| TikTok | Transcript | On this PC | Made on this PC with Whisper. |
| TikTok | Gets the video file | Implemented | Only where the video is accessible to the link importer; nothing is bypassed. |
| TikTok | Uploads | Needs platform approval | Direct Post to Everyone, followers or friends needs an eligible TikTok app audit, and TikTok's guidelines turn away personal tools and apps that repost other platforms' videos, so expect a refusal. Inbox drafts also need TikTok to approve the app (at most 5 waiting). Otherwise ClipFoundry prepares a ready-to-post package that you post in the TikTok app. |
| TikTok | Who can watch | Needs platform approval | Everyone for Public, or followers/friends for selected viewers (eligible audited apps); an unaudited app can only post 'Only me', which is staging, not a test. |
| TikTok | Your OK | Implemented | Your OK on every post (TikTok requires it). |
| TikTok | Checks the result | Implemented | The post's publish status is read back; follower-only posts may not return a link. |
| TikTok | Results | Limited by the platform | TikTok's video list API covers public posts only, so results of follower-only posts are unavailable here; enter them in Clips → Test feedback. |
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
viral. Each one stores its parts with their weights, the parts that had no data with the reason, its coverage and its
confidence.

* **Missing data** (`autopilot/trends.py: combine`). Every part that applies to a video counts. A part without data
  is neither left out nor counted as 0: it counts as the neutral 0.5 and is listed as missing with its reason.
  * *Coverage* = Σ weight of the parts with data ÷ Σ weight of the parts that apply. In the Source Score the trend
    part counts with the Trend Score's own coverage.
  * *Score* = 100 × Σ weight × value ÷ Σ weight over the parts that apply, a part without data counting as 0.5.
    For the Trend Score that is 100 × (c × weighted average of the parts with data + (1 − c) × 0.5) with coverage
    c, so it stays between 50 × (1 − c) and 50 + 50 × c and one or two numbers cannot rank a video high: a
    ten-minute-old web result without views (coverage 31%) scores at most 65.5 (it scored 99.7 before this rule).
    The Source Score's trend part is that already shrunk Trend Score.
  * *Confidence* (`trends.confidence`), in words, never as a percentage: **high** with coverage of at least 75% and
    two readings at least 20 minutes apart; **medium** with coverage of at least 50% and at least one reading of the
    numbers; **low** otherwise. A reading is a timestamped set of the platform's numbers; readings less than 20
    minutes apart count once.
  * Stored with the score: `trend_signals.components` and `sources.components` hold the parts with data and an
    `evidence` entry (weight 0) with `coverage`, `confidence`, `readings` and `missing` (part → reason). The Trend
    Score's notes name the missing parts and the evidence in words.
* **Trend Score** (`trends.score`). Weights: velocity 0.35, recency 0.18, engagement 0.12, acceleration 0.10, live
  0.10 (live streams only; it does not apply to a recording), recurrence 0.10, size 0.05.
  * *Velocity* is observed only from two readings at least 20 minutes apart (change in views ÷ hours between them).
    Without two readings it is views ÷ hours since upload, labeled *average since upload* (an estimate).
  * *Acceleration* needs a third reading at least 20 minutes before the previous one.
  * *Engagement* is (likes + 2 × comments) ÷ views; with 0 views (a measured zero) there is no rate yet, so it is
    missing. *Recurrence* counts other creators whose titles share one of the two main topic words; a title without
    topic words leaves it missing.
  * YouTube numbers without Google's derived-metrics approval are not scored at all: the score is YouTube's own
    order (`PLATFORM_ORDER`, one part with weight 1). A video without a list position has no data for it and gets
    the neutral 50 with low confidence.
* **Clip Opportunity Score** is the **Source Score** (`autopilot/scout.py: score_source`), computed before anything
  is downloaded: trend 0.35, clip potential 0.30 (expected strong clips from the video's length and the yield
  learned per category; missing while the length is unknown and for live streams, which are judged while they run),
  creator history 0.15 (missing until a video of this creator or category was finished), topic results 0.15 (missing
  until your posts on the topic have results; it does not apply with learning off), freshness 0.10 (missing without
  an upload time, and for YouTube data without the derived-metrics approval), live 0.10 (live streams only). Its
  confidence uses its own coverage and the trend signal's readings. It decides which videos are worth downloading
  and transcribing; the expected number of strong clips still decides whether a video is worth reading at all.
* After transcription each moment gets its **Clip Score** (Viral Potential with eleven factors and the hook →
  context → payoff structure), and each planned post a **Final Opportunity Score** (docs/AUTOPILOT.md#scores).

Discovery also applies configurable audience/topic terms, exclusions, source-score floor, language evidence and
complete-story screening. Metadata matches and inferred clip potential are labeled estimates; a US search region
is not evidence of US viewers. Automatic weak/repetitive/non-speech live sources are declined; explicit user and
curated inputs remain available. After transcription, automatic clips need a hook, context and payoff (a heuristic).

Final-check failures return to bounded responsible-stage repair: media to SPLICE, captions to GLYPH, safe cut-plan
repair to STORY, grounded metadata to QUILL. At most two repair attempts; access, ownership and consent failures
remain blocks. Stream timestamp checks detect offset/length problems, not semantic lip synchronization. Missing
audio is detected before Whisper; video-only live segments are saved and skipped, later sound can resume, and an
entirely video-only source fails visibly without repeating the impossible operation. Final stitching of mixed
recordings preserves later audio by adding silent tracks only for missing-audio segments; video stays stream-copied.

[Measured processing stages and server advice](PERFORMANCE.md).

Not implemented from the brief: creator-relative baselines beyond the learned yield per creator, novelty and search
signals, and a preview-based screening of hook and payoff before the download (moments are judged from the
transcript after it).

## The Brain

`#/brain`, `autopilot/knowledge.py`, `/api/brain/knowledge`, plus performance in `autopilot/brain.py`.
Documents (TXT/MD/CSV/JSON/DOCX), instructions and skill guides stay searchable on this PC. Good/bad example
clips (MP4/MOV/WebM) can carry hook, pacing, captions and storytelling labels. Original files are bounded and
never executed. Saved typed preferences require explicit revision approval before later Autopilot blueprints use
them; editing invalidates approval. Topic tags scope the lookup. Text alone does not fine-tune a model or create
arbitrary behavior. Approved controls cover caption style/position/emphasis and safe cuts versus continuous pacing.

Knowledge can be edited, disabled, deleted or exported; original assets have separate downloads. Each later clip
keeps the approved revision, feature labels, settings changed and before/after values in its influence record.
Deleting a reference stops future use while retaining that clip’s explanation. The UI’s Try a decision is explicitly
only a lookup preview. The upload tests also build and persist a later real blueprint to prove actual influence.
Teaching examples never enter posting-performance tables.

The performance evidence remains available through Clips → Test feedback and the Brain’s Performance tab.

* **Evidence with provenance.** Each observation is *Platform (API)*, *Your import* (CSV or typed in from YouTube
  Studio or TikTok) or *Tester feedback (self-reported)*. A missing number stays missing; a measured zero stays
  zero. Imports are previewed, then imported once; the same reading entered twice counts once, and a correction
  keeps the earlier values. One answer per tester per clip. Mirrored YouTube API readings follow the 30-day rule.
* **Audiences kept apart.** Results are grouped by platform, audience (selected viewers, only you, confirmed public
  posts, or *unconfirmed*: meant for your viewers but they cannot watch it yet, such as a Private upload nobody was
  invited to or a TikTok package not posted yet) and audience-group version. Only eligible selected-viewer or confirmed-public results may change
  a strategy, and only for that platform, audience and group. A post counts as mature 48 hours after your viewers could watch it (the upload,
  or later when you said you shared it or linked the post you made yourself).
* **Guards.** A strategy changes only with at least 30 mature clips from at least 5 videos in one group, each with
  at least `brain_min_views` views, and at least 20 clips on each side of the comparison (`MIN_ARM`); identical
  results on a side count as inconclusive. It moves at most 10% per update (`brain_min_clips` ≥ 30,
  `brain_max_step` ≤ 0.10, Settings → Advanced → Brain); it waits for 10 clips with results of the new setting before
  moving again, and rolls back when later results are worse. Each platform keeps its own strategy and rolls back on
  its own; a learned clip length is used only when every enabled platform learned the same value. You can pause it,
  roll back a change or reset it, and the same results cannot undo your rollback or reset (the next change waits for
  10 new clips). CORE cannot override privacy, credentials, cost limits, stop controls or the safety checks.
* **Known limits.** "Views" are plays, not people: 10 plays by 2 people pass the views threshold, and the same 3
  testers rating many clips count as many results. The count needs 5 different videos, but one video can still
  supply most of the clips. Both are product decisions (a rule for how many different people), not yet made.
* **What it changes.** The clip length the next videos Autopilot starts are cut for. The older learner
  (`learner.py`, posting times, styles and score weights) follows the same 30-post, 10%, views and 5-video guards,
  now requires 48-hour mature readings and explicit group identity. It rejects
  cached styles, weights and posting hours when the configured audience cohort changes.

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
