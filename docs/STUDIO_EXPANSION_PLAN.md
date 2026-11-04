# ClipForge: cloud studio and editing expansion

Planning checkpoint: November 3, 2026 (America/Chicago).
Status: requirements, researched recommendation and implementation plan only. Nothing in this document is
implemented by this checkpoint. The working desktop app and public download website stay available.

The full implementation brief is [CLIPFORGE_CLAUDE_PROMPT.md](CLIPFORGE_CLAUDE_PROMPT.md).
Read it together with [CLOUD_PLAN.md](CLOUD_PLAN.md) and the newest repository handoff. Its section 16 now
specifies exact screens/buttons, saved fields/defaults, account/asset/publication relationships, job behavior,
visual tokens, a labeled three-story fixture, 18 pass/fail scenarios and required delivery evidence.

## The product

The existing ClipFoundry app becomes **ClipForge**, with two main creation choices:

| Choice | Mode | You provide | ClipForge produces |
| --- | --- | --- | --- |
| Make clips | Highlights | A video link or file | Ranked, captioned vertical highlights |
| Make clips | Full stories | A long recording containing one or more stories | One complete vertical clip per story, formatted for TikTok and YouTube, in source order |
| Make a YouTube video | Full video | Multiple clips, optional audio/images, and a short creative brief | An editable assembled video, preview, captions and final export |

Full stories belongs inside Clips and shares its intake, library, review and publishing flow. It is not a
third top-level creation product. One ClipForge login may connect multiple YouTube channels and TikTok accounts;
the user chooses the actual destinations for each project/output.

The owner logs in from a Mac, PC, tablet or phone. Uploaded media, projects, Brain preferences and job status
are stored on the server. Accepted jobs continue when the browser closes. A source file must finish uploading
before the server can process it; closing a browser during transfer is a resumable interruption, not completion.
Desktop offers the full editor; phone provides upload, brief, preview, simple adjustments, status and publishing
controls. Do not claim a professional desktop timeline is equally usable on a small phone screen.

Start owner-only, with public registration disabled. Build stable workspace ownership now, then verify full
multi-user isolation and service readiness before admitting other users. No mandatory subscriptions or paid
AI generation are part of the initial proposal.

## Recommended editing foundation

Use **FilmCraft, from the ArtCraft team**, as the first integration candidate. Keep ClipForge responsible
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

If that experiment passes, integrate the tested subset under ClipForge's simple interface. Keep a normalized,
versioned edit plan independent of engine internals. If a required part fails, retain the existing FFmpeg-based
renderer for supported operations and identify the specific missing feature. Do not rebuild codecs, clone a
whole desktop suite, silently drop edits, or call an unsupported integration complete.

Preserve dependency licenses/notices and ClipForge's canonical robot branding. ArtCraft trademarks are
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

## Clips: Full stories

Analyze the complete transcript in overlapping sections, then reconcile story boundaries globally. Detect
openings, context, narrative development and conclusions. Do not truncate a story to fit Shorts duration caps.
Keep every distinct complete story, rather than only the highest-scoring moments; show partial/uncertain stories
for review instead of silently omitting or calling them complete. Mark intros, ads and unrelated gaps separately.

Present cards in source order with a title grounded in the story, start/end, duration and confidence. Let the
owner include/exclude, split, merge and adjust boundaries before batch creation. Preserve setup and payoff,
handle a story spanning analysis chunks, and flag an unfinished final story. Default to 9:16, 1080×1920 vertical
composition with readable captions, safe areas and framing that follows real subjects/activity. Offer manual
framing and fit/background alternatives. Shared source analysis should not rerun for each story.

A whole story may be longer than a platform/account permits. Check current eligibility per destination and
preserve a complete master. Offer a complete regular YouTube video where supported, download, or an explicit
choice to split into parts; never silently truncate or split a story or call every vertical video a Short.

## Skills and customization

Skills initially mean reusable editing instructions/templates, not executable plugins. Import Markdown, text,
or validated JSON into a library with name, version, scope, supported effects and enable/disable controls.
A Claude-style SKILL.md can supply supported guidance, but its shell commands, scripts, tools and network
requests must not execute. Show which instructions can be applied and which are only reference material.

Provide light/dark/system themes, accent choices, comfortable/compact spacing, reduced motion, resizable and
reorderable panels, saved layouts and Reset layout. Sync account preferences while maintaining separate desktop
and small-screen layouts. Offer simple Create, Review and Office presets; the office remains an optional view
of real work. Preserve the existing robot identity and accessible keyboard paths.

## Multiple publishing accounts

Connect several YouTube channels and TikTok accounts without replacing an earlier connection. Use stable
connection IDs, workspace ownership and provider-verified identities; migrate the current platform-keyed
account table without losing tokens, approvals or history. Reconnect/disconnect affects only the intended
account. One Google login is not necessarily one YouTube channel.

Select one or more destinations explicitly, with independent account/audience/metadata/schedule/status records.
Bind each upload session and consent to its connection. A successful post to A must not mark B complete, and
retrying B must not repeat A. Honor both per-account limits and shared app/API quotas. Keep started/uncertain
uploads bound to their original destinations; adding an account or changing a default does not redirect them.

## ClipForge branding, redesigned screens and robot names

Rename the visible product to ClipForge and reorganize the interface around the new workflows. Design a coherent
shell, typography, spacing, colors and components rather than just adding tabs to the old UI. Suggested areas
are Home, Projects, Brain (including skills), Publishing, Accounts, Office and Settings. Home has two creation
buttons; Clips contains its two modes. Use large useful previews, fewer repeated forms, clear account labels,
real progress and mobile-friendly navigation. Implement and inspect real screens, not only mockups.

Keep the same canonical robot icon across the product and platform-review assets. Update visible name/help/site
copy and prepare provider-console branding updates, while preserving existing links and immutable releases.
Do not blindly rename internal Python imports, environment variables, data directories or keychain/bundle IDs;
preserve compatibility or provide a tested migration. The label change must not create an empty new profile.

Let the owner rename any robot in its card or Team list, with Save and Reset name. Store display names per
workspace against stable robot/role IDs and show the role beside the name, e.g. “Nova · Editor.” Names sync
across devices, appear consistently in activity/accessible labels, and cannot change worker identity, manager
relationships, permissions or handoffs. Keep historical event identities and real work states intact.

## Public website redesign

The owner also requires the existing public download website to be redesigned for ClipForge, not just renamed.
The prompt's section 17 specifies the existing Sites identity/source, landing-page sections, two creation
workflows, responsive visuals, real product previews, verified Mac/Windows downloads, honest availability,
legal/review links and live-deployment checks. Open Studio appears only for an actual verified cloud app;
public visitors must not be promised accounts while the studio remains owner-only. Preserve working download
artifacts and unsigned Mac guidance until a verified replacement exists. CF-18 covers website acceptance.

## Build order and completion evidence

| Phase | Deliverable | Evidence needed to finish |
| --- | --- | --- |
| 0. Baseline and editor experiment | Latest source verified; FilmCraft capability/license decision; repeatable integration experiment | Exact source commits, real export/preview checks, supported-operation matrix and measured costs/limitations |
| 1. Private cloud foundation | Owner login, workspace ownership, multiple social connections, private uploads/media and durable processing | Wrong-user denial, account/token/destination isolation, migration, upload resume, restart and restore |
| 2. ClipForge creation and Brain | Renamed/redesigned shell with two creation choices, project brief, saved styles and skills | Existing profiles/routes preserved; a saved preference changes an actual plan and survives restart |
| 3. Clips: Full stories | Complete-story segmentation and vertical batch output inside Clips | Complete stories, safe captions/moving framing, chunk-boundary handling and honest destination eligibility |
| 4. Full-video editing | Multi-file rough cut, manual changes, preview, captions/audio, final render through tested adapter | Save/reopen parity; mixed-format media; correct preview/export; fresh quality/hash checks |
| 5. Personalization, website and devices | Redesigned app/site, theme/layout sync, robot naming and publishing UX | Cross-device checks, CF-18 website/download tests, real destinations and stable robot roles |
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
skills or the editor's own upload buttons to bypass ClipForge's queue, quality checks or account binding.

Cloud cutover copies and verifies data, reconnects platform credentials securely, then pauses the old publisher
before resuming the reconciled cloud queue. Preserve uncertain upload sessions and existing files. Test using
synthetic footage and fake platforms; a real social post is a separate owner-authorized verification.
