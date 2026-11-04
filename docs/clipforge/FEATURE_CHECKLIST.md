# ClipForge feature checklist

Status as of 2026-11-04, reviewed branch `claude/new-session-b9itcy` (PR #16; see GitHub for merge state). **Implemented** means the code exists and an
automated test or a recorded check exercises it here. Fake Google/TikTok servers, a fake OpenID provider and
synthetic media were used throughout; nothing real was signed in to, uploaded or deployed. Anything that needs a
real account, server, footage or speech model is listed under "Not verified".

## Requirements

| # | Requirement | Status | Implementation | Evidence | Not verified / next action |
| --- | --- | --- | --- | --- | --- |
| 1 | Newest baseline, handoff | Implemented | Fast-forward to `codex/cloud-plan` @ 6585c58 | `AI_HANDOFF.md`; baseline 1,556 passed | — |
| 2 | FilmCraft integration experiment | **Blocked** | Report + harness: `docs/clipforge/EDITOR_INTEGRATION.md`, `scripts/filmcraft_experiment.py` | Pinned source read (license, notices, CLI, web, gaps) | Building upstream code was refused by this session's safety policy. Owner: approve a build, or run the harness locally. |
| 3 | Versioned engine adapter, FFmpeg fallback | Implemented | `clipfoundry/studio/engine.py` (`ffmpeg-v1`) | `tests/test_studio_video.py` (slow) | FilmCraft adapter not written until (2) passes |
| 4 | Cloud mode, fail-closed startup | Implemented | `clipfoundry/cloud/settings.py`, `api._cloud_startup` | `test_cloud_auth.py` (startup refusal, key file rules) | Real server not deployed |
| 5 | Owner-only sign-in (issuer, audience, signature, expiry, subject, nonce, PKCE, state bound to the browser) | Implemented | `cloud/oidc.py`, `cloud/auth_routes.py`, `cloud/identity.py` | `test_cloud_auth.py` (wrong identity, email-is-not-identity, expired, wrong audience/issuer/nonce, other key, replayed state, other browser) | Real Google OIDC client not created (owner action) |
| 6 | Sessions: logout, sign out everywhere, idle/absolute expiry, removed owner | Implemented | `cloud/identity.py` | `test_cloud_auth.py` | — |
| 7 | Hosts, CSRF, origin, rate limits, security headers, strict CSP | Implemented | `cloud/middleware.py`; PixiJS eval-free import | `test_cloud_auth.py` | Office rendering under the CSP was not loaded in a browser in cloud mode |
| 8 | Workspace ownership on APIs, media, ranges, thumbnails, exports | Implemented | `cloud/ownership.py` (app-wide dependency), workspace columns | `test_cloud_auth.py::test_a_second_identity_sees_none_of_the_owners_data`, `test_studio_uploads.py` | — |
| 9 | Full multi-user isolation (Autopilot, Brain notes, global settings, publishing per workspace) | **Partial** | Secondary workspaces are refused these single-workspace areas and shared guidance/processing routes (403) | `test_cloud_auth.py` | Needed before public sign-up, which stays off |
| 10 | Encrypted Linux secret storage, no base64/plaintext in cloud | Implemented | `secure.py` AES-256-GCM, key file outside data | `test_cloud_auth.py` (tamper, wrong key, refuse base64, one-time upgrade) | — |
| 11 | Bug fix: Keychain values re-sealed at every start | Implemented | `db.SEALED_PREFIXES` | `test_cloud_auth.py::test_already_sealed_settings_are_never_sealed_again` | Not reproduced on a real Mac |
| 12 | URL ingestion hardening in cloud | Implemented | `netguard.check` ignores private allowance in cloud; link import checked | `test_cloud_auth.py` | No OS-level sandbox for media subprocesses (protocol whitelist only) |
| 13 | Resumable uploads, integrity, private streaming | Implemented | `studio/uploads.py`, `/api/uploads`, `/api/assets` | `test_studio_uploads.py` (interrupt/resume, cut-back, damage, dedupe, storage full, isolation) | — |
| 14 | Durable jobs with leases, idempotent completion, recovery, cancel | Implemented | `studio/jobs.py` (studio work); existing manual worker resume and Autopilot queue | `test_studio_jobs.py`, `test_studio_video.py` | Two processes claiming the same job only tested at the database level |
| 15 | Bounded resources | **Partial** | One heavy thread for all studio/manual work, upload/storage limits, systemd `MemoryMax`, `OMP_NUM_THREADS` | Upload/storage tests | No per-job CPU/scratch-disk quota yet |
| 16 | Backup/restore, retention preview | **Partial** | `python -m clipfoundry backup/restore/retention` | `test_backup.py` | Retention has no screen in Settings yet |
| 17 | Multiple YouTube/TikTok connections, migration without changing tokens | Implemented | `social_connections`, `db._migrate_connections`, `publish/connection_routes.py` | `test_multi_accounts.py`, `test_clipforge_rename.py` | — |
| 18 | Per-connection tokens, refresh locks, reconnect bound to its account | Implemented | `publish/common.ConnectionToken` | `test_multi_accounts.py` (concurrent refresh once per account, wrong channel refused) | — |
| 19 | Destination per publication, partial success, no repeat to the successful account | Implemented | `connection_id` on publications; publish request names the account | `test_multi_accounts.py::test_partial_success_retries_only_the_failed_channel` (CF-10) | — |
| 20 | Per-account spacing and limits next to shared quotas | **Partial** | Shared API-project quota counts every channel | `test_multi_accounts.py::test_both_channels_share_the_api_project_quota` | Spacing and daily limits are still per platform, not per account |
| 21 | Autopilot automation per selected account | **Partial** | Automation stays bound to the account named in its permission (the default) | Existing Autopilot suites | Choosing several automation destinations is not built |
| 22 | Rename to ClipForge, compatibility names kept | Implemented | Visible text in app, API title, callback pages; `docs/clipforge/RENAME_PLAN.md` | `test_clipforge_rename.py` (CF-15) | Website and provider consoles not changed (owner review; `WEBSITE_COPY.md`) |
| 23 | Home with exactly two creation choices | Implemented | `frontend/src/pages/Home.tsx` | Screenshots 1440–320 px | — |
| 24 | Make clips: Highlights / Full stories, style, customize, destinations, Make & upload | Implemented | `pages/MakeClips.tsx` (file), `#/create/link` (link or own transcript, the earlier Add video page), `studio/clips_flow.py`, `studio/autopublish.py` | `test_studio_render.py` (slow), recorded flow | Real uploads |
| 25 | Four-question brief, Remember this style | Implemented | `pages/MakeVideo.tsx`, `studio/video_flow.create` | `test_studio_video.py` | — |
| 26 | Guidance precedence, conflicts, frozen snapshot, "Used from your Brain" | Implemented | `studio/guidance.py`, render follows snapshot | `test_studio_guidance.py`, `test_studio_render.py` (CF-07) | — |
| 27 | Full stories: chunked detection, gaps, completeness, review controls | Implemented (local estimate) | `pipeline/stories.py`, `studio/story_review.py`, `components/StoryReview.tsx` | `test_full_stories.py` (CF-04, CF-05), slow render | **Blocked:** model-based semantic analysis (no model configured); boundaries are labelled as an estimate |
| 28 | Complete 9:16 story clips with captions and moving framing | Implemented | Existing renderer (face/speaker tracking, safe captions) with story policy | `test_studio_render.py` | Real camera footage with moving subjects not tested |
| 29 | Destination eligibility, full master kept, no silent split | Implemented | `studio/eligibility.py` (rules checked 2026-11-04) | `test_full_stories.py` (CF-06) | — |
| 30 | Split a too-long story into parts on request | **Partial** | Manual split/trim exists | Story tests | No one-click "make parts" action |
| 31 | Full video: rough cut, edits, revisions, reopen, preview, render, download, plan export | Implemented | `studio/video_flow.py`, `pages/VideoReview.tsx` | `test_studio_video.py` (CF-09) | — |
| 32 | Full-video publishing decision | **Partial** | Download works | — | Needs a 16:9 quality-gate policy and a separate consent screen |
| 33 | Skill library (import, preview, enable, export, delete, schema, example) | Implemented | `studio/skills.py`, `components/StylesSkills.tsx`, `SKILL_SCHEMA.md` | `test_studio_guidance.py` (CF-08) | — |
| 34 | Redesigned shell and screens | Implemented | `App.tsx`, `theme.css`, new pages; existing pages restyled through the tokens | Screenshots, recorded flow | Older inner pages (Missions, post review) keep their structure |
| 35 | Light/dark/system, accents, density, motion, synced | Implemented | `prefs.tsx`, `/api/preferences/appearance`; motion stays the existing per-browser Animations choice (`motion.tsx`), so a saved account value never overrides a device's accessibility setting | `test_studio_prefs.py`, `e2e/sandbox/motion.spec.ts` | Motion is deliberately not synced between devices |
| 36 | Saved layouts per device, reset | **Partial** | Saved per device class; editor in Settings; applied on the full-video Review screen | `test_studio_prefs.py` | Create and Office screens do not read their saved layout yet |
| 37 | Robot names (save, reset, Unicode, text only, role kept) | Implemented | `studio/prefs.py`, Team page, cast registry | `test_studio_prefs.py` (CF-13) | — |
| 38 | Office and robots kept | Implemented | Unchanged map/robots; dark stage in the new palette; robot team on Home | Before/after screenshots | — |
| 39 | Audio guarantees on every engine | Implemented | Clip renderer unchanged; engine mirrors its final-clock rules | Engine and story renders validate raw AAC timing | Real platform transcode |
| 40 | Capacity benchmark | **Blocked** | `scripts/benchmark_batch.py` | Smoke run (reports "unverified") | No server or representative footage here |
| 41 | Owner-only deployment configuration | **Partial** | `deploy/` (Caddy, systemd, example env), `deploy/README.md` | Config reviewed; app refuses unsafe config | Not deployed: owner must create the VM and OIDC client |
| 42 | Privacy/storage disclosure | Implemented | `docs/legal/privacy.html` (cloud, sessions, uploads, styles, skills, names) | — | Not published |

## Acceptance scenarios

| ID | Status | Evidence |
| --- | --- | --- |
| CF-01 | Implemented (fake provider) | `test_cloud_auth.py` |
| CF-02 | Implemented | `test_studio_uploads.py`, `test_studio_jobs.py` |
| CF-03 | Implemented | `test_studio_render.py`, recorded flow |
| CF-04 | Implemented (detection on the labelled 12-minute script; rendering on an 83 s recording with real speech) | `test_full_stories.py`, `test_studio_render.py` |
| CF-05 | Implemented | `test_full_stories.py` |
| CF-06 | Implemented | `test_full_stories.py` |
| CF-07 | Implemented | `test_studio_render.py` (style, override, restart, style revision) |
| CF-08 | Implemented | `test_studio_guidance.py` |
| CF-09 | Implemented | `test_studio_video.py` |
| CF-10 | Implemented | `test_multi_accounts.py` |
| CF-11 | Partial (per-account spacing) | `test_multi_accounts.py` |
| CF-12 | Implemented | `test_studio_render.py` (re-render posts nothing), existing approval-hash suites |
| CF-13 | Implemented | `test_studio_prefs.py` |
| CF-14 | Partial | `test_studio_prefs.py`; screenshots 1440/1024/768/390/320; `e2e/tests/app-shell.spec.ts` (no sideways scroll at 390 px on 15 pages, skip link, menu dialog, focus on each title); full keyboard pass of every new screen not recorded |
| CF-15 | Implemented | `test_clipforge_rename.py`, `test_multi_accounts.py` |
| CF-16 | Implemented (synthetic media) | Existing slow audio regressions, engine/story render AAC checks |
| CF-17 | Implemented (existing) | `test_public_publishing.py` unknown-outcome and reconciliation tests |

## Codex merge review and website publication (November 4, 2026)

- YouTube eligibility: outputs longer than 15 minutes are held when channel verification cannot be established;
  the master remains downloadable. Boundary and multiple-destination checks cover the hold.
- Test installs now include cloud requirements, including PyJWT for the fake OpenID provider.
- Creation/render copy no longer mislabels desktop processing as remote server processing.
- CF-18 website: implemented and published as version 3; five viewport sizes and interactive controls checked.
  Exact source/deployment IDs, release limitations and rollback: [WEBSITE_DEPLOYMENT.md](WEBSITE_DEPLOYMENT.md).
- The native installers are unchanged and do not include this PR. Owner-only cloud code is not a live hosted service.
- The earlier FilmCraft build refusal is a historical session limitation; no new approval requirement was inferred
  from it during this merge review. The FFmpeg implementation remains the available engine.

- Isolation review: a secondary workspace could read owner Brain note metadata via guidance previews. The
  regression reproduced it; guidance and processing routes now remain primary-owner-only until their shared
  services are migrated. All 70 targeted cloud/studio/account checks passed after the fix.
