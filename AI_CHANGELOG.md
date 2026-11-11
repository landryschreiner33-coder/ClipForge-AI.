# AI changelog

## Leftover files and upload races after deleting projects — 2026-11-11 (Claude Code)

Follow-ups from the delete-projects review (PR #35), passed on by the coordinator. Branch
`claude/project-thread-h05xs8`, built on #35 and merged with the release line at bc7250f. No release.

- **Animated shorts** (`clipfoundry/makers/shorts.py`): every file a build stores is listed for its short (new table
  `short_files`). At the start and end of each build, a listed file that no scene, earlier picture, saved version or
  other project names any more goes (`_tidy_files`, `_drop`, `_named`, one step under the file's lock); deleting the
  short reaches every file on its list. A file just handed out again (`assets.reused_at`, an hour) is left alone. A
  thrown-away clip that cannot be deleted yet never fails its scene (the next tidy has it).
- **Local makers** (`makers/local_engines.py`, `pictures.py`, `voice.py`, `engines/makers.py`): the short takes the
  maker's original and its note out of `data/engines/made` (`maker.json` / `maker.<ext>` beside the picture or clip,
  voices under the short's `voice/maker/`), so they go with what the short made from them. A result that cannot be
  used or was made as Stop was pressed is deleted with its note (`discard_made`, only ever inside engines/made); a
  file ComfyUI hands back that is not a picture, or an empty video, is deleted. The delete window says which
  originals go and which stay in engines/made (`project_delete._maker_originals`).
- **Uploads** (`studio/uploads.py`): saves of the same bytes take turns (`_content_lock`); two identical files
  finishing together are stored once and both finish (no HTTP 500, no stray folder; 409 "try again" only when the
  stored copy was deleted in between). `complete()` answers with `upload_id`; the same file finished on two pages
  (both resumed one upload) gives the second page an upload row of its own (`_again`).
- **"Added again"**: pages send the uploads they used (`upload_ids` on Make a YouTube video, Add files, the editor's
  media, Make clips, the classic video request, a scene's own picture, an example video), every upload they made of
  the file: also one picked again, one dropped again after a change failed, and one that finished after another file
  was picked instead (`FileDrop` reports every finished upload, `onUploaded`; `useUploadsByFile`).
  `uploads.taken(ws, upload_ids, project_id, asset_ids)` marks exactly those (new column `uploads.taken`). Add from
  this computer leaves such an upload too (`uploads._hand_out`, one step with marking the copy; the link answer has
  `upload_id`), so links count like uploads. When deleting, a project that took uploads counts every other finished
  upload of the file in the day as another page's ("again", kept), also one made before the project. So does every
  project made since ClipForge records this (`db._migrate_uploads_taken` notes when, `project_delete._marked_since`),
  also one made from a file ClipForge got another way (a link, Find media), which owns no upload; a project made
  before keeps the older rules. A project's own later upload or link of a file ClipForge already had no longer keeps
  that file forever; choosing an earlier picture again takes no upload. A scene's picture is changed once per upload
  (a failed change is tried again when the picture is dropped again, never by the page on its own). On a draft, a
  file taken out stays out (also when an upload of it that began before finishes later, or when it came from the
  first page and was dropped again), and a copy of it picked after it was taken out (another name) brings it back.
- **Deleting** (`studio/project_delete.py`): inside its own step (`BEGIN IMMEDIATE`), nothing else can change the
  database, so it looks again at what names each file and at copies handed out since the window (`_handed_out`); those
  stay, and the answer is worked out again ("… stays in ClipForge because it was used again just now"). A video's bin
  names a file only while it exists, and before the page's upload is taken (`video_flow.add_media`).
- **Deleting an example's video file** (`studio/reference._drop_file`): the file stays when anything else names it
  (saved versions, shorts, imports; the delete's own check), when it was handed out again since the example was made,
  or when another page's upload or link of it that no project or example took finished in the last day (also before
  the example); the Examples page's own uploads are the example's (`upload_ids` on `POST /api/studio/references`). A
  copy handed out again since the example was made counts only within the hour and until its upload is recorded
  (uploads a project took never keep it). The check and the delete are one step.
- **Planning chat** (`brain/chat.open_chat(create=False)`, `studio/video_setup._think`): an answer for a video deleted
  while it is written stops and never makes a new, empty chat; a chat made just as its video is deleted goes again.
- **Docs:** `docs/clipforge/ANIMATED_SHORTS.md` (tidying, the makers' originals, a scene's own picture),
  `LOCAL_ENGINES.md` (refused files are deleted), `VIDEO_SETUP.md` (`upload_ids`, the chat lookup), `LONG_VIDEOS.md`
  (a link's `upload_id`).
- **Tests:** `tests/test_studio_uploads_taken.py` (new), `test_studio_shorts_tidy.py` (new), and new cases in
  `test_studio_uploads.py`, `test_studio_shorts_voice.py`, `test_local_engines.py`, `test_video_setup_flow.py`,
  `test_studio_project_delete.py`, `test_studio_local_files.py`, `test_studio_reference.py`. Each fix has a test that
  fails on the code before it. Six independent reviews; every confirmed finding fixed.
- **Checked in the real app** (browser, fresh data folder): Make clips with the same file picked twice, Make a YouTube
  video with two copies of one file and a picture, Add files on the draft (a file it has already, and a new one), the
  delete window's words, and one big file dropped on two pages at once (each page got its own upload; deleting the
  first page's video kept the file and the second page started its video). Then: Add from this computer on Make a
  YouTube video (the link is the video's), Make clips with a file replaced while it uploaded and picked again (both
  uploads sent and taken), an example video (its upload is the example's; deleting it with its file kept the file
  another page had uploaded), Add from this computer in the editor, and a draft's file taken out and then added
  again as a copy under another name (it came back, and its upload is the video's), a draft's file dropped again and
  then taken out (it stayed out), and a file picked again whose slow upload finished after it was taken out (it
  stayed out).
- **Known limits (keeping is the safe side):** projects and examples made before this change took no uploads; such
  a project keeps the older rules, and such an example's file stays when it is deleted within a day of its upload.
  A project made since then by something other than a page (an API call, ClipForge AI's tools) from a file the owner
  uploaded keeps that file for a day after its upload if deleted, as the upload was not sent with it. An upload a
  page started and then removed from its list counts as another page's for a day. The owner's own files are never
  touched.

## Deleting projects, with a confirmation that says what goes and what stays — 2026-11-10 (Claude Code)

Landry asked to be able to delete projects. Branch `claude/project-thread-8i3krg` from the release line at 95a70e0.
No release.

- **One delete for both kinds** (`clipfoundry/studio/project_delete.py`, new): `plan(ws, id, kind)` says in plain
  sentences what goes and what stays without changing anything; `delete(ws, id, kind, wait=)` does it in one
  transaction and returns the same sentences. Kinds: `clips` (Highlights and Full stories) and `full_video`. Used by
  the Projects page, a clips project's own page and ClipForge AI's delete tool (the assistant thread).
- **What goes:** the clips with their versions, scores, blueprints, analyses and suggested post text, the transcript
  windows, story proposals and link imports; or a video's edit history (every revision), previews and finished videos,
  change requests, media searches and imports, and an animated short's scenes; the project's folder; an upload copy or
  downloaded link that nothing else uses (another clips project, an example, any other video or any of its saved
  revisions), and for a file used where it is only what ClipForge made from it; the project's ClipForge AI chat and the
  memories that apply to it only; planned posts that have not started uploading (canceled, they stay in the history);
  its place on the pinned list.
- **What stays:** the owner's own files (never deleted, never made writable); media something else uses (kept, still
  read-only); anything posted (post history, results, the fingerprints that stop a clip being posted twice); memories
  for every video, a platform or a mode; the taste lessons; Autopilot's record of the video it found (its link to the
  project is cleared, so the Autopilot page no longer opens a missing project and the entry can be removed).
- **Waits instead of deleting** (409, code `blocked`, with the reason): Autopilot still working on the project, its
  clips or its source; a post uploading or being checked; a video still being copied in (status `uploading` and the
  folder changed in the last minute; a copy that stopped halfway can be deleted). Running work (making clips, renders,
  studio jobs, link downloads, media imports, preparing a file that goes) is canceled first; a delete request waits up
  to 10 s for it, else 409 `stopping`, and the window asks again for up to 90 s.
- **Routes:** `GET /api/projects/{id}/delete-plan`, `GET /api/studio/videos/{id}/delete-plan`,
  `DELETE /api/studio/videos/{id}` (new); `DELETE /api/projects/{id}` now runs the same code (before, it refused while
  clips were being made and left the upload copy, the chat and the project's memories behind). Both DELETEs take the
  plan's `as_of` (`?as_of=`), which the window sends back.
- **Screens:** `frontend/src/components/DeleteProject.tsx` and `.css` (new): a trash button on every Projects card (top
  left, the Pin button's twin; `LibraryCard` takes an optional `onDelete`, so the Studio page's cards have none) and one
  confirmation window ("Deleted for good" and "Stays" from the server, "This can't be undone", focus starts on "Keep
  it"; while blocked only "Check again" and "Close"). A clips project's own page uses the same window
  (`libParts.tsx` `DeleteProjectDialog`). `frontend/dist` rebuilt.
- **After a second review (same day):** work that was asked to stop but is still running (its row already says
  canceled) counts as running, so a second delete never deletes from under it; a step that ends while a delete waits
  and queues the next step has that one stopped too; a planned post that starts uploading between the check and the
  cancel stops the delete (409 `blocked`) instead of being ignored; a post whose publish step is already running
  blocks; memories go by their scope only (a memory saved again for another project keeps its first project_id); a
  file the owner uploaded again after the project was made, within the last day, stays (ClipForge keeps one copy per
  file, and a new page may be about to use it; counted from the project's `created_at`, which deleting's own stop
  cannot move, and the upload that first stored the file is the project's own); a clips project's own copy of its
  video (a live recording, a download) is named in what goes; folders with a file still open in another program (Windows) are listed in `data/delete-later.json` and
  deleted at the next start (`finish_later`, only ClipForge's own project, video, link and upload folders), and the
  answer says so (`left_behind`); both DELETE routes only answer ClipForge's own page on this computer (the
  `app_request` guard the Autopilot and memory routes have, in words about deleting). Window: it cannot be closed
  while a delete is on its way, a refusal shows at once in an announced area, a project already deleted elsewhere
  just closes it, it works in development mode (StrictMode), focus moves to the next card, and the page no longer
  saves its own pinned list (the server already unpinned it; `forgetPin` in `prefs.tsx`). The e2e library test
  follows the new window.
- **After a third, independent look at those fixes:** a writable file that cannot be deleted is in use even when it
  has a second link (a render reused after undo or restore), so its folder is listed for the next start; the
  start-up sweep knows ClipForge's own read-only upload copies (a leftover link to a copy another project still uses
  is removed and the copy is read-only again, instead of the folder being dropped from the list with the link still
  in it); the space freed counts a reused render once; "added again" no longer flips to "goes" when the delete's
  own stop changes the project; while deleting, the buttons keep keyboard focus inside the window (aria-disabled)
  and after a refusal focus moves to Close; a failed pin save that is retried no longer pins a deleted project.
- **After the animated shorts and story clips joined the release line (2026-11-10):** an animated short's scene
  files (each scene's picture, its earlier pictures and the scene's clip, also one not in the plan yet) go with
  it when nothing else uses them; a file another short's scene names, or any media import (also one made for no
  project), counts as a use and stays; the window names a short's build ("making the short"); one upload of a
  file ClipForge got another way (Find media, a link) counts as added again; and a window that lists more than
  four files says "and 2 more", not "and 2 mores". Story parts projects are clips projects and need nothing new.
- **After a last independent look on the combined code (2026-11-10):** a short's scene pictures and clips are not
  copies of anything and every remake has the same name, so the window counts them on their own line ("What
  ClipForge made for its scenes: 3 pictures and 3 clips."); a picture the owner chose for a scene, uploads, downloads
  and ClipForge's library sounds keep "ClipForge's copy of …". When the makers on this computer made a short's
  pictures, video clips or voices, the window says under Stays that their originals stay in engines/made with a note
  of the words (the makers keep everything they make; deleting does not reach that folder). "Added again" is decided
  by when an upload started: only one that started after ClipForge had the file counts, so a slow save or the same
  file dropped twice at once no longer keeps a project's own file (this replaces a 5-second guess). The plan answers
  with `as_of`, the window sends it with Delete, and the delete judges "added again" at that moment, so a file the
  window said stays is not deleted because the window stayed open past the day. Passed on to the shorts and upload
  code (not this change): scene files that no scene or saved version names any more (a replaced clip, a deleted
  scene's files) stay after the short is deleted; the makers' originals could be removed with the short; two
  identical files finishing their upload at the same moment give an error and leave a stray copy.
- **After one more independent look at those fixes (same day):** a short's files are also read from every saved
  version (a deleted scene's picture is counted as made, not named as a copy); the owner's own photo stays "ClipForge's
  copy of …" while a new picture waits to replace it (who made a scene's picture is its info.picture.source); the
  makers' line also shows after the voice or motion was switched, a scene was deleted or a build was stopped (saved
  versions and the short's voice notes); and "added again" also keeps a file when another page's upload of it started
  before the project was made and finished after it (the same file under two names), or when the file was dropped
  twice in the day (the project was made from one drop at most). Passed on: a project's own later upload of a file
  ClipForge already had counts as added again, so that file is left behind (needs a record of which project took an
  upload); the same file dropped on two pages at the very same moment shares one upload, so it can still go.
- **With Make a YouTube video's planning (PR #38, merged in):** a video being planned is a full video with status
  `draft`; deleting it stops the reading of its files, removes its planning chat with an answer still being written,
  and that answer finishing afterwards makes no chat or message again (a test drives the setup page's own `start`).
- **Docs:** `docs/legal/privacy.html` says what deleting a project removes and keeps (its ClipForge AI chat and
  notes, the copy of a file added again); `docs/clipforge/ROUTE_MAP.md` lists the routes and the trash button.
- **Tests:** `tests/test_studio_project_delete.py` (27 tests). Fast suite 1,978 passed, 2 skipped (1,969 before);
  slow suite 27 passed, 1 skipped (espeak-ng installed); a click-through of the real app in a browser
  (deleting a video, an Autopilot project that has to wait, a clips project from its own page, phone width)
  passed 18 of 18 checks. After the review fixes, on the code merged with the release line at e3ad759 (story
  clips): every test, fast and slow together, 2,064 passed and 3 skipped (two model folders and opentimelineio are
  not on this machine); one timing test (`test_an_nvenc_encode_waits_while_the_gpu_is_transcribing`, which gives a
  render 2.5 s to reach the GPU wait) failed once under load and passes on its own (3 of 3) and with its file; it
  does not touch deleting. `pytest -m slow` on its own: 29 passed, 1 skipped. The click-through passed 30 of 30
  checks (now also: focus after deleting, no pinned-list save, the window held open while deleting with focus inside
  it, a refusal shown at once with focus on Close), the window loads in development mode, and the two e2e delete
  tests pass against a seeded app (a deletable and a waiting project). After the
  last review's fixes (41d54e8): every test, fast and slow together, 2,233 passed and 3 skipped; the click-through
  passed 31 of 31 (now also: Delete sends the moment the window was judged); the two e2e delete tests pass. With
  the safety follow-ups (#41) and Make a YouTube video's planning (#38) merged in (2e63fef): every test, fast and
  slow together, 2,392 passed and 4 skipped (the fourth is a video-setup test that waits for the assistant's chat
  routes, PR #37); the click-through passed 31 of 31 and the two e2e delete tests pass.
- **Not verified:** a real Windows PC (the read-only and in-use file handling is simulated in tests); Landry's Mac.
- **Known limit:** a file used where it is ("Add from this computer") that is added again for a new page that has
  not saved it yet is not protected the way an upload is (adding it again leaves no record). Only what ClipForge made
  from it goes, never the owner's file; the file may then need to be added again on that page.

## Make a YouTube video: review fixes — 2026-11-10 (Claude Code)

Two reviews of PR #38 (branch `claude/project-thread-2wwa4c`) found misreadings and rough edges; all fixed with a
test for each (each new test failed on the code before its fix). No release. Details:
[docs/clipforge/VIDEO_SETUP.md](docs/clipforge/VIDEO_SETUP.md).

- **The built-in rules** (`studio/video_setup.py`, the reading part rewritten in the second review): a no only when it
  says no to the thing ("I don't want captions", "skip the captions", "not a TikTok"; not "Grandma can't hear well
  and needs captions", "don't make the captions too big", "no music during the vows", "I hate when videos don't have
  captions"; "don't lose the captions" is a yes); keep and cut only when asked for, in everyday ways ("I'd like you
  to cut…", "can we cut…", "could we keep…"), turned round by "don't"/"never" and let go by "you don't have to"; the
  video's length, not the footage's, a part's or a cut's ("my footage is 2 hours, make it 15" is 15 minutes; "the
  intro should be about 30 seconds" is none), said in everyday ways ("10 minutes is good", "Length: 10 minutes", "not
  longer than 10 minutes"), the last one said winning; "as long as it needs" is its own choice (`NO_LENGTH` = -1),
  "as long as you like it" is not; editing off only for the whole video; shape words only about the video ("vertical
  works best", "make a reel"); titles as typed ("Let's call it Mom's 60th"), none from "call it a day"; stories
  whose steps are things that happen; a named sound takes the role its sentence gives it. A long odd message is read
  in well under a second (at most 16 words in front of a keep or cut are read).
- **Merging**: each answer reads every message since the last one an answer merged, so what a stopped message said
  counts with the next; with a model its reading wins and the rules fill what it did not use; a part said in a
  message merged before, or set by hand, changes only when a later message talks about it, compared per part with
  when the hand edit was made (`locked_at`); a quick answer talks about what its question asked (`data.about`);
  files put in order by hand hold that order against an answer written meanwhile. Without a model only those
  messages are read, so a kept or cut item taken out by hand stays out.
- **Stop and Build**: an answer that arrives after Stop changes nothing (taken in under the lock, only while still
  "thinking"); a request not yet sent when Stop or a canceled build comes is never sent; three answers at a time;
  Build after a stopped first answer reads everything said (a part set by hand after the last message about it
  stays, in the build job's plan too) and plans in the build job; a build-time request that runs too long is given
  up (told to stop through the assistant's `llm.converse`; through `llm.complete` it runs to its end and is
  dropped); every online request that went out counts toward the daily limit, also a failed or canceled one.
- **After the build** (`change_plan`, `video_flow.smart_job`, `_jump`): only the brief fields the change moved are
  set (editor choices and `ai_edit` stay); the plan's music and voiceovers carry `"brief": true` (planned videos
  only) and are placed again from the plan, while a sound moved, changed or made quieter by hand stays yours, one you
  placed yourself is never placed twice, and your own song keeps the plan's music; a new order is the bin's order;
  the look is compared with the current version; Undo/redo/going back bring back the plan each version was made
  with (`setup.plans`), the brief values it was made with (`setup.made`), the guidance made from them and the file
  order, and drop a plan change still waiting; a plan change whose edit fails or is canceled before it starts
  (`@on_stop("video_smart")`) puts back the plan, brief, guidance, name and order. `smart_edit.plan_words` is empty
  for videos made without a plan, and their sounds stay as you left them.
- **Inputs and privacy**: `asset_ids`, `remember` and file numbers are checked (422, not 500); the listening job is
  keyed by the set of files (`video_flow.bin_key`); what is sent now names the Brain rules, the memories, the plan so
  far, know-how and helper notes (`_sent`, the page's model line, `docs/legal/privacy.html`); planning never sends
  Brain notes to NVIDIA, whose agreement says they are never sent (`brain_allowed`; NVIDIA's privacy row and
  `nvidia.data_note` now name what planning sends).
- **The pages**: the plan form saves only what you changed since it opened; Length is From your style / As long as it
  needs / About… (choosing About… moves focus to Minutes; opening the form no longer does); the music file is never
  also a voiceover; Back from the editor skips the planning page (`router.redirect`); Build my video and Just do it
  wait for uploads, and words typed but not sent are asked about first; leaving names what would be lost in one
  sentence (`LeaveGuard.say`), and an open plan form counts only when changed; a file taken out stays out, also one
  picked again while it was in the video, and one taken out while uploading leaves no Resume row
  (`Picked.forget`); added files keep the order you dropped them in; only the words sent leave the message box;
  focus returns after a quick answer, Save or Cancel; Stop shows Stopping…; the editor's plan says what an empty
  plan means (and "Nothing decided yet" while it still plans) and hides Supporting media.
- **Checks**: `tests/test_video_setup.py`, `tests/test_video_setup_flow.py` (new tests for each fix),
  `e2e/sandbox/video-setup.spec.ts` (Back after Build; words not sent and form changes asked about);
  `frontend/dist` rebuilt.

## Make a YouTube video: drop in your files, tell ClipForge AI your idea, plan it together — 2026-11-08 (Claude Code)

Landry asked for the YouTube video setup to work like this: drop in your stuff, tell the AI your idea and plan, and it
can ask questions or not. Branch `claude/project-thread-2wwa4c` from the release line at 95a70e0. No release. Design,
bounds and routes: [docs/clipforge/VIDEO_SETUP.md](docs/clipforge/VIDEO_SETUP.md).

- **The start page** (`frontend/src/pages/MakeVideo.tsx`, rewritten; `#/create/video`, `?idea=` fills the box):
  your videos, pictures and sounds in one drop and in play order, your idea in your own words (4,000 characters),
  "Ask me questions" or "Just do it" (remembered: `video_setup_mode` in `prefs.py`, `prefs.tsx`, `Customize.tsx`),
  and More choices (style and example, remember the look, your script, the name).
- **The planning page** (`#/create/video/<id>`): the conversation with ClipForge AI (quick answers, "Just do it",
  Stop, notes from your helper agents), the plan as a slate whose changed lines light up
  (`components/VideoPlan.tsx`: `PlanSheet`, `PlanForm`, `useChanged`; `videoSetup.css`), your files with what was
  heard in each, adding more files, and Build my video. A video being planned is a draft project
  (`studio_projects.status = "draft"` with a `setup`, new column in `db.py`; `video_setup.is_draft`, so an animated
  short stopped before its first version keeps its own page and chat); Projects lists it and opens it here, and
  `#/video/<id>` sends it here (`planning` in the video view; `VideoReview.tsx`, `router.ts`, `App.tsx`).
- **The planner** (`clipfoundry/studio/video_setup.py`, new): built-in rules for lengths, shapes, feel, how much to
  edit, music, captions, keep and cut, openings, stories, audiences and video types; with a model, one bounded text
  request (files, what is said in them, memories, know-how, helper notes, the conversation, the plan) answered as
  `{"say", "questions", "plan"}` inside a JSON schema and checked field by field; questions at most 3 at a time and
  2 rounds, a quick answer keeps the others, typing drops them; merging keeps explicit words and hand edits; the
  online daily limit and "what was sent where" like the chat.
- **The plan drives the edit**: `plan_to_brief` fills the brief (length, shape, feel, editing, captions, music, keep,
  cut, the opening); `video_flow.py` gains `open_with` and `plan` brief fields and plans inside the build job when
  "Just do it" had no plan yet; `ai_editor.py` starts every window with the owner's plan (700 characters);
  `smart_edit.py` opens with the sentence that matches the asked opening and ranks passages that match the plan
  higher when fitting to length; the plan's file order sets the bin's order.
- **After the build**: "Your plan" on the editor page; `PUT /api/studio/videos/{id}/plan` edits again as a new
  version that Undo takes back.
- **Routes** (`studio/routes.py`): `POST /api/studio/videos/setup`, `GET|PATCH /api/studio/videos/{id}/setup`,
  `POST .../setup/say|stop|build`, `PUT .../plan`, `GET /api/studio/video-setup/model`; the old one-step
  `POST /api/studio/videos` is unchanged.
- **With the assistant (PR #37)**: a draft's chat answers through `chat.route` in the chat's own message shape, the
  `make_youtube_video` tool shows a button to this page, helper agents' notes come from `agents.consult`; each part
  is optional, so either PR can merge first.
- **Checks**: `tests/test_video_setup.py`, `tests/test_video_setup_flow.py`; `e2e/sandbox/video-setup.spec.ts` walks
  the whole flow in the sandbox (and at phone width); `frontend/dist` rebuilt.

## Safety follow-ups: the built-in AI's engine outlives a request's thread; other computers' addresses are never looked at — 2026-11-10 (Claude Code)

Branch `claude/project-thread-3rqurx` from the release line at ff890b6, PR #41. The two follow-ups the PR #39 review
found outside the engines, plus the same gap wherever a sweep of the whole app found it. Merged on Landry's standing
OK to merge finished work; no release.

- **The built-in AI's engine (llama-server) on Linux** was told to stop when its parent ends, and Linux counts the
  *thread* that started it as its parent: started from a request's worker thread (which retires after about ten idle
  seconds) or a job thread, it stopped with that thread, so the next answer loaded the model again.
  `builtin_ai._popen` now starts it from one lasting thread (the same code as PR #37, so that branch merges cleanly),
  and ComfyUI uses the same starter instead of its own. It still ends when ClipForge ends.
- **Other computers' addresses:** on Windows, merely looking at `\\server\share\x` or `//server/share/x` connects to
  that server and signs in as the person (their password hash goes with it). Any web page can make the browser ask
  ClipForge's address for something, a FilmCraft project can carry any text, and the AI's FilmCraft steps can be
  steered by words in a video. Now refused before anything looks at the file system:
  - `GET /craft/filmcraft/<file>` (FilmCraft's editor) and the app page's catch-all route: only plain folder and
    file names (`clipfoundry/pathguard.py`, shared with made files);
  - `GET /api/local/browse` and linking a file (`local_files.other_computer`): another computer is refused from the
    text alone; a share the owner listed in `CLIPFOUNDRY_LOCAL_ROOTS`, or a mapped drive, still works;
  - FilmCraft's editor looked up every text in a project as a possible file: another computer's address is no longer
    looked up (the video's own files on an allowed share or in a data folder on a share still are); a saved project
    naming `\/server/share`, a path starting with a backslash, or climbing with `..` is refused, so FilmCraft's render
    never opens it; the AI's finishing steps refuse a leading backslash too.
- **How it was found and checked:** a sweep of the whole app for both problems (five areas, then a skeptic per
  finding: six network-path cases confirmed, no other thread-bound child process), then an independent review of the
  change (three lenses, a skeptic per finding), which found one regression (the video's own files on an allowed share
  were skipped in FilmCraft's editor), fixed with a test. Every fix has a test that failed first and records each
  file-system call: `tests/test_builtin_ai_lifetime.py`, `tests/test_network_paths.py`, `tests/test_pathguard.py`,
  the last test of `tests/test_craft.py`.
- **Checks:** on the final code (b65d795) the full fast suite 2271 passed, 2 skipped, and `pytest -m slow` 30 passed,
  1 skipped (on b830fdf: 2268 and 30). On GitHub's machines, on b65d795: the FilmCraft check with the real FilmCraft
  and built-in AI (run 42783880588, macOS 15 + Ubuntu), the built-in AI check with the real engine (run 42783952354,
  Ubuntu, macOS 15, Windows) and the Local makers check starting the real ComfyUI through the shared starter (run
  42783957349, Mac, Windows, Linux) all passed.
- **Not verified:** a real Windows computer (Windows path rules were checked with PureWindowsPath and by recording
  file-system calls; no SMB server was contacted), a real FilmCraft project with footage on a NAS, the real
  llama-server (the stand-in engine was used).
- **Follow-up (not fixed here, different fix):** FFmpeg reads a downloaded "video" that is really a DASH manifest
  (`<MPD>` in a file named .mp4) and opens the files it names (checked with ffprobe 6.1 here), so on Windows a
  manifest naming `file:////server/share/v.mp4` would make ffprobe contact that server. The fix is a demuxer
  allow-list (`-format_whitelist`) on every FFmpeg input of media from outside, as `knowledge.probe_example` already
  does; it needs care so no supported format is refused, and real-media checks.

## Local makers: the final review's fixes, combined with story clips and animated shorts — 2026-11-10 (Claude Code)

PR #39 (branch `claude/project-thread-nnvh05`) took in the release line twice before merging: PR #40 (story clips,
merge 850adf0) and PR #36 (animated shorts, merge aff2a0e; `api.py` keeps both routers, `frontend/dist` rebuilt from
the combined code). Merged into the release line on Landry's standing OK to merge finished work. No release.

- **The shorts maker against the real door:** two tests in `tests/test_local_engines.py` run
  `clipfoundry/makers/local_engines.py` against `clipfoundry.engines` (cards before set-up, an engine picture made
  into a still clip, Stop, the built-in voice and its "machine-generated" rule); the shorts test of the set-up note
  checks both notes (with and without the engines package).
- **Fixed after the final review** (lifecycle, platforms and the newest code; a skeptic per finding; each fix with a
  test that failed first):
  - on Linux the parent-death signal follows the *thread* that started ComfyUI, so a ComfyUI started from a picture
    job's thread stopped when that job ended: it is now started from one lasting thread, and still ends with
    ClipForge; on Windows ComfyUI's set-up (uv) runs inside ClipForge's kill-on-close job too;
  - Stop works while ComfyUI is starting (the half-started ComfyUI is stopped), a picture stopped while ComfyUI is
    being reached is never sent, and closing ClipForge stops a set-up under way first;
  - a ComfyUI another ClipForge process started is asked to hand its graphics memory back, and heavy work asks before
    it waits for graphics memory;
  - `GET /api/engines/made/<file>` refuses anything but plain folder and file names before looking at a file (on
    Windows, looking at `\\server\share\x` connects and signs in to that server as the person);
  - deleting ComfyUI's folders uses Windows long paths, and Remove says so when files could not be deleted;
  - set-up checks for twice the packages' space (uv unpacks into its cache, then copies) and deletes uv's cache
    afterwards; `uv venv --clear --force` replaces whatever an earlier environment left; ComfyUI counts as set up
    only while the Python named in its `pyvenv.cfg` is still there (a moved ClipForge folder is set up again);
  - the process list is read as UTF-8 on Windows (PowerShell is told to write it) and on the Mac (ps in a UTF-8
    locale): a ClipForge folder under `C:\Users\José` was never recognised, and under `C:\Users\Müller` reading the
    list failed;
  - a stopped download of the shared text encoder stays with the model whose download it was (another model showed
    "Partly downloaded" and its Remove deleted it); Remove of only a stopped download says so, says that a model
    ClipForge did not download stays ready, and no longer makes the ComfyUI app unload its models.
- **Checks:** `tests/test_local_engines.py` 79 passed; on 19dfe77 the full fast suite (2179 passed, 2 skipped) and
  `pytest -m slow` (30 passed, 1 skipped); the Local makers check (now also reading a folder named with é, ü and 東
  back from each computer's process list, and failing if set-up leaves uv's cache) passed on GitHub's Mac, Windows
  and Linux on d2a8e21 (run 42749843276; Linux made its real FLUX.2 klein picture in about 4 minutes). The first run
  (42749458528, on 19dfe77) failed only on Windows, in the check's own log line: the folder was read back correctly,
  but printing 東 to a code-page-1252 console failed; the check now writes UTF-8.
- **Not verified** (needs Landry's computer): as before, Metal speed and memory, a real Wan clip, Windows with an
  NVIDIA card, the ComfyUI desktop app, and the shorts maker end to end with real engines.
- **Follow-ups outside the engines:** `clipfoundry/builtin_ai.py` starts llama-server with the same Linux
  parent-death signal from whichever thread asks; `clipfoundry/craft/routes.py` resolves a requested path before
  checking it (the Windows network-share risk fixed here for made files).

## Local makers: pictures, video and voice made on this computer — 2026-11-08 (Claude Code)

Landry asked (Nov 7) to look at seven open-source projects he found (FreeVideo, WanGP, ComfyUI Desktop, InvokeAI,
OpenHiggsfield, VoiceStudio, Tencent WeKnora), plug the useful ones into ClipForge, and keep everything local on his
Apple silicon Mac and on Windows. Branch `claude/project-thread-nnvh05` from the release line at 95a70e0; PR #39,
merged on Nov 10 after PR #40 and PR #36 (Landry's standing OK to merge finished work; see the entry above). No
release.
Design, every choice and the research: [docs/clipforge/LOCAL_ENGINES.md](docs/clipforge/LOCAL_ENGINES.md).

- **The door** (`clipfoundry/engines/__init__.py`, new package): `make_image`, `make_video`, `speak`, `voices`,
  `status`, with `progress(fraction, message)` / `cancel()` and one `EngineError` whose message is written for the
  person. The animated-shorts maker (its own thread) and ClipForge AI call only this. What is made goes to
  `data/engines/made/<kind>/<day>/` with a `.json` note (model, licence, words, seed, time).
- **ComfyUI as the picture and video engine** (`comfy_server.py`, `comfy.py`, `graphs.py`, `makers.py`, `models.py`):
  GPL-3.0, so always a separate program over HTTP on 127.0.0.1, never imported. Either ClipForge's own copy (one
  button: uv 0.13.7 from PyPI, a private Python 3.12, PyTorch 2.14.1 for Metal / CUDA 13.0 with driver ≥ 580 / the
  processor, ComfyUI 0.43.0 from GitHub's archive of the tag, its packages as of Nov 7 via `--exclude-newer`), started
  on demand with `--offline --disable-all-custom-nodes`, stopped after 10 idle minutes, shared between ClipForge
  processes; or the ComfyUI desktop app found on 127.0.0.1:8000 / :8188. The graphs are ComfyUI's official examples.
- **Models, all Apache-2.0, full precision** (fp8/int8 do not run on Metal): FLUX.2 klein 4B (recommended on 16 GB
  Macs and 8 GB NVIDIA cards), Z-Image Turbo (best detail and lettering), Wan 2.2 TI2V 5B (clips up to 5 s from words
  or a picture). Comfy-Org repositories pinned to commits; the shared Qwen3 4B text encoder is downloaded once.
  `makers.machine()/fit()/ranked()` recommend the one that suits the computer; Settings says when one will be slow.
- **The voice** (`voice.py`): Supertonic 3 (OpenRAIL-M; what it makes must be disclosed as machine-generated, so
  the rule asks for a "Voice is AI-generated" line in the caption) on the processor through ONNX Runtime, ClipForge's
  own code checked against Supertone's reference; 10 voices, 31 languages, sentence chunks, estimated word timings,
  WAV out.
- **Use rules agreed before a download** (`catalog.Model.rule`): Supertonic's OpenRAIL-M rules and the request on Wan's
  model card are shown in the download dialog, whose button reads "Agree and download"; `setup()` and
  `POST /api/engines/setup` refuse such a model without `agreed: true`; every picture, clip and voice note carries
  the rule.
- **Downloads** (`catalog.py`, `files.py`, `tasks.py`): every file pinned by address, size and SHA-256; resumable,
  free-space check, safe unpacking, one set-up at a time with Cancel; a model file ClipForge did not download is never
  replaced (same or different size).
- **Settings → Pictures, video, voice** (`routes.py`, `frontend/src/components/LocalMakers.tsx`, `studio.ts`): what is
  ready and why not, the three ComfyUI choices, set-up, each model with licence, size, memory and fit, Download / Use
  this / Remove (shown only when ClipForge downloaded the files there), a quick try for each part, the voice's licence
  rule. `frontend/dist` rebuilt. Not offered online (routes answer 404 in cloud mode).
- **Fixed after a code review (Nov 8, a test written first for each):** a ComfyUI app's model in a subfolder is sent
  by the name ComfyUI lists; Remove deletes only ClipForge's own downloads in the ComfyUI in use, keeps the shared text
  encoder while the other model has its files, refuses while a picture is being made, and lets ComfyUI release the
  files first (Windows); each job saves under its own name (the same request twice failed on ComfyUI's cache); uv's
  Python stays out of `~/.local/bin` and the Windows registry (`--no-bin --no-registry`, and the machine check fails
  if not); the venv's seed packages and PyTorch's dependencies are bounded by the checked day too (PyTorch installed
  alone with `--no-deps`); a complete `.part` file is finished instead of failing on HTTP 416, a refused range starts
  over once, the final rename retries on Windows; progress never goes backwards; Stop and time-outs wait until ComfyUI
  has let go of the graph; clearer words for a too-old ComfyUI and a missing model file.
- **Fixed after a second review (Nov 8, a test written first for each):** Remove keeps the shared text encoder only
  for a model that is complete or that ClipForge was part way through downloading (a file of the person's own with the
  same name as one of the other model's files, such as FLUX.1's `ae.safetensors`, made it keep 8 GB for a model that
  was not there, which nothing could remove afterwards), and says what it kept; a stopped download can be removed
  (the row says "Partly downloaded"); a picture or clip job now counts from starting ComfyUI to saving its file
  (`comfy_server.job()`), and Remove (`removing()`) is refused meanwhile and holds new jobs back while it runs, so it
  can no longer stop the ComfyUI a job is starting; ComfyUI 0.43's own model loader (used on NVIDIA cards) has its
  damaged-file words turned into plain words too. Found while checking those fixes: a `.part` file counts as
  ClipForge's in the app's folders only when ClipForge recorded it before its download started (another program's
  half-downloaded file of the same name was offered for removal), and Remove asks a ComfyUI that another ClipForge
  process started and shares to unload its models (`Server.release_files()`), since stopping it is not this
  process's to do and Windows would otherwise refuse the delete; removing ComfyUI itself is refused while such a
  process runs it (it deleted the program from under it).
- **Skipped, with reasons** (details in the design doc): FreeVideo (its MiniMax H3 model's licence excludes the
  United States); WanGP (custom licence needs a paid deal to ship inside a sold app; Wan 2.2 already runs through
  ComfyUI); InvokeAI (the same models already run through ComfyUI); OpenHiggsfield (only a page for a paid online
  service, and its code has no licence; the zip was unpacked apart and only read); WeKnora (a team-sized server
  needing several extra programs; a small passage search in the Brain is a follow-up); VoiceStudio kept for later
  (its default voice model is non-commercial and the app is heavy; it could add a creator's own cloned voice).
- **Checks:** `tests/test_local_engines.py` (60, a stand-in ComfyUI and a local file server, each test with its own
  data folder; `tests/conftest.py` stops any test from downloading); the full fast suite (2029 passed, 2 skipped) and
  `pytest -m slow` (27 passed, 1 skipped), both on 53dd380;
  `.github/workflows/local-engines-check.yml` + `scripts/local_engines_check.py` on GitHub's Mac, Windows and Linux
  machines: every pin compared with its source, ComfyUI set up from nothing and started, a model-free PNG and H.264
  clip, every graph accepted by the real ComfyUI, the voice (two voices, every word in order, 1.8–3.5× real time),
  and on Linux a real FLUX.2 klein picture on the processor (about 3 minutes once downloaded); all passed again on
  53dd380 (run 42704530253). The Settings page was checked in a browser at desktop and phone sizes, again on the
  final code (download dialogs, a stopped download shown as "Partly downloaded" and removed). Found and fixed by the machine check: ComfyUI exits at once (code 2) when its
  `--user-directory` does not exist yet.
- **Not verified** (needs Landry's computer): Metal speed and memory on a 16 GB and a larger Mac, a real Wan clip,
  Windows with an NVIDIA card, the ComfyUI desktop app, the shorts maker end to end with real engines.

## Animated shorts: undo keeps the scenes, Stop always frees a short, and the review's fixes — 2026-11-09 (Claude Code)

A full review of the shorts branch found one critical problem and about forty smaller ones; all are fixed on the
same branch (`claude/project-thread-5qybvh`, draft PR #36). No release.

- **Undo, redo and restore keep the scenes in step** (`makers/shorts.py`, `studio/video_flow.py`): each version of
  a short's plan keeps its scenes as they made its clips and the short's choices (`plan.short.rows`, `.options`);
  going back puts them back in the same database step that saves the version (`save_revision(..., also=...)`, one
  `BEGIN IMMEDIATE` transaction, which also turns two saves at the same moment into a Conflict). Before, the next
  build made the undone scenes again. A change still waiting stays and is made on top.
- **Stopping** (`studio/jobs.py`, `jobs.py`, `studio/routes.py`): studio jobs have stop hooks (`on_stop`); Stop all
  jobs cancels the running studio job too; a build given up after three interruptions says so and offers Try again;
  Stop frees a short whose build was lost. Ready, failed and stopped are written only when no newer build was asked
  for, and an overtaken build saves no version.
- **The script check is never skipped** after a writer that failed or was stopped; picture ideas from ClipForge AI
  never overwrite what the owner typed meanwhile; a scene another voice had to read gets Try again (and Make the
  short asks the chosen voice again); errors reach the owner in plain words (the cause goes to the log); the robot
  office names the job "Making the animated short".
- **The editor's changes:** fades that no longer fit a shorter clip are shortened in proportion; a whoosh the owner
  muted, changed or removed is never put back; sounds and pictures attached to a deleted scene are named in a note; a
  scene added after a clip the owner replaced goes after it; the Scenes panel's length is the video's.
- **Voices** (`makers/voice.py`): the engine's multilingual voices count for "Best voice"; brackets are broken up
  for `say` and espeak-ng; a failed voice listing is asked again after half a minute; the Settings hint appears only
  where Settings has the voice engine; the speech model is released whenever it was asked; Hear it never keeps a
  stand-in voice's sample (one file per request, the page says another voice read it).
- **Pictures** (`motion.py`, `pictures.py`, `cards.py`): pictures read with Pillow (see-through ones on the look's
  colour, big JPEGs decoded smaller, huge ones refused plainly); an engine picture that does not open becomes a card
  with the reason; a long word on a card gets smaller letters; New picture on a card moves its shapes; a clip thrown
  away mid-build is deleted when nothing uses it; leftovers of a closed app are tidied after an hour.
- **Pages:** Draw real pictures when a picture maker is set up after cards were made; the Make page says when
  ClipForge AI (and which one) suggests the pictures for a pasted script; no old failure banner over a ready short;
  the projects list reads each short's cover from the short, not from its plan.
- **Tests:** new `tests/test_studio_shorts_undo.py` (8), `_stops.py` (14), `_edits.py` (5); more in `_flow.py`,
  `_parts.py` (16) and `_voice.py` (22).

## Story clips: Full story, Story parts, five minutes at most, a still picture — 2026-11-09 (Claude Code)

Landry's videos: a creator reads Reddit posts aloud while he plays a game. He asked for story clips that keep the
picture still and centred and show as much gameplay as possible without distorting it; two settings, "Full story"
(one clip per story; the finder kept splitting stories) and "Story parts" (each story cut at its best places into
separate parts); and no story clip over five minutes, a longer story split no matter what. Branch
`claude/project-thread-6ouxbx` restarted from the release line at 95a70e0; draft PR into `claude/project-thread-x72wkd`.
No release. Design, rules and numbers: [docs/clipforge/STORY_CLIPS.md](docs/clipforge/STORY_CLIPS.md).

- **Stories no longer split** (`pipeline/stories.py`): pauses count relative to the narrator (`story_parts.rhythm`,
  `pause_weight`: a break only at 2.5 × the median pause and the 97th percentile, partly from the 90th); a boundary
  needs words (a strong announcement, an intro/sponsor/outro run starting or ending, a post's title read out where
  the subject changes, a story's first words or a post's title after a pause long for this narrator with a change of
  subject or after a pause far longer than any inside a story, a closing line then an opener, or a long break with a
  change of subject measured by the meaning model); intro/outro wording counts only in the first and last 12 % (at
  least 90 s); ClipForge AI's checks are held to the same cues, and when the narrator announces his stories only
  announced places and post titles where the subject changes are offered; a boundary only the model's word put there
  is dropped when it would leave a piece under 40 s (`_drop_fragments`). On 40 synthetic recordings of a gamer
  reading four posts (`tests/story_fixtures.gamer_reader`, seeds 1–40) the release line made 9 to 21 clips (15.1 on
  average); this branch makes exactly 4, each starting within 1 s of the labelled start; with a model that answers
  "new story" to everything, 4 on 30 of 30. On 423 situations written for the review (sponsor reads, intros and
  outros, posts read title-first, narrators who pause before each post, a text-to-speech reader, model mistakes, a
  worst case with long pauses inside posts) it finds every story; the release line finds 160.
- **Story parts** (`pipeline/story_parts.py`, new): part counts (`max(ceil(D/299.5), ceil(D/175), round(D/110))`,
  lowered while a part would be under 62 s; under about two minutes a story stays whole; in Full story a story of 5:00
  or less is one clip); cut places between sentences scored
  by what makes a good stop (the poster's update +0.45, a jump in time +0.35, right before a reveal +0.3, a line that
  leaves you hanging +0.3, a question or exclamation +0.12, a change of scene +0.12, a pause long for this narrator up
  to +0.25; a cut before "And/Because/Which…" or after an unfinished sentence −0.3); a dynamic programme with a cost
  for uneven parts and for parts outside 62–175 s, looking only at cut places that can lead to parts under the cap (an
  hour-long story plans in well under a second); when no set of sentence boundaries fits, Full story first tries one
  part more and Story parts fewer, longer parts, and only then is a part cut at the longest pause between two words or
  inside a long stretch without talking, never inside a word, and never leaving a part under a minute of silence in
  Story parts; ClipForge AI may choose among the four best places (`stories.Judge.choose_cut`, at most a quarter of the
  stories budget), used only when every part still fits.
- **Two settings** (`studio/clips_flow.py`, `link_import.py`, `prefs.py`, `routes.py`): the request mode `story_parts`
  makes a Full stories project with `options.story_split = "parts"` (`"whole"` otherwise and for older projects); the
  guidance preview, the link import and the remembered choice accept it.
- **Parts are stories of their own** (`studio/story_review.py`; `db.py` columns `part`, `parts`, `story_key`):
  `plan_parts`, titles "… (Part N)", the hook "Part N" shown for the whole clip (and still after a trim in the clip
  editor, unless the owner set its seconds), reasons "Part 2 of 3: starts …";
  *Split in the middle* and *Merge* number the parts again (`_renumber`).
- **Five minutes at most** (`story_parts.MAX_CLIP_S` 300, parts planned at most 299.5 s): in `plan_parts`; `capped`
  splits an older or hand-set story when its clip is made; *Start earlier*, *End later* and *Merge* refuse a longer
  story with the length in words; `PATCH /api/clips/{id}` refuses a trim that makes a story clip longer than five
  minutes (other edits to an older, longer clip still work), and a start or end that is not a time in seconds ("NaN",
  infinity) for any clip; the Stories card disables those buttons with the reason.
- **A still picture** (`story_review.story_edit`, `studio/guidance.py`): story clips start with `fit`, `center`, zoom 1
  and no push-in; only a framing chosen for the project (Customize, or its example video) changes that, not the app's
  settings, a style, a skill, a shared example or a Brain note (`guidance.story_framing`); a subject to follow chosen
  for the project with no framing gets the vertical frame. Captions go just above the fitted picture
  (`pipeline/captions.py` `above_picture`, `render.py` passes the picture's top edge, `blueprint.POSITIONS` accepts
  `"above"`), unless any level chose a caption position, and fall back to the lower third when there is no room; the
  room is measured with libass (two lines reach twice the font size; the "Part N" box ends 1.25 font sizes under its
  top), and captions at the top go under the headline while it shows (`hook_bottom`).
  "Used from your Brain" shows these as "Story clips (the whole picture, still)" with what they replaced. `"above"` is
  deliberately not a style choice in `studio/capabilities.py` (the full-video engine has no such position).
- **Screens:** Make clips (three kinds with what each does), Stories ("Part k of n", the limit, disabled buttons with
  reasons), the clip editor (the limit under Trim, "Above the picture" for Fit, the hook's seconds up to the clip's
  length), Studio labels, the Brain level words;
  `frontend/dist` rebuilt.
- **Docs:** `docs/clipforge/STORY_CLIPS.md` (new), `OWNER_GUIDE.md`, `LONG_VIDEOS.md`, `FEATURE_CHECKLIST.md`.
- **Independent review** (before the PR): found and fixed a 4:58 story split in two, cuts inside sentences and words
  near twice five minutes and in silent gameplay, a planner that took minutes on an hour-long story, kinds of story
  videos the stricter rules missed (sponsor reads, posts read title-first, narrators who pause before each post), a
  trim of "NaN" accepted, "Part N" covering captions at the top, a room check for captions above the picture that was
  too strict, "Part N" vanishing after a part was lengthened, and a subject to follow chosen for a story project doing
  nothing.
- **Checks:** `tests/test_story_parts.py` (15), `tests/test_story_clips.py` (15, two slow: libass placement and a real
  render), `tests/test_full_stories.py` (33; the gamer-reader recordings in `tests/story_fixtures.py`),
  `tests/test_smarter_ai.py`.
  Two existing expectations changed on purpose: ClipForge AI can no longer split a story at a change of subject that
  nothing in the words announces (the old near-miss test now uses a place whose words start a story).
  Full fast suite (`pytest -m "not slow"`): 1968 passed, 3 skipped; the 49 failures and errors are the same 49 tests
  that fail on the release line in this cloud machine (yt_dlp, faster_whisper, huggingface_hub and CUDA are not
  installed). Slow suite (`pytest -m slow`): 29 passed, 1 skipped (needs the sound cleanup model files). Story finder
  on 423 review situations: 423 (release line 160). `tsc --noEmit` clean, `npm run build`. Browser tests (`e2e/`,
  the app on seeded data): 56 passed, 4 skipped, 8 failed, the same 8 that fail on the release line with the same data
  (Autopilot, Office and Settings expectations outside this change).
- **Not verified:** real speech recognition on Landry's own videos (the numbers are on synthetic recordings built from
  real post patterns); ClipForge AI's real model choosing among cut places (tested with stand-in answers and a broken
  model).

## Make → Animated short: viral voice-over shorts, made on this computer — 2026-11-08 (Claude Code)

Landry asked for a maker of the animated voice-over shorts seen on TikTok: paste a script, or have it written, and
everything running locally on his Apple-silicon Mac. Branch `claude/project-thread-5qybvh` from the release line at
95a70e0. No release. Design and contracts: [docs/clipforge/ANIMATED_SHORTS.md](docs/clipforge/ANIMATED_SHORTS.md).
The picture, video and voice engines themselves come from the local-engines work (`clipfoundry/engines`, branch
`claude/project-thread-nnvh05`); this branch talks to them through one door and works without them.

- **Scenes** (`clipfoundry/makers/scenes.py`, new): a pasted script becomes scenes of 6-16 spoken words (one picture
  every 2-4 seconds at 175 words a minute); blank lines, "Scene 3" headings and timings end a scene; `[Visual: ...]`,
  `Show:`, `B-roll:` and bracketed lines become the next scene's picture; titles, music, sound and hashtag lines are
  dropped; at most 600 words and 80 scenes, refused in plain words. Picture ideas from a scene's own words name the
  script's subject.
- **ClipForge AI writes** (`makers/writer.py`, new): a script from a topic, tone, length and audience, or picture
  ideas for a pasted script, as one JSON object in a schema; reads the owner's memories first (recorded as used in
  "short_script"), then the new **Animated voice-over shorts** playbook with hooks and endings
  (`brain/knowhow.py`: 13 playbooks, task "short"); outro lines are taken off, long lines split, a script far from
  the length asked once more; Stop works while it thinks.
- **Voice** (`makers/voice.py`, new): the local voice engine, else macOS `say`, Windows SAPI or espeak-ng (as its own
  program); speed; a voice sample for Hear it; word times from the engine, the speech model when it is downloaded
  (never downloads) or estimated from the sound; the engine's licence rule is kept with each scene's voice.
- **Pictures and motion** (`makers/pictures.py`, `cards.py`, `motion.py`, `looks.py`, new): eight looks; the picture
  engine when it is set up, else an honest designed card with the scene's key words (out of the caption zone); a
  sub-pixel push-in or pan on the still (OpenCV frames piped to FFmpeg, BT.709, exact length), or the video engine's
  motion slowed at most 1.5 times and held.
- **The short** (`makers/shorts.py`, `routes.py`, new; table `short_scenes`, JSON column `studio_projects.short`):
  one durable `short_build` job makes only what changed in each scene, one failing scene never stops the others, and
  the plan is one clip per scene with centred captions where the spoken word lights up (`captions.highlight`,
  `studio/engine.py`), music at -20 dB ducked under the voice and a whoosh on every other cut; the owner's editor
  changes stay when scenes are made again. A change shows "Waiting to make the changes" until the build starts.
  `/api/studio/shorts/...`; projects list filter `kind=short`; Stop says how to go on.
- **Pages** (`frontend/src/pages/MakeShort.tsx`, `components/ShortScenes.tsx`, `shorts.ts`, `pages/shorts.css`,
  new): Make → Animated short (paste or write, look cards, voice with Hear it, speed, music, captions with "Fits the
  look", camera moves or animated pictures, what will make it); the Scenes panel on the editor page (words, picture
  idea, new or earlier or own picture, camera move, move, add, delete, try again, voice/look/music for the whole
  short, how it was made); a reminder next to Download when the voice's licence asks for an AI label; Studio shows
  three things to make; Projects has an Animated shorts filter; the top bar says "Video" on the editor page.
- **Tests:** `tests/test_studio_shorts_flow.py` (12), `_parts.py` (12), `_voice.py` (18), `_captions.py` (5) and the
  slow `_render.py` (a real short with espeak-ng, rendered and its frames checked); the know-how tests count 13
  playbooks. Browser check against the real app: a 5-scene short made from the page in 18 s, then words changed, a
  scene moved, added and deleted; 1440 and 390 px wide.
- **Not checked here:** the real picture, video and voice engines, macOS `say`, Windows SAPI, ClipForge AI writing
  with a real model and the speech model's word times (none can run in the cloud computer).

## ClipForge AI far smarter: meaning, scout and judge, eyes, ears, your taste — 2026-11-07 (Claude Code)

Landry asked to make the built-in AI and the editing "100 times smarter", with research first and anything useful
plugged in, and asked that his two research guides be used. Branch `claude/project-thread-hud5t5` from the release line
at 7723696 (PRs #30 and #31 merged). No release. Design, numbers and the research table:
[docs/clipforge/SMARTER_AI.md](docs/clipforge/SMARTER_AI.md).

- **The meaning model** (`clipfoundry/embedder.py`, new): all-MiniLM-L6-v2 (Apache-2.0) on the CPU through ONNX
  Runtime; two files downloaded once at a pinned revision and checked against pinned SHA-256 hashes (a tampered file is
  deleted); a word-piece tokenizer in the module; a 40,000-vector cache; setting `meaning_model` (on); Settings → AI
  helper → "Understanding meaning" (state, progress, Cancel, Download now, Remove); `GET /api/ai/meaning`,
  `POST /api/ai/meaning/install|cancel|remove`. Without it everything falls back to the word-based vectors.
- **One scale for two spaces** (`pipeline/semantic.py`): `Embeddings` carry the model and the video's own baseline
  similarity; `cos_cal` removes it, novelty is rank-based; `diversity.py` uses the calibrated cosine. The brain's
  memories use the meaning model when present (`brain/meaning.py` `model()`, `make()`, `min_similar()`;
  `brain/memories.py` never compares vectors from different embedders).
- **Scout and judge** (`pipeline/scout.py`, new): the model reads the transcript in 8,000-character windows and names
  up to 12 moments, each snapped to sentences and scored by `candidates.window` (new) like any other; four deep-stage
  places are kept for them. The finalists are ranked side by side with green/yellow/red verdicts; the ranking moves a
  Clip Score by at most ±10 (percentile against percentile), green +2, red −6 with the reason as a warning. Both passes
  read one brief (title, picking playbooks, the owner's rules, wanted length, taste) inside a budget of
  `ai_edit_timeout_s × 10` (at most 10 min); the built-in model answers inside a JSON schema. Setting `ai_scout` (on).
- **Eyes** (`pipeline/eyes.py`, new): three frames of the six strongest finalists go to the built-in model's vision
  part with the clip's first words; it answers in a schema (kind, people, text on screen, best thumbnail, description,
  appeal 1–10); at most ±4 on the Clip Score; the chosen frame becomes the thumbnail (`render.thumbnail_time`).
  `builtin_ai.chat` gained `json_schema` and `images`; `llm.complete` passes them through. Setting `ai_eyes` (on).
- **Ears** (`pipeline/ears.py`, new): pitch every 20 ms by autocorrelation, pitch variation, emphasis moments (pitch
  +3 semitones and loudness +0.8 σ together), laughter-like bursts (word-free, 3–8 Hz pulsing), the pause before the
  end, monotone; a prosody score joins the deep extras and a flat voice is named in the "Why". The smart editor's
  punch-ins land where the voice leans on a word (`studio/smart_edit.py`, cached `prosody.json`); when a recording's
  voice stays even after every cut, the old every-other-cut rhythm takes over for it (found by the release line's
  slow render test on a synthetic voice, fixed before the 2026.11.07 release); the note says how many and which
  rule.
- **Your taste** (`clipfoundry/taste.py`, new; tables `taste_events`, `taste_models`): lessons from unticking,
  re-ticking, exporting, publishing and deleting clips with the clip's 16-number profile; after 12 lessons (4 each
  side) a logistic regression gives each finalist at most ±6 with the reason in words, also read by the scout's brief;
  `GET/DELETE /api/taste`; PATCH `/api/clips/{id}` records choices; export and publish call `taste.published`;
  Brain → Memory shows what was learned and can forget it.
- **Full stories** (`pipeline/stories.py`): meaning shifts between the six sentences before and after each gap (robust
  z-score; z ≤ −2.5 and shift ≤ 0.25 → topic 0.22, z ≤ −1.8 and shift ≤ 0.35 → 0.12) when the meaning model is on
  (`propose(..., opts)`, `story_review.py` passes the settings); `Judge.scan` reads the recording through and names
  where stories begin before the unsure boundaries are reviewed; an unreadable answer no longer counts as "no new
  story here" (a real bug: it dropped weak accepted boundaries).
- **Deep analysis for every "Make clips"** (`pipeline/process.py`, `deep.py`): `deep_analysis` on by default with a
  pool of 4 × clips (24–40); the clip's stored analysis carries `clip_score`, `explanation`, `judge`, `scout`, `taste`
  and a small `deep` summary; the app shows them (`components/viral.tsx` `AiNotes`: scout line, rank and verdict,
  "ClipForge AI saw", "The voice", "Your taste", "How the Clip Score came about"). `frontend/src/api.ts` has the types
  and routes; `frontend/dist` rebuilt.
- **The guides' rules** (`pipeline/text_utils.py`, `virality.py`): the causal engine (pivots "but", "because", "which
  meant", "turns out" raise curiosity by up to 0.06; an "and then" chain with no turn costs 0.10 and shows the warning
  "\"And then\" chain"; `signals.causal_pivots`, `signals.episodic`); constrained-experiment hooks ("I spent 30 days",
  "I tried", "here's what happened", "on a budget", "with only") as hook and open-loop phrases; chapter-cliff fillers
  ("furthermore", "my next point", "on to the next") as transitions.
- **Fix:** `taste.predict` could return NaN when a feature never varied (standard deviations floored at 1e-4, z-scores
  clipped at ±4).
- **Checks:** `tests/test_smarter_ai.py` (39 tests; one runs the real model when `CLIPFORGE_MEANING_MODEL_DIR` is set);
  `tests/conftest.py` points the model hub at a closed port so no test downloads; `tests/test_review_creation_fixes.py` compares the unrounded ranking value (the one-decimal score can coincide when the prioritised factor sits at the mean, which the new curiosity term made happen for its passage); `scripts/builtin_ai_check.py
  --meaning --eyes` and `.github/workflows/builtin-ai-check.yml` check the real download, hashes, similarities, speed,
  a schema-bound ranking and the eyes on a GitHub runner (the model hub is blocked from the cloud computer).

## The ClipForge look: one design system and every page restyled — 2026-11-07 (Claude Code)

Landry asked to "improve the entire UI for the app, make it look very very good". Branch `claude/project-thread-89ew66`
from the release line at 3c6b980 (the long-video work runs in its own branch beside it). No release.

- **The design** ("the edit bay", [docs/clipforge/DESIGN_SPEC.md](docs/clipforge/DESIGN_SPEC.md)): dark layered
  surfaces lit from their top edge, sunken wells for the places media goes (drop zones, timelines, chats, lists),
  lifted buttons, the footage on the darkest stage so it is the brightest thing on the page, and one accent for the
  action that moves work forward and the place you are in. Dark only, as before. Poppins SemiBold (the caption face,
  bundled) for titles, the system font for everything else; 15/13/12 px text, 17 px section titles, 28 px page
  titles; sentence case everywhere, no all-caps labels. Radii 8/12/16 px; controls 36 px (32 compact, 44 on touch);
  sidebar 236 px, top bar 56 px, content up to 1280 px.
- **The design system** (`frontend/src/styles.css`, rewritten): fonts, scale, spacing, shape, light and depth
  (`--lift`, `--lift-sm`, `--sink`, `--well`, `--frame`, `--glow`) and every shared component: the shell (the rail
  marks the current place with the accent tint and a 3 px bar; blurred top bar; drawer under 1024 px), page heads,
  buttons, pills, tags, panels, forms (inputs in wells, a custom select, choice cards, segmented controls, switches,
  chips), drop zones and file rows, tabs and the Settings side list, the editors (stage, timeline, words, desk, save
  bar, versions, sequence, the ClipForge AI chat), tables, sign-in, dialogs, menus, toasts, loading skeletons, empty
  states and the robot office. Every class the pages use kept its name, so the look changed without touching how
  the pages work.
- **Palettes and accents** (`frontend/src/theme.css`, tokens only): Studio, Midnight, Graphite and Plum retuned
  (deeper canvas, clearer steps between layers) and the six accents with hover and tint; quiet text never below 6:1;
  `tests/test_theme_contrast.py` still checks every pair, and the spec lists the measured ratios.
- **Pages:** the Studio's two big choices glow with the accent; a project's clips are lifted cards; the clip and
  video editors have a framed stage, a sunken timeline and a desk head with a mark; Review packs its panels into two
  columns, preview above look and outputs above guidance (`LayoutFlow` in `components/AppearanceSettings.tsx` packs
  sized panels into columns so no hole is left beside a tall one; default widths in `prefs.py` and `prefs.tsx`
  `REVIEW_SIZE`); Settings has a side list of sections (`SettingsFrame` in `pages/Settings.tsx`, a tab row under
  900 px) with Appearance at full width; Brain → Memory shows its summary as tiles and the playbooks as a quiet list;
  the knowledge map sits on the canvas with a faint grid; the office keeps its pixel titles and room colours on the
  shared surfaces with the map as a framed window; Posts and the TikTok setup use the tokens instead of their own
  colours.
- **States:** loading pages show a title block and panel-shaped skeletons (a shimmer once per 1.6 s, paused when the
  tab is hidden) instead of a spinner; empty states have an accent disc with the icon, one sentence and one action;
  the ClipForge AI chat says what will appear in it; the sidebar's collapse button says what it does.
- **Also:** the long-video thread's new wrappers (`.script-drop`, `.script-panel`, `.script-line.matched/.weak/
  .missing`, `.script-takes`, `.local-browser`, `.local-list`, `.local-pick`) are styled ahead of their arrival;
  `index.html` paints the new canvas colour before the app loads; before/after pictures in
  `docs/clipforge/ui-redesign/`.
- **Checks:** `cd frontend && npm run build`; `python -m pytest -q tests -m "not slow"`; the browser checks for the
  shell, library, Settings and the office against a throwaway app: 32 pass, and the 5 that fail (three office map and
  bar checks, two Settings checks) fail the same way on the release line with the same data.

## Long videos: full stories found right, big footage, your script, and a smarter cut — 2026-11-07 (Claude Code)

Landry could not get 17 GB of footage into "Make a YouTube video", found the cut it made weak, wanted to give it the
script to compare with the footage, and asked first for the Full stories section to find every story in a video of
someone reading posts and make one long clip per story without asking anything. Branch
`claude/project-thread-6ouxbx` (from the release line at 32485bd), draft PR into `claude/project-thread-x72wkd`. No
release.

- **Full stories** (`pipeline/stories.py`, `studio/story_review.py`, `jobs.py`): the finder learns the narrator's own
  separators from the recording ("next story", "story number three", "this one is from r slash…", a post title read
  out, numbering in order), knows the strong and weak openers and the Reddit title patterns, never splits an update
  or a top comment from its story, labels intro, sponsor and outro blocks, and looks at a topic dip against the
  chunk's own median rather than silence alone. Every story runs until the next one starts (the transition words go
  with the story before them), nothing waits for a check, and each clip is made at once. With ClipForge AI's model
  set up it gives a second opinion on the least certain boundaries inside a time budget and names the stories from
  the post title. Text-to-speech narration (no pauses) is handled.
- **Big footage** (`studio/local_files.py`, `studio/local_routes.py`, `studio/uploads.py`, `studio/proxies.py`,
  `pipeline/transcribe.py`, `pipeline/audio.py`): on the desktop, **Add from this computer** browses the owner's
  folders and drives (`GET /api/local/browse`) and uses files where they are (`POST /api/uploads/link`; nothing
  copied, the file never changed, found again if moved within the allowed folders); the upload limit is the free
  space less 2 GB (at most 512 GB) instead of a fixed size. Each asset has a work folder (`uploads.work_dir`) for
  its sound, transcript pieces and preview copy. Long files are listened to in pieces (`transcribe.transcribe_long`,
  resumable from `transcript.parts`, the model held across the pieces of one batch and released after it,
  `release_model`), and a closed app carries on where it stopped. `POST /api/assets/{id}/prepare` does the sound,
  the transcript and a small preview copy in the background (`preview_proxies` setting); previews read the copy,
  the final render always the original (`assets.proxy_path`).
- **Your script** (`studio/script.py`, `studio/script_cut.py`, `video_flow.set_script`, `db.py`
  `studio_projects.script`): `.txt`, `.md`, `.docx`, `.pdf`, `.fdx` or pasted text (`POST /api/studio/scripts/parse`;
  `pypdf` and `python-docx` added to the requirements) become numbered lines, headings and directions. Every spoken
  line is matched to the transcribed words of every recording, each time it was said is a take, the take said most
  cleanly plays (`take_quality`), the others follow it switched off ("Another take of line 12"), neighbouring lines
  said in one go are one clip, what is in no line waits at the end switched off, a heading is a chapter, missing
  lines are named. `use_take` swaps a take in (the clip is split around the line, the old take kept behind it). A
  script goes with the new video (`POST /api/studio/videos` `script`) or later (`PUT /api/studio/videos/{id}/script`,
  a new version in the background; `null` takes it away). With a script the model is not asked anything; pictures,
  music and effects come from the smart edit as before.
- **A smarter cut without a script** (`studio/smart_edit.py` `judge_sentences`): the cleanest take of a line said
  again anywhere in the footage plays and the rest are switched off in place (`best_takes`: content-word index,
  similarity ≥ 0.8 on four or more words; a line said more than three times is a catchphrase and stays); warm-ups
  and throat-clearers in a recording's first 20 s, words to whoever is recording in its last 45 s or tenth, and a
  sign-off before the last recording are left out (`chatter`); a video of two minutes or more opens with its
  strongest line and then plays from the start (`cold_open`: the model's `hook` or the best `hook_score` after 15 s
  inside the first 60%; brief `cold_open`, on by default; Shorten the introduction skips it).
- **ClipForge AI reads the whole video** (`studio/ai_editor.py`): what the rules left out is not sent (`skip`),
  windows carry the story so far (the chapters found earlier), up to 64 windows are read inside a time budget
  (`ai_edit_timeout_s` × 15, between 2 and 15 minutes, `budget_for`), the first window always; a `hook` it names is
  only ever a sentence that plays; the report says how many sentences it read and how many were not sent.
- **In the app** (`components/ScriptDrop.tsx`, `ScriptPanel.tsx`, `LocalFiles.tsx`, `longVideo.css`,
  `pages/MakeVideo.tsx`, `pages/VideoReview.tsx`, `studioParts.tsx`, `studio.ts`): "Your script" on the Make a
  YouTube video page (drop, choose or paste), "Add from this computer" on the desktop, the cold-open choice in the
  brief; on the editor page a **Script** panel (every line with where it plays, Use this take, add, change or take
  away the script), "Cold open" and "Line N" pills in the sequence, "Use this take" on the other takes, Add from
  this computer under Your media. `frontend/dist` rebuilt.
- **Tests:** `tests/test_full_stories.py` (13), `tests/test_studio_script.py` (23), `tests/test_studio_script_cut.py`
  (4), `tests/test_transcribe_long.py` (17), `tests/test_studio_local_files.py` (9), `tests/test_studio_proxies.py`
  (3, needs ffmpeg), `tests/test_studio_smart_edit.py` (21). No speech model, no real footage and no built-in model
  in the cloud: the words are given.
- **Design:** [docs/clipforge/LONG_VIDEOS.md](docs/clipforge/LONG_VIDEOS.md) (new); `SMART_EDITING.md`,
  `OWNER_GUIDE.md`, `ROUTE_MAP.md`, `FEATURE_CHECKLIST.md` (rows 43 to 45) updated.

## ClipForge AI know-how: the research turned into playbooks, and editors that apply its numbers — 2026-11-06 (Claude Code)

Landry gave ClipForge AI two research guides (a cinematic filmmaking and post-production guide, a viral short-form
video strategy guide) and asked to use them to make the AI smarter at its job, plus "your own stuff". Branch
`claude/project-thread-605vsm` (restarted from the release line at 936d7fc, after phase A merged). No release.

- **Know-how** (`clipfoundry/brain/knowhow.py`): twelve playbooks in plain words with numbers (hooks and openings,
  endings and loops, pacing and cuts, captions and safe zones, voice and sound mix, music by mood, colour by mood,
  effects that earn their place, picking a clip, platforms and export, reading a retention graph, talking-head
  edits), distilled from the guides and ClipForge's own rules. `select(query, task)` picks the few that fit a question
  or a job (rarer words count more; the words a playbook is about count double; a task's defaults fill in) inside a
  character budget; `answer(query)` is the one playbook that answers a question alone; `principles(task)` the
  one-line reminder for a task's instructions. The owner's memories always win over it, and the prompt block says so.
- **Where it is read:** the general chat (1,400 characters after the memories; without a model it now answers
  editing questions from the playbook that fits, e.g. "how loud should my video be?"), change requests (900, after the
  memories, dropped first when a long video needs the room; the request's new `knowhow` column records what it read;
  the principles line is in the instructions), smart-edit advice (700, before the brief of every window; the system
  text now says to keep the strongest line first and leave out outro lines), the FilmCraft pass (1,500: colour,
  effects, sound by default; the system text says correct before grade, effects with their sound, voice first), clip
  scoring and post packages (the principles line). "Why?" names the playbooks a request read. Brain → Memory lists
  every playbook (`GET /api/brain/memories/knowhow`; `POST …/knowhow/select` shows what a question would read).
- **The editors apply the numbers:** outro lines ("to recap", "thanks for watching", "follow for part two",
  `text_utils.OUTRO_PHRASES`) are a warned flag, lower the payoff and make a poor opener, so the ending before them
  wins; loss or warning framing (`LOSS_WORDS`, `LOSS_PHRASES`) and starting in the middle of a story score higher as
  openers and hooks; hook lines prefer plain words and 4-12 words (best under 8); the hook headline starts below the
  apps' top bar (15% instead of 11%) and shrinks for long text (68 / 58 / 50 px); "bottom" captions sit 36% up,
  above the 35% the apps cover (was 23%, inside it); the voice clean-up uses the dialogue chain (high-pass 80/100 Hz,
  2/3.5 dB out of the mud at 300 Hz, 2/3 dB of presence at 3.5 kHz, 2.5:1/3.5:1 with a 20 ms attack and a 90 ms
  release); clips are converted to YUV with the BT.709 matrix and tagged BT.709 (FFmpeg used BT.601 for the RGB
  frames before, a visible shift of reds and greens on every clip), delivered with a closed GOP and a keyframe every
  half second, and AAC at 256 kbps (full videos: keyframes every half second, 256 kbps too).
- **In the app:** the chat shows "From its know-how: …" under answers and proposals; Brain → Memory has "What it
  knows about editing (built in)" with every playbook expandable; the chat's example chip asks "How loud should my
  video be?". `frontend/dist` rebuilt.
- **Tests:** `tests/test_clipforge_ai_knowhow.py` (12). The chat's answer is now returned as written before the model
  starts (the page polls), which also removes a timing race in the chat tests.
- **Design:** [docs/clipforge/CLIPFORGE_AI.md](docs/clipforge/CLIPFORGE_AI.md), "Know-how".

## ClipForge AI phase A: the brain's memories and the chat — 2026-11-06 (Claude Code)

Landry asked for a much better AI ("ClipForge AI"): research the best models, combine them, add its own data and
training, let them talk to it, keep everything in the brain, find music and pictures, make effects and music. The
research and plan are in the Claude Doc "ClipForge AI: research and plan"; Landry chose **brain and chat first**.
Phase A is on `claude/project-thread-605vsm` (from the release line after #25 and #26). No release.

- **The brain's memories** (`clipfoundry/brain/memories.py`, `meaning.py`, tables `brain_memories`,
  `brain_memory_uses`): rules, facts, episodes (what it did), each with a source (said, did, guessed, imported), a
  confidence, a scope (every video, one video, a platform, clips or video) and a meaning vector (`hash-v1`: hashed
  words, stems and pairs, 256 dims, no download; a real embedding model is a later download, tracked by
  `meaning_model` and recomputed by Rebuild). Recall = standing rules first, then the best few by words and meaning
  within a character budget, never an unrelated memory. The same words said twice are one memory with the stronger
  source. Guesses expire after 60 days unless confirmed. Health check, Tidy, Rebuild, export and import
  (`clipforge.brain-memories/v1`). Routes under `/api/brain/memories`.
- **Where it is used:** change requests (1,200 characters of memories in the prompt; what was applied or discarded is
  remembered), the FilmCraft finishing pass (800) and smart-edit advice (500). Every use is recorded against the
  memory, so "why?" can answer.
- **The chat** (`clipfoundry/brain/chat.py`, tables `brain_chats`, `brain_chat_messages`, routes under
  `/api/brain/chats`): teaching, forgetting, listing and explaining without a model; in a video's chat anything else is
  a change request (rules, then the model; Apply or Discard); in the general chat it is a question the model answers
  with the recalled memories as one checked JSON object (`{"say": …}`, at most 1,200 characters), counted against the
  daily AI limit. The model never calls a tool and never sees a file. Answers cut off by a restart are reported.
- **In the app:** `components/ClipForgeAI.tsx` replaces the change-request form on a video and is Brain → Talk;
  `components/MemoryTab.tsx` is Brain → Memory. "AI helper" is now **ClipForge AI** and the built-in AI is its
  **built-in model** everywhere the owner reads it; setting keys and API addresses did not change.
- **Design:** [docs/clipforge/CLIPFORGE_AI.md](docs/clipforge/CLIPFORGE_AI.md). Tests: `tests/test_clipforge_ai_brain.py`
  (9), `tests/test_clipforge_ai_chat.py` (5), plus new cases in the change-request and craft tests.
- **Not in phase A:** the embedding model download, finders (music, pictures) and makers (music, effects), settings in
  words, the taste model and the editing adapter (phases B to D in the plan).

## The built-in AI finishes the edit with FilmCraft — 2026-11-06 (Claude Code)

Landry chose "Combine, test, then merge": the built-in AI (phase 1, PR #25) and FilmCraft inside ClipForge (PR #26)
are joined on `claude/project-thread-605vsm`, and both go into the release line once the real check passes. No
release.

- **Joined:** PR #25's branch merged in. Overlaps fixed by keeping both sides: the server's shutdown stops running
  FilmCraft/EffectCraft tools and the built-in AI's engine; `config.py` has both setting lists; change logs kept;
  `frontend/dist` rebuilt from the merged sources.
- **The built-in AI does the FilmCraft pass** (`craft/ai.py`): it counts once downloaded (`ai.usable`), and
  `finish.edit_key` includes its level, so downloading it or switching level edits again. Its request is shortened
  to 14,000 characters for a model on this computer (`SHORTER`: tool descriptions, quotes, effect and look names,
  then clips, the main video's first); online services get up to 40,000. Ollama is now asked for an 8,192-token
  context for this pass (it defaulted to 4,096, which cut the request short).
- **Waiting for a local model:** `ai.ask` runs the request in its own thread so the job can be cancelled while the
  model thinks; local models get up to 10 minutes (`llm.complete(timeout=...)`, also used by Ollama and LM Studio)
  and the built-in AI answers in JSON mode (`json_object=True`, llama.cpp's `response_format`).
- **Real check:** `scripts/craft_check.py --builtin-ai` (in `filmcraft-check.yml`) downloads the engine and the Basic
  model the way the app does and runs the AI pass with them on the real apps.
- **First real run (42269267394):** on both machines the built-in AI was still answering at the 10-minute limit
  (no length cap, so a small model can go on until the time-out). Now a local model's answer is capped at 1,200
  tokens and it is asked for at most 10 steps; an answer cut off at the cap still gives the steps it finished; a step
  repeated word for word runs once. The check prints llama.cpp's timings and the engine's log when nothing lands, and
  gives GitHub's Mac machine (no graphics chip) 25 minutes.
- **Second real run (42274107689):** Ubuntu passed. The built-in AI answered in 164 s (4,359-token request at 73
  tokens/s, 844-token answer at 8 tokens/s) with 10 steps, and 6 landed in FilmCraft's render: a blur, brightness and
  contrast, a push-in keyframe, a "Lake Day" title and a box. 4 used names FilmCraft lacks. On GitHub's Mac (1.5
  tokens/s, 1,019 s) all 11 of its steps were transitions with a `duration` FilmCraft's transitions don't have, and
  the final screenshot after the save timed out (the save itself came back as version 2). Now a step that fails only
  on a parameter FilmCraft says it lacks runs once more without it (FilmCraft checks parameters before changing
  anything), the request shows a transition example, and the check's screenshots are pictures only.
- **Fixed in the built-in AI's setup:** it was marked done before it was chosen as the AI helper, so Settings (and a
  test, about one run in five) could read the old helper. It is chosen first now.
- **Tests:** six new in `tests/test_craft.py` (the shortened request, the built-in AI before and after download,
  cancelling a slow answer, the timeout, JSON mode and answer cap reaching the engine, a cut-off answer). The request now shows three example
  steps that real FilmCraft accepts (a look, an effect, a keyframed push-in), which small models need.

## FilmCraft and EffectCraft inside ClipForge: fixes from the real apps — 2026-11-06 (Claude Code)

The first real-app run (GitHub macOS 15 and Ubuntu, run 42250189370) applied all 29 FilmCraft steps and FilmCraft's
render passed its checks, and showed three problems, fixed here:

- **EffectCraft's title script** failed on `layer.property("Source Text")` (EffectCraft 0.9.2 has no such shortcut).
  Shot scripts now use helpers that look properties up by match name first (`craft/shots.py`), run in an empty
  project (`--empty`, with a retry without it for an EffectCraft that refuses it), use ClipForge comp names, and
  report what they could not set. The AI is told about the helpers.
- **FilmCraft's editor on the editor page**: the released web build (0.17.1) has the `window.filmcraft` API but no
  host messages, so the page never opened the version. The page now opens it when FilmCraft has started, takes
  `.fcproj` downloads from the frame as saves, and has a Save to ClipForge button (`file.saveAs`).
- **The check itself**: the seeded project's own rough-cut job raced the check's plan (sometimes saving version 2);
  the AI stand-in picked a clip kind that does not exist. A failing AI pass no longer stops the FilmCraft edit.
- **Second run (42255291402)**: the EffectCraft title now renders and is placed on both machines (`checks: ok`), the
  AI pass applied its steps and placed its EffectCraft shot, and FilmCraft's editor started in headless Chrome
  (WebGL2) and took the files. Fixed after it: FilmCraft only opens a project `File` made by its own window, and
  look names contain commas ("Teal Shadows, Warm Skin"), so the AI now gets the effect and look lists as JSON.
- **Third run (42256808188): passed on macOS 15 and Ubuntu.** FilmCraft edit (30 steps, none failed) with the
  EffectCraft title placed, FilmCraft's render checked, the AI pass (4 steps and an EffectCraft lower third, none
  failed), and FilmCraft's editor on the editor page: started on WebGL2, opened version 1 with all 9 tracks and its
  files, and Ctrl/Cmd+S in FilmCraft came back to ClipForge as version 2.
- A FilmCraft or EffectCraft process still running when ClipForge quits is now stopped with it (the check's server
  had left a FilmCraft preview render running).

## FilmCraft and EffectCraft inside ClipForge — 2026-11-06 (Claude Code)

Landry: "I want film craft to actually be in my app and not seperate and the ai uses it to edit and it can use any of
the tools it offers and if it uses one program to do effects it then takes that shot and puts it in the final edit".

- **Fetched by ClipForge** (`craft/apps.py`): FilmCraft 0.17.1 and EffectCraft 0.9.2 release files for macOS, Linux
  and Windows (and FilmCraft's web build), pinned by SHA-256 and size, downloaded in the background by the desktop
  app (Settings, Editing apps: set up by hand, turn off), unpacked with path/link checks into `<data>/tools/craft`.
- **The edit in FilmCraft** (`craft/finish.py`): the timeline imported by `filmcraft-cli`, then ClipForge's look and
  sound made with FilmCraft commands (Motion scale, Gaussian Blur on new "Blurred background" tracks, Scale/Opacity
  keyframes, Volume keyframes, Essential Sound ducking, caption style, -14 LUFS export).
- **EffectCraft shots** (`craft/shots.py`): the animated title replaces the still title card in the edit.
- **The AI's finishing** (`craft/ai.py`): with an AI helper, FilmCraft steps (finishing tools only, checked clip ids,
  no paths, at most 40) and up to two EffectCraft shots laid over the video.
- **FilmCraft renders final videos** (`video_flow._craft_render`, setting `edit_engine` auto/filmcraft/ffmpeg): the
  built-in editor is the backup with the reason recorded; previews stay built-in.
- **FilmCraft's editor on the editor page** (`craft/web.py`, `craft/routes.py`, `components/FilmCraft.tsx`): opens
  the AI's FilmCraft edit (job `filmcraft_edit`) with only this video's files; Save in FilmCraft becomes a new version
  rendered by FilmCraft (`plan["filmcraft"]`, saves kept by SHA-256). Desktop app only.
- **Settings → Editing apps** (`components/EditingApps.tsx`), and each version says which editor made it.
- **Tests:** `tests/test_craft.py` (15, stand-in apps), `tests/test_studio_filmcraft.py` updated for the background
  tracks (14). Real apps: `scripts/craft_check.py` in `.github/workflows/filmcraft-check.yml` (macOS 15, Ubuntu).
  Results: see the PR and AI_HANDOFF.md.
- **Docs:** `docs/clipforge/CRAFT_APPS.md`.

## Finish in FilmCraft (ArtCraft's open-source editor) — 2026-11-06 (Claude Code)

Landry asked to plug the ArtCraft apps into ClipForge for editing. FilmCraft (the video editor) is first.

- **Editor page → Finish in FilmCraft:** "Open in FilmCraft" writes the current version as an OpenTimelineIO
  timeline with SRT captions, a title-card still and a README next to the video, then opens the FilmCraft you
  installed (with its command-line tool, as a ready FilmCraft project). "Show the timeline files" and "Timeline with
  media (.zip)" (portable, also in the online studio). Not installed: the files are still written and the panel
  links to getartcraft.com/apps/filmcraft. ClipForge never downloads or bundles FilmCraft.
- **The timeline** is made from the FFmpeg engine's frame map (frame-exact): clips, images, dissolves/dips as centred
  OTIO transitions, straight cuts, the title still, pictures over the video (V2), clip sound with volume and mutes
  (A1, linked), voiceover/music/effects tracks (loops repeated, overlaps on extra lanes), chapters as markers, frame
  size and rate for FilmCraft. What cannot carry over (ducking, fades, punch-ins, fill framing, blurred background,
  overlay motion, caption look, loudness leveling) is listed in the README and the panel.
- **Code:** `studio/interchange.py`, `studio/filmcraft.py`, routes `GET /api/studio/filmcraft`,
  `POST /api/studio/videos/{id}/filmcraft`, `GET /api/studio/videos/{id}/timeline.zip`, `components/FilmCraft.tsx`.
  Docs: `docs/clipforge/FILMCRAFT.md`.
- **Tests:** `tests/test_studio_filmcraft.py` (13, fast; OpenTimelineIO 0.18.1 read the file in the local run);
  `.github/workflows/filmcraft-check.yml` + `scripts/filmcraft_check.py` import and render the timeline with
  FilmCraft 0.17.1's official release on macOS 15 and Ubuntu: passed on both (PR #26, run 42185369033).
  Full fast suite: 1781 passed.
- **Not verified:** the FilmCraft window opening on a real Mac or Windows PC; FilmCraft could not be run in the cloud
  session itself (running a downloaded program there is not allowed), so it runs on GitHub's machines instead.

## Built-in AI and "Clean up the sound" (phase 1 of the smarter editor plan) — 2026-11-06 (Claude Code)

Landry asked for an AI that comes with the app and for smarter editing with better sound; after the plan (Claude Doc
in the project thread) Landry chose "Start phase 1". Draft PR from `claude/project-thread-4sg7wk` into
`claude/project-thread-x72wkd`; nothing is merged or released. Design and limits:
[docs/clipforge/BUILTIN_AI_AND_SOUND.md](docs/clipforge/BUILTIN_AI_AND_SOUND.md).

- **Built-in AI (Settings → AI helper, listed first):** one Download button; llama.cpp `llama-server` b12017 (MIT)
  with Qwen3-VL 2B (Basic), Gemma 4 E4B (Standard) or Gemma 4 26B A4B (Pro), all Apache 2.0, downloaded on first use
  from pinned releases and revisions and checked against pinned SHA-256 hashes. The level is recommended from the
  computer's memory and graphics memory. The engine runs on 127.0.0.1 with a random key, stops when idle, when
  ClipForge quits and before transcription needs the graphics card, and is shared with the Autopilot worker. It is a
  local provider (`ai_provider = "builtin"`) for clip scoring, post text and the AI editor.
- **Clean up the sound (`clean_sound`: Off, Auto, Gentle, Strong; default Auto):** mic balance (a dead or inverted
  channel is left out), rumble and 50/60 Hz hum, background noise (DeepFilterNet 3 through ONNX Runtime, a pinned 13
  MB download; a spectral noise gate when it is not available), quiet and loud passages evened out, breaths in pauses
  softened, de-esser, gentle compression and presence. Auto leaves music and sound that is mostly not speech alone.
  Used by clip renders and the full-video editor (each file cleaned once and cached); the result lines up with the
  picture to under a millisecond. Clip editor: the setting, a before/after switch at matched loudness, and a note on
  what the last render did. Full-video editor: a choice in the Sound panel.
- **New requirement:** `onnxruntime>=1.20` (Mac, Windows and Linux wheels; about 15 to 20 MB).
- **Tests run:** `tests/test_builtin_ai.py` 19 passed; `tests/test_clean_sound.py` 15 passed, plus the real-model test
  (slow) with the model files present locally; full fast suite 1,801 passed (28 slow deselected); slow suite 26 passed and 2 failed: one test measures a pure
  test tone that Auto cleaned as noise, so it now turns the cleanup off like its other processing, and both pass
- **Real engine and models on GitHub's test machines** (`builtin-ai-check.yml` run 42160482511, Basic level): Linux
  answer 2.7 s at 35.7 tokens/s, Windows 2.8 s at 22.9 tokens/s, Mac (a virtual Mac with 3 cores, 7 GB and no graphics
  access) 19.6 s at 5.0 tokens/s after a 32 s first load; all answered the scoring prompt as JSON and the picture
  question correctly. Sound cleanup of a minute of speech: 1.5 s on Linux, 6.0 s on the Mac. The pinned catalog
  matches Hugging Face and the llama.cpp release. The native Mac app built with ONNX Runtime (`macos-desktop.yml` run
  42160487116); `macos/desktop_media_smoke.py` now also runs the voice model inside the built app.
- **Not verified:** a physical Mac or graphics card (the Mac runner has no graphics access, so real Macs should be
  faster); answer quality of each level; listening tests on real recordings; the native apps with these screens.

## Released ClipForge 2026.11.05.2: smart editing and the Mac link fix — 2026-11-05 (Claude Code)

Landry asked in the project thread to merge both fixes (PR #22, PR #23) and update the website with the new versions.
Both downloads are built from `2e5238e` (PR #20's branch with PR #22 merged, plus PR #23).

- **Checks on `2e5238e`:** `macos-desktop.yml` run 42106643196: native build and bundled-app checks (including the
  FFmpeg join and Deno), 27 slow tests; the fast-suite job hung in `apt-get` and passed on rerun (1,768). Locally
  1,768 fast tests passed.
- **Mac:** release `clipforge-mac-2026-11-05-2e5238e` (publish run 42114038409), `ClipForge-Mac-Apple-Silicon.dmg`
  237,781,526 bytes, SHA-256 `14c78abe948634cc92a7c786aac0916534ef0f88cc52e7b5e9cc55af29c2169f` (about 45 MB larger:
  Deno for YouTube). Unsigned personal preview, prerelease.
- **Windows:** `ClipForge-Windows-Setup.zip` at `raw/d60445f` on `claude/clipforge-downloads`, 47,042,861 bytes,
  SHA-256 `531e9ef012eb27705f7ed66b82325c9f2b048b854d4206c260541e9e0d63eb0d`; 77 launcher tests, all 709 app files
  equal the tree; Windows setup check run 42109581700 installed it over the 6ecdafc release (settings kept).
- **Download page:** `gh-pages` `65f026a` (previous `138c4f7`, Pages run 42114472648), ClipForge 2026.11.05.2; `build.py --check` and
  `--verify` passed (all eight listed files). Release notes in `.github/scripts/publish_personal_mac.py` name the
  new features (`d45bb0d`).
- **Not verified:** a real YouTube download, real AI models and keys, Windows 10/11 desktops, physical Macs.

## Smarter video editing and a free AI helper — 2026-11-05 (Claude Code)

- **Make a YouTube video → "How much should ClipForge edit?"** New default "Edit it for me": cuts long pauses and
  lone "um"/"uh" (checked in the sound, never inside a word), leaves out an earlier take of a line said again and a
  stumble said twice, fits the length you ask for (the opening, ending and must-keep words stay), shows your images
  over the video when their name is said, adds free background music that dips under speech and soft sound effects.
  "Fast-paced" cuts shorter pauses and zooms in a little on every other cut. "Keep my clips as they are" is the old
  rough cut. Everything left out stays in the sequence, switched off, so Put back restores it.
- **Free music and sound effects** are made on your computer by ClipForge (no downloads, no licence questions) and
  appear in Your media like any file.
- **Editor:** an "Edit it for me" panel (what was done, Edit it again with other choices as a version you can undo,
  YouTube chapters to copy), "Pictures over the video" (push-in or still, length, remove, add), a Pictures row on the
  timeline, and per-clip zoom and straight-cut joins.
- **Settings → AI helper (optional, free):** Ollama on this computer (download a recommended model, or import a
  .gguf file you already have), LM Studio, or a free key for Google Gemini, Groq or OpenRouter's free models; the
  Claude API is listed as paid. The helper reads only the words said, as text, and suggests what to leave out,
  where a picture helps, chapter titles and the music's mood; its answers are checked and limited. Without it the
  built-in editor decides alone.
- **Fixed:** captions dropped a word whose measured end ran into a cut pause (common with speech models).
- Details: docs/clipforge/SMART_EDITING.md.

## Mac: YouTube video links work again — 2026-11-05 (Claude Code)

- **Bug (released Mac build 2026.11.05):** a YouTube link ended with "No downloadable video was found on this page".
  YouTube serves picture and sound separately and yt-dlp joins them with FFmpeg, but yt-dlp only looked on the PATH.
  The Mac app keeps FFmpeg in `Contents/Helpers` (CLIPFOUNDRY_FFMPEG), and a Finder-opened app's PATH has no FFmpeg.
  yt-dlp's "ffmpeg is not installed" error matched no rule and was shown as "No video found".
- **Fix:** `media_import.public_extractor` passes `ffmpeg_location`, found the same way the renderer finds FFmpeg.
  A new reason, `tools_missing` ("Video tools missing"), names a really missing FFmpeg. The Mac app now installs
  `yt-dlp[default,deno]`: Deno (sandboxed by yt-dlp) and yt-dlp-ejs give yt-dlp its full YouTube support. Without a
  JavaScript runtime it asks only one YouTube player.
- **Tests run:** a new offline test with separate picture and sound and FFmpeg off the PATH, which failed on the
  released code and passes now. Local fast suite: 1,751 passed. A race in
  `test_unavailable_link_fails_readably_then_retry_succeeds_once` was fixed: it checked the job status before the job
  runner marked it done. The native Mac build (run 42068752230) passed, including the new bundled-app checks: the
  separate streams were joined by the bundled FFmpeg, and yt-dlp found the bundled Deno 2.9.8, which had no file access.
- **Not verified:** a real YouTube download. This environment can't reach YouTube, and GitHub's Mac runners get
  YouTube's "confirm you're not a bot" page for every player. No new Mac release was made (PR #22, not merged).

## Studio upgrade released: Mac and Windows downloads and the download page — 2026-11-05 (Claude Code)

- **Download page** (https://landryschreiner33-coder.github.io/ClipForge-AI./download/, `gh-pages` `138c4f7`):
  ClipForge 2026.11.05 for Windows and Mac, with exact sizes and SHA-256 fingerprints. The page is dark only like the
  app, shows the new
  studio (screenshots from a throwaway copy with made-up videos), explains video links, the editor, example videos,
  Find media and the Brain map, no longer mentions automatic video discovery, adds an FFmpeg step for Windows, a
  Questions section and a Support link. Yesterday's downloads stay under Older versions.
- **Mac:** unsigned personal preview DMG (Apple silicon, macOS 15+), the unchanged file from the tested build. macOS
  asks once before opening it (System Settings › Privacy & Security › Open Anyway).
- **Windows:** the setup ZIP now installs the upgrade, and its window says ClipForge. It was installed on a GitHub
  Windows runner over yesterday's version: your data folder and settings were kept, and it closed and reopened
  cleanly.
- Not verified: a real Mac or Windows PC, Windows security acceptance, processing a video on Windows, real uploads.
  The ChatGPT Sites page was not changed.

## Studio upgrade: the ClipForge name in the apps, and the full checks — 2026-11-05 (Claude Code)

- The Mac app's window, menus (About, Hide, Quit, Help), messages, Finder name and installer volume, the Mac and
  Windows start-up windows and the phone page now say **ClipForge**. Folder names, the app's internal id and saved
  passwords stay where they were, so nothing moves or has to be signed in again.
- **Fixed** after the full browser checks: the office's simple map (shown when the new graphics cannot load) froze
  with no robots as soon as one robot was queued; the Brain's saved-items list was read out as plain list items
  instead of buttons; and Missions said clips "can upload automatically" even when every post waits for your review.
- Checks actually run: fast suite 1,749 passed and slow suite 26 passed (audio, uploads, renders, restarts), on this
  machine and on GitHub's Linux runner. The Mac app was built, started and checked on a GitHub Mac runner
  (development copy, not notarized, not a release). Browser checks: read-only suite 52 passed, 7 failed; sandbox
  suite 84 passed, 2 failed; every remaining failure also fails on the commit this work started from. Browser checks
  that described screens this upgrade replaced were rewritten for the new screens; checks for the retired discovery
  setup screens are no longer run, and a new check makes sure those screens stay gone.
- Not verified: Windows packaging (no Windows runner here), installing or updating from the Mac installer, a screen
  reader pass.

## Studio upgrade: one Brain map of everything it holds — 2026-11-05 (Claude Code)

- Brain → Notes shows **styles, skills, example videos and the projects that used them** next to your notes. A line
  means something really happened: a project's recorded guidance used that style, skill, example or note, or a
  style was learned from that example video. Nothing is guessed.
- Pick any dot, or any item in the list beside the map (arrow keys move through it), to see what it changes, whether
  it is on, its revision, where it came from and which projects used it, with links to open them.
- **Save a style** is now a real form (on the Brain toolbar and the Styles tab): a name, the project types and the
  editing choices to remember.
- The map no longer glows on its own. When a project has just used something, that item shows "Just used" and a
  few rings, which stop off screen and with reduced motion. Busy maps show fewer labels until you zoom in.
- Tests actually run: `tests/test_brain_map.py` (2: links only from recorded use and provenance, other workspaces
  never shown, older snapshots read from their decisions, an example deleted with its style kept), with the guidance,
  example-video and rename suites (28 passed). Browser checks at 1440, 390 and 320 px on synthetic data: no
  sideways scroll, no console errors, list arrow keys, inspector details, Save a style, and no animation with
  reduced motion.
- Not built: clustering beyond showing 36 per collection on the map (the rest are listed), a virtualized list.

## Studio upgrade: dark only, Customize studio, keyboard and small screens — 2026-11-05 (Claude Code)

- ClipForge is **dark only**. The Light theme and the System choice are gone; a saved Light or System choice is
  dropped and every other choice (accent, spacing, clip mode) is kept. The saved colours are applied before the
  first paint, so nothing flashes light.
- **Customize studio** (the sliders button in the top bar, the Studio page, or Settings → Appearance) previews
  every change live and keeps it only on Save: four dark palettes (Studio, Midnight, Graphite, Plum), six accents
  including a new teal, spacing, text size (standard, large, larger), motion, office animation (Full, Calm, Low
  power), which Studio panels show and in what order (with presets and Move up/down buttons), the editor's panels,
  a compact or expanded office and pinned projects. Cancel or Escape puts everything back; Reset to defaults
  previews the defaults until saved. The panel says where each choice is kept.
- Pin a project from its card on the Studio page; pinned projects get their own section.
- The office stops drawing while it is scrolled off screen; Calm drops the lounge activities and Low power keeps
  the robots still. Office text follows the chosen text size.
- Keyboard: the Make menu now opens on its first item, moves with arrow keys and closes with Escape back to the
  button; the colour choices move with arrow keys.
- Fixed: the editor crashed on videos made before ClipForge recorded their guidance; a full video starting with a
  sound file made the Studio page ask for a picture that does not exist; "Follow system" was cut off in the
  office's Animations menu at larger text.
- Tests actually run: fast suite 1,747 passed on `61492d0`. New: `tests/test_theme_contrast.py` (every palette and accent against WCAG
  contrast, and no light theme), the Light/System migration and pinned projects in `tests/test_studio_prefs.py`,
  the full-video picture in `tests/test_studio_uploads.py`. Browser checks on a disposable data folder: 16 screens
  at 320, 390, 768, 1024 and 1440 px with standard and larger text (no sideways scroll, no console errors), and
  keyboard-only runs at 320, 390 and 1440 px with reduced motion (skip link, focus rings, Customize studio, Make
  menu, a confirm dialog, the office list, the editor; no endless animation with reduced motion).
- Not built: robot colour or badge variants (names only); separate page designs for phone, tablet and desktop
  (panel order and visibility differ per device class). Not run: a screen reader pass.

## Studio upgrade: Studio and the office in one place, truthful robots, rename every robot — 2026-11-05 (Claude Code)

- The app opens on **Studio**: Make clips, Make a YouTube video and Make clips from a video link; **Needs you** only
  when something has a fix (a stopped project, an editor question or proposal waiting for you, Autopilot's own
  list); the **current project** with its picture, the step it is really at, a Working, Queued or Waiting for you
  label, progress only when measured and the robots on it; the robot office (Expand opens it at `#/office`); recent
  projects and publishing. "Ready for your next video" when nothing runs. Navigation is Studio, Projects, Brain,
  Publishing, Accounts, Settings; older addresses redirect.
- The robots now show **your own work**, not only Autopilot's: Make clips projects by stage, clip and version
  renders, video links, rough cuts and renders, Find media downloads, example-video analysis and editor requests,
  each from its recorded row and only in your workspace. Queued is its own state. Paused shows only when Autopilot
  was started and then stopped, and never hides your own work. A failure shows for 30 minutes, then moves to the
  robot's log.
- Rooms follow the workflow: Intake, Media research, Story & analysis, Editing, Sound & captions, Brain, Quality &
  export, Publishing, Control room, Lounge. The 25 robots keep their ids; old room addresses still open the room
  that replaced them.
- Each robot's details show a **Log** (its Autopilot steps plus your work that ended in the last day), and the
  reason under a task now says what it is (Waiting for you, Queued, Waiting, Stopped, Blocked) instead of always
  "Blocked".
- **Every robot can be renamed**, the Brain Core included, from its details or the Team page; Reset all names asks
  first. Names reach the map, the list, accessible labels, handoff notes, activity and the Studio's team chips.
  Renaming keeps the open robot.
- Fixed: a Make clips project still downloading from a link made its picture request fail with a server error
  every few seconds on the Studio page.
- Tests actually run: fast suite 1,733 passed on `c80bcb8`. New: `tests/test_office_owner_work.py` (15),
  renaming and reset-all in `tests/test_studio_prefs.py`, the link-project picture in `tests/test_studio_uploads.py`;
  office tests updated for the new rooms and the queued state. Browser checks at 1440 px and 390 px on a disposable
  data folder: Studio, the office map and list, renaming from the details and the Team page, reset all with
  confirmation, waiting for you, the log; no sideways scroll and no console errors.
- Not built: separate states for waiting on a platform and waiting on a retry timer (the reason says which), and
  your own work in the shared activity feed (it is in each robot's log).

## Studio upgrade: tell the editor what to change — 2026-11-05 (Claude Code)

- Editor → Tell the editor what to change: a request becomes a proposal you check before anything changes. It lists
  each change in the editor's clip numbers (new order, trims, removals, captions, music dip, length) and is applied
  only with Apply, as a new version that Undo takes back. A proposal made before another edit is refused as out of
  date.
- Understood without AI: removing the silence at the start, shortening the introduction, moving or removing a part
  named by what is said in it or by its number ("move the summit part before lunch", "move clips 3 to 4 to the
  start"), dipping music further under speech, music level, caption size, position and on/off, and transitions.
  When a part comes up in several places, one short question offers the choices; no time is guessed.
- Anything else goes to the AI service chosen in Settings → AI, only when one is set up, as text: the clip list with
  ids and times, the words said, the current settings, the project's Brain choices and the request. Never the video,
  sound, file paths or keys. The screen says what was sent and whether it stays on the computer. The answer must be
  operations from a fixed list or one question; it is checked exactly like a manual edit.
- Limits: a timeout (60 s by default), cancel, a daily limit (40 per workspace by default; both in Settings → AI), a
  cache for the same request on the same version, and no automatic retries. A restart while waiting is reported
  and the request is not sent again.
- Tests actually run: fast suite 1,716 passed; new `test_studio_edit_requests.py` (14 fast, with a fake AI
  service) passes. The panel and settings were checked in a browser at 1440 px and 390 px (no sideways scroll, no
  console errors).
- Not verified: answers from a real model (no AI service is reachable from this environment). Not built: AI story
  segmentation and outlines, and a preview render of a proposal before Apply.

## Studio upgrade: Find media with license records and credits — 2026-11-05 (Claude Code)

- Editor → Find media: Images, Footage/B-roll, Music and Sound effects from Openverse, Wikimedia Commons and Pexels,
  searched together. Each card shows a preview (served through ClipForge, never loaded straight from the source),
  length or size, creator, source, license and restrictions; filters for shape, length and license. Picking a result
  copies the file into Your media; adding it to the edit is a separate step.
- Imports are durable, cancelable jobs. Downloads go through `netguard` (address pinned, redirects re-checked), with
  a size cap per kind, a content-type allow list and an FFmpeg decode check. Each file gets a provenance record
  (source, item, creator, license and version, terms, credit, retrieval time, hash) in `asset_sources`, separate from
  the Brain. Switching a source off or the source removing the item never breaks media already imported.
- Terms: unknown or unfit terms are labelled; importing one needs the owner's written reason and holds automatic
  posting for that render. Titles and descriptions from sources are inert text.
- Credits: an editable list per project, carried into the render info, a `credits.txt` beside each final render,
  and the description of automatic uploads. A credit the license requires must keep the creator and license.
- Settings → Media sources: on/off per source, Pexels key sealed with the other secrets and tested without showing
  it, limits and terms links. A 429 pauses only that source for its Retry-After time; searches are cached.
- Supporting media per project (Make a video, and the editor): off, suggest for review (default), or add
  automatically as one undoable version (images after the clip where a repeated word is said; music looped and
  ducked). Make a video also has a Music choice: none, your own, or find some.
- Fixed: a thumbnail that FFmpeg failed to write was recorded anyway and its route returned 500; it is now skipped
  and the route returns 404.
- Tests actually run: fast suite 1,702 passed; new `test_studio_media_sources.py` (15 fast) passes; new slow
  `test_studio_media_render.py` passes (rain sound and landscape image found, auditioned, imported, placed,
  reopened offline with the source off, rendered with timing and credit intact).
- Not verified: the live Openverse, Wikimedia Commons and Pexels APIs (unreachable from this environment; tests
  use recorded responses shaped like their documentation), Content ID behaviour of any imported file.

## Studio upgrade: example videos measured and applied — 2026-11-05 (Claude Code)

- Brain → Example videos: upload an example, say what you like (overall, pacing, captions, framing, sound), pick an
  optional range, mark it as one to avoid, and choose where it applies (only when chosen, every project, or some
  project types). A durable, cancelable job measures it (`studio/reference_analysis.py`, analyzer `measure-1`):
  cuts, dissolves and fades from 10 fps frame comparison; framing and caption band, position and size from stills;
  speech, music level and the music dip under speech from three sound bands. Each observation is labelled measured
  or estimate and links to the times it came from. No AI model watches or hears the video, and the screen says so.
- Analyses are cached by file hash, ranges, analyzer and speech source; Reanalyze adds a revision. Supported choices
  (shot length, caption position and size, music dip depth, aspect, frame rate, framing) can be corrected and saved
  as an Example style with provenance (example, analysis revision, method, corrections).
- Guidance precedence: project choice, then an example chosen for this project, then the style, skills, examples set
  to apply broadly, Brain notes, Settings. Make clips and Make a video offer "Use an example" and show which example
  (and which style revision) each choice came from. The example's own footage and sound never enter a project.
- Fixed: Make a video used to send its default answers as project choices, so styles, skills and examples never
  changed aspect, feel, captions, caption size or position, or frame rate.
- Tests actually run: fast suite 1,687 passed; new `test_studio_reference.py` (15 fast) passes; new slow
  `test_studio_reference_render.py` passes (an example with 1.5 s shots, lower-third captions and a 12 dB music dip
  is measured, saved, applied to a new project, and the rendered dip is within 3 dB of the measured value).
- Not verified: real Whisper transcripts (fixture transcripts used), examples longer than a few minutes on a real
  device, a vision-model pass (not built; the measurements do not read on-screen text or recognise objects).

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
