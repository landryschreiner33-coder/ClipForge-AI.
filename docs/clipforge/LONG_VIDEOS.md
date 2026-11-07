# Long videos from big footage: imports, listening, the script and the cut

Written 2026-11-07 after Landry could not get 17 GB of footage into "Make a YouTube video" and found the edit it
made weak. This is what the code does now (branch `claude/project-thread-6ouxbx`); the tests named at the end hold
it.

## Why 17 GB did not work

1. **A file over 8 GB was refused** before a byte was sent (`uploads.max_upload_bytes`, the cloud limit used on the
   desktop too): "The file is 17.0 GB; the limit is 8.6 GB."
2. **Every byte went through the browser.** The desktop app runs on the same computer as the files, but a file was
   still cut into 8 MB pieces, sent over HTTP, written and synced piece by piece, hashed again and moved into the
   data folder: a second copy of everything, and slow.
3. **Everything was listened to up front, in one go**, when "Build my video" was pressed: each file's whole sound was
   read into memory and transcribed by a Whisper model loaded again for every file, with progress only per file.
   Closing the app in the middle lost the file being listened to; the smart edit only started when every file was
   done.
4. **ClipForge AI read at most 8 parts** of what was said (about 80 minutes of talk); everything after that was cut by
   the built-in rules alone, and the rules never looked across files (a take re-recorded in another file was never
   compared with the first), never fixed a slow opening or cut an outro, and always kept the media bin's order.
5. **Previews decoded the full originals** (4K footage decoded at 360p for every piece of every preview).

## Big footage

- **Use files where they are** (desktop only). "Add from this computer" (`GET /api/local/browse`,
  `POST /api/uploads/link`) lists the folders this computer has (home, Desktop, Documents, Downloads, Movies or
  Videos, external drives) and links a file into the media as it is: no copy, no upload. The asset's `path` is the
  file itself; everything ClipForge makes for it (its 16 kHz sound, transcript, proxy, thumbnail) lives in the
  asset's own folder under the data folder (`uploads.work_dir`), never next to the owner's file, which is never
  changed or made read-only. Its content id is a *quick hash* (`quick:` + SHA-256 of the size and three 1 MB
  samples), so adding the same file twice is one asset without reading 17 GB. A moved or deleted file is reported
  by the editor's existing check ("The original file … is missing"). Cloud mode refuses linking and browsing.
- **The upload limit on the desktop is the free disk space**, not 8 GB: a file larger than the space left in the
  data folder (minus a 2 GB reserve) is refused with the real numbers and the hint to add it without copying.
- **Listening is chunked and resumable** (`pipeline/transcribe.transcribe_long`): sound longer than 20 minutes is
  transcribed in pieces of about 20 minutes cut at the quietest moment near each boundary, each piece's result is
  saved as soon as it is done (`transcript.parts/`), so a restart continues with the next piece; only one piece of
  samples is in memory at a time; the Whisper model stays loaded between files and pieces and is released at the
  end of the job. Progress says the file, the position and the total ("Listening to clip 3 of 12 · 1:02:10 of
  2:15:00").
- **Files are prepared as soon as they are added** (`POST /api/assets/{id}/prepare`, job `asset_prepare`): sound,
  transcript and proxy are made in the background while the owner is still answering the questions, so "Build my
  video" finds most of the work done. The build job still listens itself to anything not prepared.
- **Proxies for previews** (`studio/proxies.py`): a 640-wide H.264 copy of each video larger than 1280 px wide or
  longer than 10 minutes (`assets.proxy_path`), used by preview renders only; final renders always use the
  original. Piece cache keys name the source, so a preview piece made from the original is never confused with one
  from the proxy. Setting `preview_proxies` (on by default) turns this off.

## The script

A script can be added with the footage ("Your script" on the Make a YouTube video page: a file or pasted text goes
through `POST /api/studio/scripts/parse`, and `POST /api/studio/videos` takes the result as `script`, or just
`{"text": …}`) or later from the editor page's **Script** panel (`PUT /api/studio/videos/{id}/script`, a new version
made in the background; `null` takes the script away and cuts from the brief again). Formats: `.txt`, `.md`,
`.docx`, `.pdf`, `.fdx` (Final Draft) and pasted text. The project keeps the script (`studio_projects.script`,
`video_flow.script_payload` checks it and numbers the lines again), the editor page shows it (`Video.script`), and
the plan records how each line was matched (`plan.script`). (`studio/script.py`, `studio/script_cut.py`)

**Reading it.** Paragraphs become lines; a long paragraph is split into sentences. A short line in capitals, a
`#` heading, `INT./EXT.`, "Scene 3", "Part 2:" or a short line ending in ":" is a **heading** (it becomes a chapter).
A line in [brackets] or (parentheses), or starting with "B-ROLL:", "VISUAL:", "SHOW:", "ON SCREEN:", "CUT TO" is a
**direction** (never matched to speech). "NAME:" at the start of a line is a speaker label and is stripped.

**Matching it to what was said** (`script.match`). Words on both sides are normalised (case, punctuation, numbers as
words, light stemming). For each script line the rarest words anchor candidate windows in every transcript; each
window is aligned word by word (longest common subsequence, in order) and scored by **coverage**, the share of the
line's words found in order. Coverage ≥ 0.6 is a take, 0.4-0.6 a weak take, less is no take. Among the takes of one
line the best is the one with the highest coverage, then the better **take quality** (fewer fillers and stumbles,
higher word confidence, fewer pauses inside), then the *later* take (people say a line again until it is right), then
the shorter one. A stretch of speech used by one line is not used by another; neighbouring lines found one after
another in the same recording make one continuous clip.

**The cut in script order** (`script_cut.assemble`). The chosen take of each line plays, in the script's order,
with a little room around its first and last word (never into the word before or after); neighbouring lines said
in one go are one clip ("Lines 3 to 4: …"), and every clip records its lines and each line's bounds (`take_of`). The
other takes stay in the sequence switched off right after the chosen one ("Another take of line 12 (80% of the
line, a few slips)"), and the Script panel's or the sequence row's **Use this take** swaps them (`use_take` edit:
the clip is split around the line, the chosen take plays there, the take that played is kept behind it switched
off, so the swap can be undone or made again). What was said but is no take of any line is kept switched off at the
end ("Not in the script: …"). Lines with no take are **missing** (no clip; the notes name them); a heading becomes
a chapter at its first line that plays. When nothing at all matches, the recordings play whole and the notes say
so. Pictures, music and sound effects come from the smart edit as usual. With a script, ClipForge AI's model is not
asked anything: the script decides what plays. Inside a take the pauses are not cut (a line is played as it was
said); Edit it for me without the script does that.

## A better cut without a script

All in `smart_edit.judge_sentences` (step 1 of the smart edit, also run before ClipForge AI is asked so what the
rules left out is not sent), then the rest of `smart_edit.build`:

- **Best takes across files** (`smart_edit.best_takes`). A line said again anywhere in the footage (another
  recording, or later in the same one; the sentence right after is a false start or a repeat, which `retakes`
  handles as before) is found through an index of the content words (a word said in more than 200 sentences is no
  clue) and confirmed by word-level similarity ≥ 0.8 on four or more words. The take said most cleanly plays
  (`script.take_quality`: fillers, stumbles, pauses inside, word confidence), the later one on a tie; the others
  are switched off in place ("another take of this line, said more cleanly in clip-b.mp4"). A line said more than
  three times is a catchphrase and every time stays. Must-keep words protect a take; `cut_retakes: false` turns
  this off with the rest.
- **Chatter** (`smart_edit.chatter`). In the first 20 s of a recording, a warm-up phrase ("is this on", "take two",
  "let me start again", `WARMUP_PHRASES`) or a throat-clearer of discourse words only ("okay so", "alright, let's
  go") is left out. In the last 45 s (or last tenth, whichever is longer), words to whoever is recording ("did we
  get that", "cut", `PRODUCTION_PHRASES`) are left out, and a sign-off ("thanks for watching", "see you next time",
  `SIGNOFF_PHRASES`) is left out unless the recording is the last one, whose ending is the video's ending. Greetings
  and "in this video…" are not touched: for most creators they are the real opening.
- **The cold open** (`smart_edit.cold_open`, brief `cold_open`, on by default). A video of two minutes or more opens
  with its strongest line as a short clip (`id: "hook"`, `hook: true`, labelled "Cold open" in the sequence),
  then plays from the beginning; the line still plays where it was said. The line is ClipForge AI's `hook` when it
  named one that plays, else the kept sentence with the best `hook_score` (what it carries, a question, a number,
  a hook or emotion word, 2.5 to 12 s long) after the first 15 s and inside the first 60% of the video, at least
  0.55; a weaker video simply starts. One Remove takes it out; Shorten the introduction skips it.
- **ClipForge AI reads all of it** (`ai_editor.advise`). The sentences the rules left out are not sent; the rest
  goes in windows of 6,000 characters (at most 64) with the story so far (the chapter titles found in earlier
  windows and how many sentences they held) until every window is read or the time budget is spent
  (`ai_edit_timeout_s` × 15, between 2 and 15 minutes; progress shows the seconds left). What was not read is said
  in `problems`, counted in `skipped_sentences`, and the rules decide those parts. Each window may also name the
  `hook`; the first named wins. The report (`plan.smart.ai`) says how many sentences it read and how many were not
  sent.

## Full stories: one clip per story, nothing to confirm

Landry's first case: a YouTube video of someone reading several Reddit posts. The old finder looked for pauses, a
few story-opening phrases and a change of vocabulary, held back every story it was not sure of ("waiting for your
check"), ended a story at its last sentence (the narrator's remarks between stories were thrown away) and titled it
with its first sentence ("Next story."). Posts read by a text-to-speech voice have no pauses at all, so most of them
were never split.

What `pipeline/stories.py` does now:

- **The narrator's own separators are learned from the recording.** A short phrase said at the start of a sentence
  three or more times, well apart ("Next story", "Story number N", "This one is from"), marks where stories change;
  numbering ("Story one", "the third story") is read in order. Explicit announcements (`STRONG_OPENERS`: *next story*,
  *posted by*, *r/…*, *AITA for*, *TIFU by*, *the title is*…) count as much as a learned separator; the ways a story
  tends to begin (*so this one time*, *years ago*) count less. Once the narrator's separators are known, a boundary
  anywhere else needs much stronger evidence, so a story is not cut in half at a long breath.
- **Silence alone never splits.** A pause adds to the score but never reaches the threshold on its own; a change of
  subject is measured against the chunk's usual cohesion, so a slow narrator is not split at every breath.
- **Updates and comments never split.** *Update:*, *Edit:*, *Top comment*, *Someone replied*… continue the story.
- **Intro, sponsor and outro blocks** are explicit when two such sentences run together.
- **Each clip runs until the next story starts.** The narrator's remarks after a story stay with it; only the intro,
  sponsor reads and the outro are kept out. The cut sits 0.4 s before the next story's first word when the pause
  allows, else in the middle of it.
- **Titles** come from the post's own title or the first real sentence, never from the announcement.
- **Every story is a clip at once** (`story_review.auto_clips` no longer looks at completeness); how sure ClipForge
  is stays a label on the card, and *Remake this clip* follows a manual change.
- **ClipForge AI's second opinion** (`stories.Judge`, only with a model set up): the places the rules are least sure
  of (near misses and weak boundaries, likeliest first, at most 60) are shown to the model six at a time with three
  sentences of context each side; a confirmed near miss becomes a boundary, a denied weak one is dropped; then it
  names the stories from their first words (a title is used only when its words were said). Everything is bounded
  by a time budget (five times the AI timeout, 1–10 minutes); no answer leaves the rules' decision, and every answer
  is written into the boundary's reasons.

Tested on a five-post Reddit reader with no pauses, an update, an edit, read-out comments, a remark after one story
and two long breaths inside stories (`tests/story_fixtures.reddit_reader`).

## Limits

- A script in another language than the speech matches poorly; the report says so (low coverage everywhere).
- Matching is by words, not by sound: a line read with many different words is "missing" even if the meaning is
  there; the owner can put the right take in by hand.
- Proxies are made once per file (one full decode); a 17 GB 4K file takes a while the first time.
- The real speech models and the built-in AI model cannot run in the cloud test container; the tests use fakes.

## Tests

`tests/test_studio_script.py` (parsing, matching, takes, the report), `tests/test_studio_script_cut.py` (the cut
in script order, Use this take, a script given with the video or later, the checked payload, transcripts in a
linked file's work folder and the released model), `tests/test_transcribe_long.py` (pieces, resume, boundaries,
the held model), `tests/test_studio_local_files.py` (browse, link, limits), `tests/test_studio_proxies.py` (proxy
made and used by previews, never by finals; needs ffmpeg), `tests/test_studio_smart_edit.py` (takes across
files, chatter, the cold open, AI windows, budget, hook and story so far), `tests/test_full_stories.py` (the
Reddit reader, the narrator's separators, the judge).
