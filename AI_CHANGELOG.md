# AI changelog

## Studio upgrade: full-video editor with audio tracks and revision safety — 2026-11-05 (Claude Code)

- Engine `ffmpeg-v2` (plan schema 2) renders the picture in cached pieces of at most two inputs, joined by byte
  concatenation, so long timelines no longer build one huge filter graph. Element positions come from a whole-frame
  map, so sync does not drift. Older plans upgrade on load (a music bed becomes a music audio item).
- Audio: voiceover, music and effect items with start, trim, gain, fades, loop and a clip anchor; four track
  controls (source, voiceover, music, effects); a block mixer in 10 s blocks. Ducking is now measured from the
  speech track (frames above the speech level lower the music by the chosen depth, default 12 dB). This replaces
  the sidechain compressor, which only lowered music by 0 to 5.6 dB in a measured check.
- Editing: add footage, images and sound after the rough cut (insert or replace), undo and redo, restore and named
  versions; every change is a new immutable revision. A preview with the same plan is reused, and the screen marks
  an out-of-date preview. Free disk space is checked before a render.
- Screen: timeline with paged sequence, clip inspector, Sound panel with tracks, Your media upload with three
  parallel uploads you can stop and resume, Look (frame rate, caption size and position), Versions.
- Tests actually run: fast suite 1,672 passed; new `test_studio_editor.py` (9 fast) and
  `test_studio_editor_render.py` (3 slow: 120 clips frame-exact, three audio roles with at least 6 dB ducking,
  media added after the rough cut through the API) pass; `test_studio_video.py` (slow) passes. Editor screen checked
  in a browser at 1440 px and 390 px with no horizontal scroll and no console errors.
- Not verified: memory use on a real device with hours of footage, real Whisper transcripts (model download blocked
  here, fixture transcripts used), waveforms and text overlays (not built yet).

## Studio upgrade: video links in Make clips, discovery retired — 2026-11-05 (Claude Code)

- Make clips offers Video file and Video link; a link keeps the chosen mode, style, skills and destinations through a
  durable, cancelable, resumable download into a private asset (`studio/link_import.py`).
- Automatic source discovery is retired (`config.DISCOVERY_RETIRED`, one-time migration with an audit event; nothing
  deleted). Setup, Settings and Missions no longer offer topics, search keys or discovery controls.
- Tests actually run: baseline fast suite 1,630 passed on `6c3f8d9`; new `test_studio_links.py` (29) and
  `test_discovery_retired.py` (4) pass; 148 product-default suites pass with discovery retired.
- Not verified: real YouTube downloads (host unreachable here), browser checks of the changed screens, slow suite.

## Latest Claude handoff and media-review result — 2026-11-04 (Codex)

The owner's latest request is a detailed implementation prompt, including example-video learning and web media
sourcing. Delivered `docs/CLIPFORGE_STUDIO_UPGRADE_CLAUDE_PROMPT.md`: dark-only Studio/Home/Office redesign,
all-bot naming/customization, real Brain influence and analyzed reference videos, supplied YouTube URLs,
scalable multi-asset/audio editing, complete editable projects, bounded AI corrections, project-specific stock
media/sounds/images, removal of unrelated automatic source discovery, complete visible rename, website/releases,
and 31 acceptance scenarios. These new features are requirements, not implementation claims.

The full media review finished **18 passed / 3 failed**. Diagnosed the new full-video renderer's failure:
FFmpeg xfade received invalid 1/0 frame-rate metadata after timestamp/filter operations. Restored CFR metadata
and the common time base at clip/title and transition boundaries. The offline speech fixture also selected its
transcript by approximate container duration, which varies with encoder padding; it now matches the actual
source asset. No assertion was removed. The complete focused full-video test then **passed (85.12 seconds)**,
including mixed media, preview/final render, edits, restore, cancellation, captions and stored AAC clock checks.

**Repository sync correction:** GitHub reports PR #16 was merged separately at 18:24 UTC on November 4,
merge commit `883913c84e5cb621d70093b2692083962c1580c6`. The renderer repair and this handoff were created later
on `codex/review-clipforge-pr16`; do not assume they are included in that merge or its packages. Two failures
from this broader media run remain unresolved:
- `test_worker_host_runs_complete_loop_and_repeats_after_restart[public]`: later source classified weak;
  expected second post did not arrive.
- `test_added_upcoming_stream_waits_survives_restart_and_finishes_real_post_live`: live transcription timeout;
  media-process timeouts also logged.
Do not assume these are pre-existing without a baseline comparison. Fix them or deliberately replace obsolete
discovery coverage with equivalent submitted-input recovery checks as part of the requested feature retirement.
The full slow suite has not been rerun after the focused renderer repair. Evidence:
`/workspace/work/clipfoundry/pr16-slow-complete.log`, `pr16-video-ffmpeg-error.log`, `pr16-video-fixed-final.log`.

The public website version 3 is live at https://clipfoundry-studio.landryschreiner33.chatgpt.site.
The Sites downloads were unchanged by this review. New remote work added the shared download page at
https://landryschreiner33-coder.github.io/ClipForge-AI./download/ and lists November 4 packages from source
`06f459eb185b87ac344ad14e8dbd3f8e03be58d1`; their manifest was inspected, but those newer binaries were not
retested here. The latest prompt targets that shared site and optionally synchronizes Sites. No application
cloud deployment, real account upload, real AI/media-provider connection or native hardware validation was
performed in this review. Preserve the remote Mac release workflow changes pulled during final sync.

## ClipForge merged and released for Windows and Mac — 2026-11-04 (Claude Code)

- Merged PR #16, #17 and #18 into the default branch.
- Fixed the Mac smoke checks for the ClipForge name; they now pass at any window width.
- Published the Windows setup ZIP and the Mac DMG, both built from `06f459e`.
- Added the shared GitHub Pages download page at `/download/`. It is data-driven from `releases.json` and checked by
  `build.py --verify`.

Tests:
- Fast 1,630 and slow 21 passed locally.
- GitHub run 41899130825 passed the native Mac build and smoke checks plus fast and slow pytest.
- 77 Windows launcher tests passed, and every payload file was compared with the commit.
- All four listed downloads were re-downloaded and matched.

Not verified: native Windows, a physical Mac, real accounts, and Defender or Apple acceptance.

## PR #16 merge review and website refresh — 2026-11-04 (Codex)

The owner explicitly requested reviewing Claude's changes, merging PR #16 and updating the existing public website.
Working checkout: `/workspace/clipforge-pr16`, branch `codex/review-clipforge-pr16`, based on Claude head `4e0da48`.
Merged the newer `codex/cloud-plan` documentation into that head without dropping either set of handoff notes.

Review fixes:
- Hold automatic YouTube uploads over 15 minutes when the channel's long-upload eligibility is unknown. Keep the
  full master available and explain the next step; add destination/boundary regression checks.
- Include cloud requirements in development/test installs: the new OIDC test fixtures require PyJWT, which the
  existing CI installation command otherwise omitted. Desktop runtime dependencies remain unchanged.
- Correct creation/render copy that incorrectly described local desktop processing as server processing.
- Rebuild and retain the tracked frontend distribution.
- Close secondary-workspace access to shared Brain guidance and media-processing writes until those services
  are truly workspace-scoped. A regression reproduced private owner note metadata in the old guidance response;
  the same request is now refused. The primary owner workflow remains available.

Verification so far: 1,628 fast tests passed; eight focused full-story tests and 70 targeted cloud/studio/account regressions passed after the review fixes;
production frontend build passed; 12 app-shell browser tests passed in a throwaway sandbox. The full slow-media run finished
18 passed / 3 failed; the renderer subsequently passed its focused regression, with two failures unresolved (see latest checkpoint).
No real account sign-in, video upload or owner-machine data was used.

The existing Sites project `appgprj_6ae8b76d68108191bc36af565f138bed` was redesigned and published as version 3 from
`/workspace/sites/clipfoundry-downloads`: ClipForge branding, both creation flows, Brain/styles/skills, robot office,
real sandbox screenshots, responsive controls, and explicit source-preview / desktop-release / cloud availability.
Keep https://clipfoundry-studio.landryschreiner33.chatgpt.site and its public audience. Mac/Windows download URLs,
bytes and hashes remain unchanged because no new native release has been built. The source changes are not yet
in those installers. Website QA passed at 1440/1024/768/390/320 px, with no horizontal overflow or browser errors;
preview/install keyboard tabs, FAQ, legal/version links and no-JavaScript download anchors passed.

Website deployment succeeded: `appgdep_6aeb6be63940819185f90f2769de8ce2` (source `626295c6e31b0120043483e21aceda2718d57a14`);
full publication/rollback evidence is in `docs/clipforge/WEBSITE_DEPLOYMENT.md`.
Outstanding before merging: resolve the remaining media failures, complete the relevant verification and merge only the tested
head SHA. The requested updated Claude prompt is delivered. This review did not merge PR #16; a final sync discovered
it was merged separately while this review was running. See the latest checkpoint for the follow-up branch. Do not describe cloud hosting, public signup,
per-account scheduling or full-video publishing as complete. Claude's remaining partial features are recorded in
`docs/clipforge/FEATURE_CHECKLIST.md`. The earlier FilmCraft build-policy refusal describes that historical session;
it is not a newly required owner approval for this session.

## ClipForge studio, phases 0–6 — 2026-11-04 (Claude Code)

Built the ClipForge prompt (`docs/CLIPFORGE_CLAUDE_PROMPT.md`) on `claude/new-session-b9itcy` (draft PR #16).

What was built:
- **Cloud mode:** owner-only OIDC sign-in, server sessions, CSRF/host/origin guards, strict CSP, workspace ownership on
  every ID, AES-256-GCM secrets.
- **Accounts:** multiple YouTube/TikTok connections, migrated without changing tokens.
- **Server plumbing:** resumable private uploads; durable studio jobs; backup/restore/retention CLI.
- **Guidance:** precedence with frozen snapshots and "Used from your Brain"; saved styles and declarative skills.
- **Full stories:** complete stories as 9:16 clips, with destination eligibility (never truncated).
- **Full YouTube video:** assembly on a versioned FFmpeg engine with revisions.
- **Interface:** the new ClipForge shell; theme/layout prefs; robot display names; the visible rename.

The office map and robots are unchanged. Desktop data, Keychain/DPAPI names, settings keys, the publish header and
old addresses are kept.

Final regression fixes:
- Link/transcript import is reachable at `#/create/link`.
- Make clips previews guidance with a GET.
- Startup robot-name loading no longer redraws the page and discards a just-chosen file.
- Remaining Clips/Queue labels now say Projects/Publishing.
- Motion stays the per-browser Animations choice.
- The sidebar is narrower below 1366 px, so the office map keeps its minimum width.
- Browser specs follow the new navigation.

Tests: see `docs/IMPLEMENTATION_STATUS.md` (2026-11-04 test log). Not verified: real sign-in, deployment, uploads,
transcodes, native Windows/Mac hardware, throughput. FilmCraft stays Blocked (build not permitted here). No real
posts, no deployment, no owner media.
## Website redesign added to the Claude handoff — 2026-11-04 (America/Chicago)

The owner asks to tell Claude to update the website and improve its appearance. Section 17 of
[CLIPFORGE_CLAUDE_PROMPT.md](docs/CLIPFORGE_CLAUDE_PROMPT.md) now makes the existing public website redesign a
required deliverable: ClipForge branding, clear landing-page hierarchy, real previews, both creation workflows,
verified Mac/Windows downloads, accurate feature/cloud availability, responsive/accessibility checks and
publication/rollback evidence. Open Studio must lead to a real authenticated deployment; owner-only access
and the unsigned Mac preview remain honestly described. CF-18 adds the website acceptance scenario.

A separate read-only review verified the existing buildless site source and public project identity under
/workspace/sites/clipfoundry-downloads. Keep that project/address, current release metadata/checksums and the
separate GitHub Pages/TikTok verification site. No live site, installer or application code changed in this
checkpoint; only the requested prompt/plan and handoff documents were edited.

Verification: source/identity review, numbered sections and CF IDs, internal links, JSONL syntax, preservation
of prior acceptance scenarios and git diff --check. No website/browser/application tests were run because no
implementation changed. The future website work must supply those checks before being called complete.

## Opening handoff and bug-prevention requirement — 2026-11-03 (America/Chicago)

The owner requests a handoff at the beginning of the Markdown prompt and asks to keep it “big free,” interpreted
as bug-free. [CLIPFORGE_CLAUDE_PROMPT.md](docs/CLIPFORGE_CLAUDE_PROMPT.md) now opens with a continuation handoff,
truthful current planning state, and instructions to maintain AI_HANDOFF.md at startup, checkpoints and exit.
It requires root-cause fixes, regression checks, reproducible defect reporting, and no readiness claim while
known core failures remain. Unverified external behavior must remain Partial/Blocked, not be described as
literally free of all possible bugs. The detailed requirements and 17 acceptance scenarios are unchanged.

Verification: an independent read-only prompt review found no conflict with continuing implementation;
checked opening-handoff placement, preservation of the numbered implementation body, links, JSONL syntax
and git diff --check. Documentation only; no application tests, deployment or real uploads were performed.

## Detailed ClipForge build contract added to Claude prompt — 2026-11-03 (America/Chicago)

The owner requests a much more specific Markdown prompt and a simple explanation afterward. The canonical
[CLIPFORGE_CLAUDE_PROMPT.md](docs/CLIPFORGE_CLAUDE_PROMPT.md) now contains section 16: exact screen responsibilities,
Clips/full-video journeys, question fields/defaults, Brain snapshots, skill behavior, stable data relationships,
job/failure handling, visual defaults, robot-name validation and 17 concrete acceptance scenarios (CF-01–CF-17).
A labeled 12-minute/three-story fixture includes a chunk boundary inside one story. The prompt requires actual
media/provenance/account-isolation evidence; UI placeholders or mocked semantic results cannot prove completion.

Existing authorized YouTube clip creation does not gain a new mandatory per-clip review step. Full stories
remains inside Clips with full narrative preservation, vertical framing and accurate destination eligibility.
The prompt preserves previous cloud/login, multiple accounts, ClipForge rename, UI, Brain, skills, editing,
robot naming, AAC/audio and publishing requirements. The full-video brief explicitly distinguishes reusable
style preferences from project-specific ranges, private paths and publication consent.

This checkpoint changes planning documents only, not application behavior, website, installers or cloud
services. Checks: requested scope and superseded-default checks, internal links, sequential sections,
CF scenario IDs/fixture continuity, source references, JSONL syntax and git diff --check. No functional app
suite was run; the new contract is not implementation or real-platform verification.

## ClipForge prompt revision: Clips modes, multiple accounts and redesigned UI — 2026-11-03 (America/Chicago)

The owner's latest correction is authoritative: Full stories is inside **Make clips**, alongside Highlights.
Each story in a long source becomes a complete vertical TikTok/YouTube clip, with safe captions and dynamic
framing. Preserve over-limit story masters and show destination eligibility; never silently split/truncate.
The other main creation choice remains **Make a YouTube video** from uploaded clips.

The owner also requests multiple connected YouTube/TikTok accounts, the visible name **ClipForge**, a redesigned
interface organized around these workflows, and editable robot names. The canonical complete Markdown prompt
is [CLIPFORGE_CLAUDE_PROMPT.md](docs/CLIPFORGE_CLAUDE_PROMPT.md). The earlier prompt path redirects readers to it.
[STUDIO_EXPANSION_PLAN.md](docs/STUDIO_EXPANSION_PLAN.md) and the cloud plan now reflect these requirements.

The prompt includes stable workspace/connection/robot IDs, separate account-bound publications and quota scopes,
profile-preserving branding migration, consistent icon identity, responsive navigation and display-name tests.
Cloud, Brain, skills, full-video editing, prior AAC/audio fixes and publishing guarantees remain in scope.
This checkpoint writes the requested plan/prompt only; no feature, product rename, website or installer changed.

Verification: documentation scope/conflict checks, relative links, source references, sequential prompt sections,
JSONL syntax and git diff --check. No functional app tests were run because no application code changed.
FilmCraft remains an unbenchmarked integration candidate; cloud capacity/accounts and real uploads unverified.

## Cloud studio expansion plan and Claude implementation prompt — 2026-11-03 (America/Chicago)

The owner has now specified the second major change: full YouTube-video assembly from supplied clips,
complete-story batch clipping, account access across devices, importable skills, simple guided workflows and
saved themes/layouts. They request a plan and a detailed prompt for Claude Code, not implementation in this
checkpoint. Cloud remains owner-only initially, later public release, more than five source hours/day and
lowest possible cost. No paid provisioning is authorized.

[Product and build plan](docs/STUDIO_EXPANSION_PLAN.md) and
[ready-to-use Claude prompt](docs/CLAUDE_STUDIO_BUILD_PROMPT.md) define phased implementation, concrete acceptance
criteria, migration/cost controls and preservation of previous audio, Brain and publishing fixes. Continue
from the latest source after inspecting remote refs; do not start an older branch and lose Claude changes.

Official upstream inspection identifies FilmCraft (the ArtCraft team's nonlinear editor) as the first
integration candidate. Its pinned source documents a browser build and headless CLI/MCP under MIT OR Apache-2.0,
with separate notices, but remains alpha. The stock browser build processes media locally; cloud storage and
rendering require a bridge. A repeatable integration experiment must prove capabilities and audio correctness.
The separate artcraft-services repository has competing-product restrictions and is excluded from the proposed
public-product architecture without a separate grant. Sources and exact upstream commits are in the plan.

No application code, installer, website or cloud service changed. FilmCraft was not compiled or benchmarked.
Verification: official upstream README/license/notices, browser and control documentation and CLI source were
inspected; planning documents checked for complete requested scope, internal links and whitespace. No functional
tests were run for this documentation-only checkpoint. Provider accounts, capacity, end-to-end throughput and
actual cloud deployment remain unverified. The working Mac download remains unchanged.

## Cloud migration scope and cost plan — 2026-11-03 (America/Chicago)

Current planning branch: `codex/cloud-plan`, based on the verified native-app/delivery branch at `9e0aaee`.
The owner confirms the Mac app now opens; its port conflict was a separate Python HTTP file server, not an
app defect. The new request is cloud execution with login, owner-only initially, later public release,
more than five source-video hours daily, at the lowest possible cost. The second major change is unspecified.

[Cloud migration plan](docs/CLOUD_PLAN.md) records the code audit, $0 infrastructure pilot proposal, migration,
benchmark, authorization/storage changes and separate public-signup requirements. Proposed providers are
Oracle Always Free A1 (current docs: 2 OCPUs/12 GB RAM allowance, 200 GB total block storage) and free Supabase
Auth with owner-only Google login. Availability/throughput are unverified. No paid GPU/server is selected.

No application code or deployed website changed. No accounts, resources, credentials, login or cloud server
were created. This is a plan, not an implemented cloud feature. Existing loopback guards, local data stores
and Mac credentials cannot simply be exposed on the internet; follow the plan before enabling cloud access.
The owner must complete provider registration/card verification directly. No paid provisioning is authorized.
Any paid recommendation must follow an actual workload estimate and an explicit owner budget decision.

Verification: inspected current authentication, OAuth, secrets, data and job paths; checked official provider
allowances/pricing and billing documentation; documentation whitespace check passed. No functional tests were
run because this checkpoint changes only planning documents. Preserve the working Mac app and published DMG.

## Personal Mac app download published — 2026-11-03 (America/Chicago)

The owner chose personal use without Apple Developer membership and reported that the website still offered
the old ZIP. That supersedes the earlier wait-for-signing delivery restriction. The existing public website
now offers the tested native `.dmg`, explicitly labelled **unsigned personal preview** with Apple's one-time
per-app opening instructions. No Developer ID signing, notarization or removal of that warning is claimed.

Website: https://clipfoundry-studio.landryschreiner33.chatgpt.site
Site version 2, deployment `appgdep_6aea47758b188191a727141520a951e8`, returned **succeeded**.
Site source: `e8df8d718de6a6b42d9118e44375176874d6d85b`; same project and public audience retained.

Mac DMG: https://github.com/landryschreiner33-coder/ClipForge-AI./releases/download/macos-personal-2026-11-03-bc3ce2c/ClipFoundry-Mac-Apple-Silicon.dmg
SHA-256: `4fa4d423159c29d40f70632ae414c1fa047c7f72542e702f07f2e8ad0bb52d7d`; 191,813,213 bytes.
This is the unchanged native app/DMG tested at `bc3ce2cdc23ccc7a495d2cfc2ed15aba3fe161e3`:
1,556 fast tests, 19 real-media/restart tests, and the native Mac checks passed. macOS 15+ / Apple silicon.
The release includes exact corresponding source and `mac-personal-preview.json`. It is a prerelease and does
not replace the separate Developer ID/notarized release process. No real uploads or physical M5 test occurred.

Delivery workflow: https://github.com/landryschreiner33-coder/ClipForge-AI./actions/runs/41661606857
It verified the pinned artifact hash, mounted/verified the DMG, checked the bundled app signature/icon/source
identity and verified every release-asset digest before publication. The first attempt left a complete draft
because GitHub cannot resolve unpublished drafts through its tag endpoint; the corrected workflow reused that
same draft by ID and published successfully. No duplicate release or changed application bytes were created.
The public DMG was downloaded back and its full byte count/SHA-256 matched. Site release metadata now points
to that asset and its matching verification record. Windows download and checksum are unchanged.

Website browser checks: 1440, 390 and 320 px, zero page errors or horizontal overflow, mouse/keyboard setup tabs
passed, direct DMG anchor also works without JavaScript. The site's privacy policy retains its Sites hosting
disclosure and adds native local WebKit storage. Existing Mac data/Keychain identities are unchanged. Quit an
old launcher before opening the new app; drag into Applications, then open normally. macOS may require
Privacy & Security → Open Anyway once. No security setting was disabled, and no owner machine was accessed.

Source continuation stays on `codex/macos-native-app`. This checkpoint changes only delivery, website copy,
metadata and evidence; the existing app tests were reused for the unchanged packaged bytes. Do not rebuild or
merge solely to change the download. Keep the public link/checksum pair and truthful unsigned labelling intact.

## Personal Mac DMG delivery — 2026-11-03 (in progress)

The owner confirmed they are using ClipFoundry personally without Apple Developer membership and reported
that the website still downloads the old source ZIP. This supersedes waiting for signing before offering the
native app: deliver the unchanged tested DMG as an explicitly unsigned personal preview, with Apple's per-app
opening steps and no claim that Gatekeeper warnings are removed. Preserve the existing public Site identity.

`.github/workflows/macos-personal-preview.yml` publishes only the pinned successful native artifact from
`bc3ce2cdc23ccc7a495d2cfc2ed15aba3fe161e3`, run 41656652146. It checks artifact SHA-256, mounts/verifies the DMG,
checks the app source identity/signature/icon, and verifies every uploaded release asset digest before publishing
a prerelease. This does not run or alter the separate Developer ID/notarized release process. No application
code changes or media re-encoding are included. The 1,575 tests and native checks remain those of the exact
packaged commit. Delivery and website verification will be recorded once complete.

## Native Mac app verified; Apple signing pending — 2026-11-03

Continue on `codex/macos-native-app`. The tested implementation is
`bc3ce2cdc23ccc7a495d2cfc2ed15aba3fe161e3`. A complete native Apple-silicon `.app` and branded
Retina drag-to-Applications DMG now build successfully, with the canonical robot icon, Swift/AppKit window,
native file/export panels and bundled Python/FFmpeg. No first-launch pip, Terminal or global Python is needed.
The existing Brain, clipping, framing, captions and publishing code/data remain intact. macOS 15+ is required.

**Verification:** [CI run 41656652146](https://github.com/landryschreiner33-coder/ClipForge-AI./actions/runs/41656652146)
passed the native macOS 15 ARM64 job and the complete fast suite: **1,556 passed, 19 deselected in 531.55 s**.
The complete real-media/restart suite also passed: **19 passed, 1,556 deselected in 950.85 s**. No final failures or skips.
Native checks used isolated profiles and synthetic media: the real WebKit window, simulated OAuth/help links,
Blob export, unsaved-edit event guards, normal Quit and Force Quit cleanup, unchanged signed bundle, Keychain,
caffeinate, captioned 1080x1920 rendering with stable opening audio/valid raw AAC clocks, and actual AV1 decode.
The runner's VideoToolbox probe succeeded. The DMG passed `hdiutil verify`. No physical M5 or real social upload
was tested. Local focused lifecycle/release checks passed 33 tests. No frontend changes required a rebuild.

The final correction keeps the complete Python runtime under Resources, reserves Frameworks for real dylibs,
and signs the main executable with its enclosing bundle last. The FFmpeg build includes dav1d for AV1 input.
Native Quit preserves existing unsaved-edit checks. A test-only Linux process-disappearance race was corrected
without changing the app's watchdog. Previous packaging failures and the earlier one-test failure are superseded
by this exact-commit run, not counted as passes.

Actual screenshots, hashes and test provenance: [design/mac-app/2026-11-03](design/mac-app/2026-11-03/README.md).
The development artifact is named **ClipFoundry-Development-NOT-NOTARIZED**, ID `13240393392`, and expires after
seven days. Its ZIP SHA-256 is `49bc9aeffcd8cfa183ee6e3ccdddfb843dfd86e9084570514be35cc37ff39709`.
This is ad-hoc signed development evidence, **not a warning-free public release**.

**Remaining blocker:** the owner has not confirmed active Apple Developer Program membership, and no Developer
ID/notarization credentials are available. Check Membership details at https://developer.apple.com/account/ .
Use the secure signing setup in `macos/DESKTOP.md`; never request passwords or private keys in chat. The signed
release workflow must consume a successful exact-commit development artifact and pass Apple notarization,
stapling, Gatekeeper assessment and signed native smoke checks before publication. It has not been run.
The release workflow may need to be made available on the default branch before manual dispatch; do not merge
without authorization. If the artifact expires, rebuild the recorded source before signing.

The public Site identity/address and its current source ZIP are unchanged. Only update its download/hash once
an actually signed and notarized DMG exists. No Gatekeeper bypass, paid enrollment, owner-data modification,
real upload, owner-machine install, branch merge or public release was performed in this checkpoint.

## Native Mac app verification in progress — 2026-11-02

Continue on `codex/macos-native-app`, implementation commit `e5197f84196ab5fb34f40146d50e034a3254ca8c`.
The owner wants a normal local .app with an icon and no Gatekeeper override. Swift/AppKit window compilation
passed on macOS 15 ARM64. Native packaging exposed an @rpath dependency in Brotli and a source-mirror download
that failed its hash; the builder now resolves/relocates those libraries and uses Homebrew's verified source
fetcher (including pinned Git sources), never ignoring a checksum. A branded Retina DMG, secure ephemeral-CI
signing keychain, Apple notarization/stapling checks and release gates are implemented. Signed release code has
not run because no Apple signing credentials or membership confirmation are available.

Verified locally: 33 focused lifecycle/release-gate tests passed; the production renderer produced a 1080x1920
captioned synthetic clip with stable opening audio and valid raw AAC timing. Native WebKit popup/export and
clean/force-quit checks plus complete fast/slow suites are running at
https://github.com/landryschreiner33-coder/ClipForge-AI./actions/runs/41542754495 . Do not call these pending tests
passed. Earlier two development CI attempts exposed the packaging failures above; neither is a release.

Read `macos/DESKTOP.md` for build, data, signing and release instructions. The public website/source ZIP remain
unchanged until a genuinely notarized DMG exists. No security settings were weakened, no enrollment/payment
was made, and no owner media/accounts were used in testing. Preserve all prior Brain, audio and upload fixes.


## Native Mac app construction — 2026-11-02

The owner requests a professional local .app with a Dock icon and no Terminal setup. Work now continues on
`codex/macos-native-app`, from the final published website/source ZIP checkpoint. Added a Swift/AppKit WKWebView
window, bundled-runtime builder, owned backend launcher, parent-death cleanup and isolated readiness nonce.
Existing ~/Library/Application Support/ClipFoundry/data and Keychain identities stay unchanged. External OAuth
uses the system browser; native file/export panels retain the full studio UI. The media builder compiles pinned
FFmpeg 9.0.2 with x264/libass and redistributes its exact dependency sources/licenses (no nonfree FFmpeg binary).

Local verification: 25 desktop/real-process watchdog tests passed; git diff --check passed. Native CI and full
regression are pending. Development app is ad-hoc signed ONLY for CI. No Developer ID credentials or Apple
membership confirmation are available; no notarization, warning-free delivery or owner-machine execution is
claimed. The existing public website/download remain unchanged until a verified distributable is ready.


Development checkpoints made by AI assistants, newest first. Each one says what changed, why, what was actually run
and what was not. The same checkpoints, in machine-readable form, are in `.clipfoundry/ai-change-log.jsonl` (shown
read-only in Settings → Advanced → Dev Log). Work before October 7, 2026 is not repeated here: it is recorded in
`docs/IMPLEMENTATION_STATUS.md` (plan, matrix and test log) and in the Git history.

Commit ids are snapshots of a branch at the time of writing; fetch before relying on them.

## Public website and final downloads published — 2026-11-02 (America/Chicago)

Public website: https://clipfoundry-studio.landryschreiner33.chatgpt.site . Sites version 1, deployment
`appgdep_6ae90bd92960819190941651776a171b`, returned **succeeded**. Site source commit:
`8844f76843b02bcf6752cbebc1e2c73380fdb8d2` in the separate Sites source repository.

Final Mac ZIP: https://github.com/landryschreiner33-coder/ClipForge-AI./raw/0bfaba410a6d6a93717efeb012671a39bc66df9e/ClipFoundry-Mac-Apple-Silicon.zip

SHA-256: `c192292bc6cd438b64876c6e4713d8982dcd2da46a942b67ea8a1bd6c382fb60`; 28,699,559 bytes.
Packaged source `fd0d764b746f7f55f2df1dd19e660f3ac9fd036a` differs from tested
`18aacfe6cc6e893a9c5acdc15693775400a334ad` only in verification documentation/logs. The public download
was fetched and hash-checked; its app contains the final SIGHUP shutdown correction and raw AAC timing guard.
The existing Windows download at `fc7b1991e07dc9e58afc7fe74328a0874bf24e57` remains unchanged and verified.
No merge, real video upload, owner-machine install or paid service enrollment was performed.

The next assistant should preserve this Site identity/audience, update immutable release links and checksums
together, and continue from the app branch `codex/macos-download-site` and delivery branch
`codex/macos-download-delivery`. Do not claim signing/notarization or physical M5 Max testing. macOS version
and Apple Developer membership remain unconfirmed. This documentation-only commit needs no new installer.

## Public downloads and Apple-silicon preview — 2026-11-02 (America/Chicago)

Final Terminal-close correction: a real isolated POSIX watchdog test reproduced SIGHUP bypassing owned-app
cleanup. SIGHUP now follows the same shutdown path as Control+C. All 17 real-process launcher tests also passed
on native macOS ARM64, including Terminal-close cleanup. The final full suites passed against this correction.

The owner explicitly requests a public download website and the full ClipFoundry workflow on an M5 Max.
Source branch: `codex/macos-download-site`, continued from 88386d6 with all prior Claude changes and the raw AAC
clock correction retained. Download-site source lives separately at `/workspace/sites/clipfoundry-downloads`;
Sites identity: `appgprj_6ae8b76d68108191bc36af565f138bed`, explicitly public. Its reserved address is
https://clipfoundry-studio.landryschreiner33.chatgpt.site . Publication/delivery records accompany the Mac ZIP.
The existing GitHub Pages/TikTok verification site, icon, Windows ZIP and blocked historical EXE are unchanged.

`macos/` builds a readable unsigned ZIP with a verified native ARM64 Python 3.12 runtime. First setup installs
Mac dependencies and obtains pinned FFmpeg/ffprobe directly from upstream, checking compressed and extracted
hashes. Code/environments are per-release; data stays in `~/Library/Application Support/ClipFoundry/data`.
Old releases/data are retained. Another running installation is not killed. First-run imports and a synthetic
H.264/AAC render with the production raw-clock check must pass before setup is marked complete.

New Mac credentials use AES-GCM and a per-profile login Keychain key, with no plaintext fallback. CPU Whisper
is a supported native path (no Metal ASR claim). Auto encoding checks VideoToolbox before choosing it, with
x264 fallback. Mac Autopilot uses a process-bound caffeinate request; the office no longer treats the absence
of an NVIDIA GPU as a Mac failure. YouTube/TikTok permission, review, limit and uncertain-upload behavior is unchanged.

**Verified:** complete fast suite **1,540 passed, 19 deselected in 528.40 s**; complete real-media/restart suite
**19 passed, 1,540 deselected in 1012.69 s**. No final failures or skips. Both ran on fresh public Ubuntu 24.04
CI runners against 18aacfe6cc6e893a9c5acdc15693775400a334ad. The native macOS 14 ARM64 job built the actual
package, installed its bundled runtime/dependencies, passed the production AAC timing check, performed a real
Keychain encryption round trip, acquired/released caffeinate, and served the HTTP API/bundled UI. Its virtual
runner did not expose VideoToolbox, so software fallback was exercised. CI evidence:
https://github.com/landryschreiner33-coder/ClipForge-AI./actions/runs/41492774348 . Release documentation added
after this run changes no tested application code. Frontend build passed. Website browser checks passed at
1440, 390 and 320 pixels with working keyboard setup tabs, no page errors and no horizontal overflow.

An earlier local full-suite run was interrupted by the resumed workspace; an initial slow run lacked the
speech-fixture tool on PATH. The tool was restored, and the slower local reruns were deliberately stopped after
fresh CI took over. Partial local results are not counted as passes. Native CI also independently passed on
7e30061. Mac archive contents and executable launcher modes are checked; no owner media, secrets, data folders,
virtual environments or design/test fixtures are bundled.

**Limits:** macOS version and Apple Developer membership remain unconfirmed. No physical M5 Max test,
Finder/quarantine interaction, Apple signing/notarization, real social upload, existing-upload repair, paid
enrollment or security-policy change was performed. Speech models download on first transcription; no Metal
speech acceleration is present. Reconnect Windows-protected accounts on Mac; existing profiles are not silently
migrated. Keep Terminal and the Mac awake. The stable Windows download remains at delivery fc7b199.
See `macos/README.md` and `docs/MACOS_RELEASE_VERIFICATION.md` for setup and verification details.

## Confirmed upload audio timing defect — 2026-10-29 (America/Chicago)

The owner has now supplied both matching versions: the local 1080x1920 render and Google's processed
720x1280 copy. Their pictures match (692 frames each; downscaled grayscale RMSE 0.707). The YouTube copy
contains exact silence from 0.8360 to 3.0607 s while the local decoded audio remains present.

**Correction to the earlier investigation:** default ffprobe/FFmpeg parsing repaired the AAC packet clock,
so its apparently continuous timestamps did not establish a valid MP4 sample table. Direct examination of
`stts`, and ffprobe with `-fflags +nofillin`, exposes 140 invalid audio packets in the local file. Many opening
packet durations are 1 sample instead of 1024; a later packet covers 113498 samples instead of 1024. This
squeezes the opening and leaves a 2.36 s interval, matching the pattern in Google's output. The audio samples
and transfer bytes were intact. The previous volume-normalization fix alone was not a verified solution.

New rendering resets the audio time base to 1/48000 and rebuilds timestamps from actual output sample counts
AFTER cuts, speed, resampling and the compensated limiter. Real source delays/gaps have already been represented
by samples and remain intact. AAC-LC is explicit. Before promoting a temporary render, an independent bounded,
cancellable probe checks the stored packet clock without automatic timestamp repair. The final quality gate
performs the same check. Gate version 3 invalidates old cached passes for unstarted work; malformed clocks fail
with a rerender explanation and can return to the existing bounded render-repair path. Active/uncertain uploads
retain their existing session behavior. Existing uploaded media and approvals are not rewritten or reuploaded.
Older local files must receive a fresh render/check to use the fix; updating cannot restore an existing YouTube
copy's missing audio.

A separate private-workspace copy of the supplied ORIGINAL was repaired by rebuilding AAC packet timestamps
without re-encoding: encoded video/audio packets and decoded audio are identical; its raw clock now has zero
invalid packets. Neither owner file nor derived media is committed to Git or included in releases. A real
YouTube re-upload of the corrected file has not been performed or verified.

**Validation:** Full fast suite: 1,524 passed, 19 deselected in 1777.86 s. Full real-media/restart suite: 19 passed, 1,524 deselected in 2168.08 s. No final failures or skips. Nine new timing regressions pass, covering broken raw AAC clocks despite successful playback, corrected clocks, priming/final padding, two sample rates, malformed probes, cancellation and render handoff. All 204 frozen Python source/test files match. The 17 previously built frontend files are unchanged; no new frontend build was needed. The supplied local file fails the new raw timing check; its privately repaired copy passes with identical encoded audio/video packets and decoded audio. A synthetic regression fixture was corrected to include a video track before the final full fast run. A cloud workspace restart interrupted both earlier full-suite runs; both were restarted completely. Real YouTube re-upload and native Windows remain unverified.

## Supplied audio sample investigation — 2026-10-28 (America/Chicago)

The owner supplied a finished 23.067-second MP4 and its matching YouTube Shorts URL. The local MP4 fully
decodes without reported errors: H.264 video and AAC-LC stereo at 48 kHz, audio/video starting at zero,
matching 23.066667-second container lengths, and continuous audio packet timestamps. There is no opening
silent stretch of 100 ms at either -50 or -60 dBFS. One-second channel correlation stays positive; this
sample does not establish a phase-cancellation cause. This is structural/sample analysis, not a listening
assessment or proof about platform playback.

The exact supplied file (8,906,887 bytes) passed three local fake-YouTube transfers using the production
8 MiB chunk size: normal, interruption after the first chunk followed by resume, and retry after HTTP 503.
All three delivered byte-identical media through one session and produced one fake video. Secondary local
128 kbps AAC and Opus encodes of this real sample preserved the first ten seconds: sample correlation >0.9975
and maximum active 100 ms-window RMS drop <0.167 dB. These are not real YouTube transcode tests.

**Still unresolved:** the browser service could not fetch either Shorts or watch playback (throttled), and the
workspace proxy rejected YouTube access with HTTP 403. Do not work around that access policy. Request the
posted copy downloaded through YouTube Studio, or a playback recording if that copy does not reproduce it.
An optional question about replay on another device/browser is pending. The app source still has no confirmed
upload-only defect. No speculative processing change, new installer, real upload or owner-account action was
performed. Supplied media and derived audio remain in the private workspace, outside Git and release packages.

## Upload-only audio clarification — 2026-10-23 (America/Chicago)

**Unresolved:** The owner now clarifies that the video sounds fine before upload and becomes distorted/quiet
only after upload. The earlier normalization defect is real, but it is not a confirmed explanation or fix for
this reported upload-only problem. Do not claim the prior download fixes this case without comparing the actual
finished local MP4 with its matching platform playback. It remains unknown whether the local preview means the
original source, the finished clip, or another rendered version; the platform/link has been requested.

Follow-up on app revision `58770e2242c8a84a6b6394048abde55a5065dc23`: traced selected-file resolution, content-hash
checks, and YouTube/TikTok binary upload paths. The encoders are not invoked by the uploaders. Six focused
resumable/interrupted/chunk tests passed (50 deselected, 6.63 s). A retained synthetic render has AAC-LC stereo
at 48 kHz, with audio/video starting at zero and both container durations 11.600 s. Four local secondary encodes
(AAC/Opus, mono/stereo, 128 kbps) retained clean initial tone and stable repeated passages: initial-to-later
RMS change remained within 0.007 dB and initial tone purity exceeded 99.99%. These are local FFmpeg tests,
not YouTube/TikTok processing tests and not evidence about the owner's particular media.

No functional code, media, platform account or release package changed in this follow-up. Next evidence needed:
the exact exported finished MP4 that sounds correct locally and the corresponding affected uploaded-video link
(or the platform-processed file if the link cannot be accessed). Compare the same version, initial decoded
samples, channel phase/downmix, timestamps and platform output before choosing another processing change.
The cloud workspace has no owner-PC VPN/account connection and its network policy does not currently grant
YouTube/TikTok access. Do not bypass that policy or ask for account credentials.

## Audio startup and volume stability — 2026-10-23 (America/Chicago)

Base: `2eda06afe16b9dbfd22a2f42c3056d08c88c7094`, verified as the latest pushed source on both
`claude/sharp-rubin-zmg6tx` and `codex/brain-graph-quality-discovery` before work. All 18 remote branch heads
were checked. This update continues from that source and preserves the earlier Brain, framing, scheduler,
submitted-video, Python setup and robot-office changes.

The previous single-pass loudness normalizer could boost a quiet opening by about 50 dB, then reduce the same
quiet signal by over 24 dB after a loud moment. This is a reproduced processing defect, not proof that every
reported distorted source has this cause. The owner has not supplied an affected original/render/platform pair.
The uploaders transfer the rendered MP4 bytes without changing the audio.

New normalized renders measure the complete kept audio timeline after first-track selection, clock repair,
trims/joins, stereo downmix and speed changes. The encode uses one constant gain targeting -14 LUFS, limited
by the measured -1.5 dB true-peak headroom and a maximum 24 dB boost. Highly dynamic recordings can therefore
finish quieter than -14 LUFS rather than pumping or flattening their dynamics. Silent/ungated material receives
no guessed boost. Explicit gain and the existing compensated final limiter remain. Normalization off skips the
measurement pass. Failed/malformed measurements stop rendering; cancellation and time bounds apply. Numeric
measurements and the applied gain are retained in local `render_info.audio_processing`; no extra audio recording
is saved or sent to a service. The editor describes -14 LUFS as a target, not a guaranteed platform standard.

Existing files, approvals and uploads are not rewritten or posted again. To apply the fix to an older clip,
render it again from its source, preview it, and let its new exact-file checks/approval run before uploading.
Already damaged source samples cannot be reconstructed by changing loudness normalization.

**Validation:** Full fast suite: 1,515 passed, 19 slow deselected in 573.11 s. Full real-media/restart suite: 19 passed, 1,515 deselected in 890.51 s. No failures or skips in these final runs. The first media attempt lacked espeak on PATH (12 passed, four skipped, three fixture-setup failures); the existing isolated speech tool was added to that test process's PATH and all 19 cases were rerun without code changes. TypeScript/Vite production build passed (Vite 4.88 s); two existing built-browser creation/editor checks passed (11.6 s). All 202 frozen Python source/test files and 17 built files match. New regressions verify stable AAC startup and repeated quiet passages, noise/silence, exact kept intervals and speed, invalid-measurement/cancellation handling, a full 1080x1920 render from AAC 44.1 kHz, and byte-identical transfers through fake YouTube and TikTok. Before/after output measurement reduced an artificial 24.42 dB drop on identical quiet audio to 0.0013 dB. Real platform transcoding and the owner's affected original remain unverified.

No owner data/profile, native Windows/RTX3050, real YouTube/TikTok upload or platform transcoding was tested.
The local privacy text describes the added measurements; public Pages is not redeployed by this update.


## 2026-10-19 · Brain-guided creation, moving crops and spaced publishing

* **Changed:** platform-tagged Brain lessons apply across subjects, manual clips retain real ranking provenance,
  and the editor lists used lessons. Automatic crops follow measured visual motion when faces disappear, with
  cache invalidation and recorded quality-gate evidence. Default posts are 30 minutes apart; automatic pending
  collisions and already queued transfers respect spacing across restarts. Positive custom gaps/explicit rescheduled times
  and active/uncertain transfers remain intact. Existing valid input reuse statements carry through Queue
  review; generated repairs require fresh exact-file checks and approval, without retyping source reuse.
* **Why:** owner reports unused Brain guidance, static crops, simultaneous schedules and repeated Queue reuse
  questions for supplied inputs. No local-file ownership assumption or new old-backlog grant was introduced.
* **Validation:** Final full fast suite: 1,504 passed, 18 slow deselected in 687.23 s. All 18 selected real-FFmpeg/synthetic-media and restart cases passed: 15 in 766.75 s before stopping the remaining legacy zero-gap fixture wait, then its corrected three cases in 455.55 s. TypeScript/production build passed (6.03 s); all 61 built-browser checks passed in 170.29 s. All 204 other frozen Python/source/test/bootstrap/dependency files and 17 tested built files retain their hashes. Only the slow-loop fixture changed after the fast/first-15-media checks, to explicitly select zero spacing for compressed test time; all its three affected cases were rerun. Production source stayed unchanged. The final 205-file manifest matches the delivered source. The final source adds the reviewed alternate-version repair guard, covered by the final full suites and 62 focused checks; the already completed browser run covers unchanged frontend paths. Earlier full attempts stopped for evidence/pacing/version corrections are not final evidence. Actual moving-frame output, saved Brain ranking influence, input-bound reuse, concurrent/restarted pacing, platform waits and exact fake uploads were checked in disposable profiles. No owner profile, real social upload, native Windows/RTX3050 or 24-hour soak was tested.
* **Delivery/limits:** readable source setup is pinned separately with managed release history preserved; no
  custom EXE rebuild or security setting changes. Native Windows/GPU, owner profile, real platform delivery,
  approval and 24-hour operation are unverified. Existing media/uploads remain unchanged.

## 2026-10-19 · Matching TikTok icon across the app and public website

* **Changed:** reuse the exact submitted 1024-square robot PNG for app branding, the public site's headers and
  browser tabs, and the helper's single recommended icon. Form packs include matching PNG/ICO website assets;
  local legal previews serve them correctly. Legacy icon download endpoints remain compatible.
* **Published:** branding-only `gh-pages` revision `80a6a3f4782de64fed88a06d9db54533de4869bd`; successful
  Pages deployment and exact readback of all eight source files. Preserve existing TikTok URL verification,
  `.nojekyll` and product/legal copy. The public-site fix needs no desktop reinstall.
* **Why:** TikTok's reviewer found the submitted robot differed from the website's old filmstrip logo/favicon.
* **Validation:** TypeScript/production build passed (5.11 s). Final affected Python suites: 41 passed in 6.89 s.
  Twelve Chromium checks cover all three public pages at desktop/mobile widths in light/dark mode; the built app
  header, favicon, helper preview and download also match the exact submitted PNG. All six ICO frames match nearest-
  neighbor canonical pixels. The broad fast run completed with 1,489 passed, one obsolete website-readiness fixture
  failure and 17 slow deselected in 537.24 s. It had already collected the older fixture, which forbade added assets
  and all image elements. The corrected fixture permits only the bundled canonical image and passes in both the
  41-case affected-suite rerun and a final individual rerun. All 326 frozen code/test/build/website hashes match.
  Exact published source readback and successful Pages deployment were verified. The media/Autopilot pipeline and
  dependency/bootstrap files are unchanged; slow media and broad browser suites were not rerun for this branding
  correction.
* **Limits:** direct live-site HTTP is unavailable under this environment's network policy. No TikTok portal
  submission/approval or real account upload verified. Existing installer artifact remains pinned to its prior
  revision; media/Autopilot/dependency behavior is unchanged.

## 2026-10-19 · Verified Windows Python selection and preserved environment recovery

* **Changed:** standard-library bootstrap verifies actual standard 64-bit CPython 3.12/3.11 for Windows AMD64;
  both readable installer and app launcher share the check. Compatible `.venv` is kept; incompatible copies get
  unique backups before fresh creation, failed partials are preserved with rollback where possible, and a known
  active environment blocks replacement. Missing supported Python yields side-by-side official-install guidance.
* **Why:** owner screenshot reports no matching CTranslate2 distribution. Its exact runtime/index is unknown;
  current CPython 3.13/3.14 AMD64 wheels exist, so this uses the app's supported runtime policy without claiming
  those versions inherently lack wheels. Native ARM64/32-bit lack the applicable wheel.
* **Preserved:** owner data/Brain/accounts/clips, GPU/dependency pins, rendering, frontend and submitted-video
  upload behavior; no automatic global Python installation, PATH/registry/security change or old-environment
  deletion. Previous release evidence remains separate.
* **Validation:** Full fast regression suite: 1,489 passed, 17 slow deselected in 527.16 s. All 203 frozen source/test/bootstrap/dependency hashes matched. The 38 focused bootstrap checks passed in 3.54 s, including real disposable-host venv creation, reuse and replacement, preserved dependency markers/data, failure rollback, active-process and concurrency guards, exact runtime checks and read-only probes. A 19,230,360-byte CPython 3.12 Windows AMD64 CTranslate2 4.8.3 wheel was downloaded and its SHA-256 matched PyPI (b5daf0758d522a422c76e53eb02ce9f42465a9aba938a86b27249fb5db2571b9). No dependency/GPU pins, app pipeline or frontend files changed; all 17 previously browser-tested built files retain their hashes. The previous 17 media and 59 browser results apply to unchanged scopes and were not rerun. The readable setup is separately pinned to this exact app commit; its delivery proof records installer/helper tests, full source hashes, managed-release history and immutable download readback. No native Windows/owner install, CUDA/RTX3050,
  real upload/Defender or 24-hour run verified. Linux cross-pip dry runs are not native Windows proof.

## 2026-10-19 · Submitted videos to Brain-guided clips and automatic YouTube uploads

* **Changed:** Missions accepts a recorded-video link/file with **Make & upload clips** or **Make clips only**.
  Submitted input is now the default; periodic/queued search and watched-folder admission stop without deleting
  old data or removing optional discovery. Relevant supported Brain guidance uses Settings fallback.
* **Authorization:** one explicit input-scoped request records destination/audience, genuine kids answer and
  reuse basis outside Brain. Acquired original/project/current terms and every final file/payload are bound.
  Only its newly generated qualifying YouTube posts can auto-approve; old backlog/later inputs/TikTok stay separate.
  Source requests do not change ownership or global audience/standing consent. Stop/pause/cancel, credit, quality,
  source drift, waits and uncertain-session/no-duplicate handling remain. An accepted-input enqueue gap recovers
  durably without reviving attempted/canceled jobs. Retention keeps referenced source/audit records while
  clearing stale API data and ordinary unused discovery; its foreign key no longer interrupts maintenance.
* **Audio:** retain measured downmix/peak/clock/track corrections and exercise actual Brain-guided rendered AAC
  through the exact fake YouTube upload bytes and restart. Existing distortion and real platform processing are
  not guaranteed repaired. Existing media/uploads remain unchanged.
* **Validation:** Final full fast suite: 1,451 passed, 17 slow deselected, in 676.07 s. Final full real-FFmpeg/synthetic-media and restart suite: 17 passed, 1,451 deselected, in 934.97 s. TypeScript and the production build passed (10.00 s). All 59 final built-browser checks passed in 161.55 s. The final fast suite used 198 frozen Python source/test files. All production and selected media-test sources stayed unchanged during the full media run; 81 frontend source and 17 built-file hashes stayed unchanged through the final browser checks. A deselected fast retention fixture's timestamp setup was corrected before the final fast run; the media run's production/selected sources were unaffected. Focused checks also passed: 60 submission/consent, 79 final status/routes/legacy readiness, 29 advanced-route/legacy, 119 legacy intake/scheduler/publishing, three new actual-media and 26 legacy audio/quality and nine retention checks. The three new media cases use relevant saved Brain guidance, real caption/AAC rendering, exact fake-upload bytes and restart without duplicates, including the broad YouTube switch off and TikTok enabled. Earlier full attempts were interrupted before the final route/status/retention corrections and are not final evidence. Tests use isolated profiles, synthetic media and fake platforms only. The readable source setup is pinned separately to this committed app tree with the tested frontend manifest; its delivery verification records exact archive hashes and source revision.
  No real owner account/Windows/RTX3050/Defender/24-hour run verified.

## 2026-10-15 · Failed search keys and post-only reuse explanations

* **Tool:** Codex. **Branch:** `codex/brain-graph-quality-discovery`. **Base:** `0c2729d`.
* **What changed:** bounded same-account OAuth refresh, safe key setup/restriction errors, explicit uncached saved
  search tests, credential-current results, strict responses and quota-aware concurrency. Key whitespace handling,
  provider-specific/review-mode diagnosis and clear post-only reuse text with independent Brain boundary tests.
* **Why:** owner reports no clips, clarifies both keys fail and asks that reuse entries not be saved in Brain.
  They confirmed these appear only on the post. No automatic Brain write existed; deliberate notes stay intact.
* **Validation:** Final full fast suite: 1,373 passed, 14 slow deselected, in 755.18 s. Final full real-FFmpeg/synthetic-media and restart suite: 14 passed, 1,373 deselected, in 945.34 s. Final TypeScript and production build passed (5.17 s). All 51 final built-browser checks passed in 167.41 s, with all 17 built-file hashes unchanged. Focused provider verification: 77 passed in 7.83 s; focused diagnosis/health/phone: 88 passed in 11.26 s; independent saved-search/Brain separation checks: 113 passed in 22.43 s before the final wait-order correction, then 53 passed in 4.06 s including both same-key full-server-wait regressions. All 261 frozen production/frontend/Python-test hashes remained unchanged through final verification. Tests used isolated data, synthetic media, MockTransport and fake platforms. No owner keys, Windows profile/RTX3050, actual search-service account, real upload, Defender acceptance or 24-hour soak was verified. Permission answers were already post-only; the update clarifies and verifies that boundary.
* **Not verified:** owner keys/provider setup, Windows/profile/RTX3050, real uploads or a 24-hour soak.

## 2026-10-15 · Audio, comments, ongoing search and live/Windows recovery

* **Tool:** Codex. **Branch:** `codex/brain-graph-quality-discovery`. **Base:** `11bdb435`.
* **What changed:** stereo downmix before normalization, final post-gain peak control, shared audio-clock/track
  handling; strict real kids answers and truthful YouTube comments/audience explanations; independent provider
  waits, recurring capacity-aware search, bounded pagination and saved-signal refill; visible supported search
  keys/free-only controls; safe paired HLS and bounded empty-ended-stream archive recovery; scoped Windows
  10054 cleanup with Python-version-compatible detachment. Added concrete `CLAUDE_HANDOFF.md`.
  Health/phone cadence reads remain pure; host-only deadline reconciliation also handles a full queue draining.
* **Why:** owner confirmed distorted uploaded audio, comments off on some posts, searches stopping and the two
  supplied live/Windows errors. Concrete defects were reproduced locally; no owner media/account was accessed.
* **Validation:** Final full fast suite: 1,278 passed, 14 slow deselected, in 579.81 s. Real-FFmpeg/synthetic-speech media and restart verification covered all 14 scenarios across two runs: the full attempt passed 12 with 2 repeat-discovery timeouts (1,274 deselected, 1153.68 s); after correcting only the compressed-clock fixture's discovery-list cache expiry, both private/public repeat scenarios passed in 374.57 s. This was not a single all-green full-media run. Production cache/quota policy and all real render, final-report, exact-upload-byte and restart assertions were unchanged by that fixture correction. Final production build: 10.32 s; TypeScript passed. All 43 final built-browser checks passed in 93.25 s, with all 17 frontend hashes unchanged. Focused independent bugfix verification: 73 passed in 32.22 s, including measured encoded mono/surround audio, exact fake-upload bytes, real split-HLS synchronization and real asyncio cleanup compatibility. Windows/phone focused verification: 63 passed in 10.25 s; earlier discovery focused: 89 passed in 11.12 s. The final queue-drain deadline correction and surrounding discovery checks passed 61 tests in 9.13 s. Final comments/search checks after the current-label correction: 47 passed in 22.85 s. The final read-only health/phone/search correction passed 77 checks in 16.64 s, with database-unchanged assertions intact. The complete media run used the final audio/live/publishing code, preceding only the pure health-cadence refactor and its four new fast tests; all 39 media-scope source hashes remained unchanged. That refactor is covered by the final full fast run and 77 focused checks. The earlier interrupted suites preceded final deadline/returned-label corrections and are not final evidence. No real owner Windows profile/media, RTX3050, live provider key, account upload or 24-hour soak was tested.
* **Not verified:** owner Windows runtime/profile/original audio, RTX3050, real provider keys/accounts/uploads,
  actual platform comment settings, native Windows/Defender or a 24-hour unattended soak. Existing published
  audio is not rewritten and source distortion cannot be reconstructed.

## 2026-10-15 · Faster review, bulk approval and consistent Brain guidance

* **Tool:** Codex. **Branch:** `codex/brain-graph-quality-discovery`. **Base:** `ec20aec`.
* **What changed:** inline Queue video/text previews, Quick approve and selection of up to 50 YouTube posts.
  Permission presets replace required typing, and one combined consent replaces duplicate checkboxes. Batch
  approval uses a fixed, expiring, account/file/source/terms/payload/audience/check-bound preview, explicit common
  permission basis and any missing kids answer; each success receives its own manual approval. Future posts gain
  no permission. Final guarded writes reject changed or active work without hashing under the database lock.
  Partial results retain skipped posts for review; exact retries return prior results. Known credit, physical
  quality, grounded text, post audience/time, platform waits and duplicate protections remain. TikTok stays
  individual. Single review and current per-post assertions retain exact-payload confirmation.
  Brain matching now retains source-title/spoken context through candidate generation, ranking, planning and
  rendering, including resume/live. Natural caption declarations and example feature fields are recognized;
  disliked-example observations no longer become desirable ranking traits. Recognized effects/length hints are
  shown honestly, Settings remain the fallback and explicit clip edits win. Unsupported text stays searchable.
* **Why:** the owner finds repeated review too slow and reports saved Brain notes/examples not changing clips.
* **Validation:** Final full fast suite: 1,195 passed, 11 slow deselected, in 739.22 s. Final real-FFmpeg/synthetic-speech media and restart suite: 11 passed, 1,195 deselected, in 1024.81 s. This includes exact selected-post fake uploads/restart and two actual Brain-guided/owner-overridden caption renders with persisted provenance. Final production build: 9.44 s; TypeScript passed. All 31 final built-browser checks passed in 95.78 s, with all 17 frontend hashes unchanged. Focused checks: 42 bulk, 19 independent approval audit and 86 Brain/context checks passed. Browser fixture wording/details visibility and async readiness were corrected before the final run; earlier interrupted or fixture-correction runs are not final evidence.
* **Not verified:** the owner's PC/profile, native Windows/GPU, real social uploads or a 24-hour soak.

## 2026-10-14 · Prepare and schedule for individual reuse review

* **Tool:** Codex. **Branch:** `codex/brain-graph-quality-discovery`. **Base:** `d0b7102`.
* **What changed:** review before publishing defaults on. Bounded quality-first discovery and local posting plans
  can include accessible unblocked sources with unrecorded reuse terms. Rights labels remain truthful, and new
  posts wait for manual approval. Queue shows proposed times without calling them approved uploads; review drafts
  do not expire. Uncovered posts need an individual owner reuse statement and basis bound to the exact source,
  terms/credit, post, account, audience, platform, bytes/version, text and options. Known required credit and
  physical-media checks remain binding. Old unstarted automatic approvals return to review atomically, retaining
  time, text, privacy and publication identity. Queued work, retry and not-published recovery cannot restore an
  automatic upload grant. Unknown outcomes retain their session and use account-bound readback. Separate manual
  publishing cannot borrow an assertion. Explicitly disabling review restores the existing guarded automatic mode.
* **Why:** the owner wants to inspect finished clips and confirm reuse before approving publication, rather than
  have missing records prevent a review plan or let standing permission authorize new uploads.
* **Validation:** Final full fast suite: 1,112 passed, nine slow deselected, in 529.54 s. Final real-FFmpeg/synthetic-speech media and restart suite: nine passed, 1,112 deselected, in 879.93 s, including the new review/owner-confirmation/exact-byte upload/restart loop. Final production build passed in 8.79 s; 12 built browser checks passed in 40.23 s, with all 17 frontend file hashes unchanged. Focused checks: 95 publishing/reuse checks; 64 scheduler/public/manual checks; final 46 review/current-terms checks; 107 legacy recovery checks; and eight final independent audit/fixture checks. The initial full fast attempt found an older fixture approving an unverified channel claim; its corrected exact-video verification retains all connection, quota, hash, explicit-block and no-upload assertions. Earlier full attempts were stopped before final corrections and are not final suite evidence.
* **Not verified:** the owner's Windows profile, native Windows/GPU operation, real platform uploads or a 24-hour soak.

## 2026-10-13 · Continuous eligible uploading and Brain/manager handoffs

* **Tool:** Codex. **Branch:** `codex/brain-graph-quality-discovery`. **Base:** `718358f`.
* **What changed:** app daily source/clip/platform caps default to 0 (unlimited), with all-day earliest-slot
  posting. A recorded one-time volume amendment preserves existing account/audience/kids permission and old
  posts, while future owner limits persist. Bounded search/queue/quality/API/cost/platform holds remain active.
  Uploadable-only broad discovery prioritizes verified own/agreed/CC media and explains local-only clips;
  legacy local-only finds cannot monopolize capacity. Past-due eligible approval holds and lost replacement
  times recover; reported platform zero holds approved dispatch without disrupting an active transfer.
  Current reuse/credit checks bind to both reports and actual upload text. Missing credit returns to editable
  review; proven unstarted row synchronization retains upload identity, route and current feature evidence.
  Private/canceled/manual/started/uncertain work remains protected. Count-only real Brain consultations now
  appear separately from mature-result learning. Explicit fresh manager/boss handoffs respect newer checkpoint
  outcomes, actual job ownership and Pause/Reduced/hidden/offline/history guards. Quiet rooms explain idle state.
* **Why:** the owner reported missing-permission posting holds, requested no app daily cap and continuous work,
  and found the office's Brain/handoffs misleading. No missing reuse or account permission was fabricated.
* **Validation:** Final fast suite: 1,047 passed in 556.14 s; eight real-media/restart checks passed in 836.38 s.
  Final production build passed in 6.16 s; 11 final built browser checks passed in 94.42 s, matching all 17 file
  hashes. Earlier 12 choreography checks, six department, three motion and six lounge checks passed. Final
  reuse/publishing: 93 passed; public/manual publishing: 34 passed. New current-terms regressions: 26 passed;
  independent continuous: 12 passed. Root phone checks: 56 passed. Initial full fast run found ten stale fixtures;
  updated local-discovery/finite-plan/current-report fixtures retain all permission/bytes/version/quality/wait
  checks. No owner Windows/GPU, real platform upload or 24-hour soak was tested.
* **Not verified:** real owner Windows data/runtime, RTX3050, actual account posting/visibility or a 24-hour soak.
  No real publishing, account/privacy change, spending, media deletion, security exclusion or deployment occurred.

## 2026-10-13 · Finished clips reach YouTube scheduling

* **Tool:** Codex. **Branch:** `codex/brain-graph-quality-discovery`. **Base:** `987ebb2`.
* **What changed:** reusable accessible discovery candidates take priority; parked permission/file waits cannot
  monopolize the bounded workable queue or displace them. Finished recorded clips get immediate durable handoff
  before batch yielding. Bounded reconciliation recovers proven old handoffs while preserving canceled work,
  manual edits, live decisions and existing packaging states. Parent cancellation/Pause is rechecked after
  fingerprinting. Stale consent no longer hides pending approval reminders; Private permission requires a
  confirmed upload destination too. Setup embeds audience and separate YouTube permission controls for connected
  accounts. Read-only readiness/derived warnings explain finished-clip holds without depending on a working
  scheduler; unavailable times are not called scheduled, and newer preparation overrides historical failures.
* **Why:** the owner had finished clips after an all-day YouTube-only run, with no posts or Needs you explanation.
  The exact owner-PC hold remains unknown; code failures were reproduced on disposable data and corrected.
* **Validation:** Final full fast suite: 958 passed, eight slow deselected, in 489.73 s. Final real-FFmpeg/synthetic-speech
media and restart suite: eight passed, 958 deselected, in 695.71 s, including Public/Private and live recovery
loops. Final production build passed in 3.98 s; seven built-interface browser checks passed in 43.6 s. All 17
tested built-file hashes match. Final focused handoff/readiness/simple-page checks: 88 passed in 24.79 s.
Discovery focused checks: 99 passed in 19.36 s; four new behavior regressions fail on the original source.
Scheduler/consent checks: 73 passed, one slow deselected, in 78.53 s. Independent review found the late-
cancellation race; its three corrected regressions passed and no material findings remain. No real owner data,
Windows/RTX3050, platform upload or 24-hour soak was tested.
* **Not verified:** owner Windows data/runtime, RTX3050, real platform accounts or a 24-hour unattended soak.
  No real publishing, consent/account change, spending, firewall/router change or deployment occurred.

## 2026-10-13 · Private phone status companion

* **Tool:** Codex. **Branch:** `codex/brain-graph-quality-discovery`. **Base:** `4838aa8`.
* **What changed:** default-off Tailscale/home-Wi-Fi listener serves a mobile read-only dashboard, separate from
  desktop APIs and media. Guarded owner controls issue single-use expiring pairing codes, enable/disable access
  and revoke up to eight hashed 90-day device grants. Keys use authorization headers and opt-in browser storage;
  codes and keys never enter URLs/logs. Listener failures leave the desktop functional; custom desktop ports,
  restart and shutdown cleanup are covered. Counts, progress, status and attention policy follow actual app
  state. Mobile polling handles background/offline/reconnect/expiry, clears unauthorized data and escapes text.
  Desktop setup prevents old polls from overwriting newer actions. Setup/privacy/architecture docs are updated.
* **Why:** the owner wants to see how ClipFoundry is doing from a phone, including away from home.
* **Validation:** Final full fast suite: 869 passed, eight slow deselected, in 386.91 s. Final focused phone tests: 55 passed in 9.03
s; 75 existing local-guard/office/Autopilot regressions passed in 30.43 s before the final attention refinement.
Final built phone browser suite: ten passed in 12.6 s. Final built desktop setup/race checks: two passed in 27.6 s.
Production build passed in 3.85 s; all 17 built-file hashes were recorded. No actual phone, Windows/Tailscale
connection or real account was tested.
  Initial full fast suite: 865 passed before the final attention-policy refinement. No processing/publishing
  handler changed, so no new slow media run. Installer tests and exact bundle integrity are recorded separately.
* **Not verified:** native Windows/RTX3050, actual phone browsers, real Tailscale account connectivity/firewall
  behavior or platform accounts. No real upload, account change, router/firewall configuration or cloud hosting.

## 2026-10-13 · Automatic Brain guidance and supported integration cards

* **Tool:** Codex. **Branch:** `codex/brain-graph-quality-discovery`. **Base:** `28aee85`.
* **What changed:** enabled saved Brain material participates automatically in new clip selection/rendering,
  with Settings fallback. Local recognition covers supported caption/pacing controls and ranking priorities;
  explicit choices override prose. Good examples contribute measured duration hints blended once with the
  original target. Disabled/paused material remains inactive. Revision-specific selection/render decisions merge
  without mutating shared snapshots. Manual editor overrides retain precedence; existing clips/posts persist.
  Brain shows recognized choices, automatic activation and unsaved drafts, with no separate approval action.
  Integrations removes seven inactive connector placeholders while retaining real platform permission/limit
  messages. Raw Brain material is never executed or sent to an AI; only fixed priority names accompany its
  existing transcript payload. Privacy/product documentation describes the changed behavior.
* **Why:** the owner reported stored Brain material was not being used and requested automatic use even with
  sparse knowledge, combined with Settings, plus removal or repair of unsupported integration entries.
* **Validation:** Final full fast suite: 814 passed, eight slow deselected, in 349.16 s. Final focused Brain/provider/blueprint/artifact regressions: 96 passed in 43.45 s. Actual-FFmpeg/synthetic-speech media/restart suite: eight passed, 811 deselected, in 710.71 s before the final example-blending/provenance review fixes; those final fixes are covered by the final 814/96 runs. Final controlled browser batch: eight passed in 45.5 s against the final built interface. Build passed in 6.44 s. No real uploads, accounts, Windows/RTX3050 execution or 24-hour soak were tested.
  Final fast/focused coverage includes the last example-blending and shared-provenance fixes. Media ran before
  those last fixes; all eight passed using existing portable speech tools and adequate workspace temp storage.
  Eight final browser checks cover activation, real lookup, unsaved drafts, stale-revision recovery, graph
  accessibility/mobile/motion/bounds and removal of placeholders. The local report collector separately passes
  synthetic privacy/GET-only/custom-port/offline/invalid-port checks. Packaging integrity is recorded separately.
* **Not verified:** native Windows installation/runtime, RTX 3050 CUDA/NVENC, actual account grants/visibility,
  model quality with owner clips, visual learning from examples, or an actual 24-hour soak. No real posts,
  account-permission changes, dependency upgrades, purchases or deployment.

## 2026-10-13 · TikTok setup, visible Brain graph and focused discovery

* **Tool:** Codex. **Branch:** `codex/brain-graph-quality-discovery`. **Base:** `8999e5f` from the default branch;
  PR #14 is already merged. **Result:** the commit containing this entry.
* **What changed:** TikTok form helper supplies copyable app details, current-port Desktop callback, two 1024×1024
  PNG icons, products/scopes and a form-pack export with local draft website/legal pages. Inbox, Direct Post and
  optional statistics request only their chosen permissions after applying, saving and reconnecting. Exports
  exclude credentials, tokens, account identity and owner media; URL checks are syntactic, with no network fetch.
  The helper prepares drafts only when opened and does not claim registration, review approval, hosting or an
  actual integration demo.
  Brain's interactive graph shows actual saved notes/examples/preferences, shared tags and recorded readings and
  clip influence; notes/evidence open their stored records/provenance. Decorative glow and positions are not model
  thoughts.
  Add note is simpler; Teach preference retains explicit revision review/approval. Stale edits return 409 and keep
  unsaved text until explicit reload. Uploaded material does not fine-tune a model.
  Quality-first broad discovery defaults to three picks per pass, six unfinished picks including needs-rights,
  one known creator and two per topic. The existing default three-attempt daily budget remains; explicit inputs
  keep their behavior and weak estimates do not trigger unlimited attempts to fill the clip target.
  Tavily's optional free-key setup explains 1,000 monthly credits/no card and explicitly selects a $0 app spending
  limit when chosen, preserving other settings. No new graphics or browser dependency was added.
  One read-only Integrations assertion now expects the already implemented explicit Public audience choice,
  while Unlisted remains absent. Owner-data test flows and the HTTP write blocker are unchanged; no permission
  is selected or saved by that test.
* **Why:** the owner requested a finished app and Windows installer, clearer TikTok setup, an Obsidian-style view
  of saved Brain data and stronger discovery choices instead of chasing more clips.
* **Validation:** final full fast Python: **804 passed**, eight slow deselected, in **429.01 s**; Python is unchanged.
  All eight media cases passed across the initial run (seven passed, one environment disk-capacity failure,
  965.89 s) and unchanged live rerun (48.81 s) using workspace temp storage.
  **52 unique browser checks** are covered across runs: initial 42 passed/two failed in 12.7 min; final 19 passed
  in 1.1 min (11 changed UI, eight strict read-only Settings; ten overlap the initial batch); complete loop one
  passed in 7.0 min. The final lazy helper fixes background preparation; the old Public assertion was updated
  with read-only policy intact. Recorder/temp-storage prerequisites were fixed for the actual complete loop.
  Final build passed in **4.06 s**; all 14 tested/captured hashes match.
  [Desktop/mobile/empty previews](design/brain-workspace/README.md) use controlled records from the final run.
  Earlier interrupted outputs and historical checkpoint counts are separate evidence. The Windows installer
  has a separate bundle/integrity record on `codex/clipfoundry-one-click`; native Windows remains unverified.
* **Not verified:** Windows installation/execution, RTX 3050 CUDA/NVENC, real platform grants/visibility and an
  actual 24-hour soak. TikTok personal-tool eligibility, Sandbox/public limits and per-post consent remain external
  constraints. No real upload, app registration/review, account-permission change or website deployment occurred.

The PR #14 entries below retain their original branch status and evidence. PR #14 is now merged; earlier
draft/unmerged instructions are historical and do not govern this new checkpoint.

## 2026-10-11 · Final merge review and stable log-rotation check

* **Tool:** Codex. **Branch:** `claude/project-thread-vw1n9y`, PR #14. **Base:** `51984a3`.
  **Result:** the commit containing this entry. The owner authorized merge after the final review; the actual
  merge outcome is recorded on GitHub.
* **What changed:** the live log-rotation test now takes the standard logging handler lock while enumerating
  and measuring backup files. This prevents the test from inspecting an intermediate rename. The real child
  still writes enough output to rotate logs, stays running during the check, and is stopped afterward.
  Production code and the browser-tested frontend are unchanged.
* **Validation:** independent production review found no material blockers. The initial targeted run passed
  105 checks and failed this one snapshot race in 77.43 s; all 16 corrected launcher checks passed in 0.72 s.
  The fresh full fast suite passed **757 checks**, with **8 slow cases deselected**, in **301.90 s**.
  The worktree diff is clean and all 14 browser-tested build hashes match. GitHub reported no workflow runs,
  commit statuses, review submissions or review threads for the reviewed head; the PR had no conflicts.
* **Not verified:** Windows, RTX 3050, real platform accounts and an actual 24-hour soak remain owner checks.
  The preceding media/browser/crash-recovery evidence remains applicable. No real upload or deployment occurred.

## 2026-10-11 · Unattended Public operation and current YouTube policy

* **Tool:** Codex. **Branch:** `claude/project-thread-vw1n9y`, existing draft PR #14. **Base:** `61f6042`.
  **Result:** the commit containing this entry. PR stays draft/unmerged.
  Started October 10; final validation October 11.
* **What changed:** removed the obsolete API-project audit requirement for Public uploads, following official
  YouTube `videos.insert`/`videos` documentation updated October 8 and checked October 10. Explicit Public audience,
  account-bound approval/standing permission, rights, exact-file checks and actual visibility remain; old Private
  schedules are preserved. Midnight zero is retained so 0–24 scheduling works. OAuth Production/reconnect guidance
  distinguishes Testing's seven-day YouTube grants from API quota audits; private TikTok profiles cannot offer Everyone.
  Optional `run-unattended.bat` / `--unattended` restarts an unexpectedly exited app with bounded backoff, selected
  profile/port locks, owned descendant cleanup and explicit-stop handling. It preserves intentional Pause and
  permissions. Its local diagnostic log rotates at 5 MiB plus two backups; optional same-user login startup is
  documented.
  Only one app may use a data profile. The watchdog detects process exit, not a still-running hung main app.
* **Recovery fixes:** failed host initialization cleans up partial workers before releasing its lock; job setup
  errors clear phantom running/heartbeat entries. Bounded cancellable media reads/writes/waits kill/reap children;
  HTTP/live capacity checks retain a 2 GB reserve. Low disk yields Needs you and a durable wait, preserving saved
  segments and never implying stream EOF. Final assembly replaces a complete recording only after success.
  Scheduled pre-session waits recheck Pause/current permission/account/audience/final quality. Strict unknown-upload
  recovery requires an original-account, unique recent match with submitted metadata and reads actual visibility.
  Final-chunk crashes/cancellation/ambiguous errors hold another upload; manual restart recovery offers read-only
  Refresh status. Later reconnect, setup, scope or quota errors preserve the final-byte hold and publication
  identity. Existing valid sessions keep their exact confirmed bytes.
* **Why:** the owner requested all-day autonomous Public publishing from a personal setup and a final reliability
  review. This supports unattended YouTube operation after setup while preserving deliberate exception holds.
* **Validation:** full fast Python: 757 passed, eight slow deselected, in 390.67 s. All eight slow cases passed across
  the full run (six passed, two fixture setup failures, 786.85 s) and corrected Public (58.73 s) and upcoming-live
  (49.02 s) reruns. Public setup now uses `confirm=True` and asserts the confirmed response; its controlled scheduler
  cadence is five seconds. The live fixture uses a valid 0.5 GB capture cap on the small cloud temp disk; production's
  default 8 GB cap and 2 GB reserve remain. Production code did not change for these fixture corrections.
  All 32 isolated browser cases passed together in 8.1 min. TypeScript/Vite build passed in 4.37 s; all 14 tested
  file hashes match. Final fast verification includes recovery, media, launcher, policy and unknown-outcome
  regressions. Actual-app POSIX exit/restart/stop smoke passed in 11.98 s; Windows remains unverified.
  The real-media loop now tests Public and Private separately through repeat/restart,
  exact checked/uploaded bytes, mature fake results and actual live/post-live handlers. Public needs no invitation
  fixture. Earlier department/office test counts and animation evidence below remain historical.
* **Not verified:** actual 24-hour soak, Windows launcher/Task Scheduler/Job Objects, RTX 3050 CUDA/NVENC and real
  account scopes/quota/visibility/revocation. No real post, account change, purchase or deployment occurred. No new
  dependency; `.mcp.json`, GPU versions, Playwright versions and read-only `e2e/tests` are unchanged. The watchdog
  cannot make a powered-off PC work or bypass unknown outcomes, missing rights, expired access or resource holds.

## 2026-10-10 · Department attendance, manager supervision and reliability review

* **Tool:** Codex. **Branch:** `claude/project-thread-vw1n9y`, existing draft PR #14. **Base:** `e896632`.
  **Result:** the commit containing this entry. Requested October 9; resumed/completed October 10. PR stays unmerged.
* **What changed:** real jobs or substantive assigned backlog gather each complete department into its room.
  Workers appear immediately at their own desks; supporting peers remain honestly idle and ready. Managers stand
  facing the team with clipboard/pointing gestures, while their own jobs and real reviews take priority. Quiet
  paused/unavailable peers can attend; bare counts, stale paused tasks and unreferenced recurring timers cannot
  summon a team. A finished worker remains while its teammates work, then returns to lounge activities. Confirmed
  transfers meet inside the receiver's office and return to the latest department duty; a newer own job preempts
  carrying an older document away. Pixi and Canvas retain motion/freeze guards and all 25 identities.
  Brain Processing now has clipped scan bands, travelling synapse trails, rising sparks and orbital light trails.
  Added floor/contact/furniture polish and rebuilt frontend; existing Pixi/GSAP reused without new dependencies.
* **Reliability fixes:** lease-bound progress/host updates and transactional recovery protect current jobs from
  recovered handlers and heartbeat races; failed lock-file creation releases its mutex. Quality-check job identity
  includes the rule version. Regeneration checkpoints and restores video, captions, transcript, edit decisions,
  render plan and thumbnail, remaining non-Ready until rollback succeeds and retaining recovery copies on failure.
  Brain edits use atomic revision checks; paused learning collects results without changing/applying learned values,
  and confirmed audience drift cannot enter new selected-viewer readings. Manual publishing rechecks linked-source
  rights, platform coverage, current quality/version, confirmed bytes, connected account and emergency Pause.
  Unknown YouTube outcomes hold new uploads; strict original-account metadata lookup is read-only and ambiguity
  stays held. Already-processing entries only refresh status. The Publish page exposes the hold and Refresh status.
  Privacy text describes temporary recovery copies and approval-file fingerprints.
* **Why:** the owner requested full departments in their offices, a visible supervisor, a cooler Brain and a broad
  code review before delivery. Each backend fix addresses a reproduced fault found during that review.
* **Validation:** full fast Python: 685 passed, seven slow cases deselected, in 347.07 s. All seven slow media cases
  passed together, 685 fast deselected, in 676.84 s. All 31 isolated browser checks passed together in 7.8 min.
  Final TypeScript/Vite build passed in 5.96 s with the existing 904 KB lazy graphics warning;
  all 14 distribution files and file sets are identical to tested/captured SHA-256 manifests. Routing/controller
  checks cover 3,844 + 36,304 routes, 600 virtual seconds and 150 mixed transitions. Actual Brain/supervisor pixels
  animate and freeze in Reduced while real states update. All 32 touched/new code files meet 120 columns, and
  whitespace checks pass.
  Earlier 29/31-case browser runs each had one failure: a mismatched report fixture, then sampling the same Canvas
  idle frame twice. Matching job/kind/reference and polling across 900 ms frames corrected these; the production
  new-own-job guard remains intact. Those runs are distinct from the final all-green run above.
* **Evidence:** [department screenshots, controlled video and provenance](design/robot-office/departments/README.md):
  nine screenshots, one visibly labeled 37.40-second 1440×900 H.264 recording, 25 identities, visible laptop controls,
  no mobile horizontal overflow and zero page/console errors. The actual stopped-sandbox lounge capture is separate
  from controlled working/Brain/handoff states. All 14 captured production-file hashes are recorded. The recording
  demonstrates choreography, not real processing times, GPU performance or platform-account behavior.
* **Not verified:** Windows CMD/setup/fonts/scaling, RTX 3050 CUDA/NVENC and real platform accounts/uploads remain
  owner checks. No real post, owner account change, purchase or deployment occurred. GPU dependencies, `.mcp.json`,
  Playwright versions and read-only `e2e/tests` are unchanged. Earlier checkpoint results below remain historical.

## 2026-10-09 · Social pixel office and off-duty lounge life

* **Tool:** Codex. **Branch:** `claude/project-thread-vw1n9y`, draft PR #14. **Base:** `5b1f7a9`.
  **Result:** the commit containing this entry. PR stays draft/unmerged.
* **What changed:** six authored arcade/game/drink/snack/read/rest gestures in furnished lounge zones, with 29
  exclusive places, 25 stable cast homes, phased rotation and at most two recreational walkers. Real work and
  document transfers preempt breaks; job icons and references remain truthful. The owner's stopped-office
  recreation exception preserves Paused badges; individual pause while Running/unavailable remains quiet, and
  global Pause/Reduced/hidden/stale views freeze. Added pinned GSAP 3.15.0 pure easing with its standard no-charge
  license notice, cached Pixi BlurFilter light pools and an original locally bundled generated skyline. Optional
  image loading has a 1.5-second bound/procedural fallback and safe cropped-texture cleanup. Canvas has simpler
  phase-driven gestures; frozen Brain cues stay still on expiry. Dense whole-map names are staggered and the close
  lounge camera uses compact labels. Built frontend; no backend/media/publishing behavior changed.
* **Why:** the owner requested better graphics tools and off-duty robots that play, eat and drink while retaining
  the refined retro style and actual job behavior.
* **Validation:** full fast pytest: 641 passed, seven slow cases deselected, in 280.30 s. Final TypeScript/Vite build
  passed in 5.83 s with the existing 904 KB lazy graphics chunk warning. All 23 focused browser cases passed together
  in 6.4 min (lounge 6, living 7, motion 3, pixel 3, robot 4). All 14 distribution files are SHA-256 identical to the
  assets used in that final run after source-formatting cleanup.
  Geometry/controller checks covered 2916 + 4770 routes, 600 simulated seconds with all 25 identities rotating
  safely, exclusive reservations/max two walkers, and 150 mixed-state transitions. Actual rendered checks show
  all six Full gestures changing pixels, zero Reduced drift and real-work suppression of leisure props; frozen
  Canvas Brain pixels remain unchanged when an activity cue expires.
* **Evidence:** [actual isolated screenshots, labeled recordings and editing guide](design/robot-office/lounge/README.md).
  Final desktop/laptop/mobile captures retain all 25, visible laptop controls, no mobile overflow and zero page
  errors. Actual stopped lounge recording: 33.24 s; labeled controlled work/Brain/handoff recording: 33.48 s.
  Both are 1440×900 H.264 and have zero page errors. An initial controlled recording timed out with three browsers
  competing; its standalone rerun succeeded. Only startup before the provenance banner was trimmed, without retiming.
  These recordings do not measure clipping speed or GPU performance.
* **Not verified:** Windows CMD/installation/PC graphics/scaling, RTX 3050 CUDA/NVENC and real accounts/uploads.
  The seven slow media cases were not repeated for this frontend-only scope; prior results remain historical.
  GPU pins, `.mcp.json`, Playwright versions and `e2e/tests` remain unchanged. No real posts, account changes,
  hosting purchase or deployment occurred.

## 2026-10-08 · Living office, seated robots and animated Brain

* **Tool:** Codex. **Branch:** `claude/project-thread-vw1n9y`, draft PR #14. **Base:** `a119dfd`.
  **Result:** the commit containing this entry. PR stays draft/unmerged.
* **What changed:** a 960×640 furnished office with consistent robot/desk/chair proportions, clear aisles and 25
  individual lounge seats. Idle/waiting/paused/unavailable robots rest there; working/reviewing robots walk to
  their own desks and sit with bent knees and keyboard hand motion. Confirmed fresh job transitions and worker
  reports bring both robots together, pass one visible document and return them to the latest actual destination.
  Ownership/cursor recovery prevents outdated senders after hidden/paused/offline periods and history resets.
  The animated Brain has neural hemispheres, synapses and layered orbits; decorative Standby and true Processing
  are labeled separately. Paused/Reduced/offline states still the art. Added a room camera, matching Canvas
  compatibility layout, separated handoff names and built frontend. No new dependency or backend behavior.
* **Why:** the owner requested realistic proportions, idle lounge behavior, seated work, actual handoffs and a
  cooler animated Brain while keeping refined retro pixel art. Existing PixiJS supplies the needed tools.
* **Validation:** TypeScript/production build passed; 17 office Python checks passed in 6.10 s. All 17 focused browser
  checks passed together in 3.1 min. Browser coverage is seven
  living-office cases plus three motion, three pixel and four robot-office cases; exact final outcomes are at the
  top of [IMPLEMENTATION_STATUS.md](docs/IMPLEMENTATION_STATUS.md). Both suspension and reset sender regressions
  passed. Actual desktop/laptop/mobile captures reported zero browser errors; all 25 identities and laptop controls
  fit. The earlier full backend/media suites were not repeated for this frontend-only change.
* **Evidence:** [actual isolated screenshots, labeled controlled animation and editing guide](design/robot-office/living/README.md).
  The controlled video demonstrates graphics and event choreography, not real clipping time or GPU processing.
* **Not verified:** Windows CMD/PC graphics/scaling, RTX 3050 CUDA/NVENC and real connected accounts. Dependencies,
  GPU pins, `.mcp.json`, Playwright versions and `e2e/tests` are unchanged in this checkpoint. No real posts,
  account changes, purchases or deployment occurred.

## 2026-10-08 · Refined pixel office and Windows path recovery

* **Tool:** Codex. **Branch:** `claude/project-thread-vw1n9y`, existing draft PR #14. **Base:** `c33a291`.
  **Result:** the commit containing this entry. PR stays draft and unmerged.
* **What changed:** pinned PixiJS 8.22.0 paints the furnished office and all 25 refined robot rigs; Team/detail/gallery
  portraits share one lazy offscreen renderer with a bounded frame cache. Static scenery is cached separately from
  live robot/room layers. A scoped navy studio shell fits the map, details and controls at laptop sizes. Existing
  job events still govern work, walks, report handoffs and decisions; COMMAND visibly signals recorded approval.
  Motion preferences remain and graphics failure restores the original Canvas artwork and controls.
  Included third-party graphics notices and rebuilt distribution. No backend or publishing behavior changed.
  Windows setup now explains the long-path failure shown in the owner's screenshot and recommends fresh ZIP contents
  directly in a short folder (`C:\CF14`), creating a fresh `.venv` while preserving normal data. Both venv and pip
  failure branches include the guarded remedy; no registry changes or administrator settings.
* **Why:** the owner requested using better graphics tools and chose refined retro pixel art; their nested archive
  extraction also caused a Windows dependency installation failure.
* **Validation:** TypeScript/production build passed. Office Python: 17 passed in 7.20 s. Final isolated browser run:
  ten passed in 59.3 s (3 motion, 4 robot, 3 graphics/portrait/visible approval cases). The earlier scratch 60-second
  run timed out in the last sequential viewport check; a corrected timeout passed nine, then the final ten-case run
  passed with the approval pixel regression and scenery cache. Actual desktop/laptop/mobile captures recorded zero
  browser errors. 25 Team/100 gallery portraits rendered with a stable shared context count. Reduced-mode approval
  differs from idle in actual rendered pixels. Diff checks passed. Prior full/media results remain the preceding
  checkpoint's evidence and were not rerun in full for this graphics follow-up.
* **Evidence:** [screenshots, labeled controlled animation and source-editing guide](design/robot-office/retro/README.md).
  Pixi needs no account, plugin hookup or paid AI service. The video uses controlled test events, not real processing.
* **Not verified:** Windows CMD execution/installation, PC fonts/scaling/graphics, RTX 3050 CUDA/NVENC and real accounts.
  GPU dependencies, `.mcp.json`, Playwright versions and `e2e/tests` remain unchanged. No real posts, purchases,
  account permission changes or deployment occurred.

## 2026-10-08 · Public publishing, teachable Brain and complete robot office

* **Tool:** Codex. **Branch:** `claude/project-thread-vw1n9y`, existing draft PR #14. **Base:** `fea045d`.
  **Result:** the commit containing this entry. PR stays draft and unmerged.
* **What changed:** all 25 named robots remain readable with real job states, dependencies/handoffs and saved
  Follow system / Full / Reduced motion. Brain supports safe local document/good/bad example uploads, search,
  revision approval/edit/disable/delete, complete metadata/text/influence export and immutable later-plan influence.
  Approved typed preferences alter new blueprints; uploaded prose is inert and examples never become posting results.
  Discovery uses topic/language/freshness/relevance evidence and explains estimates and weak-story filters.
  Final checks send bounded repairs to the responsible stage. Video-only sources fail before Whisper; live
  segments with missing audio preserve the timeline and returning audio. Existing GPU execution paths remain.
  Explicit NEW Public YouTube automation uses channel/audience-bound consent, recorded project-audit confirmation,
  exact-file checks, limits and local due-time uploads without `publishAt`; old Private schedules remain Private.
  TikTok still needs eligible app/creator options/per-post consent, with truthful draft/manual fallbacks.
  Learning separates public/selected cohorts and waits 48 hours. Added stage timing report and isolated Windows launcher.
* **Final regression fixes:** Pause/Stop is checked atomically when claiming work; database migrations are serialized
  across threads/processes and committed before the next initializer; clearing the YouTube audit confirmation blocks
  new automatic Public approvals/uploads while preserving Private permissions; Brain export removes browsing caps.
  The Windows GPU-check command explicitly selects test data and distinguishes CUDA proof from NVENC render proof.
* **Why:** the owner's continuation prompt supersedes selected-only new uploads and hidden idle robots, while
  preserving existing visibility/data, platform restrictions and the unmerged PR.
* **Validation:** 641 passed, 7 deselected in 263.21 s. All seven slow cases and ten sandbox browser checks passed across initial
  runs and targeted reruns, with exact outcomes/fixture corrections in [IMPLEMENTATION_STATUS](docs/IMPLEMENTATION_STATUS.md).
  TypeScript/production build passed. Focused startup/core/office/TikTok: 66 passed; full Brain export: 8;
  public-audit/automatic-publishing recheck: 33; publishing: 44; returning-audio/recovery: 28.
  Disposable old-schema upgrade preserves rows/approval/media bytes. Before-fix reconstructions fail the new
  Stop/startup/export regressions. Tests use synthetic media/transcripts and local fake publishing, with real
  FFmpeg; no owner accounts/data or real uploads.
* **Evidence:** [screenshots, actual job animation, controlled motion demo and saved Brain influence](design/robot-office/screenshots/README.md).
  [Processing measurements/server advice](docs/PERFORMANCE.md) and [separate Windows ZIP test](docs/WINDOWS_PR14_TEST.md).
* **Not verified / blocked:** RTX 3050 CUDA/NVENC, Windows setup/fonts/scaling, real network intake and connected
  account scopes/project/app approvals/returned Public visibility. Official developer hosts returned proxy 403;
  current policies could not be freshly verified. Google's reachable official GitHub schema confirms only the
  `publishAt` field contract. Audit settings record owner confirmation, not programmatic approval.
  No server purchase, deployment, account permission changes or real posts occurred.

## 2026-10-08 · PR #14 review round

* **Tool:** Claude Code (cloud session). **Branch:** `claude/project-thread-vw1n9y` (draft PR #14), on top of
  `f71238c`. **Result commits:** `cf54204` (code) and the commit that adds this entry (docs).
* **What changed**
  * Public video importing stays on (owner, 2026-10-08). The beginner browser test now expects public videos to be
    clipped on the PC, to pass the final check and never to be planned or posted; the beginner answers *who
    watches* before anything is planned. A rule recorded after a video was clipped now reaches that video.
  * TikTok: a post-it-yourself page for the ready-to-post package (download, copy caption, steps, then link the post
    or mark it posted, `POST /scheduled/{id}/posted`); branded content only for Friends; a full inbox (5 pending
    drafts) holds TikTok posts for a day; labels that don't claim who could see a post. *I shared it* updates the
    post itself; held public posts can be sent to the selected viewers from their page.
  * Approvals and the automatic-publishing permission name the connected account; another account connected means a
    new approval. START pressed again before its work ran queues nothing new.
  * Brain and learner: uploads nobody else could watch are not evidence (*unconfirmed*), maturity counts from
    sharing, each platform rolls back on its own, a rollback or reset is not undone by the same results, 20 clips
    per side, identical results are inconclusive, the learner needs views and 5 videos.
  * Health: GPU errors and CPU fallback, accounts as information, *Unknown — not updating* when the feed is lost, a
    size-bounded `workers.log`, discovery stalls. Integration cards: Test connection, last check, rate limits.
  * Trend and Source Scores: missing parts count as neutral, with coverage, confidence and the missing parts stored.
    Video access failures carry one of 13 reasons; a named wait is honored, temporary problems are retried.
  * Robots: the crown badge of COMMAND and the managers, TRACKER green, SPARK's blue eye, PATCH's orange lamp;
    contact sheet re-captured. Setup and Sources text no longer say other people's videos are skipped.
  * Docs: privacy page (Test connection result, log sizes, the account an approval names, posts you made yourself),
    `docs/OFFICE.md`, `docs/PLATFORM_CAPABILITIES.md`, INSTALL and README (TikTok), AGENTS.md decisions, this file,
    `AI_HANDOFF.md`, `docs/IMPLEMENTATION_STATUS.md`.
* **Why:** the owner's follow-up of October 8, 2026 (compare with the spec, fix the beginner test without disabling
  public videos, recheck TikTok, verify the Brain, steps to test on the PC).
* **Tests run:** listed in the JSONL entry and in `docs/IMPLEMENTATION_STATUS.md` (test log).
* **Not verified:** GPU on the RTX 3050, real YouTube and TikTok accounts, TikTok's decision on the app, Windows.

## 2026-10-07 · The robot office screens, docs and handoff

* **Tool:** Claude Code (cloud session). **Branch:** `claude/project-thread-vw1n9y` (draft PR #14), on top of
  `26f6b8f`. **Result commit:** the commit that adds this entry.
* **What changed**
  * The app's places are now Office, Missions (the former Autopilot page), Clips (the former Library), Queue (the
    former Posts) and Settings; old addresses open the new pages in place.
  * Office: a pixel-art office (layout of reference image A) whose 25 robots stand where their real jobs are, walk
    and carry reports from the event feed, and rest in the Lounge; details panel (overview, robot, room), activity
    feed, bottom bar (Start, Pause, Resume, Stop all, Pause publishing), list view, Reduce animations, a stale mark
    when the feed is lost. Team roster (`#/office/team`) and developer gallery (`#/dev/robots`).
  * Settings → Integrations: who watches your uploads per platform (selected viewers, only you, keep on this PC),
    "My viewers changed", each connection's capabilities, NVIDIA AI setup with opt-in, check, small test and
    disconnect. Settings → Advanced: the Brain's limits and the Dev Log.
  * Clips → Test feedback; the Queue shows who each post is for, what really happened and whether results exist.
  * YouTube readings mirrored into the Brain now follow the 30-day YouTube data rule like the readings themselves.
  * Two slow video tests that `26f6b8f` missed now expect YouTube uploads as Private without `publishAt`.
  * Docs: `docs/OFFICE.md`, `design/robots/README.md`, this file, `AI_HANDOFF.md`, README beginner steps and NVIDIA
    setup, privacy page (NVIDIA excerpts, tester answers, office and learning records, audience records).
* **Why:** the owner's master prompt for the robot office (October 7, 2026), sections 15-23 and 26.
* **Tests run:** listed in the JSONL entry and in `docs/IMPLEMENTATION_STATUS.md` (test log).
* **Not verified here:** GPU transcription and rendering on the RTX 3050, real YouTube or TikTok uploads, real
  invitations, TikTok's audit, real NVIDIA requests, Windows-specific behavior.

## 2026-10-07 · Selected audience, office backend, Brain guards and optional NVIDIA AI (`26f6b8f`)

* **Tool:** Claude Code (cloud session). **Branch:** `claude/project-thread-vw1n9y`. **Base:** `eff96fb`.
* **What changed**
  * Uploads go only to a selected audience: YouTube Private without `publishAt`, with viewers you invite in YouTube
    Studio; TikTok followers or friends through an audited Direct Post, otherwise a ready-to-post package. Public,
    unlisted and Everyone are blocked on every path; posts planned before keep their audience and old public ones
    are held. Approvals and automatic uploads are bound to the audience stamp (`APPROVAL_SCHEME = 3`, Private-only
    consent v2). Pause publishing.
  * Office backend (`clipfoundry/office`): the cast registry, the event feed with a resume cursor, managers'
    reports, the Director's recorded decisions at four checkpoints, health readings, room details, controls,
    capability registry and integration cards.
  * Brain (`autopilot/brain.py`): observations with provenance, null kept apart from zero, idempotent CSV import
    with preview, corrections kept; strategy changes need 30 mature clips from 5 videos in one selected audience,
    move at most 10%, wait for new results and roll back. The older learner follows the same guards.
  * Optional NVIDIA text AI (`pipeline/nvidia.py`), off by default, with opt-in, budgets and local fallback.
* **Why:** the same master prompt, sections 9-14 and 21-22.
* **Tests run:** `pytest -m "not slow"`: 543 passed (new suites `test_audience`, `test_office`, `test_brain`,
  `test_nvidia`).
* **Not verified here:** as above.
