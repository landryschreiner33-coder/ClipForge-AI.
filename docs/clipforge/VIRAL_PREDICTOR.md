# The viral predictor

ClipForge predicts how a clip will do before it is posted: a **viral score** (0-100), the **hook** (the first three
seconds), a **hold curve** (the share still watching each second, how much is watched on average and how many stay to
the end), the **strongest moment**, a **heatmap** of five channels second by second, the **reasons** behind each
number, and **fixes** it has already tried on the clip. It runs on this computer after every render, while clips are
picked, on Prepare post, and on any video dropped on **Make → Check a video**.

Landry asked (Nov 26): "reverse engineer how their viral predictor works so we can implement it to help the videos go
more viral", meaning Higgsfield's Virality Predictor. The rule for this work: only what Higgsfield shows publicly and
published research; nothing decompiled, no private endpoints, no protections bypassed. ClipForge's predictor is its own
design built from that public information.

## What Higgsfield shows publicly (read Nov 26, 2026)

| | Higgsfield (public page and coverage) | ClipForge |
|---|---|---|
| Input | "Any format, vertical or horizontal, up to 15 seconds" | Any rendered clip; Check a video takes up to 10 minutes |
| Outputs | "A virality score, a peak hook timestamp, a hold rate, and a heatmap" | The same four, plus a hold curve, average watched, reasons and fixes |
| Heatmap | "brain response across vision, sound, memory, attention, language" | The same five channels, measured from the clip (no brain model) |
| Method | Not published. One newsletter said the brain map "appears to be powered by TRIBE v2"; Higgsfield has not confirmed | Written below, with every number in the code |
| Accuracy | Not published ("No accuracy data or method is published", Blur Studio) | Measured against the owner's own posts (Publishing → Results) |
| Fixes | None on the official page | Tried on the clip first; only fixes that do not lower the score are shown |

Pages read: [higgsfield.ai/apps/virality-predictor](https://higgsfield.ai/apps/virality-predictor),
[Pasquale Pillitteri](https://pasqualepillitteri.it/en/news/2273/higgsfield-virality-predictor-hook-score-hold-rate-2026),
[Blur Studio](https://www.blurstudio.ai/knowledge/higgsfield-virality-predictor),
[Nahornyi](https://nahornyi.ai/en/news/higgsfield-predicts-video-virality-before-posting),
[Quasa](https://quasa.io/media/higgsfield-launches-virality-predictor-an-ai-tool-that-predicts-if-your-video-will-go-viral-before-you-post-it),
[Woshipm](https://www.woshipm.com/ai/6394356.html), [OpusClip's guide](https://www.opus.pro/blog/best-ai-tools-to-predict-video-virality).
Reviewers agree that the tool is a black box with no published benchmark, and warn against treating it as an oracle.
The Higgsfield connector in this project can only browse models and generations, so nothing was run through it.

### Why not use the brain model it may be built on

Meta's TRIBE v2 ([blog](https://ai.meta.com/blog/tribe-v2-brain-predictive-foundation-model/),
[TRIBE v1 paper](https://arxiv.org/abs/2507.22229)) predicts fMRI activity for an average viewer, once a second, from
the picture (V-JEPA2), the sound (Wav2Vec-BERT) and the words (LLaMA 3.2). It is shared under **CC BY-NC**
(non-commercial), needs about 30-40 GB of graphics memory, and the gated LLaMA model needs its own sign-up. A community
repackaging ([pylox-neuro](https://huggingface.co/pyloxsystems/pylox-neuro)) is CC-BY-NC-4.0 too. ClipForge only uses
Apache/MIT models, so it does not use either, and it does not pretend to read a brain: the five channels are measured
from the clip itself.

### What the research does say

Tong et al., "Brain activity forecasts video engagement in an internet attention market", PNAS 2020
([PDF](https://web.stanford.edu/~knutson/nfc/tong20.pdf), [summary](https://neurosciencenews.com/viral-video-brain-15884/)):
36 viewers, 36 YouTube videos. Brain activity linked to positive arousal (nucleus accumbens) in **the first 4 seconds**
forecast how often a video was watched online (adjusted R² 0.28, against about 0 for viewers' own ratings); activity
linked to negative arousal (anterior insula) forecast fewer views. People's ratings did not forecast the crowd. The
takeaways ClipForge uses: **the opening decides**, it should give something positive and arousing at once, and a clip's
own content says more than how people say they feel about it. The study is small and used fMRI, not a model; it does
not show that any software score predicts virality, which is why ClipForge measures itself against the owner's posts.

Platform help pages agree that the start and how much is watched matter: YouTube counts engaged views and shows
retention ([1](https://support.google.com/youtube/answer/6390658), [2](https://support.google.com/youtube/answer/12340300),
[3](https://support.google.com/youtube/answer/12220281)); TikTok weighs whether a video is watched to the end
([TikTok](https://support.tiktok.com/en/using-tiktok/exploring-videos/how-tiktok-recommends-content)).

## How ClipForge's predictor works

Code: `clipfoundry/predictor/` (`signals.py` measures, `model.py` predicts, `fixes.py` tries fixes, `learn.py` learns
from results, `checks.py` is Check a video, `routes.py` the API, `__init__.py` ties it to clips and renders).

### 1. Measure (signals.py), half a second at a time

From the file, with FFmpeg, numpy and OpenCV only: movement and new shots (every frame at the reference-analysis scan
rate), faces and on-screen text (one still per half second, at most 180), loudness, sudden sounds, emphasis, laughter
and reactions (a reaction must be 3 dB above its surroundings as well as stand out, so music swells are not cheers),
and the clip's words with their times. While clips are picked, before anything is rendered, `from_source` measures a
moment of the recording from its words and loudness only, and the prediction says the picture was not measured.

### 2. Five channels (model.channels), one value per second from 0 to 1

- **Vision:** movement, new shots, faces and text on screen.
- **Sound:** loudness, sudden sounds, emphasis and reactions.
- **Language:** speech, how much it says, hook words, questions and payoff lines.
- **Attention:** something new to notice (a cut, a sound jump, emphasis, a question); its pull halves every 2.5 s
  when nothing changes.
- **Memory:** what sticks: emphasis, emotion, payoff lines, reactions, numbers, and the ending.

### 3. The hook (model.hook), 0-100

The first 3 seconds of picture (movement, a face or text in the first second, a cut), sound (sound from the start) and
words (how strong the opening line is in the 11-factor Viral Potential, how soon the first real word comes, hook words,
a question or a number), weighted 35/20/45. A dark or black opening costs 35 points of picture, a still first 2 s 15,
a silent first second 40 of sound. The hook notes say which of these it found.

### 4. The hold curve (model.hold): a modelled audience

Part of the audience swipes away in the first 2 seconds: 60% stay with no hook at all, 85% with a perfect one. After
that, 1% a second leave anyway, up to 4.5% more where the clip gives the eye, the ear and the mind little, boredom
builds after 3 seconds with nothing new (up to 3.5% more), dead air over a still picture costs 8% a second, and an
unanswered question keeps people (leaving drops to 75% until the payoff). The curve has one point per second
(0 s to the end); **hold rate** is the share at the end, **average watched** the share of the clip an average viewer
sees, and the **drops** are where most leave, with why.

### 5. The viral score (model.viral_score)

A mix of five parts, each 0-1, through an S-curve to 0-100: **what it says** (the clip's 11-factor Viral Potential)
25%, **hook** 25%, **how much is watched** 30% (30% watched counts 0, 75% or more counts 1), **memorable moments** 10%,
**something to look at** 10%. A part that could not be measured is left out and the others are weighted up. Bands:
90 Very high, 75 High, 60 Good, 40 Fair, below Low. The **strongest moment** is the highest point of the combined
channels; the reasons say when it falls after the hook.

### 6. Fixes (fixes.py), tried before they are offered

For a clip ClipForge made, it re-runs the prediction on the clip with each change and keeps at most five that help:
start later (on the first real word or a stronger line in the first 8 s), end earlier (just after the payoff line),
remove pauses, captions, the hook on screen, punch-ins on a long still stretch, louder sound, and (advice only) tease
the strongest moment at the start. A fix must add at least 1 point of score, 2 points of average watched or 3 of hold
rate, never lower the score, never cost more than 3 points of hook, never leave the clip shorter than 5 s (or the
owner's shortest clip), and never cut a line in a way the clip checks flag (weak context, a misleading cut, a weak
ending, a change of topic). **Add to my edit** puts a fix in the clip editor; the owner then saves and renders. For a
video ClipForge did not make, the fixes are advice.

### 7. Learning from the owner's results (learn.py), bounded

When posts have results, the learner (autopilot/learner.py) hands them to the predictor:

- **Accuracy**, from 10 posts per platform: how well the scores ordered the views (Spearman), how often the predicted
  top third beat the median, the median views per band, and the error of average watched where the platform reports
  it. Shown on Publishing → Results.
- **Calibration** of average watched, from 15 posts: a line fitted to the real numbers (slope kept between 0.3 and 2),
  pulled toward no change while there are few posts (n / (n + 20)).
- **Weights**, from 30 posts: each part of the score may move at most 40% from its designed value, and at most 10% per
  learning round.

Nothing is learned while the Brain is paused, and what was learned is dropped when the model version changes.

### 8. Where it is used

- **After every render** (`pipeline/render.py`): the prediction is stored in the clip's render info with the file's
  checksum; a changed file is predicted again. It never fails a render.
- **Clip picking** (`pipeline/deep.py`, step 5c): each candidate moment's hook and hold move its Clip Score by at
  most 5 points ("Predictor" in the score's reasons).
- **Posting plan** (`autopilot/scheduler.py`): when a clip has a prediction, its expected retention is the average of
  the learner's figure and the predicted average watched.
- **Post records** (`publish/jobs.py`): the prediction at posting time is kept with the post, so results can be
  compared with it later.
- **Screens:** the clip editor's Viral predictor card (score ring, hook, hold, peak, hold curve, heatmap, reasons,
  fixes), Prepare post, the score on clip cards, **Make → Check a video**, the accuracy table on Publishing → Results,
  and the on/off switch in the AI settings (`viral_predictor`, on by default).
- **ClipForge AI** knows it from the app guide section "The predictor".

## Honest limits

- It is an estimate for comparing clips and finding what to fix, not a promise of views. Until the owner's posts have
  results, the numbers come from the design above and the research it follows, not from measured accuracy.
- The channels are measured signals (movement, faces, text, loudness, words), not a model of a brain.
- While clips are picked, only words and sound are known; the picture counts after the render.
- Check a video transcribes with the built-in speech model when it is installed; without it, speech is estimated from
  the sound and the result says so.
- Not checked here: real posts' results against the predictions (needs the owner's accounts), and Windows/Mac speed on
  long videos.
