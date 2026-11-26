# Clip quality: what the research says and what ClipForge does with it

Written 2026-11-25 for the final release (batch 2). Every rule below is marked by how sure we are of it:

- **Rule**: a platform says it in its own help pages or API documentation. ClipForge follows it or checks for it.
- **Hypothesis**: a pattern from platform guidance or editing craft that ClipForge uses as a scoring signal. It is a
  good bet, not a fact about your channel. Results → Compare is how your own posts confirm or reject it.
- **Tested**: ClipForge's own tests or the clip quality benchmark check that the code does what this page says.
  Tested means the code behaves as described. It never means a clip will get views.

Nothing here promises views. The Viral Potential number ranks clips against each other; it is an estimate from the
clip's words, timing and sound (pipeline/virality.py, `ESTIMATE_NOTE`).

## Sources and why each was used

All read on 2026-11-25.

| Source | What it gave us | Why this one |
|---|---|---|
| YouTube Help, Shorts analytics ([answer 12220281](https://support.google.com/youtube/answer/12220281)) | How YouTube counts a Shorts view and an engaged view | It is how YouTube itself measures a Short, so it decides what "worked" means |
| YouTube Help, titles ([answer 12340300](https://support.google.com/youtube/answer/12340300)) | Put the most important words near the beginning; an accurate title; few capitals and emoji | YouTube's own advice for titles, not a guess |
| YouTube Help, hashtags ([answer 6390658](https://support.google.com/youtube/answer/6390658)) | Up to three hashtags shown by the title; more than 60 and all are ignored; no unrelated hashtags | The limits ClipForge checks before posting |
| YouTube Data API, `videos.insert` ([docs](https://developers.google.com/youtube/v3/docs/videos/insert)) | Title up to 100 characters, description up to 5000 bytes | The fields the upload actually sends |
| TikTok Support, how TikTok recommends content ([page](https://support.tiktok.com/en/using-tiktok/exploring-videos/how-tiktok-recommends-content)) | Signals: interactions (likes, shares, comments, watching in full or skipping), video information (sounds, hashtags), user information; watch time weighs heavily | TikTok's own description of its feed |
| TikTok for Business, Creative Codes ([page](https://ads.tiktok.com/business/en-US/creative-codes)) | 9:16, at least 720p, keep text clear of the app's buttons, hook → body → close, sound on | TikTok's own creative guidance (written for ads, so used as a hypothesis for organic clips) |
| TikTok for Developers, Content Posting API and content sharing guidelines ([guidelines](https://developers.tiktok.com/docs/en/content-sharing-guidelines)) | Caption up to 2200 UTF-16 characters; the user picks the privacy and sees what is posted | The rules the posting code must follow |
| YouTube API Services Developer Policies (quoted in `learning.YOUTUBE_NOTE`) | Metrics derived from YouTube API data need Google's approval | Why YouTube numbers are left out of Compare until you confirm that approval |
| ClipForge's 16 built-in playbooks (`brain/knowhow.py`, from the Nov 6 and Nov 18 research) | Hooks, endings, pacing, captions and safe zones, titles, hashtags, gaming clips | Already in the app and already used by ClipForge AI; this page does not repeat them |

## Picking the moment

| What ClipForge does | Kind | Where | Tested by |
|---|---|---|---|
| Ranks the opening first: the first real word within a second or two, a first line that gets to the point | Hypothesis (YouTube counts engaged views only once a viewer stays past the start; TikTok weighs watch time and skips) | `virality.analyze` hook, opening | test_virality.py |
| Needs a clip to make sense alone: no "as I said", no reply to someone outside the clip | Hypothesis | `virality.analyze` standalone | test_virality.py |
| **New:** a "he" or "she" the clip never introduces counts against it; when the line just before the clip says who it is, the clip is rejected and a version that starts there wins | Hypothesis | `candidates.unnamed_person`, `virality.analyze` | test_clip_selection_rules.py, benchmark (bakery story) |
| **New:** "where was I", "let me read chat" end the topic, so a clip does not run across them | Hypothesis | `text_utils.TRANSITION_PHRASES` | test_clip_selection_rules.py, benchmark (clutch clip) |
| Ends on the payoff; an outro ("thanks for watching") counts against it | Hypothesis (Creative Codes' hook → body → close; playbook "Endings") | `virality.analyze` payoff, outro | test_virality.py |
| **New:** two or more goodbye lines at the end ("that is the stream for today", "bye chat") reject the clip | Hypothesis | `virality.analyze` outro | test_clip_selection_rules.py, benchmark |
| **New:** an ad or sponsor read ("brought to you by", "use code", "at checkout") is never a clip; one ad line in a longer clip is a warning | Hypothesis | `text_utils.AD_PHRASES`, flag `ad_read` | test_clip_selection_rules.py, benchmark (podcast) |
| **New:** thanking followers and reading chat ("thanks for the follow", "gifted subs") counts against a clip; three such lines reject it | Hypothesis | `text_utils.CHAT_CHORES`, flag `chat_chores` | test_clip_selection_rules.py, benchmark (clutch clip) |
| **New:** a clip that ends by circling one point ("Consistency matters. Be consistent. Consistency is key.") has a weak ending | Hypothesis | `text_utils.repeat_run`, flag `weak_ending` | test_clip_selection_rules.py, benchmark (sourdough) |
| **New:** "one checkbox", "the one setting" open a question the clip answers, like "here's why" | Hypothesis | `text_utils.ONE_THING` | test_clip_selection_rules.py, benchmark (tutorial) |
| Speech clarity from the transcriber's word confidence and how far the voice stands above the background | Hypothesis | `virality.analyze` clarity | test_virality.py |
| Clips run from the shortest to the longest length you set, ideal in between (25 / 45 / 90 s by default) | Your setting | `virality.analyze` retention | test_virality.py |
| Shows the reasons for each clip under Opening, Context, Pacing, Payoff, Audio and Framing | — | `virality.reasons` | test_rank_reasons.py |
| Suggests a tighter start and end (warm-up words, a line cut in half, an outro, chat talk, repeated lines) | Hypothesis | `pipeline/trims.py` | test_trims.py, test_clip_selection_rules.py |
| Remove pauses takes out dead air but keeps up to a second after a question or "wait for it" | Hypothesis (a pause before an answer builds tension) | `trims.tension_pause`, `render.keep_segments` | test_trims.py, benchmark |
| **New:** a "one thing" line at the very end, when the one thing comes right after the cut, is a misleading cut (rejected) | Hypothesis | `candidates.sentence_features` setup, flag `misleading_cut` | test_clip_selection_rules.py |
| **New:** "our captain", "my teammate", "the host" introduce a person, so a "he" after them is not a cold start | Hypothesis | `text_utils.PERSON_NOUNS` | test_clip_selection_rules.py, test_live_pick.py (story told on stream) |

## Live streams and long recordings

| What ClipForge does | Kind | Where | Tested by |
|---|---|---|---|
| Scores moments by reactions in the sound (loud stretches without words), the words, and how the picture changes | Hypothesis | `deep.audio_features`, `eyes` (visual pass for the best candidates), `live_pick` | test_smarter_ai.py, test_live_pick.py |
| **New:** a reaction often comes a second or two after the line that caused it. A laugh, a shout or a crowd that starts within 3 s after the last word (before anyone speaks again) stays in the clip, up to 3 s of it; the reason says "Ends on a reaction" | Hypothesis (playbook "Gaming and stream clips": "stop when the reaction has landed") | `virality.reaction_after`, `deep.optimize_bounds`, `candidates.refine_bounds` | test_clip_selection_rules.py, benchmark (game stream) |
| **New:** Remove pauses keeps those reactions: a loud stretch without words is not silence | Hypothesis | `render.heard`, `render.keep_segments(loud=…)` | test_clip_selection_rules.py, benchmark |
| **New:** a clip that opens right after a reaction gets a warning: what caused it happened before the clip, so a version that starts earlier wins | Hypothesis | `virality.reaction_before`, flag `starts_on_reaction` | test_clip_selection_rules.py |
| Each clip looks for the face cam again; the place found earlier is only a hint, so a cam moved mid-stream is found in its new place, and the new place is what later clips remember | — | `reframe.find_cam(hint=…)`, `render._remember_cam` | test_split_view.py (cam moved from bottom left to top right) |
| Chat messages are not read: a recording has no chat in it, and reading live chat needs each platform's chat connection, which ClipForge does not have yet. Chat talk the streamer reads out loud is in the transcript and counts (see "Talks to chat" above) | Blocker | — | — |

Phrase lists are matched as whole words where a part of a word would mislead ("use code" is not "because code",
"for the sub" is not "for the subway"): `text_utils.count_words`.

## Framing (stream layouts)

| What ClipForge does | Kind | Tested by |
|---|---|---|
| 9:16 output at 1080×1920 | Rule (Creative Codes: 9:16, at least 720p) | test_split_view.py |
| Gameplay + Facecam, Picture-in-picture, Gameplay only; finds a face cam in the corner or uses the box you draw or lock; a separate camera recording lined up by its sound | Hypothesis (playbook "Gaming and stream clips") | test_facecam_layouts.py (frames checked with the cam bottom left, top right, drawn, and none) |
| Captions and the headline stay clear of the apps' buttons (headline from 15 % down, bottom captions 36 % up; under a picture-in-picture box when it is on top) | Rule in spirit (Creative Codes: keep space for the app's interface); the exact margins are a hypothesis | test_facecam_layouts.py (captions below the box), test_story_clips.py |

## Titles and hashtags

| What ClipForge does | Kind | Tested by |
|---|---|---|
| Three options per clip, one of each kind where the clip allows: searchable (topic word in the first four words), curiosity (a question or open loop), the moment | Hypothesis | test_title_kinds.py |
| Recommends one per destination with a short reason: YouTube the most searchable or accurate, TikTok the line to open the caption with | YouTube's "important words near the beginning" is a rule of thumb from YouTube; the TikTok pick is a hypothesis | test_title_kinds.py |
| Every option is a line from the clip itself (grounded) | — | test_postpack.py (grounding) |
| **New:** a title must make sense alone: not "That's the setting" or "If you upload in ten eighty" | Hypothesis | test_clip_selection_rules.py |
| Title up to 100 characters, YouTube description up to 5000 bytes, TikTok caption up to 2200 characters, more than 60 hashtags makes YouTube ignore all, the first three show by the title; checked before posting | Rule | test_title_kinds.py (field checks) |
| Three to five specific hashtags from the clip's own words | Hypothesis (YouTube: no unrelated hashtags; playbook "Post text and hashtags") | test_postpack.py |
| **Nov 26 (Landry's title and hashtag research):** the video's subject comes from its name (a link's title, the file's name, an Autopilot source's title): names written with a capital ("Elden Ring"), not file-name filler. It leads the hashtags (#EldenRing, readable CamelCase) and the Searchable title ("Elden Ring: every attempt she healed off my hits"); its words count as known in every check, other names still do not | Hypothesis (research: one clear promise, subject or strongest detail early) | test_titles_hashtags.py |
| Hashtags in the order your own (Settings → Defaults → Hashtags on every post), the subject, the clip's specific topic; tags that differ only in letter case are one tag; never #fyp, #foryou, #viral or #trending; YouTube shows the first 3, TikTok gets at most 4, at most 5 anywhere | Research (YouTube 1-3, TikTok 2-4, Reels at most 5) | test_titles_hashtags.py |
| A title that names nothing ("Watch this", "It was crazy": fewer than two meaningful words and no topic word, number or name) goes last and is never recommended over one that does | Research (plain words, one concrete detail) | test_titles_hashtags.py |
| The moment leads with a concrete detail (a number, a count) before the conclusion; the model is told not to give the ending away in a curiosity title | Research | test_titles_hashtags.py |
| The recommended title says where the clip backs it ("The clip says it at 0:04") | Research (each recommendation with the timestamp that supports it) | test_titles_hashtags.py |
| A trim that cuts out a title's or hashtag's line puts a note next to it; the text is not changed. Writing new suggestions keeps what you typed yourself (not a suggestion you picked) | Research | test_titles_hashtags.py |
| Autopilot and Missions posts use the same subject, hashtag order, know-how and advice, skip titles that don't stand alone, and give the kind of title you usually pick (Brain → Learned) 6 points | Hypothesis | test_titles_hashtags.py |
| Not done: trend data for hashtags (none is available without an outside service), the 12-pair pilot (search vs curiosity titles) needs real posts: Posts → Results → Compare can run it | — | — |

## Measuring what worked (Posts → Results → Compare)

| What ClipForge does | Why |
|---|---|
| Compares by format, channel, niche or clip length, one platform and one audience at a time | YouTube and TikTok count differently, and a small test group does not react like the public |
| Reads every post at the same age: the reading closest to 48 hours after your viewers could first watch it | A post read after a week always beats one read after a day |
| Medians, not averages | One viral post moves an average a lot and a median little |
| A difference is "clear" only with at least 5 posts on each side and a permutation test on log views below 0.1; otherwise "too few posts" or "no clear difference yet" | So a lucky streak is not sold as a lesson |
| The last 28 days against the 28 before | A comparable period, same reading age |
| A number the platform does not report is "not reported", never estimated | Honest numbers |
| YouTube numbers only after you confirm Google's approval for derived metrics | YouTube API Services Developer Policies |
| Each group ends with a test to run next ("Make 6 of your next 10 posts Picture-in-picture clips…") | Turns a hypothesis into something your own posts can confirm |

Tested by tests/test_compare_results.py. This is the only place ClipForge says something "worked", and it says it
about your posts, not about posts in general.

## The benchmark

`scripts/clip_quality_benchmark.py` runs the same footage through two versions of the clip finder with the app's
default settings and writes a before/after report: which moments are promoted, rejected or trimmed, and why. The
built-in footage is three scripts (`scripts/clip_benchmark/`: a podcast, a game stream and a tutorial) read by a
computer voice, with the traps real footage has. It is synthetic: word times are estimated and every word has the same
confidence, so it shows what the code does with those patterns, not how viewers react. It also runs on your own
footage (a folder of `audio.wav` + `transcript.json`).

Result on 2026-11-25, release line before batch 2 against this batch: see
[benchmarks/clip-quality-2026-11-25.md](benchmarks/clip-quality-2026-11-25.md).

## Still open

- The benchmark footage was written by us, so the new rules were checked against patterns we chose. Run the benchmark
  on your own videos (it never uploads anything) to see them on real speech.
- A reaction is found from loudness alone. Loud game sound with nobody talking looks the same as a shout, so a clip
  can keep up to 3 s of an explosion after the last word. The 3 s limit keeps that small.
- Live chat is not read (see the blocker above).
- Framing is checked when a clip is rendered, not while moments are ranked.
- Which layout, length or title kind works best for your channel is a question for Compare, not for this page.
