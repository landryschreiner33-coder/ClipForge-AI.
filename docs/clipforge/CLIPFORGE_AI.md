# ClipForge AI: the brain and the chat (phase A)

ClipForge AI is the name of ClipForge's own AI: the built-in model (Qwen3-VL 2B, or Gemma 4 on bigger computers) or
the AI helper you set up, plus a **brain** that remembers what you tell it, what you did and what worked, and a
**chat** where you ask for changes, ask questions and teach it. The full plan (models, finders, makers, training) is
the Claude Doc "ClipForge AI: research and plan"; this file is the design of phase A, which this code implements.

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

**Meaning.** Phase A embeds with `hash-v1`: content words, stems and word pairs hashed into 256 numbers (feature
hashing with a stable hash, so a vector made today still matches one made last year), unit length, cosine
similarity. No download, no network, a few microseconds a memory. The plan's embedding model (Qwen3-Embedding
through the built-in engine) replaces it later; `meaning_model` records which embedder made each vector, the brain
check reports vectors made by another embedder, and **Rebuild** recomputes them.

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
| anything else, in the general chat | with an AI helper: a question to the model with the recalled memories, answered as `{"say": …}` (checked: a string, at most 1,200 characters); without one: what it can do on its own | the answer, and what it used |

A model answer runs in the background (`status` thinking) the way change requests do; the page polls the message.
Every `ai` message keeps `data.used` (ids and words of the memories it used) and `data.tool`. Limits: a message is
at most 500 characters, a chat keeps its last 200 messages, the general chat's AI answers count against
`ai_edit_requests_per_day`. Finding media, making music and settings in words come in later phases; the chat
says so when asked.

## API

- `GET /api/brain/memories?q=&kind=&project_id=&limit=` · `POST /api/brain/memories` `{text, kind?, scope?, project_id?, platform?, tags?}` · `PATCH /api/brain/memories/{memory_id}` · `DELETE /api/brain/memories/{memory_id}` · `POST /api/brain/memories/{memory_id}/confirm` · `GET /api/brain/memories/{memory_id}/uses`
- `POST /api/brain/memories/recall` `{query, project_id?, platform?, mode?}`: what it would use, with scores
- `GET /api/brain/memories/check` · `POST /api/brain/memories/rebuild` · `POST /api/brain/memories/tidy`
- `GET /api/brain/memories/export` · `POST /api/brain/memories/import` `{data}`
- `POST /api/brain/chats` `{project_id?}` (opens the video's chat, or the general one, with its messages) · `GET /api/brain/chats/{chat_id}/messages?after=` · `POST /api/brain/chats/{chat_id}/messages` `{text, base_revision?}` · `POST /api/brain/chats/{chat_id}/messages/{message_id}/apply` · `.../discard` · `DELETE /api/brain/chats/{chat_id}/messages`

Reads need a local (or signed-in) request, writes the app's own header, like the rest of `/api/brain`. Every id in
an address is checked against the workspace app-wide (`cloud/ownership.py`).

## Not in phase A

The embedding model download, finders and makers in the chat, settings in words beyond one video's own, a brain
shared with the online studio (export/import moves it by hand), the taste model and the editing adapter.
