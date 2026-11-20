# Story clips: Full story, Story parts, five minutes at most, a still picture

Landry's case (Nov 7–8 2026): a creator reads Reddit posts aloud while he plays a game. Three things were wrong with
the story clips ClipForge made from such a video:

1. **The camera moved.** Story clips followed faces and motion and pushed in, so the gameplay jumped around and was
   cropped. Landry wants the picture centred and as much of the gameplay as possible, never distorted.
2. **Full stories split the stories.** On 40 synthetic recordings of this kind (four posts each), the release line
   made between 9 and 21 clips, 15 on average, instead of 4.
3. **There was one setting.** Landry wants two: *each clip is the full story*, and *find the best places to split
   each story and make the parts separate clips*. And no story clip may be longer than five minutes: a longer story
   is split, whatever the setting.

## Why stories were split, and what changed (`pipeline/stories.py`)

A gamer narrator stops talking for seconds all the time (median pause about 2.5 s, often 4 s, sometimes 10 s), talks
about the game in the middle of a post, and the posts themselves say things that look like a story starting
("A few years ago…", "Back in high school…") or ending ("To this day…", "And that's why…"). The old finder counted a
pause of 3 s as strong evidence, read a change of vocabulary as a new story, took "Today I…" in the middle of a post
for the video's intro, and let ClipForge AI's model add a boundary wherever it said "new story".

- **Pauses count relative to the narrator** (`story_parts.rhythm`, `pause_weight`): a pause is a break only when it
  is long *for this recording* (at least 2.5 × the median pause and the 97th percentile), partly between the 90th
  percentile and that. A gamer's usual 2–4 s pause is no evidence at all.
- **A boundary needs words, not only a gap.** A place is accepted only when something *says* a story starts
  (`_boundary`, "explicit"):
  - a strong announcement ("first story", "next one", "Okay, last story, this one is from r slash…", AITA / TIFU
    titles, "posted by");
  - an intro, sponsor or outro *run* starting or ending: such material comes in runs of sentences, so one sentence
    inside a post that happens to say "discount" is not a sponsor read;
  - a post's title read straight ("My (25F) sister-in-law ruined my wedding", without "AITA") where everything after
    it is about something else, which also adds 0.25 to the place's score;
  - a pause that is long for this narrator together with a story's first words or a post's title about something
    else, or with a clear change of subject measured by the meaning model;
  - a pause far longer than any this narrator makes inside a story (at least 5 × the median pause), then a story's
    first words or a post's title: a reader who leaves a silence before each post;
  - a closing line followed by an opener, or by a title-like line about something else.

  Everything else stays below the threshold.
- **Intro and outro wording only counts near the start and the end** (`EDGE_SHARE` 12 % of the recording, at least
  90 s): "Today I am still embarrassed" in the middle of a post is part of the post.
- **ClipForge AI's second opinion is held to the same rule.** A place the model is asked about must carry a cue in
  its words (an opener, a post title where the subject changes, a closer followed by a new subject). When the
  narrator announces his stories (two or more strong announcements), only announced places and post titles where
  the subject changes are offered, so a model that says "new story" everywhere still ends with the announced posts,
  and a post read title-first among announced ones is still found.
- **A model's mistake never cuts a story into pieces** (`_drop_fragments`): a boundary only the model's word put
  there is dropped when it would leave a piece shorter than 40 s on either side of it. A place the rules found on
  their own stays.

Measured on the same 40 recordings (`tests/story_fixtures.gamer_reader`, seeds 1–40): **4 stories every time**, each
starting within 1 s of the labelled start, with the rules alone; with a model that answers "new story" to every
question, 4 every time (30 recordings). On a wider set of 423 situations written for the review (sponsor reads,
intros and outros, posts read title-first, narrators who pause before each post, posts that mention the next story,
a text-to-speech reader, model mistakes, a worst case with long pauses inside the posts) every story is found where
it starts; the release line's finder gets 160 of the 423. The existing Reddit-reader, three-story and meaning-model tests
still pass.

## Two settings (`studio/story_review.py`, `pipeline/story_parts.py`)

Make clips has three kinds of clips: **Highlights**, **Full story** and **Story parts**. Story parts is a Full stories
project (the same styles, skills and examples apply) with `options.story_split = "parts"`; Full story is
`"whole"` (also the default for projects made before). `clips_flow.prepare` maps the request mode to the project mode
and the split; the guidance preview, the link import and the remembered choice (`prefs.CLIP_MODES`) accept it.

- **Full story**: one clip per story, from its start to the next story's start, never split, except a story longer
  than five minutes, which is split in the fewest parts that fit (`ceil(D / 299.5 s)`); a story of 5:00 or less is
  one clip.
- **Story parts**: every story long enough is cut into parts of about 1¾ minutes: `n = max(ceil(D / 299.5),
  ceil(D / 175), round(D / 110))`, lowered while a part would be shorter than 62 s; a story under about two minutes
  stays whole. Parts are between 62 s (TikTok counts over a minute as long) and 175 s (under the three-minute Shorts
  and Reels limit) when the story allows.

**Where a part ends** (`story_parts.candidates`, `split`): every place between two sentences, at least 15 s inside
the story, gets a quality score: the poster's update starts (+0.45), a jump in time ("The next morning", "Two weeks
later", +0.35), right before a reveal ("Turns out", "That's when I found out", +0.3), a line that leaves you hanging
("And that's when I saw…", "…and then", +0.3), a question or an exclamation (+0.12), a change of scene (+0.12), a
pause that is long for this narrator (up to +0.25); a cut before a sentence that carries on the same thought ("And…",
"Because…", "Which…") or after a sentence that is not finished costs 0.3. A dynamic programme picks the cuts with the
best total quality, never letting a part pass five minutes, with a cost that grows as the parts get uneven and a large
one for a part outside the 62–175 s bounds. It only looks at the cut places that can lead to parts under the cap, so an
hour-long story is planned in well under a second. When no set of sentence boundaries fits, Full story first tries
one part more (a clean cut is better than the fewest parts) and Story parts tries fewer, longer parts; only then is a
part cut at the longest pause between two words, or inside a long stretch without talking (gameplay), and never inside
a word. A cut inside gameplay says so ("in a stretch without talking"), and Story parts never makes a part shorter
than a minute out of silence.
With a model set up, ClipForge AI may choose among the four best places for each cut (`stories.Judge.choose_cut`,
at most a quarter of the stories budget); its choice is used only if every part still fits.

Each part is its own clip: the story's title with "(Part N)", the same story key, "Part N" shown at the top for the
whole clip (the hook overlay, `hook_seconds` = the length rounded up to a whole second, plus 1 s; a trim in the clip
editor keeps it for the whole part, unless the owner set the label's seconds), and a reason that says why the part
starts where it does ("Part 2 of 3: starts right before a reveal, a 6.1 s pause.").

## Never longer than five minutes

`MAX_CLIP_S = 300`; parts are planned at most 299.5 s (`CAP_PLAN_S`) so rounding to milliseconds never crosses it.
Enforced everywhere a story clip's length can change:

- the pipeline (`plan_parts`) in both settings;
- `story_review.capped`: a story stored before the limit, or whose boundaries were set by hand, is split at its best
  point when its clip is made (pipeline or *Make this clip*), and the story's parts are numbered again;
- *Start 2 s earlier* / *End 2 s later* (`patch`) and *Merge with next* (`merge`) refuse a result over five minutes
  with the length in words; the Stories card disables those buttons with the reason;
- *Split in the middle* numbers the parts (Part 1, Part 2…) and *Merge* numbers the rest again; parts merged back
  into one whole story lose their number;
- the clip editor's trim (`PATCH /api/clips/{id}`) refuses a story clip over five minutes; other changes to an older,
  longer story clip still work. The editor's Trim tab says so. A start or end that is not a time in seconds ("NaN",
  infinity) is refused for every clip: it would have rendered the clip to the end of the recording.

## A still picture with the captions above it

A story clip starts with `layout: fit`, `tracking: center`, `zoom: 1.0`, `auto_zoom: false`: the whole source frame,
centred over a blurred, darkened copy of itself, never cropped, zoomed, pushed in or stretched. Only a framing chosen
for this project (Customize in Make clips, or the example video chosen for it) changes that; the app's settings, a
saved style, a skill, an example applied to every project or a Brain note do not (`guidance.story_framing`). A
subject to follow chosen for this project with no framing (say "face") gets the vertical frame, because the whole
picture leaves nothing to follow; zoom and push-ins stay off. The clip editor can still change any of it per clip.

The captions go **above the picture** (`caption_position: "above"`, `pipeline/captions.py`): the renderer passes the
picture's top edge (656 px down for 16:9 in 1080 × 1920); room for two caption lines is kept 28 px above it, below the
apps' top bar or 36 px below the "Part N" box, the words shrinking by at most a fifth to fit. The room is measured
with libass itself: two lines reach at most twice the font size above their baseline in every style (outline and the
growing highlighted word included), and the box ends 1.25 font sizes under its top for one line. Under "Part N" that
leaves full-size captions above a 16:9 game and slightly smaller ones (82 px bold) above a 16:10 one. With no room (a
4:3 picture under a headline, High energy above a 16:10 game under a headline, a square or vertical picture, Fill),
they go to the lower third as before. Captions placed at the top go under the headline while it shows ("Part N"
shows the whole time), so the label never covers them. Any choice of caption position
(project, example, style, skill, Brain note) wins over "above". "Above the picture" is offered in the clip editor
when the layout is Fit; it is not a style choice, because the full-video engine has no such position.

*Used from your Brain* tells the truth about this: for Full story and Story parts, `guidance.resolve` records the
framing, tracking and caption position decided by "Story clips (the whole picture, still)", with what they replaced
("instead of fill from Settings").

## Tests

- `tests/test_story_parts.py`: part counts, the cut at the jump in time / the update, Story parts ending on a
  cliffhanger, reveal or jump, a 24-minute story never over five minutes, minutes without words, one endless
  sentence, a gamer's pauses, cuts before "And" or after an unfinished sentence, ClipForge AI's choice and its
  failures, exact coverage, a story just under ten minutes cut between two sentences, minutes of silent gameplay
  after a post (no short part, no cut word), an hour-long story and an endless sentence planned in moments.
- `tests/test_full_stories.py`: the gamer reading posts while playing (five recordings), the eager model, a post read
  title-first among announced ones, worst cases with long pauses inside the posts, sponsor/intro/outro runs against a
  single "discount" sentence, announcement-like lines inside a post, a text-to-speech reader who pauses before each
  post, a model's mistake that would leave a fragment, and the existing three-story, Reddit-reader and meaning tests;
  `tests/test_smarter_ai.py` (the table-of-contents pass, short posts with varying silences and the meaning model).
- `tests/test_story_clips.py`: both settings end to end in the database (titles, keys, hooks, edits), Make clips'
  request modes, the API, the cap in `plan_parts`, `capped`, `patch`, `merge`, split and merge numbering, the clip
  trim (and "NaN" refused), "Part N" kept after a trim, the framing precedence (a chosen subject to follow), the
  snapshot, caption placement and captions at the top under "Part N", and (slow) libass drawing every caption style
  between the "Part N" box and a 16:9 or 16:10 picture, and a real render of a 16:9 recording: the picture band
  matches the whole source frame at four moments (a 5 % push-in would not) and the captions are drawn only above
  it.

## Limits

- The numbers are measured on synthetic recordings built from real post patterns (`story_fixtures.py`); real speech
  recognition adds its own mistakes (missing punctuation makes fewer, longer sentences). It needs a run on Landry's
  own videos to confirm.
- A narrator who never says anything between posts and pauses no longer than usual gives the rules nothing to go on;
  then a long story stays one clip (and is split only past five minutes).
- Captions above the picture need room: a 16:9 or wider picture has it; 16:10 has it except for High energy under
  a headline; 4:3 has it without a headline.
