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
5. **Build my video.** The plan drives the edit (below). It waits while files upload, and words typed but not sent
   are asked about first (send them, or build without them). The planning talk continues as the video's ClipForge
   AI chat, and the plan stays on the editor page ("Your plan"), where "Change the plan" and "Edit it again with
   this plan" make a new version that Undo takes back, with the plan it was made with. Only the parts you changed
   reach the brief, so choices made on the editor page (Edit it for me, ClipForge AI's reading) stay; the plan's
   music and voiceovers are placed again from the plan (a sound you moved, changed or made quieter by hand stays
   yours, and one you placed yourself is never placed twice; your own song on the music track keeps the plan's
   music, only ClipForge's own music makes way for it); a new file order is the order the video plays; the shape and
   captions are compared with the version you see. If that edit fails, or is canceled before it starts, the plan,
   the brief, the guidance the edits use (length, feel), the name and the order go back (files the edit added stay,
   after yours). Undo, redo and going back bring back the plan the version was made with, the brief values it set as
   they were then (also an editor choice the plan change had overwritten), the guidance made from them and, when the
   plan's order differs, the file order; a plan change still waiting for its edit no longer applies. Supporting
   media is only looked for at the build. A video made without a plan keeps its music and voiceovers as you left
   them.

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
| `length_min` | wanted length in minutes | 0.25–240; 0 = your style decides; -1 = as long as it needs | brief `target_duration_s` (fit to length; -1 sends 0: no fit) |
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
`notes` for ClipForge AI's edit prompt. The form for changing it by hand sends only the fields you changed since it
opened (a change ClipForge AI made meanwhile stays); a field you set by hand stays as you set it until a message
written after the change talks about that part again, so a hand edit made while ClipForge AI was answering stays too
(`setup.locked_at`, compared per part with the last message read that talks about it). An opening set by hand turns
the cold open on; "start from the beginning" (cold open off) clears the opening. Moving files by hand on the planning
page empties the plan's `order` and holds it like a hand edit (your order is the order, also against an answer
written meanwhile); a later message about the order lets ClipForge AI set it again, and then the plan's order is the
order.

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
- the owner's memories (every Brain rule that applies and the facts that fit the idea, 600 characters; none when
  the model is NVIDIA's, whose agreement says raw Brain notes are never sent) and the built-in know-how for the idea
  (600);
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
answer being written; what was planned before stays, and an answer that arrives after Stop changes nothing (it is
taken in under the same lock Stop takes, only while its message is still "thinking" and the video is still being
planned). An answer only looks up the video's chat, never makes one (`open_chat(create=False)`): a video deleted
while its answer is written gets no new, empty chat, and `open_chat` removes a chat it just made for a video deleted
in between. A request not yet sent is never sent. One already sent is told to stop when the assistant's
`llm.converse` (PR #37) carries the request; through `llm.complete` it runs to its end and its answer is dropped.
Up to three answers are written at once, so one draft's slow answer or a build that plans never waits behind
another.

**Without a model, or when the model fails**, the built-in rules read what the owner said: lengths ("10 minutes",
"under 5 min", "an hour"), shapes ("vertical", "TikTok", "square", "16:9"), feel words, how much to edit
("fast-paced", "keep everything"), music ("no music", "my song"), captions, "keep …", "cut …"/"skip …"/"remove …",
"start with …"/"open with …", "for my family", video types (vlog, tutorial, review, podcast …) and a story told
with "first … then … finally …". A story part stops where another instruction starts ("…the sunset at the end, and
use my summer song as the music" keeps the music out of the story). The answer says the rules answered, puts any
problem first, and says once how to set up the free built-in model.

Everyday ways of saying it count: "15 minutes for youtube", "10 minutes is good", "I'd say 10 minutes", "Length: 10
minutes", "not longer than 10 minutes" (9), "10 to 12 minutes would be great", "give me 10 minutes of the best bits";
"it should be vertical", "let's do vertical", "vertical works best", "horizontal for youtube", "make a reel";
"Let's call it Mom's 60th" and "Title: Lake Days" (the title keeps the apostrophe as typed); "I'd like you to cut…",
"can we cut…", "could we keep…", "I think you should cut…"; "for the background music, use beach vibes.mp3" (a sound
named in a sentence takes the role its sentence gives it); a story whose steps are things that happen ("set up the
tent", "make dinner", "add the beans"). Of two lengths, one said about the video ("make it 10 minutes", "a 10 minute
video", one on its own) beats one said only near "about" ("it's only like 20 seconds"); among those the last wins, and
"as long as it needs" is one of them ("as long as it needs, but no more than 15 minutes" is 13.5).

What the rules do not take as an instruction: a no that does not govern the word ("Grandma can't hear well and needs
captions", "no emojis in the captions", "no music and captions on"), a no about how or where rather than whether
("don't make the captions too big", "don't put the captions over our faces", "I don't want music with lyrics", "no
music during the vows"), how things are rather than what to do ("I hate when videos don't have captions", "I don't
have any music", "it feels empty without music"), two noes ("don't lose the captions" is a yes), "don't forget the
captions", "I don't mind music" and "can't wait for the zooms" (a yes), and "not sure about captions" (neither); a
keep or cut that is not asked for ("my dad tries to remove the hook", "we cut the cake"), while "don't ever cut the
sunset" keeps it, "don't include the gas station" cuts it and "you don't have to keep the sunset" lets it go; a
number that says how long the footage, a talk, a drive or a part is ("my footage is 2 hours long, I want a 15 minute
video" is 15; "my footage is 2 hours, make it 15" is 15 minutes; "I've got 3 hours", "the intro should be about 30
seconds", "we need to cut 20 minutes" and "hold on a sec" are none), a time in the video, "not 12 minutes" or "as
long as you like it" (meaning "if you like it"); "keep everything light and fun", "leave the drive as is", "don't cut
a thing from the first dance" or "don't trim my footage too much" (only the whole video kept as it is turns editing
off); a shape word about something else ("the old town square", "the landscape is beautiful", "landscape shots",
"fishing reels"); a list of changes told with "then" (no story) and "we call it a day" or "the locals call it the
blue lagoon" (no title). The words in front of a keep or cut are read in one pass (at most 16 of them), so a long
odd message never stalls the planner.

**Merging.** Each answer reads the owner's messages since the last one an answer merged: the newest, and any whose
answer was stopped or failed before it (Build, and the build job's plan, read all of them when nothing was planned
yet). The new plan is the old plan, then the model's reading, then what the rules read in those messages where the
model's reading of that part was not used (keep and cut only when the model changed neither list), then the fields
the owner set by hand (kept unless one of those messages, written after the hand edit, talks about that part; a
quick answer talks about what its question asked, stored as `data.about` on the owner's row). A model's reading wins
over the rules' (its 8 over the rules' 10), but a model never changes, without those messages talking about it, a
part the owner said in a message merged before or a part it silently emptied. Without a model, only those messages
are read on top of the plan, so a kept or cut item you took out by hand stays out.

**Questions** (only in "Ask me questions"): at most 3 on screen and 2 rounds per draft, never one that was asked
before or that the plan already answers. Without a model the rules ask, in the first round only, for what matters
and is missing: who it is for, the length, the feel. A quick answer answers its question and keeps the others asked
with it on screen (no new round; the answer says "One more question below, or press Just do it."); typing your own
message moves on and drops them, so no question stays to nag. A quick answer pressed in the ClipForge AI panel
counts the same way. "Just do it" on a question switches the mode and builds.

**Just do it** builds at once. When there is no plan yet, the build job plans after listening (so the plan uses
every word said), posts the plan to the chat, sets the brief and continues; the editor page shows it. When the build
cannot start (no video, say), the draft stays and the chat says why, so nothing is lost. **Build my video** before
ClipForge AI ever answered (its first answer was stopped) does the same: the rules read everything said (a part
you set by hand after the last message about it stays as you set it, in the build job's plan too), and the build job
plans with the model after listening when one is set up. A planning request in the build job that runs past its time
is given up (told to stop through `llm.converse`; through `llm.complete` it runs to its end and is dropped), and one
whose build is canceled is never sent if it had not gone out yet; a request that went out counts toward the online
daily limit either way.

## Drafts

A video is being planned here when `video_setup.is_draft(project)`: `studio_projects.status = "draft"`, a non-empty
`setup` and `workflow = "full_video"`. Another video can wait as "draft" too (an animated short stopped before its
first version, PR #36), so the pages, the Projects link and the chat route all use this check, and the video and
setup views carry it as `planning` (the editor page sends a planning video to its setup page, the setup page sends
any other video to its editor, and Build my video opens the editor, each in place of the history entry
(`router.redirect`), so Back never lands on a page that only sends you on). A draft has `plan_revision = 0`, no
build job, and `setup` = `{"mode", "plan", "idea", "locked", "locked_at", "rounds", "asked", "open", "style_id",
"reference_id", "remember", "owner_order", "pending", "consulted", "named", "source", "planned", "look", "by",
"plans", "made", "change"}` (`locked_at`: when each hand edit was made; `plans`: the plan each version was made
with, the last 30, for Undo; `made`: the brief and file order of those versions; `change`: a plan change whose edit
is running, to put back (with the brief, guidance, name and order) if it fails or is canceled; `open`: the questions on
screen; `named`: the owner named the video, so the plan's title no longer renames it; `source`: who wrote the plan
last, `ai` or `rules`; `planned`: a plan exists; `look`: the shape or captions a plan change after the build asks
the next edit to apply, then cleared; `by`: who pressed Build, for "Remember this style"). The bin is listened to
(`video_media` job) as soon as the draft exists and whenever files are added. The planning talk is the draft's own
ClipForge AI chat (`brain_chats` with its `project_id`): owner rows (`data.answers`: the question a quick answer
answered; `data.about`: the parts of the plan that question asks about), and AI rows with `data.tool = "plan"`,
`data.say`, `data.plan`, `data.lines`, `data.questions`, `data.ask` (the first open question, for quick replies in
the ClipForge AI panel), `data.source` (`ai` or `rules`), `data.sent` and `data.remote` (what was sent where),
`data.helpers` and the memories and know-how used. A model answer is written in the background
(`status = "thinking"`; the page polls every 2 seconds while it thinks or listens).

| Route | What it does |
|---|---|
| `POST /api/studio/videos/setup` | start a draft: files, idea, mode, name, style, example, script, remember, and `upload_ids` (the page's uploads of the files, which become the video's: `uploads.taken`) |
| `GET /api/studio/videos/{id}/setup` | the draft (or built video's) setup: plan, mode, messages, files with listening state, model |
| `POST /api/studio/videos/{id}/setup/say` | the owner says something (`text`, and `question_id` for a quick answer); returns the owner row, the AI row and the setup |
| `POST /api/studio/videos/{id}/setup/stop` | stop the answer being written |
| `PATCH /api/studio/videos/{id}/setup` | mode, plan fields by hand, name, style, example, remember, file order, script |
| `POST /api/studio/videos/{id}/setup/build` | build the draft (plans first in the job when there is no plan) |
| `PUT /api/studio/videos/{id}/plan` | after the build: change the plan and edit again as a new version |
| `GET /api/studio/video-setup/model` | whether ClipForge AI has a model to plan with, its name, on this computer or not |
| `POST /api/studio/videos/{id}/media` | (existing) add files, to a draft too; `upload_ids` as above, also for a file the video has already |

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

Text only: the idea, the conversation, the plan so far (with what the owner set by hand), file names, lengths, what
is said in the videos, the Brain rules and the other memories that fit the idea (never to NVIDIA), the built-in
know-how and the helper agents' notes (bounded as above). Never the video, the sound or file paths. Each answer
says whether it stayed on this computer or went over the internet, and to whom. Every planning request to an online
model counts against `ai_edit_requests_per_day` ("AI requests a day" in Settings → Advanced), also one that failed or
was given up on: `brain.allowance.take` (task `video_plan`) counts it just before it is sent, in the same count as
ClipForge AI's chat, its helper agents and their notes, and the editor's change requests, and at the limit nothing is
sent and the rules answer (`limit_reached`, `_take`); a model on this computer has no limit. A model request may take
`max(60, ai_edit_timeout_s × 2)` seconds, at most 300; in the build job it renews the job's lease while it waits.

## Tests

- `tests/test_video_setup.py`: the rules (lengths, shapes, feel, music, keep and cut, openings, stories and where a
  story part stops, and every misreading both reviews found, plus a long odd message read quickly), merging (the
  model's reading first, the rules filling what it did not use), what a message talks about, bounds on a model's
  answer, questions and carry-over, plan to brief, "as long as it needs".
- `tests/test_video_setup_flow.py`: a draft from files and an idea, talking, quick answers keeping the other
  questions, hand edits, files and order, Build my video, Just do it with and without a model and when it cannot
  start, a model answering in the background, broken and wild answers, the online daily limit, changing the plan
  after the build (your editor choices stay, the plan's sounds and order follow it, Undo brings the plan back, a
  failed edit puts it back), Stop with a late answer, a hand edit made while it thinks, Build after a stopped first
  answer, a stopped message read with the next one, hand edits kept by Build and the build job's plan, a quick
  answer letting the model change what it asked, files reordered while it thinks, a stopped request never sent, a
  canceled build that sends nothing more and counts what it sent, Brain notes never sent to NVIDIA, odd inputs, a
  failed online request counted, Undo and a failed or canceled plan change bringing back the guidance, the brief
  values and the file order, Undo while a plan change waits, sounds changed by hand neither doubled, dropped nor set
  back, a video made without a plan keeping its sounds, going back past any number of hand edits, the opening and fit
  to length, every route, and a message to a draft's chat from the ClipForge AI panel (runs when the assistant's chat
  routes are present).
- In a browser against `e2e/sandbox/run_sandbox.py` (temporary data, made-up transcripts): the whole flow on desktop
  and at 390 px phone width, words not sent and plan-form changes asked about before they are lost (and nothing
  asked when the form was not changed), with no console errors; the existing e2e app-shell and create/library suites
  pass.

## What the cloud cannot test

The built-in model's real answers, real footage, real speech and a real Mac. The tests use a fake model (fixed JSON
answers, a broken answer, a slow answer), synthetic transcripts and the rules; Landry's computer is the real test.
