# ClipFoundry: cloud studio and editing expansion

Planning checkpoint: November 3, 2026 (America/Chicago).
Status: requirements, researched recommendation and implementation plan only. Nothing in this document is
implemented by this checkpoint. The working desktop app and public download website stay available.

The full implementation brief is [CLAUDE_STUDIO_BUILD_PROMPT.md](CLAUDE_STUDIO_BUILD_PROMPT.md).
Read it together with [CLOUD_PLAN.md](CLOUD_PLAN.md) and the newest repository handoff.

## The product

One account, one private studio, three clear starting choices:

| Choice | You provide | ClipFoundry produces |
| --- | --- | --- |
| Short clips | A video link or file | The existing ranked, captioned highlights |
| Full stories | A recording containing one or more stories | A separate complete video for each identified story, in source order |
| Full YouTube video | Multiple clips, optional audio/images, and a short creative brief | An editable assembled video, preview, captions and final export |

The owner logs in from a Mac, PC, tablet or phone. Uploaded media, projects, Brain preferences and job status
are stored on the server. Accepted jobs continue when the browser closes. A source file must finish uploading
before the server can process it; closing a browser during transfer is a resumable interruption, not completion.
Desktop offers the full editor; phone provides upload, brief, preview, simple adjustments, status and publishing
controls. Do not claim a professional desktop timeline is equally usable on a small phone screen.

Start owner-only, with public registration disabled. Build stable workspace ownership now, then verify full
multi-user isolation and service readiness before admitting other users. No mandatory subscriptions or paid
AI generation are part of the initial proposal.

## Recommended editing foundation

Use **FilmCraft, from the ArtCraft team**, as the first integration candidate. Keep ClipFoundry responsible
for the guided workflow, Brain, story analysis, accounts, durable jobs, quality checks and publishing.

Primary repositories inspected at these exact commits:

| Repository | Observed capability and license | Recommendation |
| --- | --- | --- |
| [storytold/artcraft](https://github.com/storytold/artcraft/tree/1f969a9224934a55417daf10359a6fb1458b63f4) | Interactive AI image/video creation and scene tools; MIT OR Apache-2.0, with separate notices | Optional future creative tools; not the primary timeline choice |
| [storytold/filmcraft](https://github.com/storytold/filmcraft/tree/57dc82ea2046c2ec479ab4d4d8167d90e5500b49) | Nonlinear editing, browser build and headless CLI/MCP; MIT OR Apache-2.0, with separate notices; alpha | Prototype as the editor/engine behind a replaceable adapter |
| [storytold/artcraft-services](https://github.com/storytold/artcraft-services/blob/1d0425fcfe32677f16e796874e955b7ba0a71005/LICENSE.md) | Separate source-available backend; restricts commercial resale and competing products | Exclude from the proposed public-product architecture unless separate permission is obtained |

FilmCraft's [browser documentation](https://github.com/storytold/filmcraft/blob/57dc82ea2046c2ec479ab4d4d8167d90e5500b49/docs/web.md)
says its stock web build keeps media on the user's device and runs cooperatively on the browser UI thread.
A static deployment alone does not provide cloud rendering, account sync or unattended work. Build an explicit
bridge between authenticated project storage, small preview media and a server-side editing worker. The
[headless CLI source](https://github.com/storytold/filmcraft/blob/57dc82ea2046c2ec479ab4d4d8167d90e5500b49/apps/filmcraft-cli/src/main.rs)
includes import, commands, project save, render and export; actual compatibility and performance still need testing.

Run a bounded integration experiment before adopting it: import mixed source files, trim/reorder, add captions
and a supplied music track, save/reopen, preview in the browser and export on a headless Linux worker. Compare
preview and final timeline, opening audio, timestamps, output duration, memory and elapsed time. Verify ARM64
support on the proposed server. Document every unsupported operation and conversion loss.

If that experiment passes, integrate the tested subset under ClipFoundry's simple interface. Keep a normalized,
versioned edit plan independent of engine internals. If a required part fails, retain the existing FFmpeg-based
renderer for supported operations and identify the specific missing feature. Do not rebuild codecs, clone a
whole desktop suite, silently drop edits, or call an unsupported integration complete.

Preserve dependency licenses/notices and ClipFoundry's canonical robot branding. ArtCraft trademarks are
separate from the code licenses. Optional generative services can cost money even when their client is open
source. This checkpoint inspected source/docs; it did not compile or benchmark FilmCraft.

## Brain and the short creative interview

After upload, ask at most four required questions, prefilled from the selected saved style:

1. What kind of video is this, and who is it for?
2. What length and shape do you want? Allow “use your judgment.”
3. What style: calm/storytelling, balanced, or energetic? Include caption/music choices when relevant.
4. What must stay, and what should be removed or avoided?

Ask a follow-up only for a real conflict or missing essential information. Show an editable brief with a clear
“Remember this style” control. Remembered answers become structured, editable Brain preferences with their
origin and scope; project-only answers remain in the project. Do not store publishing/reuse statements or keys
as creative guidance. Existing enabled notes still apply where supported.

The planning screen shows “Used from your Brain” and names the actual preferences, examples and skills used.
Project-specific choices override saved style; saved guidance fills its supported fields; Settings fill gaps.
Unsupported prose remains visible as reference material, with an honest explanation. Never label reference
storage, retrieval or example measurements as model fine-tuning. Store actual accepted edits as optional,
reviewable feedback, not automatic global rules inferred from every click.

## Full stories

Analyze the complete transcript in overlapping sections, then reconcile story boundaries globally. Detect
openings, context, narrative development and conclusions. Do not truncate a story to fit Shorts duration caps.
Keep every distinct complete story, rather than only the highest-scoring moments; show partial/uncertain stories
for review instead of silently omitting or calling them complete. Mark intros, ads and unrelated gaps separately.

Present cards in source order with a title grounded in the story, start/end, duration and confidence. Let the
owner include/exclude, split, merge and adjust boundaries before batch creation. Preserve setup and payoff,
handle a story spanning analysis chunks, and flag an unfinished final story. Default to source aspect ratio;
vertical reframing is an explicit option. Shared source analysis should not rerun for each story.

## Skills and customization

Skills initially mean reusable editing instructions/templates, not executable plugins. Import Markdown, text,
or validated JSON into a library with name, version, scope, supported effects and enable/disable controls.
A Claude-style SKILL.md can supply supported guidance, but its shell commands, scripts, tools and network
requests must not execute. Show which instructions can be applied and which are only reference material.

Provide light/dark/system themes, accent choices, comfortable/compact spacing, reduced motion, resizable and
reorderable panels, saved layouts and Reset layout. Sync account preferences while maintaining separate desktop
and small-screen layouts. Offer simple Create, Review and Office presets; the office remains an optional view
of real work. Preserve the existing robot identity and accessible keyboard paths.

## Build order and completion evidence

| Phase | Deliverable | Evidence needed to finish |
| --- | --- | --- |
| 0. Baseline and editor experiment | Latest source verified; FilmCraft capability/license decision; repeatable integration experiment | Exact source commits, real export/preview checks, supported-operation matrix and measured costs/limitations |
| 1. Private cloud foundation | Owner login, workspace ownership, private uploads/media, durable processing, deployment files | Logged-out/wrong-user denial, upload resume, restart recovery, backup restore, desktop regression tests |
| 2. Guided creation and Brain | Three choices, project brief, saved style and supported skill import | A saved preference changes an actual edit plan; project overrides work; influence evidence survives restart |
| 3. Full-story mode | Complete-story segmentation and batch output | Multiple complete stories including chunk-boundary/long stories; no accidental Shorts cap or silent omissions |
| 4. Full-video editing | Multi-file rough cut, manual changes, preview, captions/audio, final render through tested adapter | Save/reopen parity; mixed-format media; correct preview/export; fresh quality/hash checks |
| 5. Personalization and devices | Theme/layout sync, responsive flows and polished errors | Mac/PC/tablet/phone browser tests; no inaccessible panels or destructive layout resets |
| 6. Unattended operation and cutover | Measured workload, queued publishing, migration and rollback | More-than-five-hour representative daily batch, bounded disk/cost, no duplicate posts after failures |

Keep each phase runnable and ship a complete tested path through it. Security and workspace ownership belong
in the foundation, not as a final login overlay. Public signup is a later release gate, not part of phase 1.

## Cheapest practical deployment

Use the existing [cloud plan](CLOUD_PLAN.md): first try a genuinely free eligible CPU VM with free identity
service, private persistent storage, HTTPS and one heavy processing slot. Provider accounts and capacity are
not yet available. Confirm current allowances directly before provisioning. Do not add paid generation,
serverless GPU, object storage or a managed database just because they simplify architecture.

Keep an optional worker boundary so a measured bottleneck can later move to paid compute without moving
identity or publishing. More than five source hours daily, multi-source assembly and long-story exports make
free production capacity uncertain. Measure the complete workflow, output volume, retained storage, traffic,
retry costs and required headroom. A free pilot is an experiment, not an unlimited hosting promise.

## Publishing and reliability

Full-story and full-video outputs need their own format/duration policies. Preserve existing Shorts rules and
all exact-file quality checks. Retain the final AAC sample-clock repair, raw stored-packet verification and
opening-audio regressions that fixed uploaded audio. A new engine must pass the same checks before its files
can publish; a local player sounding fine is insufficient evidence about platform transcoding.

Publishing remains an explicit choice of account, audience, time and applicable consent. Existing input-scoped
YouTube automation stays intact; a new full-video project does not inherit permission from an unrelated clip
submission. Keep TikTok's supported per-post workflow, platform limits and truthful status. Never use imported
skills or the editor's own upload buttons to bypass ClipFoundry's queue, quality checks or account binding.

Cloud cutover copies and verifies data, reconnects platform credentials securely, then pauses the old publisher
before resuming the reconciled cloud queue. Preserve uncertain upload sessions and existing files. Test using
synthetic footage and fake platforms; a real social post is a separate owner-authorized verification.
