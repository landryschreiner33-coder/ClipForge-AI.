# ClipForge AI, far smarter: meaning, scout and judge, eyes, ears, taste

This is the design, as built, of the November 2026 work that made ClipForge's built-in AI and its editing decisions
much smarter. It sits on top of phase A ([CLIPFORGE_AI.md](CLIPFORGE_AI.md): the brain, the know-how playbooks, the
chat) and on the deep clip analysis (`clipfoundry/pipeline/deep.py`). Everything here runs on the owner's computer,
is bounded (no single new signal can move a Clip Score by more than a stated amount), is explained in words next to
the clip, and falls back to the previous behaviour when a part is missing (no model, no download, a slow answer).

## What the research said

Where the best clip tools and the published work agree, and what ClipForge did about each point:

| Finding | Source | What ClipForge now does |
|---|---|---|
| Word lists miss moments told in plain words; a model that reads the whole transcript finds them | the way Opus Clip, Vizard and Klap describe their "virality" passes; the long-context reading in Gemini and Qwen papers | the **scout** pass (`pipeline/scout.py`) |
| Ranking finalists side by side (listwise) beats scoring them one at a time with a model | RankGPT / listwise reranking papers; "LLM as a judge" results | the **judge** pass, bounded ±10 |
| Sentence-embedding models see that two sentences mean the same thing; word overlap cannot | Sentence-BERT (Reimers & Gurevych 2019), all-MiniLM-L6-v2 | the **meaning model** (`embedder.py`) |
| Pitch movement and emphasis predict engagement; a flat voice loses viewers | speech prosody research (Hirschberg; Ward), the retention guide's "performance" section | the **ears** (`pipeline/ears.py`) |
| The picture decides the first second; a thumbnail with a face and a clear subject wins | platform studies, the retention guide's "frame one" rules | the **eyes** (`pipeline/eyes.py`) |
| Personal taste beats a global score once there are a few dozen labels | recommender basics; what Descript and Opus Clip do with "brand" choices | the **taste** learner (`taste.py`) |
| Topic segmentation from embeddings finds story boundaries the words hide | TextTiling and its embedding successors | **Full stories** with meaning shifts (`pipeline/stories.py`) |

The two guides the owner gave ClipForge in November 2026 (a short-form retention guide and a cinematic filmmaking and
post-production guide) are the twelve built-in playbooks of `brain/knowhow.py`. How they were used is listed at the
end of this page.

## The meaning model (`clipfoundry/embedder.py`)

all-MiniLM-L6-v2 (sentence-transformers, Apache-2.0; based on MiniLM-L6-H384-uncased, MIT): 22 million parameters,
384 numbers per text, run on the CPU through ONNX Runtime (no PyTorch). Two files are downloaded once from the
official repository at a **pinned revision** and checked against **pinned SHA-256 hashes**; a file that does not
match is deleted and the error shown. Size on disk: 90.6 MB.

| File | Bytes | SHA-256 |
|---|---|---|
| `onnx/model.onnx` | 90,405,214 | `6fd5d72f…6046452` |
| `vocab.txt` | 231,508 | `07eced37…992038a3` |

Revision `1110a243fdf4706b3f48f1d95db1a4f5529b4d41`. The word-piece tokenizer is implemented in the module (no extra
packages); texts longer than 256 word pieces are cut; mean pooling over the attention mask, unit length. A marker file
(`clipforge-verified.json`) records a verified install; a licence file is written next to the model.

- **Setting:** `meaning_model` (on by default). Settings → AI helper → "Understanding meaning" shows the state
  (On / Off / Downloading / Not usable here / Not downloaded yet), a progress bar with Cancel, "Download now (91 MB)"
  and "Remove to free 91 MB". The pipeline also downloads it on first use when the setting is on.
- **Fallbacks:** setting off, no ONNX Runtime, cloud mode, or a failed download (retried after an hour) → every
  caller uses the word-based vectors it used before. Nothing stops working.
- **Cache:** the last 40,000 texts' vectors stay in memory (a two-hour video is about 2,500 sentences); duplicate
  texts in one call are embedded once; batches of 32.
- **API:** `GET /api/ai/meaning`, `POST /api/ai/meaning/install|cancel|remove`.
- **Who uses it:** the deep clip analysis (`pipeline/semantic.py`), diversity, Full stories, the brain's memories
  (`brain/meaning.py`: a question finds the memory that means the same thing; `model()` names the embedder in use;
  vectors from different embedders are never compared, and Rebuild recomputes the old ones).

### Two spaces, one scale (`pipeline/semantic.py`)

`embed_sentences` returns an `Embeddings` array that carries `.model` (`minilm-l6-v2` or `lexical`) and `.baseline`,
the video's own similarity between unrelated sentences (about 0.0 with words, about 0.10 with the meaning model;
measured per video from distant sentence pairs when there are enough). `cos_cal` removes the baseline, so the
features downstream (one topic or several, does the ending tie back, novelty within the video, diversity between
clips, story boundaries) mean the same thing whichever space made them. Novelty is rank-based for the same reason.

## The scout and the judge (`clipfoundry/pipeline/scout.py`)

Both passes read the same **brief** (`scout.brief`, built once per run): the video's title, the best playbooks for
picking clips (1,100 characters), the owner's standing rules from the brain (500), the wanted length, and the
taste learner's sentence when it has one.

1. **Scout** (`scout.nominate`), before the candidates are scored: the model reads the transcript in order in
   windows of 8,000 characters and names up to 4 moments per window (12 in all) that would stand alone as a short,
   with a kind (story, insight, funny, emotional, controversial, how_to) and a reason. Each moment is snapped to
   sentences, checked for length, scored by `candidates.window` exactly like every other candidate, and gets a
   stage-1 bonus of 0.08; a moment that repeats a candidate the word lists already found strengthens it instead.
   Four deep-stage places (`RESERVED`) are kept for the best nominations so a quiet story is not pushed out by loud
   candidates. The clip's "Why" says "named by ClipForge AI while reading the video (story)".
2. **Judge** (`scout.judge`), after the deep stages: the finalists (at most 12, 700 characters each) go into one
   request; the model ranks them and gives each a verdict (green / yellow / red with a reason). The ranking moves a
   Clip Score by at most **±10** points, and only by as much as the model disagrees with the local ranking
   (percentile against percentile); green adds 2, red costs 6 and shows as a warning with the model's reason. The
   model never adds a clip the local analysis rejected and never removes one.

Time budget: `ai_edit_timeout_s × 10`, at most 10 minutes for both passes; progress is reported to the job; a
cancelled job stops at once; a slow or unreadable answer leaves the local decisions as they are. The built-in model
answers inside a **JSON schema** (`SCOUT_SCHEMA`, `JUDGE_SCHEMA`, enforced by llama-server while it writes), so a
small model cannot answer in the wrong shape; other providers get the same schema as instructions. Setting:
`ai_scout` (on by default; needs a model set up and `deep_analysis`).

## The eyes (`clipfoundry/pipeline/eyes.py`)

The built-in model's vision part (the `--mmproj` file downloaded with every level) was never used before. For the
six strongest finalists (`VISUAL_KEEP`) three 384-pixel-wide frames (a quarter, half and three quarters of the way
through) go to the model in one request with the clip's first words, and it answers in a schema: the kind of
footage (talking_head, interview, vlog, screen_recording, gameplay, slides, b_roll, other), how many people, text on
screen, which frame makes the best thumbnail, a one-line description, and appeal 1–10. The answer moves the Clip
Score by at most **±4** (`(appeal − 5) × 0.8`), is shown as "ClipForge AI saw: …", and the chosen frame becomes the
clip's thumbnail (`render.thumbnail_time`, if the frame falls inside the rendered clip at its speed). Setting:
`ai_eyes` (on by default; built-in provider only; nothing happens for audio-only files or other providers).

## The ears (`clipfoundry/pipeline/ears.py`)

numpy alone, from the 16 kHz copy made for transcription: pitch every 20 ms by autocorrelation (70–400 Hz, voicing
strength ≥ 0.45), loudness in dB, and from them

- **pitch variation** (robust standard deviation of the voiced pitch in semitones, scaled by 3.5),
- **emphasis moments**: pitch 3 semitones above the speaker's usual pitch and loudness 0.8 standard deviations above
  the usual level at the same time, grouped at least a second apart,
- **laughter-like bursts**: word-free stretches of 0.4 s or more, loud as a whole, whose loudness pulses 3–8 times a
  second (at least 35 % of the modulation energy),
- **the pause before the end** (the longest gap between words in the final third) and **monotone** (pitch spread
  under 1.2 semitones and loudness spread under 3 dB).

A prosody score (0.45 variation + 0.25 emphasis rate + 0.20 laughter + 0.10 not monotone) joins the deep stage's
extras; a flat voice is named in the clip's "Why". The smart editor (`studio/smart_edit.py`) puts its punch-ins
(zoom 1.1) on the parts where the voice leans on a word instead of on every other cut; when a recording's voice
stays even after every cut (a flat delivery, a synthetic voice), the old rhythm takes over for that recording so
the fast-paced level never leaves its jump cuts bare, and the note says which rule was used. The emphasis moments
of a recording are computed in one-minute blocks and cached in `prosody.json` next to the audio. Every number is
labelled as an estimate from the sound alone.

## Your taste (`clipfoundry/taste.py`)

Every choice about a clip is a lesson: leaving it out (unticking, −1), putting it back (+0.6), exporting (+1),
publishing (+1), deleting (−0.8). A lesson stores the clip's profile: the eleven virality factors, Viral Potential,
duration, whether it opens with a question, story words, hook words (16 features). With 12 lessons and at least 4 on
each side, a regularised logistic regression on standardised features is fitted in milliseconds; from then on each
finalist gets an adjustment of at most **±6** with the reason in words ("you tend to keep clips with a stronger hook
and leave out long ones"), and the same sentence goes into the scout's brief. A feature that never varied cannot
explode (standard deviations are floored, z-scores clipped at ±4). Tables `taste_events` and `taste_models`
(`db.py`); `GET /api/taste`, `DELETE /api/taste`; PATCH `/api/clips/{id}` with `selected` records "deselected" /
"reselected", and the export and publish paths call `taste.published`. Brain → Memory shows "What it learned from
your choices" with a "Forget my choices" button. Nothing is guessed from one click; taste only reorders finalists.

## Full stories with meaning (`clipfoundry/pipeline/stories.py`)

- **Meaning shifts** (`meaning_shifts`, only with the meaning model): for every gap between sentences, how much the
  six sentences after it still talk about what the six before talked about (calibrated cosine), and how unusual that
  is for this recording (a robust z-score). A gap with z ≤ −2.5 and shift ≤ 0.25 counts as a change of subject
  (topic evidence 0.22); z ≤ −1.8 and shift ≤ 0.35 counts a little (0.12). Words alone keep deciding when the
  vocabulary changes; the meaning model adds the cases where the words stay the same but the subject moves, and a
  boundary still needs a pause or an explicit change to cross the threshold (0.5).
- **Table of contents** (`Judge.scan`): ClipForge AI first reads the recording through and names where new stories
  begin (`SCAN_SCHEMA`), then is asked about the boundaries the rules are unsure of (`review`). An answer that is not
  readable is recorded as such and leaves the rules' decision alone (it is not read as "no new story here").
- The result's `method` names what was used ("… and the meaning model, checked by ClipForge AI").

## The Clip Score, explained

`deep.clip_score` adds the bounded adjustments to the Viral Potential base: semantic, audio, trend, weak picture,
the eyes (±4), the judge (±10, red −6, green +2), your taste (±6). Each one is a line in the clip's `explanation`
("+2.0 ClipForge AI ranked it 1 of 2 (green)"). The clip's stored analysis carries `clip_score`, `explanation`,
`judge`, `scout`, `taste` and a small `deep` summary (prosody without the long list of times, what the eyes saw).
The app's clip view (`components/viral.tsx`, `AiNotes`) shows the scout line, the rank and verdict, "ClipForge AI
saw", "The voice", "Your taste", and a disclosure "How the Clip Score of N came about".

## Settings

| Setting | Default | Meaning |
|---|---|---|
| `deep_analysis` | on | the staged analysis for every "Make clips", not only Autopilot; a broader pool (4 × clips, 24–40) |
| `ai_scout` | on | the scout and judge passes (need a model) |
| `ai_eyes` | on | the eyes (built-in model only) |
| `meaning_model` | on | the meaning model, downloaded once (91 MB) |

## How the two guides were used

Already applied before this work (PR #28, the twelve playbooks and the editors' numbers): outro lines as a weak
ending and poor opener; loss and warning framing; open loops and contrast words; slow opens and back-references;
topic changes inside a clip; speaking rate centred at 2.9 words a second; the flat 15–45 s length window; −14 LUFS
and −1 dBTP; BT.709 tagging; captions of 1–3 words with an outline, accent colours, above the bottom 35 %; the
dialogue voice chain; music ducking.

New in this work, from the guides:

- the scout and judge read the picking playbooks in every brief, and the judge's criteria are the guide's: does it
  stand alone, does the first line earn the second, does it stop on the payoff, no greetings or sponsor lines;
- the **causal engine**: beats joined by "but", "because", "which meant", "turns out" (`CAUSAL_WORDS`,
  `CAUSAL_PHRASES`) raise curiosity by up to 0.06; a chain of "and then … and then" with no turn (`EPISODIC_PHRASES`,
  two or more and no pivot) lowers it by 0.10 and shows the warning "\"And then\" chain" (`signals.causal_pivots`,
  `signals.episodic`);
- the **constrained experiment** hook ("I spent 30 days…", "I tried…", "here's what happened", "on a budget",
  "with only") counts as a hook and an open loop (`HOOK_PHRASES`, `OPEN_LOOP_PHRASES`);
- **chapter-cliff fillers** ("furthermore", "my next point", "on to the next") count as a topic change inside a clip
  (`TRANSITION_PHRASES`);
- the guide's performance rules became measurements: pitch movement and emphasis (the ears), a flat voice named in
  the "Why", punch-ins on the words the voice leans on (the talking-head playbook's second tier);
- the frame-one rules became the eyes' question (subject, faces, text on screen, the best thumbnail).

Deliberately not automated: a slow drift zoom (100 → 106 %) on static shots (the engine's `zoompan` exists only for
overlays) and sculpted silence before the payoff (needs a judgement of the joke that the rules cannot make yet).

## Checks

- `tests/test_smarter_ai.py` (39 tests): the download with pinned hashes (a tampered file is deleted), the tokenizer,
  pooling and caching with a fake session, the two spaces and calibration, the scout's windows and nominations with a
  fake model, the judge's bounds, the eyes' frames and thumbnail, the ears on synthetic voices (emphasis, lively vs
  flat, laughter), punch-ins on emphasis, the taste learner end to end and its API, meaning shifts and the table of
  contents, the built-in request body (images, schema), the guides' rules. One test runs the real model when
  `CLIPFORGE_MEANING_MODEL_DIR` points at a copy (paraphrases closer than strangers).
- `scripts/builtin_ai_check.py --meaning --eyes` on a GitHub runner (`.github/workflows/builtin-ai-check.yml`): the
  real download and hashes, paraphrase vs stranger similarity and speed, a schema-bound ranking through the built-in
  model, and the eyes on a generated test video.
- Not testable in the cloud: the download itself (the model hub is blocked from the cloud computer), real speech, a
  17 GB file, and the built-in model's answers on real footage; those need a runner or the owner's computer.
