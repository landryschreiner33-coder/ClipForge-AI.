# ClipForge AI: the brain, the know-how and the chat (phase A)

ClipForge AI is the name of ClipForge's own AI: the built-in model (Qwen3-VL 2B, or Gemma 4 on bigger computers) or
the AI helper you set up, plus a **brain** that remembers what you tell it, what you did and what worked, built-in
**know-how** (what good editors know, as playbooks), and a **chat** where you ask for changes, ask questions and
teach it. The full plan (models, finders, makers, training) is
the Claude Doc "ClipForge AI: research and plan"; this file is the design of phase A, which this code implements.
The work that followed (the meaning model, the scout and judge, the eyes, the ears, your taste, Full stories with
meaning) is in [SMARTER_AI.md](SMARTER_AI.md).

Two rules hold everywhere:

- **One door.** `clipfoundry/brain/` is the only way memories are read or written. The chat, "Ask for a change",
  the FilmCraft pass and the smart editor all go through it, so nothing lives only inside a prompt.
- **Checked tools, never files.** The model answers in JSON that is checked against a fixed shape and limits (the
  existing `edit_requests.check` and `craft/ai.check_steps`); it never sees paths, keys, the video or the sound.

## The brain: memories

A memory is one row of `brain_memories`, in plain words, with what the model needs to use it well:

| Field | Meaning |
|---|---|
| `kind` | `rule` (a standing order: "never zoom on faces"), `fact` (about you, your channel, your audience), `episode` (what happened: a request and its outcome), `asset` (a track or picture it found or made, with its licence), `answer` (what a model answered and with which memories) |
| `source` | `said` (you told it), `did` (it watched what you did), `guessed` (its own inference), `imported` (from a brain file) |
| `confidence` | `said` 1.0, `did` 0.8, `guessed` 0.5. A guess expires after 60 days unless you confirm it (it becomes `said`). |
| `scope` | `all`, `project:<id>`, `platform:<youtube|tiktok>` or `mode:<clips|video>`. A memory is only recalled where its scope matches. |
| `text` | The memory itself, at most 600 characters. |
| `data` | Structured details (request id, proposal summary, licence, prompt), never sent to a model. |
| `meaning` | Its embedding (`meaning.py`), with `meaning_model` naming the embedder that made it. |
| `used_count`, `last_used_at` | Bumped every time an answer used it; `brain_memory_uses` records where (`change_request`, `filmcraft`, `smart_edit`, `chat`) and the id of that answer. |

**Meaning.** With the meaning model on and present (`clipfoundry/embedder.py`, all-MiniLM-L6-v2 on the CPU, see
[SMARTER_AI.md](SMARTER_AI.md)) a memory's vector is the model's 384 numbers, so a question finds the memory that
means the same thing in other words. Without it, `hash-v1`: content words, stems and word pairs hashed into 256
numbers (feature hashing with a stable hash, so a vector made today still matches one made last year), unit length,
cosine similarity; no download, no network, a few microseconds a memory. `meaning_model` records which embedder
made each vector; vectors from different embedders are never compared, the brain check reports vectors made by
another embedder, and **Rebuild** recomputes them with the embedder in use.

**Recall** (`brain.recall(query, ws, project_id, platform, mode, limit, budget_chars)`):

1. candidates: enabled, not expired, scope matches;
2. rules first: every matching `rule`, newest and most confident first, at most 8;
3. then the best other memories by `0.55 × words + 0.45 × meaning`, where words is the share of the query's content
   words found in the memory (weighted by how rare each word is in this brain) and meaning is the cosine; `said`
   +0.15, `did` +0.05, `guessed` −0.10, this project +0.10, used or made in the last 30 days +0.05; a memory needs a
   score of at least 0.2 to count;
4. cut to `limit` memories and `budget_chars` characters, rules never cut before facts.

`Recall.prompt()` is the block a model gets: "What the owner has told ClipForge AI (standing rules first):" and
one line per memory. `brain.record_use(ids, where, ref_id)` is called when an answer used them.

**Writing.** `remember(ws, text, kind, source, scope, ...)` de-duplicates: the same words (case and spacing
ignored) in the same workspace and kind update the memory (revision + 1, the stronger source and confidence win)
instead of adding a twin. `forget(ws, memory_id)` deletes a memory and its uses; an answer that used it keeps
its own copy of the words. `confirm` turns a guess into something you said. `export` gives one JSON file
(`clipforge.brain-memories/v1`); `import_` merges by id and revision (a newer file wins, nothing is deleted).

**Health** (`brain.check(ws)`): counts by kind and source, memories without a meaning or with an old embedder,
near-duplicates (same kind, cosine ≥ 0.92), guesses unused for 90 days, expired memories, the size on disk. The
Brain page shows it; **Tidy** removes the expired ones and merges exact duplicates; **Rebuild** recomputes meanings.
The existing backup includes the tables (they are in the same database).

**Privacy.** Memories never go to the finders. A remote AI helper sees only the memories recalled for that one
answer, and the disclosure line says so. `data` never goes anywhere.

## Where the brain is used

| Where | Gets | Writes | Recorded as |
|---|---|---|---|
| Ask for a change (`edit_requests`) | rules + facts + episodes of this project, at most 1,200 characters inside the 14,000-character request | an `episode` when a proposal is applied ("Asked … → applied as version N: …", `did`) or discarded | `change_request`, the request's id; the request's `memories` column shows what it used |
| The FilmCraft pass (`craft/ai`) | rules + facts, at most 800 characters inside the local 14,000-character request | an `episode` when the pass landed steps | `filmcraft`, the project's id |
| Smart edit's AI advice (`ai_editor`) | rules, at most 500 characters per window | nothing | `smart_edit`, the project's id |
| The chat | rules, facts, episodes, answers, at most 1,600 characters | rules and facts you teach it, episodes of what it did | `chat`, the message's id |

The guidance snapshot (styles, skills, examples, notes) is unchanged: it is structured and deterministic; memories
are words for the model. The Brain page's "Used from your brain" and a request's `memories` list show both.

## Know-how

`clipfoundry/brain/knowhow.py` is what ClipForge AI knows about editing before you teach it anything: thirteen
**playbooks** in plain words with the numbers an editor needs, distilled in November 2026 from two guides the owner
gave it (a cinematic filmmaking and post-production guide and a viral short-form video strategy guide) and from
ClipForge's own rules. They are built in (the same on every computer, never downloaded, never sent anywhere on their
own) and **the owner's memories always win over them**: a model reads the memories first, and the know-how block's
header says so.

| Playbook | What it holds | Read by default for |
|---|---|---|
| Hooks and openings | the first 3 seconds; the three things on frame one; loss or warning framing; plain words, 180-210 wpm | clip scoring, post packages |
| Endings and loops | stop 2-3 s after the payoff, no outro lines, calls to action in the middle, seamless loops | clip scoring, smart edits |
| Pacing and cuts | emotion, story, rhythm (Murch); J-cuts; shot lengths 3-6 s, never under 1.5 s; a change every 2-5 s (shorts) or 5-7 s | change requests, smart edits |
| Captions and safe zones | 1-3 words timed to the voice, stroke, accent colour; captions 45-55% from the top; the 15% / 35% / 11% / 28% the phone apps cover; 9:16 crop maths | |
| Voice and sound mix | the loudness order; the voice chain (high-pass 80-100 Hz, 200-400 Hz cut, 2.5-5 kHz boost, de-ess, 2.5:1-3.5:1); music ducking 3-5 dB, 150-250 ms; -14 LUFS / -1 dBTP | the FilmCraft pass |
| Music by mood | modes by feeling, tempo by mood, twelve scene types, hard sync and the 12-24 frames of silence | |
| Colour by mood | correct before grade; waveform and skin zones; lighting ratios; palettes by genre; 8-bit care | the FilmCraft pass |
| Effects that earn their place | the ranked list; every effect with its sound; pattern interrupts; hiding seams | the FilmCraft pass |
| Picking a clip | standalone, the tiny arc, completion and hook-rate numbers, shares and saves, seamless joins | clip scoring |
| Platforms and export | 1080x1920 H.264 High, closed GOP, Rec. 709, AAC 256-320 kbps; what each platform judges; the keyword in the first 3-5 s, 3-5 hashtags | post packages |
| Reading a retention graph | what each shape of the curve means and the fix | |
| Talking-head edits | pauses and takes, punch-ins, more than one speaker, pictures on cue | smart edits |
| Animated voice-over shorts | the hook in 2 s, one picture per 6-14 words with a push-in or pan, 175 wpm, concrete pictures with the same character and no words in them, only sure facts, the payoff and the loop | writing an animated short (with hooks and endings) |

**Picking** (`knowhow.select(query, task, limit, budget_chars)`): the share of the question's words a playbook
covers, rarer words counting more and the words a playbook is *about* (its title and its own word list) counting
twice as much as words inside its lines; a playbook not meant for the task counts for less; below a score of 0.2
nothing is picked by words, and the task's defaults (the last column) fill the list; then it is cut to `limit`
playbooks and `budget_chars` characters. `Picked.prompt()` is the block a model gets ("ClipForge AI's craft
know-how (built in; what the owner said always wins over it):" and one paragraph per playbook).
`knowhow.answer(query)` is the one playbook that answers a question on its own (score 0.3 or more).
`knowhow.principles(task)` is the one-line reminder each task carries in its instructions.

| Where | Gets | Budget |
|---|---|---|
| The general chat | the best two playbooks for the question, after the memories; without a model, `answer` replies on its own | 1,400 characters |
| Ask for a change | the best two for the request (pacing by default), after the memories; left out before the memories when a long video needs the room; the request's `knowhow` column records them | 900 |
| Smart edit's AI advice | the best two for the brief (talking heads, endings, pacing by default), before the brief of every window | 700 |
| The FilmCraft pass | the best two for the title (colour, effects, sound by default), after the memories | 1,500 |
| Writing an animated short | the best three for the topic (shorts, hooks, endings by default), after the memories (recorded as used in "short_script"); see docs/clipforge/ANIMATED_SHORTS.md | 2,000 |
| Clip scoring, post packages | the principles line only | |

The Brain → Memory page lists every playbook (`GET /api/brain/memories/knowhow`); an answer's "From its know-how"
line names the ones it read. The deterministic editors apply the numbers directly (see the changelog): outro lines
are a weak ending and a poor opener, loss or warning framing and short plain headlines score higher as hooks, the
hook headline sits below the apps' top bar and shrinks to fit, "bottom" captions sit above the 35% the apps cover,
the voice chain uses the dialogue numbers, clips are converted and tagged BT.709 and delivered with a keyframe every
half second and 256 kbps AAC.

## The chat

`brain_chats` (one per video, one for everything else) and `brain_chat_messages` (`role` owner | ai, `text`,
`data`, `status` done | thinking | failed). `brain.chat.send(ws, chat_id, text)` understands these without a model
(rules first), in this order:

| You say | It does | It answers with |
|---|---|---|
| "remember …", "always …", "never …", "from now on …", "I like/want/prefer/don't want …" | `remember` as a `rule` (`said`); "for this video" or "here" scopes it to the video | "Remembered: … It applies to every video / this video." |
| "forget …" | finds the closest memories; deletes one only when your words match it exactly | the candidates, each with a Forget button |
| "what do you know / remember …", "what have you learned" | lists the best memories for the words after it (or the newest) | the list |
| "why …", "what did you use", "explain" | the latest answer for this video (change request or FilmCraft pass): its summary and the memories it used | the explanation |
| anything else, in a video's chat | `edit_requests.ask` (rules, then the AI helper) | the proposal: Apply as a new version, Discard; a question with choices; or why not |
| anything else, in the general chat | with an AI helper: a question to the model with the recalled memories and the know-how that fits it, answered as `{"say": …}` (checked: a string, at most 1,200 characters); without one: the playbook that answers it, or what it can do on its own | the answer, and what it used |

A model answer runs in the background (`status` thinking) the way change requests do; the page polls the message.
Every `ai` message keeps `data.used` (ids and words of the memories it used), `data.knowhow` (the playbooks it
read) and `data.tool`. Limits: a message is
at most 500 characters, a chat keeps its last 200 messages, the general chat's AI answers count against
`ai_edit_requests_per_day`. Finding media, making music and settings in words come in later phases; the chat
says so when asked.

## API

- `GET /api/brain/memories?q=&kind=&project_id=&limit=` · `POST /api/brain/memories` `{text, kind?, scope?, project_id?, platform?, tags?}` · `PATCH /api/brain/memories/{memory_id}` · `DELETE /api/brain/memories/{memory_id}` · `POST /api/brain/memories/{memory_id}/confirm` · `GET /api/brain/memories/{memory_id}/uses`
- `POST /api/brain/memories/recall` `{query, project_id?, platform?, mode?}`: what it would use, with scores
- `GET /api/brain/memories/check` · `POST /api/brain/memories/rebuild` · `POST /api/brain/memories/tidy`
- `GET /api/brain/memories/knowhow` (every playbook and its source) · `POST /api/brain/memories/knowhow/select` `{query, task?}`: what it would read, and the playbook that would answer on its own
- `GET /api/brain/memories/export` · `POST /api/brain/memories/import` `{data}`
- `POST /api/brain/chats` `{project_id?}` (opens the video's chat, or the general one, with its messages) · `GET /api/brain/chats/{chat_id}/messages?after=` · `POST /api/brain/chats/{chat_id}/messages` `{text, base_revision?}` · `POST /api/brain/chats/{chat_id}/messages/{message_id}/apply` · `.../discard` · `DELETE /api/brain/chats/{chat_id}/messages`

Reads need a local (or signed-in) request, writes the app's own header, like the rest of `/api/brain`. Every id in
an address is checked against the workspace app-wide (`cloud/ownership.py`).

## Not in phase A

The embedding model download, finders and makers in the chat, settings in words beyond one video's own, a brain
shared with the online studio (export/import moves it by hand), the taste model and the editing adapter.
