# AI handoff

Read [AGENTS.md](AGENTS.md), this file, [docs/OFFICE.md](docs/OFFICE.md) and
[docs/PLATFORM_CAPABILITIES.md](docs/PLATFORM_CAPABILITIES.md). Snapshot: 2026-10-13 (UTC).
Fetch before trusting branch state.

## Latest continuation: finished clips reach YouTube scheduling

Base: `987ebb288ae9097bedbd80d0adee2b3c05c4271f`, on `codex/brain-graph-quality-discovery`.
The owner reported an all-day YouTube-only run with finished clips, no schedules/uploads and no Needs you.
The owner's actual Windows database was not accessed. Isolated reproductions identified and fixed these paths:

* Parked reuse-permission/file waits filled the six-find backlog forever; high-estimate local-only finds could
  take every daily attempt before reusable media. Bounded workable/parking lanes retain saved history and daily
  budgets while giving accessible, covered candidates priority. Explicit input and quality floors stay intact.
* Analysis waited for every render before fingerprint/package handoff. Each completed recorded output now hands
  off before any priority yield. Scheduler/maintenance recover bounded older proven outputs exactly once, using
  saved validated plans, selection evidence and existing files. Failed/canceled packaging and manual edits remain
  untouched. Live replacements finish their decisions first. Cancellation/Pause are rechecked after fingerprinting.
* A stored consent for a different channel/audience could suppress approval reminders even when unusable.
  Availability now controls reminders; existing Private plans retain valid original permission. Private automatic
  consent also requires a confirmed, non-local destination. Setup exposes audience confirmation and separate
  automatic YouTube permission together, filtered to connected platforms, with no automatic grant or audience change.
* Read-only posting readiness and derived setup warnings show post text, final checks, local-only rights and
  scheduling/permission holds even if the scheduler never wrote an action item. Recent stage counts sample at most
  200 finished automatic clips; the total counts all. An approved item without a posting time is a wait, not a schedule.
  Latest preparation state wins over older failures. Phone attention retains its fixed-description whitelist.

**Validation:** Final full fast suite: 958 passed, eight slow deselected, in 489.73 s. Final real-FFmpeg/synthetic-speech
media and restart suite: eight passed, 958 deselected, in 695.71 s, including Public/Private and live recovery
loops. Final production build passed in 3.98 s; seven built-interface browser checks passed in 43.6 s. All 17
tested built-file hashes match. Final focused handoff/readiness/simple-page checks: 88 passed in 24.79 s.
Discovery focused checks: 99 passed in 19.36 s; four new behavior regressions fail on the original source.
Scheduler/consent checks: 73 passed, one slow deselected, in 78.53 s. Independent review found the late-
cancellation race; its three corrected regressions passed and no material findings remain. No real owner data,
Windows/RTX3050, platform upload or 24-hour soak was tested.
An independent review's late-parent-cancellation finding was fixed and its three regressions pass. Earlier test
runs were stopped before that correction and are not final suite evidence. One UI test had an in-flight mocked
response disposed at teardown; seeding its status fixture before browser polling resolved it. The old plain-text
test now projects the visible posting title/detail rather than treating a machine stage enum as user text.
No real upload, account-permission change, Windows/RTX3050 execution, owner-data inspection or 24-hour soak is
claimed. The installer retains verified prior managed profiles; ordinary unknown ZIP profiles are not adopted.

## Latest continuation: private phone status dashboard

Base: `4838aa897e59b68a1365dd7ed7f4d60f52dfcc8c`, on `codex/brain-graph-quality-discovery`.
The owner asked to check ClipFoundry's progress from a phone. Settings → Integrations → **Check from your phone**
now controls an optional, default-off companion listener. Tailscale is the recommended private connection;
trusted home Wi-Fi is also supported, with an explicit unencrypted-HTTP explanation. The app never installs
Tailscale, signs into it, changes a firewall/router or rebinds the desktop listener. Literal private IPv4
binding and actual CLI desktop-port tracking preserve listener isolation, including restart/custom-port cases.

The separate FastAPI app serves only three phone assets, single-use pairing and an authenticated status snapshot.
Owner-only localhost controls enable/disable, issue a five-minute eight-digit code and revoke all grants.
Pairing attempts are rate limited globally and per peer. At most eight random device keys last 90 days;
SQLite stores only their SHA-256 hashes. Codes/keys never enter URLs or logs. Normal restarts retain grants;
disabling stops access, revoking removes grants. The phone uses session storage by default, opt-in local storage
for Remember this phone, and clears its displayed status/key after revocation/expiry. Disconnect clears that
browser only; the PC's Unpair all phones revokes copied keys too.

The mobile dashboard reports actual current work, measured/unknown progress, local-day unique clip counts,
separate platform-post counts, next planned post, posting queue and health statuses. It uses the desktop attention
policy, suppresses routine retry alerts and maps only fixed descriptions for derived account/worker/sleep holds.
No media, raw diagnostics, credentials, account identities, Brain text or desktop controls are exposed.
Polling pauses in the background, shows stale/offline readings plainly, backs off and resumes on reconnection.
Desktop setup ignores old polls after newer actions. [Setup and architecture](docs/PHONE_DASHBOARD.md).

**Validation:** Final full fast suite: 869 passed, eight slow deselected, in 386.91 s. Final focused phone tests: 55 passed in 9.03
s; 75 existing local-guard/office/Autopilot regressions passed in 30.43 s before the final attention refinement.
Final built phone browser suite: ten passed in 12.6 s. Final built desktop setup/race checks: two passed in 27.6 s.
Production build passed in 3.85 s; all 17 built-file hashes were recorded. No actual phone, Windows/Tailscale
connection or real account was tested.
The initial complete suite passed 865 checks before the attention-policy refinement. Independent review found
and prompted fixes for that refinement and an older-poll/new-action race. Media/Autopilot handlers are unchanged;
the slow media suite was not repeated for this feature. Native Windows, actual phone browsers, Tailscale account
connectivity, Windows firewall behavior, RTX3050 and real platform accounts remain device checks.
The bundled installer is pinned and integrity-checked separately on `codex/clipfoundry-one-click`.

## Latest continuation: automatic Brain guidance and useful integrations

Base: `28aee85b4ef239584da296cec900bc3d8dde4399`, on `codex/brain-graph-quality-discovery`.
The owner requested all saved Brain material to participate automatically, combined with Settings, and inactive
integration placeholders removed. This supersedes the older separate Brain-approval workflow below; publishing
consent and platform restrictions are unchanged.

Enabled saved notes, document text, explicit preferences and described examples are consulted for new clip
selection and rendering. A bounded local interpreter recognizes caption choices, continuous/safe-cut pacing and
known hook/payoff/context/ranking priorities. Explicit controls win over prose; instructions precede examples,
then references, newest saved item first. Settings supply missing choices. Good example durations blend with the
owner's original target by n/(n+3), capped at 60% and constrained by configured length limits. The original target
is retained between source/candidate stages so the hint cannot be counted twice. Selection provenance is copied
and merged by knowledge ID/revision, without mutating another clip's saved decision. Existing clips/posts remain
intact. Manual per-clip overrides win over Brain caption choices. Disabled/paused guidance stays inactive.

Brain shows recognized choices, ranking priorities, automatic activation and unsaved-draft status; it has no
separate approval button. Unrecognized material remains searchable, with actionable help. Raw notes/examples
stay local, no prose executes, and videos do not teach visual appearance or fine-tune a model. Only fixed known
priority labels accompany the existing excerpt sent to an already selected/authorized text AI. The NVIDIA
sending explanation and Privacy page describe this.

Integrations now lists YouTube, TikTok, Tavily, Wikimedia Commons and NVIDIA. Twitch, Kick, Reddit, X, Instagram,
podcasts and Google Trends placeholder cards are removed. Real connection, scope, audit, consent and quota holds
remain visible; no account permission or posting behavior was changed.

**Validation:** Final full fast suite: 814 passed, eight slow deselected, in 349.16 s. Final focused Brain/provider/blueprint/artifact regressions: 96 passed in 43.45 s. Actual-FFmpeg/synthetic-speech media/restart suite: eight passed, 811 deselected, in 710.71 s before the final example-blending/provenance review fixes; those final fixes are covered by the final 814/96 runs. Final controlled browser batch: eight passed in 45.5 s against the final built interface. Build passed in 6.44 s. No real uploads, accounts, Windows/RTX3050 execution or 24-hour soak were tested.
Early runs exposed old approval/placeholder assertions and a malformed new sentence fixture; these were
corrected without weakening write/local-only/platform guards. The first media run lacked the existing portable
speech fixture tool (three failures, four skips); the corrected environment produced all eight passes above.
The earlier 811-check run preceded three additional regression cases; it is not the final complete count.
The standalone local diagnostic collector is separately verified with portable PowerShell: GET-only/custom-port
snapshot, strict privacy whitelist, missing-app and invalid-port behavior. Native Windows remains unverified.
The installer carries this exact source snapshot and has a separate integrity record.

## Current scope and branch

Current work is on `codex/brain-graph-quality-discovery`, starting at
`8999e5fb29a0e1455d8fccff4037d6f089f9091b` from the default branch. PR #14 is merged. Its draft/unmerged notes and
test counts below describe historical checkpoints and are superseded by this branch's status.

The owner requested a finished app and Windows installer, simpler TikTok app setup, a visible Brain graph and
quality before quantity in discovery. Settings now includes **Help me fill out the TikTok app form**: copyable
details, the actual Desktop callback for the current local port, two 1024×1024 PNG icons, scope explanations and
a form-pack ZIP with local draft website/legal pages. Inbox uses `user.info.basic,video.upload`; Direct Post uses
`user.info.basic,video.publish`; optional statistics adds `video.list` and Display API. Applying choices, saving
Settings and reconnecting are separate steps. Existing permission choices are preserved until explicitly changed.
The helper prepares a draft only when opened. It checks URL format locally, does not submit a review or deploy pages,
and excludes app credentials,
tokens, account identities and owner media from the export. TikTok's personal-tool eligibility, Sandbox limits,
per-post consent and private-profile restriction still apply. See [the setup guide](docs/TIKTOK_APP_SETUP.md).

Brain now opens an interactive graph with saved notes, approved preferences, examples, shared topic tags,
recorded clip influence and result readings. Selecting a note or evidence opens its stored record and provenance.
Category/tag edges organize knowledge; influence edges identify the applied revision. Positions and glow are decorative,
not hidden AI thoughts. The graph is bounded to 160 saved items, 32 topics and 48 recent evidence records; list,
editor, history and full knowledge export retain access to the other saved data. **Add note** starts a simple note,
with an optional title derived from its text. **Teach preference** presents supported choices used automatically when saved enabled; the latest
continuation above supersedes its previous separate review/approval step. Documents and examples do not fine-tune a model.
The editor sends its displayed revision; stale edits return HTTP 409 and preserve the draft until explicit reload.

**Missions → Permissions & sources → Quality before quantity** enables focused broad-search discovery by default:
three new candidates per pass, six unfinished automatic search picks including `needs_rights`, one known creator
per pass and two per topic. The existing daily attempt budget remains three by default; weak outcomes do not
justify more attempts to fill the clip target. Explicit links, chosen folders/channels and manual work retain
their existing behavior. Scores and expected clips remain estimates until full analysis and final-file checks.
Optional Tavily setup explains its free 1,000-credit monthly plan without a card; saving a new key with the free
option explicitly sets the app allowance to 1,000 and its monthly spending limit to $0. Other settings are retained.

**Current validation:** the final full fast suite passed **804 checks**, with **8 slow cases deselected**, in
**429.01 s**; Python source is unchanged. All eight media cases are covered by seven initial passes (965.89 s,
one environment disk-capacity failure) and the unchanged live case passing in 48.81 s on workspace temp storage.
Final browser coverage is **52 unique checks across runs**: the initial 44-case batch had 42 passes/two failures
in 12.7 min; the final 11 changed-UI plus eight strict read-only Settings cases all passed in 1.1 min; the complete
loop passed in 7.0 min. Ten cases overlap between the initial/final batches. Lazy helper preparation fixes the
background preview request; one stale Public-visibility assertion was maintained without changing read-only
flows. Recorder/temp-storage environment fixes preserved the full loop. The latest build passed in **4.06 s**;
all 14 tested/captured file hashes match. Current graph previews came from the final run. Earlier interrupted
outputs are not final passes. Installer integrity is tracked separately on `codex/clipfoundry-one-click`.
Final results are recorded at the top of
[IMPLEMENTATION_STATUS.md](docs/IMPLEMENTATION_STATUS.md). See the
[desktop/mobile/empty graph previews](design/brain-workspace/README.md) for controlled-data provenance.
Windows execution, RTX 3050 CUDA/NVENC, real platform accounts/grants/visibility and an actual 24-hour soak remain
unverified. No real upload, account-permission change or website deployment is claimed by this checkpoint.

## Historical PR #14 scope and branch

The owner authorized merging PR #14 after one final pass on October 11. This pre-merge checkpoint follows
`51984a3`; check GitHub for the actual merge state. Independent review found no material blocker, and the
14 browser-tested frontend files still match their recorded hashes. The fresh targeted run passed 105 checks
and exposed one test-only race: inspecting log backups during an active rename. The test now takes the logging
handler's lock for its file snapshot; production code is unchanged. All 16 launcher checks passed in 0.72 s.
The fresh full fast suite passed **757 checks**, with **8 slow cases deselected**, in **301.90 s**.
The earlier real-media, browser, build and actual-app restart evidence remains applicable. Windows, real accounts
and an actual 24-hour soak remain unverified; merge authorization does not change those limits.

The preceding unattended-Public checkpoint started at `61f6042` on the then-draft/unmerged PR #14.
Work ran October 10–11.
The owner requested autonomous all-day Public publishing from a personal setup. Designed unattended YouTube operation
keeps explicit Public setup, account/visibility-bound standing permission, reuse eligibility, exact-file checks and
honest readback. Existing Private schedules stay Private; Public results need no Studio invitations. Midnight **0** now
survives scheduling/consent reads, so **0–24** covers the full day without changing daily limits.

Official YouTube `videos.insert`/`videos` documentation updated October 8 and freshly checked October 10 permits
Public uploads from unverified projects. The obsolete project-audit Public gate is removed; API audit concerns
quota increases. OAuth publishing status is separate: External Testing YouTube refresh grants expire after seven
days; choose Production, then reconnect. Personal use may be exempt from OAuth verification, but authorization can
still be revoked. TikTok retains eligible-app/per-post consent limits; a private TikTok profile cannot offer Everyone.
See [current platform evidence](docs/PLATFORM_CAPABILITIES.md) and [unattended setup](docs/UNATTENDED.md).

The optional `run-unattended.bat` / `python -m clipfoundry --unattended` watches app process exit and restarts with
bounded backoff. It preserves the selected data profile and saved Pause/permissions, owns its app/worker/media tree,
uses profile/port locks and stops without restarting on explicit Ctrl+C. Local app/watchdog diagnostics rotate at
5 MiB plus two older copies. Same-user Windows login startup is documented, never installed automatically.
Run only one app per data profile, including across different ports. This watchdog detects process exit; it does
not detect a still-running, hung main app.
Worker startup cleanup retains its lock until partial workers finish; setup failures do not keep phantom leases.
Bounded cancellable media pipe/process I/O and 2 GB disk-reserve checks keep low-space failures from blocking a
worker forever. Low-disk live capture waits without declaring EOF or deleting saved segments; final assemblies
replace complete recordings only after success.

Scheduled pre-session work rechecks Pause, current consent/account/audience and final quality even after a local
publication row exists. Existing sessions retain their confirmed bytes. Strict original-account, unique recent
submitted-metadata recovery reads actual visibility before reporting success. Final-chunk crash/cancellation or
ambiguous outcomes keep duplicate holds; manual startup recovery shows an unknown outcome with read-only Refresh.
Once final-byte evidence is saved, later reconnect, setup, scope or quota errors preserve that same hold and
publication identity rather than permitting another upload.
The real-media full-loop fixture now covers Public and Private independently, including repeat/restart/exact-byte
checks. This remains synthetic/fake-account verification, not real account or 24-hour operation proof.

Privacy documents local unattended diagnostic retention. No new dependency, real posting, account change, purchase
or deployment occurred. Windows/RTX 3050/accounts and an actual 24-hour soak remain owner checks. Deliberate rights,
quota, authorization, disk and unknown-outcome holds can still need attention; restarting does not bypass them.

The preceding department-office and reliability checkpoint starts at `e896632`, requested October 9 and completed
October 10 on the same draft/unmerged PR #14. Real working/reviewing jobs or substantive assigned backlog gather
the whole department into its own room. Actual workers appear immediately at their own desks; idle teammates sit
ready without typing, progress or invented jobs. Managers oversee from safe floor positions with clipboard checks
and brief pointing gestures; their own jobs and real report reviews take priority. Quiet paused/unavailable peers
may attend, but stale paused tasks, bare queue counts and unreferenced recurring timers do not summon a team.
A completed robot stays ready while another teammate has work, then resumes its reserved lounge activities.
Confirmed handoffs meet inside the receiver's office and return both robots to their latest department assignment.
A newer own job preempts carrying an older document out of its office. Actual badges and task details stay truthful.

The Brain's Processing animation now adds clipped holographic scans, travelling synapse trails, emitter sparks and
orbital light trails. Standby remains visibly decorative; Brain/global Pause, Reduced, hidden and stale views still
the art. Pixi and Canvas share department duties and supervisor cues. No dependency was added; the existing PixiJS
8.22.0 and GSAP 3.15.0 remain. [Latest department evidence and provenance](design/robot-office/departments/README.md).

The owner's full-code-review request also uncovered and fixed concrete backend faults:

* Job progress and host state now reject recovered lease owners and finished/pending jobs; recovery chooses an
  expired lease under the same write transaction as its update, protecting concurrent heartbeat/cancellation.
  Failed lock-file creation releases the in-process mutex, allowing the next GPU/startup lock acquisition.
* Final-check job identity includes the quality-rule version. Regeneration saves/restores the video and complete
  captions, transcript, edit decisions, render plan and thumbnail together. Interrupted rollback remains non-Ready
  until restoration succeeds, retaining its checkpoint on failure. Validated future plans are preserved.
* Brain edits use atomic revision checks, including enable/disable, so a delayed edit cannot overwrite a reviewed
  lesson or re-enable a disabled rule. Paused learning still collects results but preserves learned values and
  applies no cached learned weights/calibration. Confirmed audience drift is excluded from new cohort readings;
  prior observations keep their original provenance.
* Manual publishing checks linked-source rights, platform coverage, current quality/version and exact confirmed
  file bytes before a new transfer. Ordinary manual clips retain their existing workflow. Account binding survives
  TikTok options; emergency Pause also holds queued manual transfers while existing sessions may finish.
  An unknown manual YouTube outcome blocks another upload. Refresh status only reads the original account and
  requires one recent candidate with matching submitted metadata; ambiguity keeps the hold. Already-processing
  queue entries only read status. The Publish page exposes the hold and its refresh action.

Privacy documentation now covers local recovery copies and confirmed-file fingerprints. `.mcp.json`, GPU files,
Playwright versions and read-only `e2e/tests` remain unchanged. No real posts or owner account changes occurred.

The preceding social-pixel-office checkpoint starts at `5b1f7a9`: the owner requested better graphics tools and
off-duty games, food and drinks. Six authored gestures animate arcade controls, board-game pieces, mugs,
bites, page turns and stretches. There are 29 exclusive activity places, 25 stable cast homes and at most two
recreational walkers. Identity-phased routines rotate through free destinations; work and confirmed document
handoffs take precedence, preserve real references and clear leisure props. State badges remain authoritative.
The owner explicitly authorized stopped-office recreation even when those off-duty roles are marked Paused.
An individual pause while Running or an unavailable role remains quiet; global Pause, Reduced, hidden and stale
views freeze recreation. Recovery does not replay missed leisure time or old job stages.

PixiJS 8.22.0 now uses cached BlurFilter light pools and distinct arcade/café/game/sofa zones. New dependency
GSAP 3.15.0 supplies pure gesture-easing functions on the office clock, without independent timelines; its standard
no-charge license notice is included (it is not MIT). Native image generation produced the original bundled skyline.
Optional skyline loading is bounded to 1.5 seconds; failure/stall leaves procedural windows, and late completion
cannot mutate the scene. Cropped textures are destroyed without deleting the shared asset source. Canvas retains
simpler phase-driven gestures and a frozen Brain cue cannot change its pixels when activity expires. Lounge names
are staggered on the whole map and compact in the close camera. Portrait caching and all 25 identities remain.
[Current evidence, provenance and editing guide](design/robot-office/lounge/README.md).
This follow-up changes no backend, media processing or publishing behavior. PR #14 stays draft/unmerged.

The preceding living-office checkpoint started at `a119dfd`: the owner asked for believable proportions, idle robots in a
lounge, seated work, actual document transfers and an animated Brain. This supersedes idle-at-station placement.
The 960×640 floor plan now gives all 25 identities individual lounge seats, room-sized desks/chairs and walkable
aisles. `OfficeMotion.ts` follows current snapshots and fresh confirmed report/stage events: both robots approach,
one document passes between them, then both return to their latest actual destination. It never delays a backend
job or guesses a future transition. Paused/unavailable roles rest; Reduced skips walking; stale/hidden views freeze
and recovery uses the current snapshot without replaying old transfers. `BrainCore.ts` has layered neural lobes,
synapse lights and depth-sorted orbits: ambient **Standby** is decorative, **Processing** follows actual Brain
state/events, and Paused/Reduced/offline still the art. A room camera makes the furniture and robots inspectable.
The Canvas compatibility renderer now uses the same floor plan, seats and transfer controller.
Evidence: [living office and labeled controlled preview](design/robot-office/living/README.md).
This frontend-only follow-up adds no dependencies or processing/publishing behavior. PR #14 stays draft/unmerged.

The preceding visual checkpoint started at `c33a291`: the owner chose **refined retro pixel art** and asked to use better
graphics tools. The office now uses pinned PixiJS 8.22.0 with authored cast-specific artwork, layered room furniture
and a scoped studio shell. Team/detail portraits share one cached offscreen renderer. Existing job snapshots and
events still control states, walks, reports and decisions; this adds no processing or publishing behavior.
Graphics initialization/module failure restores the original Canvas map. Full / Reduced / Follow system remain.
The Windows install screenshot showed nested archive folders exceeding the standard path limit: use fresh ZIP
contents directly in `C:\CF14`, with `test-isolated.bat` there, creating a new `.venv`. Do not copy a partial environment.
The launcher now explains this when a long root may cause dependency setup to fail; no registry change is required.
Visual evidence and tool/edit instructions: [refined office](design/robot-office/retro/README.md).

Continue existing draft PR #14 on `claude/project-thread-vw1n9y`; keep it unmerged. This continuation started at
`fea045d` (previous code review `cf54204`). Default remains `claude/wonderful-ritchie-909tq3` at `eff96fb`.
The owner explicitly superseded selected-only new uploads and hiding idle robots. New Public uploads require
explicit setup/consent and eligible platform capability. Existing posts and scheduled Private uploads retain their
visibility. Never send test videos to owner accounts, buy hosting, deploy, or change account permissions.

## Historical PR #14 implementation

* All 25 robot identities remain individually visible at desks or reserved lounge places, with named labels and
  overhead state icons. Task selection includes shared references, dependencies, blocked reason and next robot.
  Saved motion choices: Follow system / Full / Reduced; Full overrides OS reduced motion. Stale state stops
  animation. Decorative recreation preserves actual state, work priority and genuine document handoffs.
* Brain at `#/brain`: durable searchable documents/instructions/skill guides, good/bad example uploads and feature
  labels, revision approval, edit/disable/delete/export, performance history and recorded per-clip influence.
  `autopilot/knowledge.py`, `knowledge_routes.py`, additive `brain_knowledge`/`brain_influences` tables. Uploaded prose
  is reference text, not executable code or model fine-tuning. Only supported approved caption/pacing preferences
  affect new blueprints; topic tags scope them. Examples never become posting results. Export includes all saved
  metadata/text/influences, without browsing caps; original uploaded files are downloaded separately.
* Demonstration: actual document upload + approval → later validated/persisted blueprint changes bold captions to
  minimal. Both instruction and bad-example later-plan regression tests pass. Screenshot/proof JSON record the
  saved decision; Try a decision is separately labeled a preview.
* Discovery: audience/topic terms, exclusions, language evidence, source-score floor and complete-story filter;
  curated/manual inputs retained. Metadata audience relevance and clip potential are estimates, not verified US
  viewers or promises of virality. Automatic repetitive/weak/unsuitable-live candidates are declined with reasons.
* Final check returns bounded repair work to SPLICE / GLYPH / STORY / QUILL with exact reasons and shared references.
  Two repair attempts maximum; uploads already using a file and user edits/cancellation are protected. Timestamp
  checks detect A/V offset and duration problems, not semantic lip sync. Missing sound is detected before Whisper;
  silent live segments are retained/skipped and later audio resumes; mixed final recordings retain returning
  sound with silent timeline gaps, temporary assembly files are removed, and all-video-only sources fail clearly once.
* New Public YouTube uploads and standing automation use explicit audience confirmation, connected-channel and
  visibility-bound permission, limits and exact-byte checks. Public lead is zero, so local
  uploads start at due time without `publishAt`. Existing Private schedules remain Private. Actual returned
  restrictions are reported. API-project audit status is informational; it no longer gates Public uploads.
  TikTok Everyone remains eligible-app + creator-options + per-post consent; inbox
  drafts/manual packages are honest fallbacks. No standing TikTok automatic consent.
* Learning separates confirmed-public and selected-viewer cohorts; unconfirmed/requested visibility does not drive
  learning. Both learners require 48-hour maturity. Cached weights/styles/posting-time data cannot carry over when
  the configured audience changes. Existing bounded updates, rollback, source diversity and sample guards remain.
* Measured real stage intervals: `/api/office/performance`, `python -m clipfoundry performance --days 7`.
  Pause/Stop controls are re-read atomically when the worker claims a job, preventing a stale preliminary
  state read from starting new work after the control was committed. Two deterministic regressions reproduced
  the old race and now pass. Database first-use migrations share a cross-process/thread lock and commit before
  another initializer reads the schema; old-project preservation and concurrent startup regressions pass.
  Separate Windows launcher `test-isolated.bat`: own `data\pr14-test`, videos, `.venv` and port 8899.

## Historical PR #14 validation

Latest unattended-Public validation is recorded at the top of
[IMPLEMENTATION_STATUS.md](docs/IMPLEMENTATION_STATUS.md). Full fast Python passed 757 tests, eight slow deselected,
in 390.67 s. All eight slow cases passed across the full run (six passed, two fixture setup failures, 786.85 s) and
the corrected Public (58.73 s) and upcoming-live (49.02 s) reruns. Production code stayed unchanged for those
corrections.
All 32 isolated browser cases passed together in 8.1 min. TypeScript/Vite build passed in 4.37 s; all 14 tested file
hashes match. Final fast verification includes the recovery, media, launcher, policy and unknown-outcome regressions.
The actual-app POSIX exit/restart/stop smoke passed in 11.98 s; Windows behavior remains unverified.

At the preceding department/reliability checkpoint:
[IMPLEMENTATION_STATUS.md](docs/IMPLEMENTATION_STATUS.md). Full fast Python passed 685 tests, seven slow deselected,
in 347.07 s. All seven slow media cases passed together in 676.84 s, with 685 fast cases deselected. All 31 isolated
browser checks passed together in 7.8 min. Final TypeScript/Vite build passed in 5.96 s with the existing 904 KB
lazy graphics warning.
All 14 build files and file sets match both tested and captured SHA-256 manifests. Routing/controller checks cover
3,844 + 36,304 routes, 600 virtual seconds and 150 mixed transitions. Actual Brain/supervisor pixels animate and
freeze in Reduced while true states update. All 32 touched/new code files meet 120 columns; whitespace checks pass.
Earlier 29/31-case browser runs each had one fixture/sampling failure, corrected without weakening the new-job
guard; the implementation log records their details separately from the final 31-case pass.
The new evidence has nine screenshots and one 37.40-second 1440×900 H.264 recording. Controlled work, supervisor,
Brain and handoff fixtures are visibly labeled separately from an actual stopped-sandbox lounge screenshot.
All 25 identities, laptop controls and mobile List/Studio layout were inspected, with no horizontal mobile overflow
and zero page/console errors. Evidence records all 14 captured production-file hashes. The recording documents
animation and confirmed-event choreography, not actual video-processing speed, Windows or RTX 3050 performance.

At the preceding lounge checkpoint:
The full fast suite passed **641 tests**, with seven slow cases deselected, in 280.30 s. All **23 focused browser
checks passed together in 6.4 min**. Final TypeScript/Vite build passed (5.83 s; existing lazy 904 KB graphics chunk
warning); all 14 distribution files are SHA-256 identical to the assets used in that final browser run.
Actual isolated desktop/laptop/mobile captures have 25 robots, visible laptop controls, no mobile horizontal
overflow and zero page errors. Both 1440×900 H.264 recordings have zero page errors: 33.24 s of actual stopped
off-duty animation, and 33.48 s of visibly labeled controlled work/Brain/stage fixtures. Only startup before the first
visible provenance banner was trimmed; animation was not retimed. Neither measures processing
speed. Prior slow media cases were not repeated for this frontend-only checkpoint.

At the preceding living-office checkpoint:
Production TypeScript/build passed; 17 office Python checks passed in 6.10 s and all 17 focused browser cases passed
together in 3.1 min. The browser cases cover lounge seats,
walk/sit/return, same-job document passing, event freshness/identity, Pause cancellation, Brain standby/processing/
pause, Reduced still frames, camera, fallback, portrait/navigation and desktop/laptop/mobile layout, plus current
sender recovery after hidden/paused stages and protection against reset-history replay. Evidence is
separated into actual isolated snapshots and visibly labeled controlled animations; neither is a GPU benchmark.

The preceding refined-art validation: TypeScript/production build passed, 17 office Python tests passed (7.20 s), and all ten focused motion/robot/
graphics browser cases passed together (59.3 s). Actual desktop/laptop/mobile captures recorded zero browser errors;
the separate animation video is visibly labeled as controlled test states. A pixel regression verifies COMMAND's
approval looks different from idle even in Reduced mode. Static floor/furniture is cached once; portrait cache is bounded.
The earlier 641-test and complete-media results below belong to `c33a291`; those suites were not repeated during
that refined-art checkpoint. Subsequent fast runs above are separate. Windows batch execution, PC graphics/scaling
and GPU checks remain owner checks. That refined-art checkpoint added only PixiJS; the latest lounge also adds GSAP.
Playwright and GPU pins remain unchanged.

The original master-continuation results below belong to the earlier `c33a291` checkpoint, separately from the
subsequent reruns. Its complete fast suite passed **641 tests** (263.21 s; seven slow cases deselected).
All seven slow cases passed across the full run
(six passed) and the corrected complete-loop rerun (one passed); the test now waits for both durable published
schedules before advancing fake result maturity. Ten browser checks passed across the sandbox run and targeted
Brain/Public-loop reruns. The Public browser loop includes two posts, restart, results, live capture and pause.
Production frontend TypeScript/build passed. Focused startup/core/office/TikTok: 66 passed; publishing: 44;
knowledge/public: 17; full Brain export: 8; public-audit/automation: 33; timing/office: 19; returning-audio/recovery: 28.
A database made using `fea045d` opened under the new additive schema with project/clip/settings/private
schedule/audience/approval and media bytes unchanged. No owner data was accessed.

Visual assets: [design/robot-office/screenshots/README.md](design/robot-office/screenshots/README.md). It distinguishes
actual isolated app/jobs, synthetic transcripts, saved blueprint decisions, lookup previews and controlled animations.

## External limits and remaining owner checks

Earlier October 8 developer-host requests returned proxy **403**; those verification limits remain historical.
October 10 official documentation was reachable and freshly checked: YouTube's October 8 update permits Public
from unverified projects, API audits cover quota increases, and External Testing grants have a seven-day lifetime
for YouTube scopes. Current sources and remaining TikTok restrictions are recorded in PLATFORM_CAPABILITIES.

Not verified here: RTX 3050 CUDA transcription / NVENC rendering; real accounts, scopes, quota grants and
returned Public visibility; TikTok app eligibility and approval, real Direct Post/inbox; Windows setup, fonts,
scaling; Windows Task Scheduler/process-tree cleanup; a real 24-hour unattended soak; live network access on the
owner’s PC; real NVIDIA services. Run the
[Windows test guide](docs/WINDOWS_PR14_TEST.md) in a separate copy first. No real posts, purchase or deployment occurred.

[Server recommendation](docs/PERFORMANCE.md): keep the PC until its real timing/GPU report supports a comparison;
a server can improve uptime but does not remove platform restrictions. No general randomized experiment system,
unique-viewer/dominant-video rule, new Twitch/Kick/Reddit/X/Instagram/podcast connectors or preview-before-download
screen was added. Knowledge controls are intentionally typed; arbitrary prose does not automatically alter decisions.

## Do not break

Keep `.mcp.json` and GPU dependencies unchanged; no Playwright pins. Preserve the owner-data browser tests'
read-only workflows and request blocker. One stale Integrations assertion now matches the already implemented
Public choice; it does not select an audience, grant permission or issue a write. Commit built `frontend/dist`.
Preserve exact-file quality/approval hashes, reuse eligibility, access guards, account-bound consent, limits,
duplicate prevention/recovery and emergency stop. No silent CPU fallback in Autopilot. Never fabricate processing
progress, metrics or visibility; keep decorative recreation visibly separate from actual job activity.
PR #14 is merged; follow the current scope and branch recorded above.
