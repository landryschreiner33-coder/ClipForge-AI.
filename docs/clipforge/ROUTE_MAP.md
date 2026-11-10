# ClipForge route map

The app keeps its hash router (`frontend/src/router.ts`). Old addresses are rewritten in place with
`history.replaceState`, so bookmarks, notifications and Back keep working and never bounce. Deep links survive
sign-in: the sign-in page returns to the address that was requested.

## Logical screens

| Screen | Address | Replaces / aliases | Contents |
| --- | --- | --- | --- |
| Sign in (cloud only) | shown in place of any address while signed out | — | ClipForge name and robot icon, Continue with Google, error and retry. No project data is requested before sign-in. |
| Studio | `#/` | `#/home`, `#/studio` | Home and the Office together: Make clips, Make a YouTube video, a video-link action, Needs you (only when actionable), the current project (real step, measured progress, its robots, next action), the office (map or list, expandable), recent projects and publishing status. Empty state: "Ready for your next video". |
| Make clips | `#/create/clips` | `#/create` (old Add video) | Highlights / Full stories selector, file or link, saved style, destinations, Make clips / Make & upload clips. |
| Add from a link | `#/create/link` | — | The earlier Add video page: a public link, or a file with its own transcript; linked from Make clips. |
| Make a YouTube video | `#/create/video` (`?idea=…` fills the idea) | — | Your files (drop or Add from this computer) beside Your idea: the idea in your own words, Ask me questions or Just do it (remembered), More choices (style, example, Remember this style, script, name). Starts a draft (docs/clipforge/VIDEO_SETUP.md). |
| Planning a video | `#/create/video/:id` | — | A draft video: the conversation with ClipForge AI (quick answers, Just do it, Stop), the plan (read as a slate, Change it by hand), your files with what was heard, More choices, Build my video. A built video's address opens its review page. |
| Make an animated short | `#/create/short` | — | Paste my script or Write it for me (topic, tone, length), look, voice with Hear it, speed, music, captions, camera moves or animated pictures, what makes it (picture maker, voice, word timing), Make the short. Opens the short in Full-video review with its Scenes panel. |
| Source project review | `#/project/:id` | (unchanged) | Large preview, outputs (highlights or story cards), transcript, Used from your Brain, downloads, publishing. |
| Full-video review | `#/video/:id` | — | Preview, outline, sequence (trim/reorder/include), Your plan (Change the plan edits again as a new version), Used from your Brain, versions, render, download, publish. An animated short adds its Scenes panel first (words, picture, camera move, add and delete scenes, voice, look and music). A draft's address opens its planning page. |
| Projects | `#/projects` | `#/clips`, `#/library`, `#/projects/*` | One library with All / Clips / Full videos / Animated shorts filters, search, status badges, thumbnails. |
| Test feedback | `#/projects/feedback` | `#/clips/feedback` | Existing feedback page. |
| Edit clip | `#/clip/:id` | (unchanged) | Existing clip editor. |
| Prepare post | `#/publish/:id` | (unchanged) | Existing publish screen, now with an explicit account selector. |
| Brain | `#/brain`, `#/brain/{styles,notes,examples,skills,graph,...}` | existing Brain tabs | Styles, Notes, Examples, Skills; Graph is an optional view. |
| Publishing | `#/publishing/{review,scheduled,published,history,problems,results}` | `#/queue/*`, `#/posts/*`, `#/publish-center/*` | Queue/calendar with per-destination rows, exact account names and an account filter. |
| Post review | `#/post/:id` | (unchanged) | Existing post page. |
| Accounts | `#/accounts` | `#/settings/accounts` | Add YouTube account, Add TikTok account, connection cards, Reconnect, Disconnect. |
| Office (expanded) | `#/office` | `#/studio/office`, `#/office/*` | The Studio's office at full size: rooms that follow the workflow, real robot states, details panel, controls. |
| Team | `#/office/team` | `#/studio/team` | Robot list with Rename / Reset name. |
| Autopilot | `#/missions/*` | `#/autopilot/*` | Existing Missions pages, reached from the Studio and the top-bar Autopilot status. |
| Settings | `#/settings`, `#/settings/{appearance,defaults,integrations,storage,advanced}` | existing Settings tabs | Appearance and layouts, default style, storage/retention, advanced. |
| Setup | `#/setup/*` | (unchanged) | Existing first-run steps. |
| Robot gallery | `#/dev/robots` | (unchanged) | Development view. |

## Navigation

Desktop (≥ 1024 px): a 232 px collapsible sidebar with Studio, Projects, Brain, Publishing, Accounts and
Settings (the studio upgrade merged Home and Office into Studio), plus a 64 px top bar with the page title, the Make menu, Customize studio, the Autopilot status and (in cloud mode) the
signed-in owner and Sign out. Below 1024 px the sidebar becomes a drawer opened from the top bar. A persistent
"Make" button stays in the top bar on every size, so the main task is always one tap away.

## Backend routes added in this build

| Area | Routes |
| --- | --- |
| Sign-in | `GET /api/auth/me`, `GET /api/auth/login`, `GET /api/auth/callback`, `POST /api/auth/logout`, `POST /api/auth/logout-all` |
| Uploads and assets | `POST /api/uploads`, `GET/PUT /api/uploads/{id}`, `POST /api/uploads/{id}/complete`, `GET /api/assets/{id}`, `GET /api/assets/{id}/media`, `GET /api/assets/{id}/thumbnail` |
| Studio projects | `POST /api/studio/clips`, `POST /api/studio/videos` (with `script`), `GET /api/studio/projects`, `GET/PATCH /api/studio/videos/{id}`, `POST /api/studio/videos/{id}/{build,edits,render,cancel,smart}`, `PUT /api/studio/videos/{id}/script`, `POST /api/studio/scripts/parse`, `GET /api/studio/videos/{id}/media` |
| Planning a video | `POST /api/studio/videos/setup`, `GET/PATCH /api/studio/videos/{id}/setup`, `POST /api/studio/videos/{id}/setup/{say,stop,build}`, `PUT /api/studio/videos/{id}/plan`, `GET /api/studio/video-setup/model` |
| Animated shorts | `GET /api/studio/shorts/options`, `POST /api/studio/shorts`, `POST /api/studio/shorts/voice-sample`, `POST /api/studio/shorts/{id}/scenes`, `PATCH/DELETE /api/studio/shorts/{id}/scenes/{scene_id}`, `POST /api/studio/shorts/{id}/make`, `PUT /api/studio/shorts/{id}/options`, `GET /api/studio/projects?kind=short` |
| Big footage (desktop) | `GET /api/local/browse`, `POST /api/uploads/link`, `POST/GET /api/assets/{id}/prepare` |
| Full stories | `GET /api/projects/{id}/stories`, `PATCH /api/stories/{id}`, `POST /api/projects/{id}/stories/{split,merge,create}` |
| Styles and skills | `/api/studio/styles…`, `/api/studio/skills…` (import, preview, enable, export, delete) |
| Connections | `GET /api/connections`, `POST /api/connections/{platform}/add`, `POST /api/connections/{id}/reconnect`, `POST /api/connections/{id}/disconnect`, `PATCH /api/connections/{id}` |
| Preferences | `GET/PUT /api/preferences/appearance`, `GET/PUT /api/preferences/layout/{device}`, `GET/PUT/DELETE /api/robots/names/{role_id}` |
