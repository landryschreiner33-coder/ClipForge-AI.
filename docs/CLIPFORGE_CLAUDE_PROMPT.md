# Claude Code implementation prompt: ClipForge cloud studio

Copy the content below into Claude Code, or ask Claude Code to read this file in the repository and implement it.
Updated November 3, 2026 (America/Chicago), with the owner's corrections. This is the canonical full prompt;
it supersedes the earlier three-choice creation layout. Section 16 adds concrete screen contracts, defaults,
data requirements, fixtures and pass/fail scenarios. This brief does not claim the features are built.

---

You are continuing the existing ClipFoundry application and renaming its product experience to **ClipForge**.
Build the requested cloud studio in tested, runnable increments. Inspect the latest code first and preserve
previous Claude/Codex fixes. Do not replace the app with a mockup or stop after creating a plan. When an external account, real footage, capacity or paid service is unavailable, finish all
independent implementation and testing, then report the exact remaining setup and evidence needed.

## 1. Owner goals and agreed scope

The owner wants:

1. Upload multiple clips and have the app assemble a full YouTube video. Ask a few useful questions about how
   it should be edited, remember selected answers in the Brain, and reuse that style on future projects.
2. Keep **Clips** as one creation workflow with two modes: **Highlights** and **Full stories**. In Full stories,
   each story in a long source video becomes one complete vertical clip formatted for TikTok and YouTube,
   including its setup and ending. Full stories is inside Clips, not a separate top-level creation product.
3. A personal account that works from any device, with processing on a server even when the Mac is off.
4. Import reusable skills that help the app edit and make creative decisions.
5. Simple, polished flows requiring few clicks, with advanced controls available when wanted.
6. Customizable themes, layout, panel arrangement and display preferences that are saved to the account.
7. Reuse appropriate ArtCraft-family open-source editing software instead of writing a professional editor,
   codec stack and effects system from scratch.
8. Connect multiple YouTube channels and multiple TikTok accounts at the same time, under one ClipForge login.
   Clearly select which account(s) each output should publish to.
9. Rename the product from ClipFoundry to **ClipForge**, preserving existing projects, settings and credentials.
10. Rearrange and redesign the interface around these workflows so it looks cohesive, attractive and professional.
11. Let the owner give every robot a custom display name, saved across sessions and devices.

Cloud is owner-only at first; public accounts come later. Expected demand exceeds five source-video hours
per day. Cost should be as low as possible. No paid resource or subscription has been approved. A genuinely
free pilot is acceptable as a proposal, but free capacity and throughput are not proven. Do not silently charge
for models, compute, storage or traffic. Keep the working local Mac/Windows experience during the transition.

## 2. Establish the correct baseline

Repository: https://github.com/landryschreiner33-coder/ClipForge-AI.

Read AGENTS.md, the newest AI_HANDOFF.md and AI_CHANGELOG.md entries, docs/IMPLEMENTATION_STATUS.md,
docs/STUDIO_EXPANSION_PLAN.md, docs/CLOUD_PLAN.md, docs/PLATFORM_CAPABILITIES.md and relevant pipeline docs.
Fetch and inspect current remote refs, including any newer Claude fixes. The planning branch is
codex/cloud-plan, originally based on codex/macos-native-app at 9e0aaee. Do not assume main exists, reset user
changes, revive an old PR branch, or blindly treat an older branch as the latest source. Work in an isolated
branch/worktree if necessary. Record the actual starting commit and how newer fixes were retained.

The native Mac app was tested at bc3ce2cdc23ccc7a495d2cfc2ed15aba3fe161e3. Its historical passing tests are
baseline evidence only, not verification of your new changes. The existing download site is
https://clipfoundry-studio.landryschreiner33.chatgpt.site . Preserve its project/address and working downloads;
it can link to the new authenticated studio once deployed and verified. It is not itself a media-processing
server. Do not replace it with a fake login or a button pointing to a nonexistent deployment.

Inspect these existing paths before designing replacements:

- clipfoundry/api.py, db.py, config.py, secure.py and jobs.py.
- clipfoundry/pipeline/{blueprint,render,quality,artifact}.py and related audio/framing/transcription code.
- clipfoundry/autopilot/{queue,host,brain,brain_routes,scheduler,publisher}.py and related handlers.
- clipfoundry/publish/common.py and existing OAuth/upload/consent paths.
- frontend/src/pages/{Brain,Create,ClipEditor,Posts,Settings}.tsx, App.tsx and styles.css.
- tests/test_audio_start_regression.py, tests/test_audio_packet_timing.py, fake_platforms.py,
  synthetic_media.py and the existing browser sandbox.

The current app is single-user FastAPI/React with global SQLite/settings/account data. Linux secret storage
has a base64 fallback unsuitable for cloud use. Publishing guards/OAuth callbacks are loopback-oriented.
Do not expose this unchanged process to the internet.

## 3. ArtCraft/FilmCraft integration decision

Research checked these upstream revisions; recheck and pin the exact compatible revision you adopt:

- ArtCraft: https://github.com/storytold/artcraft/tree/1f969a9224934a55417daf10359a6fb1458b63f4
- FilmCraft: https://github.com/storytold/filmcraft/tree/57dc82ea2046c2ec479ab4d4d8167d90e5500b49
- Separate services license:
  https://github.com/storytold/artcraft-services/blob/1d0425fcfe32677f16e796874e955b7ba0a71005/LICENSE.md

FilmCraft is the first candidate for timeline editing. Its main code is MIT OR Apache-2.0 with third-party
notices; it documents a browser/WASM UI and headless CLI/MCP. It is alpha. ArtCraft Studio concentrates on
interactive AI creation. The separate artcraft-services repository has restrictions on competing products;
do not copy it into the proposed publicly released product without an appropriate separate grant.

Inspect FilmCraft README.md, NOTICE, ATTRIBUTION.md, docs/web.md, docs/control-protocol.md, docs/architecture.md
and apps/filmcraft-cli/src/main.rs. Preserve required notices. Keep ClipForge's own robot icon and branding;
code licenses do not grant ArtCraft trademark rights. Do not assume optional generation services are free.

First produce a small repeatable integration experiment, not a whole-product fork:

- Import three synthetic or authorized files with different frame rates/audio rates.
- Assemble trims and reordered clips, one supplied B-roll insert, captions and optional supplied music.
- Save/reopen the project, undo/edit it, preview it in a browser and export on a headless Linux worker.
- Check output duration, cuts/captions, opening audio, stored AAC packet timing and preview/export parity.
- Measure build/runtime requirements, RAM, CPU, disk and throughput; prove ARM64 compatibility if selecting A1.
- Identify unsupported commands, project conversion loss and browser/mobile constraints honestly.

FilmCraft's stock browser build processes files locally and is single-threaded; hosting it is not cloud
processing. Implement a private media/project bridge and server-side worker. Use low-resolution proxies for
interactive editing and full originals for server rendering. Browser project files and local paths must map
to authorized immutable asset IDs, not arbitrary worker filesystem paths. Protect both the bridge and job API.

Put the engine behind a versioned adapter (capabilities, project import/save, apply validated edits, preview,
render, cancel, progress). Keep a normalized edit plan and time map with rational/integer timing. Commands must
be typed and allowlisted; a model/skill must not get an unrestricted shell or arbitrary engine file/network
access. Do not expose raw MCP/control ports publicly or let the editor publish directly to social platforms.

Use the tested integration if it passes. Where it fails, keep the existing FFmpeg renderer for supported
operations, with a documented capability limit. Do not silently render a different edit or rebuild an NLE from
scratch. Keep the implementation useful while documenting any genuinely blocked editor feature.

## 4. Cloud, identity and persistent data

Implement an explicit cloud mode while preserving local mode. Prefer a small deployment: HTTPS reverse proxy,
authenticated API, private persistent storage and a durable worker. Avoid Kubernetes and extra managed services
unless measured requirements justify them. Proposed pilot is an eligible Oracle Always Free ARM VM plus free
Supabase Auth, subject to real account availability, current allowances and actual throughput. These accounts
are not connected yet. The detailed current proposal and its limitations are in docs/CLOUD_PLAN.md.

- Owner-only Google sign-in through a proper identity provider; registration off. Authorize a configured stable
  owner subject, not a user-supplied email/header. Validate issuer, audience, signature, expiry and subject.
- Persist an identity/workspace model. Scope projects, media, Brain, skills, layouts, jobs, settings, social
  accounts, approval records and OAuth state. Never switch a process-wide data path based on a request.
- Enforce authorization on APIs, job events, media ranges, thumbnails, previews, exports and downloads. Hiding
  navigation is not authorization. Private objects must not be exposed through public static directories.
- Secure sessions, logout/expiry/recovery, CSRF where applicable, explicit allowed hosts/origins, login/upload
  rate limits, and OAuth state/PKCE bound to the initiating session/workspace. Use configured HTTPS callbacks.
- Add encrypted Linux credential storage with an independently managed key; fail closed without it. No base64
  or plaintext fallback in cloud mode. Do not put social tokens in browsers, model prompts or render workers.
- Harden URL ingestion for cloud: desktop allowances for owner-typed private URLs must not expose cloud metadata,
  loopback or private networks. Check redirects/resolution and sandbox media subprocess access.
- Use resumable uploads, integrity checks and private streamed playback. Show honest upload progress. Accepted
  jobs survive closing the browser; unfinished uploads resume rather than being shown as ready.
- Persist server-side projects, briefs, preferences, layouts and histories. A second logged-in device sees the
  same work. Use revisions/conflict handling so concurrent tabs do not silently overwrite newer edits.
- Keep scheduling responsive during heavy work. Bound CPU threads, memory, scratch disk, queue size, runtime,
  subprocess privileges and concurrency. Start with one heavy processing slot and deliberate CPU configuration.
- Build idempotent job completion, leases, cancellation, backoff, restart recovery, readiness and useful logs.
  Do not silently downgrade the owner's selected model/quality when hardware is unavailable.
- Provide backup/restore and configurable retention with a clear preview of what is deleted. Keep originals
  unless an explicit retention policy allows deletion; regenerable caches may be cleaned separately.

An isolated single-owner deployment may retain SQLite on local persistent disk. Public multi-user service
requires fully verified tenant isolation, fair scheduling, cost controls and an appropriate database/storage
migration. Test two synthetic identities now even if only the owner is admitted in production. Public signup
must remain off until cross-workspace access, private files, jobs, account deletion and recovery are verified.

## 5. Multiple connected social accounts

A ClipForge login identifies the person; connected YouTube channels and TikTok accounts are publishing
connections inside that person's workspace. Support multiple connections on the same platform simultaneously.
This is required in the private owner release, not deferred until public signup.

- Inspect the current accounts table: platform is its primary key. Replace that single-account assumption with
  stable connection IDs, workspace ownership, platform and the provider-confirmed external channel/account ID.
  Migrate old accounts without overwriting tokens, history or existing approval/destination bindings.
- Connect another account without disconnecting the previous one. Show verified channel/account name, avatar,
  platform, user nickname and connection health. Verify the actual target channel after OAuth, including a
  YouTube Brand Account where supported; a shared Google email is not a channel identity.
- Deduplicate reconnects to the same confirmed account within the same workspace. Reconnect must update that
  connection, not create accidental duplicates or silently change an existing destination.
- Store and refresh encrypted tokens per connection with appropriate locking. Bind OAuth state to workspace,
  user, intended add/reconnect operation and connection. Revoke/disconnect without affecting unrelated accounts.
- Give each project/clip an explicit destination selector. Permit one or several selected destinations, with
  separate audience, metadata, kids options where required, schedule and status per destination. New connections
  must never become automatically selected for existing approved work.
- Model one checked media artifact with distinct destination publication jobs. Idempotency, upload sessions,
  approval/consent, cancellation and reconciliation must include the connection identity. A successful upload
  to channel A must not mark channel B complete; retrying B must not upload again to A.
- Bind automatic YouTube requests to the explicitly selected connections and permitted outputs. Adding or
  changing a destination needs corresponding consent; no workspace-wide implicit upload grant. Preserve
  TikTok's supported per-post flow and explicit privacy/account confirmation.
- Keep spacing and account-specific limits per destination while also honoring shared API-project/app quotas,
  provider-wide waits and budgets. Do not treat multiple accounts as a way around platform limits.
- On expiry/disconnection, pause that destination with an actionable message. Do not silently reroute it. Changing
  a UI default must not change existing queued/approved/started posts or their uncertain upload sessions.
- Allow account filters in the library, queue/calendar and reports. Defaults may prefill future projects only;
  always display the real destination before upload. Preserve selected accounts across device sessions.

## 6. Rename the product to ClipForge

Use **ClipForge** consistently in the shell, login, browser title, navigation, onboarding, dialogs, notifications,
help, generated export labels and newly built installer/display metadata. Update the download website's visible
brand and relevant legal/product wording as part of the reviewed rollout, not by altering immutable old releases.
The owner authorizes the product rename; older instructions to retain the ClipFoundry display name are superseded.

Keep the canonical robot icon consistent across app, website, favicon and platform-review materials. A rename
alone is not a request to replace that icon or claim an ArtCraft affiliation. Prepare matching OAuth/TikTok app
branding and a clear checklist of provider-console changes requiring owner access; do not claim those external
changes or approvals have happened without verifying them.

Do not perform a blind global code rename. Existing clipfoundry imports, CLIPFOUNDRY_* environment variables,
profile directories, bundle/keychain identifiers, database identities, OAuth client IDs and historical links
can remain internal compatibility names. If any must change, provide a tested migration and aliases, keeping
all projects, Brain data, connections, approvals and history. Never create an empty new profile just because the
label changed. Preserve the existing website address and repository unless a separate address move is chosen;
use redirects/compatibility links for any explicitly migrated routes. No domain purchase is authorized.

## 7. Simple creation flow and Brain integration

Home should lead with exactly two creation choices: **Make clips** and **Make a YouTube video**. Inside Make clips,
choose **Highlights** or **Full stories**. Full stories must share the source intake, library, review, accounts,
queue and publishing controls with other clips. Do not create a third standalone product/page hierarchy for it.

Follow with upload/link, a short brief where needed, a preview and a clear next action. Preserve existing routes
and data with aliases if navigation changes. Use simple words, autosave, actionable errors and advanced options
in expandable sections. Keep Office as an optional truthful activity view. A repeat project can use its saved
style instead of answering the same questions again.

For Full YouTube video, support multiple files and optional supplied audio/images. Ask at most four required
questions, prefilled from the chosen Brain style:

1. What is this video about and who is it for?
2. Desired duration/aspect ratio, including “use your judgment.”
3. Editing style/pacing, with caption and music choices when useful.
4. Must-keep moments and anything to remove or avoid.

Ask only necessary follow-ups. Offer “Use my saved style.” Summarize the brief before creation, allow editing,
and show “Remember this style” clearly. Save remembered preferences to Brain with scope, source, version and
supported typed values. A project-only answer must not change unrelated projects. Existing enabled supported
Brain notes apply without reintroducing a separate approval gate.

Define deterministic precedence: explicit project/edit choices; selected style/skills and relevant saved Brain
preferences; then Settings/defaults. Surface same-level conflicts rather than silently choosing unrelated
rules. Relevant examples may supply supported measurable guidance; do not claim visual imitation or training
without implementing and testing it. Use actual source/transcript context when retrieving relevant material.

Carry effective guidance and revision IDs through analysis, edit planning, framing, captions and rendering,
including retries and resumed jobs. Show “Used from your Brain” with concrete resulting decisions and links to
the contributing entries. Distinguish enabled, applied, overridden, unsupported and reference-only content.
A read counter or an animation is not proof of use. Editing guidance must visibly change an actual plan/output.

Never turn reuse/permission text, login secrets or social account data into Brain knowledge. Treat transcripts,
uploaded examples and retrieved content as data, not authority to execute tools or override publishing rules.
Any external-model transmission must follow the owner's configured opt-in and show what data leaves the server.
Use the existing provider abstraction and budgets; do not add a paid required model. If a semantic feature needs
a model that is unavailable, explain it and provide manual boundaries/edits rather than fabricate completion.

## 8. Clips: Full stories mode

This is a mode within Clips. Example: a long video contains six narrated stories; the owner chooses
Make clips → Full stories and receives six separate vertical clips, each containing its whole story.
It uses complete-story detection instead of highlight scoring. It must not compress each story into a teaser.

- Process the entire recording with timestamps and overlapping analysis chunks. Reconcile boundaries and
  duplicates globally so a story crossing a chunk boundary stays intact.
- Identify story openings, context, development and endings using transcript meaning plus audio/visual cues.
  Silence alone is not a story detector. Preserve complete sentences, setup, reveals and payoff.
- Include every distinct story, not just high-scoring ones. Show incomplete/uncertain candidates for review;
  do not silently discard them or promise perfect semantic detection.
- Separate introductions, ads, transitions and unrelated material. Do not force every second into a story.
- Show chronological cards with source start/end, duration, grounded title and completeness/confidence.
  Allow split, merge, trim, reorder, include/exclude, preview and one batch-create action. These controls must
  not add a mandatory manual step for every confident, eligible clip already covered by an explicit YouTube
  creation/upload request; uncertain boundaries or unsupported destinations need a clear separate status.
- Support multi-minute stories without forcing 15–60-second clips. Keep independent duration/format/quality
  policies per output mode; do not weaken existing Shorts checks globally.
- Default both Clips modes to a 9:16, 1080×1920 vertical composition suitable for TikTok and YouTube, with
  readable captions and destination-aware safe areas. Preserve story content while reframing; do not merely
  center-crop the entire video. Follow measured subjects/activity smoothly, handle scene changes and multiple
  speakers, and allow fit/blur-background layouts, manual keyframes and deliberate fixed-framing overrides.
- Preserve the complete story even if it exceeds a destination's current duration limit. Check current official
  platform rules and account/API capabilities at implementation and again where runtime capability checks apply.
  A vertical clip is not automatically a YouTube Short. Label eligibility per destination accurately.
- Keep a full-story master export. If it is too long for TikTok or Shorts, explain this and offer the complete
  YouTube video where supported, download, or an explicitly requested split into parts. Never silently truncate,
  speed up, discard, relabel or split a whole story just to force publication. Only make parts after the user
  chooses that alternative, preserving the full-story version and coherent boundaries.
- Reuse source decoding/probes/transcription. Cache by media hash, settings/model version and guidance revision.
- Store a time map and final transcript for each output. Avoid clipping words and artificial fades over speech.

## 9. Full YouTube video mode

Produce a real, editable video from supplied assets:

- Durable media bin, source metadata, transcript where present, thumbnails and efficient proxies.
- A proposed narrative/sequence outline based on the brief and source evidence, then an assembled rough cut.
- Clip ordering, trim/split/reorder, keep/remove sections, simple transitions, titles, optional captions and
  user-supplied B-roll/music. Apply real audio gain/ducking controls without damaging speech.
- Default 16:9 with explicit alternatives. Duration target is a preference with an explanation if source
  content cannot meet it. Do not manufacture statements, narration or missing story endings.
- Preview, save, undo/redo, project versions, autosave/recovery and simple changes such as shortening an intro
  or keeping a specified segment. Resolve requested changes into validated edits, not unconstrained execution.
- Render from full sources on the server. Support cancellation/progress and exact re-opening of the saved plan.
- Download final media and captions/project interchange where supported; show unsupported effects before export.
- Provide a distinct publishing decision after preview, with account/audience/time choices and existing guards.
  Do not inherit a prior clip submission's consent for an unrelated assembled project.

Optional generated assets are a later opt-in integration with disclosed provider/cost. The core full-video
workflow must work with supplied footage; do not make generation credits a hidden dependency.

## 10. Skill library

Start with declarative editing skills/templates, not executable extensions. Support Markdown, text and a
versioned JSON schema. A skill has a name, description, version, applicable modes, optional topic scope and
supported structured preferences or edit-plan constraints. Store original content privately with provenance.

Import, inspect, edit, enable/disable, select for a project, export and delete skills. Preview the parsed effect
before enabling it. Show unsupported instructions clearly. Recognize supported guidance from a Claude-style
SKILL.md but never claim full Agent Skills compatibility or execute bundled scripts automatically.

Limit input size/count, reject invalid encodings and unsafe paths, and escape rendered content. Avoid ZIP
imports initially; if supported, reject traversal, symlinks, decompression bombs and executable payloads.
Imported text cannot request secrets, execute code, change accounts, authorize publication or modify another
workspace. Test malicious and contradictory examples. Normal editing skills must actually affect the plan;
a file library with no downstream effect does not satisfy this requirement.

## 11. Redesign the interface for the new product

This is an information-architecture and visual redesign, not just a color change or extra tabs in the old shell.
Build a coherent ClipForge studio that makes creation, review and destination selection obvious.

Suggested navigation, refined after auditing actual flows:

- Home: two clear creation buttons, recent projects, real running work and only actionable problems.
- Projects/library: clips and full videos with recognizable thumbnails, search/filter and useful status badges.
  Clips contains Highlights and Full stories modes; avoid duplicate libraries for each mode.
- Brain: styles, notes, examples and skills, with a simple editor and the existing graph as an optional view.
- Publishing: queue/calendar, exact destination labels, review and per-account filters.
- Accounts: connect/reconnect multiple YouTube/TikTok accounts with clear identity and health.
- Office: optional robot activity view and robot naming.
- Settings: appearance, saved layouts, defaults and advanced settings.

Use a consistent design system: intentional typography, spacing, surfaces, borders, colors, controls and icons.
Give previews and the current task visual priority. Group related actions; reduce repeated forms and needless
clicks. Keep advanced editing available without exposing a professional editor's entire menu to a beginner.
Include useful empty states, real progress, autosave indicators, retry/reconnect paths and clear success messages.
Do not show unfinished integrations as functional controls or simulate jobs to make a screen look alive.

Create a route map and design specification first, then implement and inspect real screens with realistic
content at desktop/tablet/phone sizes. Keep backwards-compatible routes. Capture before/after screenshots and
a short recording of upload → mode/style → preview → chosen destination. Do not stop at a design mockup.

Add light/dark/system theme, selected accent colors, density and reduced motion. Provide resizable, reorderable,
hideable panels and saved Create/Review/Office layouts. Offer Reset layout and prevent every useful panel from
becoming inaccessible. Persist account preferences and separate desktop/tablet/phone layouts with schema
versions. A phone must not inherit off-screen desktop coordinates. Keyboard/focus, contrast, labels, touch
targets, readable captions and the full mobile navigation must work, not just shrink to fit.

Keep the canonical robot icon at design/tiktok/app-icon-dark.png consistent with website/favicon/TikTok identity.
Test the embedded editor's isolation headers, media auth and OAuth popup/redirect behavior together; browser
security headers must not silently break sign-in. Keep decorative animation away from essential editing controls.

## 12. Let the owner name the robots

Every robot, including managers and the Brain robot, can have an editable display name. Provide a clear Rename
control on its detail card and/or a simple Team list; do not require code or file edits. Save and offer Reset name.
Show the custom name together with its role, for example “Nova · Editor,” so the office stays understandable.

- Persist names per workspace using stable existing robot/role IDs. A name is display metadata; it must never
  change a worker ID, job assignment, permissions, manager relationship, event routing or handoff destination.
- Sync names across devices and restarts; scope reads/updates to the owner's workspace. Set a reasonable length
  limit, trim blank input, support normal Unicode and render names as text. Reset restores the default label.
- Use names consistently in the office, tooltips, team lists, accessible labels and current activity panels.
  Keep historical events/provenance intact by resolving stable IDs rather than rewriting event records.
- Keep role labels visible even if two robots receive the same name. Renaming must not break search, filtering,
  robot selection or navigation from an activity item to its robot.
- Preserve truthful worker activity, department attendance, managers, handoffs and off-duty lounge behavior.
  Changing a name or theme must not invent work or affect processing. Respect reduced motion and paused views.

## 13. Audio, publishing and cost guarantees

Do not regress the uploaded-audio fix. The earlier defect was damaged stored AAC timing that ordinary FFmpeg
parsing hid, so local playback sounded normal while YouTube's processed copy failed at the beginning. Preserve
source samples/clocks, rebuild the FINAL audio clock after all filters and validate stored packet timing with
timestamp auto-repair disabled. Keep constant bounded gain from whole-edited-clip measurement, downmix/limiter
rules, normalization-off, track choice and no unintended speech fades or startup pumping.

Run opening/quiet/middle/end audio regressions on encoded output from every engine. Include mixed sample rates,
channel layouts, offsets, variable frame rates and concatenation. Check raw timestamps, decoded audio continuity,
source/output alignment and fake-platform transfer bytes. Neither a browser preview nor a waveform alone proves
upload correctness. No actual YouTube/TikTok transcode is verified without an authorized real upload.

Preserve exact-file hashes and quality reports, metadata grounding, audience/account/kids binding, valid reuse
assertions, cancellation, Pause publishing, platform rate limits and Retry-After. A re-render needs fresh checks
and applicable approval. Never mutate or repeat started/uncertain uploads. Account-specific scheduling reserves
slots atomically and respects spacing, timezone/DST and platform restrictions. “As many as allowed” never means
bypassing platform limits or posting every output at the same time.

Existing input-scoped Make & upload clips behavior stays intact for qualifying YouTube clips. TikTok retains
its supported per-post flow. New mode publishing must have explicit applicable consent and platform eligibility;
do not assume long stories fit TikTok limits. Keep unsupported destinations disabled with a useful explanation.
All renderers feed the same ClipForge publishing gate; do not use upstream editor upload buttons as a bypass.

Avoid repeated full-file processing and model loads where safe. Measure stage timing/cache hits/peak memory,
queue latency and storage use. Bound caches, retry loops, analysis context and output concurrency. Keep AI/media
workers separated from social credentials. Before any paid proposal, measure the actual source/output workload,
quality settings, storage/egress, startup and retry costs. Billing alerts alone are not spending caps; enforce
admission budgets, conservative in-flight reservations and runtime limits. Do not claim five source hours equal
five billed compute hours or that a free server can support the workload without measurement.

## 14. Tests and acceptance evidence

Use isolated temporary profiles, synthetic media and fake platforms. Do not test mutations against the owner's
running database/accounts or publish real videos. Follow repository-required checks. Add meaningful behavioral
regressions rather than tests that merely repeat implementation details.

Required evidence:

- Auth: owner session, expired/revoked session, wrong identity, direct/range media request, OAuth state and
  negative cross-workspace ID access. Private media/Brain/skills/jobs must never leak across users.
- Cloud: interrupted upload/resume, process restart, worker crash, cancellation, bounded disk, backup/restore,
  second-device project resume, and conflicting tab edits.
- Multiple accounts: at least two fake YouTube channels and two fake TikTok accounts in one workspace, including
  two channels associated with one Google identity where supported. Verify add/reconnect/disconnect isolation,
  concurrent token refresh, correct token/destination binding, partial multi-destination success, no duplicate
  retry to the successful account, shared/per-account limits, account filtering and old-account migration.
- Rebrand: an existing ClipFoundry profile opens with the same projects, notes, accounts and historical approvals
  under the ClipForge label. Old routes/settings aliases still work. No accidental empty profile or lost secrets.
- Robot names: save/reset, Unicode and unsafe-text rendering, duplicate-name role labels, workspace isolation,
  reload/device sync and unchanged real handoff/worker IDs.
- Brain/skills: a saved preference changes a real plan; project override wins; reference-only claims stay
  honest; guidance revisions survive retries; malicious skill text cannot execute or alter publishing.
- Stories: multiple stories, story longer than Shorts bounds, story crossing chunks, one story, no stories,
  incomplete final story, ambiguity, ads/intro gaps and non-English material where supported. Compare expected
  labeled boundaries with actual proposals and inspect rendered starts/ends, not just JSON shape. Test that
  Full stories is reached inside Clips, produces complete 9:16 clips with safe captions/moving framing, and
  preserves an over-limit master without silently splitting it or falsely marking it platform-eligible.
- Full video: mixed files, manual timeline edits, save/reopen, proxy/full-source mapping, caption/time-map parity,
  missing source, cancellation and a successful headless render through the chosen engine.
- Media: AAC raw clocks/decoded opening audio, transitions without unintended gaps, VFR/source offsets,
  real subject motion where applicable, and fresh hash-bound gate checks for every output format.
- Publishing: exact transferred bytes, collision-free automatic slots, Retry-After, restart/unknown outcomes,
  changed-file rejection and no duplicate posts. No silent audience/account changes.
- UI: login/upload/brief/preview/export on desktop and phone, keyboard navigation, theme/layout persistence,
  reset/recovery, no horizontal overflow and useful empty/loading/error states.
- Capacity: a representative daily batch exceeding five source hours on the actual proposed host, with full
  stage timings, output count/durations, peak RAM/disk and realistic headroom. If the host/footage is unavailable,
  supply the benchmark harness and explicitly mark throughput unverified instead of extrapolating a tiny clip.

Run the required Python fast suite; run relevant real-media/restart suites for pipeline/worker changes.
Build frontend/src and commit generated frontend/dist as required by this repo. Run write-capable UI tests only
in the sandbox; the existing owner-app e2e path stays read-only. Record actual commands/results/source commits,
not old test counts presented as new verification. Save screenshots and a short recording of the real flows.

## 15. Delivery order, cutover and handoff

Implement in this order, with a working checkpoint after each phase:

0. Verify newest baseline, investigate editor/license, run the bounded FilmCraft integration experiment, and
   prepare the ClipForge route/design map and compatibility-aware rename plan.
1. Cloud mode, identity/workspace ownership, encrypted secrets, private uploads/media, durable jobs, multiple
   social connections and migration. Keep public ingress off until authentication/storage checks pass.
2. Implement the ClipForge shell and two creation entries, guided brief, saved Brain styles and declarative
   skill library with real downstream use. Preserve data, existing routes and account/approval identities.
3. Add Clips → Full stories: complete-story analysis, vertical composition, review and batch output with correct
   destination eligibility. Preserve Highlights as the other Clips mode.
4. Full-video assembly, tested editor adapter, manual adjustments, preview and validated server render.
5. Finish redesigned screens, theme/layout sync, robot naming, responsive views and multi-account publishing UX.
6. Full regression pass, real capacity measurement when available, migration/cutover and deployment handoff.

Back up and migrate a copy of desktop data; preserve bytes, hashes and history. Mac Keychain/Windows DPAPI
secrets cannot simply move to Linux; reconnect accounts securely. Before live cutover, pause the old publisher
and reconcile in-flight/uncertain uploads. Never run two schedulers against copies of the same active queue.
Keep a rollback path without replaying already-published jobs. Update privacy/storage/retention disclosures.

For each checkpoint report implemented/partial/blocked status, tests actually run, screenshots where relevant,
known limitations and the next action. Update AI_HANDOFF.md, AI_CHANGELOG.md, .clipfoundry/ai-change-log.jsonl
and docs/IMPLEMENTATION_STATUS.md. Provide setup/run/restore commands, environment-variable names (no secrets),
engine pin/notices, migration instructions and a concise owner guide.

Continue independently where authorized. Do not ask the owner to decide routine architecture choices. Ask
only when a product choice truly cannot be inferred, account setup is required, or actual costs/external
publication need authorization not already granted in the session. Do all preparatory work first so any
approval concerns a concrete result.
Do not merge, spend money, delete owner data, publish real posts or enable public signup by implication.

## 16. Concrete implementation and acceptance contract

Treat the following as the implementation defaults and acceptance requirements, not optional inspiration.
Preserve existing explicit owner choices during migration. You may adjust an internal name or equivalent
technical design after inspecting the code, but document the reason and keep the same observable behavior.
These defaults are product decisions for this build, not claims about current platform limits or hosting prices.

### 16.1 Exact screen responsibilities

| Screen | Required content and actions | Must not happen |
| --- | --- | --- |
| Sign in | ClipForge name/icon, Continue with Google, sign-in error/retry, authorized-owner access | Private project names/media exposed before authorization; public signup enabled |
| Home | Make clips, Make a YouTube video, recent projects, real active jobs, actionable problems | A third top-level Full stories creation button; fake progress or empty bot activity presented as work |
| Make clips | Highlights / Full stories selector, file/link input, saved style, chosen destinations, creation action | Repeating the full-video questionnaire for a simple clip; a file upload silently authorizing publishing |
| Make a YouTube video | Multi-file media bin, four-question brief, saved style, Build my video | A professional timeline shown before a beginner can upload and describe their video |
| Project review | Large preview, outputs/sequence, transcript, Used from your Brain, simple edits, download/publish | Hiding which saved guidance applied; marking a preview-only change as a finished render |
| Projects | One library with Clips / Full videos filters, thumbnails, source/project names, status, search | Separate disconnected libraries for Highlights and Full stories |
| Brain | Styles, Notes, Examples, Skills; searchable list/editor; optional Graph view | A graph as the only way to add/edit a preference; permission forms becoming knowledge |
| Publishing | Queue/calendar, per-destination rows, account filter, scheduled time/timezone, real status/retry | A platform icon used instead of an exact channel/account identity |
| Accounts | Add YouTube account, Add TikTok account, connection cards, Reconnect, Disconnect | Connecting account B replaces account A |
| Office | Real department/robot activity, Team list, robot card with Rename and Reset name | Custom names changing roles, manager routing or worker behavior |
| Settings | Appearance/layouts, default style, storage/retention, advanced configuration | Credentials displayed in plain text; resetting layout deletes project edits |

Preserve the current router where practical. Map these logical screens to actual routes in a checked-in route
map, including aliases for old links. Browser Back, reload, deep links, unsaved edits and sign-in returns must
work. Do not invent a second navigation system inside the embedded editor.

### 16.2 Exact Clips journey

1. Choose Make clips. The two mode options are Highlights and Full stories, with one-sentence descriptions:
   “Pick the strongest short moments” and “Make one complete clip for each story.” Default a new profile to
   Highlights; remember a user's later explicit mode selection without changing existing projects.
2. Add a file or supported recorded-video link. Show source name, probed duration and upload/import status.
   For uploads show bytes received; resume a failed transfer without creating duplicate source/project rows.
3. Choose My saved style, another named style, or Settings defaults. Keep framing/captions under optional
   Customize controls. For Clips the default output is 9:16, 1080×1920; apply supported Brain choices and
   explicit per-project overrides. Full stories has no mandatory target clip length.
4. Choose Make clips only or Make & upload clips. For the latter, show selected verified YouTube destinations,
   audience, applicable kids choice and the existing source-specific reuse assertion/confirmation once.
   Reuse an already-valid source assertion rather than asking again for every generated clip. Display what
   can upload automatically and which TikTok destinations still require review; do not imply TikTok auto-consent.
5. Process on the server, save the plan and guidance snapshot, render and check each output. The owner can leave
   after the input finishes uploading. Preserve cancel/pause behavior and show real failure reasons.
6. Show one output card per highlight/story, with duration, preview, completeness where relevant and destination
   eligibility. Offer Download, Edit, and the applicable publishing action. Confident, checked outputs already
   covered by the explicit YouTube request can proceed without a newly introduced per-clip approval ceremony.
   Hold uncertain story boundaries for adjustment; do not present them as confidently complete.

Full stories must preserve narrative material. Default to a continuous source interval for each story, keeping
its opening, context, reveal and ending. Do not remove internal sentences as “low virality” or speed up speech
to meet duration targets. User-requested cuts remain editable revisions with an updated time map and checks.
Any safe trimming of boundary silence must not clip speech. Mark intro/outro/ads outside stories separately.

### 16.3 Exact full-video journey and creative brief

Start with a media bin. Accept supported video files and optional supplied audio/images; show upload status,
file name, thumbnail, duration and drag-to-reorder. Unsupported files get individual actionable errors while
valid files remain. Do not assume every file has audio, every video shares a frame rate, or file order is the
final story order. Source files remain immutable; edits reference them.

Use these four grouped questions, prefilled from the chosen style, with optional advanced fields:

| Question | Data to save | New-profile default |
| --- | --- | --- |
| What are we making, and who is it for? | Video type, intended audience, short goal | General YouTube video; optional goal text |
| How long and what shape? | Target duration or automatic, aspect ratio | Use your judgment; 16:9 |
| What should it feel like? | Calm/storytelling, balanced or energetic; captions; supplied music choice | Balanced; captions from Settings; no added music unless selected |
| What must stay or go? | Must-keep assets/ranges/topics, avoid/remove requests | Nothing excluded or required beyond keeping coherent meaning |

Show Remember this style beside the brief, not hidden in Settings. Enable it for a new full-video brief with a
clear explanation and allow turning it off before submission; respect a previously saved opt-out. The user may
name the style or accept a generated editable name. Remember editing choices, not this project's private source
paths, unique must-keep timecodes, platform consent or credentials. Keep project-specific constraints in the
project. Save a revision rather than silently overwriting a style used by older projects.

Build my video creates a saved outline and a rough-cut sequence, then a preview. Show the outline, Used from
your Brain, simple trim/reorder/include controls and an Advanced editor action using the tested editor adapter.
Allow “Shorten the introduction,” “Keep this section” and “Remove this clip” where the underlying operation is
supported. Convert requests to a proposed validated edit, explain an unsupported request and keep the old version
until the replacement saves. Never simulate success when the timeline did not change.

Save/reopen must reproduce source order, trims, captions, framing, gains, transitions and supplied music.
Changing an edit creates a new revision; the previous finished artifact stays visible until the new render
passes checks. Download and Publish refer to a clearly identified finished version. Full-video publishing uses
its own explicit request, not an unrelated short-clip grant. Show the account and actual output before consent.

### 16.4 Brain and skills must have a testable effect

Persist both the source guidance and the resolved values used for a job. Required records include guidance
entry/revision IDs, scope, supported fields, effective values, overridden values/reasons and the project/plan
revision. Show examples such as “Lower captions — from My story style” or “Energetic pacing — overridden by
this project's Calm choice.” Do not claim every note influenced every output.

Changes to Brain entries affect new plans. Existing queued/rendered/approved projects keep their saved guidance
snapshot unless the owner chooses Apply latest style and creates a new plan/render revision. Resume/retry of the
same revision must not quietly pull new notes and produce different approved bytes.

Provide one bundled editable example skill and one documented import schema. Use a schema version, skill ID,
name, version, applicable workflow/mode, original instructions and parsed supported preferences. Import into a
preview showing recognized fields and unsupported text; explicit enable makes supported guidance available
without a second approval queue. Allow project-specific enable/disable and export of the same versioned format.

Implement a declared capability registry so the parser, editor and renderer agree on supported fields. A skill
can influence only implemented editing choices; it cannot change publication consent, secrets, quotas or worker
privileges. Unknown fields remain visibly unsupported and do not disappear on export. A helpful name or an
uploaded Markdown file alone does not count as a working skill.

Required behavioral test: save a relevant supported lower-caption preference, create a new plan, verify its
resolved field and actual caption placement, then override placement in the project and verify the override.
Repeat after restarting the service. A renamed note or increased read count is not acceptable evidence.

### 16.5 Data and API contracts to carry through the existing code

Adapt existing models rather than creating a parallel app. Document migrations and map legacy rows to stable
identities. These are required relationships/fields, not a mandate to add one table for every row below:

| Concept | Required identity and data |
| --- | --- |
| Workspace | Stable ID, authorized owner identity, settings/limits; never derived from an untrusted request path |
| Social connection | Stable ID, workspace ID, platform, provider-confirmed account/channel ID, encrypted credential reference, scope/health; unique external identity per platform/workspace |
| Asset | ID, workspace/project ownership, content SHA-256, private storage reference, probe metadata, proxy-to-original mapping |
| Project | ID, workspace, workflow clips/full_video, clip mode highlights/full_stories where applicable, input asset IDs, brief/style snapshot, revision |
| Story proposal | Stable ID, source asset, start/end in an explicit timebase, completeness/confidence/reason, included flag, manual-boundary revision |
| Edit plan | Project revision, source time ranges, output settings, supported edits, framing/captions/audio parameters, guidance snapshot, engine capability/version |
| Artifact | Immutable ID, project/plan revision, exact media hash, time map/final transcript, codec/duration/dimensions, quality report for those bytes |
| Destination publication | Artifact and connection IDs, explicit audience/options/text, schedule/timezone, consent binding, idempotency key, upload session, outcome/reconciliation state |
| Skill/style | Workspace-scoped ID, schema/content revision, supported guidance, origin, enabled state and applicable modes |
| Appearance/robots | Workspace/user preference ownership, schema version, device-class layout, stable robot role ID to display-name mapping |

API mutations require authenticated ownership and validated typed inputs. Do not trust workspace IDs merely
because the browser sent them. Media reads, event streams and background-job claims use the same ownership
rules. Use revision/ETag-style checks for concurrent edits and return a resolvable conflict instead of last-write
loss. Use request idempotency for submission/publish actions, while allowing an explicitly new project later.

An editor/worker receives asset references restricted to its job, validated plan revision, requested output
settings and scoped output locations. It never receives social tokens or arbitrary server paths. Returned media
must be probed, hashed and checked; claimed success from an engine is not sufficient. Include engine/version in
cache identity. Preserve metadata and timeline conversion errors rather than dropping them silently.

On legacy-account migration, do not change existing signed/hashed approvals merely to fit the new schema.
Resolve historical account references through a verified mapping; if binding cannot be preserved, hold only
the affected unstarted work with an explanation. Never rewrite an active/uncertain upload's destination.

### 16.6 Job states and actionable failures

Keep one durable source of truth for state. Reuse existing internal enums where suitable and document their UI
mapping. The user must be able to distinguish receiving the file, waiting for a worker, analyzing, planning,
rendering, checking, ready, needing input, canceled and failed. Publishing separately distinguishes review,
scheduled, transferring, platform processing, confirmed result, waiting for the platform and outcome unknown.
An input-upload percentage is not render progress, and accepted bytes are not proof platform processing finished.

Examples of correct messages/actions:

- Interrupted input: “Upload interrupted. Resume upload.” Keep received chunks within the configured retention.
- Rejected account token: name that account and offer Reconnect; other eligible destinations may continue.
- Story exceeds a destination limit: name the account/limit and offer the full master plus supported alternatives.
- Model unavailable: offer configured alternatives or manual editing; never say semantic story analysis succeeded.
- Storage full: stop admitting work, preserve existing media/jobs, show usage and safe cleanup options.
- Unknown upload result: retain the existing session and expose reconciliation; never automatically start over.

Retry buttons resume a supported stage safely. An expired lease must not let two workers commit two successful
artifacts/publications for the same job revision. Cancellation stops future work and cleans only job-owned
scratch files; it must not erase original footage or past published history.

### 16.7 Concrete visual defaults and robot naming

Use the current robot identity in a cleaner studio shell. Starting design tokens: dark background #0B0D14,
surface #151A25, primary text #F5F6FA, muted text #A8B2C5, violet accent #9A7CFF and success teal #46D6C4.
Create a separate coherent light palette; default theme follows the system. Check actual rendered contrast
(minimum 4.5:1 for ordinary text), including selected, disabled and error states. Do not use color alone for status.
Use a readable system/locally bundled sans-serif font, 16px base body text, an 8px spacing system and restrained
borders/shadows. Pixel art belongs primarily in the office; essential controls and labels stay easy to read.

Desktop starts with a roughly 232px collapsible sidebar and 64px top bar, with flexible content and a large
preview. Small screens use a navigation drawer, stacked cards and persistent access to the main task action.
Test 1440px, 1024px, 768px and 390px widths, plus 320px overflow. Touch actions should have at least 44×44px targets.
The editor may offer a simplified mobile view instead of shrinking all desktop panels into unreadable columns.

Provide theme/system choice, accent palette, comfortable/compact density, follow-system/reduced motion and
saved layouts. Keep separate desktop and small-screen layout records. Reset layout changes only layout settings,
not style guidance, current edits or robot names. Store preferences server-side with optimistic local feedback
and a visible save failure/retry if persistence fails.

For robot names, use a single-line field allowing 1–32 Unicode code points after trimming. Reject blank names
with an inline explanation; Reset name explicitly restores the default. Render as text, never HTML. Duplicates
are allowed with roles still visible. Example: rename the Editor robot to Nova; the UI shows “Nova · Editor”
while all backend events/handoffs retain the original robot ID. All existing robots, including managers, remain
available; do not replace the office with renamed generic progress cards.

### 16.8 Required end-to-end acceptance scenarios

Build reproducible fixtures/harnesses and record actual results. Fixture times and mocked platform limits below
are test inputs, not claims about real YouTube/TikTok limits. Use fake accounts/providers for mutations.

| ID | Scenario | Pass condition |
| --- | --- | --- |
| CF-01 | Owner signs in on desktop and phone; another synthetic identity requests its project/media | Owner sees the same project; other identity receives no project/media/private metadata |
| CF-02 | Close the browser after upload; restart a worker during processing | Durable job resumes without duplicate completion; owner returns to the saved result |
| CF-03 | In Clips, switch Highlights to Full stories | Same intake/library/queue; full-story cards preserve narrative rather than a teaser duration target |
| CF-04 | A labeled 12-minute recording has three stories and intro/outro gaps | Exactly three complete included story outputs; gaps separately identified; all three vertical |
| CF-05 | One story crosses an analysis chunk boundary | One continuous story proposal/output, not duplicate fragments or a missing ending |
| CF-06 | Mock one destination limit below a complete story's duration | Full master preserved, accurate destination restriction, no silent split/speed-up/truncation |
| CF-07 | Save lower-caption guidance; create; override; restart and resume | Actual plan/output follows the saved snapshot and explicit override; provenance is correct |
| CF-08 | Import an editing skill with a valid preference and a shell/secrets instruction | Valid preference can apply; dangerous instruction never executes; unsupported content is visible |
| CF-09 | Assemble three mixed-rate videos plus a supplied image/music file; trim/reorder; save/reopen | Preview and server export match the saved plan, captions and audio; unsupported edits reported |
| CF-10 | One clip targets YouTube A and B; A succeeds, B waits/fails; retry B | A uploads once, B uses B's credentials/session, statuses stay independent, waits honored |
| CF-11 | Add/reconnect/disconnect two YouTube and two TikTok connections; exercise shared quota | No connection replacement or token crossover; both shared and account-specific limits hold |
| CF-12 | Re-render an approved output or change its selected destination | Old consent/checks cannot authorize new bytes/destination; active uncertain session stays intact |
| CF-13 | Rename Editor to Nova, reload/open phone, then reset | Name syncs; real role/handoff IDs unchanged; reset restores only the default display name |
| CF-14 | Theme/layout changes on desktop and phone, keyboard use and reset | Preferences persist; mobile remains usable; no hidden essential panels, lost edits or overflow |
| CF-15 | Open a migrated existing installation with the ClipForge label | Same project/media/Brain/account/history counts and original media hashes; no blank new profile |
| CF-16 | Render and transfer mixed-rate media with opening speech and later quiet passages | Raw AAC clocks valid; decoded speech continuous; no introduced opening glitch/dropout or gain pumping |
| CF-17 | Crash near upload acknowledgement, then restart scheduler | Same session reconciled; no duplicate post; exact account/audience and file binding remain intact |

For CF-04 use annotated intervals: intro 00:00–00:15, story A 00:15–03:10, gap 03:10–03:25,
story B 03:25–07:05, gap 07:05–07:20, story C 07:20–11:40, outro 11:40–12:00. Put a chunk boundary at 06:00
inside story B. Include distinguishable opening/closing sentences and actual speech/audio in the rendering
fixture. Check those sentences survive in order and every story appears once. Allow only measured boundary
silence padding; do not declare success from the number of cards alone. Add one ambiguous/incomplete-story
fixture that is visibly flagged instead of mislabeled complete. Separately test real semantic analysis with
labeled authorized material when a configured model is available; mocked segmentation is not that evidence.

### 16.9 Required delivery artifacts and completion rule

Create a feature checklist linking each requirement/CF scenario to actual implementation, test and evidence.
For every requirement use Implemented, Partial or Blocked; include a concrete reason and next action for the
last two. Do not call a feature complete because its form, API stub or screenshot exists.

Deliver: the updated code and migrations; pinned editor integration/capability report and notices; route map
and design tokens; runnable owner-only deployment configuration with a secret-free example environment file;
backup/restore/cutover steps; regression results; screen recordings/screenshots; a benchmark harness/report;
and a short owner guide covering login, creation modes, Brain/skills, account selection and robot names.
Provide exact build/run commands and the tested commit. Prepare the next version of website copy to describe
only verified capabilities; keep the working download until its replacement is tested.

The performance report must measure a representative aggregate batch of more than five source hours, full
output rendering and cleanup on the proposed server, not just ASR on a short clip. Record model/settings,
source and output hours, stage wall times, failures/retries, peak RAM/disk, transfer and retained storage.
If it cannot finish a day's workload within a day with headroom, mark capacity insufficient and propose the
lowest-cost measured change. If no host is available, deliver the harness and mark capacity unverified.
The owner must approve any exact paid configuration before provisioning; do not promise unlimited free capacity.

Completion means the required user journeys work with real saved state and validated media, the meaningful
automated tests pass, migration preserves existing data, and any untested provider/hardware behavior is stated
plainly. Continue useful independent work when provider setup is missing; never fabricate deployment URLs,
account connections, real-platform approval, video uploads or test results.
