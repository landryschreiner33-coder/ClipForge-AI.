# Audit of the current interface

## What was inspected

| | |
| --- | --- |
| Repository | `landryschreiner33-coder/ClipForge-AI.` |
| Default branch | `claude/wonderful-ritchie-909tq3` at **97b5c9a** (PRs #1-#5 merged). This proposal branches from here. |
| PR #6 (draft, not merged) | `claude/fix-overnight-run-simplify-81jehi` at **d00cdf0**. Its UI changes were tested at e3bf152. It adds your videos folder, the "needs videos" message and the five keep-awake states. It was read from a separate worktree and left untouched. |
| Method | I read all of `frontend/src` (App, api.ts, autopilot.ts, 9 pages, 9 components, styles.css) and the backend that feeds the simple Autopilot page: `autopilot/home.py`, `autopilot/routes.py`, `autopilot/host.py`, `api.py`, `config.py`, `pipeline/quality.py` (check labels) and `db.py` (`delete_project`). I also ran PR #6's code in the throwaway sandbox (`e2e/sandbox/run_sandbox.py`: temp data, fake Google/TikTok, synthetic video) and took 20 screenshots at 1440×900 and 390×844. |

## Current routes (`frontend/src/App.tsx`)

| Address | Page | Notes |
| --- | --- | --- |
| `#/` | Dashboard | The fallback for unknown addresses. |
| `#/create` | Create | Upload or import from a URL. |
| `#/projects` | Projects | Grid of source videos. No search or filter. |
| `#/project/:id` | ProjectView | Processing progress, clips, selection, ZIP, regenerate. |
| `#/clip/:id` | ClipEditor | 6 tabs: trim, framing, captions, hook, audio, post package. |
| `#/publish/:clipId` | Publish | Versions, post text, YouTube panel, TikTok panel, uploads. |
| `#/autopilot[/system\|sources\|jobs\|learning]` | Autopilot | First run, simple Home, Advanced tabs. `overview` is an alias for `system`. |
| `#/publish-center[/upcoming\|problems\|published\|history]` | PublishCenter | Planned posts. |
| `#/settings[/advanced]` | Settings | General and Advanced. |

Sidebar: Dashboard, Create, Projects, Autopilot, Publish Center, Settings, plus a "Create clips" button.

## Components and API

* **Pages:** Autopilot.tsx (1165 lines; Onboarding, Home, NeedsYou, ActivityLog, SystemDetails, GpuCard, QuotaCard,
  TrendsCard, SourcesTab, JobsTab, LearningTab and 8 dialogs), Publish.tsx (506), Settings.tsx (361),
  ClipEditor.tsx (337), ProjectView.tsx (297), PublishCenter.tsx (258), Dashboard.tsx (202), Create.tsx (192),
  Projects.tsx (80).
* **Shared components:** `ui.tsx` (Icon, Logo, Toggle, Segmented, ScoreBadge, StatusBadge, Modal, toast, usePoll,
  StylePicker); `accounts.tsx` (ConnectButton, AccountBadge, setup steps); `approve.tsx` (ApproveDialog);
  `autoPublish.tsx`; `autopilotSettings.tsx`; `postpack.tsx`; `stats.tsx`; `versions.tsx`; `viral.tsx`.
* **API client** (`api.ts`): health, stats, settings, projects (list/get/rename/delete/cancel/reprocess/importUrl),
  clips (get/patch/render/words/versions/regeneratePost), accounts (connect/disconnect/tiktokCreator), publish,
  publications, performance and stats refresh, and progress over SSE. `renameProject` exists, but no screen uses it.
* **Autopilot client** (`autopilot.ts`): status (with `home`), enable/start/permission, stopAll/resume, scan, sources
  and rights, feeds, rules, agreements, jobs (logs/cancel/retry), quota, trends, learning, activity, scheduled
  (approve/edit/reschedule/cancel/retry/publishNow/link/resolve), and autoPublish.
* **Types that the redesign depends on:** `HomeView` (currently, next_look, needs_you, upcoming, keep_awake,
  my_videos, auto_publish, pc_note, skipped_today), `NeedsYouItem.type` (account, sleep, gpu, rights, file,
  approve, publish, videos, other), `GpuStatus` (`available` vs `mode`, `last_transcription.device`, problem, fix),
  `ScheduledItemRow` (clip_id, status, status_note, fix, approval.hash), `Job` (progress, stage, ref_type, ref_id),
  and `Project`/`Clip` (has_thumbnail, stage, progress, version).

## Feature-location map (today)

| Feature | Where it is now | Data |
| --- | --- | --- |
| Next action and problems | Autopilot → Home → NeedsYou, and scattered banners | `home.needs_you` (the backend orders it: account, sleep/gpu, rights, file, approve, publish, videos) |
| Start, pause, stop all, resume | Autopilot Home header, "STOP ALL JOBS" in System | `start`, `enable`, `stopAll`, `resume` |
| Keep awake (PR #6) | Autopilot Home PC line and NeedsYou | `home.keep_awake`, the sleep needs_you item |
| Your videos folder (PR #6) | Autopilot Home card | `home.my_videos`, `openMyVideos` |
| GPU state | Dashboard System panel, Autopilot System GpuCard | `/api/health`, `status.gpu` |
| Recent work | Dashboard "Recent projects" | `/api/projects` |
| Upload and URL import | Create | multipart upload, `importUrl` |
| Clips of a video | ProjectView | `project(id).clips` |
| Clip editing | ClipEditor (6 tabs) | `patchClip`, `renderClip`, `clipWords` |
| Versions | Publish page (VersionsCard) | `versions`, `createVersions`, `setActiveVersion` |
| Manual posting | Publish page | `publish`, `publications`, `tiktokCreator` |
| Planned posts and approval | Publish Center plus ApproveDialog | `scheduled`, `approve`, `publishNow`, `resolve`, `link` |
| YouTube automatic publishing | Autopilot Home line plus AutoPublishDialog | `autoPublish`, `enableAutoPublish` |
| Performance | Dashboard PerformanceCard, post stats rows | `performance`, `refreshAllStats` |
| Accounts and app codes | Settings General and Settings Advanced (repeated) | `accounts`, settings `*_client_*` (masked `********`) |
| Rights, agreements, sources, jobs, learning | Autopilot Advanced tabs | the Autopilot client |

## What the audit found

1. **Dashboard is a marketing page.** It opens with a hero ("Turn long videos into ready-to-post shorts"),
   pipeline chips, four stat cards (one says "$0 runtime cost"), a system-spec panel and, at the bottom, performance.
   "Create clips" appears in the sidebar and in the hero.
2. **Two homes.** The Dashboard and the Autopilot Home both summarize the app, and the Autopilot Home repeats
   dashboard numbers ("1 / 15 clips").
3. **At 390 px the navigation loses its labels.** The sidebar becomes an unlabeled icon rail, and the "Create clips"
   button is clipped to "reate cli".
4. **Shouting buttons.** Primary buttons are all caps (START AUTOPILOT, PAUSE AUTOPILOT, OPEN MY VIDEOS FOLDER,
   REVIEW POSTS, CONNECT YOUTUBE).
5. **A clip and its posts are hard to connect.** Versions live on the Publish page, not in the editor. The Publish
   Center rows carry up to 6 badges and 5 buttons. Nothing on a clip shows its planned posts.
6. **The editor has no unsaved-change guard.** Leaving the page drops edits silently, and it doesn't say which
   version the preview shows.
7. **Text glitches seen in the sandbox.** The project header shows "undefinedx realtime" when
   `info.transcription.speed` is missing. A Publish Center row shows `trend “”` when the trend topic is empty.
8. **The project page opens with two long notices** before the clips.
9. **Accounts appear twice** in Settings (General, and again under Advanced → Publishing).
10. **No project search or filter**, although the Library can grow large with Autopilot.
11. **Time zone confusion.** A notice explains UTC versus America/Chicago; row times don't say which zone they use.

The good parts, which the redesign keeps: the backend already orders `needs_you` by urgency; every problem already
carries a `fix`; the five keep-awake states are honest; GPU availability and the actual processing mode are
separate fields; quality checks have plain labels; and the approval flow is bound to the exact file.

## What I could not inspect

* **The real Windows PC:** Segoe UI rendering, the RTX 3050, real CUDA transcription, the black console window,
  and the real Windows sleep refusal. The sleep states were read from PR #6's code and its sandbox output only.
* **Real YouTube or TikTok accounts:** real TikTok creator info (privacy options, whether comments are allowed),
  audit restrictions, and real statistics. The fake platforms stand in for them.
* **The approve dialog screenshot:** the capture fired before the modal opened. The dialog was audited from
  `components/approve.tsx` instead.
* **A screen reader.** Accessibility was checked with axe-core and keyboard tests only (see SPEC.md).
