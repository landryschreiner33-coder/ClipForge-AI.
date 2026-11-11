# AI handoff

## ClipForge AI becomes a real assistant: conversation, actions, helper agents — 2026-11-08 (Claude Code, cloud session)

**Plain-English summary:** Landry asked for a built-in AI to actually talk to like a real AI, and for agents that work
alongside it. ClipForge AI now holds a real conversation in both chats (on each video, and Brain → Talk): it reads the
conversation so far, knows Landry's projects and memories and its know-how, writes its answer word by word (Stop keeps
what it wrote), and does things in ClipForge with twelve tools. Looking things up and making new things (a memory, a
proposed change, a helper's work) happen at once; renaming, forgetting and deleting only happen when Landry presses OK
on the card it shows. Helper agents (eight ready-made, or Landry's own, in Brain → Agents) are specialists that
ClipForge AI hands jobs to, that Landry talks to with "@Name", and that give the new-video planner short notes.
Without a model the old rules still answer, and the chat offers the built-in model in one press.

- **Branch / PR:** `claude/project-thread-sa113l` from the release line at 95a70e0 (PR #33 merged), PR #37. Landry's
  standing OK (Nov 9): merge finished work into the release line once its checks pass; no release without an explicit
  OK. A safety and robustness pass followed an independent review (13 problems, each reproduced first), and a second
  pass followed a second review of those fixes (15 more; AI_CHANGELOG.md, "Safety and robustness pass" and "Second
  review pass").
- **Design and limits:** [docs/clipforge/CLIPFORGE_AI.md](docs/clipforge/CLIPFORGE_AI.md), "The assistant",
  "Actions", "Helper agents", "API", "Not done yet"; [AI_CHANGELOG.md](AI_CHANGELOG.md).
- **Privacy page:** `docs/legal/privacy.html` has a "ClipForge AI" part (what its chats, memories, helpers, the change
  requests made in a video's chat and the online request records keep, and until when) and says which features send text
  to the AI helper you choose and what a conversation sends ("An AI service you choose", NVIDIA's row: web addresses
  starting with http://, https:// or www. and email addresses removed from everything, the size limit on each request's
  words), and that downloading the built-in model contacts GitHub and Hugging Face. Since the merge with PR #35 it says
  that deleting a project removes its chat, the memories kept for it alone and a video's change requests, while the
  record of each request sent to an online AI (the editor's change requests too) stays for the daily limit. The public
  website (gh-pages) is not updated: that needs Landry's OK.
- **Code:** new `clipfoundry/brain/assistant.py`, `tools.py`, `toolbox.py`, `agents.py`, `allowance.py` (the daily
  limit, per request); changed `brain/chat.py`,
  `routes.py`, `memories.py` (use place `agent`, `twin()`), `db.py` (table `brain_agents`, role `agent`), `api.py`,
  `pipeline/llm.py` (`converse`; the GPU wait counts in its time; `is_local` knows every loopback address and
  Ollama cloud models), `builtin_ai.py` (`converse`, never idle while answering, loading counts in the time,
  `answer_floor`, `Server.warm` under the GPU lock, one spawner thread on Linux), `gpu.py`,
  `studio/edit_requests.py` (the shared daily count for an online AI, its own limit for a model on this computer),
  `studio/ai_editor.py` (asks `llm.is_local`), `studio/link_import.py` (titles stored as one line),
  `pages/Settings.tsx` ("AI requests a day");
  `frontend/src/components/ClipForgeAI.tsx`, `AgentsTab.tsx` (new), `pages/Brain.tsx`, `brain.ts`,
  `components/AiHelperSettings.tsx`, `styles.css`; `frontend/dist` rebuilt; `tests/test_clipforge_ai_assistant.py`,
  `test_clipforge_ai_agents.py`, `test_clipforge_ai_safety.py` (new), `test_llm_converse.py`, `fake_model.py`
  (new), `test_clipforge_ai_chat.py`,
  `test_clipforge_ai_knowhow.py`, `test_builtin_ai.py`, `fake_llama_server.py`; `scripts/assistant_check.py` and
  `.github/workflows/assistant-check.yml` (new: the real built-in model in a conversation).
- **The contract with the other threads** (other branches call these; keep the names and shapes):
  - **The new-video planner thread** answers a draft video's chat with `brain.chat.route(applies, handle)` (its
    messages have `data.tool` "plan", which the page shows like "talk"), registers `make_youtube_video` with
    `tools.register(tools.Tool(...))` (its `Result.data` has `links` `[{label, href: "#/create/video?idea=…"}]`), asks
    the helpers with `agents.consult(ws, task, *, context="", agent_ids=None, where="plans", ref_id="",
    budget_s=60.0)` (`ref_id` is recorded on the online requests it counts; it returns `[]` when today's online
    requests are used up and while the built-in model is not loaded yet, which then starts loading), and speaks as
    ClipForge AI with
    `assistant.persona()`, `assistant.history(chat_id, budget_chars=3000, *, as_json=False, before="")`,
    `assistant.app_context(ws, project_id="", budget_chars=2000)`, `assistant.ready(settings=None)` and
    `llm.converse(settings, messages, *, system, task, json_object, json_schema, max_tokens, timeout, temperature,
    num_ctx, on_text, cancel)`. Also public: `tools.Tool`, `tools.Result`, `tools.ToolError`,
    `agents.list_(ws, enabled_only=False)`, `agents.run(ws, agent_id, task, …, owner_text="")`, and
    `allowance.take(ws, settings, task, ref="")` before each request the planner sends to an online model itself
    (it raises `allowance.Reached` when today's limit is reached; a model on the computer is never counted). A part
    counts only through its `ai_usage` rows (the editor's change requests from before it wrote its own are the one
    exception): `allowance.counted(ws, settings, write)` runs a `write` that must itself write that row with the
    part's own (the check and both rows are one step under one lock). The editor's change requests use
    `allowance.editor_request`, which writes their `edit_requests` row and their own `ai_usage` row (task
    `edit_request`), so deleting a video does not give the day's requests back. A video counts as
    being planned (its chat and links open the setup page) only when it is a draft with its setup and the full_video
    workflow, the same rule as the planner's `video_setup.is_draft`.
  - **Deleting projects** (PR #35, merged in) is `clipfoundry/studio/project_delete.py`: `plan(ws, project_id,
    kind)` (`goes`, `stays`, `blocked`, `working`, `as_of`, `removes`) and `delete(ws, project_id, kind, *, wait,
    as_of, removes)`, which raises `DeleteError` (`code`: `not_found`, `blocked`, `stopping`, `changed`, `kind`).
    `delete_project` calls exactly these: the card keeps the plan's `as_of` and `removes` (what it listed beyond the
    project: media files, the copy of the video it was made from, planned posts, and as `kept` the files it said
    stay; internal arguments: `"internal": True` in the schema, hidden from the model,
    kept only from the button's saved arguments) and OK sends them back
    with `wait=10.0`, so it never deletes more than the card listed. `stopping` keeps the card for another press;
    `blocked` (Autopilot or a post started since) and `changed` (it would now remove more) end it, and asking again
    shows a card with what goes then; `not_found` says the project was deleted already. Deleting a project also
    deletes its chat (`chat.decide` answers `gone`). `test_clipforge_ai_assistant.py` tests the card with the real module
    and the engine's corners with a stand-in.
  - Chat messages keep the `brain_chat_messages` table and its columns; roles are `owner`, `ai` and `agent`;
    `data.tool` values include "talk" (the assistant) and "plan" (the planner).
- **Verify:** `python -m pytest -q tests/test_clipforge_ai_assistant.py tests/test_clipforge_ai_agents.py
  tests/test_clipforge_ai_safety.py tests/test_llm_converse.py tests/test_clipforge_ai_chat.py
  tests/test_clipforge_ai_knowhow.py tests/test_builtin_ai.py`, then `python -m pytest -q tests -m "not slow"` and
  `python -m pytest -q -m slow`; `cd frontend && npm run build`; on a
  runner, the `assistant-check.yml` workflow (the real built-in model on Linux and Mac; it runs when a push to this
  branch changes the AI's code, or by hand; its job summary has a table of every turn, and the run keeps the JSON
  report for 14 days; `python scripts/assistant_check.py --fake --out report.json` checks the script itself without
  a download). On Landry's computer: set up the built-in model from the chat's card; in Brain → Talk ask "What
  projects do I have?" and for hook ideas; say "From now on, never put music under my intros." (a memory with
  Undo); ask it to
  rename a project and press OK on the card; add the Critic in Brain → Agents and write "@Critic review my last
  video"; press Stop on a long answer; in a video's chat ask "What would make this video better?".
- **Judgement calls to know about:** the built-in model and Ollama get the smaller budgets (an 8,192-token context);
  change and delete tools never run on the model's word, even after a "yes" in the conversation: only the card's OK
  runs them, and a change or delete that cannot be offered (or is blocked) is shown with its reason and is no reason
  to ask the model again (the Basic model, asked again, said a delete it could not offer was done); beside a tool the
  model does read, it reads that it was not done, and the next turns read it in the conversation (`history`);
  "remember: …" and an exact "forget …" skip the model (forgetting every memory that says the words after "forget",
  its twins too, `memories.forget_words`, or those after a leading "my", "that", "the" or "about" only when no memory
  says them all; "forget", "remember" and "note" are whole words; the Forget card names each memory, at most 16, and
  its OK forgets only those, each only while it still says the card's words, and never looks again: a card saved by
  an earlier build forgets only the memory it named), while "I like …" and "always …" now go to the conversation,
  where the model saves lasting preferences with `remember` (and ClipForge keeps a plainly said one itself when a
  small model forgets); `remember` saves at once only the owner's own words from this message and never changes a
  memory the owner already has (anything else is a "Remember “…”?" card); a video's chat still proposes the changes
  the editor's rules fully understand without the model; one answer at a time per chat, and at most two being written
  in the whole app; helpers run one after another (inside an answer and in `consult`); every request to an online
  model counts against the daily limit, `consult` notes and the new-video planner's requests included (since the merge
  with PR #38 the planner takes each request from the same allowance: `allowance.take`, task `video_plan`, in
  `video_setup._take`, and `video_setup.limit_reached` asks `allowance.reached`); Tidy (Brain → Memory) is one step
  under the database's write lock and merges only twins kept for the same videos and switched on or off alike, so
  tidying never changes what ClipForge AI follows; what the owner does meanwhile waits for it and is never undone by
  it (a confirmation or an edit of a memory Tidy removed answers "Memory not found."; the same words said again are
  kept, because `remember`, an edit, a confirmation and a brain file write only over the revision they read,
  `memories._write_over`, so no two states of a memory share a revision); a brain file's newer revision applies
  also beside a twin; twins Tidy keeps apart are read once in a prompt (the best of those that fit the question)
  and left to the owner (the brain check names those switched on); since the merge with PR #42, the delete's last
  look counts a copy handed out again only within `uploads.REUSE_HOLD_S` (an hour,
  `project_delete._hand_out_since`), so a delete card that waited for days keeps a file nothing names only when it
  was handed out within the hour before OK; Find media's automatic round puts each pick in the video's media as it
  is imported, so it names its copy at once.
- **Not done:** the real built-in model's answers could not be run here (the model hub is blocked): the
  `assistant-check.yml` workflow runs them on GitHub's Linux and Mac machines with the Basic level (every must-check
  passed on d02bb25 and 56aae46; the small model rarely uses its tools itself, so ClipForge's safety nets do the
  remembering; PR #37 links the run on the final version). The Standard level a Mac with 16 GB or more gets can be
  run by hand on the Linux machine (`level: standard`, `machines: linux`; without a graphics chip its answers get
  900 s there). Landry's computer was not tested; web
  research for the Researcher, a model per helper, helpers in parallel, pictures in the chat, voice (CLIPFORGE_AI.md,
  "Not done yet").
- **Waiting on Landry:** a try of the chat and the helpers on Landry's computer; the release (explicit OK).

## Leftover files and upload races after deleting projects — 2026-11-11 (Claude Code, cloud session)

**Plain-English summary:** follow-ups from the review of deleting projects. Deleting an animated short now also
removes the pictures and clips it made and then replaced, and the original files the local makers made for it. Two
copies of the same file finishing their upload at the same moment no longer fail. ClipForge now remembers which
project or example each upload (and each file added from this computer) was for, so a project's own later upload of
a file no longer keeps that file forever after the project is deleted, while a file another page has just added is
still kept for that page. A planning answer that arrives just as its video is deleted no longer makes an empty chat.

- **Branch / PR:** `claude/project-thread-h05xs8`, built on PR #35 (deleting projects), into
  `claude/project-thread-x72wkd`, merged under Landry's standing word to merge finished work. Not released: a release
  still needs Landry's explicit OK.
- **Code:** `clipfoundry/makers/shorts.py` (`short_files`, `_tidy_files`, `_drop`, `_named`, makers' originals taken
  in, `update_scene` `upload_ids`), `makers/local_engines.py` / `pictures.py` / `voice.py`, `engines/makers.py`,
  `studio/uploads.py` (`_content_lock`, `_reuse`, `_again`, `_hand_out`, `taken`), `studio/project_delete.py`
  (`_added_again`, `_handed_out`, the recheck inside the delete, `_maker_originals`), `studio/reference.py`
  (`_drop_file`, `create(upload_ids=)`), `studio/video_flow.py`, `clips_flow.py`, `video_setup.py`, `routes.py`,
  `local_routes.py`, `brain/chat.py` (`open_chat(create=False)`), `db.py` (`short_files`, `uploads.taken`,
  `assets.reused_at`); frontend `studio.ts`, `studioParts.tsx` (`FileDrop.onUploaded`, `useUploadsByFile`),
  `MakeClips`, `MakeVideo`, `VideoReview`, `ShortScenes`, `ExampleVideos`; `frontend/dist` rebuilt. Details:
  [AI_CHANGELOG.md](AI_CHANGELOG.md).
- **For other work:** a page that makes a project, an example or a scene picture from the owner's files must send
  `upload_ids` (every upload and link it made of those files; `uploadFile` and the link answer carry `upload_id`), or
  deleting that project keeps the files as if another page had them (a project made since uploads are recorded owns
  only the uploads sent with it). ClipForge AI's tools that make a project from an uploaded file should pass the
  upload ids they know. A new kind of owner (not a project or
  an example) that takes uploads passes its own id to `uploads.taken`. Code that hands out a stored file again must
  go through `uploads._reuse` (the mark a running delete and a short's tidy look at). A new place that stores files
  for a short records them in `short_files`.
- **Verify:** `python -m pytest -q tests/test_studio_uploads_taken.py tests/test_studio_shorts_tidy.py
  tests/test_studio_project_delete.py tests/test_studio_local_files.py tests/test_studio_reference.py`; the fast and
  slow suites; `cd frontend && npm run build`.
- **Not done:** Landry's Mac and a real Windows PC; real local makers (ComfyUI, the voice engine) are stand-ins in
  the tests. Projects and examples made before this change took no uploads and keep the older rules.
- **Waiting on Landry:** the release (explicit OK).

## Deleting projects — 2026-11-10 (Claude Code, cloud session)

**Plain-English summary:** Landry asked to be able to delete projects. Every card on the Projects page now has a
trash button. It opens a window that lists exactly what will be deleted for good and what stays, and nothing happens
until "Delete project" is pressed. Deleting removes what ClipForge keeps only for that project (its clips or edit
history, renders, its own copy of the video when nothing else uses it, its ClipForge AI chat and the notes kept only
for it, planned posts not yet sent). The owner's own files, media another project uses, anything already posted and
what ClipForge AI learned for all videos stay. Work running on the project is stopped first; while Autopilot or a
post is busy with it, or the video is still being copied in, the window says why it has to wait. A file that is open
in another program (Windows) is deleted the next time ClipForge starts.

- **Branch / PR:** `claude/project-thread-8i3krg` from the release line at 95a70e0 (story clips, PR #40, animated
  shorts, PR #36, the local makers, PR #39, the safety follow-ups, PR #41, and Make a YouTube video's planning,
  PR #38, merged in on top), PR #35 into `claude/project-thread-x72wkd`,
  merged under Landry's standing word to merge finished work.
  Not released: a release still needs Landry's explicit OK.
- **Code:** new `clipfoundry/studio/project_delete.py`, `frontend/src/components/DeleteProject.tsx` / `.css`,
  `tests/test_studio_project_delete.py`; changed `clipfoundry/api.py` (router, `DELETE /api/projects/{id}` with the
  `from_this_computer` guard, `finish_later()` at start), `frontend/src/pages/Projects.tsx`, `Studio.tsx`
  (`LibraryCard` `onDelete`), `components/libParts.tsx`, `prefs.tsx` (`forgetPin`), `e2e/tests/library.spec.ts`,
  `tests/test_integration.py` (the page's header on its delete); `frontend/dist` rebuilt. Details:
  [AI_CHANGELOG.md](AI_CHANGELOG.md).
- **For other work:** a table that belongs to one project goes in `VIDEO_TABLES` or `CLIPS_TABLES` (a listed table that
  does not exist yet is skipped). A new place that keeps asset ids must be read by `_used_elsewhere` (and by
  `_video_asset_ids` when it names a video's own files, as an animated short's scenes do), or deleting another
  project can remove a file it still needs. Work a delete cannot see (a thread, not a studio job) must re-check that
  its project still exists before it writes anything for it: the planning answer (`video_setup._think`) opens the
  project's chat with `open_chat`, which makes a new empty chat if the delete lands between its two reads. ClipForge AI's delete tool calls `plan()` and `delete()` (pass the
  plan's `as_of` to `delete` when a person read the plan first, and its `removes` when the confirmation can wait
  long, as ClipForge AI's card can: then nothing more than it listed is deleted, or nothing, code `changed`);
  deleting from a project's own chat deletes that chat too. A new kind of file ClipForge makes for one project should be recorded where `_video_asset_ids` reads it,
  or it stays after the project is deleted.
- **Verify:** `python -m pytest -q tests/test_studio_project_delete.py`; the fast and slow suites; `cd frontend && npm
  run build`; in the app, delete a full video and a clips project from Projects and read the window first.
- **Not done:** a real Windows PC check (read-only and in-use files are simulated); a Delete action on a full video's
  own page (the Projects page has it). Deleting only works in
  the browser on the computer that runs ClipForge (like Autopilot and memories), not from another device on the
  network. A file used where it is and added again for a page that has not saved it yet is not protected the way a
  re-upload is (only ClipForge's prepared data for it goes; the owner's file never does). Passed on to the shorts,
  makers and upload code: scene files no scene or saved version names any more stay after a short is deleted; the
  makers' originals in engines/made stay (the window says so); two identical uploads finishing at the same moment
  give an error and leave a stray copy; a project's own later upload of a file ClipForge already had counts as
  "added again", so it is left behind (needs a record of which project took an upload); the planning answer's
  `open_chat` race above (at most one empty chat row). Known limit: the same file
  dropped on two pages at the very same moment shares one upload, so deleting the project made on one page can
  remove the file the other page is about to use (dropping it again fixes it).
- **Waiting on Landry:** the release (explicit OK); a try on a real Windows PC and on Landry's Mac.

## Make a YouTube video: plan it with ClipForge AI — 2026-11-08, review fixes 2026-11-10 (Claude Code, cloud session)

**Plain-English summary:** Landry asked for the YouTube video setup to work like this: drop in your stuff, tell the AI
your idea and plan, and it can ask questions or not. Make a YouTube video is now two pages. On the first you drop in
your videos, pictures and sounds (in the order they should play), tell ClipForge AI your idea in your own words, and
choose "Ask me questions" or "Just do it". On the second you talk it through: ClipForge AI answers with a plan you can
read (the name, what it is, who it is for, length, shape, feel, how it opens, the story in order, what to keep and cut,
music, captions…), asks at most three short questions with quick answers when you chose questions, and changes the
plan as you keep talking or as you change any line by hand. "Build my video", or "Just do it" at any point, edits the
video from the plan: the brief, the opening you asked for, ClipForge AI's edit, fitting to length and the file order
all follow it. The plan stays on the editor page, where changing it edits again as a new version. A video being
planned waits in Projects as a draft, so leaving the page loses nothing.

- **Branch / PR:** `claude/project-thread-2wwa4c`, PR #38 into `claude/project-thread-x72wkd` (the release line,
  merged in again on Nov 9 with PR #36 and PR #40). Fixes from two reviews on Nov 10 (see AI_CHANGELOG.md): the
  built-in rules' reading rewritten, merging that keeps what a stopped message said and every hand edit, Undo and
  failed or canceled plan changes that bring back what the next edit uses, sounds changed by hand that stay, and the
  pages' guards before you leave or build. Landry's standing word (Nov 9) is to merge finished work into the release
  line; releases still need an explicit OK. It works with
  and without the assistant's PR #37 (`claude/project-thread-sa113l`): merged in a scratch copy on Nov 10, only
  `frontend/dist` (rebuild it) and the change logs (keep both) conflict, and both sets of tests pass.
- **Design and limits:** [docs/clipforge/VIDEO_SETUP.md](docs/clipforge/VIDEO_SETUP.md) (what the owner sees, the plan's
  fields and bounds, how the plan drives the edit, the planner, drafts and routes, what is shared with the assistant,
  privacy); [docs/clipforge/ROUTE_MAP.md](docs/clipforge/ROUTE_MAP.md); [AI_CHANGELOG.md](AI_CHANGELOG.md).
- **Code:** new `clipfoundry/studio/video_setup.py`; changed `db.py` (the `setup` column), `studio/routes.py`,
  `video_flow.py`, `ai_editor.py`, `smart_edit.py`, `prefs.py`; `frontend/src/pages/MakeVideo.tsx` (rewritten), new
  `components/VideoPlan.tsx` and `videoSetup.css`, changed `pages/VideoReview.tsx`, `App.tsx`, `router.ts`,
  `studio.ts`, `prefs.tsx`, `components/Customize.tsx`; `frontend/dist` rebuilt; `tests/test_video_setup.py`,
  `tests/test_video_setup_flow.py`, `e2e/sandbox/video-setup.spec.ts` (listed in `e2e/playwright.sandbox.config.ts`).
- **Verify:** `python -m pytest -q tests/test_video_setup.py tests/test_video_setup_flow.py -p no:cacheprovider`, the
  whole suite (`-m "not slow"` and `-m slow`); `cd frontend && npm ci && npm run build`; `cd e2e && npx playwright
  test -c playwright.sandbox.config.ts video-setup.spec.ts` (starts its own sandbox). On Landry's computer: Make a
  YouTube video with real footage and the built-in model on; tell it an idea, try both choices, answer a question,
  change the plan by talking and by hand, build, then change the plan on the editor page.
- **Judgement calls to know about:** "Ask me questions" is the first choice and the last choice is remembered; the
  built-in rules ask at most three questions once (who it is for, length, feel) and a model at most three per round,
  two rounds; a quick answer keeps the other questions while typing your own words drops them; drafts are real
  projects (status "draft") so nothing is lost; ClipForge AI's "Make a YouTube video" tool only shows a button that
  opens the page with the idea filled in (the owner drops in the files) instead of starting a video by itself; the
  old one-step `POST /api/studio/videos` stays for scripts and tests; the plan form sends only what you changed, and
  a line you set by hand stays until a message written after it talks about it again. With a model, its reading of
  a message wins over the built-in rules' (the rules only fill what it did not use); "As long as it needs" is its own
  choice (-1), not "from your style" (0); after the build a plan change only moves the brief fields it changed, and
  Undo brings the plan back with the video, with the brief values, guidance and order it was made with. A plan's
  sound that you change by hand (move, role, trim, level) becomes yours and stays as you left it, even if the plan's
  music changes later. Planning never sends Brain notes to NVIDIA (its agreement says they are never sent); the
  ClipForge AI chat (`brain/chat.py`, older code outside this work) still recalls memories for any provider, NVIDIA
  included, which the NVIDIA privacy row does not mention: worth a look in the assistant's work.
- **Not done:** the built-in model's real planning answers, real footage and speech, and a real Mac cannot be tested
  from the cloud computer (the tests use a fake model and made-up transcripts); speaking the idea instead of typing
  it; planning several videos from one drop.
- **Waiting on Landry:** a real test on Landry's computer with the built-in model; the release (explicit OK).

## Safety follow-ups: built-in AI engine lifetime and other computers' addresses — 2026-11-10 (Claude Code, cloud session)

**Plain-English summary:** two small safety gaps found by the review of the local makers are fixed, plus the same
gap in four more places. On Linux the built-in AI's engine could stop a few seconds after answering (it was tied to
the thread that started it), so the next question loaded the model again; it now lives as long as ClipForge. On
Windows, a web page or a crafted project could make ClipForge look at a file on another computer, which signs in to
that computer as the person; ClipForge now refuses such addresses before looking at anything, while footage on a
share the owner uses still works.

- **Branch / PR:** `claude/project-thread-3rqurx` from the release line at ff890b6, PR #41, merged into
  `claude/project-thread-x72wkd` on Landry's standing OK after the fast and slow suites and the FilmCraft, built-in
  AI and Local makers checks on GitHub's machines passed. No release.
- **Code:** `clipfoundry/builtin_ai.py` (`_popen`, `_spawn_loop`: identical to PR #37's, so it merges cleanly),
  `engines/comfy_server.py` (uses `builtin_ai._popen`), new `clipfoundry/pathguard.py` (`plain_parts`),
  `craft/routes.py`, `engines/routes.py`, `api.py` (catch-all), `studio/local_files.py` (`other_computer`,
  `ELSEWHERE`), `studio/uploads.py` (`link_local`), `craft/web.py` (`_resolve` with roots, `_PATHISH`, `_CLIMB`),
  `craft/ai.py` (`_PATHISH`). Details and checks: [AI_CHANGELOG.md](AI_CHANGELOG.md).
- **Verify:** `python -m pytest -q -p no:cacheprovider tests/test_builtin_ai_lifetime.py tests/test_network_paths.py
  tests/test_pathguard.py tests/test_craft.py`; the whole suite with `-m "not slow"` and `-m slow`.
- **Open follow-up:** FFmpeg opens files named inside a downloaded DASH manifest (see the changelog); a demuxer
  allow-list for media from outside is the fix, with real-media checks.

## Local makers: pictures, video and voice made on this computer — 2026-11-08/10 (Claude Code, cloud session)

**Plain-English summary:** Landry found seven open-source projects and asked for the useful ones to be plugged into
ClipForge, all running locally on his Apple silicon Mac and on Windows. ClipForge can now make pictures, short video
clips and voice-overs itself, for free: pictures and clips through ComfyUI (ClipForge sets up its own private copy
with one button, or uses the ComfyUI desktop app if it is installed) with three Apache-2.0 models, and a built-in
voice (Supertonic 3) that needs no extra program. Every download is pinned to an exact size and checksum, nothing goes
online once downloaded, and Settings → Pictures, video, voice recommends what suits the computer. The animated-shorts
maker and ClipForge AI use it through one door. The other projects were skipped for stated reasons (licences that
exclude the United States or forbid use in a paid app, cloud-only services, heavy servers, or overlap with ComfyUI).

- **Branch / PR:** `claude/project-thread-nnvh05` from the release line at 95a70e0, PR #39 into
  `claude/project-thread-x72wkd`, merged on Nov 10 on Landry's standing OK to merge finished work ("when something is
  done merge it"), after PR #40 and PR #36: the branch took the release line in twice (850adf0, aff2a0e) and
  `frontend/dist` was rebuilt from the combined code. The app code was last changed in 19dfe77 and the machine
  check in d2a8e21 (Local makers check run 42749843276 passed on Mac, Windows and Linux). No release.
- **Design and limits:** [docs/clipforge/LOCAL_ENGINES.md](docs/clipforge/LOCAL_ENGINES.md) (Landry's list with the
  reason for each verdict, the models and their licences, the door, how it was checked, what the cloud cannot check);
  [AI_CHANGELOG.md](AI_CHANGELOG.md).
- **Code:** new `clipfoundry/engines/` (`__init__`, `catalog`, `files`, `tasks`, `comfy_server`, `comfy`, `graphs`,
  `models`, `makers`, `voice`, `routes`); `clipfoundry/config.py` (settings `engines_*`), `api.py` (routes, shutdown),
  `gpu.py` (ComfyUI hands back graphics memory before heavy work); `frontend/src/components/LocalMakers.tsx`,
  `studio.ts`, `pages/Settings.tsx`, `router.ts`; `frontend/dist` rebuilt; `scripts/local_engines_check.py`,
  `.github/workflows/local-engines-check.yml`; `tests/test_local_engines.py`, `tests/conftest.py`.
- **Verify:** `python -m pytest -q tests/test_local_engines.py -p no:cacheprovider`; the whole suite with
  `python -m pytest -m "not slow" -q -p no:cacheprovider` (add `-n 4` with pytest-xdist) and `-m slow` (needs
  espeak-ng); `cd frontend && npm ci && npm run build`; the "Local makers check" workflow runs on every push that
  touches the engines (Mac, Windows, Linux; `workflow_dispatch` takes a picture model id). On Landry's computer:
  Settings → Pictures, video, voice → Set up ComfyUI, download FLUX.2 klein 4B, "Make a test picture"; download the
  voice and "Hear it"; then Wan 2.2 and "Make a 2-second test clip" on a large Mac or an NVIDIA PC.
- **Judgement calls to know about:** ComfyUI 0.43.0 (the newest published release) rather than the newer 0.44 tags;
  one set of full-precision files for every computer (fp8/int8 fail on Metal), so downloads are large (16–23 GB per
  model); FLUX.2 klein 4B is the recommendation for 16 GB Macs; the voice's word timings are estimated inside each
  sentence; the CI picture is made on the processor at 256×256 with `--bf16-unet` to fit the runner's memory; the
  voice and Wan 2.2 need an "Agree and download" (their licences come with use rules; `setup(agreed=True)`); PyTorch
  is installed with `--no-deps` and gets its dependencies from PyPI under the Nov 7 cut-off (PyTorch's own index has
  no upload dates), so on Linux with NVIDIA the CUDA libraries come from PyPI too.
- **Code review (Nov 8):** a three-reviewer pass with skeptics found ten real problems (subfolder model names in the
  ComfyUI app, Remove deleting the shared encoder or files ClipForge did not download, the same request twice failing
  on ComfyUI's cache, uv putting `python3.12` on the PATH and in the Windows registry, unbounded seed and PyTorch
  dependency versions, a complete `.part` file never finishing, progress going backwards, Stop returning while ComfyUI
  still ran, two misleading error texts); all fixed with a test each (AI_CHANGELOG.md has the list).
- **Second review (Nov 8):** three more, each fixed with a test: Remove kept the 8 GB shared text encoder for a
  model that was not there when the person had a file of the same name as one of its files (FLUX.1's `ae.safetensors`
  is also Z-Image's VAE name), and could then never remove it (now kept only for a model that is complete or that
  ClipForge was part way through downloading, and Remove says what it kept; a stopped download can be removed); a
  picture job counted as running only while ComfyUI worked on it, so Remove could stop the ComfyUI a job was starting
  (`comfy_server.job()` now covers start to saved file, `removing()` excludes it); ComfyUI 0.43's own loader's words
  for a damaged file (used on NVIDIA cards) were shown raw. Two more found while checking: another program's `.part`
  file in the app's folders counted as ClipForge's (now only one recorded in the index before the download), and
  Remove did not make a ComfyUI shared from another ClipForge process let go of the files (`release_files()`), and
  removing ComfyUI itself deleted it from under such a process (now refused). Only
  one of the three planned reviewers ran then (a usage limit); the other two ran on Nov 10 (below). Known limit: the
  job guard is per process, so a second ClipForge process making a picture with the shared ComfyUI is not seen by
  Remove in the first (today only the app process makes pictures).
- **Final review (Nov 10, on the code combined with PR #40 and PR #36):** lifecycle, platforms and newest-code
  reviewers, then fixes each with a test that failed first: ComfyUI started from a short-lived thread on Linux died
  with that thread (the parent-death signal follows the thread; now one lasting starter thread); uv's set-up joins
  the Windows kill-on-close job; Stop while ComfyUI starts, a picture stopped while ComfyUI is reached is never sent,
  closing ClipForge stops a set-up first; a ComfyUI another ClipForge process started hands its graphics memory back,
  before heavy work waits; made files refuse network-share and other-drive paths before looking (Windows would sign
  in to the share); Windows long paths when deleting, and Remove says when files stayed; set-up space counted twice
  and uv's cache deleted afterwards, `uv venv --clear --force`, set-up again after the folder moved; the process list
  read as UTF-8 on Windows and the Mac (folders like `C:\Users\José` were not recognised, `Müller` raised); a
  stopped download of the shared text encoder stays with the model whose download it was; Remove of only a stopped
  download says so and leaves the ComfyUI app's loaded models alone. Two tests run the shorts maker against the door.
- **Follow-ups outside the engines (not this PR's code):** `clipfoundry/builtin_ai.py` starts llama-server with the
  same Linux parent-death signal from whichever thread asks; `clipfoundry/craft/routes.py` resolves a requested
  path before checking it (the Windows network-share risk).
- **Not done:** real Metal generation and speed on Landry's Mac, a real Wan clip, Windows with NVIDIA, the ComfyUI
  desktop app, the shorts maker end to end with real engines (all need Landry's computer); smaller fp8 files for small
  NVIDIA cards; LTX-Video.
- **Waiting on Landry:** trying Settings → Pictures, video, voice on his Mac; the release (explicit OK).

## Story clips: Full story, Story parts, five minutes at most, a still picture — 2026-11-09 (Claude Code, cloud session)

**Plain-English summary:** Landry uploads videos of a creator who reads Reddit posts aloud while he plays a game. Story
clips made from them moved the camera, Full stories kept cutting one story into many clips, and there was only one
setting. Now story clips show the whole gameplay picture, centred and still, with the captions just above it; Make
clips has **Full story** (one clip per story) and **Story parts** (each story cut at its most gripping places into
Part 1, Part 2…, each its own clip); and no story clip is ever longer than five minutes, whatever the setting or hand
edit. On 40 test recordings of this kind of video (four posts each) the release line made 9 to 21 clips; this makes 4.
An independent review before the PR found problems with cut points, kinds of story videos the stricter rules missed,
caption placement and framing details; all are fixed and tested.

- **Branch / PR:** `claude/project-thread-6ouxbx`, restarted from the release line at 95a70e0 (PRs #30–#33), draft PR
  into `claude/project-thread-x72wkd`. No release; Landry has not said to merge.
- **Design and limits:** [docs/clipforge/STORY_CLIPS.md](docs/clipforge/STORY_CLIPS.md) (why stories were split, the
  rules, the part planner, every place the five-minute limit is enforced, the still picture, the measured numbers);
  [AI_CHANGELOG.md](AI_CHANGELOG.md).
- **Code:** new `clipfoundry/pipeline/story_parts.py`; changed `pipeline/stories.py`, `captions.py`, `render.py`,
  `blueprint.py`, `studio/story_review.py`, `guidance.py`, `capabilities.py` (a word only), `clips_flow.py`,
  `link_import.py`, `prefs.py`, `routes.py`, `db.py` (three columns), `api.py` (trim limit); `frontend/src/pages/MakeClips.tsx`,
  `ClipEditor.tsx`, `Studio.tsx`, `Projects.tsx`, `components/StoryReview.tsx`, `studioParts.tsx`, `App.tsx`,
  `prefs.tsx`, `studio.ts`; `frontend/dist` rebuilt; tests `tests/test_story_parts.py`, `tests/test_story_clips.py`
  (new), `tests/test_full_stories.py`, `tests/story_fixtures.py`, `tests/test_smarter_ai.py`.
- **Verify:** `python -m pytest -q -p no:cacheprovider tests/test_story_parts.py tests/test_story_clips.py
  tests/test_full_stories.py tests/test_smarter_ai.py`; `python -m pytest -m slow -q -p no:cacheprovider
  tests/test_story_clips.py tests/test_studio_render.py` (real renders, needs ffmpeg and espeak-ng); `cd frontend &&
  npx tsc --noEmit -p . && npm run build`. On Landry's computer: Make clips → Full story on one of the gamer videos
  (one clip per post, the picture still, captions above it), then Story parts on the same video (Part 1, Part 2… with
  "Part N" at the top), and a story longer than five minutes (split into parts in both settings).
- **Judgement calls to know about:** a story boundary now needs something said (an announcement, a post's title where
  the subject changes, an intro/sponsor/outro run, a story's first words after a long pause) or a long break with a
  change of subject measured by the meaning model;
  ClipForge AI can no longer split at a change of subject alone (an existing test's expectation changed on purpose).
  Story parts is a Full stories project with `options.story_split = "parts"`, so Full stories styles, skills and
  examples apply to both. Only a framing chosen for the project (Customize or its example video) or the clip editor
  can move the picture of a story clip; a saved style, a skill, a shared example, a Brain note or the settings cannot.
  A subject to follow chosen for the project with no framing gets the vertical frame (otherwise the choice would do
  nothing). A story of 5:00 or less is one clip in Full story; parts are planned at most 299.5 s.
  Captions sit above the picture unless any level chose a caption position. Parts are 62–175 s when the story allows
  (TikTok counts over a minute as long; under the three-minute Shorts and Reels limit).
- **Not done:** real speech recognition on Landry's own videos (needs his computer); ClipForge AI's real model choosing
  among cut places (stand-in answers only); captions above the picture for 4:3 sources with a "Part N" headline, High
  energy captions above a 16:10 source with a "Part N" headline, square or vertical sources (they use the lower
  third).
- **Waiting on Landry:** a look at the PR; a real-video test on his computer; the merge; the release (explicit OK).

## Make → Animated short: viral voice-over shorts — 2026-11-08 (Claude Code, cloud session)

**Plain-English summary:** Landry asked for the animated voice-over shorts seen on TikTok, from a pasted script or
one ClipForge writes, all running on his Mac. Make → Animated short now turns a script into scenes, gives each a
voice, a picture and a gentle camera move, and puts them together with big captions where the spoken word lights up,
music under the voice and a whoosh on the cuts. Every scene can be changed on its own afterwards (words, picture,
move, order, add, delete), and the normal editor, preview, render and FilmCraft work on it. Without the local
engines it still works: the computer's own voice and designed cards with each scene's key words.

- **Branch / PR:** `claude/project-thread-5qybvh` from the release line at 95a70e0, draft PR into
  `claude/project-thread-x72wkd`. No release; Landry has not said to merge.
- **Depends on, loosely:** the local engines (`clipfoundry/engines`, thread "Plug local open-source tools into
  ClipForge", branch `claude/project-thread-nnvh05`). `makers/local_engines.py` is the only door; without the module
  every role reports "not part of this version" and the fallbacks run. Either branch can merge first.
- **Design and limits:** [docs/clipforge/ANIMATED_SHORTS.md](docs/clipforge/ANIMATED_SHORTS.md);
  [AI_CHANGELOG.md](AI_CHANGELOG.md).
- **Code:** new `clipfoundry/makers/` (scenes, writer, voice, pictures, cards, motion, looks, local_engines, shorts,
  routes); changed `db.py`, `api.py`, `jobs.py`, `cloud/ownership.py`, `studio/engine.py` (`captions.highlight`),
  `studio/video_flow.py`, `studio/routes.py`, `brain/knowhow.py`, `brain/memories.py`, `requirements.txt` (pillow);
  frontend `pages/MakeShort.tsx`, `components/ShortScenes.tsx`, `shorts.ts`, `pages/shorts.css` (new), `App.tsx`,
  `Studio.tsx`, `Projects.tsx`, `VideoReview.tsx`, `MemoryTab.tsx`, `router.ts`, `studio.ts`; `frontend/dist` rebuilt.
- **Verify:** `python -m pytest -q tests/test_studio_shorts_flow.py tests/test_studio_shorts_parts.py
  tests/test_studio_shorts_voice.py tests/test_studio_shorts_captions.py tests/test_clipforge_ai_knowhow.py`; the
  real render: `python -m pytest -q -m slow tests/test_studio_shorts_render.py` (needs espeak-ng); `cd frontend && npm
  run build`. On Landry's Mac: Make → Animated short with a pasted script (the `say` voices), then with the local
  makers set up (real pictures and the Supertonic voice: the reminder next to Download should appear), and Write it
  for me with the built-in AI.
- **Judgement calls to know about:** captions default to the look's own style; a scene is 6-16 words (one picture
  every 2-4 s); the engine's own estimated word times are ignored in favour of listening or the sound; "auto" voice
  is pinned when a short is first made so later scenes match; a short allows 600 words and 80 scenes; the owner's
  editor changes (order, trims, removed clips, levels, word fixes) survive scenes being made again.
- **Not done / not testable here:** the real engines, `say`, SAPI, a real model writing scripts and the speech
  model's word times; a Windows run.
- **Waiting on Landry:** a look at the PR, a try on his Mac, the merge and any release (explicit OK each time).
- **Nov 9 review round:** undo/redo/restore now put a short's scenes and choices back with the version (the critical
  finding), Stop and Stop all jobs always free a short, and the other review findings are fixed (see the 2026-11-09
  entry in [AI_CHANGELOG.md](AI_CHANGELOG.md)). New tests: `tests/test_studio_shorts_undo.py`, `_stops.py`,
  `_edits.py`. Still only on real machines: the engines, Landry's downloaded voices, a real model writing and the
  speech model's word times.

## ClipForge AI far smarter: meaning, scout and judge, eyes, ears, your taste — 2026-11-07 (Claude Code, cloud session)

**Plain-English summary:** Landry asked for the built-in AI and the editing to be "100 times smarter", research first,
and asked whether his two research guides were used. ClipForge now understands what is said (a small meaning model,
downloaded once and checked against pinned hashes), reads the whole video and names moments the word lists miss, ranks
the finalists side by side with verdicts, looks at frames of the best clips and picks their thumbnails, listens to the
voice (emphasis, laughter, flat delivery) for the score and for where punch-ins go, learns Landry's taste from the
clips he keeps and drops, finds story changes in long videos that the words hide, and applies three more rules from
the guides (the causal "but / which meant" engine, the constrained-experiment hook, chapter fillers). Every new signal
is bounded and explained next to the clip, and everything falls back to the old behaviour when a part is missing.

- **Branch / PR:** `claude/project-thread-hud5t5` from the release line at 7723696, draft PR into
  `claude/project-thread-x72wkd`. No release; Landry has not said to merge.
- **Design and limits:** [docs/clipforge/SMARTER_AI.md](docs/clipforge/SMARTER_AI.md) (the research table, every
  number and bound, how the guides were used, what was deliberately not automated); [AI_CHANGELOG.md](AI_CHANGELOG.md).
- **Code:** new `clipfoundry/embedder.py`, `taste.py`, `pipeline/scout.py`, `eyes.py`, `ears.py`; changed
  `pipeline/semantic.py`, `deep.py`, `process.py`, `candidates.py`, `diversity.py`, `stories.py`, `render.py`,
  `virality.py`, `text_utils.py`, `llm.py`; `builtin_ai.py` (schema + images), `brain/meaning.py`, `memories.py`,
  `db.py`, `api.py`, `config.py`, `studio/smart_edit.py`, `story_review.py`, `publish/jobs.py`,
  `autopilot/publisher.py`; `frontend/src/api.ts`, `components/AiHelperSettings.tsx` (MeaningSetup),
  `MemoryTab.tsx` (taste panel), `viral.tsx` (AiNotes); `frontend/dist` rebuilt; `scripts/builtin_ai_check.py`,
  `.github/workflows/builtin-ai-check.yml`; `tests/test_smarter_ai.py`, `tests/conftest.py`.
- **Verify:** `python -m pytest -q tests -p no:cacheprovider --ignore=tests/test_studio_smart_render.py` (the
  render tests need espeak-ng); `cd frontend && npm ci && npm run build`; on a runner, the "Built-in AI check"
  workflow with `--meaning --eyes` (Linux and Mac jobs). With a local copy of the model,
  `CLIPFORGE_MEANING_MODEL_DIR=<dir> python -m pytest tests/test_smarter_ai.py -k real_meaning_model`. On Landry's
  computer: Make clips on a real video with the built-in model and read the clip's "Why" lines (scout, rank, saw,
  voice); untick and re-tick a dozen clips and watch Brain → Memory → "What it learned from your choices".
- **Judgement calls to know about:** `deep_analysis`, `ai_scout`, `ai_eyes` and `meaning_model` are on by default
  (each bounded, each with an off switch); the meaning model is all-MiniLM-L6-v2 and not a Qwen embedding (90 MB,
  CPU, Apache-2.0, no PyTorch); the model never adds or removes a clip on its own; the judge moves scores only by its
  disagreement with the local ranking; taste needs 12 lessons with 4 on each side before it does anything; the
  "and_then" flag has severity "warn" because the penalty table knows only warn and block.
- **Not done:** real downloads and the built-in model cannot be exercised from the cloud computer (the model hub is
  blocked); the runner workflow must be run after the push and its result read; the slow drift zoom on static shots
  and sculpted silence before a payoff from the filmmaking guide (recorded as follow-ups in SMARTER_AI.md); the
  Qwen3-Embedding model through the built-in engine (the plan's later phase).
- **Waiting on Landry:** a look at the PR; a real-footage test on his computer; the merge; the release (explicit OK).

## The ClipForge look: one design system and every page restyled — 2026-11-07 (Claude Code, cloud session)

**Plain-English summary:** Landry asked for the whole UI to look very, very good. The app now has one design system
("the edit bay": layered dark surfaces lit from the top edge, sunken wells for media, lifted controls, the footage the
brightest thing on the page, one accent for the way forward) and every page is restyled on it: the shell, Studio,
projects, the clip and video editors, Review, Brain, Settings (now a side list of sections), publishing, accounts,
sign-in, the robot office, and the loading and empty states. How the pages work is untouched: class names and markup
stayed, so the TSX changed only where a state needed a line (skeleton pages, the empty-state disc, the chat's empty
line, the Settings frame, the Review column packing).

- **Branch / PR:** `claude/project-thread-89ew66` from the release line at 3c6b980, draft PR into
  `claude/project-thread-x72wkd`. No release. The long-video work (`claude/project-thread-6ouxbx`) runs beside it:
  its new wrapper classes are styled here and its pages (MakeVideo, VideoReview, MakeClips, StoryReview) were not
  touched, so the two merge without conflicts in the TSX.
- **Design and limits:** [docs/clipforge/DESIGN_SPEC.md](docs/clipforge/DESIGN_SPEC.md) (tokens, measured contrast,
  layout rules); before/after pictures in [docs/clipforge/ui-redesign/](docs/clipforge/ui-redesign/).
- **Code:** `frontend/src/styles.css` (the system, rewritten), `theme.css` (palettes and accents, tokens only),
  `pages/editor.css`, `library.css`, `posts.css`, `Brain.css`, `BrainGraph.css`, `office/studio.css`,
  `components/TikTokSetup.css`; `components/ui.tsx` (skeleton page, empty-state disc, side tabs), `pages/Settings.tsx`
  (`SettingsFrame`), `components/AppearanceSettings.tsx` (`LayoutFlow` column packing), `components/ClipForgeAI.tsx`,
  `App.tsx`, `pages/Brain.tsx`, `BrainGraph.tsx` (sentence-case titles), `prefs.tsx` and
  `clipfoundry/studio/prefs.py` (`REVIEW_SIZE`), `index.html`; `frontend/dist` rebuilt.
- **Verify:** `cd frontend && npm run build`; `python -m pytest -q tests -m "not slow"` (at least
  `tests/test_theme_contrast.py tests/test_studio_prefs.py`); `cd e2e && npx playwright test tests/app-shell.spec.ts
  tests/library.spec.ts tests/settings.spec.ts tests/office.spec.ts` against a running app. Then look: the pages at
  1440 and 390 px wide have no sideways scroll, the save bar sits at the bottom, the kind label sits above each title,
  and the four palettes and six accents in Customize studio all read well.
- **Judgement calls to know about:** dark only stays (no light theme); the Settings tabs became a side list on wide
  windows (the same links, `.tabs.tabs-side`); the kind label stays visible because a browser check reads it; the
  Review page's default panel widths went from equal to 0.6/0.4/0.6/0.4 (saved layouts keep their own sizes); the
  Brain's upper-case labels became sentence case ("My knowledge", "Saved items", "Local knowledge map"); the office
  keeps the pixel face for titles and names only.
- **Not done:** a light theme (dark only by design); the five browser checks that fail on the release line with the
  demo data (three office map and bar checks that need the real job system; two Settings checks: five newer settings
  without a place on the page, and the daily-target field error); a "before" picture for every page (nine pages have
  pairs).
- **Waiting on Landry:** a look at the pictures and the PR; the merge; the release (needs an explicit OK).

## Long videos: full stories, big footage, the script and a smarter cut — 2026-11-07 (Claude Code, cloud session)

**Plain-English summary:** Landry wanted the long-video editing much better and smarter: 17 GB of footage would not
go in, the cut was weak, the script should be compared with the footage, and first the Full stories section had to
find every story in a video of someone reading posts and make one long clip per story without asking. The stories
finder now learns the narrator's own separators and never asks (committed first, e6681ed). Big files are used where
they are on the desktop, listened to in pieces that resume, and previewed from a small copy. A script in any common
format is matched line by line to the footage and cut in script order with the cleanest take of each line, the
other takes a click away. Without a script, the cut keeps the best take across files, drops warm-ups and camera
chatter, opens with the strongest line, and ClipForge AI reads the whole video inside a time budget.

- **Branch / PR:** `claude/project-thread-6ouxbx` (from the release line at 32485bd), draft PR into
  `claude/project-thread-x72wkd`. No release. The UI redesign thread (`claude/project-thread-89ew66`) styles the new
  screens; my styles are in `frontend/src/components/longVideo.css` so the two do not collide.
- **Design and limits:** [docs/clipforge/LONG_VIDEOS.md](docs/clipforge/LONG_VIDEOS.md) (as built, with the numbers);
  [AI_CHANGELOG.md](AI_CHANGELOG.md) lists every change.
- **Code:** `clipfoundry/pipeline/stories.py`, `studio/story_review.py`; `studio/local_files.py`, `local_routes.py`,
  `proxies.py` (new), `uploads.py`, `api.py`, `config.py`, `engine.py`, `reference.py`; `pipeline/transcribe.py`,
  `audio.py`, `process.py`; `studio/script.py`, `script_cut.py` (new), `video_flow.py`, `routes.py`, `db.py`;
  `studio/smart_edit.py`, `ai_editor.py`; `frontend/src/studio.ts`, `components/ScriptDrop.tsx`, `ScriptPanel.tsx`,
  `LocalFiles.tsx`, `longVideo.css` (new), `studioParts.tsx`, `pages/MakeVideo.tsx`, `pages/VideoReview.tsx`;
  `requirements.txt` (`pypdf`, `python-docx`).
- **Verify:** `python -m pytest -q tests/test_full_stories.py tests/test_studio_script.py
  tests/test_studio_script_cut.py tests/test_transcribe_long.py tests/test_studio_local_files.py
  tests/test_studio_proxies.py tests/test_studio_smart_edit.py tests/test_studio_editor.py tests/test_studio_jobs.py`
  (all green here); `cd frontend && npm run build`. On a real computer: add a 17 GB file with Add from this computer,
  watch it listen in pieces and resume after a quit, give a script and check the takes, build without a script and
  check the cold open and the takes across files, and the Full stories section on a real Reddit-reader video.
- **Judgement calls to know about:** with a script ClipForge AI's model is not asked at all and the pauses inside a
  take are not cut (a line plays as it was said); a line said more than three times is a catchphrase and every time
  stays; greetings and "in this video…" are not chatter; a sign-off is left out only in a recording that is not the
  last; the cold open is on by default from two minutes and needs a score of 0.55 (a weaker video just starts);
  the desktop upload limit is the free space less 2 GB; linked files are never changed and everything made for them
  lives in ClipForge's data folder; the speech model is held across the pieces of one batch and released after it
  (`transcribe.release_model`; the live loop in `pipeline/live.py` is unchanged).
- **Not done:** a real 17 GB file, the real speech model, the built-in model and espeak-ng renders could not be
  tried in the cloud; script matching is by words, not meaning (a paraphrased line counts as missing); the local
  browser was tried on Linux paths only; the look of the new panels is the UI thread's.
- **Waiting on Landry:** review of the PR and a try with his own footage; the release (needs an explicit OK).

## ClipForge AI know-how from the research — 2026-11-06 (Claude Code, cloud session)

**Plain-English summary:** Landry gave ClipForge AI two research guides (cinematic filmmaking and post-production;
viral short-form video strategy) to make it smarter at editing, and asked for my own improvements too. The guides
are now twelve built-in playbooks (`clipfoundry/brain/knowhow.py`) that the chat, change requests, smart edits, the
FilmCraft pass, clip scoring and post packages read, inside budgets, after the owner's memories (which always win);
the chat answers editing questions from them without a model; and the deterministic editors apply the numbers
(outros, loss-framing hooks, caption safe zones, the voice chain, BT.709 colour, delivery settings).

- **Branch / PR:** `claude/project-thread-605vsm` (restarted from the release line at 936d7fc), draft PR into
  `claude/project-thread-x72wkd`. No release.
- **Design and limits:** [docs/clipforge/CLIPFORGE_AI.md](docs/clipforge/CLIPFORGE_AI.md), "Know-how";
  [AI_CHANGELOG.md](AI_CHANGELOG.md) lists every number that changed.
- **Code:** `clipfoundry/brain/knowhow.py` (new), `brain/chat.py`, `brain/routes.py`, `db.py` (`edit_requests.knowhow`),
  `studio/edit_requests.py`, `studio/ai_editor.py`, `studio/video_flow.py`, `craft/ai.py`, `pipeline/llm.py`,
  `pipeline/postpack.py`, `pipeline/text_utils.py`, `pipeline/candidates.py`, `pipeline/virality.py`,
  `pipeline/hooks.py`, `pipeline/captions.py`, `pipeline/cleanup.py`, `pipeline/render.py`, `pipeline/ffmpeg_utils.py`,
  `studio/engine.py`; `frontend/src/brain.ts`, `studio.ts`, `components/ClipForgeAI.tsx`, `components/MemoryTab.tsx`.
- **Verify:** `python -m pytest -q tests/test_clipforge_ai_knowhow.py tests/test_clipforge_ai_chat.py
  tests/test_virality.py tests/test_core.py tests/test_editing.py`; the FilmCraft check workflow for the real apps
  (the pass's request now carries the know-how block).
- **Judgement calls to know about:** "bottom" captions moved from 23% to 36% up the frame (the apps cover the bottom
  35%); the hook headline from 11% to 15% down; the clip renderer now converts RGB → YUV with BT.709 (it was BT.601,
  a colour shift on every clip) and adds `-g fps/2 -flags +cgop` and BT.709 tags; AAC 192 → 256 kbps. Music levels
  and ducking were left as they are (no way to listen here).
- **Not done:** vision (static frames, pattern interrupts from the picture), the retention-graph reader on real
  analytics, music ducking with the 150-250 ms release in the engine, a use counter for playbooks.
- **Waiting on Landry:** review of the PR; the release (needs an explicit OK); the nine plan questions.

## ClipForge AI phase A: the brain and the chat — 2026-11-06 (Claude Code, cloud session)

**Plain-English summary:** Landry wants the AI to be much better and called ClipForge AI: researched models combined
with its own data and training, a chat to ask for changes, everything kept in the brain, finding music and pictures,
making effects and music. The research and the four-phase plan are in the Claude Doc "ClipForge AI: research and
plan" (link in the project memory); Landry chose to start with the brain and the chat. Phase A gives ClipForge AI a
memory (rules, facts and what it did, with sources, scopes and a meaning search, no download needed), uses it in
change requests, the FilmCraft pass and smart edits, and adds a chat on every video and in the Brain, plus a Memory
tab. The old "AI helper" is now ClipForge AI's model.

- **Branch / PR:** `claude/project-thread-605vsm` (restarted from the release line after #25 and #26), PR #27,
  merged into `claude/project-thread-x72wkd` as 936d7fc on 2026-11-06. Not released.
- **Design and limits:** [docs/clipforge/CLIPFORGE_AI.md](docs/clipforge/CLIPFORGE_AI.md).
- **Code:** `clipfoundry/brain/` (`memories.py`, `meaning.py`, `chat.py`, `routes.py`), `db.py` (four tables, the
  `memories` column on `edit_requests`), `studio/edit_requests.py`, `studio/video_flow.py`, `studio/ai_editor.py`,
  `craft/ai.py`, `craft/finish.py`; `frontend/src/brain.ts`, `components/ClipForgeAI.tsx`, `components/MemoryTab.tsx`,
  `pages/Brain.tsx`, `pages/VideoReview.tsx`.
- **Verify:** `python -m pytest -q tests/test_clipforge_ai_brain.py tests/test_clipforge_ai_chat.py
  tests/test_studio_edit_requests.py tests/test_craft.py`; the FilmCraft check workflow for the real apps.
- **Open questions for Landry** (my picks apply until answered, see the plan doc): monetised use (commercial-safe
  licences only), the computer (plan for a plain laptop), internet for the finders (finders online, brain offline),
  consent to learn (locally), where the brain lives (this computer, export/import), music find-first, the name,
  where to train (free Colab), anything missing.
- **Waiting on Landry:** the release (needs an explicit OK); the nine plan questions.
- **Next (phase B):** the embedding model download (Qwen3-Embedding-0.6B) behind `meaning_model`, the finders
  (Pixabay, Freesound, Jamendo under their licences) and the first maker (ACE-Step music), each as a checked tool the
  chat can use.

## FilmCraft and EffectCraft inside ClipForge — 2026-11-06 (Claude Code, cloud session)

**Plain-English summary:** Landry wants FilmCraft inside ClipForge, not separate, with the AI editing through its
tools and effect shots from another app put into the final edit. ClipForge now fetches FilmCraft and EffectCraft
itself, edits each final video in FilmCraft with FilmCraft's own tools (plus EffectCraft's animated title and, with an
AI helper, the AI's finishing), has FilmCraft render it, and opens FilmCraft's editor on the editor page; saves there
come back as new versions. The built-in FFmpeg editor stays as the backup.

- **Branch / PR:** `claude/project-thread-605vsm`, draft PR #26 (on top of the timeline hand-off).
- **Design and limits:** [docs/clipforge/CRAFT_APPS.md](docs/clipforge/CRAFT_APPS.md).
- **Code:** `clipfoundry/craft/` (apps, runner, finish, shots, ai, web, routes), `studio/video_flow.py`
  (`_craft_render`, `save_filmcraft`, job `filmcraft_edit`, hand-finished versions in `save_revision`),
  `studio/interchange.py` (blurred background tracks), `frontend/src/components/FilmCraft.tsx`, `EditingApps.tsx`.
- **Verify with real apps:** `scripts/craft_check.py` (GitHub's Mac and Linux machines; the cloud session may not run
  downloaded programs).
- **Real-app results:** run 42256808188 passed on macOS 15 and Ubuntu (edit, EffectCraft title, AI pass with an
  EffectCraft shot, FilmCraft render, the editor page opening version 1 and Ctrl/Cmd+S coming back as version 2).
  Earlier runs found: no `property("Source Text")` in EffectCraft 0.9.2, no host messages in FilmCraft 0.17.1's web
  build, FilmCraft only opens a `File` made by its own window, look names with commas (see AI_CHANGELOG.md). Facts read from the released files: the 0.17.1 web
  build has `window.filmcraft` (execute, commands, inspect, screenshot, info, files, readFile, importFiles,
  importUrl, openProject) and saves by anchor download; `effectcraft-cli script --json` prints `result`/`output`.
- **Built-in AI (PR #25) joined in:** it does the FilmCraft AI pass once downloaded, with a request shortened to fit
  its 8,192-token context; `scripts/craft_check.py --builtin-ai` checks it with the real model. Landry approved
  merging #25 and #26 into the release line once that check passes.
- **Waiting on Landry:** release.
- **Next:** EffectCraft's own editor in the page, PhotoCraft (thumbnails), Windows check with the real apps.

## Finish in FilmCraft — 2026-11-06 (Claude Code, cloud session)

**Plain-English summary:** Landry asked to plug the ArtCraft apps (getartcraft.com/apps) into ClipForge for editing.
FilmCraft, their open-source video editor, is plugged in as a hand-off: the editor page writes the cut as a timeline
with captions and opens it in FilmCraft for hand finishing (colour, keyframes, titles, mixing). FFmpeg stays the
engine for automatic editing and rendering.

- **Branch:** `claude/project-thread-605vsm`, from `claude/project-thread-x72wkd` (separate from phase 1, PR #25).
- **Design, limits and how it is verified:** [docs/clipforge/FILMCRAFT.md](docs/clipforge/FILMCRAFT.md).
- **Code:** `studio/interchange.py` (OTIO + SRT + package/zip), `studio/filmcraft.py` (find, import with
  `filmcraft-cli`, open), three routes in `studio/routes.py`, `frontend/src/components/FilmCraft.tsx` (rebuilt dist).
- **Real FilmCraft:** `.github/workflows/filmcraft-check.yml` (push to `claude/**` touching these files, or by hand)
  runs `scripts/filmcraft_check.py` against FilmCraft 0.17.1 pinned by SHA-256 on macOS 15 and Ubuntu.
- **Next ArtCraft apps:** PhotoCraft (thumbnails), EffectCraft (titles), SoundCraft (voice): same "open in" pattern.

## Built-in AI and sound cleanup (phase 1) — 2026-11-06 (Claude Code, cloud session)

**Plain-English summary:** Landry asked for a plan to make clipping and editing smarter with an AI that ships with
the app (plan: Claude Doc in the project thread), then chose "Start phase 1". Phase 1 is built: a built-in AI that
downloads on first use (level picked from the computer) and becomes the default helper, and "Clean up the sound"
(noise, hum, breaths, mic balance, even levels, voice polish) with a before/after switch. Draft PR, not merged.

- **Branch:** `claude/project-thread-4sg7wk`, from `claude/project-thread-x72wkd` @ `e7f7919` (PR #20's branch with
  #22 and #23); the PR targets that branch.
- **Design and limits:** [docs/clipforge/BUILTIN_AI_AND_SOUND.md](docs/clipforge/BUILTIN_AI_AND_SOUND.md).
- **Code:** `clipfoundry/builtin_ai.py`, `clipfoundry/pipeline/cleanup.py`; wiring in `pipeline/llm.py`, `gpu.py`,
  `api.py` (`/api/ai/builtin*`, `/api/clips/{id}/sound-check`), `pipeline/render.py` (`_clean_sound`),
  `studio/engine.py` (`source_sound`), `studio/video_flow.py`; frontend `AiHelperSettings.tsx`,
  `components/SoundCompare.tsx`, ClipEditor, Settings, VideoReview.
- **Real-machine check:** `.github/workflows/builtin-ai-check.yml` runs on pushes to this branch (Mac, Linux,
  Windows; Windows fetches only the four files it needs because this repository's folder name cannot be checked out
  there). Its summary has load time, words per second and the sound cleanup's real-time factor.
- **Next phases (not started):** smarter clips, styles and finishing, YouTube videos and short films (see the plan).

## Release ClipForge 2026.11.05.2 (smart editing + Mac link fix) — 2026-11-05 (Claude Code, cloud session)

Landry asked to merge both fixes and update the website. PR #22 was merged into `claude/project-thread-x72wkd`
(`a6b17b1`), then merged into PR #23's branch (`2e5238e`, conflicts only in the changelog files). Both downloads
come from `2e5238e`; PR #23 was merged after the release with this record. Details: the top entry of
[AI_CHANGELOG.md](AI_CHANGELOG.md) and `docs/clipforge/WEBSITE_DEPLOYMENT.md`.

- Mac: release `clipforge-mac-2026-11-05-2e5238e`, from tested run 42106643196. Windows: `raw/d60445f` on
  `claude/clipforge-downloads`, Windows setup check run 42109581700. Page: `gh-pages` `65f026a`.
- Rollback: revert `65f026a` on `gh-pages` with a normal commit; the 2026.11.05 files (6ecdafc) stay listed under
  Older versions and their URLs never change.
- Pushing straight to `gh-pages` worked this time (it was refused earlier the same day).
- PR #20 (the studio upgrade branch these PRs merge into) is still not merged into the default branch.

## Smart video editing and the AI helper — 2026-11-05 (Claude Code, cloud session)

**Plain-English summary:** Landry asked for a video editor that actually edits (trims, adds sound and pictures when
it helps) and for a free way to plug in an AI (a key or a local model). "Make a YouTube video" now defaults to
"Edit it for me": pauses, lone fillers, earlier takes and stumbles are cut, the length is fitted, images are shown
over the video when they are named, and free music and soft effects made on the computer are added. Settings → AI
helper sets up Ollama (download or .gguf import), LM Studio or a free Gemini/Groq/OpenRouter key. Draft PR #23,
not merged.

- **Branch:** `claude/project-thread-k49gua`, from `claude/project-thread-x72wkd` (#20, unmerged), PR #23 targets it.
- **Design and limits:** [docs/clipforge/SMART_EDITING.md](docs/clipforge/SMART_EDITING.md).
- **Code:** `studio/smart_edit.py` (the plan), `studio/ai_editor.py` (AI advice, windowed and validated),
  `studio/library.py` (synthesized music/effects), `ai_setup.py` (presets, Ollama pull/import), engine `join`,
  `zoom`, `overlays`; `video_flow.prepare_smart`, `smart_again`, job `video_smart`; frontend MakeVideo, VideoReview
  (SmartPanel, Pictures), `components/AiHelperSettings.tsx` at `#/settings/ai`.
- **Compatibility:** API callers without `smart_edit` get the old rough cut; music is added to unedited clips only
  when `music` is `auto`/`library`. Captions now keep a word that starts in a clip and is mostly inside it.
- **Tests:** `tests/test_studio_smart_edit.py` (fast), `tests/test_studio_smart_render.py` (slow, needs espeak-ng).
- **Not verified:** a real Ollama/LM Studio model, real free-tier keys, the native apps with these screens.

## Mac YouTube link fix — 2026-11-05 (Claude Code, cloud session)

Landry reported that the released Mac app (2026.11.05) failed every YouTube link with "No downloadable video was found
on this page". The fix is on branch `claude/project-thread-8zldhx`, in draft PR #22, which is stacked on PR #20 (its
base is `claude/project-thread-x72wkd`). See the top entry of [AI_CHANGELOG.md](AI_CHANGELOG.md) for the cause, the
fix and the checks. It is not merged and not released; a new Mac DMG needs Landry's OK (release flow: the
`macos-desktop.yml` run, then `macos-personal-preview.yml`). YouTube itself cannot be tested from the cloud
environment or from GitHub runners (bot check), so only a real Mac confirms it.

## ClipForge studio upgrade, released — 2026-11-05 (Claude Code, cloud session)

**Plain-English summary:** work on the studio upgrade handoff
([CLIPFORGE_STUDIO_UPGRADE_CLAUDE_PROMPT.md](docs/CLIPFORGE_STUDIO_UPGRADE_CLAUDE_PROMPT.md)) was carried out in its own
order. Steps 1–7 are done: video links, discovery retired, the full-video editor, example videos, Find media, change
requests, Studio and the office, dark design and Customize studio, the Brain map, the ClipForge name in the native
apps and the full checks. Step 8, the release Landry approved, is done: the Mac DMG preview release and the Windows
setup ZIP, both from `6ecdafc`, and the new download page on GitHub Pages (`gh-pages` `138c4f7`, PR #21, merged at
Landry's request "update the website"). Merging PR #20 is a separate decision. No real account or video was touched;
there is no cloud deployment.

- **Branch:** `claude/project-thread-x72wkd`, started from the default branch `claude/wonderful-ritchie-909tq3` @
  `12afd01` and merged with `codex/review-clipforge-pr16` @ `0b723c0` (renderer repair `fc0664c`) as `6c3f8d9`.
  Other remote branches were compared; none has newer app source.
- **Requirement matrix (kept current):** [docs/clipforge/STUDIO_UPGRADE_MATRIX.md](docs/clipforge/STUDIO_UPGRADE_MATRIX.md).
- **Baseline on `6c3f8d9`:** fast suite 1,630 passed; slow suite 21 passed (clean worktree), including the two tests
  the 2026-11-04 entry below lists as failing. They did not reproduce here, so they were left as they are.
- **Done so far:**
  - `cc89a87` Video link in Make clips: `studio/link_import.py`, `jobs.fetch_public_video`, `uploads.store_file`;
    29 tests in `tests/test_studio_links.py`.
  - `d3abd6e` Discovery retired: `config.DISCOVERY_RETIRED`, `db._migrate_discovery_retired`, screens cleaned;
    `tests/test_discovery_retired.py`. Older discovery suites run with the retirement patched off (dormant-engine
    coverage, documented in `tests/conftest.py` and the matrix).
  - Full-video editor (handoff section 8): engine `ffmpeg-v2` renders in pieces (any number of clips; ≤2 inputs per
    FFmpeg run; audio mixed in 10 s blocks; disk space checked first), plan schema 2 with voiceover/music/effects
    tracks, insert/replace/add media after the rough cut, undo/redo/restore/named versions as new revisions, caption
    word fixes, and a rebuilt editor screen. **Ducking now works at normal speech levels** (the old sidechain setting
    did nothing below loud speech; measured). Tests: `tests/test_studio_editor.py` (fast),
    `tests/test_studio_editor_render.py` (slow). Details: `docs/clipforge/EDITOR_INTEGRATION.md`.
  - Example videos (handoff section 6): `studio/reference_analysis.py` measures cuts/dissolves/fades, framing,
    on-screen caption lines, speech, pauses and the music dip under speech locally (no AI model; labelled Measured
    or Estimate with playable timestamps); `studio/reference.py` runs it as a durable job cached by content hash +
    ranges + analyzer version, saves an Example style with provenance and corrections, and feeds guidance (a chosen
    example ranks right after project choices). New fields `shot_length_s`, `duck_depth_db` are applied by the rough
    cut. Make a video stopped sending pre-filled answers as project choices (they overrode every style). Tests:
    `tests/test_studio_reference.py` (fast), `tests/test_studio_reference_render.py` (slow).
  - Find media (handoff section 6, web media library): `studio/media_sources.py` searches Openverse, Wikimedia
    Commons and Pexels (key sealed in Settings → Media sources), proxies previews per workspace, imports through a
    durable job with `netguard` downloads, size/type/decode checks and a provenance row (`asset_sources`, kept apart
    from the Brain), and keeps an editable credits list (render info, `credits.txt`, automatic upload descriptions).
    Unknown or unfit terms need the owner's written reason and hold automatic posting. Supporting media per project
    (suggest by default, or add automatically as one undoable version). Editor panel, Settings tab and Make a video
    choices built. Tests: `tests/test_studio_media_sources.py` (fast), `tests/test_studio_media_render.py` (slow).
    **Provider APIs not live-verified** (hosts unreachable here).
  - Tell the editor what to change (handoff section 9): `studio/edit_requests.py` turns a request into a
    `clipforge.edit-proposal/v1` proposal (stable clip ids, source times), checked on its own revision by the same
    edits as the manual controls and applied only on Apply as a new revision (Undo reverts; stale proposals are
    refused). Rules understand the handoff's examples without AI; anything else goes text-only to the AI service in
    Settings → AI when one is set up, with a timeout, cancel, a daily limit, a cache and no automatic retries.
    Tests: `tests/test_studio_edit_requests.py` (fake AI service; no real model was called).
  - Studio and the office (handoff sections 4 and 5): `pages/Studio.tsx` replaces Home (two choices, video link,
    Needs you, current project with its real step and team, the embedded office, recent projects, publishing);
    navigation is Studio, Projects, Brain, Publishing, Accounts, Settings. `office/work.py` feeds your own work into
    the robots (queued, working, waiting for you, error, with a per-robot log of the last day), filtered by
    workspace; `office/roles.py` has the new rooms with `OLD_ROOMS` for old ids. Every robot including the Brain
    Core can be renamed (`office/RobotName.tsx`; `POST /api/robots/names/reset` needs `confirm`). Tests:
    `tests/test_office_owner_work.py`, `tests/test_office.py`, `tests/test_office_manager_handoffs.py`,
    `tests/test_studio_prefs.py`. Fast suite 1,733 passed on `c80bcb8`.
  - Dark design, Customize studio and accessibility (handoff section 3): dark only (`theme.css` has one set of
    tokens and four dark palettes; `public/appearance-boot.js` applies the saved choice before the first paint; a
    saved Light or System theme is dropped by `studio/prefs.py`, appearance schema 2, and every other choice kept).
    **Customize studio** (`components/Customize.tsx`) previews live and saves palette, accent, spacing, text size,
    motion and office animation, Studio panels (order, visibility, presets), editor panels, compact or expanded
    office and pinned projects; layouts are per device class (`layout:{desktop,tablet,phone}`, schema 2, older
    editor layouts kept). The office map stops drawing off screen; Calm and Low power office options. Keyboard fixes:
    the Make menu (shared `useMenu`) and the colour pickers (native radios). Also fixed: the editor crashed on
    videos made before guidance was recorded, and full videos starting with a sound file asked for a missing
    picture. Tests: `tests/test_theme_contrast.py` (11), `tests/test_studio_prefs.py`, `tests/test_studio_uploads.py`.
    Browser checks (scripted, Chromium, disposable data): 16 screens at 320–1440 px with two text sizes, and
    keyboard-only runs at 320, 390 and 1440 px with reduced motion. Fast suite 1,747 passed on `61492d0` (the code of this step; the last commits rebuild the app and add docs).
  - Brain map (handoff section 6, "Interface"): Brain → Notes now maps styles, skills, example videos and the
    projects that used them next to the notes, linked only by recorded facts (`studio/brain_map.py`,
    `GET /api/studio/brain/map`; project guidance snapshots and Example style provenance). Graph and List show the
    same records with filters, arrow keys and an inspector (effects, on/off, revision, projects that used it).
    **Save a style** is a new form (Brain toolbar and Styles tab). The idle glow is gone; only records applied in the
    last 15 minutes pulse. Tests: `tests/test_brain_map.py` (2); browser checks at 1440, 390 and 320 px.
  - Product name (handoff section 11): the Mac app's window, menus and messages, its Finder name and DMG volume, the
    Mac and Windows launchers and the phone page say ClipForge (`44647c5`). Bundle id, data folders, Keychain and
    DPAPI names, the `X-ClipFoundry` header and `CLIPFOUNDRY_*` keys are kept (no tested migration).
  - Step 7 checks (details in the matrix): fast 1,749 passed and slow 26/26 (audio, uploads, renders, restart and
    recovery), here and on GitHub's Linux runner. Mac app compiled, smoke-tested and packaged on a GitHub Mac runner
    (`macos-desktop.yml` run 8, artifact `ClipFoundry-Development-NOT-NOTARIZED`, 7 days; not a release). Browser
    suites compared with the starting commit: read-only 52 passed / 7 failed (the start's own failures), sandbox 84
    passed / 2 failed (both failing at the start). The comparison found three regressions, fixed in `e6e9380`: the
    office fallback map stopped drawing when a robot was queued, the Brain's Saved items lost their button role, and
    Missions claimed automatic uploads in review mode. Stale specs were updated (`5dca810`, `d3241f3`); discovery's
    retired setup specs are kept but not run, and `discovery-retired.spec.ts` checks those screens stay gone.
  - Step 8 release (details in the matrix and `docs/clipforge/WEBSITE_DEPLOYMENT.md`): Mac release
    `clipforge-mac-2026-11-05-6ecdafc` (192,306,837 bytes, SHA-256 `198706f3…3e6c5d`) from tested run 42050818316,
    published by run 42060598566;
    Windows `ClipForge-Windows-Setup.zip` at `raw/69a930e` (46,962,928 bytes, SHA-256 `89df9b2d…5ea84`) on
    `claude/clipforge-downloads`, with a new Windows install check (`windows-setup-check.yml`, run 42052332032:
    previous release, then this one over it, data and settings kept, close and reopen). Download page: `gh-pages`
    `138c4f7` (squash of PR #21 from `claude/download-page-2026-11-05`; same tree as the checked commit `89c922b`;
    previous `414ef86`), deployed by Pages run 42062766514. Rollback: revert `138c4f7` on `gh-pages`. The ChatGPT Sites
    page is unchanged (no access here).
- **Plan (handoff order):** ~~scalable media and multi-track audio editing with revisions~~ → ~~example-video
  analysis, applied Brain styles~~ → ~~Find media providers, bounded AI corrections~~ → ~~Studio/Home/Office and
  all-robot names~~ → ~~dark-only design and Customize studio~~ → ~~full checks (fast, slow, browser, recovery,
  audio) and native packages~~ → ~~release downloads and the download page (step 8)~~. Merging PR #20 and any real
  post still need the owner's OK in the project thread.
- **Not verified:** installing the DMG over an older copy on a real Mac and Gatekeeper, Windows 10/11 desktops and
  Defender/SmartScreen, video processing on Windows (the runner had no FFmpeg), a screen reader pass, live media
  provider APIs, real accounts and uploads.
- **Environment limits here:** no access to YouTube, Openverse, Wikimedia, Freesound or other media hosts (the proxy
  refuses them), so provider integrations are tested against fake transports only. GitHub artifact storage is
  unreachable too, so the Mac build's files were not downloaded here (release downloads and raw URLs do work).
  GitHub's hosted Windows runners work (the repository is public); actions/checkout cannot create the checkout folder
  there because the repository name ends with a dot, so the Windows check downloads its files from raw URLs instead.
  Git pushes from this session are accepted only for existing `claude/` branches, not for `gh-pages` or a new branch;
  the page went through a branch created with the GitHub tools and a PR into `gh-pages`. `*.github.io` is
  unreachable from here, so the live page was not loaded; the Pages run and the merged files were checked instead.

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

The owner asked to merge the changes, publish Windows and Mac downloads, and build a website that both Claude and
ChatGPT can update.

- **Merged:** PR #16 into `codex/cloud-plan` (`883913c`). PR #17 brought that into the default branch
  `claude/wonderful-ritchie-909tq3` (`c7d502f`). PR #18 fixed the Mac smoke checks for the new name (`0036e68`).
  Codex's automatic review of PR #17 and PR #18 reported no findings.
- **Mac build fixes:** the native smoke checks looked for "ClipFoundry" on the studio page. The second check read the
  page's visible text, which in a window narrower than 1024 px has no sidebar and so no product name. Now the page
  title must contain "ClipForge" and the studio's page heading must exist. These checks run only in automated smoke
  mode. The bundle ID, Keychain service and data folder still say ClipFoundry, and the Finder name stays ClipFoundry.
- **Release source:** both downloads are built from `06f459e`.
  - GitHub run 41899130825 passed the native Mac build, window, quit and force-quit checks, and the fast and slow
    pytest suites.
  - Locally, `a96781b` passed 1,630 fast and 21 slow tests; it differs from `06f459e` only in docs and the two smoke
    checks.
- **Windows download:** `ClipForge-Windows-Setup.zip` on branch `claude/clipforge-downloads` at `29c4a63`.
  46,661,349 bytes, SHA-256 `c1738e2975b346368f75725cc8a73f26cd12dffd574b29b9cffc16f2daabdb19`.
  - 77 launcher tests passed. All 675 app files match the commit, except six `.bat` files that differ only by the
    declared CRLF export. The managed-profile release history is kept.
  - Not run on native Windows, and Windows security acceptance was not tested.
- **Mac download:** release `clipforge-mac-2026-11-04-06f459e`, `ClipForge-Mac-Apple-Silicon.dmg`. 192,010,395 bytes,
  SHA-256 `1da040a23a88f73b9a800aeaa4f1d761808ba18363fc28c45241aaee5850b000`.
  - It is the unchanged tested artifact (artifact digest `9865d719…`), published by the input-driven
    `macos-personal-preview.yml`.
  - Unsigned personal preview: not Developer ID signed or notarized. Not run on a physical Mac.
- **Shared website:** https://landryschreiner33-coder.github.io/ClipForge-AI./download/ , from the `download/` folder of
  `gh-pages` (`414ef86`). Any assistant with push access updates it with an ordinary commit.
  - Data lives in `download/releases.json`. `python3 download/build.py --verify` downloads and hashes every listed file;
    all four matched.
  - The live page was checked at 1440 and 390 px, with no errors or sideways scrolling.
  - The root legal pages and the TikTok verification file are unchanged.
  - Procedure: `download/UPDATING.md`.
- **ChatGPT Sites page:** clipfoundry-studio.landryschreiner33.chatgpt.site still links the older ClipFoundry downloads.
  Only its own workspace (Codex) can publish it. Codex can point its buttons at the GitHub Pages page or at the two
  URLs above.
- **Not verified:** native Windows or RTX 3050 execution, physical Mac execution, real sign-in or uploads, and Windows
  Defender or Apple acceptance.

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

## ClipForge build checkpoint, phases 0–6 — 2026-11-04 (Claude Code, cloud session)

**Plain-English summary:** ClipForge is built and tested here on synthetic media and fake platforms. The app is
now called ClipForge. Home offers two choices, **Make clips** (Highlights or Full stories) and **Make a YouTube
video**. You can connect several YouTube and TikTok accounts, save styles, import editing skills, rename robots,
choose a theme, and run an owner-only, sign-in-protected server mode. The robot office and its robots are
unchanged, shown on the new dark stage and as a robot team on Home. Nothing was deployed, nothing was published,
and no real account or owner media was used.

- **Branch:** `claude/new-session-b9itcy`, draft PR #16 (not merged). Commits: `0f341c2` (phases 0–1),
  `c4bc2fc` (2–3), `b313647` (4), then this checkpoint (5–6).
- **What exists, by phase:**
  - Cloud mode with fail-closed startup: `clipfoundry/cloud/`, plus `deploy/`.
  - Sign-in: Google/OIDC, PKCE + nonce + state bound to the browser.
  - Sessions and guards: server sessions, CSRF, host/origin checks, rate limits and a strict CSP.
  - Encrypted secrets: AES-256-GCM, with the key file kept outside the data folder.
  - Workspace ownership is checked on every ID in an address.
  - Multiple social connections, migrated from the single account with tokens copied byte for byte
    (`social_connections`).
  - Resumable private uploads: `studio/uploads.py`.
  - Durable studio jobs with leases: `studio/jobs.py`.
  - Backup, restore and retention from the CLI.
  - Guidance precedence with frozen snapshots and "Used from your Brain": `studio/guidance.py`.
  - Styles and declarative skills: `studio/styles.py`, `studio/skills.py`, `docs/clipforge/SKILL_SCHEMA.md`.
  - Full stories: `pipeline/stories.py`, `studio/story_review.py`, with eligibility in `studio/eligibility.py`.
  - Full-video assembly on a versioned FFmpeg engine, with revisions: `studio/engine.py`, `studio/video_flow.py`.
  - New shell and pages: Home, Make clips, Make a YouTube video, Projects, Brain, Publishing, Accounts, Office,
    Settings → Appearance.
  - Theme, accent, density, motion and per-device layouts, synced through `/api/preferences`.
  - Robot display names.
  - The ClipForge rename. Data folder, database, Keychain/DPAPI names, settings keys, the `X-ClipFoundry` header and
    old addresses are kept.
- **Final fixes in this checkpoint:**
  - The earlier link/transcript Add video page is reachable again at `#/create/link`, linked from Make clips.
  - Old Clips/Queue labels and links now say Projects/Publishing.
  - Make clips previews its guidance with a GET (a POST was flagged by the read-only browser checks).
  - Loading robot names at start no longer redraws the page. That redraw threw away a file chosen in the first moment.
  - After Start Autopilot, setup opens the Office.
  - Motion stays the per-browser Animations choice; an account value no longer overrides it after a reload.
  - The sidebar is narrower below 1366 px, so the full office map keeps readable labels at 1280×720.
- **Status of each requirement:** `docs/clipforge/FEATURE_CHECKLIST.md` (42 requirements, CF-01–CF-17).
  - Partial: per-account spacing, full multi-user isolation (public sign-up stays off), full-video publishing,
    retention screen, saved layouts on Create/Office, one-click "make parts", per-job CPU/disk quotas.
  - Blocked: the FilmCraft build (this session's policy refused running third-party build scripts), model-based
    story analysis (no model configured), capacity benchmark (no server or footage).
- **Owner guide:** `docs/clipforge/OWNER_GUIDE.md`. Prepared website text (not published):
  `docs/clipforge/WEBSITE_COPY.md`.
- **Tests run here** (details in the 2026-11-04 rows of the `docs/IMPLEMENTATION_STATUS.md` test log):
  - Final fast suite: 1,628 passed. Final slow suite: 21 passed.
  - Sandbox browser specs: 95 of 100 passed. The three failures caused by this work are fixed and passed on rerun.
  - Read-only browser suite: 50 passed.
  - Every remaining browser failure (7 read-only, 2 sandbox) fails identically on the starting commit `6585c58`.
    These are stale assertions from earlier changes, left for a separate fix.
- **Not verified:** real Google sign-in, a real server deployment, real YouTube/TikTok uploads or transcodes, real
  camera footage with moving subjects, native Windows/RTX 3050 or Mac hardware, throughput per source hour, and the
  office under the cloud CSP in a real browser session.
- **Next action for the owner:** review draft PR #16. To try cloud mode, create a VM and an OIDC client, then follow
  `deploy/README.md`. To evaluate FilmCraft, approve building it (or run `scripts/filmcraft_experiment.py` locally).
  Run the owner-machine checklist at the end of `docs/IMPLEMENTATION_STATUS.md`.

## ClipForge implementation — session start 2026-11-04 (Claude Code, cloud session)

**Plain-English summary:** implementation of the ClipForge cloud studio prompt has started. Nothing in it
was built before this session. This entry records the real starting point; later entries above it record
each checkpoint as it is reached.

- **Branch:** `claude/new-session-b9itcy` (the branch this session must push to). It sat at the old default
  branch tip `8999e5f` and was fast-forwarded to `codex/cloud-plan` @ `6585c58` (the newest source line; it
  contains `codex/macos-native-app` @ `9e0aaee` and every earlier Claude/Codex fix). No uncommitted changes existed.
- **Newer fixes retained:** every remote branch was compared with `codex/cloud-plan`. The only branches with
  commits it lacks are `codex/clipfoundry-one-click` and `codex/macos-download-delivery`, which hold
  installer/ZIP delivery bundles, not app source (no `clipfoundry/` or `frontend/src` tree), plus older
  superseded experiment branches (`claude/ecstatic-shannon-wb1zq1`, `claude/clipfoundry-office-audience`,
  `codex/retro-robot-autopilot`, `codex/fix-autopilot-idle`) whose work landed through later merges.
- **State at start:** ClipFoundry desktop app (local FastAPI + React + SQLite). Cloud mode, login, workspaces,
  multiple social accounts, Full stories, full-video assembly, skills, ClipForge rename and redesign: planned only.
- **FilmCraft experiment:** the pinned source (`storytold/filmcraft@57dc82e`) was cloned and its README/NOTICE
  read. Building it (`cargo build -p filmcraft-cli`) was refused by this session's safety policy because it would
  execute third-party build scripts downloaded from the internet. Blocked: the owner must approve building and
  running upstream code (or run the harness on their own machine) before the integration can be evaluated.
- **Baseline tests:** the fast suite is being run on the untouched starting commit in a separate worktree so the
  result is not affected by new edits; the result is recorded in the next checkpoint entry.
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


Read [AGENTS.md](AGENTS.md), this file, [docs/OFFICE.md](docs/OFFICE.md) and
[docs/PLATFORM_CAPABILITIES.md](docs/PLATFORM_CAPABILITIES.md). Snapshot: 2026-10-23 (America/Chicago).
Fetch before trusting branch state.

## Latest continuation: Brain use, moving framing, spaced uploads and input reuse

Date: 2026-10-19 (America/Chicago). Base: `82784dd41463dc3559082b9c8e252e20051d789e`, on
`codex/brain-graph-quality-discovery`. The owner reports Brain not affecting clips, fixed framing, simultaneous
posting times and Queue asking again for supplied-video reuse permission. The supplied example note is
"Find strong standalone moments across topics for TikTok and YouTube Shorts. Prioritize:".

* Brain platform/workflow tags no longer require those literal words in spoken content. Remaining topic tags
  still narrow relevance. That example note supplies the recognized standalone ranking priority. Manual clip
  creation now retains actual ranking revision/decision snapshots, and rendering combines them with the
  supported caption/style guidance. The editor lists the lessons actually used. Disabled lessons, explicit clip
  edits, local raw-note privacy and reference-only unsupported prose remain unchanged.
* Auto framing uses measured motion/edge activity when face detection has no usable subject, including long
  tracking dropouts. Equally good visual crop windows centre the measured activity rather than pinning it to a
  crop edge. The framing cache version is 3. The final gate recognizes motion only with recorded analysis
  coverage/activity evidence and labels the result an estimate. Explicit Center/Manual and uncropped portrait
  frames remain steady. Existing files and old uploads are not silently rewritten or uploaded again.
* Default spacing is 30 minutes. A one-time migration repairs the old saved zero; positive custom gaps and later
  explicit choices survive. There is no new daily cap. Local replans serialize; pending automatic collisions are
  spaced without changing valid content approvals, owner-rescheduled times or started/uncertain sessions. A
  durable per-account atomic reservation also spaces already queued transfers after a restart/platform wait.
  Actual new starts refresh pacing after a long wait, and completions extend it after slow uploads. Rechecking/
  resuming the same logical transfer retains its identity; platform waits and all publishing gates bind.
* An existing unique source-submission record remains discoverable if an older intake refresh lost its marker.
  Queue can carry that input's reuse statement onto its exact new post, avoiding retyping during quality/manual
  review and ordinary text edits. It does not become a verified ownership/license rule or Brain knowledge.
  Auto-repaired generated output can receive fresh exact-file authorization only after new checks, with the
  generated metadata intact and no owner edit/cancel or selected alternate version. Input account/audience/kids/terms/source-byte binding,
  old-backlog exclusion, explicit blocks and TikTok per-post consent remain. A clip with no valid saved upload
  request still needs the owner's actual approval; a local file alone creates no grant.

**Validation:** Final full fast suite: 1,504 passed, 18 slow deselected in 687.23 s. All 18 selected real-FFmpeg/synthetic-media and restart cases passed: 15 in 766.75 s before stopping the remaining legacy zero-gap fixture wait, then its corrected three cases in 455.55 s. TypeScript/production build passed (6.03 s); all 61 built-browser checks passed in 170.29 s. All 204 other frozen Python/source/test/bootstrap/dependency files and 17 tested built files retain their hashes. Only the slow-loop fixture changed after the fast/first-15-media checks, to explicitly select zero spacing for compressed test time; all its three affected cases were rerun. Production source stayed unchanged. The final 205-file manifest matches the delivered source. The final source adds the reviewed alternate-version repair guard, covered by the final full suites and 62 focused checks; the already completed browser run covers unchanged frontend paths. Earlier full attempts stopped for evidence/pacing/version corrections are not final evidence. Actual moving-frame output, saved Brain ranking influence, input-bound reuse, concurrent/restarted pacing, platform waits and exact fake uploads were checked in disposable profiles. No owner profile, real social upload, native Windows/RTX3050 or 24-hour soak was tested.

The readable setup is pinned separately after this exact source checkpoint, retaining every prior managed
release identity and the historical blocked EXE unchanged. It includes the prior Python compatibility, audio,
submitted-video and TikTok icon fixes. Close the desktop app before updating; new framing applies to new renders.
Native Windows/RTX3050, the owner's actual Brain/profile and real YouTube/TikTok delivery are not verified here.
Public Pages remains at its separately deployed icon correction; this task does not redeploy public legal pages.

## Latest continuation: consistent TikTok app, website and tab icon

Date: 2026-10-19 (America/Chicago). Base: `4fae46c82f5b14e3a54c451dee7ff5e3d948b21f`, on
`codex/brain-graph-quality-discovery`. TikTok's reviewer rejected Basic information because its robot icon did
not match the older filmstrip on the public site and browser tab.

The unchanged submitted dark robot PNG (`design/tiktok/app-icon-dark.png`, 1024 x 1024 RGB, 9,382 bytes,
SHA-256 `b4dae127e333ec936c29acc6d9baabebda2caaf724689a2435591a7652e077fa`) now supplies the app's Logo and
favicon, all three legal-page headers and PNG favicons, and the current helper's single recommended download.
Legacy dark/light API endpoints remain for existing clients. Form packs contain `app-icon.png` and complete
website assets, including that exact PNG and an ICO with six nearest-neighbor frames (16 through 256 pixels).
The local `/legal/` allowlist serves those images with their proper types; no credentials or app data are exported.

Published the narrow branding correction to existing `gh-pages` as
`80a6a3f4782de64fed88a06d9db54533de4869bd`. The site's existing product/legal text, `.nojekyll` and TikTok URL
verification file are unchanged. [Pages run 39347822850](https://github.com/landryschreiner33-coder/ClipForge-AI./actions/runs/39347822850)
succeeded for that exact revision and reports https://landryschreiner33-coder.github.io/ClipForge-AI./ . All eight
published source files were read back byte-for-byte. Direct live-site HTTP is unverified because `github.io` is
outside this environment's network policy; exact-source browser checks and successful deployment were verified.
No desktop reinstall is needed to correct the public website. The existing readable installer remains pinned to
its earlier app revision; this checkpoint does not rebuild or replace it. The owner can use the exact published
`app-icon.png` in TikTok Basic information and resubmit. TikTok approval remains its own decision; no portal
submission, real account connection, scope change or post was performed.

**Validation:** TypeScript/production build passed (5.11 s). Final affected Python suites: 41 passed in 6.89 s.
Twelve Chromium checks cover all three public pages at desktop/mobile widths in light/dark mode; the built app
header, favicon, helper preview and download also match the exact submitted PNG. All six ICO frames match nearest-
neighbor canonical pixels. The broad fast run completed with 1,489 passed, one obsolete website-readiness fixture
failure and 17 slow deselected in 537.24 s. It had already collected the older fixture, which forbade added assets
and all image elements. The corrected fixture permits only the bundled canonical image and passes in both the
41-case affected-suite rerun and a final individual rerun. All 326 frozen code/test/build/website hashes match.
Exact published source readback and successful Pages deployment were verified. The media/Autopilot pipeline and
dependency/bootstrap files are unchanged; slow media and broad browser suites were not rerun for this branding
correction.

## Latest continuation: Windows Python selection and safe environment recovery

Date: 2026-10-19 (America/Chicago). Base: `fcd48aecece759ed676d871a9282d81b83f0ab92`, on
`codex/brain-graph-quality-discovery`. The owner reports pip cannot find a matching CTranslate2 distribution.
The screenshot alone does not identify the actual runtime, architecture or package index; do not assign an
unverified cause. Current CTranslate2 CPython 3.13/3.14 Windows AMD64 wheels exist. The app's supported Windows
policy is standard 64-bit CPython 3.12, then 3.11 (`win-amd64`, non-free-threaded); native ARM64/32-bit lack the
applicable wheel.

`start.bat` probes candidates by executing new standard-library-only `windows_bootstrap.py --check-python`,
instead of selecting a generic latest `py -3`. The readable source installer performs the same authoritative
check before app/profile writes and forwards the verified executable in `CLIPFOUNDRY_BOOTSTRAP_PYTHON`.
The app rechecks that interpreter and the actual `.venv` interpreter. Compatible `.venv` is reused; an
incompatible/unverifiable one is preserved as unique `.venv-backup-*`, then a fresh supported environment is
created and verified. Creation failures preserve partials under `.venv-failed-*` and roll back the old environment
where possible. Setup refuses to replace a known active environment and never kills its processes or deletes old copies.
If no candidate qualifies, install official 64-bit Python 3.12 side by side, then reopen; no automatic global
Python installation/removal, PATH/registry/security changes or owner-data deletion is introduced.

Brain, accounts, clips and the data profile are not migrated or rewritten by this repair. GPU/dependency pins,
frontend, media/rendering and submitted-video/Autopilot behavior remain unchanged. The installer artifact is pinned
separately after this source checkpoint; preserve managed-profile revision history and the historical blocked EXE.

**Validation:** Full fast regression suite: 1,489 passed, 17 slow deselected in 527.16 s. All 203 frozen source/test/bootstrap/dependency hashes matched. The 38 focused bootstrap checks passed in 3.54 s, including real disposable-host venv creation, reuse and replacement, preserved dependency markers/data, failure rollback, active-process and concurrency guards, exact runtime checks and read-only probes. A 19,230,360-byte CPython 3.12 Windows AMD64 CTranslate2 4.8.3 wheel was downloaded and its SHA-256 matched PyPI (b5daf0758d522a422c76e53eb02ce9f42465a9aba938a86b27249fb5db2571b9). No dependency/GPU pins, app pipeline or frontend files changed; all 17 previously browser-tested built files retain their hashes. The previous 17 media and 59 browser results apply to unchanged scopes and were not rerun. The readable setup is separately pinned to this exact app commit; its delivery proof records installer/helper tests, full source hashes, managed-release history and immutable download readback. A Linux cross-platform full pip dry run evaluates host markers and is not native Windows dependency
proof. The prior submitted-video release's 17 media and 59 built-browser checks below remain historical evidence
for unchanged scopes, not reruns for this setup repair. Native Windows CMD/process inspection/venv creation,
owner installation/RTX3050, real uploads, Defender acceptance and a 24-hour soak remain unverified.

## Latest continuation: submitted videos, Brain-guided creation and automatic YouTube upload

Date: 2026-10-19 (America/Chicago). Base: `ab666fd5f2c4ca9c84a4fe9a2e874bc852437231`, on
`codex/brain-graph-quality-discovery`. The owner replaces unreliable video finding with a link/file they supply,
then wants Brain-guided creation and automatic upload without per-clip approval.

Default `autopilot_input_mode=submitted` suppresses periodic/queued discovery and automatic watched-folder
admission. Existing sources, media, keys, Brain and post history remain. A one-time migration records this default
for old profiles without overriding a later explicit choice. Optional discovery is still selectable in Advanced.
Missions offers **Make & upload clips** and **Make clips only**, with actual per-input counts and hold reasons.

The upload action requires the actual connected YouTube channel, confirmed audience, genuine kids answer, source
reuse basis and one explicit checkbox. `source_submissions` stores its exact wording/options separately from
Brain/standing consent. A supplied file is copied to `data/submitted/<id>/`; acquisition binds original SHA,
project and current terms/credit. Accepted source/request creation is atomic; the scheduler recovers only an
unstarted enqueue gap, never deliberate cancellation. Retention preserves source rows referenced by submission
audits while clearing stale API metrics/cache and ordinary unused discovery rows. Re-adding an existing video
cannot grant old backlog access.
Guarded links need no search key; private/protected/unavailable/live media is not bypassed.

Relevant supported Brain notes and example preferences are consulted with source/spoken context and Settings
fallback, retaining explicit editor overrides. Raw notes/examples stay local; unsupported references and measured
example lengths are described honestly. Submission/reuse text never becomes Brain guidance or ownership/license.
Each qualifying new YouTube post gets an exact-file/payload approval labeled `by=submission`, tied to its input
request. It may schedule/dispatch despite broad scheduling/publishing/YouTube toggles being off, without changing
those globals. Old backlog and later inputs remain unapproved; local-only inputs create no automatic posts;
TikTok keeps per-post consent. Stop, Pause publishing, cancellation, source/hash/account/audience/terms drift,
credit, final quality, quotas/waits and active/uncertain upload recovery remain binding. Manual edits can require
manual review rather than being overwritten by automatic approval.

The prior downmix-before-normalization, final peak control, first-track and delayed/gapped-clock fixes remain.
Actual synthetic FFmpeg/AAC and exact fake-upload checks exercise the new path, including Brain-guided caption
rendering and restart without duplicate uploads. A limiter cannot reconstruct preexisting source distortion.

**Validation:** Final full fast suite: 1,451 passed, 17 slow deselected, in 676.07 s. Final full real-FFmpeg/synthetic-media and restart suite: 17 passed, 1,451 deselected, in 934.97 s. TypeScript and the production build passed (10.00 s). All 59 final built-browser checks passed in 161.55 s. The final fast suite used 198 frozen Python source/test files. All production and selected media-test sources stayed unchanged during the full media run; 81 frontend source and 17 built-file hashes stayed unchanged through the final browser checks. A deselected fast retention fixture's timestamp setup was corrected before the final fast run; the media run's production/selected sources were unaffected. Focused checks also passed: 60 submission/consent, 79 final status/routes/legacy readiness, 29 advanced-route/legacy, 119 legacy intake/scheduler/publishing, three new actual-media and 26 legacy audio/quality and nine retention checks. The three new media cases use relevant saved Brain guidance, real caption/AAC rendering, exact fake-upload bytes and restart without duplicates, including the broad YouTube switch off and TikTok enabled. Earlier full attempts were interrupted before the final route/status/retention corrections and are not final evidence. Tests use isolated profiles, synthetic media and fake platforms only. The readable source setup is pinned separately to this committed app tree with the tested frontend manifest; its delivery verification records exact archive hashes and source revision.
No owner Windows/profile/RTX3050, real YouTube transcode/account upload, Defender acceptance or 24-hour soak has
been verified. Prior release results below are historical, not proof for this new checkpoint.

## Latest continuation: failed search keys and separate post-only reuse records

Base: `0c2729d0a1e148e22da5bcdbd6db4ccb490dafa7`, on `codex/brain-graph-quality-discovery`.
The owner reports no clips and says both search keys fail; exact provider errors and owner-PC access were not
available. They confirm permission text appears only on the clip's approval/reuse details. That already belongs
to the exact post, not Brain; no automatic permission-to-knowledge leak was found or claimed.

YouTube discovery refreshes rejected same-account OAuth once, counting requests and preserving waits. Key errors
distinguish invalid/restricted keys and disabled APIs without reflecting credentials. No automatic credential
substitution occurs. A request lock protects the discovery allowance against concurrent probes. Copied outer key
whitespace is trimmed; new saves reject extra lines/control characters safely. Tavily server waits stay durable.

Settings → Integrations → Search connections adds explicit saved-connection tests. YouTube makes an uncached
general-quota read (one more if sign-in refreshes); Tavily reads `/usage` without running a search. Strict responses,
bounded repeated/concurrent checks, provider waits and credential-current results apply. GET stays read-only.
Only safe results/times and a private credential fingerprint persist. The tests cannot prove search quota,
downloadable originals or publishing readiness; no guaranteed-zero-credit claim is made for Tavily `/usage`.

Missions/health distinguish each provider's waits and review mode from reuse blocks. Failed configured searches
degrade health while independent sources continue; removed keys stop adding stale health failures. Forms/details
say reuse answers stay with those posts and never teach Brain. Single/bulk and learning regressions verify that
ordinary owner notes, all Brain evidence and exact-post approval remain separate and intact.

**Validation:** Final full fast suite: 1,373 passed, 14 slow deselected, in 755.18 s. Final full real-FFmpeg/synthetic-media and restart suite: 14 passed, 1,373 deselected, in 945.34 s. Final TypeScript and production build passed (5.17 s). All 51 final built-browser checks passed in 167.41 s, with all 17 built-file hashes unchanged. Focused provider verification: 77 passed in 7.83 s; focused diagnosis/health/phone: 88 passed in 11.26 s; independent saved-search/Brain separation checks: 113 passed in 22.43 s before the final wait-order correction, then 53 passed in 4.06 s including both same-key full-server-wait regressions. All 261 frozen production/frontend/Python-test hashes remained unchanged through final verification. Tests used isolated data, synthetic media, MockTransport and fake platforms. No owner keys, Windows profile/RTX3050, actual search-service account, real upload, Defender acceptance or 24-hour soak was verified. Permission answers were already post-only; the update clarifies and verifies that boundary.
Owner Windows/profile/keys and actual provider access remain unverified. Preserve prior fixes and managed-install
history; pin the source delivery only after the final commit and tested frontend export.

## Latest continuation: audio distortion, comments, ongoing search and live/Windows recovery

Base: `11bdb43523f9b01e82590d2dd9e67473d323c88d`, on `codex/brain-graph-quality-discovery`.
The owner confirmed distorted audio, comments disabled on some YouTube uploads, discovery stopping, and two
screenshots of Windows Proactor reset cleanup and split/ended live capture failures. The concrete Claude
continuation guide is [CLAUDE_HANDOFF.md](CLAUDE_HANDOFF.md); preserve its verification limits and owner-PC follow-up.

Real audio reproductions found default surround downmix and boosted gain clipping, lost delayed starts/gaps and
different transcription/render tracks. Downmix now precedes normalization, final latency-compensated peak control
follows gain, timestamps become real silence before processing and first-track selection is consistent. Existing
renders/uploads/transcripts are not silently rewritten. A limiter cannot restore distortion already in a source.

Made-for-kids values are strictly real booleans through all upload paths; malformed legacy/API values wait for
a real answer. UI explains kids/Private comment restrictions, returned YouTube audience flags are retained without
extra requests, and unknown comment availability points to Studio. No owner answers/visibility are auto-flipped;
the upload API has no enable-comments control. Provider-specific waits, capacity-aware recurring checks, bounded
five-page cursors and free feed refill prevent unrelated services and saved signals from stalling. Existing
encrypted YouTube/Tavily keys and free-only allowances are visible in Search connections; no new provider added.
When a busy queue drains, the persisted search deadline shortens as well as its interval; polling does not extend
the shortened deadline or alter an individual provider's wait.
Health and phone status use a pure cadence calculation. Only the periodic host updates deadlines/migration;
viewing status cannot change scheduling state. Existing phone database-unchanged checks remain binding.

Split HLS uses one guarded local A/V relay with common clocks/shared budgets. Empty ended platform captures have
finite, restart-safe public-archive recovery; partial timelines/project identity/single handoff remain intact.
The Windows handler finishes only the known native 10054 stdlib cleanup, supports differing Python detach
signatures, preserves other errors and restores handlers. Phone's own lifespan starts no desktop workers.

**Validation:** Final full fast suite: 1,278 passed, 14 slow deselected, in 579.81 s. Real-FFmpeg/synthetic-speech media and restart verification covered all 14 scenarios across two runs: the full attempt passed 12 with 2 repeat-discovery timeouts (1,274 deselected, 1153.68 s); after correcting only the compressed-clock fixture's discovery-list cache expiry, both private/public repeat scenarios passed in 374.57 s. This was not a single all-green full-media run. Production cache/quota policy and all real render, final-report, exact-upload-byte and restart assertions were unchanged by that fixture correction. Final production build: 10.32 s; TypeScript passed. All 43 final built-browser checks passed in 93.25 s, with all 17 frontend hashes unchanged. Focused independent bugfix verification: 73 passed in 32.22 s, including measured encoded mono/surround audio, exact fake-upload bytes, real split-HLS synchronization and real asyncio cleanup compatibility. Windows/phone focused verification: 63 passed in 10.25 s; earlier discovery focused: 89 passed in 11.12 s. The final queue-drain deadline correction and surrounding discovery checks passed 61 tests in 9.13 s. Final comments/search checks after the current-label correction: 47 passed in 22.85 s. The final read-only health/phone/search correction passed 77 checks in 16.64 s, with database-unchanged assertions intact. The complete media run used the final audio/live/publishing code, preceding only the pure health-cadence refactor and its four new fast tests; all 39 media-scope source hashes remained unchanged. That refactor is covered by the final full fast run and 77 focused checks. The earlier interrupted suites preceded final deadline/returned-label corrections and are not final evidence. No real owner Windows profile/media, RTX3050, live provider key, account upload or 24-hour soak was tested.
No owner Windows profile/media, native Windows/RTX3050, real provider key/account upload or 24-hour soak was tested.
Pin source delivery only after the final commit/build manifest; preserve earlier managed profile history and EXE bytes.

## Latest continuation: fast selected-post approval and consistent Brain use

Base: `ec20aec76825a284393af00d812ec4a08a8beca3`, on `codex/brain-graph-quality-discovery`.
The owner requested fewer navigation/typing steps and mass approval. Queue now provides inline video/full-text
previews, Quick approve, selection of visible YouTube posts (up to 50), and Approve selected. A fixed batch preview
shows actual posts, account, audiences and times. Reuse presets or one custom basis cover only the selected posts
that need assertions; one explicit combined consent covers the reviewed files/text/audiences/reuse. Missing
made-for-kids answers may be filled once, while existing answers stay intact. Single-post review shares these
presets and one combined consent. TikTok retains its individual platform review.

The owner also reports saved Brain notes/examples not affecting clips. Source title and spoken-word topic context
now follows candidate generation (including cached/resumed and live paths), ranking, blueprint and render. Tagged
example length is consulted after transcription, while per-candidate priorities avoid leaking unrelated transcript
topics. Natural caption declarations and named example feature fields are recognized. Bad-example observations
no longer promote unwanted traits; explicit corrective preferences remain usable. Settings fill unspecified
choices, owner duration bounds remain binding and explicit editor overrides win. Public lesson metadata/UI show
recognized effects and measured example length; unsupported material stays searchable without changing edits.
No video appearance recognition, new external model calls, raw-note transmission, old-media rewrite or publishing
permission is implied. The earlier docs/AUTOPILOT.md Brain-approval instructions were corrected to match save activation.

Batch previews are bounded in-memory snapshots with ten-minute validity, at most 64 entries and no future-post
grant. Expired/old entries are evicted on later previews or app exit. Confirmation rechecks actual bytes/version,
current source terms/credit, row/text/options, account/audience, posting mode/timing and passing final checks.
A final SQLite write guard prevents an active job/state change from being overwritten, with hashing outside the
write lock. Changed, blocked, unchecked, replacement or active/uncertain-upload work is skipped with a reason.
Each success receives its own manual approval and exact-post assertion if needed; repeated identical requests
return their prior result. No source is marked owned/licensed by a preset. Future arrivals are never selected
automatically. Partial success keeps failed selections for review and cannot silently retarget or rewrite posts.

Review-before-publishing stays the default. Required credit, file/media/grounding checks, explicit account/audience/
kids choices, exact approval binding, platform waits and duplicate protections remain. Selected due posts can start
after approval; disabled dispatch still waits for Publish now. The readable source setup must preserve verified
same-user managed profiles and the entire earlier application; do not recommend the blocked EXE or change security.

**Validation:** Final full fast suite: 1,195 passed, 11 slow deselected, in 739.22 s. Final real-FFmpeg/synthetic-speech media and restart suite: 11 passed, 1,195 deselected, in 1024.81 s. This includes exact selected-post fake uploads/restart and two actual Brain-guided/owner-overridden caption renders with persisted provenance. Final production build: 9.44 s; TypeScript passed. All 31 final built-browser checks passed in 95.78 s, with all 17 frontend hashes unchanged. Focused checks: 42 bulk, 19 independent approval audit and 86 Brain/context checks passed. Browser fixture wording/details visibility and async readiness were corrected before the final run; earlier interrupted or fixture-correction runs are not final evidence.
No owner Windows profile, native Windows/RTX3050, real account uploads or 24-hour soak was accessed or verified.

## Latest continuation: local schedules, owner reuse review and manual approval

Base: `d0b7102e8273cee068531da554c8d83f3fa43f8f`, on `codex/brain-graph-quality-discovery`.
The owner now wants preparation and scheduling followed by individual reuse review and approval.
`autopilot_review_before_publish` defaults on for new and existing profiles that have no explicit choice.
Accessible unblocked sources can enter the bounded quality-first queue without recorded reuse coverage;
their rights status remains truthful. Exact-file and grounded-text checks still precede local posting plans.
All new plans wait for owner approval. Standing YouTube permission is suspended in review mode. Future explicit
mode choices persist; approved-post dispatch, source limits, audience choices and other saved settings stay intact.

Queue shows proposed times with Needs review, separately from approved uploads. Review drafts do not expire after
48 hours. Uncovered posts additionally require an owner reuse statement and basis, bound to the exact post/source,
current terms and required credit, account, platform, audience, file/version, text and options. This assertion does
not create source ownership/license or cover another post. Required credit cannot be waived. Changes invalidate
the assertion and approval. Source-sound uncertainty is reviewable; physical-media failures still block use.
After explicit approval the existing scheduled dispatcher or Publish now can upload, with original audience,
made-for-kids/platform choices and exact-file, quality, duplicate and Retry-After checks.

Old automatic approvals for provably unstarted transfers return to review atomically with their payload, time,
privacy and publication identity preserved. A queued job cannot bypass the review guard. Retry and confirmed
not-published recovery require new owner approval in review mode. Active or uncertain outcomes keep their original
session; unknown outcomes use account-bound readback before local policy changes. Existing published videos and
saved media remain intact. Separate manual Publish cannot borrow a scheduled post's assertion.

If review mode is explicitly disabled, recorded coverage and separate standing YouTube permission again govern
automatic approval. Tests for that historical contract explicitly select it; new `test_review_*` suites exercise
the actual default. The inspectable Windows source setup remains the delivery route; preserve all verified prior
managed profiles and do not recommend the blocked EXE or change antivirus settings.

**Validation:** Final full fast suite: 1,112 passed, nine slow deselected, in 529.54 s. Final real-FFmpeg/synthetic-speech media and restart suite: nine passed, 1,112 deselected, in 879.93 s, including the new review/owner-confirmation/exact-byte upload/restart loop. Final production build passed in 8.79 s; 12 built browser checks passed in 40.23 s, with all 17 frontend file hashes unchanged. Focused checks: 95 publishing/reuse checks; 64 scheduler/public/manual checks; final 46 review/current-terms checks; 107 legacy recovery checks; and eight final independent audit/fixture checks. The initial full fast attempt found an older fixture approving an unverified channel claim; its corrected exact-video verification retains all connection, quota, hash, explicit-block and no-upload assertions. Earlier full attempts were stopped before final corrections and are not final suite evidence.
No owner Windows profile, RTX3050, real social upload or 24-hour soak was accessed or verified.

## Latest continuation: continuous eligible uploads and real Brain/manager activity

Base: `718358f30110ab871e21059177f83ccd9ea3d3a9`, on `codex/brain-graph-quality-discovery`.
The owner confirmed Missions reports missing reuse permission for the finished clips. That is a real posting
hold. Automatic broad discovery now defaults to uploadable sources for a connected destination, with verified
own/agreed channels before broad quota use, actual Creative Commons metadata checks and fixed source guidance.
Explicit public local imports remain available. Inactive old local-only picks cannot starve eligible work;
history and completed media remain saved. No permission is inferred from public availability or Brain prose.

App source/day, unique-clip/day and platform daily caps default to zero (unlimited), with 0–24 posting hours and
no forced gap. Work remains bounded per search and by active queue capacity, quality floors, API/cost allowances
and platform responses. A one-time recorded volume amendment updates prior app limits and existing YouTube
permission without changing its channel/audience/kids answer or creating a missing grant. Future explicit caps
persist. Historical posts/times and Private visibility remain unchanged. Continuous planning picks the earliest
eligible time; old past-due permission holds and lost replacement slots now recover. A reported platform zero
holds even an already-approved post until capacity returns, without touching an existing upload session.

Final checks bind to current reuse terms and required source credit. Stale terms, including a previously failed
sound-rights check, request bounded fresh checks. Required credit is checked in the actual upload payload;
missing credit returns an old post to editable review without replacing its text/privacy. Owner correction and
approval can update a provably unstarted publication snapshot, retaining its ID; started or uncertain transfers
keep their session/payload. TikTok mode and current features follow that unstarted approved snapshot too.
Manual edits, canceled jobs, existing post approvals and protected uploads cannot be silently repackaged.

Real saved-guidance use in selection, ranking, plans and renders records count-only consultation events.
Preview/graph/status reads remain read-only; disabled/empty/paused/canceled work emits no fake activity.
Brain consultation is distinct from mature-results learning, whose thresholds are unchanged. Fresh report and
checkpoint paths now pass through the responsible manager and boss, with linked real next work dispatched
through its manager. Explicit empty paths suppress inferred transfers. Newer held/rejected checkpoints cannot
reuse older approvals. Managers' own work/errors and unrelated workers keep priority; quiet rooms say why idle.
Pause, Reduced motion, hidden/offline/history guards and lounge recreation remain intact.

**Validation:** Final fast suite: 1,047 passed, eight slow deselected, in 556.14 s. Final real-FFmpeg/synthetic-speech
media/restart suite: eight passed, 1,047 deselected, in 836.38 s, including Public/Private fake uploads,
restart and live recovery. Final production build passed in 6.16 s; 11 final built browser checks passed
in 94.42 s, with all 17 frontend hashes unchanged. Earlier 12 choreography checks passed in 209.87 s;
six department, three motion and six lounge checks also passed. Final focused reuse/publishing checks:
93 passed in 90.79 s; public/manual publishing: 34 passed in 40.59 s. New reuse-context: 26 passed in
9.36 s. Independent continuous checks: 12 passed in 9.28 s; broader review batches: 60 and 83 passed
(one slow deselected), plus 17 packaging/artifact checks. Root phone checks: 56 passed in 9.06 s.
The first complete fast run passed 1,037 and exposed ten old fixtures assuming optional charts,
three-source plans or reports made before terms were attached; corrected cases retained all access,
Retry-After, permission, byte/version and quality assertions. Earlier office locator/route fixtures
were corrected to match actual consultation IDs, room-sign selection and manager paths. Controlled
screenshots/GIF are in design/robot-office/continuous. No actual owner profile, Windows/GPU or real
platform upload was tested.

No actual owner profile, Windows/RTX3050, real social upload or 24-hour soak was accessed or verified. The new
source ZIP must be pinned only after final tests/build and preserve verified earlier launcher-created profiles.
Do not recommend the blocked EXE or change antivirus/security settings. App publishing consent and exact-file,
reuse, quality, duplicate and Retry-After guards remain required.

## Latest continuation: finished clips reach YouTube scheduling

Base: `987ebb288ae9097bedbd80d0adee2b3c05c4271f`, on `codex/brain-graph-quality-discovery`.
The owner reported an all-day YouTube-only run with finished clips, no schedules/uploads and no Needs you.
The owner's actual Windows database was not accessed. Isolated reproductions identified and fixed these paths:

* Parked reuse-permission/file waits filled the six-find backlog forever; high-estimate local-only finds could
  take every daily attempt before reusable media. Bounded workable/parking lanes retain saved history and daily
  budgets while giving accessible, covered candidates priority. Explicit input and quality floors stay intact.
* Analysis waited for every render before fingerprint/package handoff. Each completed recorded output now hands
  off before any priority yield. Scheduler/maintenance recover bounded older proven outputs exactly once, using
  saved validated plans, selection evidence and existing files. Failed/canceled packaging and manual edits remain
  untouched. Live replacements finish their decisions first. Cancellation/Pause are rechecked after fingerprinting.
* A stored consent for a different channel/audience could suppress approval reminders even when unusable.
  Availability now controls reminders; existing Private plans retain valid original permission. Private automatic
  consent also requires a confirmed, non-local destination. Setup exposes audience confirmation and separate
  automatic YouTube permission together, filtered to connected platforms, with no automatic grant or audience change.
* Read-only posting readiness and derived setup warnings show post text, final checks, local-only rights and
  scheduling/permission holds even if the scheduler never wrote an action item. Recent stage counts sample at most
  200 finished automatic clips; the total counts all. An approved item without a posting time is a wait, not a schedule.
  Latest preparation state wins over older failures. Phone attention retains its fixed-description whitelist.

**Validation:** Final full fast suite: 958 passed, eight slow deselected, in 489.73 s. Final real-FFmpeg/synthetic-speech
media and restart suite: eight passed, 958 deselected, in 695.71 s, including Public/Private and live recovery
loops. Final production build passed in 3.98 s; seven built-interface browser checks passed in 43.6 s. All 17
tested built-file hashes match. Final focused handoff/readiness/simple-page checks: 88 passed in 24.79 s.
Discovery focused checks: 99 passed in 19.36 s; four new behavior regressions fail on the original source.
Scheduler/consent checks: 73 passed, one slow deselected, in 78.53 s. Independent review found the late-
cancellation race; its three corrected regressions passed and no material findings remain. No real owner data,
Windows/RTX3050, platform upload or 24-hour soak was tested.
An independent review's late-parent-cancellation finding was fixed and its three regressions pass. Earlier test
runs were stopped before that correction and are not final suite evidence. One UI test had an in-flight mocked
response disposed at teardown; seeding its status fixture before browser polling resolved it. The old plain-text
test now projects the visible posting title/detail rather than treating a machine stage enum as user text.
No real upload, account-permission change, Windows/RTX3050 execution, owner-data inspection or 24-hour soak is
claimed. The installer retains verified prior managed profiles; ordinary unknown ZIP profiles are not adopted.

## Latest continuation: private phone status dashboard

Base: `4838aa897e59b68a1365dd7ed7f4d60f52dfcc8c`, on `codex/brain-graph-quality-discovery`.
The owner asked to check ClipFoundry's progress from a phone. Settings → Integrations → **Check from your phone**
now controls an optional, default-off companion listener. Tailscale is the recommended private connection;
trusted home Wi-Fi is also supported, with an explicit unencrypted-HTTP explanation. The app never installs
Tailscale, signs into it, changes a firewall/router or rebinds the desktop listener. Literal private IPv4
binding and actual CLI desktop-port tracking preserve listener isolation, including restart/custom-port cases.

The separate FastAPI app serves only three phone assets, single-use pairing and an authenticated status snapshot.
Owner-only localhost controls enable/disable, issue a five-minute eight-digit code and revoke all grants.
Pairing attempts are rate limited globally and per peer. At most eight random device keys last 90 days;
SQLite stores only their SHA-256 hashes. Codes/keys never enter URLs or logs. Normal restarts retain grants;
disabling stops access, revoking removes grants. The phone uses session storage by default, opt-in local storage
for Remember this phone, and clears its displayed status/key after revocation/expiry. Disconnect clears that
browser only; the PC's Unpair all phones revokes copied keys too.

The mobile dashboard reports actual current work, measured/unknown progress, local-day unique clip counts,
separate platform-post counts, next planned post, posting queue and health statuses. It uses the desktop attention
policy, suppresses routine retry alerts and maps only fixed descriptions for derived account/worker/sleep holds.
No media, raw diagnostics, credentials, account identities, Brain text or desktop controls are exposed.
Polling pauses in the background, shows stale/offline readings plainly, backs off and resumes on reconnection.
Desktop setup ignores old polls after newer actions. [Setup and architecture](docs/PHONE_DASHBOARD.md).

**Validation:** Final full fast suite: 869 passed, eight slow deselected, in 386.91 s. Final focused phone tests: 55 passed in 9.03
s; 75 existing local-guard/office/Autopilot regressions passed in 30.43 s before the final attention refinement.
Final built phone browser suite: ten passed in 12.6 s. Final built desktop setup/race checks: two passed in 27.6 s.
Production build passed in 3.85 s; all 17 built-file hashes were recorded. No actual phone, Windows/Tailscale
connection or real account was tested.
The initial complete suite passed 865 checks before the attention-policy refinement. Independent review found
and prompted fixes for that refinement and an older-poll/new-action race. Media/Autopilot handlers are unchanged;
the slow media suite was not repeated for this feature. Native Windows, actual phone browsers, Tailscale account
connectivity, Windows firewall behavior, RTX3050 and real platform accounts remain device checks.
The bundled installer is pinned and integrity-checked separately on `codex/clipfoundry-one-click`.

## Latest continuation: automatic Brain guidance and useful integrations

Base: `28aee85b4ef239584da296cec900bc3d8dde4399`, on `codex/brain-graph-quality-discovery`.
The owner requested all saved Brain material to participate automatically, combined with Settings, and inactive
integration placeholders removed. This supersedes the older separate Brain-approval workflow below; publishing
consent and platform restrictions are unchanged.

Enabled saved notes, document text, explicit preferences and described examples are consulted for new clip
selection and rendering. A bounded local interpreter recognizes caption choices, continuous/safe-cut pacing and
known hook/payoff/context/ranking priorities. Explicit controls win over prose; instructions precede examples,
then references, newest saved item first. Settings supply missing choices. Good example durations blend with the
owner's original target by n/(n+3), capped at 60% and constrained by configured length limits. The original target
is retained between source/candidate stages so the hint cannot be counted twice. Selection provenance is copied
and merged by knowledge ID/revision, without mutating another clip's saved decision. Existing clips/posts remain
intact. Manual per-clip overrides win over Brain caption choices. Disabled/paused guidance stays inactive.

Brain shows recognized choices, ranking priorities, automatic activation and unsaved-draft status; it has no
separate approval button. Unrecognized material remains searchable, with actionable help. Raw notes/examples
stay local, no prose executes, and videos do not teach visual appearance or fine-tune a model. Only fixed known
priority labels accompany the existing excerpt sent to an already selected/authorized text AI. The NVIDIA
sending explanation and Privacy page describe this.

Integrations now lists YouTube, TikTok, Tavily, Wikimedia Commons and NVIDIA. Twitch, Kick, Reddit, X, Instagram,
podcasts and Google Trends placeholder cards are removed. Real connection, scope, audit, consent and quota holds
remain visible; no account permission or posting behavior was changed.

**Validation:** Final full fast suite: 814 passed, eight slow deselected, in 349.16 s. Final focused Brain/provider/blueprint/artifact regressions: 96 passed in 43.45 s. Actual-FFmpeg/synthetic-speech media/restart suite: eight passed, 811 deselected, in 710.71 s before the final example-blending/provenance review fixes; those final fixes are covered by the final 814/96 runs. Final controlled browser batch: eight passed in 45.5 s against the final built interface. Build passed in 6.44 s. No real uploads, accounts, Windows/RTX3050 execution or 24-hour soak were tested.
Early runs exposed old approval/placeholder assertions and a malformed new sentence fixture; these were
corrected without weakening write/local-only/platform guards. The first media run lacked the existing portable
speech fixture tool (three failures, four skips); the corrected environment produced all eight passes above.
The earlier 811-check run preceded three additional regression cases; it is not the final complete count.
The standalone local diagnostic collector is separately verified with portable PowerShell: GET-only/custom-port
snapshot, strict privacy whitelist, missing-app and invalid-port behavior. Native Windows remains unverified.
The installer carries this exact source snapshot and has a separate integrity record.

## Current scope and branch

Current work is on `codex/brain-graph-quality-discovery`, starting at
`8999e5fb29a0e1455d8fccff4037d6f089f9091b` from the default branch. PR #14 is merged. Its draft/unmerged notes and
test counts below describe historical checkpoints and are superseded by this branch's status.

The owner requested a finished app and Windows installer, simpler TikTok app setup, a visible Brain graph and
quality before quantity in discovery. Settings now includes **Help me fill out the TikTok app form**: copyable
details, the actual Desktop callback for the current local port, two 1024×1024 PNG icons, scope explanations and
a form-pack ZIP with local draft website/legal pages. Inbox uses `user.info.basic,video.upload`; Direct Post uses
`user.info.basic,video.publish`; optional statistics adds `video.list` and Display API. Applying choices, saving
Settings and reconnecting are separate steps. Existing permission choices are preserved until explicitly changed.
The helper prepares a draft only when opened. It checks URL format locally, does not submit a review or deploy pages,
and excludes app credentials,
tokens, account identities and owner media from the export. TikTok's personal-tool eligibility, Sandbox limits,
per-post consent and private-profile restriction still apply. See [the setup guide](docs/TIKTOK_APP_SETUP.md).

Brain now opens an interactive graph with saved notes, approved preferences, examples, shared topic tags,
recorded clip influence and result readings. Selecting a note or evidence opens its stored record and provenance.
Category/tag edges organize knowledge; influence edges identify the applied revision. Positions and glow are decorative,
not hidden AI thoughts. The graph is bounded to 160 saved items, 32 topics and 48 recent evidence records; list,
editor, history and full knowledge export retain access to the other saved data. **Add note** starts a simple note,
with an optional title derived from its text. **Teach preference** presents supported choices used automatically when saved enabled; the latest
continuation above supersedes its previous separate review/approval step. Documents and examples do not fine-tune a model.
The editor sends its displayed revision; stale edits return HTTP 409 and preserve the draft until explicit reload.

**Missions → Permissions & sources → Quality before quantity** enables focused broad-search discovery by default:
three new candidates per pass, six unfinished automatic search picks including `needs_rights`, one known creator
per pass and two per topic. The existing daily attempt budget remains three by default; weak outcomes do not
justify more attempts to fill the clip target. Explicit links, chosen folders/channels and manual work retain
their existing behavior. Scores and expected clips remain estimates until full analysis and final-file checks.
Optional Tavily setup explains its free 1,000-credit monthly plan without a card; saving a new key with the free
option explicitly sets the app allowance to 1,000 and its monthly spending limit to $0. Other settings are retained.

**Current validation:** the final full fast suite passed **804 checks**, with **8 slow cases deselected**, in
**429.01 s**; Python source is unchanged. All eight media cases are covered by seven initial passes (965.89 s,
one environment disk-capacity failure) and the unchanged live case passing in 48.81 s on workspace temp storage.
Final browser coverage is **52 unique checks across runs**: the initial 44-case batch had 42 passes/two failures
in 12.7 min; the final 11 changed-UI plus eight strict read-only Settings cases all passed in 1.1 min; the complete
loop passed in 7.0 min. Ten cases overlap between the initial/final batches. Lazy helper preparation fixes the
background preview request; one stale Public-visibility assertion was maintained without changing read-only
flows. Recorder/temp-storage environment fixes preserved the full loop. The latest build passed in **4.06 s**;
all 14 tested/captured file hashes match. Current graph previews came from the final run. Earlier interrupted
outputs are not final passes. Installer integrity is tracked separately on `codex/clipfoundry-one-click`.
Final results are recorded at the top of
[IMPLEMENTATION_STATUS.md](docs/IMPLEMENTATION_STATUS.md). See the
[desktop/mobile/empty graph previews](design/brain-workspace/README.md) for controlled-data provenance.
Windows execution, RTX 3050 CUDA/NVENC, real platform accounts/grants/visibility and an actual 24-hour soak remain
unverified. No real upload, account-permission change or website deployment is claimed by this checkpoint.

## Historical PR #14 scope and branch

The owner authorized merging PR #14 after one final pass on October 11. This pre-merge checkpoint follows
`51984a3`; check GitHub for the actual merge state. Independent review found no material blocker, and the
14 browser-tested frontend files still match their recorded hashes. The fresh targeted run passed 105 checks
and exposed one test-only race: inspecting log backups during an active rename. The test now takes the logging
handler's lock for its file snapshot; production code is unchanged. All 16 launcher checks passed in 0.72 s.
The fresh full fast suite passed **757 checks**, with **8 slow cases deselected**, in **301.90 s**.
The earlier real-media, browser, build and actual-app restart evidence remains applicable. Windows, real accounts
and an actual 24-hour soak remain unverified; merge authorization does not change those limits.

The preceding unattended-Public checkpoint started at `61f6042` on the then-draft/unmerged PR #14.
Work ran October 10–11.
The owner requested autonomous all-day Public publishing from a personal setup. Designed unattended YouTube operation
keeps explicit Public setup, account/visibility-bound standing permission, reuse eligibility, exact-file checks and
honest readback. Existing Private schedules stay Private; Public results need no Studio invitations. Midnight **0** now
survives scheduling/consent reads, so **0–24** covers the full day without changing daily limits.

Official YouTube `videos.insert`/`videos` documentation updated October 8 and freshly checked October 10 permits
Public uploads from unverified projects. The obsolete project-audit Public gate is removed; API audit concerns
quota increases. OAuth publishing status is separate: External Testing YouTube refresh grants expire after seven
days; choose Production, then reconnect. Personal use may be exempt from OAuth verification, but authorization can
still be revoked. TikTok retains eligible-app/per-post consent limits; a private TikTok profile cannot offer Everyone.
See [current platform evidence](docs/PLATFORM_CAPABILITIES.md) and [unattended setup](docs/UNATTENDED.md).

The optional `run-unattended.bat` / `python -m clipfoundry --unattended` watches app process exit and restarts with
bounded backoff. It preserves the selected data profile and saved Pause/permissions, owns its app/worker/media tree,
uses profile/port locks and stops without restarting on explicit Ctrl+C. Local app/watchdog diagnostics rotate at
5 MiB plus two older copies. Same-user Windows login startup is documented, never installed automatically.
Run only one app per data profile, including across different ports. This watchdog detects process exit; it does
not detect a still-running, hung main app.
Worker startup cleanup retains its lock until partial workers finish; setup failures do not keep phantom leases.
Bounded cancellable media pipe/process I/O and 2 GB disk-reserve checks keep low-space failures from blocking a
worker forever. Low-disk live capture waits without declaring EOF or deleting saved segments; final assemblies
replace complete recordings only after success.

Scheduled pre-session work rechecks Pause, current consent/account/audience and final quality even after a local
publication row exists. Existing sessions retain their confirmed bytes. Strict original-account, unique recent
submitted-metadata recovery reads actual visibility before reporting success. Final-chunk crash/cancellation or
ambiguous outcomes keep duplicate holds; manual startup recovery shows an unknown outcome with read-only Refresh.
Once final-byte evidence is saved, later reconnect, setup, scope or quota errors preserve that same hold and
publication identity rather than permitting another upload.
The real-media full-loop fixture now covers Public and Private independently, including repeat/restart/exact-byte
checks. This remains synthetic/fake-account verification, not real account or 24-hour operation proof.

Privacy documents local unattended diagnostic retention. No new dependency, real posting, account change, purchase
or deployment occurred. Windows/RTX 3050/accounts and an actual 24-hour soak remain owner checks. Deliberate rights,
quota, authorization, disk and unknown-outcome holds can still need attention; restarting does not bypass them.

The preceding department-office and reliability checkpoint starts at `e896632`, requested October 9 and completed
October 10 on the same draft/unmerged PR #14. Real working/reviewing jobs or substantive assigned backlog gather
the whole department into its own room. Actual workers appear immediately at their own desks; idle teammates sit
ready without typing, progress or invented jobs. Managers oversee from safe floor positions with clipboard checks
and brief pointing gestures; their own jobs and real report reviews take priority. Quiet paused/unavailable peers
may attend, but stale paused tasks, bare queue counts and unreferenced recurring timers do not summon a team.
A completed robot stays ready while another teammate has work, then resumes its reserved lounge activities.
Confirmed handoffs meet inside the receiver's office and return both robots to their latest department assignment.
A newer own job preempts carrying an older document out of its office. Actual badges and task details stay truthful.

The Brain's Processing animation now adds clipped holographic scans, travelling synapse trails, emitter sparks and
orbital light trails. Standby remains visibly decorative; Brain/global Pause, Reduced, hidden and stale views still
the art. Pixi and Canvas share department duties and supervisor cues. No dependency was added; the existing PixiJS
8.22.0 and GSAP 3.15.0 remain. [Latest department evidence and provenance](design/robot-office/departments/README.md).

The owner's full-code-review request also uncovered and fixed concrete backend faults:

* Job progress and host state now reject recovered lease owners and finished/pending jobs; recovery chooses an
  expired lease under the same write transaction as its update, protecting concurrent heartbeat/cancellation.
  Failed lock-file creation releases the in-process mutex, allowing the next GPU/startup lock acquisition.
* Final-check job identity includes the quality-rule version. Regeneration saves/restores the video and complete
  captions, transcript, edit decisions, render plan and thumbnail together. Interrupted rollback remains non-Ready
  until restoration succeeds, retaining its checkpoint on failure. Validated future plans are preserved.
* Brain edits use atomic revision checks, including enable/disable, so a delayed edit cannot overwrite a reviewed
  lesson or re-enable a disabled rule. Paused learning still collects results but preserves learned values and
  applies no cached learned weights/calibration. Confirmed audience drift is excluded from new cohort readings;
  prior observations keep their original provenance.
* Manual publishing checks linked-source rights, platform coverage, current quality/version and exact confirmed
  file bytes before a new transfer. Ordinary manual clips retain their existing workflow. Account binding survives
  TikTok options; emergency Pause also holds queued manual transfers while existing sessions may finish.
  An unknown manual YouTube outcome blocks another upload. Refresh status only reads the original account and
  requires one recent candidate with matching submitted metadata; ambiguity keeps the hold. Already-processing
  queue entries only read status. The Publish page exposes the hold and its refresh action.

Privacy documentation now covers local recovery copies and confirmed-file fingerprints. `.mcp.json`, GPU files,
Playwright versions and read-only `e2e/tests` remain unchanged. No real posts or owner account changes occurred.

The preceding social-pixel-office checkpoint starts at `5b1f7a9`: the owner requested better graphics tools and
off-duty games, food and drinks. Six authored gestures animate arcade controls, board-game pieces, mugs,
bites, page turns and stretches. There are 29 exclusive activity places, 25 stable cast homes and at most two
recreational walkers. Identity-phased routines rotate through free destinations; work and confirmed document
handoffs take precedence, preserve real references and clear leisure props. State badges remain authoritative.
The owner explicitly authorized stopped-office recreation even when those off-duty roles are marked Paused.
An individual pause while Running or an unavailable role remains quiet; global Pause, Reduced, hidden and stale
views freeze recreation. Recovery does not replay missed leisure time or old job stages.

PixiJS 8.22.0 now uses cached BlurFilter light pools and distinct arcade/café/game/sofa zones. New dependency
GSAP 3.15.0 supplies pure gesture-easing functions on the office clock, without independent timelines; its standard
no-charge license notice is included (it is not MIT). Native image generation produced the original bundled skyline.
Optional skyline loading is bounded to 1.5 seconds; failure/stall leaves procedural windows, and late completion
cannot mutate the scene. Cropped textures are destroyed without deleting the shared asset source. Canvas retains
simpler phase-driven gestures and a frozen Brain cue cannot change its pixels when activity expires. Lounge names
are staggered on the whole map and compact in the close camera. Portrait caching and all 25 identities remain.
[Current evidence, provenance and editing guide](design/robot-office/lounge/README.md).
This follow-up changes no backend, media processing or publishing behavior. PR #14 stays draft/unmerged.

The preceding living-office checkpoint started at `a119dfd`: the owner asked for believable proportions, idle robots in a
lounge, seated work, actual document transfers and an animated Brain. This supersedes idle-at-station placement.
The 960×640 floor plan now gives all 25 identities individual lounge seats, room-sized desks/chairs and walkable
aisles. `OfficeMotion.ts` follows current snapshots and fresh confirmed report/stage events: both robots approach,
one document passes between them, then both return to their latest actual destination. It never delays a backend
job or guesses a future transition. Paused/unavailable roles rest; Reduced skips walking; stale/hidden views freeze
and recovery uses the current snapshot without replaying old transfers. `BrainCore.ts` has layered neural lobes,
synapse lights and depth-sorted orbits: ambient **Standby** is decorative, **Processing** follows actual Brain
state/events, and Paused/Reduced/offline still the art. A room camera makes the furniture and robots inspectable.
The Canvas compatibility renderer now uses the same floor plan, seats and transfer controller.
Evidence: [living office and labeled controlled preview](design/robot-office/living/README.md).
This frontend-only follow-up adds no dependencies or processing/publishing behavior. PR #14 stays draft/unmerged.

The preceding visual checkpoint started at `c33a291`: the owner chose **refined retro pixel art** and asked to use better
graphics tools. The office now uses pinned PixiJS 8.22.0 with authored cast-specific artwork, layered room furniture
and a scoped studio shell. Team/detail portraits share one cached offscreen renderer. Existing job snapshots and
events still control states, walks, reports and decisions; this adds no processing or publishing behavior.
Graphics initialization/module failure restores the original Canvas map. Full / Reduced / Follow system remain.
The Windows install screenshot showed nested archive folders exceeding the standard path limit: use fresh ZIP
contents directly in `C:\CF14`, with `test-isolated.bat` there, creating a new `.venv`. Do not copy a partial environment.
The launcher now explains this when a long root may cause dependency setup to fail; no registry change is required.
Visual evidence and tool/edit instructions: [refined office](design/robot-office/retro/README.md).

Continue existing draft PR #14 on `claude/project-thread-vw1n9y`; keep it unmerged. This continuation started at
`fea045d` (previous code review `cf54204`). Default remains `claude/wonderful-ritchie-909tq3` at `eff96fb`.
The owner explicitly superseded selected-only new uploads and hiding idle robots. New Public uploads require
explicit setup/consent and eligible platform capability. Existing posts and scheduled Private uploads retain their
visibility. Never send test videos to owner accounts, buy hosting, deploy, or change account permissions.

## Historical PR #14 implementation

* All 25 robot identities remain individually visible at desks or reserved lounge places, with named labels and
  overhead state icons. Task selection includes shared references, dependencies, blocked reason and next robot.
  Saved motion choices: Follow system / Full / Reduced; Full overrides OS reduced motion. Stale state stops
  animation. Decorative recreation preserves actual state, work priority and genuine document handoffs.
* Brain at `#/brain`: durable searchable documents/instructions/skill guides, good/bad example uploads and feature
  labels, revision approval, edit/disable/delete/export, performance history and recorded per-clip influence.
  `autopilot/knowledge.py`, `knowledge_routes.py`, additive `brain_knowledge`/`brain_influences` tables. Uploaded prose
  is reference text, not executable code or model fine-tuning. Only supported approved caption/pacing preferences
  affect new blueprints; topic tags scope them. Examples never become posting results. Export includes all saved
  metadata/text/influences, without browsing caps; original uploaded files are downloaded separately.
* Demonstration: actual document upload + approval → later validated/persisted blueprint changes bold captions to
  minimal. Both instruction and bad-example later-plan regression tests pass. Screenshot/proof JSON record the
  saved decision; Try a decision is separately labeled a preview.
* Discovery: audience/topic terms, exclusions, language evidence, source-score floor and complete-story filter;
  curated/manual inputs retained. Metadata audience relevance and clip potential are estimates, not verified US
  viewers or promises of virality. Automatic repetitive/weak/unsuitable-live candidates are declined with reasons.
* Final check returns bounded repair work to SPLICE / GLYPH / STORY / QUILL with exact reasons and shared references.
  Two repair attempts maximum; uploads already using a file and user edits/cancellation are protected. Timestamp
  checks detect A/V offset and duration problems, not semantic lip sync. Missing sound is detected before Whisper;
  silent live segments are retained/skipped and later audio resumes; mixed final recordings retain returning
  sound with silent timeline gaps, temporary assembly files are removed, and all-video-only sources fail clearly once.
* New Public YouTube uploads and standing automation use explicit audience confirmation, connected-channel and
  visibility-bound permission, limits and exact-byte checks. Public lead is zero, so local
  uploads start at due time without `publishAt`. Existing Private schedules remain Private. Actual returned
  restrictions are reported. API-project audit status is informational; it no longer gates Public uploads.
  TikTok Everyone remains eligible-app + creator-options + per-post consent; inbox
  drafts/manual packages are honest fallbacks. No standing TikTok automatic consent.
* Learning separates confirmed-public and selected-viewer cohorts; unconfirmed/requested visibility does not drive
  learning. Both learners require 48-hour maturity. Cached weights/styles/posting-time data cannot carry over when
  the configured audience changes. Existing bounded updates, rollback, source diversity and sample guards remain.
* Measured real stage intervals: `/api/office/performance`, `python -m clipfoundry performance --days 7`.
  Pause/Stop controls are re-read atomically when the worker claims a job, preventing a stale preliminary
  state read from starting new work after the control was committed. Two deterministic regressions reproduced
  the old race and now pass. Database first-use migrations share a cross-process/thread lock and commit before
  another initializer reads the schema; old-project preservation and concurrent startup regressions pass.
  Separate Windows launcher `test-isolated.bat`: own `data\pr14-test`, videos, `.venv` and port 8899.

## Historical PR #14 validation

Latest unattended-Public validation is recorded at the top of
[IMPLEMENTATION_STATUS.md](docs/IMPLEMENTATION_STATUS.md). Full fast Python passed 757 tests, eight slow deselected,
in 390.67 s. All eight slow cases passed across the full run (six passed, two fixture setup failures, 786.85 s) and
the corrected Public (58.73 s) and upcoming-live (49.02 s) reruns. Production code stayed unchanged for those
corrections.
All 32 isolated browser cases passed together in 8.1 min. TypeScript/Vite build passed in 4.37 s; all 14 tested file
hashes match. Final fast verification includes the recovery, media, launcher, policy and unknown-outcome regressions.
The actual-app POSIX exit/restart/stop smoke passed in 11.98 s; Windows behavior remains unverified.

At the preceding department/reliability checkpoint:
[IMPLEMENTATION_STATUS.md](docs/IMPLEMENTATION_STATUS.md). Full fast Python passed 685 tests, seven slow deselected,
in 347.07 s. All seven slow media cases passed together in 676.84 s, with 685 fast cases deselected. All 31 isolated
browser checks passed together in 7.8 min. Final TypeScript/Vite build passed in 5.96 s with the existing 904 KB
lazy graphics warning.
All 14 build files and file sets match both tested and captured SHA-256 manifests. Routing/controller checks cover
3,844 + 36,304 routes, 600 virtual seconds and 150 mixed transitions. Actual Brain/supervisor pixels animate and
freeze in Reduced while true states update. All 32 touched/new code files meet 120 columns; whitespace checks pass.
Earlier 29/31-case browser runs each had one fixture/sampling failure, corrected without weakening the new-job
guard; the implementation log records their details separately from the final 31-case pass.
The new evidence has nine screenshots and one 37.40-second 1440×900 H.264 recording. Controlled work, supervisor,
Brain and handoff fixtures are visibly labeled separately from an actual stopped-sandbox lounge screenshot.
All 25 identities, laptop controls and mobile List/Studio layout were inspected, with no horizontal mobile overflow
and zero page/console errors. Evidence records all 14 captured production-file hashes. The recording documents
animation and confirmed-event choreography, not actual video-processing speed, Windows or RTX 3050 performance.

At the preceding lounge checkpoint:
The full fast suite passed **641 tests**, with seven slow cases deselected, in 280.30 s. All **23 focused browser
checks passed together in 6.4 min**. Final TypeScript/Vite build passed (5.83 s; existing lazy 904 KB graphics chunk
warning); all 14 distribution files are SHA-256 identical to the assets used in that final browser run.
Actual isolated desktop/laptop/mobile captures have 25 robots, visible laptop controls, no mobile horizontal
overflow and zero page errors. Both 1440×900 H.264 recordings have zero page errors: 33.24 s of actual stopped
off-duty animation, and 33.48 s of visibly labeled controlled work/Brain/stage fixtures. Only startup before the first
visible provenance banner was trimmed; animation was not retimed. Neither measures processing
speed. Prior slow media cases were not repeated for this frontend-only checkpoint.

At the preceding living-office checkpoint:
Production TypeScript/build passed; 17 office Python checks passed in 6.10 s and all 17 focused browser cases passed
together in 3.1 min. The browser cases cover lounge seats,
walk/sit/return, same-job document passing, event freshness/identity, Pause cancellation, Brain standby/processing/
pause, Reduced still frames, camera, fallback, portrait/navigation and desktop/laptop/mobile layout, plus current
sender recovery after hidden/paused stages and protection against reset-history replay. Evidence is
separated into actual isolated snapshots and visibly labeled controlled animations; neither is a GPU benchmark.

The preceding refined-art validation: TypeScript/production build passed, 17 office Python tests passed (7.20 s), and all ten focused motion/robot/
graphics browser cases passed together (59.3 s). Actual desktop/laptop/mobile captures recorded zero browser errors;
the separate animation video is visibly labeled as controlled test states. A pixel regression verifies COMMAND's
approval looks different from idle even in Reduced mode. Static floor/furniture is cached once; portrait cache is bounded.
The earlier 641-test and complete-media results below belong to `c33a291`; those suites were not repeated during
that refined-art checkpoint. Subsequent fast runs above are separate. Windows batch execution, PC graphics/scaling
and GPU checks remain owner checks. That refined-art checkpoint added only PixiJS; the latest lounge also adds GSAP.
Playwright and GPU pins remain unchanged.

The original master-continuation results below belong to the earlier `c33a291` checkpoint, separately from the
subsequent reruns. Its complete fast suite passed **641 tests** (263.21 s; seven slow cases deselected).
All seven slow cases passed across the full run
(six passed) and the corrected complete-loop rerun (one passed); the test now waits for both durable published
schedules before advancing fake result maturity. Ten browser checks passed across the sandbox run and targeted
Brain/Public-loop reruns. The Public browser loop includes two posts, restart, results, live capture and pause.
Production frontend TypeScript/build passed. Focused startup/core/office/TikTok: 66 passed; publishing: 44;
knowledge/public: 17; full Brain export: 8; public-audit/automation: 33; timing/office: 19; returning-audio/recovery: 28.
A database made using `fea045d` opened under the new additive schema with project/clip/settings/private
schedule/audience/approval and media bytes unchanged. No owner data was accessed.

Visual assets: [design/robot-office/screenshots/README.md](design/robot-office/screenshots/README.md). It distinguishes
actual isolated app/jobs, synthetic transcripts, saved blueprint decisions, lookup previews and controlled animations.

## External limits and remaining owner checks

Earlier October 8 developer-host requests returned proxy **403**; those verification limits remain historical.
October 10 official documentation was reachable and freshly checked: YouTube's October 8 update permits Public
from unverified projects, API audits cover quota increases, and External Testing grants have a seven-day lifetime
for YouTube scopes. Current sources and remaining TikTok restrictions are recorded in PLATFORM_CAPABILITIES.

Not verified here: RTX 3050 CUDA transcription / NVENC rendering; real accounts, scopes, quota grants and
returned Public visibility; TikTok app eligibility and approval, real Direct Post/inbox; Windows setup, fonts,
scaling; Windows Task Scheduler/process-tree cleanup; a real 24-hour unattended soak; live network access on the
owner’s PC; real NVIDIA services. Run the
[Windows test guide](docs/WINDOWS_PR14_TEST.md) in a separate copy first. No real posts, purchase or deployment occurred.

[Server recommendation](docs/PERFORMANCE.md): keep the PC until its real timing/GPU report supports a comparison;
a server can improve uptime but does not remove platform restrictions. No general randomized experiment system,
unique-viewer/dominant-video rule, new Twitch/Kick/Reddit/X/Instagram/podcast connectors or preview-before-download
screen was added. Knowledge controls are intentionally typed; arbitrary prose does not automatically alter decisions.

## Do not break

Keep `.mcp.json` and GPU dependencies unchanged; no Playwright pins. Preserve the owner-data browser tests'
read-only workflows and request blocker. One stale Integrations assertion now matches the already implemented
Public choice; it does not select an audience, grant permission or issue a write. Commit built `frontend/dist`.
Preserve exact-file quality/approval hashes, reuse eligibility, access guards, account-bound consent, limits,
duplicate prevention/recovery and emergency stop. No silent CPU fallback in Autopilot. Never fabricate processing
progress, metrics or visibility; keep decorative recreation visibly separate from actual job activity.
PR #14 is merged; follow the current scope and branch recorded above.
