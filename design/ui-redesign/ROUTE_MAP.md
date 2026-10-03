# Route and feature map

The redesign keeps every address that works today. IDs in addresses don't change. Old addresses that change are
**aliases**: they are replaced in place (`history.replaceState`), so they open the new page, and Back doesn't bounce
on the alias. The prototype implements all of this (`prototype/app.js`, `ALIASES`), and the tests in SPEC.md §11
check it.

## Addresses

| Today | New | Kind |
| --- | --- | --- |
| `#/` Dashboard | `#/` **Home** | same address, new page |
| `#/create` Create | `#/create` **Add video** | same |
| `#/projects` Projects | `#/library` **Library** | alias `#/projects` → `#/library` |
| `#/project/:id` | `#/project/:id` **Source video** page | same |
| `#/clip/:id` | `#/clip/:id` **Edit clip** | same |
| `#/publish/:clipId` | `#/publish/:clipId` **Prepare post** | same |
| `#/autopilot` | `#/autopilot` **Autopilot** (overview) | same |
| — | `#/autopilot/activity` **Activity** | new |
| `#/autopilot/sources` | `#/autopilot/sources` **Permissions & sources** | same |
| `#/autopilot/system`, `/jobs`, `/learning` | same, under **Advanced** | same |
| `#/autopilot/overview` | `#/autopilot/system` | alias (as today) |
| `#/publish-center`, `/upcoming` | `#/posts/review` **Needs review** | alias |
| — | `#/posts/scheduled` **Scheduled** | new |
| `#/publish-center/published` | `#/posts/published` | alias |
| `#/publish-center/history` | `#/posts/history` (Published, including canceled and replaced) | alias |
| `#/publish-center/problems` | `#/posts/problems` | alias |
| `#/publish-center/<anything else>` | `#/posts/review` | alias |
| — | `#/posts/results` **Results** | new |
| — | `#/post/:scheduledId` **Post review** | new (today this is a dialog) |
| — | `#/setup`, `/videos`, `/mode`, `/posting` **First-time setup** | new (today it's the Autopilot first-run screen) |
| `#/settings` (General) | `#/settings` **Accounts** | same address |
| — | `#/settings/defaults` **Defaults** | new |
| `#/settings/advanced` | `#/settings/advanced` | same |
| anything unknown | `#/` Home, with a note that the address doesn't exist | as today, plus the note |

## Features: where each one goes

| Capability today | New place |
| --- | --- |
| Dashboard hero and pipeline chips | Removed (marketing) |
| Dashboard stat cards (clips, projects, "$0 runtime cost") | Removed. The counts show in context (Library chips, Posts tab counts). |
| Dashboard System panel (FFmpeg, GPU, Whisper) | Autopilot → This PC and Processing facts; Autopilot → Advanced → System; Settings → Advanced |
| Dashboard Performance card | Posts → Results |
| Dashboard recent projects | Home → Recent videos and clips |
| Sidebar "Create clips" button | "+ Add video" on Home and Library, and in the Library's empty state |
| Autopilot first run (connect, topics, start) | `#/setup` (3 steps); Autopilot shows "Set up Autopilot" until then |
| Autopilot Home: status, Start/Pause | Autopilot overview status panel |
| STOP ALL JOBS / Resume | Autopilot → "Pause or stop everything" section, and the stopped banner |
| Needs you | Home lead card (first item) plus Autopilot → Needs you (all items) |
| PC note (black window) and keep-awake states (PR #6) | Autopilot → This PC fact, and the note under the facts |
| Your videos folder (PR #6) | Autopilot → Your videos; Setup step 1; Library empty state |
| Upcoming posts | Home → Coming up (4), Autopilot → Coming up (5), Posts → Scheduled (all) |
| Automatic publishing line and dialog | Autopilot → How posts go out; Settings → Accounts → YouTube |
| Activity log and skipped videos | Autopilot → Activity |
| Opportunities and trend list | Autopilot → Activity (found) and Advanced → System (trends, providers, Scan now) |
| Sources, rights rules, feeds, agreements, rights dialogs | Autopilot → Permissions & sources |
| Workers, GPU card, quota, events, action items | Autopilot → Advanced → System |
| Jobs (logs, retry, cancel) | Autopilot → Advanced → Jobs |
| Learning | Autopilot → Advanced → Learning |
| Add content dialog | Autopilot → Permissions & sources → "Add…" |
| Create: upload, URL import, options, transcript | Add video (URL import and options behind disclosures) |
| Projects grid, delete | Library (plus the name filter and status chips); delete in the card's More menu |
| Project view: progress, cancel, error | Source video page |
| Project view: clip cards, preview, select, ZIP | Source video page → Clips made from it |
| Regenerate dialog | Source video page → More → "Make clips again…" |
| Clip editor tabs (trim, framing, captions, hook, audio, post) | Editor groups Trim, Captions (with the hook), Layout, Audio, Post text |
| Versions card (on Publish today) | Editor → Versions (under the timeline); Prepare post shows the posting version |
| Publish page (manual YouTube and TikTok) | Prepare post (same controls, plus "Posts of this clip") |
| Publication rows and stats | Prepare post → Uploads you started here; Posts → Results |
| Publish Center views, EditDialog, ApproveDialog | Posts tabs; Post review page (text, time, approve, publish now, cancel, resolve, link) |
| Settings General (accounts, Autopilot basics) | Settings → Accounts; Settings → Defaults |
| Settings Advanced (everything else) | Settings → Advanced (unchanged fields; accounts no longer repeated) |
| Terms and Privacy links | Sidebar footer |
