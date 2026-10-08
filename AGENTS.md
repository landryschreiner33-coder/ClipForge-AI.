# ClipFoundry: guide for AI assistants

Read this before changing anything. It says what the project is, where it stands, how to run and test it, and the
rules every change must keep. Deeper documents: [README.md](README.md) (features, architecture),
[INSTALL.md](INSTALL.md) (Windows setup), [docs/AUTOPILOT.md](docs/AUTOPILOT.md) (Autopilot design),
[docs/IMPLEMENTATION_STATUS.md](docs/IMPLEMENTATION_STATUS.md) (requirement matrix, open plan, test log),
[docs/PLATFORM_CAPABILITIES.md](docs/PLATFORM_CAPABILITIES.md) (what YouTube/TikTok allow),
[e2e/README.md](e2e/README.md), [docs/OFFICE.md](docs/OFFICE.md) (robot office, selected audience, capability matrix,
Brain).

**Before you change anything, also read [AI_HANDOFF.md](AI_HANDOFF.md)** (where the newest work stands) and the top of
[AI_CHANGELOG.md](AI_CHANGELOG.md). After a meaningful checkpoint, add an entry to both `AI_CHANGELOG.md` and
`.clipfoundry/ai-change-log.jsonl` (what changed, the tests you actually ran, what you could not verify; no secrets,
no transcripts of conversations) and refresh `AI_HANDOFF.md`.

## What it is

ClipFoundry (repo name ClipForge-AI) is a **local-first, single-user desktop tool**. It turns long videos into
captioned 9:16 short clips for TikTok, YouTube Shorts and Reels. It is not a SaaS: it has no accounts, no cloud
rendering, and a local SQLite database and files. The owner runs it on a **Windows PC with an NVIDIA RTX 3050**.

```
VIDEO → TRANSCRIPT → BEST MOMENTS → CLIPS → 9:16 → CAPTIONS → HOOKS → EXPORT
```

There are two ways to use it:

* **Manual:** drop in a video, get ranked clips, edit, export, or publish through the official APIs.
* **Autopilot:** 12 background workers on a durable SQLite job queue. Every 3 hours they look for videos the user may
  use (own content, recorded creator agreements, CC BY, public domain), clip and package them, check the final file,
  schedule posts (9:00-21:00 America/Chicago) and publish them: YouTube automatically once the user has given that
  permission, TikTok only after the user's OK on each post. Then they learn from the real results. Nothing asks the
  user about single videos: what is not covered is skipped and explained in the Activity log.

## Stack

| Part | Details |
| --- | --- |
| Backend | Python 3.11/3.12, FastAPI + uvicorn, SQLite (`clipfoundry/db.py`), served at http://127.0.0.1:8765 |
| Media | ffmpeg (NVENC or x264), OpenCV (YuNet face model), PySceneDetect |
| Transcription | faster-whisper / CTranslate2 on CUDA 12 (cuBLAS + cuDNN 9 from pip, `requirements-gpu.txt`) |
| AI scoring | Local heuristic by default. Optional: Ollama / LM Studio / OpenAI-compatible, Claude API (paid, off by default). |
| Frontend | React 18 + Vite 5 + TypeScript in `frontend/src`. **The built `frontend/dist` is committed**, so users don't need Node. |
| Publishing | YouTube Data API v3 (OAuth PKCE, resumable upload); TikTok Content Posting API (Direct Post or inbox draft). Tokens are encrypted with Windows DPAPI (`secure.py`). |
| Tests | pytest (`tests/`), Playwright browser tests (`e2e/`, read-only, run against the user's local app) |

## Where the code is

```
clipfoundry/
  __main__.py      CLI: app, `process <video>`, `gpu-check`, `workers`
  api.py           REST API + serves frontend/dist
  config.py        settings, defaults and ranges (DEFAULT_SETTINGS, validate_settings)
  db.py            SQLite schema (SCHEMA, JSON_FIELDS, ADDED_COLUMNS for migrations, CLIP_CHILDREN)
  jobs.py          manual-mode background job runner
  gpu.py, locks.py cross-process GPU lock (one heavy GPU job at a time, VRAM wait)
  netguard.py      checks every URL that came from data (public IPs only, checked redirects, size caps)
  secure.py        DPAPI secret storage
  pipeline/        transcribe, candidates, virality/scoring/llm, hooks, postpack, reframe, captions,
                   render, versions, export, and new in this round:
                   artifact.py (render record), quality.py (file checks), blueprint.py (typed clip plan)
  publish/         youtube.py, tiktok.py, jobs.py (upload worker), routes.py, stats.py (real metrics only),
                   audience.py (who may watch: one policy for every upload path)
  autopilot/       queue.py (durable jobs + WORKERS), host.py (worker threads/process, @handler),
                   handlers.py (imports every handler module), scout, trends, providers, rights, hunter,
                   live, packaging, gate (Final Quality Gate), scheduler, quota, publisher, learner,
                   brain.py (results with provenance, guarded strategy), routes.py (/api/autopilot), brain_routes.py
  office/          the robot office's backend: roles.py (cast), feed.py (events, reports, decisions), view.py
                   (snapshot), health.py, capabilities.py (integration matrix), integrations.py, routes.py
  pipeline/nvidia.py optional NVIDIA-hosted text AI (off by default)
frontend/src/      App.tsx (shell), router.ts (addresses, old-address aliases, unsaved-changes guard), status.tsx
                   (one shared Autopilot status poll), format.ts, api.ts, autopilot.ts, styles.css (design tokens),
                   office/ (cast.ts registry, sprites.ts pixel art, world.ts floor plan, OfficeMap.tsx, panels.tsx,
                   useOffice.ts event feed, api.ts), pages/ (Office, Team, Setup, Autopilot = Missions, Library =
                   Clips, Feedback, Create, ProjectView, ClipEditor, Publish, Posts = Queue, PostReview, Settings),
                   components/ (ui.tsx shared controls, integrations.tsx, page parts)
design/            robots/ (art notes, manifest, contact sheet), robot-office/screenshots/, ui-redesign/ and
                   retro-studio/ (earlier designs)
tests/             pytest suites; fake_platforms.py (fake YouTube/TikTok), synthetic_media.py (ffmpeg test video)
e2e/               Playwright tests for the user's own running app (read-only by design)
data/              created at runtime (gitignored): clipfoundry.db, projects/<id>/..., models/, logs/workers.log
```

The Autopilot flow is:

```
hunt_source → analyze_source (Engagement Strategist writes a Clip Blueprint, render follows it)
  → package_clip → quality_check (Final Quality Gate) → schedule_tick → user approves in Queue
  → publish (audience check first: YouTube Private, TikTok followers, or a ready-to-post package)
```

## Run and test

```bash
python -m venv .venv && .venv/bin/pip install -r requirements-dev.txt   # Windows: .venv\Scripts\...
.venv/bin/python -m clipfoundry                   # app on :8765 (Windows users: start.bat)
.venv/bin/python -m pytest -m "not slow"          # ~550 tests, ~5-7 min
.venv/bin/python -m pytest -m slow                # 7 real-media cases, ~10-12 min (needs ffmpeg + espeak-ng)
cd frontend && npm install && npm run build       # after any change in frontend/src; commit dist/ too
cd e2e && npm install && npm test                 # read-only browser tests against a running app
cd e2e && npm run test:sandbox                    # beginner, motion, robot and complete-loop checks (ports 8799/8800)
```

* `tests/conftest.py` points `CLIPFOUNDRY_DATA` at a temp folder and sets `CLIPFOUNDRY_WORKERS=off`, so tests never
  touch real data. Tests use fake platforms and synthetic video, never real accounts.
* Other environment variables: `CLIPFOUNDRY_PORT`, `CLIPFOUNDRY_FFMPEG`, `CLIPFOUNDRY_URL` (e2e), `HF_ENDPOINT`.
* `e2e/sandbox/run_sandbox.py` starts a throwaway app (temp data, fake Google/TikTok from `tests/fake_platforms.py`,
  synthetic transcript instead of Whisper). Use it to try UI changes that write; never point write tests at real data.
* Last recorded results: see the test log in `docs/IMPLEMENTATION_STATUS.md`. `npm run build` reproduces the
  committed `dist/`.

## Where things stand (2026-10-08)

**Branches.** The default branch is `claude/wonderful-ritchie-909tq3` (there is no `main`). Everything is merged
into it: PR #1 (plan items 1-7), PR #3 (zero-config and hands-off Autopilot), PR #2 (NVENC GPU lock, exact
Retry-After, confirmed channels), PR #4 (the Playwright MCP launcher), PR #5 (plan items 10-13), PR #6 (overnight
run fixes, item 16), PR #7 (the UI redesign, item 17), PR #8 (Codex's idle-Autopilot fixes, item 18), PR #9 and
#10 (website, item 19), PR #11 (ChatGPT's link intake and retro robot studio, item 20) and PR #12 (the final review's
fixes to it). Start new work from the default branch; the tested commits are in the test log of
`docs/IMPLEMENTATION_STATUS.md`.

**Done** (plan in `docs/IMPLEMENTATION_STATUS.md`):

1. **Render artifact record** (`pipeline/artifact.py`). Every render stores:
   * `edl.json`, the edit time map;
   * `transcript.final.json`, the words heard in the output;
   * SHA-256 and ffprobe results, in `render_info["artifact"]`.
2. **Final Quality Gate** (`pipeline/quality.py`, `autopilot/gate.py`). It checks the exact file: hash, codecs,
   1080×1920, duration, a full decode, black, frozen and silent stretches, caption timing, cuts inside words, and
   metadata grounding.
   * The report is bound to the file's SHA-256.
   * The scheduler and the publisher require a passing report.
3. **Clip Blueprint** (`pipeline/blueprint.py`). A typed, validated clip plan, stored in `clip_blueprints` and
   followed exactly by the renderer.
   * Unsupported instructions are reported, never silently applied.
   * Manual clips have no blueprint.
4. **Queue safety.** The priority floor is inside the atomic claim, each claim gets its own lease token, and a
   stopping host keeps its lock until its worker threads exit.
5. **Strict GPU.** In Autopilot, a CUDA failure pauses the job for 30 minutes and raises an action item. It never
   silently falls back to the CPU; the setting `autopilot_allow_cpu_fallback` (default off) allows it.
6. **URL safety** (`netguard.py`).
   * URLs from data must resolve to public addresses; URLs the user typed may point into their own network.
   * Redirects are checked hop by hop, and the connection is pinned to the checked address.
   * ffmpeg gets `-protocol_whitelist`.
   * Sources are capped at 8 GB / 240 minutes.
7. **Never upload twice.** If YouTube accepted every byte but its answer was lost, the post becomes "reconciling"
   ("Upload not confirmed" in the UI) until the user resolves it.
8. **NVENC encodes take the GPU lock** like transcription does (PR #2).
9. **Retry-After is never shortened** (PR #2). Up to 60 s is waited out in place; a longer wait puts the job back
   for exactly that time (Autopilot: `queue.Wait`; manual uploads: a timer that survives restarts) and the same
   upload continues then.
10. **Replacement cooldown** (`scheduler.replacement_blocked`, table `slot_replacements`). A slot is swapped at most
    once per `autopilot_replacement_cooldown_hours` (default 24, not on the main settings page). The history
    follows the slot's time and every post that took part in a swap, survives restarts, and allows one pending
    proposal per slot; a declined proposal is not made again. Existing databases are backfilled from
    `replaces`/`replaced_by`.
11. **Dashboard counts.** `status()["target"]` counts unique clips (`published`, `scheduled`) and platform posts
    (`published_posts`, `scheduled_posts`, `posts_by_platform`) separately; "today" is the local day, 23 or 25
    hours long on a daylight-saving change (`scout.day_bounds`).
12. **Daylight saving.** `tests/test_autopilot_integrity.py` plans and recovers missed posts across both
    America/Chicago changes.
13. **Multi-interval plans.** `blueprint.with_middle_cuts` removes up to two weak middle sentences (only filler
    words, a clear promotional line, or a warm-up phrase with no words of its own) when every safe-cut rule holds:
    pauses on both sides, complete sentences, the next sentence does not point back at removed words, hook, payoff,
    questions, first and last sentences stay, at most 35% removed, and the clip keeps `min_duration`. Otherwise the
    clip stays continuous. The final transcript, captions, packaging and gate follow the cut output.
14. **Confirmed channels** (PR #2, the owner decided "restrict"). `autopilot/verify.py` asks YouTube (Data API) or
    TikTok (oEmbed) who posted the exact video before a channel rule or ownership applies; see rule 1.
15. **Approvals bound to the exact file.** An approval records the SHA-256 of the rendered video with the text,
    privacy, options and render version (`scheduler.APPROVAL_SCHEME = 2`). Changed bytes, even with the same size
    and time stamp, a missing or unreadable file, or an approval from before the hash was stored all need a new
    approval; YouTube is approved again automatically only through the automatic-publishing permission and a
    passing gate report for the new bytes.

16. **Overnight run fixes (2026-09-30).** A night of Autopilot with only a connected account did nothing: every video
    it found belonged to other people and was skipped, and the page said "Nothing right now".
    * **Your videos folder** (`autopilot/myvideos.py`): START creates `Videos\ClipFoundry` in the user folder (outside
      the app folder) and watches it as an Owned watch folder. `CLIPFOUNDRY_VIDEOS` overrides the path (tests, sandbox).
    * Needs you showed *Autopilot needs videos to work with* (`home.needs_videos`). Since item 20 a lack of videos
      is not a Needs you item: Home says *Nothing needs you. Add a video to make clips.* and the overview's *Your
      videos* panel keeps OPEN VIDEOS FOLDER.
    * `awake.py`: while Autopilot is on, the app asks Windows not to sleep (`autopilot_keep_awake`, default on).
      The page reports the real state (`home.keep_awake`: on, pending, failed, off, unsupported), never the
      setting alone; a refusal is a Needs you item (`sleep`) with the power-settings steps, retried every minute.
17. **UI redesign (2026-10-01, PR #7; the owner approved the design).** A "quiet dark studio" look and five places:
    Home, Autopilot, Library, Posts, then Settings. `design/ui-redesign/` holds the spec, the route map and the
    prototype it was built from.
    * Old addresses keep working: `router.ts` replaces them in place (`#/projects` → `#/library`,
      `#/publish-center/*` → `#/posts/*`, …), so Back never bounces on them.
    * Home leads with the first Needs you item; first-time setup is `#/setup` (3 steps; the choice is the
      `setup_mode` setting); Autopilot has Overview, Activity, Permissions & sources and Advanced (System, Jobs,
      Learning); Posts has tabs and a page per post (`#/post/:id`, `GET /api/autopilot/scheduled/{id}`) that
      replaces the approval dialog; Settings has Accounts, Defaults and Advanced.
    * `home.working` (the video being worked on, the job's own progress) and `home.posts` (the sidebar counts, the
      same rules as the Posts tabs) feed the shell.
    * The editor asks before leaving unsaved changes (links, Back, closing the window) and says when a save was not
      rendered. No `window.confirm`/`prompt` is left: dialogs say what will happen.
18. **Idle Autopilot fixes (2026-10-01, PR #8; from `codex/fix-autopilot-idle`, brought into the redesign).**
    * Discovery also checks the connected YouTube channel and active channel agreements, scans agreement folders like
      watch folders, rechecks waiting files at every folder check, and frees the daily slot of a stopped video
      (`scout.reconcile_sources`).
    * A failed search keeps what the other searches found and honors Retry-After; a malformed Tavily or Commons answer
      counts as a failed search, not an empty one.
    * `home.discovery` (last and next search, what was found, search problems in plain words) and `home.currently`
      say why an idle Autopilot is idle. Stopped background work is a Needs you item (`stopped`), not shown in the
      first minute after the app starts.
    * Deleting a video also deletes its clip scores, analysis and suggested post text (`CLIP_CHILDREN`); the post
      history and clip fingerprints stay.
19. **Website and legal pages (2026-10-01, PR #9).** `docs/legal` (`index.html`, `privacy.html`, `terms.html`,
    `site.css`) is the public website, written from an audit of the code; the app serves it at `/legal/`. Publisher
    Landry Schreiner, contact landryschreiner456@gmail.com, Minnesota law, "All rights reserved". No lawyer has
    reviewed it. It goes public only with the owner's OK, from a `gh-pages` branch holding only those files.
    * The audit's fixes: every secret setting is sealed (the AI keys too), httpx no longer logs request addresses
      (a YouTube API key travels in one), and the YouTube 30-day clean-up also runs at every start and counts a
      found video's age from YouTube's last answer.
20. **Link intake and retro robot studio (2026-10-02, PR #11 by ChatGPT/Codex from the owner's briefs; PR #12 the final
    review).** Paste a public video or stream link in Autopilot → *Add a video or stream* (`autopilot/intake.py`,
    job `identify_link`); it is processed locally even when reuse permission is unknown (rule 1). Live HTTP/HLS goes
    through `autopilot/stream_access.py`. Failed or weak videos release their turn (`scout.refill`), automatic clips
    get at most two fresh renders after a broken file (`gate.regenerate_clip`), and closing the app keeps an upload's
    session. The look is the retro robot studio (`design/retro-studio/SPEC.md`): four stations that follow the real
    workers, a Reduce motion preference in this browser.
    * PR #12: an interrupted live recording (app closed, Autopilot paused) waits and records on instead of ending;
      Stop all jobs is a hold, so its canceled work is queued again when asked for after Resume jobs (a job you
      cancel yourself stays canceled, `queue.STOP_ALL`); a due or *Publish now* post runs its canceled upload job
      again; the overview names searches that did not work again.

21. **Robot office (2026-10-07/08, draft PR #14 on `claude/project-thread-vw1n9y`, not merged; from the owner's
    master prompt).** Details: `docs/OFFICE.md`, `AI_HANDOFF.md`.
    * Places: Office (`#/`), Missions (`#/missions`, the former Autopilot page), Clips (`#/clips`, the former
      Library, plus Test feedback), Queue (`#/queue/*`, the former Posts) and Settings; old addresses still work.
    * Selected audience only (rule 13): YouTube Private without `publishAt`, shared by the owner in YouTube Studio;
      TikTok followers or friends through an audited Direct Post, else a ready-to-post package the owner posts and
      links (or marks posted) on the post's page. Approvals are bound to the audience stamp and the connected
      account (`scheduler.APPROVAL_SCHEME = 3`; the automatic-publishing permission names its channel); Pause
      publishing.
    * The office: 25 robots (`office/roles.py` = `frontend/src/office/cast.ts`) moved only by the event feed of
      real job transitions; managers' reports and COMMAND's recorded decisions at the source, clip, QC and upload
      checkpoints; health readings; capability registry and integration cards.
    * Brain (`autopilot/brain.py`): provenance, null ≠ 0, idempotent imports, Test feedback; strategy changes need
      30 mature clips from 5 videos in one selected audience (counted from when the owner confirmed sharing;
      uploads nobody else could watch are not evidence), 20 clips per side for a comparison, and move at most 10%,
      with rollback per platform that the same results cannot undo.
    * Optional NVIDIA text AI (`pipeline/nvidia.py`), off by default, with opt-in, budgets and local fallback.

**Zero-config and hands-off Autopilot** (PR #3; tables in `IMPLEMENTATION_STATUS.md`). The user wants: connect
YouTube, connect TikTok, START AUTOPILOT, and nothing technical on the main page.
* `autopilot/home.py` builds the simple page (`status()["home"]`: currently, needs_you, opportunities, upcoming,
  activity, empty-state text, setup). `POST /api/autopilot/start`.
* No per-video questions by default (`rights_ask_per_video` off). Creator agreements (`rights.add_agreement`), file
  access (`autopilot/access.py`, separate from reuse rights) and the automatic-publishing permission
  (`autopilot/autopublish.py`, YouTube only) replace them.
* UI (item 17): first-time setup is `Setup.tsx`; the Autopilot overview is plain, and the technical parts live
  under Autopilot → Advanced (`#/autopilot/system|jobs|learning`) and Settings → Advanced. Keep jargon (worker,
  feed, provider, source, quota) off Home, the Autopilot overview, Setup and Settings → Accounts/Defaults;
  `test_autopilot_simple.py` checks the backend's page text.

**Decided:** live monitoring is on by default (owner, 2026-09-29). Public video discovery (`autopilot_public_videos`)
stays on, with publishing eligibility checked separately (owner, 2026-10-08); `e2e/sandbox/beginner-flow.spec.ts`
now expects public videos to be clipped on the PC and never planned or posted, and passes.

**Open decisions for the owner:** TikTok. Its guidelines turn away personal tools and apps that repost videos from
other platforms, so the audit for Direct Post is unlikely; inbox drafts also need TikTok to approve the app. Without
either, each TikTok clip is a ready-to-post package the owner posts in the TikTok app (`docs/PLATFORM_CAPABILITIES.md`).

**Next candidates:** multi-cut clips beyond weak sentences (e.g. dropping a tangent), and the checks on the owner's
PC listed at the end of `IMPLEMENTATION_STATUS.md`.

**Never verified here** (the cloud session has no GPU and no accounts): real CUDA transcription on the RTX 3050,
real YouTube/TikTok uploads, real Data API and oEmbed answers, and throughput per source. The checklist at the end
of `IMPLEMENTATION_STATUS.md` lists what the user must run on their PC.

## Rules every change must keep

These are product guarantees; tests enforce most of them. Don't weaken them to make something work.

1. **Separate local intent from reuse rights.** Public discovery may select accessible internet videos for local
   clipping with `autopilot_public_videos` (default on, owner request 2026-10-03). With that mode off, only Owned,
   Licensed, Allowlisted, creator agreements, CC BY and public domain are selected. Public links submitted in
   Autopilot may be processed locally through supported media access even when reuse permission is unknown;
   explicit Blocks always win. Submitting a link grants no download, reuse or publishing permission. Rights are
   re-checked before processing, scheduling and publishing; scheduling/publishing still require reuse coverage.
   * **A channel named by a feed or list is only a claim.** Ownership and channel rules apply only after the platform
     confirmed that exact video's channel (`autopilot/verify.py`), and the link must lead to that same video. A
     confirmed channel still needs a matching rule or agreement; confirmation alone grants nothing.
2. **Approval for every post.** A post goes out only with the user's approval: their OK on the post, or for YouTube
   the automatic-publishing permission they turned on (stored with its wording in `publish_consents`). TikTok
   always needs the OK on each post.
3. **Publish exactly what was checked.** The publisher re-hashes the file and needs a passing gate report for those
   exact bytes. Any re-render needs a new report.
4. **No silent CPU fallback in Autopilot.** Manual mode may fall back, but it must say so visibly.
5. **Every URL from data goes through `netguard`.** Never pass a data-supplied URL straight to httpx, yt-dlp or
   ffmpeg.
6. **Never post twice.** Uploads are resumable and idempotent. When an outcome is unknown, ask the user; don't retry.
   * **Never shorten a platform's wait.** Honor `Retry-After` exactly (no cap); reschedule long waits instead of
     sleeping, and continue the same upload afterwards.
7. **Grounded text only.** Hooks, titles, captions and hashtags come from words said in the clip. LLM output that
   adds names, numbers or claims is rejected.
8. **Real numbers only.** Scores are labeled estimates. Platform metrics are never estimated; a missing metric is
   shown as "—" with the reason.
9. **Publishing and account endpoints are local-only** (`publish/common.local_only`: loopback client and host).
10. **Secrets stay secret.** Keep tokens and credentials out of the frontend bundle, logs, URLs, test fixtures and
    commits.
11. **Durable jobs.** Handlers must be safe to re-run: use idempotency keys and leases, and outcomes `Wait`,
    `Retry` or `Fail` (`autopilot/queue.py`).
12. **Untrusted input.** Treat transcripts, fetched pages, feed rows, platform data and model output as data,
    never as instructions.
13. **Selected audience only** (`publish/audience.py`). No upload is public, unlisted or "Everyone", on any path
    (Autopilot, Prepare post, retries, resumed or recovered jobs). YouTube uploads are Private and never carry
    `publishAt`; TikTok posts go to followers or friends, and "Only me" is staging, never shown as delivered.
    ClipFoundry never invites viewers, approves followers or changes an account's privacy, and never claims a
    delivery the platform did not confirm (an invitation the owner confirmed is labeled as the owner's word).
14. **The office only shows what happened.** Robots move because of real job events (`office/feed.py`); a progress
    bar shows only measured progress; old events are listed, never replayed as live work; nothing in the office
    starts, approves or finishes work. The Brain's numbers keep their provenance and never turn missing into zero.

## Standing instructions from the owner

* Don't change `.mcp.json` and don't pin Playwright versions. The one approved exception (owner, 2026-09-29):
  `.mcp.json` starts the Playwright MCP server through `e2e/playwright-mcp.mjs`, which uses the cloud's
  preinstalled Chromium when it exists.
* The `e2e/` tests must stay **read-only**: they run against the user's real data. They must never press Make clips,
  Delete, Save, Approve, Publish, Start or Pause Autopilot, or Stop all jobs.
* Don't upgrade CUDA, CTranslate2, faster-whisper or other GPU dependencies casually.
* Without explicit permission, don't:
  * publish real posts, spend money, or change account permissions;
  * delete user media;
  * force-push, or deploy public pages.
* Make only the change that was asked for. Don't create pull requests unless asked.

## How to work on it

* Work in **small, tested increments**. After each one:
  * run `pytest -m "not slow"`, plus `-m slow` if rendering, Autopilot or the pipeline changed;
  * update `docs/IMPLEMENTATION_STATUS.md` (plan checkbox, matrix row, test log line).
* A new DB table goes into `SCHEMA` in `db.py` (`CREATE TABLE IF NOT EXISTS`), plus `JSON_FIELDS` for JSON columns.
  A new column goes into `ADDED_COLUMNS`. A per-clip table must also go into `CLIP_CHILDREN`, so deletes clean it up.
* A new Autopilot job kind needs three things:
  * a `@handler("kind")` from `autopilot/host.py`;
  * the kind listed under a worker in `queue.WORKERS`;
  * its module imported in `autopilot/handlers.py`.

  Several tests assert the worker count (currently 12).
* A new setting goes into `config.py` (default and range), plus `frontend/src/components/autopilotSettings.tsx` if the
  user should see it.
* After frontend changes, run `npm run build` and commit `frontend/dist`.
* When a change alters what ClipFoundry stores, sends, keeps or deletes, update `docs/legal/privacy.html` (and the
  Terms or product page if they mention it) in the same change: the pages describe the code exactly.
* Style: match the surrounding code. Lines are at most 120 characters, and comments explain *why*. UI text is plain
  English for a non-developer and says what to do next. Prefer fakes (`tests/fake_platforms.py`) and synthetic media
  (`tests/synthetic_media.py`) over mocks of internals.
* Report honestly: if something was not run or not verified, say so.

## Using this with a chat-only AI

Paste this file first. Then paste the specific source files and the test file for the part you want to change.
Ask for a patch plus the tests that prove it, and run `pytest -m "not slow"` yourself before committing.
