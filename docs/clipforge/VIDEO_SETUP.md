# Make a YouTube video: drop in your files, tell ClipForge AI your idea, build

Written 2026-11-07 and 2026-11-08 for Landry's ask: "make the setup for the editing the youtube video better where
you drop in your stuff then tell the ai your idea for it and plan and stuff and it can ask questions or not". Branch
`claude/project-thread-2wwa4c` from the release line at 95a70e0. The tests named at the end hold what is written
here.

## What the owner sees

1. **Drop in your stuff** (Make → Make a YouTube video, `#/create/video`). Videos, pictures, sounds in one drop
   ("Add from this computer" on the desktop for big files, nothing copied), in the order they should play (up,
   down, remove). Each video is listened to in the background as soon as the draft exists, so ClipForge AI knows
   what is said in your footage while you talk to it.
2. **Tell ClipForge AI your idea**, in your own words (up to 4,000 characters): what happens, who it is for, how
   long, the feel, how it should open, the story in order, what to keep or cut, the music. The box can arrive
   filled in: `#/create/video?idea=…` (the ClipForge AI chat's "Make a YouTube video" button uses it).
3. **Questions, or not.** Two choices: "Ask me questions" (ClipForge AI asks at most three short questions at a time,
   and only about what it really needs; each has quick answers and a "Just do it" button) or "Just do it" (it never
   asks: it plans and starts editing at once). The choice is remembered for next time (the appearance setting
   `video_setup_mode`, which "Reset to defaults" in Customize keeps), and the planning page has the same switch.
4. **The plan.** The planning page (`#/create/video/<id>`) has the conversation on the left ("Talk it through") and
   the plan on the right, shown as a slate under the video's name: what it is, who it is for, length, shape, feel,
   how much to edit, how it opens, the story in order, what to keep, what to cut, music, captions, pictures, sound
   effects, zooms, the order of your files. The lines your last message changed light up for a moment. Keep talking
   to change it ("make it shorter", "no music"), press a quick answer, or "Change it by hand". Under the plan: your
   files with what ClipForge AI heard in each (listening, waiting its turn, nothing said, or "heard 312 words"),
   adding more files, and More choices (name, style and example, remember the look, your script).
5. **Build my video.** The plan drives the edit (below). The planning talk continues as the video's ClipForge AI
   chat, and the plan stays on the editor page ("Your plan"), where "Change the plan" and "Edit it again with this
   plan" make a new version that Undo takes back.

Leaving the page keeps everything: the video is a **draft** project from the first message on ("Planning with
ClipForge AI" in Projects; opening it, or its old `#/video/<id>` link, returns to this page). Drafts can be deleted
like any project (the "Add deleting projects" work: the draft's chat and its memories go with it, its listening is
stopped first, and ClipForge's copies of files nothing else uses are deleted after the confirmation names them).

## The plan

Stored in `studio_projects.setup.plan`; every field is optional, "" or empty means "from your style and Brain".

| Field | What it is | Bounds | Drives |
|---|---|---|---|
| `title` | the video's name | 120 chars | project name (unless you named it) |
| `summary` | what the video is, one or two sentences | 300 | ClipForge AI's edit prompt |
| `video_type` | "Travel vlog", "Tutorial" … | 80 | brief `video_type` |
| `audience` | who it is for | 120 | brief `audience` |
| `goal` | what it should do | 200 | brief `goal` |
| `length_min` | wanted length in minutes | 0.25–240, 0 = none | brief `target_duration_s` (fit to length) |
| `aspect_ratio` | 16:9, 9:16, 1:1, 4:5 | enum | brief `aspect_ratio` |
| `feel` | calm, balanced, energetic | enum | brief `feel` (joins) |
| `edit` | smart ("Edit it for me"), tight ("Fast-paced"), off ("Keep my clips") | enum | brief `smart_edit` |
| `opening` | how it should open ("the jump off the dock") | 200 | brief `open_with` (cold open) + edit prompt |
| `story` | the parts, in order | 8 × 160 | edit prompt; fit-to-length ranking |
| `keep` | words or topics that must stay | 12 × 80 | brief `must_keep` |
| `cut` | words or topics to leave out | 12 × 80 | brief `avoid` |
| `music` | auto, library, mine, none | enum | brief `music` (`mine` = your music file) |
| `music_file` | which of your sounds is the music | an audio file of the project | brief `music_asset_id` |
| `voiceover_files` | which of your sounds are voiceovers | audio files of the project | brief `voiceover_asset_ids` |
| `captions`, `pictures`, `sound_effects`, `zooms`, `cold_open` | on, off or "" | enum | brief `captions`, `broll_images`, `sound_effects`, `punch_in`, `cold_open` |
| `order` | your videos and pictures in play order | a permutation of them | the media bin's order (only while you have not reordered by hand) |
| `notes` | anything else to keep in mind | 6 × 200 | edit prompt |

`video_setup.plan_to_brief` turns a plan into brief fields; `brief.plan` keeps `summary`, `opening`, `story` and
`notes` for ClipForge AI's edit prompt. The form for changing it by hand sends only the fields you changed; a field
you set by hand stays as you set it until a later message talks about that part again.

## How the plan drives the edit

- **The brief.** Every brief field above, so length, shape, feel, captions, music, keep and cut work exactly as the
  old four questions did (the same validation, the same guidance snapshot, "Remember this style" saves the plan's
  look the way it saved questions 2 and 3).
- **ClipForge AI's edit** (`ai_editor.build_prompt`): every window starts with "The owner's plan for this video"
  (summary, how it opens, the story in order, notes; at most 700 characters) and the instructions say to follow it:
  leave out what does not serve it, choose the hook it asks for, name chapters after its parts.
- **The opening without a model** (`smart_edit.cold_open`): with `open_with`, the kept sentence that shares most of
  its words (at least half, said in 1.5 to 15 seconds) opens the video, anywhere in it, for any video of 30 seconds
  or more; the note says "the opening you asked for". Without a match the usual strongest line rules apply.
- **Fit to length**: a passage that shares words with the plan's summary, opening, story or keep list ranks higher
  (at most +0.15 on the 0–1 passage score), so the cut keeps what the plan is about.
- **Order**: the plan's `order` sets the media bin's order before the rough cut when you never reordered by hand.

## The planner (`clipfoundry/studio/video_setup.py`)

Every time the owner says something, ClipForge AI answers with a message and the plan, in one of two ways.

**With a model** (Settings → ClipForge AI: the built-in model, a local server or a key): one request, text only:

- who ClipForge AI is (the assistant's `persona()` when present, else a built-in line), how to answer;
- the files: number, name, kind, length; for each listened video its first words, its two strongest lines (by the
  smart editor's hook score, with their times) and its most frequent topic words; "still being listened to" for the
  rest (at most 3,000 characters, transcripts marked as data);
- the owner's memories (rules and facts, 600 characters) and the built-in know-how for the idea (600);
- notes from the owner's helper agents when the assistant offers them (`agents.consult(..., where="plans")`, once
  per draft, asked again on the next message while none could answer yet, 60 seconds, 800 characters). They are
  stored on the answer (`data.helpers`, the chat's own shape) and shown under it as "Notes from your helpers";
- the conversation so far: this chat's messages as turns (the owner's as "user", ClipForge AI's and helpers' as
  "assistant", 3,000 characters), as a real multi-turn request through `llm.converse` when the assistant brought it,
  else one prompt through `llm.complete`;
- the current plan as JSON, the fields the owner set by hand, the mode, how many question rounds were asked, and the
  questions still on screen with quick answers ("don't ask them again").

It answers one JSON object `{"say", "questions", "plan"}` (a JSON schema for the built-in model, so a small model
cannot answer in another shape; 1,200 tokens at most). The answer is data: every field is checked against the
bounds above, unknown fields are dropped, file numbers must exist, the order must be a permutation. "Stop" ends an
answer being written; what was planned before stays.

**Without a model, or when the model fails**, the built-in rules read what the owner said: lengths ("10 minutes",
"under 5 min", "an hour"), shapes ("vertical", "TikTok", "square", "16:9"), feel words, how much to edit
("fast-paced", "keep everything"), music ("no music", "my song"), captions, "keep …", "cut …"/"skip …"/"remove …",
"start with …"/"open with …", "for my family", video types (vlog, tutorial, review, podcast …) and a story told
with "first … then … finally …". A story part stops where another instruction starts ("…the sunset at the end, and
use my summer song as the music" keeps the music out of the story). The answer says the rules answered, puts any
problem first, and says once how to set up the free built-in model.

**Merging.** The new plan is the old plan, then the model's plan, then what the rules found said explicitly in the
newest messages (an explicit "10 minutes" wins over a model that wrote 8), then the fields the owner set by hand
(kept unless the newest message changes that field).

**Questions** (only in "Ask me questions"): at most 3 on screen and 2 rounds per draft, never one that was asked
before or that the plan already answers. Without a model the rules ask, in the first round only, for what matters
and is missing: who it is for, the length, the feel. A quick answer answers its question and keeps the others asked
with it on screen (no new round; the answer says "One more question below, or press Just do it."); typing your own
message moves on and drops them, so no question stays to nag. A quick answer pressed in the ClipForge AI panel
counts the same way. "Just do it" on a question switches the mode and builds.

**Just do it** builds at once. When there is no plan yet, the build job plans after listening (so the plan uses
every word said), posts the plan to the chat, sets the brief and continues; the editor page shows it. When the build
cannot start (no video, say), the draft stays and the chat says why, so nothing is lost.

## Drafts

A video is being planned here when `video_setup.is_draft(project)`: `studio_projects.status = "draft"`, a non-empty
`setup` and `workflow = "full_video"`. Another video can wait as "draft" too (an animated short stopped before its
first version, PR #36), so the pages, the Projects link and the chat route all use this check, and the video and
setup views carry it as `planning` (the editor page sends a planning video to its setup page, the setup page sends
any other video to its editor). A draft has `plan_revision = 0`, no build job, and `setup` = `{"mode", "plan", "idea",
"locked", "rounds", "asked", "open", "style_id", "reference_id", "remember", "owner_order", "pending",
"consulted", "named", "source", "planned", "look", "by"}` (`open`: the questions on screen; `named`: the owner named
the video, so the plan's title no longer renames it; `source`: who wrote the plan last, `ai` or `rules`; `planned`:
a plan exists; `look`: the shape or captions a plan change after the build asks the next edit to apply, then
cleared; `by`: who pressed Build, for "Remember this style"). The bin is listened to
(`video_media` job) as soon as the draft exists and whenever files are added. The planning talk is the draft's own
ClipForge AI chat (`brain_chats` with its `project_id`): owner rows (`data.answers`: the question a quick answer
answered), and AI rows with `data.tool = "plan"`, `data.say`, `data.plan`, `data.lines`, `data.questions`,
`data.ask` (the first open question, for quick replies in the ClipForge AI panel), `data.source` (`ai` or `rules`),
`data.sent` and `data.remote` (what was sent where), `data.helpers` and the memories and know-how used. A model
answer is written in the background (`status = "thinking"`; the page polls every 2 seconds while it thinks or
listens).

| Route | What it does |
|---|---|
| `POST /api/studio/videos/setup` | start a draft: files, idea, mode, name, style, example, script, remember |
| `GET /api/studio/videos/{id}/setup` | the draft (or built video's) setup: plan, mode, messages, files with listening state, model |
| `POST /api/studio/videos/{id}/setup/say` | the owner says something (`text`, and `question_id` for a quick answer); returns the owner row, the AI row and the setup |
| `POST /api/studio/videos/{id}/setup/stop` | stop the answer being written |
| `PATCH /api/studio/videos/{id}/setup` | mode, plan fields by hand, name, style, example, remember, file order, script |
| `POST /api/studio/videos/{id}/setup/build` | build the draft (plans first in the job when there is no plan) |
| `PUT /api/studio/videos/{id}/plan` | after the build: change the plan and edit again as a new version |
| `GET /api/studio/video-setup/model` | whether ClipForge AI has a model to plan with, its name, on this computer or not |
| `POST /api/studio/videos/{id}/media` | (existing) add files, to a draft too |

`POST /api/studio/videos` (the old one-step create) is unchanged for scripts and tests.

## Shared with the assistant (PR #37)

The thread "Make the built-in AI a real assistant" (branch `claude/project-thread-sa113l`, PR #37) rebuilds the chat
and adds tools and helper agents. This module uses its pieces when they exist and works without them, so either PR
can merge first (checked on 2026-11-08 by merging its d02bb25 into this branch: only `frontend/dist` conflicts, which
the second merge rebuilds; both test sets pass together):

- `brain.chat.route(applies, handle)`: registered at import, so a message to a draft's chat from the ClipForge AI
  panel goes to `video_setup.say`; the answer comes back in the chat's own message shape (`chat_id`, `updated_at`,
  `data.ask`, `data.sent`, `data.remote`, `data.helpers`, `data.used`).
- `brain.assistant.persona()` and `stop(message_id)`; `pipeline.llm.converse(settings, messages, …)` for a real
  multi-turn request.
- `brain.tools.register(Tool("make_youtube_video", …, risk="look", places=("general",)))`: in the general chat,
  ClipForge AI can show a "Make a YouTube video" button (`data.links`) that opens this page with the owner's idea
  filled in. It never starts a video by itself; the owner drops in the files.
- `brain.agents.consult(ws, task, context=…, where="plans", ref_id=…, budget_s=60)`: the helper agents' notes.
- The assistant's project list opens drafts at `#/create/video/<id>`, like Projects.

## Privacy and limits

Text only: the idea, the conversation, file names, lengths and what is said in the videos (bounded as above).
Never the video, the sound or file paths. Each answer says whether it stayed on this computer or went over the
internet, and to whom. Every planning answer from an online model counts against `ai_edit_requests_per_day`
(shared with the chat and change requests); a model on this computer has no limit. A model request may take
`max(60, ai_edit_timeout_s × 2)` seconds, at most 300; in the build job it renews the job's lease while it waits.

## Tests

- `tests/test_video_setup.py`: the rules (lengths, shapes, feel, music, keep and cut, openings, stories and where a
  story part stops), merging, bounds on a model's answer, questions and carry-over, plan to brief.
- `tests/test_video_setup_flow.py`: a draft from files and an idea, talking, quick answers keeping the other
  questions, hand edits, files and order, Build my video, Just do it with and without a model and when it cannot
  start, a model answering in the background, broken and wild answers, the online daily limit, changing the plan
  after the build, the opening and fit to length, every route, and a message to a draft's chat from the ClipForge AI
  panel (runs when the assistant's chat routes are present).
- In a browser against `e2e/sandbox/run_sandbox.py` (temporary data, made-up transcripts): the whole flow on desktop
  and at 390 px phone width, with no console errors; the existing e2e app-shell and create/library suites pass.

## What the cloud cannot test

The built-in model's real answers, real footage, real speech and a real Mac. The tests use a fake model (fixed JSON
answers, a broken answer, a slow answer), synthetic transcripts and the rules; Landry's computer is the real test.
