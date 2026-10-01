# ClipFoundry redesign: design specification

**Direction: a quiet dark studio.** A calm dark workspace where the videos carry the color. Each view has one warm
orange action, and every status is a word plus an icon. The app should read like a video tool, not a dashboard: the
first thing on every page is what is happening and what to do next.

## 1. Principles

1. **One sentence, one next step.** Every page opens with its state in plain words and at most one orange button.
2. **Three kinds of things, never mixed up.** A *source video* (your long video, in the Library), a *clip* (a
   9:16 video made from it), and a *post* (one clip on one platform at one time). Each page says which kind it is
   with a small label ("Source video", "Clip", "YouTube post").
3. **Truth over reassurance.** Green only for a confirmed good state. Unknown is gray and says "Unknown" or "last
   known". No percentage or countdown unless the backend reports one; scores are labeled estimates; missing
   platform numbers are "—" with the reason.
4. **Problems come with their fix.** Every problem shows what happened, what to do, and a button when one exists.
5. **Nothing technical on the main path.** Workers, jobs, feeds, quota and diagnostics live in secondary views,
   which are one click away and never removed.
6. **Consequences before commitment.** Approve, publish now, stop all, delete and automatic publishing each say
   exactly what will happen before you confirm.

## 2. Tokens (`prototype/tokens.css`)

### Color

| Token | Value | Use | Contrast |
| --- | --- | --- | --- |
| `--canvas` | #101214 | page background | |
| `--surface` | #191C20 | panels, cards | |
| `--raised` | #22262C | menus, dialogs, save bars, selected nav | |
| `--hover` | #2A2F36 | hover fill | |
| `--border` | #343941 | separators only (1.47:1: decorative) | |
| `--control-border` | #737B87 | inputs, switches, secondary buttons | 4.0:1 on surface, 4.4:1 on canvas |
| `--text` | #F3F4F6 | body text | 15.5:1 on surface |
| `--text-2` | #BBC2CC | supporting text | 9.5:1 on surface, 8.5:1 on raised |
| `--text-3` | #9AA3AE | timestamps, captions, labels | 6.7:1 on surface, 6.0:1 on raised |
| `--primary` | #FF9C64 | the one action, active nav icon, links | 8.3:1 on surface |
| `--on-primary` | #201008 | text on primary buttons | 9.0:1 on primary |
| `--focus` | #FFB088 | 2 px focus ring, offset 2 px | 9.6:1 on surface |
| `--good` / tint | #5BD39A / #16261E | confirmed good | 9.1:1 on surface, 8.4:1 on tint |
| `--warn` / tint | #F2C055 / #2A2415 | waiting for you, degraded | 10.1:1, 9.1:1 |
| `--bad` / tint | #FF8A80 / #2E1C1C | failed, blocked, refused | 7.5:1, 7.1:1 |
| `--info` / tint | #7DB7FF / #18222F | working, informational | 8.2:1, 7.7:1 |
| `--neutral` / tint | #BBC2CC / #22262C | unknown, off, canceled | 8.5:1 |
| `--demo` / tint | #C9B6FF / #211C2E | prototype chrome only (never shipped) | 9.2:1 |

The logo keeps its orange-to-pink gradient; nothing else uses gradients. Surfaces are flat; the one shadow token
(`--shadow-overlay`) is only for dialogs, menus, the drawer, toasts and sticky save bars.

### Type, spacing, shape

* **Font:** `"Segoe UI", system-ui, …` (the Windows system font; no web font download). Monospace:
  `"Cascadia Mono", Consolas, …` for paths and codes.
* **Scale:** page title 30 px (`--fs-title`, 1.875rem; 26 px under 520 px), section 20 px, card title 17 px, body
  16 px, supporting 14 px, timestamps 13 px. Line height 1.5. Sentence case everywhere; no all-caps buttons.
* **Spacing:** 4 / 8 / 12 / 16 / 24 / 32 / 48 (`--s1` … `--s7`).
* **Radius:** panels 12 px, controls 8 px, pills fully round.
* **Sizes:** controls and nav rows at least 44 px high (small buttons 40 px, with 44 px spacing between them);
  sidebar 232 px; content max 1200 px (880 px for forms such as Settings, Setup and Add video).

## 3. Components

| Component | Rules |
| --- | --- |
| **Shell** | Sidebar with Home, Autopilot (shows On / Paused / Stopped / Off / Unknown), Library, Posts (count waiting for review, or problems), a gap, then Settings. Below 1024 px: a top bar with a labeled **Menu** button that opens a drawer (a dialog with focus trap and Escape), the logo, and the Autopilot state. A skip link comes first. |
| **Page head** | Kind label (optional), H1, one supporting line, and at most one secondary action on the right ("Add video" on Home and Library). Breadcrumbs above the head on nested pages. |
| **Lead card** | Home only: a status pill, one sentence (22 px), detail, steps or a fix, and one primary button. A colored left edge gives the tone. "Also needs you (n)" lists the rest with one small action each. |
| **Status pill** | Icon plus word, always both. Tones: good, warn, bad, info, neutral. With a lost connection, "good" pills render neutral. |
| **Fact** | Label, value with icon and tone, and a one-line description. Used for the Autopilot state strip. |
| **Need row** | Icon, title, detail, optional numbered steps and a "What to do" line; actions on the right (below on narrow screens). Only the first row's action is orange. |
| **Buttons** | Primary (orange, one per view), secondary (outlined), quiet (text), danger (red outline, always opens a confirm dialog). Destructive and rare actions go in a labeled "More" menu (`⋯` with an accessible name such as "More for Morning Mic episode 12"). |
| **Thumbnail** | Source video 16:9 with its duration; clip 9:16 with its duration; a missing thumbnail shows a film icon and "No preview yet"; a busy item overlays its real stage. |
| **Player** | 9:16, up to 560 px high, with a version badge ("Version 2" or "Source") and a caption preview. |
| **Timeline** | Waveform, selected range, playhead, start and end sliders (with typed values in Trim), and a clickable word strip. It scrolls inside its own region. |
| **Save bar** | Sticky at the bottom of the editor, Settings and post review. It shows the exact state ("Unsaved changes: Trim, Captions", "Saved, not rendered yet. The video is still version 2.", "Rendering version 3… 45%") and the actions. |
| **Dialog** | Title, consequences, then actions: Cancel on the left, the action on the right. Focus moves in, Tab is trapped, Escape closes, and focus returns to the opener. Never `alert`/`confirm`. |
| **Menu** | Opens under its button; Escape closes it and returns focus. Disabled items say why ("Cancel processing first"). |
| **Tabs** | Page sections are links (they change the address and support Back); editor groups are ARIA tabs with arrow keys. |
| **Toast and live region** | One polite live region. It announces actions and finished work ("3 clips are ready"), never polling ticks. Progress bars carry `aria-valuenow` but aren't announced. |
| **Banners** | Connection lost (warn), all jobs stopped (bad), an unknown address (info). |
| **Empty and loading** | An empty state says why it is empty and offers the next step. Loading uses flat skeleton blocks, with no spinner on a blank page. |

## 4. Navigation and objects

* **Home** summarizes: the one next step, then recent videos and clips and the next few posts. It links to
  Autopilot and Posts instead of repeating them. No stats, specs or charts.
* **Autopilot** is the control room: the switch, the truthful state, what needs you, the current work, your videos
  folder, upcoming posts and how posts go out. The Activity, Permissions & sources and Advanced views (System, Jobs,
  Learning) sit one tab away.
* **Library** holds source videos. A source video page holds its clips. A clip has an editor and a "Prepare post"
  page (manual posting).
* **Posts** holds every planned and published post (a post is one platform), with review, schedule, problems and
  results.
* **Add video** is an action ("+ Add video" on Home and Library, and in the Library's empty state), not a
  destination. Its page still has an address (`#/create`), so links keep working.

The route and feature map is in [ROUTE_MAP.md](ROUTE_MAP.md).

## 5. Screens

**Home.** H1 "Home" with "Autopilot: On · Looking for videos it may use" under it. The lead card shows the first
needs_you item in backend order: account > sleep and GPU > rights > file > approve > publish > needs videos. That
matches the brief's order (blocking problem > review > missing content). If nothing needs you, it shows current work,
then "All caught up" with the newest clips. First use shows Welcome with "Get started" (setup) and "Add a video now".
Below: *Recent videos and clips* (source thumbnail, status, origin, time, and a strip of clip thumbnails that open
the editor) and *Coming up* (4 posts: time, title, platform, exact status; the time zone is stated once).

**Autopilot.**
1. A status panel: "Autopilot is on" or "Autopilot is on, but 3 problems need you", the current label, and
   Pause or Start. Then four facts:
   * **This PC:** the five PR #6 states. On is "Kept awake" (Windows agreed). Pending is "Asking Windows" (not
     confirmed). Failed is "Windows said no", and the remedy is in Needs you. Off means the setting is off.
     Unsupported says to turn off sleep in the power settings.
   * **Processing:** "GPU · RTX 3050"; "GPU found, transcription not working" (Autopilot pauses); "CPU (slower) for
     the last video" with the reason; or no NVIDIA GPU. It never shows the CPU as GPU.
   * **Next online search:** a time only when `next_look` exists.
   * **Your videos folder:** checked every 3 minutes. The folder check is separate from online search.

   Then the line "Keep this PC on and leave the black ClipFoundry window open."
2. **Needs you (n):** every pending item, each with its fix and action.
3. **Working on:** the source thumbnail, the current step, and a progress bar only when the job reports progress
   ("46% of this step, as the job reports it. No time estimate is available."). A waiting reason replaces progress.
   **Your videos:** Open videos folder, count, watched or not, and the location behind "Show folder location".
4. **Coming up** plus **How posts go out:** YouTube waits for your OK or posts by itself under the permission;
   TikTok needs your OK on each post; connecting an account is never permission.
5. **Pause or stop everything:** the difference between Pause (keeps the queue) and Stop all jobs (the emergency
   stop, which cancels the queue and needs Resume jobs). Stop all opens a confirm dialog; "stopped" shows a red
   banner with Resume jobs.

**Autopilot secondary views.** *Activity:* found opportunities (the score is labeled an estimate), and every video
with what happened and why it was skipped ("Add the file…" when a file would help). *Permissions & sources:* creator
agreements (record and remove, with evidence and conditions), sources with on/off switches, permission rules, and
found videos with their permission status and Source Score (estimate). *Advanced:* System (12 workers, GPU details
including memory and holder, API quota, events, and the scan and trend controls), Jobs (filter, log, retry, cancel)
and Learning.

**First-time setup** (`#/setup/videos|mode|posting`). (1) Add your videos: choose one now, or use your videos folder.
(2) Choose how to work: manual or Autopilot; topics appear with Autopilot (default: podcasts, interviews, comedy).
(3) Set up posting when ready: connect YouTube or TikTok, or skip. This step states that connecting doesn't allow
posting, that YouTube automatic posting is a separate permission, and that TikTok always asks. Finish either starts
Autopilot or goes Home.

**Add video.** A large drop area with "Choose a video" and "Use a sample video". Formats are MP4, MOV, MKV, WEBM and
M4V (the current `ACCEPT` list). "Import from a link instead" is a quieter disclosure with the real restrictions
(rights, yt-dlp, no DRM, paywalls or logins). "More options" holds clips, length, caption style, framing, silence
cleanup, auto-zoom, the hook, and an optional transcript. Copying shows real upload progress, then the video's page
opens with the real stages.

**Library.** Cards with thumbnail, title (2 lines), status pill, origin and time, and a "More" menu (cancel
processing; delete, disabled while processing and saying why). A name filter and All / Working / Ready / Problems
chips filter the loaded list on the page; the backend adds no search. Empty: "Your library is empty" with Add video
and Open videos folder.

**Source video page.** It is labeled "Source video" and shows the video's details. While processing, it shows the
5 real stages, real progress and Cancel. An error shows its fix with Try again. When done, it reports "5 of 11
moments passed the quality bar", with "How clips are ranked" behind a disclosure. Then **Clips made from it**:
select, Download selected or all (ZIP), and clip cards (9:16 thumbnail, title, Viral Potential labeled an estimate,
category, source time, the clip's posts) with **Edit clip**, **Export** and **Prepare post**. "Make clips again"
(which warns that edits are discarded) and Delete live in the More menu. Zero clips shows why and how to get
weaker ones.

**Clip editor.** The preview (rendered clip with its version, or the source range before rendering) with Play, and
the timeline below it. Grouped controls sit beside it (stacked under 1100 px), in tabs: **Trim** (typed times and
length), **Captions** (on/off, style, position, size, key words, per-word highlight, caption text, and the
on-screen hook: choice, on/off, seconds), **Layout** (tracking, fill or fit, zoom, auto-zoom), **Audio** (volume,
loudness normalization, silence cleanup, filler words, pacing) and **Post text** (title, caption, "Write new
suggestions"). **Versions** sit under the timeline: create, compare, and choose the one used for export and posts.
The save bar reads, for example, "Unsaved changes: Trim". Discard, Save, and Save and render are separate. Saving
doesn't render. Rendering makes a new file, which gets a new final check, and approved posts of that clip need a new
OK. Leaving with unsaved edits, by any link or by browser Back, asks "Leave without saving?" (Stay / Discard and
leave / Save and leave), plus the browser's own prompt on reload or close.

**Prepare post** (`#/publish/:clip`). This is manual posting now. It shows the preview and posting version, the
posts this clip already has (links), and the shared post text with suggestions. The YouTube panel has privacy, the
audit restriction, the required "made for kids" answer, and optional #Shorts. The TikTok panel has creator, direct
or inbox, privacy from creator info with the audit restriction, comment/duet/stitch, commercial disclosure, the
music confirmation, and a manual-upload fallback. "Publish to YouTube now…" and "Post to TikTok now…" open a
confirmation that states account, visibility, timing and that the upload can't be taken back. Uploads started here
are listed at the bottom.

**Posts.** Link tabs: **Needs review** (count), **Scheduled**, **Published** (with a switch for canceled and
replaced, which is the old History), **Problems** (count; grouped as Upload not confirmed, Failed, Blocked, and
Finish in the TikTok app) and **Results**. Rows show a 9:16 thumbnail, the title, platform and account, the local
time with zone, the exact status pill, the status note, and for review the rights and final-check summary. Each row
has one button (Review / Resolve / See what to do / See why / Link the post / Open) and a More menu (change text or
time, open the clip, open on the platform, cancel). There's no bulk approval and no calendar. **Results** shows real
totals ("from 1 of 2 posts", "—" when not reported), a table per post with "—" and the reason on hover or focus,
Viral Potential at posting (labeled an estimate), Refresh numbers, and the CSV download.

**Post review** (`#/post/:id`). The exact file (its version) plays on the left. On the right:
* **Status**, depending on the post: approved (by you, or automatically "because every check passed. You did not
  review it"); Upload not confirmed with "It's on YouTube: add its link…" and "It's not there: upload again…" (the
  second warns about double posting); failed with its fix and Try again; blocked by the final check with Open the
  clip; finish in the TikTok app with a link field.
* **Before it can go out:** the account, permission to use, the final check (with all 14 checks of this file behind a
  disclosure).
* **Text and visibility:** suggestions from the clip's words, title, description and tags, who can see it, the
  public-at-time explanation, the audit restriction, and made for kids. TikTok shows its own fields.

A sticky **Your OK for YouTube** bar spells out what approving does, has the "I watched this video and read its
text" checkbox, and **Approve for YouTube**; while the button is unavailable, the bar says exactly what's missing.
**Publish now** appears only on an approved post, as its own confirmed step. Cancel this post and Change the time
are also here.

**Settings.** Link tabs:
* **Accounts:** per platform, the status and Connect, Reconnect or Disconnect. The app codes sit behind a disclosure,
  with the secret shown as "•••••••• (saved)" and a Replace button. Also here: the redirect address with Copy, the
  permissions, the audit checkbox, how to get the codes, and automatic publishing (YouTube) or per-post OK (TikTok).
* **Defaults:** new-clip defaults, the daily target, posting hours and topics.
* **Advanced:** transcription and GPU (model, device, CPU fallback in Autopilot, free VRAM), Autopilot details
  (time zone with validation, keep awake, limits, replacement, worker process), discovery and rights (API key masked,
  cost limit, automatic permission types), and rendering, AI scoring and system info. All current fields stay.

A sticky save bar with Discard and Save sits at the bottom, and a field error blocks saving and points at the field.
Account and GPU problems also show as banners on the other Settings tabs, and in Home and Autopilot through Needs you.

## 6. States covered (switch them with Prototype controls)

| State | Where |
| --- | --- |
| First use | Scenario "First use": Welcome on Home, setup flow, empty Library and Posts, "Autopilot is not set up" |
| Loading | "Show loading state" (skeletons) |
| Empty library | Scenario "First use" or "Autopilot on, no usable videos" |
| Video copying / processing / ready | Add video → Use a sample video → Make clips (copy %, then 5 stages, then 3 clips) |
| Ready clips / no clip passed | Scenario "Clips ready" (the Saturday Q&A video has no clips, and the page explains why) |
| Autopilot running / paused / stopped | Autopilot control (On, Paused, Stopped) |
| No usable content | Scenario "Autopilot on, no usable videos": "Autopilot needs videos to work with" |
| Sleep on / pending / refused / off / unsupported | "This PC's sleep" control; the refusal shows the Windows steps |
| Worker or GPU problems | Scenario "Problems" or the Processing control (GPU broken, CPU fallback, no GPU); a failed job in Advanced → Jobs |
| Posts awaiting approval / auto-approved / scheduled / published | Posts tabs in "Clips ready" |
| Failed / blocked / upload unknown / finish in app | Posts → Problems in "Problems" |
| Approval invalidated by a new render | Editor → Save and render on the first clip, then Posts shows "Needs a new OK: the video changed" |
| Missing or revoked account | YouTube account control, or scenario "Problems" |
| Stale or offline status | "Connection to ClipFoundry: Not answering": a banner, "Unknown" states, no green |
| Long names, missing thumbnails | The two checkboxes |
| Unavailable metrics | Posts → Results (YouTube shares and all TikTok numbers are "—" with reasons) |
| Unknown address | Any unknown `#/…` shows Home with a note |

## 7. Accessibility

* **Contrast:** see the table (every text and status color is ≥ 5.9:1; controls are 4.0:1). axe-core found no WCAG
  2.1 A/AA violation on 17 screens × 2 scenarios.
* **Never color alone:** every status is an icon plus a word; the Autopilot dot always has a sentence beside it.
* **Keyboard:** the skip link comes first; the focus ring is visible (2 px, `--focus`); dialogs and the drawer trap
  focus, close on Escape and return focus; menus close on Escape; the editor tabs use arrow keys, Home and End. After
  navigating, focus moves to the page title (H1) and the tab title updates.
* **Names and structure:** one H1 per page and H2 sections; the icon-only buttons have names; switches are
  `role="switch"` with `aria-checked`; segmented controls are radio groups; progress bars have values.
* **Announcements:** one polite live region for results of actions, never for polling.
* **Motion and zoom:** `prefers-reduced-motion` turns off the pulse and transitions. Layouts reflow at 768 and 390 px
  without sideways scrolling, which also covers 200% zoom on a 1440 px screen.
* **Targets:** 44 px, with 40 px small buttons spaced apart.

## 8. Copy rules

Plain sentences for a non-developer, in sentence case, saying what to do next. The words are video, clip, post,
your videos folder, "needs your OK", and "Upload not confirmed". Never worker, job, feed, provider, quota or lease on
the main path; those words stay in Advanced. Each item names its platform. Times are local, and the zone is stated
once per list. Estimates say "estimate". Buttons are verbs. A danger button names what it deletes ("Delete video
and 5 clips"), and its dialog says what is not affected ("Posts already on YouTube or TikTok stay there").

## 9. What exists today and what would be new

| Shown in the prototype | Backing today | Needed |
| --- | --- | --- |
| Home lead, Needs you, sleep, GPU, your videos, upcoming | `home.*` (PR #6), `status.gpu` | Nothing new. Home reads the Autopilot status that the Autopilot page already polls. |
| Autopilot current work: thumbnail and step list | `home.currently` (a label); `Job.progress`, `stage`, `ref_type`, `ref_id`; `Project.has_thumbnail` | **Small addition:** expose the running job (or its project) in `home`, so the page can show the thumbnail, the steps and the job's own progress. Without it, show only the label, which is what the prototype does when progress is missing. |
| "Next online search" vs "folder checked every 3 minutes" | `home.next_look`; `feed_scan` runs every 180 s | The folder interval is a constant (a frontend string, or exposed if it becomes a setting). |
| Library name filter and status chips | `/api/projects` | Frontend only. |
| A clip's posts (clip cards, Prepare post) | `ScheduledItemRow.clip_id` | Frontend join over `/api/autopilot/scheduled`, or a `clip_id` filter on that endpoint. |
| Editor unsaved-change guard, version badge, "saved, not rendered" | `Clip.version`, `edit` | Frontend only. |
| "Needs a new OK: the video changed" | The approval is bound to `approval.hash` (APPROVAL_SCHEME 2) | **Check** how the API reports an invalidated approval (a `status_note`, or back to awaiting_approval) and show that exact wording. |
| Posts views and groups | `VIEWS` in `autopilot/routes.py` | Frontend grouping. The "Scheduled" tab covers approved, publishing and uploaded-with-a-publish-time. |
| Results | `performance`, publication stats | Moves from the Dashboard; no new data. |
| Connection lost banner | `usePoll` errors | Frontend only (track the last successful update time). |
| Setup flow | `setup.started`, `start`, accounts | Frontend only. The "manual" choice is not stored today; store it in a setting or infer it from Autopilot being off. |
| Everything in Advanced, Sources, Jobs, Learning, Settings | Existing | Moved or regrouped only. |

Nothing in the prototype needs a new backend capability beyond the one small `home` addition. The
invalidated-approval wording must be checked against the API before phase 4.

## 10. Tradeoffs

* **Four destinations instead of six** means Create is no longer in the sidebar. It is a button on Home and Library,
  and in the Library's empty state. A user who wants to "make clips" starts from "Add video". That is one extra
  click from Autopilot or Posts, in exchange for a sidebar without a duplicated action.
* **Home no longer shows stats or specs.** Performance moves to Posts → Results, and the GPU moves to Autopilot and
  Settings. Anyone who opened the Dashboard for numbers now has to go one page further.
* **Posts replaces Publish Center.** The name matches the object. The e2e tests and the owner's habit ("Publish
  Center") have to change, so the old addresses redirect.
* **Manual posting stays a separate page** ("Prepare post"), rather than merging into post review. The two flows
  have different rules (now vs. scheduled, manual choices vs. Autopilot packaging), and merging them would blur the
  approval guarantees.
* **Versions move next to the editor.** Choosing the posting version now lives where the video is made. Prepare post
  shows which version it will post.
* **The dark theme only.** The current app is dark, and the owner works in it. A light theme is possible later
  because everything is tokenized.
* **The system font.** It keeps the app offline and fast. On Linux or macOS the prototype falls back to the local UI
  font, so the screenshots are not a pixel-exact preview of Windows.
* **The sticky save and approve bars** cost some vertical space on small laptops. In return, the state and the next
  action stay visible without scrolling. On phones they stop being sticky.

## 11. How the prototype was checked

* **Every route:** 41 addresses × 5 scenarios × 4 sizes (1440×900, 1366×768, 768×1024, 390×844). No sideways page
  scrolling, no script errors, no "undefined" or "NaN" in the text, an H1 on every page, and no network requests.
* **Interaction** (46 checks, all passing):
  * the path Add video → copying → processing → clips → Edit clip → the unsaved-changes guard (link and browser
    Back) → Save and render → Prepare post;
  * approval blocked until complete; the approval reopened by a new render;
  * the 8 old-address aliases, Back behavior, and aliases not trapping Back;
  * the skip link, the focus ring, dialog focus trap, Escape and focus return, the menu, the drawer, and the editor
    tab arrow keys;
  * the lost connection showing no green;
  * axe-core.
* **Not checked:** Windows rendering (Segoe UI and the real DPI), a screen reader, touch devices, and the prototype
  inside the claude.ai artifact frame beyond one preview.
