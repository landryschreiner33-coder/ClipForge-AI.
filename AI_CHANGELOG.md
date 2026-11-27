# AI changelog

## Smoother motion without GSAP: Taser, zapped robots, pop-ups, glides, caption pop, reordering — 2026-11-26 (Claude Code)

Landry asked whether GSAP could improve anything. The answer was no (it can't reach the canvas and WebGL loops or the
Python-rendered videos, ticks outside `document.getAnimations()` and the Reduced-motion switch, and has a
proprietary licence), so the six rough spots found on the way were smoothed with the browser's own animations.
Branch `claude/project-thread-wkj3fp`.

- **Taser:** the held Taser's sway uses `rotate`/`translate` (space.css) and the lunge is a Web Animation on
  `transform` (TaserItem.tsx), so they add up instead of fighting over one property (it used to snap about 3 degrees).
  The lunge and the ship's jolt restart without a forced reflow.
- **A zapped robot stands still** for its reaction (OfficeMotion.stun), so the lightning and words stay on it; its
  job and route are untouched and it walks on afterwards. Not under Reduced motion (nothing walks then anyway).
- **Pop-ups ease in and out** (`frontend/src/smooth.ts`, space.css "pop-ups"): dialogs rise in and fade out, menus
  (Make, More, Brain) scale in and out, the small-window menu slides, notes slide up and fade. Closing never waits:
  the real element is gone at once (focus, clicks, screen readers move on) and only an inert, aria-hidden copy with no
  ids or names fades. Pop-ups holding a frame, video or canvas close at once. A note replaced by a new one replays
  its entrance.
- **Glides:** picking a room on the ship glides the camera there (450 ms, OfficeMap.tsx; not under Reduced motion or
  Low power). The Brain graph's zoom buttons, arrow keys, 0 and Fit glide the view (260 ms, BrainGraph.tsx); a drag
  stops a glide.
- **Caption pop, preview and video:** Brain → Styles' preview pops each new page (90 ms from the preset's `pop`)
  and shows High energy's bigger current word; it re-renders 20 times a second instead of every frame. The finished
  video's pop (captions.py `build_ass`) only reached the first word (a word's own look ends with `{\r}`, which also
  ended the pop) and not at all in High energy (its lit word is drawn bigger): now every word of a page's first line
  grows in together, each to its own size (`test_a_new_caption_page_pops_every_word_not_only_the_first`).
- **Reordering slides:** files on Make a YouTube video and scenes of an animated short slide to their new place
  (FLIP, `useSlide`).
- Everything is instant under Reduced motion and visible to `document.getAnimations()` (the demo recorder and the
  browser checks step it). No new dependency.
- **Review (3 reviewers, a verifier per finding), all fixed:** the Office's and Studio's Escape now skip a fading
  dialog copy (`.dialog:not(.leaving *)`); a copy keeps the original's scroll and list choices; a robot carrying or
  receiving a handoff is never held by a zap, and a stun ends at its time even while the feed is frozen (the list
  of stuns is replaced every frame); a reorder during a slide measures places without the slide and carries on from
  where each row is shown; a menu reopened while its copy fades focuses its real first item; the Brain map's glide
  never steps backwards on its first frame, and a drag or new glide starts from the view last asked for.
- Video of every change: /mnt/project-files/smooth-polish/smooth-polish.mp4 (record.js beside it).

## ClipForge's own viral predictor — 2026-11-26 (Claude Code)

Landry: "reverse engineer how their viral predictor works so we can implement it to help the videos go more viral"
(Higgsfield's Virality Predictor). Built from Higgsfield's public page, published coverage and research only; nothing
decompiled or scraped. Details, sources and every number: [docs/clipforge/VIRAL_PREDICTOR.md](docs/clipforge/VIRAL_PREDICTOR.md).

- **Every clip is predicted after it renders** (`clipfoundry/predictor/`): a viral score 0-100, the hook (first 3 s of
  picture, sound and words), a hold curve (share still watching each second, average watched, hold rate), the
  strongest moment, a five-channel heatmap (vision, sound, language, attention, memory), reasons tied to moments.
- **Fixes it tried first:** start later, end earlier, remove pauses, captions, the hook on screen, punch-ins, louder
  sound, tease the strongest moment; only those that do not lower the score are offered, and Add to my edit puts one
  in the clip editor.
- **Make → Check a video:** any video up to 10 minutes, measured on this computer.
- **Wired in:** clip picking (a moment's hook and hold move its Clip Score by at most 5), the posting plan's expected
  retention, the prediction kept with each post, and a bounded learner that measures accuracy on the owner's posts,
  calibrates average watched (from 15 posts) and adjusts the score's weights (from 30, at most 40%).
- **Screens:** the clip editor's Viral predictor card, Prepare post, clip cards, Publishing → Results (how well it
  matched), and an on/off switch in the AI settings. ClipForge AI's app guide has "The predictor".
- No brain model: Meta's TRIBE v2 (which Higgsfield may use) is CC BY-NC, so the channels are measured from the clip.
- Tests: `tests/test_viral_predictor.py` (19).
## ClipForge AI watches and listens — 2026-11-26 (Claude Code)

Landry: "Make it so it can actually watch the videos frame by frame and listen to the audio or piece of media, so it
doesn't guess what's in a clip and the clips are better." Design and numbers: `docs/clipforge/WATCH_AND_LISTEN.md`.

- **Listening** (`pipeline/listen.py`): YAMNet (Google, Apache-2.0, 521 sounds) ships inside ClipForge as
  `assets/models/yamnet.onnx` (7.5 MB, built from Google's weights by `scripts/export_yamnet.py`, same answers as
  TensorFlow within 0.003) and names every sound of the whole track on the CPU: laughter, applause, cheering,
  screaming, a gasp, music, explosions, crashes... A "reaction" is now a reaction heard, not any loud stretch.
- **Watching** (`pipeline/watch.py`): every video decoded once at 2 frames a second (VideoToolbox on a Mac) and
  every frame measured: movement, hard cuts, faces, light, sharpness, a tiny thumbnail. Shots, action, still parts.
- **Seeing** (`eyes.describe_video`): the built-in model is shown every part of the video (4 frames, the words, the
  sounds) and says what happens, most promising parts first, within a time budget; answers are kept.
- **Clip picking** (`pipeline/senses.py`, `candidates.from_senses`, `deep.py`, `scout.py`): new candidates built
  around laughs, cheers, explosions and bursts of action (also where nobody talks: a time window on shot cuts); what
  was seen and heard counts in every ranking and in the Clip Score (at most ±9, explained, plus up to ±12 toward
  what happens for clips with little talk); the scout and judge read ⟨seen/heard⟩ notes.
- **Where you see it:** each clip's Why ("What happens", "What is heard", "The picture"), ClipForge AI's `clip`
  tool and a new `watch` tool, and Settings → ClipForge AI → Watching and listening (`ai_listen`, `ai_watch`,
  `ai_watch_budget_s`).
- Tests: `tests/test_watch_and_listen.py`; real machines: `.github/workflows/watch-listen-check.yml`.

## Editing quality, batch 4a: speed, speed ramps, freeze frames, slow zooms and pans — 2026-11-26 (Claude Code)

Batch 4a of Landry's "majorly improve the editing" (plan in
[docs/clipforge/EDITING_CRAFT_RESEARCH.md](docs/clipforge/EDITING_CRAFT_RESEARCH.md)), from
`claude/project-thread-c3hbwh` on top of batch 3 (PR #83). Details:
[docs/clipforge/RANGE_EDITING.md](docs/clipforge/RANGE_EDITING.md).

- **Speed** per clip in full videos, 0.25× to 4× (`clip.speed`), and **speed ramps** with smooth easing between 2 to 8
  points (`clip.speed_ramp`, four presets). One time map per clip (`studio/retime.py`) drives the picture (FFmpeg
  `setpts` + `fps`), captions, overlays, anchored sound, chapters, the cold open and picture placement.
- **Sound keeps its pitch:** a retimed clip's sound is stretched with WSOLA (`retime.stretch`); normal speed is exact.
  No split edits next to a retimed clip.
- **Freeze frames** (`kind: "freeze"`, `hold_ms`, new edit op `freeze`): "Freeze here" inside a clip splits it, "Hold
  the last frame" adds one after it; room tone plays under them like under a photo.
- **Slow camera moves** (`clip.motion`: 2 to 6 keys of zoom 1.0-1.5 and centre, smooth or linear) on recordings,
  freezes and photos: zoom in or out, pan left, right, up or down.
- **Editor:** Speed, Speed ramp, Split or freeze and Camera move in the clip panel; lengths shown as they play.
  **Plain words:** "put clip 3 in slow motion", "speed up the intro", "add a speed ramp to the jump", "freeze the last
  frame for 2 seconds", "slowly zoom in on clip 2", "remove the slow motion" (`studio/edit_requests.py`).
- **FilmCraft:** with "auto", finals that use any of this stay on the built-in engine (`engine.retiming_in_use`); a
  FilmCraft render says what it skipped. The timeline export carries speed as a linear time warp and freezes as
  freeze-frame effects and lists the rest as not carried.
- **Tests:** `tests/test_retime.py` (16 fast, 7 real renders read frame by frame from a numbered test video), plain
  words in `tests/test_studio_edit_requests.py`, routing in `tests/test_craft.py`. Not verified: real speech at
  extreme speeds, phone footage with variable frame rate.
- **Review fixes (before merging):** a review with real renders found 15 problems, all fixed: frames are found on the
  file's own frame grid and never past the picture's last frame (freezes at a clip's end, 24 fps freezes, a freeze
  near the end ends the clip on it); retimed pieces read 100 ms early and use `fps round=up`, so every frame is the
  mapped one; camera moves count output frames (60 and 24 fps footage keep the pace); splits give each half its part
  of the same ramp or move (`speed_ramp.range`, `motion.range`, exact) and move attached pictures, sounds and chapters
  with their moment; a 40 ms straight crossfade where two halves of a slowed clip meet; leads before a moment are
  video time (negative offsets, the swish's new anchor `lead_ms`), and the editor's "Starts after its clip" is video
  time (`audio_move.out_offset_ms`, `audio_timeline[].clip_ms`); the speed and camera-move rules take only phrases
  that name clips (numbers in words, ordinals, the intro, the ending), refuse photos in words, undo only the right
  direction and also clear a punch-in. List in docs/clipforge/RANGE_EDITING.md, "Review". A second review of the
  fixes found 8 more (undo "from the video" or "from it", a clip named "intro", photo and freeze answers, "2nd" vs
  "second", muted sounds in the editor field via the view's new `anchor_ms`, freezes at the start of short clips and
  just past half a second), all fixed with tests.

## Text-message stories (the TikTok kind), up to ten minutes — 2026-11-26 (Claude Code)

Landry: "I want the text stories to be like the ones on TikTok like these in the pictures and they should be several
minutes long up to 10 and either you can put your own script in or have it write it for [me] and don't release
anything yet only merge what's done". Branch `claude/project-thread-gjc836`. The narrated kind stays as it was.

- **A new kind of Text Story, "Text-message story"** (`makers/chatstory.py`, kind `chat` in `text_stories`): a phone
  chat card (header with back arrow and unread number, round picture with the first letter, the name, video-call
  button; grey bubbles on the left, blue on the right, tails on the last of a run, colour emoji) appears a bubble at a
  time over the background, each message read aloud in its sender's voice, with a pop for theirs and a whoosh for
  mine. Pages: when the card is full a new page starts without the header. Looks: dark, light, dark with green
  bubbles. Pace quick/normal/slow, sounds on/off, read aloud on/off (unread: each bubble stays as long as it takes to
  read), unread number 0-999, whose phone it is, the name at the top. No watermark and no one's branding.
- **The script:** one message a line, `Name: message`; a line without a name adds to the last person; `Me`, `I`,
  `You` or `Myself` is whose phone it is (else the second person to write); three or more people is a group chat with
  names over their bubbles; `\` at the start keeps a "Word:" line as text. Limits: 400 messages, 320 characters a
  message, 1,800 words, 8 people, 10 minutes (checked again once the voices are recorded).
- **Voices:** everyone gets one at once (whose phone it is the best voice, the others another kind first, a voice
  comes back higher or lower when there are more people than voices); each person's voice, speed and tone with
  Hear. Each message's voice is recorded once (`lines/<hash>.wav`) and levelled; messages of emoji or dots alone are
  not read. Pronunciations work as in narrated stories.
- **Up to ten minutes for both kinds:** narrated stories now take 1,750 words (was 650) with lengths of about 5 and 10
  minutes; ClipForge AI plans a long story (a beat a part) and writes it about 300 words at a time, each part seeing
  how the story so far ends; a long revision goes a part at a time. A part far longer than asked is cut at a sentence
  and a last part that would not fit is asked for again shorter (then cut, with a note).
- **ClipForge AI writes chats** (`writer.write_chat`): kinds of story plus "Comeback", lengths of about 1, 3, 5 and
  10 minutes (20/55/95/185 messages); up to 32 messages in one go, longer ones planned and written 32 at a time;
  revisions 40 messages at a time keep the people; the contact's name comes from the model; "follow for part 2"
  endings are taken off. The assistant's `write_text_story` takes `kind` and `length`.
- **Page:** Text Stories (+ Make → Make a text story) has New text-message story and New narrated story; the chat
  editor has Chat (script with a live phone preview in the chosen look, the writer), People and voices, Background,
  Look and sound, Preview, Export. Free footage ideas start with satisfying, cooking, cutting food, soap cutting,
  kinetic sand; "Let ClipForge pick" also prefers clips named for cooking, cutting, slicing, kitchen and food.
- **Rendering:** the card's pictures are drawn with Pillow (Inter, bundled; colour emoji from the computer's font,
  read only) and shown by FFmpeg's concat reader over the background (`overlay`), a new bubble rising in over two
  frames; the pictures are deleted when the video is made.
- **Review fixes** (an independent review found 17 things; all fixed, each with a test that failed before):
  symbols the emoji font lacks (★ ✓ ✗ ♪) are drawn as letters, and every character Inter lacks uses the first font
  of the computer that has it (Chinese, Japanese, Korean, Hindi, Thai, Hebrew; Windows and Mac lists too), also in a
  group sender's name and the round picture's letter; lines and pages are worked out once at 1080 (`bubble_lines`)
  so the preview matches the video; a message too long for a page ends with "…" on the card (the voice reads all of
  it) and an opening one too tall for under the header starts its own page; a line read by a stand-in voice is not
  kept, so the next recording asks for the chosen voice again, and each kept line has a note of its voice and licence
  (`lines/<hash>.json`) so the licence text survives rebuilds and lists each person's when they differ; reading
  without voices keeps the recorded lines; each card picture starts on its own 1/30 s frame (`option framerate` in
  the list, used when the FFmpeg takes it, FFmpeg 5 or later); ClipForge AI's revisions keep "Automatic" whose
  phone it is with the same person, match a sender whose emoji went missing, ask again and then keep the part when
  an answer drops a person or most of a part ("Unchanged."), and write `//` messages so they read back the same;
  switching a story to narrated and back keeps its messages. Page: what is typed is never replaced by the saved copy
  (a new line or space before a pause stayed lost before), the name at the top and the unread number are saved a
  moment after typing and when the page closes, Hear skips messages without words, "Automatic" names whom it would
  pick (`chat.auto_phone`), and the Speed and Tone sliders say whose they are.
- **Second review of the fixes** (3 reviewers, a verifier per finding): 5 more confirmed and fixed. A preview bubble
  is also as wide as its words drawn at the small size (without raqm, as on most Windows installs, they came out
  wider and ran past the edge); the first bubble stays under the header and is cut to the 16 lines that fit there
  (moving it to a page of its own lost the header for the whole video); a short closing part of a long story can come
  back as short as it was; a chat revision that cuts ("down to the best 6") is not held to half the messages; a
  revision keeps the phone with the same person also when the chosen person has left the chat; Stop pressed just as
  ClipForge AI finished writing brings the written text into the page.
- **Tests:** `tests/test_chat_stories.py` (31: script, limits, whose phone, voices, timing, pages, writer short and
  ten-minute chats and a ten-minute narrated story with fake models, a real voiced preview checked frame by frame,
  a slow export, and 15 for the review fixes); `test_text_stories` now checks the 1,750-word limit. Demo:
  `/mnt/project-files/text-stories/text-message-story-demo.mp4`. Not verified: a real model writing a ten-minute
  chat, Mac and Windows voices and emoji fonts (the cloud has eSpeak and Noto Color Emoji only).

## The Taser gets Landry's picture, the Missions logo, and bigger zaps — 2026-11-26 (Claude Code)

Landry sent two pictures: "Use this as the tazer design and the other as the missions logo and improve the getting
taxed animations".

- **The Taser is Landry's pixel-art picture** (`public/space/taser.png`, with its prong sparks split out as
  `taser-sparks.png` so they crackle, and its cyan light turning amber while it recharges), on the charger and in your
  hand. Held, it hangs under the pointer, so the zapped robot stays in view.
- **The Missions logo** in the side bar is Landry's orbit with a star (`ui.tsx`, icon `missions`).
- **Bigger zaps:** every zap opens with a shock (the robot rattles, its skeleton and a white flash take turns, sparks
  burst), lightning runs from the prongs over the robot, and a comic "BZZZT!" (or "ZAP!", "KRZZT!"…, never the same
  twice in a row) pops up. Then comes one of twelve reactions, the nine before plus three new ones: a glitch (the
  robot splits into colour bands with pixels flying), a reboot (it slumps dark, a loading bar fills, it powers back
  on) and a rocket (it blasts up on a flame and lands). The four biggest (falling over, overcharge, reboot, rocket)
  jolt the whole ship for a moment. Under Reduced motion there is no lightning or jolt: a still spark and the words.
- Tests: `tests/test_taser.py` (12 reactions dealt fairly, the shock in every one, the new reactions' pieces, sound
  words, lightning lines, the pictures in the app and the built app, the Missions logo).

## ClipForge AI sets "End on the last frame" from words — 2026-11-26 (Claude Code)

After editing batch 3 (PR #83) added "End on the last frame" for music set to Loop, ClipForge AI can set it: "end
the music on the last frame", "make the song end with the video", "play the song from its start" (rules, no model,
`studio/edit_requests._back_time_said`), and an AI service may answer `audio_back_time`. Only music set to Loop that
plays to the end is changed; music that already does it is left alone (ClipForge's own music by default). The app
guide gained "A full video's sound and music". Details: docs/clipforge/CLIPFORGE_AI.md, "A video's music ending, in
words".

## Editing quality, batch 3: full videos (split edits, room tone, music that ends on time) — 2026-11-26 (Claude Code)

Batch 3 of Landry's "majorly improve the editing" (plan in
[docs/clipforge/EDITING_CRAFT_RESEARCH.md](docs/clipforge/EDITING_CRAFT_RESEARCH.md)), from
`claude/project-thread-c3hbwh` on top of batch 2 (PR #82). Details:
[docs/clipforge/LONG_EDITING.md](docs/clipforge/LONG_EDITING.md).

- **Split edits (J and L cuts)** at straight cuts between two recordings: the sound edit moves 8, 6 or 4 frames off
  the picture cut, only where no word changes hands (`studio/sound_joins.py`, the sound section of `engine.render`).
- **No clicks where two recordings meet:** 40 ms equal-power crossfades that only reach into room sound.
- **Room tone** under title cards, photos and videos without sound: the nearest recording's quietest stretch between
  words, looped seamlessly at that recording's volume, written a block at a time; it steps aside where a voiceover
  plays (0.1 s fades) and stays off muted clips; it runs on under a neighbouring clip's own fade.
- **Music that ends on the last frame:** ClipForge's own beds (and any music with the new "End on the last frame"
  ticked) start so their end lands on the last frame, fading in at least 1 s. Looping music now repeats one decoded
  pass exactly (FFmpeg's own looping of AAC/MP3 padded in 0.1 s of silence every 5 repeats, before this batch too).
- **FilmCraft:** with "auto", finals that use any of this stay on the built-in engine so they sound like the preview
  (`engine.sound_joins_in_use`, which takes the preview's own report of room tone and moved music when there is
  one); a FilmCraft render says what it skipped (`craft_skipped`, now shown with the version, together with batch 1's
  colour note, which was computed but not shown before); a version finished by hand in FilmCraft says nothing.
- **Defaults:** the balanced feel cuts instead of dissolving (calm keeps dissolves); "Edit it for me" punches in at
  its normal level too; whooshes at most every 15 s; a short's hook title is on its first frame; one-piece clips fade
  their sound over 10 ms at both ends.
- **Where:** the video editor's Sound panel says what the last render did; music items set to Loop have "End on the
  last frame" (`audio_set` field `back_time`).
- **Review before the PR** (2 reviewers, 9 findings; the verifiers ran out of usage after 2): all 9 handled. FilmCraft
  finals (2), owner's songs back-timed and impossible to turn off, a set-length loop back-timed, the container length
  used for MP3/AAC, a dip where a clip's own fade meets room tone, room tone in memory, level wording; and split edits
  rarely fit the app's own tight edits, which the doc now says (the 0.1 s word margin is kept). A second review (3
  reviewers, each finding checked by a verifier) found 5 more, all fixed: gaps and a late ending in looped AAC/MP3
  music, room tone dropped from a whole photo a voiceover only touched, FilmCraft skipped on "auto" when no room tone
  was found, a wrong note on hand-finished FilmCraft versions, and "End on the last frame" shown for music that stops
  before the end.
- **Tests:** `tests/test_sound_joins.py` (9 fast, 3 real renders that fail when a feature is turned off) and the
  FilmCraft routing in `tests/test_craft.py`. Not verified: real recordings with real room noise.

## Helpers that promise in more words — 2026-11-26 (Claude Code)

Same thread, after PR #79 merged. The last real-model check (run 45788754134) showed the Script writer answering
"@Script writer …" with "Got it: I'll write a two-line hook … I'll keep the tone strong and engaging, with a clear
hook in the first line…". For a helper, `intents.promise(…, helper=True)` reads any "I'll …"/"Let me …" sentence
beside a promise as more of the promise when no quotes or new lines hold the work; it is asked to write it
(`NUDGE_DO`), and `_ask_agent` reports it to ClipForge AI. `NUDGE_DO` lists no examples any more (the model copied
them back), and a helper that still only promises gets one more round with its job alone and no tools, as the
planner asks it; in the check on that (run 45798706829) the Script writer wrote its hook. Details:
docs/clipforge/CLIPFORGE_AI.md, "After the sixth check".

## Editing quality, batch 2: short clips (punch-ins on cuts, sound effects, caption timing) — 2026-11-26 (Claude Code)

Batch 2 of Landry's "majorly improve the editing" (plan in
[docs/clipforge/EDITING_CRAFT_RESEARCH.md](docs/clipforge/EDITING_CRAFT_RESEARCH.md)), from
`claude/project-thread-c3hbwh` on top of batch 1 (colour). Details:
[docs/clipforge/SHORTS_EDITING.md](docs/clipforge/SHORTS_EDITING.md).

- **Punch-ins on jump cuts:** where a pause or filler was cut out, the shot size switches 1.00/1.10 on the cut's
  own frame (1.06 for sources under 1080 lines), centred on the face; never within 0.6 s of the last change.
- **A change every few seconds:** no framing held over 5 s; long stretches get an eased change at a pause.
- **Push-in on key words:** rationed (one per 6 s), landing on the word; with a cut in the way it comes in on the cut.
- **Sound effects from the edit:** a soft whoosh with each push-in, a light pop on each coloured key word, made by the
  app (no files), 18-20 dB under the speech, following its real loudness and the clip's volume; one Settings choice
  for clips and full videos.
- **Captions:** a new page on a jump cut, words lit 40 ms early, lines kept clear of the apps' buttons, a gentle pop.
- **Where:** Settings → Clips → Extras, the clip editor (Layout and Audio, with what the last render did), skills,
  styles, Brain notes and Full Cloud (`sound_effects`). The old sentence-level `render.zoom_curve` is gone.
- **Review fixes before the PR** (10 confirmed): the zoom switch lands on the first frame of the new shot at any
  speed (`render.Timeline.cut_frames`), no eased push across a cut or one-frame spike after one, caption pages turn
  with the cut despite the 40 ms lead, effects follow the speech level and the clip volume, no pops for Minimal
  captions, two `sound_effects` fields merged into one, the effects track deleted after the encode, the app rebuilt.
- **Tests:** `tests/test_moves.py` (14 fast, 1 real render); fast suite 3,447 passed, slow suite 38 passed (1 caption
  test updated for the new side margins). Not verified: how it feels on real talking-head footage.

## Editing quality, batch 1: colour (phone HDR, automatic correction, matching, looks) — 2026-11-26 (Claude Code)

Landry asked for deep research on how videos are edited and for much better editing. The research and the five-batch
plan are in [docs/clipforge/EDITING_CRAFT_RESEARCH.md](docs/clipforge/EDITING_CRAFT_RESEARCH.md); this is batch 1,
from `claude/project-thread-c3hbwh` on the release line at c89e5bb. Details:
[docs/clipforge/COLOUR.md](docs/clipforge/COLOUR.md).

- **Phone HDR video looks right:** HLG (iPhone and most Android phones) and PQ are tone-mapped to normal video in
  clips and full videos; before, they came out flat and grey. Untagged HD video is read as BT.709 (FFmpeg alone
  reads BT.601) and every output is tagged BT.709.
- **Automatic colour** (Settings → Defaults, on): white balance from the greyest pixels (a blue sky is not a cast),
  levels only when clearly off and changing brightness only, vibrance on washed-out colour, skin protected; a game or
  screen recording is half corrected; measured once per recording or clip, cached, never per frame.
- **Matching:** in a full video, recordings of people are nudged toward the one that plays longest.
- **Looks:** Natural, Clean and bright, Warm, Cool, Film, Teal and orange, Moody, Vintage, Black and white, with a
  strength. **Clean up grainy footage:** measured noise picks nothing, `atadenoise` or `fftdnoiz`.
- **Where:** a Colour tab in the clip editor, a Colour panel in Make a YouTube video, Settings → Defaults, and edit
  requests in plain words ("make it black and white", "fix the colours", "tone down the look"). The full-video plan
  keeps `color`; `color_grade` is now a real edit.
- **How:** `pipeline/grade.py` bakes everything for a recording into one 33³ `.cube` applied by `lut3d` (in every
  FFmpeg build, including the Mac one without zscale); the grade's hash is part of the engine's piece key.
- **Full Cloud** jobs carry the colour choices (`worker_api.SETTING_KEYS`), and the Mac desktop check asserts the
  bundled FFmpeg has `lut3d`, `atadenoise` and `fftdnoiz` and that a render reports its colour step.
- **Review fixes** (an independent six-area review before the PR): full-range video (many Android phones, OBS,
  drones) and JPEG photos keep their blacks in both renderers, in previews and in the "fit" layout; untagged HD is
  measured the way it is rendered; HDR10 peaks are read; a cancelled or failed measurement is never cached; grain
  cleanup follows the size shown; colour words inside other requests are left alone; under "auto", finals whose
  colour step does something stay on the built-in engine (FilmCraft does not run it).
- **Tests:** `tests/test_grade.py` (25, fast) and `tests/test_grade_render.py` (2, slow); see the test log in
  `docs/IMPLEMENTATION_STATUS.md`. Not verified: real phone HDR footage and low-light grain, the Mac itself.

## Guards, second round: what the real built-in model still got wrong — 2026-11-26 (Claude Code)

Same thread. The real-model check on PR #79 (Basic level, run 45777094657) showed the first guards working (no echo,
complete project lists, the helper hand-off) and three slips left. Details: docs/clipforge/CLIPFORGE_AI.md, "Guards
for a small model", "After the first real-model check".

- A listing plainly asked for ("how are my clips doing?", "what projects do I have?") is looked up before the
  model's first round, so it answers from real numbers in one round.
- `intents.promise` reads sentence by sentence: "I'll delete … First, I'll check … Let me look at it." is a promise.
- A plainly asked change (delete, rename, make clips from a link) whose first round uses no tool shows its card,
  whatever the words claim; it waits for the OK.
- A helper that only says what it will write is told to write it now (`NUDGE_DO`), also after looking things up.
- The same look asked again in one answer is not run twice (`Outcome.looked`).
- **A second review (16 findings, each shown with a probe, all fixed):** "Let me see, your best clip is …" is an
  answer, not a promise; listings are read only from a whole short request; a rename needs a quoted or plain new
  name ("… please", "a catchy title" are left to the model); "Have the Critic's notes been fixed?" no longer runs the
  Critic; a helper repeating its job is caught; "[0:42–1:10] …" stays; a listing found before a failure is shown.
  Posts: "27 Nov 2 pm" is Nov 27 at 14:00, "marketing" and "novice" are no months, "Dec 30" on Jan 2 is the one
  just gone, "yesterday", weekdays and "the 25th" also find past posts to retry, "morning"/"afternoon"/"evening",
  "15 pm" is no time; one post on "my cooking channel" never comes from "Fishing channel"; approve all offers the
  posts it can approve first. Thumbs: only a model's answers (never the video planner's), a short liked answer fits
  whole, the "Sent over the internet" line and the toast say when learning is off.
- **After the second real-model check (run 45781339101 on d910464):** results read in one round, the delete card
  shown, the planner's Script writer wrote its part. Two slips left, now caught: the app's own card notes ("[Waiting
  for the owner's OK: …]") are removed from any answer (a helper answered with only that note), and a helper that
  still only promises after being asked again reaches ClipForge AI as "… only said what it would do … Write it
  yourself now".
- **After the third check (run 45782892862 on c9506ad):** the Script writer's answer was then empty twice. In the
  conversation the model reads, a helper's name and the card notes now stand beside "say" ("by", "notes"), never in
  it; a helper that still writes nothing is asked once more with its job alone (guard `alone`).
- **After the fourth check (run 45785137953 on 9279e9d, every must-check passed):** "Got it: I'm ready to write …" is
  a promise. A small review (4 findings, each with a probe) fixed: long helper notes no longer drop an answer from
  the conversation, card notes with brackets in a name are removed whole, a helper that proposed a change or kept a
  memory is not called a promise, the job-alone round is not nudged again.

## Guards so the built-in model gives real answers — 2026-11-26 (Claude Code)

Same thread, after the real Basic model (Qwen3-VL 2B) check on GitHub's machines showed it echoing the owner,
saying "Let me look." without looking, stopping at "Here are your projects:" and imitating "[Script writer]"
instead of handing the job over. Details: docs/clipforge/CLIPFORGE_AI.md, "Guards for a small model".

- `brain/intents.py` reads the owner's own words: a switched-on helper asked by name gets the job before the model's
  first round (`handoff`); a plainly phrased request has its one tool call (`guess`), used only when the model's
  round did nothing with it.
- `assistant.think`: an echo, a promise without a tool, an answer that stops at a colon or an empty one is replaced
  by that tool call, or the model is asked once more with what went wrong; "[Name] …" is removed from ClipForge AI's
  words; a look tool's listing (`Result.show`) the answer leaves out is added. What a guard caught is saved as
  `data.guards`.
- The real-model check prints the guards and has a new turn, "How are my clips doing?".
- **👍 and 👎 on answers** (`brain/ratings.py`, `Rate` in `ClipForgeAI.tsx`): a liked answer to a similar question
  becomes the example for the next one, 👎 reasons are avoided, a disliked answer to a very similar question is
  answered differently; ratings live in their answers and go with their chat.
- **Several posts at once:** `cancel_post`, `retry_post` and `approve_post` take `all: true`; post words, days
  ("tomorrow") and times narrow them strictly; one card lists them and always waits for the OK; one post that cannot
  change never stops the others.
- **A review of all of the above (19 findings, all fixed):** a guessed change always waits for the OK; guesses only
  for short, plain requests ("let me know…" is an answer, not a promise; "rename X" needs X's exact name); words the
  guard held are kept when the model fails; days ("Nov 28", "the 28th", weekdays) are read in the posting time zone
  and times exactly, a number it cannot read is said, state words ("failed") keep only those posts, at most 50 with
  the count said, soonest first; approve's account is `channel`; ratings: written under the OK lock, fit a budget
  (800 characters for small models), 👎 reasons sent without their questions, tools shown with a liked example,
  nothing read with learning off, the privacy page lists the rating among what a message keeps.

## ClipForge AI reads your results; the ready-made helpers get the tools their jobs need — 2026-11-26 (Claude Code)

Thread "Make ClipForge AI and agents smarter" (Landry: "make the AI way smarter and more useful same with the agents"),
branch `claude/project-thread-st8tpc` from the release line at c89e5bb.

- **`results` tool** (`brain/insights.py`): totals per platform as Publishing → Results counts them, the 5 best and 3
  weakest posts read fairly at 48 hours (`autopilot/compare.posts`, the owner's own views left out, posts under 48
  hours "too new to compare"), comparisons by format, channel, niche or length (`compare.compare`), and the lessons
  learned from results. YouTube numbers only after Google's approval for derived metrics (`learner.usable`).
  Without a model, "how are my clips doing?" reads the same summary.
- **Ready-made helpers** got the tools their jobs need: the Hook and title writer, Editor, Critic and Thumbnail
  planner read the clip (`clip`); the Growth coach reads `results` and `posts` first; the Researcher reads results;
  the Script writer opens the project. Helpers added before and left unchanged are upgraded once
  (`agents.EARLIER`, `_upgrade`); whatever the owner changed stays.
- The chat's "Sent over the internet" line and the privacy page name the results an online model may read.


## Final release, batch 5: what was still missing from Landry's 18-point list — 2026-11-26 (Claude Code)

A check of the batch 4 head against Landry's updated list of Nov 26 found what had not shipped yet; this batch
builds it (PR #72, from `claude/project-thread-8ua98o` on the release line at 3baaa34).

- **ClipForge AI acts on its own** (Landry: "no i want it to be able to do it on its own you dont have to say ok"):
  Settings → ClipForge AI → "Do it without asking" (default) or "Ask me first". New commands: edit a planned post's
  text, approve and post a YouTube post (the post page's checks), trim and edit a clip, clips or a mission from a
  link, a Text Story, Autopilot on/off/stop all/resume, the posting rules. Deleting always asks; a TikTok post always
  waits for the owner's OK on its page (TikTok's rules for apps). The main AI reviews every helper's work.
- **Titles and hashtags** (Landry's research): what the whole video is about (its name and the source's title)
  leads the Searchable title and the hashtags; hashtags go subject → topic → community, #viral/#fyp/#trending
  filtered, case duplicates removed, YouTube 1-3, TikTok 2-4 with the caption, Reels at most 5; Settings → Defaults →
  "Hashtags on every post"; vague titles sink; each recommended title names the moment the clip says it; a trim
  that cuts out that line flags the post text; text typed by hand is kept when the post text is made again.
- **Learning for automatic and live posts:** Autopilot and live clips use the title kinds and captions/pacing
  learned from your edits. **Clips that start on the point:** a lead-in, warm-up or outro is trimmed when clips are
  made (Settings → Defaults, on by default), shown in the clip editor with "Put it back", never learned as your edit.
- **The ClipForge name everywhere:** the Mac Keychain key is copied to "ClipForge profile encryption" (the old item
  stays, so a copy of the app from before the rename still opens the profile with the same key), the videos folder is Videos/ClipForge (an old ClipFoundry folder keeps being used), the
  Mac download is ClipForge-Mac-Apple-Silicon.dmg, and the Mac app refreshes its name in Finder and the Dock and says
  once where other copies are (nothing is moved).
- **More colours:** backgrounds forest, ocean, ember and black; accents gold, ruby and lime, and "Your own" colour
  picker. **Cancel upload** for Text Stories backgrounds and face cam recordings.
- **Full Cloud:** with a cloud computer set up, shorts' pictures and video are made there too.
- **Live face cam:** "Draw the face cam" on a live stream's row in Missions: a picture from the newest recorded
  minute, a box around the streamer's cam, and every live clip with a split view uses it from then on.
- **Animated shorts:** camera moves ease in and out, two new pushes that drift sideways, six moves in turn; with no
  characters added, a picture maker that takes reference pictures (FLUX.2 klein) draws each later scene with the
  first scene's picture so the main character looks the same; every voice-engine voice also comes deeper and
  brighter (30 voices instead of 10).
- **Text Stories:** "Find free footage" in the Background step searches Settings → Media sources and puts the pick
  behind the story, with its license and any credit it needs.
- **Releases without built-in sign-in** show a warning in the Mac build's summary (`write_oauth_apps.py --release`).
- **Text Stories open from Make** (Landry: "make sure the text stories is in the make tab like the rest not on the side
  bar as its own"): Make → Make a text story and the Studio's tile; no side bar entry; its pages light up the Studio.
- **Real example pictures for the animated-short looks** (Landry made them with ChatGPT from prompts ClipForge wrote):
  `public/looks/<look>.jpg` at 9:16 replace the shapes drawn in code (still the fallback if a picture can't load), and
  Brain → Styles plays its sample captions over a sunset-road picture (`public/brain/style-preview-*.jpg`).
- **The Taser is a thing you pick up** (Landry: "make it an actual item you can grab with animations ... the same
  thing shouldent happen all the time"): it lies on a charger in the Control room; picked up, it follows the pointer
  over the ship, swaying with its prongs crackling. A zap makes it lunge and recharge (amber light; zapping again too
  soon only fizzles), and the robot plays one of nine reactions drawn on the ship: a short-circuit shake, an X-ray
  flash, a jump, a spin, falling over with dizzy stars, soot and smoke, floating up, a dance with music notes, or a
  golden overcharge. A shuffled deal shows every reaction once before any comes back, never the same one twice in a
  row, each with its own lines and sound. Escape, the charger or "Put the Taser back" returns it; keyboard works too.
- **Review (4 reviewers, every finding checked again): 21 problems fixed.** ClipForge's own trims keep the plan's
  middle cuts (`blueprint._inside_trims`); owner hashtags with digits or other alphabets pass every check; a
  sentence's first word is not a subject; learned trims are measured from ClipForge's pick; title kinds use the same
  words everywhere (`postpack.kind_keywords`); live clips render with their learned look; text typed before the
  upgrade is kept; ClipForge AI never posts an approved TikTok post, checks the account its card showed, says so when
  a post was approved meanwhile, puts TikTok hashtags in the caption, and asks before making a project's clips
  again; the old Keychain item is kept; the live face cam picture is never an old one; the two new Settings
  defaults are saved; free footage joins the backgrounds as they are when it arrives; pushes drift as gently as
  pans; older shorts keep their automatic moves; the kept-picture note names the scene as the owner sees it.

## Final release, batch 4: space look, Text Stories, characters, Full Cloud — 2026-11-25 (Claude Code)

Last of the four batches in Landry's "ClipForge Final Release" prompt (sections 1, 6, 7 and 8). Built on
`claude/project-thread-hqwolr`; brought over as a checked patch and shipped from `claude/project-thread-8ua98o` on top
of batch 3 (PR #70).

- **Space look** (section 1): the big black hole is traced per pixel round a Schwarzschild hole with the ship and
  camera orbiting it (`blackHoleOrbit.ts`, `shipArt.ts`), falling back to the lighter turning disk when frames are
  slow or WebGL is missing; Settings → Appearance has Space view, your own accent colour (made readable on every
  palette, `prefs.accent_shades`), Reset colours, Sound effects (off by default) and the office Taser (show/hide).
- **Text Stories** (section 8, `makers/textstory.py`, `makers/voice_styles.py`, `TextStories.tsx`): a story read
  over background video. The script is pasted or written and revised by ClipForge AI; four voice styles with tone
  done by FFmpeg; pronunciations that keep the written words in the captions; favourite voices; backgrounds
  uploaded (trimmed, looped, moved, replaced) or picked by ClipForge from usable videos, or a moving colour
  background; title card and highlighted captions; preview and 1080×1920 export as studio jobs with Stop.
- **Animated shorts: characters and places** (section 7, `makers/cast.py`, `ShortCast.tsx`): a library of
  characters and places with their details and up to 3 reference pictures each (up to 4 go with one picture),
  used in every shot they are in (FLUX.2 klein's reference graph when the picture model can, the words otherwise);
  "Describe a change" proposals that show what would change before anything is applied; a colour drift check per
  scene against the character's pictures; a hold time per scene and one transition between scenes for the whole
  short. **Look examples** (`makers/look_examples.py`, `lookArt.tsx`):
  every look card shows an example picture (a drawn one until your picture maker makes real ones with "Make
  examples with my picture maker"), with a larger preview of the chosen look.
- **Full Cloud** (section 6, `fullcloud/`, [docs/clipforge/FULL_CLOUD.md](docs/clipforge/FULL_CLOUD.md),
  [deploy/WORKER.md](deploy/WORKER.md)): Settings → Processing chooses Local, Hybrid (pictures and video on the
  cloud computer) or Full Cloud: Make clips runs on your own ClipForge worker (ClipForge started with
  `CLIPFOUNDRY_WORKER_KEY`, answering only worker requests with that key). The desktop uploads the video or sends
  the link with the transcript and clip choices (style choices without their names), follows the job's stages, brings
  the clips back into the project (rows and files, this computer's paths) and deletes the job there. Estimates from
  the worker's own past jobs, the owner's hourly price, a monthly limit that stops a job before anything is sent,
  Stop, picking a job up again after a restart without a second upload, and a private test job that proves each
  stage ran on the worker. The project page shows what was sent, the stages, the cost and the log, and what stays
  on this computer.
- **Privacy page**: characters and reference pictures, Text Stories, Full Cloud (what goes to the worker, what it
  keeps and for how long).
- **Review fixes** (findings 7 to 25 of the batch's review, each with a test that fails on the code before it):
  a Text Story never stays "working" after ClipForge stops (it says what happened and the button works again); Stop
  that comes too late keeps nothing new; a script longer than one video holds is refused with the limit named; the
  title's pronunciations count in the captions; a story's export is never offered back as a background, nor a
  background whose file is gone; the editor link goes only to a project that still exists; a new style brings its
  favourite voice unless the story keeps its own; deleting a story removes its Brain notes; a voice engine's copy is
  kept with the story (and a preview of your own words is not kept); a failed render leaves no half file;
  pronunciations match words with punctuation round them; a trimmed background loops as trimmed. Animated shorts:
  "Nothing changed" when a change was already there, a change for one shot uses that shot's details, a held scene
  refits its transition, an unchanged reference picture is not checked again, and the library has Delete.
- **Full Cloud folder guard**: the worker's tidy-up and the desktop's fetch only touch a project's own folder inside
  the projects folder (`worker_api.own_folder`); a row that names any other folder is left alone and logged.
- **Second review of the fixes** (7 more problems, each with a test that fails before its fix): ClipForge AI's note
  about a story is written only after the story kept the writing (`writer.remember_story`), so a story deleted or
  stopped meanwhile gets none; a page that looks at a story in the middle of a Stop settles it as stopped, and a
  story is settled in one conditional write (`_settle`), never over a result; a dissolve is fitted with the editor's
  own check on whole frames (`engine.transition_too_long`), and one ClipForge shortened or turned into a cut comes
  back when the scenes are long enough again (`plan.short.fitted`); Apply to every shot also reaches a shot with its
  own words for that detail; deleting a library entry deletes its reference pictures that nothing else uses
  (`project_delete.drop_unnamed`); a Full Cloud project outside its own folder is refused before anything is sent,
  and one refused when its clips come back ends its job, so Process again can run it here. A last look found 3
  smaller ones, also fixed with tests: From my library marks the entry's pictures as handed out to the short
  (`cast.hold_refs`), so a Delete at the same moment keeps them; a transition the owner sets in the editor clears
  what ClipForge fitted; a Stop sent from a page that still showed a finished job never stops a newer one.
- **Fact-check of the release report** (every sentence checked against the code, each finding checked again by a
  second reader) found one real problem, fixed with 2 tests that fail before it: a TikTok upload stopped after its last
  part (Cancel upload in Publish Center, or Stop all or a job cancel on a planned post) while TikTok asked to wait
  before its status was read: the wait was cut short, so the post said "Nothing was published", or went back for a
  new time and would have been posted twice. Once every part is sent the status is now read to the end, and a late
  Cancel upload says so (`jobs.TOO_LATE_TIKTOK`). **GitHub's Mac FilmCraft check** then timed out again: the batch 4
  patch had been made from a tree without `covered.ts` (a684076) and the check's busy-page handling (72c4ab6), so
  applying it removed them. Both are back, and the orbiting hole holds still behind the editor too.

## Final release, batch 3: AI commands, saved chats, crew, learning — 2026-11-25 (Claude Code)

Third of the four batches in Landry's "ClipForge Final Release" prompt (sections 4 and 5). Built on
`claude/project-thread-hqwolr` on top of batch 2; merged as PR #70 (`f1c0618`).

- **Commands with real tools** (`brain/operations.py`): ClipForge AI can list posts (upcoming, problems, posted, in
  the Autopilot time zone), move a post to a time or the nearest free time, fix posts that are too close together
  (one card for all of them), cancel an upload or take a post off the schedule, retry a failed post, write a clip's
  post text again, change a clip's framing, render a clip, make a project again, stop work, pause or resume a
  mission, change an editing setting, and say why a project, clip or job is stuck (`diagnose_*`: stalled after 10
  minutes without progress, failed, waiting). Each runs the function the app's own button runs (the routes in
  `api.py` and `autopilot/routes.py`), so the same checks, gap between posts and approval rules apply. Changes and
  deletions wait for the owner's OK on a card that says what will happen; it never publishes or approves a post.
  It finds exactly one post, project, clip or mission first and asks which one when more fit. Work it queues comes
  back as `work` and the chat shows it queued, running (with progress), completed or failed
  (`GET /api/brain/chats/work/{kind}/{ref}`, `SavedChats.tsx` `WorkChip`). The commands are offered to the model
  only when the recent words ask for one (`operations.CUES`), so ordinary chats keep their short prompt.
- **The crew does the work** (`crew_check`, `crew_report`): clips handed to the crew go through the same final check
  Autopilot runs before a post (`autopilot/gate.py`: file, picture, sound, captions, cuts, text), as durable jobs
  with idempotency keys at the manual priority, so a retry or restart never runs one twice; a fixable problem goes
  back to the robot responsible (at most two repairs) and the Director's decisions are kept in the office feed.
  ClipForge AI reports what the crew found and decided and which command fixes what is left; the office robots
  animate from those real jobs.
- **Saved chats** (`brain/chat.py`): Talk to AI keeps as many chats as you start (New chat, switch, rename, delete),
  named after their first message until you rename one, kept across restarts with their actions. What ClipForge AI
  remembers is shared by all of them; a video's own chat stays with that video.
- **Learning from your edits** (`brain/learned.py`, Brain → Learned): each clip editor save is read for trims
  (against ClipForge's own start and end), framing, captions, pacing and title picks, plus thumbs up or down. When 3
  clips agree (70%), the habit is written down in words and checked on the owner's own edited clips, one left out at
  a time, before and after, by format; it is used for new clips only when it gets at least 20% closer on 4 or more
  clips. Explicit preferences (set by the owner) win over trends and are never overwritten. Each item can be turned
  off, changed, deleted; every change is a numbered version (with the preferences, whether clip choices move Clip
  Scores, and the words of the owner's rules for ClipForge AI) and Go back restores one. A new clip starts with the
  learned values in its edit (`process.learned_edit`, `edit.learned_keys`), so a value the owner never touched is not
  counted as their choice. The clip-choice model (`taste.py`) gets a held-out check (`learned.taste_check`) and an
  on/off switch; a title kind you usually pick is recommended first (`postpack.generate`). Publishing rules,
  accounts, spending limits and daily targets are never learned. Settings: `learn_from_edits`.
- **Privacy page:** a section on what Brain → Learned keeps, and saved chats in the ClipForge AI section.

## Final release, batch 2: clip quality, stream layouts, titles, Compare — 2026-11-25 (Claude Code)

Second of the four batches in Landry's "ClipForge Final Release" prompt. Branch `claude/project-thread-hqwolr`, from
the release line at `cf51120` (batch 1 merged). What is a platform rule, what is a hypothesis and what is tested:
[docs/clipforge/CLIP_QUALITY_RESEARCH.md](docs/clipforge/CLIP_QUALITY_RESEARCH.md).

- **Clip picking (Highlights and Full stories):** new reasons a moment is rejected or ranked lower, all found by
  the benchmark below: an ad or sponsor read (`text_utils.AD_PHRASES`, flag `ad_read`), talking to chat ("thanks for
  the follow", "gifted subs": `CHAT_CHORES`, flag `chat_chores`), two goodbye lines at the end (outro blocks), a
  "he" or "she" the clip never introduces (`candidates.unnamed_person`; rejected when the line just before the clip
  says who, so the version that starts there wins), "where was I" and "let me read chat" end a topic, a clip that
  ends by circling one point (`text_utils.repeat_run`), and a "one thing" line at the end whose answer comes after
  the cut (misleading cut). "Here is the one setting…" opens a question like "here's why". Phrase lists match whole
  words (`text_utils.count_words`): "use code" is not "because code". "No way!" is a reaction, not a reply.
- **Why a clip ranks where it does:** `virality.reasons` gives one line each for Opening, Context, Pacing, Payoff,
  Audio and Framing, shown under the clip's Viral Potential.
- **Suggested trims** (`pipeline/trims.py`, `GET /api/clips/{id}/trims`, editor card): a tighter start (warm-up
  words), an end on the point (outro, chat talk, a reply, a repeat), a line cut in half, and the dead air Remove
  pauses would take out. Remove pauses keeps up to a second after a question or "wait for it"
  (`trims.tension_pause`).
- **Live streams and long recordings:** a laugh, a shout or a crowd that starts within 3 s after the last word stays
  in the clip, up to 3 s of it (`virality.reaction_after`, `deep.optimize_bounds`, `candidates.refine_bounds`), and
  Remove pauses keeps it (`render.heard`); a clip that opens right after one gets a warning
  (`virality.reaction_before`). A face cam moved mid-stream is found in its new place. Chat messages are not read
  (a recording has none and ClipForge has no chat connection): documented as a blocker.
- **Stream layouts:** Gameplay + Facecam, Picture-in-picture (the cam in a box at the top, left or right corner,
  captions below it) and Gameplay only (the gameplay fills the frame, the cam is left out), per clip in the editor's
  Layout tab and per live stream. The face cam is found in the corner, or you draw a box for one clip or lock it for
  every clip of the video (`GET/PUT /api/projects/{id}/facecam`); a separate camera recording is lined up with the
  video by comparing up to five minutes of both sounds, or by the offset you set (`pipeline/facecam.py`,
  `/api/projects/{id}/camera`). When no cam is found the clip says so and falls back to your usual layout.
- **Titles and hashtags:** three options per clip, one of each kind where the clip allows: Searchable, Curiosity and
  The moment, all from the clip's own words; a recommended one per destination with a short reason; a title must make
  sense alone ("That's the setting" is not offered); a number is never the searchable topic. Fields are checked
  before posting (title 100 characters, YouTube description 5000 bytes, TikTok caption 2200 characters, hashtags).
- **Posts → Results → Compare** (`autopilot/compare.py`, `GET /api/performance/compare?by=`, local only): your posts
  by format, channel, niche or clip length, one platform and audience at a time, each read 48 hours after it went
  out; medians; "clear" only with 5 posts on each side and a permutation test below 0.1, else "too few posts" or "no
  clear difference yet"; the last 28 days against the 28 before; YouTube numbers only after you confirm Google's
  approval for derived metrics; each group ends with a test to run next. Never a promise of views.
- **Benchmark:** `scripts/clip_quality_benchmark.py` makes three synthetic videos (a podcast, a game stream, a
  tutorial, read by espeak-ng), runs two versions' real clip finder on them and writes a before/after report:
  [docs/clipforge/benchmarks/clip-quality-2026-11-25.md](docs/clipforge/benchmarks/clip-quality-2026-11-25.md).
- **Privacy page:** the face cam box and the camera recording copy are listed under "Your videos and clips".
- **Fixed after the GitHub check (three root causes):** the meaning vectors kept part of a group of equally strong
  directions, and which part a maths library returns differs between computers, so clip picks differed on GitHub
  (`semantic.whole_groups` keeps a tied group whole or not at all); Cancel on a post wrote back a stale copy of the
  post's info and could lose what the upload wrote at the same moment (`db.merge_publication_info`); stopping the
  built-in AI said it had stopped before its process ended (`builtin_ai.Server.stop` now lets go after the wait).
  Each has a test that fails on the old code.

## Final release, batch 1: name and icon, Cancel upload, one sign-in, Missions — 2026-11-25 (Claude Code)

Landry's "ClipForge Final Release" prompt (November 24, 8:58 PM Chicago time) asks for four batches. This is the first.
Branch `claude/project-thread-hqwolr` from the release line at `54f953b`, pull request #68 into
`claude/project-thread-x72wkd`.

- **Name and icon:** `scripts/make_icons.py` makes every icon from the attached gold command robot
  (`design/brand/clipforge-icon-gold-source.png`, checked by SHA-256): the 1024 px PNG (app, website, tab, TikTok
  form), the 128 px sidebar logo, a 16 to 256 px Windows `.ico` and the Mac iconset on Apple's grid; up to 32 px a
  closer crop keeps the visor and eyes readable. The art has a black background (the prompt says blue space); it is
  used as attached. The Mac app keeps its `ClipFoundry.app` folder, executable and bundle id
  (`com.clipfoundry.studio`), so an update replaces it in place and Keychain, WebKit storage and data stay; Finder,
  the Dock, Launchpad and Spotlight show "ClipForge" through a localized display name (`InfoPlist.strings`). About
  shows the release version, Help opens the website, the DMG artwork and the smoke test say ClipForge.
  `macos/find_duplicates.sh` lists every copy and the Dock's entries (read-only) with safe steps to remove a stale
  duplicate. Windows `.bat` titles, the phone page and the legal pages say ClipForge. Not done here: the Windows
  installer's Start menu and desktop shortcut names live on `claude/clipforge-downloads` (release time).
- **Cancel upload, imports:** the chunked browser import deletes its partial file (`uploads.cancel`) and says what
  happened when it came too late (finished: the asset stays; still writing: "checking"); a stopped upload's next part
  gets a 409 with its real state; the two whole-file uploads stop at once; a stop also reaches a picture on its way
  to the cloud computer and a result being fetched (no part file left). Unfinished uploads past their retention are
  cleaned when ClipForge starts.
- **Cancel upload, posts:** Publish Center and scheduled posts (post page, Posts menu) have **Cancel upload**, apart
  from cancelling a job (which only postpones) and Stop all. It stops after the part being sent; nothing is posted;
  the clip stays; Retry makes exactly one new upload. The request is written into the upload record
  (`info.cancel_requested_at`) and the post's history, so a waiting job, a restart or the orphan check never revives
  it. When the platform already has the whole video, the real state is shown: YouTube's upload session is asked
  (`youtube.session_state`: complete, partial, expired, unknown); a finished video is recorded as posted ("Too late
  to cancel"); anything unclear after the last part keeps the outcome-unknown hold (rule 6). A TikTok upload whose
  chunks all arrived is processing on TikTok and cannot be stopped; the page says so. A post queued behind another
  is cancelled at once and frees its place.
- **One sign-in:** Connect YouTube and Connect TikTok use ClipForge's own app registrations
  (`publish/oauth_apps.py`), so nobody pastes codes. Google's desktop client may ship inside the app (Google says
  such a client cannot keep secrets); release builds write it from repository secrets
  (`scripts/write_oauth_apps.py`, never committed). TikTok's client secret must stay on a server, so the app talks
  to a small stateless token broker (`deploy/tiktok_broker`, written and tested, not deployed) that adds the secret
  to the code exchange, refresh and revoke and keeps nothing. Your own developer app under Settings → Publishing →
  Advanced still wins. Accounts shows how each platform signs in and what each connected account can do (YouTube:
  upload, schedule, read, analytics; TikTok: Direct Post ("Only me" until TikTok's audit), Inbox, no scheduling
  API, phone handoff, stats). The privacy page names the broker.
- **Missions:** Missions sits in the main menu after Projects. Each mission shows its next upload (time in the
  Autopilot time zone, named; platform; account; needs-your-OK link), the office robots working on it now, and
  Pause uploads / Resume uploads for that mission alone. Times typed in the reschedule box are read in the Autopilot
  time zone (before: the computer's), with daylight-saving gaps refused; a time too close to another post answers
  with the nearest free time and a **Use the nearest free time** button.

## Release 2026.11.20: the moving sky — 2026-11-20 (Claude Code)

Landry picked "Release it now" on the release card (November 20, 2:49 PM Chicago time). Published from `72af02d`
(PR #66: the release line at `d3518f7`, which holds PR #65, plus the Mac release notes), merged as `f711d0f` with the
same tree.

- **Mac:** release `clipforge-mac-2026-11-20-72af02d` (unsigned personal preview, marked prerelease like the earlier
  ones), DMG 232,042,612 bytes, SHA-256 `b72b1faa04c3a533dad10d479d7d2ed81586c033acbe10266e2e87f3f7fdbdb8`, from
  build and test run 44815897634 (native build and bundled-app smoke; 3,109 fast tests passed, 2 skipped; 31 slow
  tests passed, 1 skipped), published unchanged by run 44823150295.
- **Windows:** `raw/2322e29352d5879e3876f2d5423209e0853f35ea/ClipForge-Windows-Setup.zip` (50,491,596 bytes, SHA-256
  `b5e32961fb976330c881f3222a2bba9014b073755731732fbcdac566dfc68de0`); Windows setup check 44816196313 installed
  2026.11.19.2 (raw/70f3450) first, then this one over it; record commit `9ca4882` on `claude/clipforge-downloads`.
- **Download page:** `gh-pages` `e0c197c` (previous `e349d2d`): `releases.json` 2026.11.20 with five changes and the
  checked and not-checked lists; Download page run 44824108721, Pages run 44824107927. The pictures were not retaken.
- **Fact-check:** each sentence of the Mac notes and the download page text was checked against the code at `72af02d`;
  then an independent check (four checkers by area, a skeptic for each finding) went through 66 claims. Three findings
  were refuted (the small black hole is hidden in windows narrower than 1024 px, as it has been since the space studio;
  the week of turning was run on a fake clock, which exercises the same arithmetic; the fact-check sentence describes
  the check that was running). One was confirmed: the page's not-tested list did not say that the hold-still settings
  had not been tried in a browser for this version. They were then tried on the built app
  (`/mnt/project-files/space-studio/moving-sky/still-probe.js`): Motion › Reduced chosen in Settings › Appearance, the
  computer asking for less motion, Robot activity › Low power chosen there and a hidden window each paused the sky's
  tiles and held the sky's canvas and both black holes (the Studio's and the Projects page's) still, and showing the
  window again set them moving; with Reduced, a page change and a tab change started no animation (with Full motion: 4
  and 2). The page's tested list now says so, and its not-tested list names power use. One wording was corrected too:
  the galaxy and the lightning's balls could stay blank for the rest of the visit, so the page says only that they could
  stay blank; the fix is titled "Fixed: …" as `download/UPDATING.md` asks.

## Moving sky, turning black hole and smooth page changes — 2026-11-20 (Claude Code)

Landry asked on November 20 (8:55 AM Chicago time): "give the backround animation like the stars and black hole and
when you swich tabs have it be a smotth transition send me a video of what they look like", then (9:52 AM) "also make
the backround animated like we are moving". Branch `claude/project-thread-t2bntx`, pull request #65 into the release
line. Released as 2026.11.20.

- **The sky moves as if the ship were flying on to the right** (`components/starSky.ts`, `components/StarSky.tsx`,
  `space.css`): the nebula holds still; the two tiles of small stars slide left (far 6, near 11 pixels a second),
  moved by the browser's compositor with Web Animations, so the page does no work per frame; a canvas over them draws
  brighter stars that twinkle and drift faster (10, 18 and 30 pixels a second), specks of dust rushing past (160 to
  260, 16 to 26 px long, about one for every 75,000 square pixels) and a shooting star every 7 to 16 seconds (only
  the next few are kept). The canvas redraws only the small squares that changed, 30 times a second (60 while a
  shooting star crosses). The masthead keeps its own copy of the sky (`.sky-back`), its tiles shifted to line up with
  the window's; a pixel comparison of the two differed by at most 6 of 255. The window's canvas is measured from its
  own box, so a scrollbar that takes room (Windows, or a Mac with a mouse) no longer squeezes its stars out of line
  with the masthead's copy, while the stars keep their places when a scrollbar comes or goes; a change of window size
  repaints both copies, a still one too; a screen of another pixel density gets sharp canvases (`pixelRatio.ts`).
- **The black hole's disk turns** (`components/blackHoleGl.ts`): every streak of the painted disk is drawn again each
  frame on the graphics chip (WebGL), the inner streaks faster, with the same widths, colours and adding-up light; the
  shadow picture masks the far side in the same pass. Points along each streak are spaced by the hole's size, so a
  small hole draws far fewer. Without WebGL (or with only a slow one) the canvas painter shows the picture with its
  travelling light. If frames come more than 45 ms apart through two 2.5-second stretches in a row (gaps over a second
  are the page held up and do not count), every black hole holds still, so a computer without a graphics chip stays
  quick, and tries again after 2 minutes, then 4, 8 and so on up to an hour (the cloud's browser trips it in about 5
  seconds; before, one frame there took 280 to 540 ms). The disk's clock counts only turning time, so a hole that
  starts again carries on from the picture last shown. The graphics chip counts in 32-bit numbers, so it gets the
  time since the start of the hour, and at each new hour every streak's starting angle moves on by as far as it
  turned (worked out in 64-bit numbers): the disk stays smooth however long the app is open, with no jump on the hour
  (with the old clock, 14 of 30 frames did not move after 7 days). If the chip loses the drawing (a driver update or
  reset), the hole starts again on a fresh canvas instead of turning into a blank or white box; after three losses,
  or when the chip's programs do not build, the canvas painter. Where the browser draws canvases on the chip
  (Windows), a reset gives them back empty: the canvas painter's hole and the sky's stars are painted again. The
  shared clock never reads earlier than the picture already shown, so a hole that starts turning never steps back.
- **After a graphics-chip reset, the space studio's other pictures come back too** (broken since the space studio,
  found by the last review): the ship's hull, rooms and bloom (`office/StudioScene.ts`, `paintBase`), the Brain's
  galaxy (`pages/galaxy.ts`, `BrainGraph.tsx`), the lightning's glowing balls and its still frame
  (`pages/brainLightning.ts`, `BrainGraph.tsx`) and still robot portraits (`office/Portrait.tsx`) used to stay blank
  until the page was opened again (the galaxy and the lightning's balls for the rest of the visit); each now paints
  itself again on `contextrestored`, and AGENTS.md rule 14 says so for new canvases.
- **Smooth changes** (`transitions.ts`): a new page fades in and rises 14 px (340 ms); a new tab fades in only what is
  under the tab bar it was chosen in, 8 px (260 ms), so a second row of tabs (Missions → Advanced, the Brain's Memory
  views) stays put when a tab in it is chosen and fades in with the rest when the change brings it in; what loads in the
  next 1.2 seconds (the list that replaces "Loading…") fades in too instead of popping in; tab highlights cross-fade;
  the Studio panel's highlight slides between Working on and Make, measured from the chosen tab so it fits the count of
  what is being made and larger text, and the panel fades in; the slim masthead hole fades in when you leave the Studio.
  Settings keeps its title and list of sections while Connections setup, Defaults, Integrations or Advanced loads
  (`LoadingPanels` in `components/ui.tsx`), so moving there from Appearance, Media sources and the rest changes only the
  section; before, the whole page flashed to a skeleton and rose. The content is there at once (focus, reading order and
  clicks unchanged); under Reduced motion everything is instant.
- **Review:** an independent review (four areas, a reviewer and a skeptic each) confirmed 13 problems and refuted 4;
  all 13 are fixed (scrollbars squeezing the window's sky, a still masthead copy after a height-only resize,
  pixel-density changes, an ever-growing shooting-star list, the sky's loop after sign-out, a lost WebGL drawing, the
  canvas painter after a half-made WebGL drawing, 32-bit time after days open, the Studio highlight with a count badge
  or larger text, hovering the chosen Studio tab, second-row tab bars fading). A second review of those fixes (two
  areas, a reviewer and a skeptic each) confirmed 3 more, all fixed: the canvas-painted hole and the sky's stars went
  blank after a graphics-chip reset; the disk jumped once an hour; a second row of tabs that a change brought in
  popped in. A last review of those fixes (two areas, a reviewer and a skeptic each) refuted both findings about them
  (an extra rebuild of the disk's strips when turning starts, which the clock clamp above removes anyway; a fade of
  the wrong bar after a hand-typed address with a trailing slash) and confirmed an older one: the ship, galaxy,
  lightning and portraits staying blank after a reset, fixed as above. It also noted the Settings flash, fixed too.
- **Checks:** see the table in `docs/IMPLEMENTATION_STATUS.md` (type check, build, pytest on the files that read the
  frontend, the sandbox's visual specs, and probes in the cloud browser for each fix).
- **Rules:** AGENTS.md rule 14 and `design/space-studio/README.md` list the new decoration and when it holds still.
- **Video for Landry:** `/mnt/project-files/space-studio/moving-sky/` (recorded frame by frame on a fake clock with
  every animation stepped by hand, because the cloud's browser draws WebGL slowly; `record.js` is kept beside it).
- **Not verified:** how it runs in the Mac app's window and on the RTX 3050 laptop (the cloud has no graphics chip).

## Release 2026.11.19.2: the space studio — 2026-11-20 (Claude Code)

Landry wrote "once done release the changes" on November 19 at 9:56 PM Chicago time. The release line held PR #62 (the
space studio, merged as `8c08f73` on top of the 2026.11.19 records `87a38c8`); no other finished pull request was
waiting. PR #63 (the Mac release notes only, two commits) was merged as `54ec586`, whose tree equals that of its head
`0597fef`; both downloads are built from 0597fef. Every URL, size, hash and run:
[docs/clipforge/WEBSITE_DEPLOYMENT.md](docs/clipforge/WEBSITE_DEPLOYMENT.md).

- **Fact-check before release** (four checkers by area: studio, clips, Brain, look; a skeptic for each checker's
  findings; 19 confirmed, 2 refuted, 174 claims confirmed as written; all 19 corrected): a whole team goes to its
  consoles while it has real work (running, queued, waiting, or stopped by an error in the last half hour;
  `office/DepartmentDuty.ts`), not one robot when its job starts; the badge above a robot is a job-state sign, and its
  task shows under Current task when you pick it; Working on shows how many things need you, not the things; while a
  clip renders, the status names the render's step instead of "Making clip N of M"; each Brain link strikes again two to
  six times a second (it keeps its shape for 2 to 5 frames at 12 a second), not about 12; Accounts shows how sign-in
  tokens are protected, not where they are kept; Live recordings lists only the streams being recorded now; a card shows
  a video's length only once it is known; a panel order saved in Customize studio no longer applies to the new Studio;
  Talk to AI is behind Menu on a narrow window; the walkthroughs simulated the upload and the clip making. The corrected
  sentences were then checked again (two checkers, a skeptic for each; 100 claims confirmed, 1 finding refuted) and
  three more download page wordings corrected: What's going on and Activity show the crew's steps for Autopilot, live
  streams and the Brain (a project you make yourself adds none); the screen's light shows Waiting for a live stream or
  an Autopilot video even while it is being made; larger text was checked on five screens, not all.
- **Checks on 0597fef:** Native Mac desktop app run 44677488448 (macOS 15 native build and bundled-app smoke; fast
  3,109 passed, 2 skipped; slow 31 passed, 1 skipped); Windows setup check 44677612640 (installed 2026.11.19
  first). The first builds from 36efa8b (the notes before the fact-check; Mac run 44673939916 and Windows check
  44674145380 passed, raw/7937c41) are not listed.
- **Mac:** release `clipforge-mac-2026-11-19-2-0597fef`, the unchanged DMG from run 44677488448, published by run
  44681038739. **Windows:** `raw/70f3450` on `claude/clipforge-downloads` (record commit `95aac79`). **Download page:**
  `gh-pages` `e349d2d`, with new pictures of the Studio, the ship, Make clips, Make a YouTube video, the animated short
  maker and the Brain, and new portraits of the 25 robots.
- **Not verified:** the new look in the Mac window and on Windows, the frame rate on Landry's laptop, real connected
  accounts, a real video going through ClipForge while the robots work.

## Space studio: the ship and its crew, a galaxy Brain and a first clip in three steps — 2026-11-19 (Claude Code)

Landry asked on 2026-11-19, with eleven reference pictures, to "Build ClipForge's animated space studio", then for
Courier type, room names, the activity badge above each robot, visible stars, one background that goes together, a
better black hole, and "make everything easily accessible so i can easly make all type of clips, make youtube video,
make animated short, clip live stream as it goes". Later that evening (8:47 to 8:50 PM CST) Landry asked to keep the
AI chat and every feature simple to reach, for the Studio's side panel to show what is being worked on (a screen of
the video, what's going on, the next video to publish at the bottom) with a tab for the create buttons, and to "make
the brain lines and balls look like lighting and make sure its animated". Branch `claude/project-thread-t2bntx` from
the release line at 87a38c8, PR #62. Released as 2026.11.19.2. What each screen became, the art and how the ship is
drawn: [design/space-studio/README.md](design/space-studio/README.md).

- **Studio:** a cutaway ship with 25 robots and CORE, drawn with Canvas 2D (`office/StudioScene.ts`) from one crew atlas
  (`public/space/crew.png`, `src/space/sprites.json`, floor plan `src/space/ship-world.json`). Robots move only for real
  job states and handoffs from the office feed. Engines, CORE's rings, blinking and lounge breaks are decoration stepped
  at about 12 frames a second; Reduced motion, Low power, a hidden page or a paused feed hold the ship still. Room names
  always show (one word each on a phone-sized ship, where a resting robot's marker is a dot), and each robot's state
  badge sits above its head. A name too long for one line shows one word (Media, Story, Sound), a manager watching its
  team stands at its own desk, and on a smaller ship the badges shrink a little, so no badge covers another badge, and
  from 1330 wide up no badge touches a room's name (at 1190 to 1320 and at 640 wide a badge can touch a name's bottom
  edge, at most 7% of its line). The Studio panel beside the ship has two tabs. **Working on** (first): what is being
  made now on a screen with a light that says what it is doing, its real step, progress only when measured and the
  robots on it; What's going on (the crew's last three real steps, See everything); the queue; how many things need
  you; Talk to ClipForge AI; and Next to publish at the bottom, with a little upright screen of the clip (its saved
  thumbnail), where and when. **Make**: Make clips, Make a YouTube video, Make an animated short, Clip a live stream,
  and "Not sure what to make?". The tabs work with the arrow keys. Under the ship: Whole ship, Activity, Reduce
  motion. Bottom strip: today's real counts and the computer's state. PixiJS and GSAP are removed (`frontend/dist` 4.5 →
  3.9 MB).
- **Brain:** Memory shows the real graph over a spiral galaxy painted once from a fixed seed (`pages/galaxy.ts`).
  Its real links are jagged bolts of light in each branch's colour and its dots glowing balls with white-hot middles
  (`pages/brainLightning.ts`, a canvas under the dots); while motion is allowed each link strikes again every 2 to 5
  frames at 12 frames a second, and it holds still under Reduced motion, Low power, a hidden or off-screen page or a
  lost connection. A frame took about 3 ms with 174 dots in the cloud browser; a computer that needs longer gets
  fewer frames. Beside the map (wider than 1180), the details panel is as tall as the map and scrolls inside, so a
  long panel no longer pushes the map below the fold on a laptop; a picked dot's name that would run off the map's
  edge goes under the dot; on a narrow window the Brain's tabs wrap onto more lines instead of hiding behind the
  edge. Branches are amber for Example videos, teal for Skills and ice blue for
  Recorded evidence. Picking a dot runs a light from CORE along its real path and settles a ring; search finds a
  real dot; Add knowledge is a menu (Add note, Teach preference, …); Open in editor. Styles: a form on the left and
  a caption preview you can play on the right, in the fonts the renderer burns in (`components/StyleStudio.tsx`).
- **Projects:** big cards with real lengths (`GET /api/studio/projects` rows carry `duration`), statuses, pins and
  menus, then Live recordings with the channel the link named. **Publishing:** tab counts, the time zone, the next
  scheduled post, and an empty review queue showing DOCK's amber beacon. **Accounts:** the default YouTube channel
  beside a drifting satellite that sends one signal pulse when an account newly connects; a TikTok row; where
  sign-in tokens are kept. **Settings → Appearance:** choices apply at once and save to the account
  (`APPEARANCE_SCHEMA = 3`: the glacier accent replaces violet as the default; a saved violet moves once); a live
  Studio preview at desktop, tablet and phone sizes; its Motion control and Studio's Reduce motion are one choice.
- **First clip:** + Make → Make clips: 1 Choose a video, 2 Pick what to make ("Pick the best moments" Highlights,
  "Keep each story from start to finish" Full story, Story parts), 3 Make clips, with working defaults and the rest
  under More options (which counts changed choices). Status words: "Finding the best moments", "Making clip 2 of 6"
  (was "Rendering clip"), and "Your clips are ready" with Review clips, which goes straight to the clips
  (`#/project/{id}/clips`). A chosen video that can't be read any more is named, with Choose file again. Save to
  computer is its own button wherever a clip can be saved (was Export).
- **Everything one or two presses away:** Talk to AI has its own place in the navigation (right under Studio, with
  the page title "Talk to ClipForge AI") and is now a Brain tab instead of hiding under More; on a phone the menu also
  opens Autopilot. Every page was checked to be reachable from the navigation, the Studio or + Make. ClipForge AI's
  own directions (`brain/appguide.py`) name the Brain's new places (Brain → More → Skills, Brain → Memory → Add
  knowledge → Add note, …) and the Studio's Make and Working on tabs.
- **A test that failed every evening:** `test_each_channel_has_its_own_daily_limit_gap_and_slots` planned posts one
  and three hours after the clock's own time, which are different days in the planning time zone from 9 PM to
  midnight; it fails the same way on the release line. It now plans from 8 AM the next day.
- **Type and sky:** Courier Prime (OFL, `frontend/src/assets/fonts`); one fixed sky (nebula and two star tiles); the
  black hole is painted in code (`components/blackHoleArt.ts`).
- **Tests changed:** e2e `office.spec` (the ship's rooms, Who watches, Animations, the lounge rule), `create.spec`
  (three steps, Review clips, Choose file again), `app-shell` (the Studio panel's tabs and arrow keys; Talk to AI in
  the navigation, the Brain's tabs and the Studio), `posts`; sandbox specs for the ship (renderer `ship`, the plain map
  when its code can't load), the Add knowledge menu, Open in editor, Ship view, the Brain's lightning (moves, holds
  still with Reduced motion and in a hidden tab) and Talk to AI from the navigation.
- **Checks:** `npm run build` (dist 3.9 MB). Python fast suite: all 3,111 ran, none failed, 2 skipped (finished in two
  parts after a cloud restart); after the last ship changes, the 339 tests in the 12 Python files that read frontend
  files passed again, and so did the 22 read-only browser tests of the office and the app shell. Python slow suite: 31
  passed, 1 skipped. Read-only browser tests (`e2e/tests`, against the demo app): 62 passed, 6 skipped, 5 failed, and
  those 5 (Autopilot ×3, Settings ×2) fail the same way on the release. Sandbox browser specs: 48 of 50 pass;
  beginner-flow (no Topics box) and video-setup (Change it by hand after coming back) fail the same way on the release.
  After the last ship changes, the ship's 31 sandbox specs passed again; department-office now also checks that no state
  badge covers another badge or a room's name (on the layout before these changes, at the spec's 1440 width, 7 badges
  and 3 names were covered). Measured at 36 window sizes from 390 to 1920 wide with every department at work: no badge
  covers another badge (before, a manager covered up to 63% of a teammate's badge, and the lower rooms' badges most of
  "Media research"); no badge touches a room's name from 1330 wide up or from 768 to 1180 wide; at 1190 to 1320 and at
  640 wide a badge can touch the bottom edge of a name (at most 7% of its line; up to 24% before the badges shrank on a
  smaller ship), and at 390 wide up to a fifth. GitHub "Native Mac desktop app" runs 44653081606 on 2014f3c and
  44658528437 on a273337 (before the badges shrank on a smaller ship): native macOS 15 build and bundled-app smoke
  (WebView, Keychain, tools) and the fast and slow Python suites passed; the run on the final head is named in PR #62's
  merge commit. Larger text at 1366×768 and 390×844: no sideways scroll and no cut-off text. Screenshots, frame
  sequences and both walkthroughs (mouse and keyboard only) are in `/mnt/project-files/space-studio/final/`.
- **Checks after the Studio panel, Talk to AI and the lightning:** `npm run build`; sandbox specs for the Brain,
  motion and the ship, 46 passed, and the Brain and motion ones again after the last layout fixes, 15 passed;
  `e2e/tests` app-shell, office and settings, 29 passed (the 2 Settings failures are the same on the release); 380
  Python tests (the 12 files that read frontend files, the reference and chat tests); the lightning's still check, 6 of
  6; its cost per frame, 2.9 ms with 174 dots (14 ms and about 6 frames a second with the processor slowed 4 times);
  screenshots at three sizes and with larger text: no sideways scroll, nothing cut off
  (`/mnt/project-files/space-studio/final/panel-talk-lightning/`, with `lightning.gif`).
- **Not verified:** Landry's Mac and Windows, the frame rate on the RTX 3050 laptop (the lightning too), real
  connected accounts, and a real video going through the pipeline while the ship animates. Schedule post for a clip you made yourself does
  not exist (only Autopilot plans times); a decision card asks Landry whether to add it.

## Release 2026.11.19: live clips, channels and a smarter ClipForge AI — 2026-11-19 (Claude Code)

Landry wrote "Make sure all the new changes are merged and then release them". The release line already held the
three finished pull requests since 2026.11.16.2: #58 (choose which channels each post goes to, `3bb861f`), #57 (live
clip quality, split view, take turns between channels, Stop clipping, `afc0c1f`) and #59 (smarter chat, Brain-led
clip picking, longer clips, lessons from results, post text rules, `d3a72c7`). No other finished pull request was open
(#46 is an unfinished draft; #20 and #15 are older branch-to-default PRs). PR #60 (`13e1fcb`, texts only) was merged
as `5430f7c` (same tree); both downloads are built from 13e1fcb. Every URL, size, hash and run:
[docs/clipforge/WEBSITE_DEPLOYMENT.md](docs/clipforge/WEBSITE_DEPLOYMENT.md).

- **Fact-check before release** (three checkers by feature area, a skeptic per checker's findings; 18 confirmed, all
  corrected): the privacy page now says Disconnect deletes only the sign-in tokens (the account's ID, name, picture
  link and settings, also "Tick for new posts", stay until the data folder is deleted: `db.disconnect_connection`
  keeps the row; the page's older Disconnect item said otherwise too); split view saves `cam.json` for any video with a
  face cam; a Make & upload request saves whether clips are split between channels; a clip keeps up to 160 characters
  of each memory or skill line that steered it, also after the memory is forgotten; the Brain line sent to a model
  holds up to three words per subject the owner's memories name; a canceled or failed live recording keeps its last
  minute sounds until a later try finishes it or the video is deleted. The Terms say a Make & upload request names
  the ticked YouTube channels and how clips are shared. Both pages are effective November 19, 2026. Mac notes and
  download page text: Stop clipping also stops the recording, a live stream has its own Split view choice (Settings ›
  Defaults › Split view does not affect streams), Post selected is YouTube only, about three live clips an hour while
  live (a standout adds one; the full-recording check can add more), the Brain moves a score by about 8 points at most
  and can lift a moment over the bar, lessons need 10 views and use YouTube's own numbers only with Google approved
  derived metrics, title length and question rules pick one of the clip's own lines.
- **Checks on 13e1fcb:** Native Mac desktop app run 44599070088 (macOS 15 native build and bundled-app smoke; fast
  3,105 passed, 2 skipped; slow 31 passed, 1 skipped); Windows setup check 44599233122 (installed 2026.11.16.2 first).
  The first build from 150978b (before the legal fixes; check 44596262908 passed, raw/1286dca) is not listed.
- **Mac:** release `clipforge-mac-2026-11-19-13e1fcb`, the unchanged DMG from run 44599070088, published by run
  44604316140. **Windows:** `raw/7122cce` on `claude/clipforge-downloads` (record commit `036771e`). **Download page
  and legal pages:** `gh-pages` `8809e3e`.
- **Not verified:** real Twitch, Kick or YouTube streams and real face cams; real uploads to two or more channels; a
  real TikTok account; a real model's answers; lessons from real posted results; Landry's Mac.

## Smarter chat, Brain-led clip picking, fuller clips, lessons from results — 2026-11-19 (Claude Code)

Landry wrote "improve the ai when i talk to it it does not know a lot of stuff and is dumb make sure it is smarter
and that the clipping system uses the brain", "make it so it proporally uses the brain data to improve its work and
esspecially the clips to know how to make viral ones", "make it so the clips arent so short and they are actually
longer and more engaging", "make it so the ai is involved in the clipping and that the brain is better used and when
it sees the data on what works and dosent it changes stuff" and "make sure it knows the best titals and captions to
use". Branch `claude/project-thread-dwz7vo` (release line afc0c1f merged in, with the live clips work of PR #57),
pull request #59. **Not released.** Framing and the split view from the same message are the live thread's work
(PR #57).

- **The chat knows more** (`brain/library.py`, `brain/appguide.py`, `brain/knowhow.py`): one search over sixteen
  playbooks (new: titles, post text and hashtags, gaming and stream clips), a 29-section guide to the app itself
  (what it does, where each thing is, with the page to open) and the advice lines of switched-on skills, which were
  imported and shown but never read before. Without a model the chat answers "how do I clip a live stream?" or
  "what makes a good title?" from them and links the page; with a model they go into the prompt, and the tools
  `clip` (a clip's words, score and reasons) and `settings` let it look things up. An answer says what it read
  ("From its guide to ClipForge", "From your skills"). The chat tells an owner whose computer can run a bigger
  built-in model (`builtin_ai.best_level`).
- **Clip picking reads the Brain** (`brain/steer.py`): the owner's memories, imported lessons and viral examples,
  the advice of skills about picking clips and lessons from results are read, without a model, into kinds of moment
  to look for or pass over (funny, a big reaction, a story, friction, small talk, ad reads …). A candidate that
  shows them moves by 0.02 raw per kind times the source's weight (the owner's rule 1.0 … a viral example 0.2), at
  most ±0.045 in all, so the Brain re-orders close calls and cannot pass a weak moment; an owner's "never" is a
  warning flag. Lengths the owner told it ("clips at least 40 seconds") set the run's lengths. The clip page shows
  "Your Brain: +N points. It …" and Brain → Memory counts the use ("clips").
- **Fuller clips** (`virality.grown`, `scoring._fuller`, `config.py`, `db._migrate_clip_lengths`): defaults are now
  25 / 45 / 90 seconds (saved 15 / 60 / 30 are moved once). The strongest lines of a moment are grown with their
  build-up and ending while the talk stays on the subject, never across a topic change or a pause over three
  seconds. On stand-in talks clean stories were already whole (40-60 s); messy talk went from a median of 21.6 s to
  31.9 s. A plain-talk clip with no marked line that ends on a finished point is no longer docked for "excessive
  setup". Live clips are not grown here (agreed with the live thread, which has its own).
- **The AI that reads the video** (`pipeline/scout.py`): its brief now carries the Brain's one-line picking summary,
  six memories that fit the video (900 characters, was 500) and the know-how and skills advice that fit it (1,300,
  was 1,100; a stream reads the gaming playbook). **Also fixed:** recording which memories it used raised
  ("Unknown place of use") and was logged as "recall failed" on every run, so the scout never got its memories.
- **Lessons from results** (`brain/lessons.py`, run by the learning job): with the same guards as the clip-length
  learning (48 hours old, enough views, one audience, YouTube API numbers only with approval) it compares, per kind
  of moment, clips that showed it with clips that did not. A clear difference (6 clips and 3 videos on each side,
  past a bar split over the kinds tested and read from Student's t with the error taken over videos, view counts
  compared only when read at about the same age) becomes
  a memory "From your results: look for …" that clip picking and the chat read. On pure noise about 1-3% of runs
  make a lesson. Forget it and it stays forgotten while the numbers say the same; switch it off or rewrite it and it is
  left alone.
- **Titles, post text and hashtags** (`brain/poststyle.py`, `pipeline/postpack.py`, `autopilot/packaging.py`): what
  the owner said about how post text looks (letter case, no emoji, how many hashtags, title length, a question as
  the title, no call to action) is applied by both writers. It never adds a word, so the grounding check holds. A
  model is told the choices in ClipForge's words and reads the advice of skills about titles. Hashtags that say
  nothing about the video (#fyp, #viral, #video; a platform's name unless the title is about the platforms) are
  dropped; a clip gets
  five at most. Story clips and Autopilot's rewritten post text follow the rules kept for their own video too.
- **Review fixes** (8 checkers, 23 problems, each with a test): a "no" in an owner's line reaches only until it
  turns to what they want ("no intros, just funny moments"); "never end clips on a question" is about the cut;
  "no more than 60 seconds" is a longest length and "the first 10 seconds" no length at all; "what else" is a topic
  change only when a line opens with it; a fuller clip never replaces one that passes the score bar with one that
  fails it. Post text: "don't forget the hashtags" is a yes, "thumbnail text in capitals" is not a title rule,
  "hashtags welcome" is not banned by the list before it. A JSON skill's own advice lines get the importer's checks
  and are checked again when read. Three guide lines were wrong (links with a transcript, automatic YouTube posts,
  which parts read notes); the privacy page now lists what the chat's clip and status tools send.
- **Second check** (4 checkers tried to break the fixes, a skeptic re-checked each claim; 30 confirmed, all fixed
  with tests): several fixes read owner sentences the wrong way round ("don't pick clips that are just small talk",
  "drop clips with swearing", "look for hidden funny moments", "I don't want you to add any hashtags"). A turn now
  ends a "no" only once the "no" has named what it refuses; only "cut" can mean making clips; a "no" anywhere in its
  part of a sentence counts for post text. Lessons take their error between videos (with kinds that come with some
  videos more than others, noise made a lesson in about a fifth of runs; now about 5%) and compare view counts only
  read at 48 to 96 hours. A skill line or name is checked as one line. 116 owner sentences about picking and
  lengths and 102 about post text are read as meant (`tests/test_brain_steer.py`, `tests/test_post_style.py`).
- **Third check** (4 checkers, a skeptic per claim; 15 confirmed, all fixed with tests). Lessons: the error was
  taken per side, so a reaction that doubled views inside every video was missed when the videos' reach differed
  (found in 3% of runs; now 100%), and one long stream holding most reactions still made a lesson from its luck in a
  fifth of runs (now under 1%): the error is now the gap's own spread with each video left out in turn, with fewer
  degrees of freedom when a few videos carry it. View counts read after 96 hours were dropped, so an owner who
  imports on day 5 got no lessons: counts are now compared when read within 1.5 times the audience's middle age.
  Picking: the rest of a list after a cut point ("never end a clip on a joke, a question, or a cliffhanger") no
  longer reads as wanted; "never pick intros or lead with small talk" refuses both; "get to the action in 10
  seconds or less" is no clip length. Post text: "never skip the emoji" asks for emoji; "my titles aren't getting
  clicks so make them questions" asks for questions (a "no" reaches only its own instruction and the last eight
  words); "text in all caps on my videos" and "only the first letter in capital letters" are no title rules;
  "hashtags from other creators" is which and "hashtags that much" is fewer; "Why I quit Instagram" keeps
  #instagram. Chat: two skills whose names may not be shown ("Post titles for TikTok") no longer share one key, so a
  later import cannot replace an earlier one, and they are still found by their names; the captions playbook's
  phrase words no longer pull "make it work on YouTube" to captions; "buttons" leads to captions only beside what
  they cover, never in "which share button do I press?".
- **Fourth check** (4 checkers, a skeptic per claim; 14 confirmed, all fixed with tests; most were sentences the
  third check's fixes read wrongly). Lessons: a gap inside every video was still mostly missed when videos held one
  to three reaction clips, so where at least 3 videos have clips on both sides the gap is now measured inside each
  of them (found in 100 of 100 runs either way); the error is read from the values before the outlier cap (a few
  volatile videos made a lesson in 16% of runs, now 2%); an import of last month's counts made a 48-hour lesson
  disappear, so counts are compared around the reading age nearest 48 hours that 12 clips share. On pure noise 2-4%
  of runs make a lesson; 20 points on 30 videos is found in 94 of 100. Picking: "skip the small talk or just give
  me the reactions" wants the reactions; "my clips should be done in 30 seconds or less", "no longer then 60
  seconds" and "30 sec max" are longest lengths; after a cut point only a bare list goes with it ("don't end clips
  on a question, funny moments and reactions work best" wants both). Post text: a "no" again reaches back through
  its whole instruction (the eight-word limit lost "I don't want you to ever put any of those hashtags"), "so
  many" goes on, "titles aren't supposed to have emojis" refuses; "no hashtags from tomorrow" and "from the
  description" are refusals, not which hashtags; "Titles, lower case on all my clips" and "only the first letter
  capitalized not all caps" are title rules; "Why I left TikTok for YouTube" keeps both platforms. Chat: "where is
  the captions button?" goes to the app guide; "the side buttons hide my text" gets the captions playbook in edits
  too; editing a skill keeps the refused name it is found by.
- **Fifth check** (4 checkers on the fourth check's own changes, a skeptic per claim; 8 confirmed, all fixed with
  tests that fail on the fourth check's code). Lessons: with three or four long streams beside many one-clip videos
  the gap was taken inside the streams alone and the clear gap was found in 22 and 51 of 100 runs; it is now taken
  inside videos only when at least 5 of them hold at least half of each side's clips (94 and 95 of 100, noise 2-3%);
  a few newer clips read at two days hid 40 clips read on day 3, so the view-count band is now the one nearest 48
  hours that holds at least half as many clips as the fullest. Picking: "clips min 30 sec max 60 sec" became a
  30-second cap (each bound now keeps its own number); "dont pick clips that are just banter or just intros" again
  refuses both. Post text: in a run-on sentence an early "dont worry" or "not sure" refused what came after ("just
  make sure there are emojis"): "just" with a new instruction, "please" and "honestly" start a new one, and "not
  sure", "no idea", "don't care", "don't mind" refuse nothing; "dont reuse hashtags from my last video" removed every
  hashtag and is again about which ones. Chat: "is there a button to hide the captions?" got the captions playbook
  instead of the app guide, and "where are the tiktok buttons on the screen?" lost it; both are back as before.
- **Decisions:** the Brain's effect on a score is small and bounded on purpose; only the owner's own words can ask
  for small talk, ad reads or swearing; an owner's sentence about an editing subject is not a picking rule; the
  shortest clip stays a soft limit (a tight moment may run to 75% of it); clips cut from a live stream follow the
  general post text rules but not one kept for a single video (`autopilot/live.py` was left to the live thread).
- **Not verified:** a real model's answers with the larger brief; Landry's Mac; real streams; lessons on real
  posted results (tested with recorded stand-in results only).
- **Checks:** on e932640, `pytest -m "not slow"` 3105 passed, 2 skipped (27 min) and `pytest -m slow` 31 passed,
  1 skipped (21 min), each alone on the machine; earlier the same on b523866 (3084 passed) and cb646fd (3050
  passed). `npm run build` reproduces the committed `frontend/dist` (rebuilt after the release line came in; no
  frontend file changed since). The review checks' 271 owner sentences read as meant (75 about picking, 41 about
  lengths, 155 about post text), and the fifth check's 18 new test cases fail on the fourth check's code.
  Lesson simulations: noise alone makes a lesson in 0.5-3% of runs (200 runs each), real gaps are found in 94-100
  of 100.

## Live clips: better moments, split view, split between channels, Stop clipping — 2026-11-18 (Claude Code)

Landry wrote: "Improve the live cliping so it finds better moments, fix the fraiming of what it shows and it should be
able to split veiw it like face cam one half and gamplay or other thing in the other half if needed, be able to choose
what live stream clips go to what channle, and be able to split the clips between channles, make it prioritze quality
over quanity, make it so you can have it stop clipping the stream at any time but it will still upload the scheduled
clips". Branch `claude/project-thread-82eyed` (PR #57) from the release line, with the channel picker branch
(`claude/project-thread-rxehvi`, PR #58) merged in, because "split between channels" builds on it. **Not released.**

- **Quality over quantity** (`autopilot/live_pick.py`, `live.detect`). A live moment's score is the Clip Score
  estimate plus how lively it sounds (-2 to +8: louder than the stream usually is, pitch, emphasis, laughter, read
  from each minute's kept 16 kHz sound for the four strongest candidates). Three levels per stream: *Only the best
  moments* (default: 6 minutes of listening first, about 3 clips an hour, starts 3 minutes apart, 5 points above the
  minimum, above the stream's own 85% mark, which rises with every clip made in the last hour, and a wait of up to 2
  minutes for a better moment), *Balanced* (6 an hour, 2 minutes apart, the 60% mark) and *Every good moment* (the
  old behaviour). A standout (15 points above the bar) may ignore the gap and be one clip over the hour. The reason
  nothing is made is written to the stream's card (`info.live_note`). `post_live` keeps the same floor and
  `live_pick.total_cap`. On a stand-in half hour the old picker made 26 clips; the new default keeps 3, all in
  the strongest quarter and the strongest among them.
- **Framing and split view** (`pipeline/reframe.find_cam`, `split_layout`, `render`, `captions`). The old framing
  followed the only face it found, so a stream with a corner face cam was parked on that corner. The cam's rectangle
  is now found (steady edges, still picture against moving picture, a small steady face) and the clip shows the cam
  across the top 30-42% and the rest of the picture below, captions on the line between. Layouts `auto` (split when
  a cam is found) and `split` (whenever a small face is found) exist per clip and per live stream, not in Settings;
  without a cam the clip uses the Settings layout. Stream choice: when there is a face cam (default), always, never.
- **Split between channels** (`submissions.clip_turn`, `scheduler.candidates`). `source_submissions.settings.split =
  "turns"` (absent means every channel gets every clip). Each clip gets one planned post: the channel that already
  holds a post of this clip (any status), else the usable channel with the fewest of this source's clips, the
  owner's ticking order on a tie. The agreement text and the saved consent name the choice. Videos have it too.
- **Stop clipping** (`intake.action("stop_clipping")`, `live._clip_minute`, `post_live`, `_close_stopped`). Stops
  the recorder, skips the picker, and closes the stream without the full-recording search (or between two renders
  when that had begun: nothing half-made is kept, and a replacement cut never supersedes the live clip). It never
  sets `intake.canceled`, never touches clip jobs, approvals or planned posts, and Try again does not take it back.
- **Screens.** Live streams form: How picky, Split view; with two channels ticked, how the clips are shared; a
  **Stop clipping** button with a dialog that says what stays. Settings → Advanced → Autopilot details: the two
  defaults. Clip editor → Layout: Split view, Split if face cam.
- **Stored data.** Minute sound files (`live/<minute>.wav`) live for the rolling window and are removed when the
  recording is finished; `cam.json` in the project's folder holds where the face cam sits. Privacy page updated.
- **Checks:** see the test log in `docs/IMPLEMENTATION_STATUS.md`. **Not verified (needs Landry's Mac):** real
  streams and real face cams (the tests draw their own), real uploads to two channels, the screens in the Mac window.

**Later the same day, three more messages from Landry, in the same pull request:**

- *"fix the fraiming for clips esspecially live stream clips i want to be able to see the full gamplay and face cam
  like a split veiw or how other apps have it"* and *"make sure the clips fraiming is fixed and you can see the
  gameplay and face cam"*. **Split view now keeps the whole picture** (`reframe.split_panels`, `render._split_whole`):
  the face cam across the top (28-36% of the height), a strip for the headline and the captions, then the whole
  source picture at full width over a blurred, darkened fill. The earlier look (the picture's middle filling
  everything under the cam) stays as *Zoomed in*. **Split view is the default for every clip with a face cam**, not
  only live clips: `render.cam_layout` turns a layout that nobody chose into `auto`, and `render.layout_chosen` says
  who chose (a clip edit, the video's own option, a blueprint, or a guidance decision above the Settings level).
  New Settings (Defaults): `split_view` (`auto` | `off`) and `split_game` (`whole` | `zoom`); the clip editor has
  *Under the face cam* for one clip (`edit.split_game`). `render_info` gains `layout_asked` and `split_game`. A
  stream whose split view is *off* stores `split_view: "off"` in its project options.
- *"make it so the clips arent so short and they are actually longer and more engaging"*. Measured first: on a
  stand-in stream of minute-long stories a live clip was only the strongest 12 to 25 seconds of a story, and longer
  length settings moved that by a few seconds only, because a moment is found as its strongest sentences and sits
  near the shortest length allowed. **Live clips now keep the build-up and the ending** (`live_pick.fuller`,
  `live_pick.ranked`, `live.detect`): fuller versions of each moment are analysed (never across a transition
  phrase, a topic boundary or more than three seconds of silence, never over `max_duration`), the best few get the
  full live rating, and the version with the best "live score minus 0.15 per second short of `target_duration`"
  is clipped. A fuller version under the stream's floor leaves the moment as found; one that overlaps a clip
  already made is not considered. The reasons say *Kept the build-up and the ending: 79 s instead of 45 s*. On the
  stand-in the three best clips went from 12-17 s to 35-40 s with today's lengths and to 35-73 s at 25/45/90.
  The clip length defaults themselves (25/45/90) and ordinary clips are the thread "Make ClipForge AI smarter in
  chat" (branch `claude/project-thread-dwz7vo`); live reads the same Settings and has no lengths of its own.
- The release line with the merged channel picker (PR #58, 3bb861f) is merged in.

**Independent review (three reviewers, Nov 19) and its fixes.** 18 findings, none high; all fixed except one known
limit:

- *Live picker.* The hold-back waited for the strongest moment, but the next minute's search could cut the same
  speech differently and the moment was lost while the weaker one was clipped: the picker now remembers up to four
  strong moments between minutes, the waited-for one first (`live_pick.keep`, `Session.held` in `state.json`), and
  rates them again. Before six minutes of the stream were rated there is no standout (it used to be floor + 15, so
  the hour's clips could be spent side by side in the first minutes). A fuller version may share no more of a clip's
  footage than the moment itself (it was measured against its own, longer length). Stop clipping pressed during a
  minute's search makes no clip, and a re-run of `post_live` after Stop clipping keeps a better cut that had already
  taken a live clip's place (it used to drop it too, leaving the moment with no clip).
- *Split between channels.* Ties are broken by the clips over every take-turns request before the ticking order
  (inputs with one clip all went to the first channel); a clip planned again after its post was canceled counts for
  its channel; a clip uploaded by hand to a chosen channel stays there and counts (`submissions._turns`,
  `_turns_overall`). Outside this branch's own code: a replacement approved under a video's upload request now takes
  the weaker post's slot (`scheduler.auto_approve` calls `_take_slot`; the channel-picker entry listed this as a
  known limit). A link added in Live streams that is a recorded video no longer shows stream choices, the videos list
  says *taking turns*. Known limit: a clip waits for its own channel when that channel's planning days are full
  (only with a daily limit set).
- *Split view.* A clip that was rendered keeps whether it looked for a face cam (`render.cam_layout(..., rendered)`),
  so a caption fix no longer turns an older clip into a split view and Settings → Split view → Off changes only new
  clips; the editor shows what a re-render gives. Framing chosen by hand without a layout gives one picture on plans
  and manual clips alike, and the editor's Layout changes with it. Plans keep their layout without a face cam and
  *Under the face cam* (`Framing.fallback`, `Framing.game`; older plans read Settings as before). Top captions go
  on the line between the pictures. A stream recorded since before the update keeps the Settings layout
  (`split_view: "off"`, as its card says). "Add a video with its transcript" sends a layout only when one was picked.
- Every fix has a test that fails on the code before it (picker 4, Stop clipping 2, channels 4, split view 3 changed).
- *A second look at the fixes* (two reviewers) found six smaller gaps, also fixed with tests: a clip's channel is
  taken first from a post that is planned or out, then from an upload made by hand, then from any earlier post
  (`submissions._bound`), so a clip uploaded by hand to B after its post for A was canceled is never planned on A;
  every count of a take-turns input counts clips, not posts (`_places`); a remembered fuller version follows the
  same overlap rule as a fresh search (else the moment is tried as found); a re-rendered split view keeps its *Under
  the face cam* look like its layout, and the editor shows it (`render_info.split_game`); `render_info` records the
  one-picture layout (`layout_fallback`) that the editor uses when Framing is chosen by hand; the transcript page
  sends a layout with a Framing it picked, so that Framing is not ignored by a split view.

## Choose which channels each post goes to — 2026-11-18 (Claude Code)

Landry wrote "make it so you can choose what clips or stuff goes to what channle or if it goes to all or just a few".
Branch `claude/project-thread-rxehvi` from the release line at 56d2cbd. **Not released.**

- **One picker everywhere** (`frontend/src/components/channelPicker.tsx`): every connected YouTube channel and TikTok
  account by name and picture, a tick box each, and **All** for a platform with two or more. An account that needs
  Reconnect is shown but can't be ticked, with the reason. **Accounts → Tick for new posts** decides which accounts
  start ticked (stored as `social_connections.info.post_by_default`; without a choice, the default account).
- **Prepare post** (one clip): each platform panel lists its accounts; one upload per ticked account, one after
  another, and a refusal for one never stops the others. An account that already has the clip says so before you
  confirm. TikTok offers Direct Post, a privacy choice and interactions only when every ticked account allows them.
- **Post selected…** on a video's page (`postSelected.tsx`): several clips to the ticked YouTube channels in one go,
  each with its saved post text. A clip a channel already has, or is still uploading, is left out unless you tick
  *Post them there again*. TikTok stays on Prepare post (its rules need a check of every post).
- **Missions → Submitted videos and Live streams**: tick the YouTube channels for each video or stream. The request
  saves them as `source_submissions.settings.connections = {connection_id: channel ID}` in your order (max 20). All
  is saved as the channels connected at that moment, so a channel connected later is never included. A request
  without that key is from before this change and means the default channel only, with all its old checks.
- **Autopilot follows the choice** (`autopilot/targets.py`, scheduler, submissions, publisher, rights, bulk review):
  one planned post per chosen channel (`scheduled_publications.connection_id`), each with its own approval (the hash
  now includes the connection for a bound post, and the approval names its account), its own daily limit, slots,
  minimum gap and slot replacement, its own duplicate check, and its own Reconnect notice (`connect:<connection>`):
  a channel that needs Reconnect holds only its own posts, and changing the default never moves a bound post.
  Posts without a chosen account behave exactly as before (default account, platform-wide duplicate check).
- **One-time data step** (`db._migrate_scheduled_accounts`): the 2026-11-04 connections migration wrote the default
  connection on every planned post, and nothing read it. The first start of this version clears it once, so those
  posts keep going to the default account and their approvals stay valid. Publications keep their account.
- **Also fixed while here:** reconnecting an account no longer wipes what was recorded for it
  (`db.upsert_connection` merges `info`, as `update_connection` did); Home's "Connect YouTube… N planned posts cannot
  go out" counts only the default account's posts; Queue, the post page and bulk approval show each post's own
  account; the *I have permission* statement says "each YouTube channel I chose" when several are ticked.
- **Not built (no way to post these exists yet):** animated shorts and full YouTube videos have no publish path, so
  they have no channel choice. The standing automatic-publishing permission and TikTok keep their own rules: the
  permission covers the default channel only, and TikTok asks for your OK on every post.
- **Second review (two independent reviewers, each finding checked by a skeptic): four confirmed, all fixed, none
  could send a post to a wrong channel.** (1) A post to a chosen channel whose sign-in YouTube refused during the
  upload is held with no job left to try it again; "Needs you" hid its Reconnect notice as soon as the account
  looked connected. The notice now stays until the post is retried (`home._held_for_owner`), the same as for a post
  without a channel. (2) The cooldown after a dynamic replacement was kept per platform and time, so a replacement
  on one channel held the same time on every other channel; it is per account now
  (`scheduler.replacement_blocked`). (3) A TikTok package you post yourself could not be approved on its page while
  TikTok was signed out ("Another account is connected now"): the page named the signed-out account; it now names
  an account only while it is connected. (4) The post page and the approve check used two definitions of "the
  account of a post without a channel". There is one now (`autopilot/targets.py`): the post follows the default
  account until its upload has begun, then it belongs to the account that upload began on (`begun_on`), so an
  upload interrupted by a platform wait finishes where it started with its approval intact, and an upload record
  that never started is cancelled and started fresh on the account the post is approved for (it used to upload to
  the old default). Smaller points from the same review: Post selected never re-sends an upload that is still
  under way or unconfirmed; TikTok "How to post" returns to Post directly when the account without Direct Post is
  unticked; a TikTok inbox draft already sent is noted before sending it again; a video's status names the one
  chosen channel that is held; the post page retries reading the accounts.
- **Known limits, unchanged:** a platform's "wait" or daily upload limit still holds the posts of all channels of
  that platform until it passes (`platform_limits` is per platform). With "Make & upload" and dynamic replacement,
  a replaced post and its replacement can both stay approved (it was so before this change, with one channel too).
- **Checks:** the cloud session's fast suite on d9cb7c9 (2,743 passed, 2 skipped; `test_an_nvenc_encode_waits_while_the_gpu_is_transcribing`, a 2.5-second timing test in code this change does
  not touch, failed once at the start of the run and passed 3 of 3 times alone); 23 new tests in
  `tests/test_post_to_channels.py`; `npm run build` reproduces the committed `frontend/dist`; a real-app browser
  check against a throwaway app with three fake YouTube channels and one TikTok account (16 of 16 steps: one clip
  to two channels, three clips to two channels with the repeat left out, each channel got each clip exactly once,
  the channel that needs Reconnect can't be ticked, Missions sends the ticked channels, no page errors). GitHub on
  6d51ff0 (run 44320764673): fast suite, slow suite and the Native Mac desktop app build all passed. After the
  second review's fixes: 31 tests in `tests/test_post_to_channels.py` (8 new; 6 of them fail on the code before the
  fixes), the 50 test files that touch the changed modules (880 passed), `tsc --noEmit`, `npm run build`, and the
  browser check extended to 27 steps (TikTok mode switch, repeats and an upload under way in Post selected, the
  TikTok package approved while signed out). The full suites on the final commit are on the pull request.
- **Not verified:** real YouTube channels or TikTok accounts (fake platforms only); the screens in the Mac window on
  Landry's computer.

## Release 2026.11.16.2: the cloud computer gets its own section in Settings — 2026-11-16 (Claude Code)

Landry asked where the app lets you connect a cloud computer and wrote "i dont see a section with that make sure its
merged and actualy released". It was merged (PR #49, `0716ba4`), released (2026.11.13.2 and 2026.11.16) and installed
on their Mac (2026.11.16, `f3aea38`), but only as one of four buttons in the ComfyUI box on Settings → Pictures, video,
voice, with its address box shown only after choosing it. Landry chose its own section and a release. PR #55
(`fa5e139`) was merged as `77eaa99` (same tree); both downloads are built from fa5e139. Every URL, size, hash and run:
[docs/clipforge/WEBSITE_DEPLOYMENT.md](docs/clipforge/WEBSITE_DEPLOYMENT.md).

- **Settings → Cloud computer** (`#/settings/cloud`, after Pictures, video, voice in the Settings list): what it does,
  what makes pictures and video now, the cost note and **Use a cloud computer**; once chosen, the same address box,
  Save and check, key, RunPod steps and the Pictures / Video clips models as before. `LocalMakers.tsx` takes
  `part="all" | "cloud"` and shares the cloud block, steps, model panels and dialogs between both pages; each page has
  its own component key. While a set-up task runs, the cloud page names that task and shows its progress (a review
  finding: it said "ComfyUI is being set up" during any download).
- **Settings → Pictures, video, voice** keeps the same choice and shows **Faster: a cloud computer** with *Set up a
  cloud computer* while it is not chosen. Messages about the cloud computer say "Settings, Cloud computer"
  (`engines/remote.py`, `makers.py`, `comfy.py`, `engines/__init__.py`); ClipForge AI's `go_to` can open
  `cloud_computer` and `makers_settings`; `router.ts` accepts the tab; a `cloud` icon.
- **Checks:** Native Mac desktop app run 44018676801 on fa5e139 (native build and bundled-app smoke; fast 2,721 passed,
  2 skipped; slow 31 passed, 1 skipped); the cloud session's fast suite on fa5e139 (2,721 passed, 2 skipped); `npm run
  build` reproduces the committed `frontend/dist`; browser checks of both pages (off and on, phone width, switching
  pages, no page errors); three reviewers plus a verifier per finding.
- **Mac:** release `clipforge-mac-2026-11-16-2-fa5e139`, the unchanged DMG from run 44018676801, published by run
  44022165510. **Windows:** `raw/eceeeb1` on `claude/clipforge-downloads` (Windows setup check 44020274850 installed
  2026.11.16 first; record commit `649817e`). **Download page:** `gh-pages` `3166005`.
- **Not verified:** a real RunPod pod (Landry's account; costs money) and the new page in the Mac window on Landry's
  computer.

## Release 2026.11.16: clip live streams while they are live — 2026-11-16 (Claude Code)

Landry wrote "Make sure you release the new changes". Everything merged into the release line since 2026.11.13.2 is in
it: PR #52 (clip live streams while they are live, several at once, with uploads during the stream). PR #53
(`f3aea38`) corrected the texts a fact-check found wrong or missing and added the Mac release notes; it was merged as
`9d0be40` (same tree). Both downloads are built from f3aea38. Every URL, size, hash and run:
[docs/clipforge/WEBSITE_DEPLOYMENT.md](docs/clipforge/WEBSITE_DEPLOYMENT.md).

- **Fact-check before release** (release notes, app texts and legal pages against the code at a187452; each finding
  checked again by a second reviewer): the Live streams page now names the recording limits (Largest source, 4 hours
  or 8 GB by default; the recording stops even if the stream is still live); the Stop recording dialog says the
  full-recording check may swap a live clip nobody approved, and offers "add the link again" only for links the app
  accepts again (channel pages and stream addresses); the Missions header no longer says nothing uploads without a
  review (Make & upload uploads passing clips); the privacy page says a channel link is checked every few minutes until
  it goes live, for up to a day; the Terms say a live recording is kept on cancel and deleted with its project. On the
  download page, live links in Make clips (refused by the app) became Clip a live stream, and two answers name Make &
  upload.
- **Mac:** release `clipforge-mac-2026-11-16-f3aea38`, the unchanged DMG from build and test run 43912561838 (macOS 15:
  native build and bundled-app smoke passed; 2,721 fast tests passed, 2 skipped; 31 slow tests passed, 1 skipped),
  published by run 43921441880. GitHub had no Apple-silicon Mac runner free for the native job's first four tries
  (run 43897847676 twice, run 43909484088 and run 43912561838's first attempt, each cancelled after 15 minutes: "The job
  was not acquired by Runner of type hosted even after multiple attempts"); re-running only that job worked.
- **Windows:** `ClipForge-Windows-Setup.zip` at `raw/26ef3a1` on `claude/clipforge-downloads` (50,216,384 bytes; 872
  app files equal to the Git tree at f3aea38 except the six declared CRLF exports; 77 launcher tests); the setup check
  now installs 2026.11.13.2 (raw/dd6958b) first; Windows setup check run 43898294309 passed; record commit
  `622dfef`.
- **Download page:** `gh-pages` `c68f266`: 2026.11.13.2 moved to All versions; seven changes, what was checked and what
  was not. `index.html`, `privacy.html` and `terms.html` are the app's copies at f3aea38 (live streams).

## Clip live streams while they are live, several at once — 2026-11-16 (Claude Code)

Landry asked: "Make it so I can clip streams while they are live and the auto pilot is able to upload them as a clip
stuff during the live" and "Also, let me be able to clip multiple streams at once". Branch
`claude/project-thread-09o53d` from the release line at cef8add, PR #52 into `claude/project-thread-x72wkd`. No
release. Design: [docs/AUTOPILOT.md](docs/AUTOPILOT.md), *Clip live streams*.

- **Missions → Live streams** (`#/missions/live`, also Make → Clip a live stream): up to 10 links at a time (Twitch or
  Kick channels, YouTube live videos or `youtube.com/@name/live`, public `.m3u8`); each is its own input with its own
  **Make & upload clips** request. RTMP/SRT/RTSP are refused. **Stop recording** finishes from what was recorded and
  keeps the clips and uploads.
- **Uploads during the live:** `submissions.bind_live` binds the request to the recording project while live; every
  upload is still the exact clip file that passed its final checks; after the end `bind_live_recording` binds the
  joined recording (path and SHA-256) before the full-recording analysis. Pace: Minimum gap per YouTube account,
  shared by all streams.
- **Several at once:** Live Monitor runs 3 lanes (`queue.WORKER_LANES`); `post_live` runs on the Deep Clip Analyzer.
  A starting or reconnecting stream reserves the room the streams still recording, and those starting at the same
  moment (`live._starting`), may still write; only a stream found live reserves, after its lookup.
- **One broadcast per input:** 5 minutes' offline grace; a new broadcast id, or (channel pages only) a long gap,
  finishes the recorded one; a stream waiting for disk space remembers no broadcast.
- **Joining** (`live._assemble`, also for live-clip windows): minutes placed by recorded length (`duration`) and cut
  there (`outpoint`); unreadable minutes become gaps; minutes without sound, or with changed sound settings (saved per
  minute as `sound`), get a per-minute PCM sound track encoded once.
- **Queue, all job kinds:** a turn that waits, retries or crashes after Cancel, Stop all jobs or its time limit
  arrived ends canceled, held or timed out (`host._cancel_won`); Stop all never turns your own Cancel into a hold, and
  Cancel after a time limit stays a cancel. The supervisor continues held live turns every 30 s after Resume.
- **Docs:** `docs/AUTOPILOT.md`, README, AGENTS, CLAUDE_HANDOFF; the app's privacy, terms and legal home pages
  (effective Nov 16; the public website copies change only with a release).
- **Tests run:** `tests/test_review_submitted_live.py` (47 tests) and slow `tests/test_review_submitted_live_streams.py`
  (two streams at real speed through the real worker host, recorder, FFmpeg, rendering, checks and a fake YouTube; both
  upload while still live); every rule from five review rounds broken on purpose was caught by a test; on 1c7ef31 the
  fast suite passed (2,721 passed, 2 skipped) and the slow suite passed (31 passed, 1 skipped); `npm run build`
  reproduces `frontend/dist`.
- **Not verified:** real Twitch, Kick and YouTube broadcasts (YouTube cannot be reached from the cloud); CPU Whisper
  on Landry's Mac with 2-3 streams; an encoder whose decode times lag more than its declared reorder depth (the cut at
  each minute could drop a few frames there; not seen with x264).

## Release 2026.11.13.2: pictures and video on a rented cloud computer — 2026-11-14 UTC (Claude Code)

Landry wrote "Make sure the new version is released". Everything merged into the release line since 2026.11.13 is in
it: PR #49 (pictures and video clips made on a rented cloud computer such as a RunPod pod), PR #47 (the legal pages
corrected) and PR #48 (records). PR #50 (`78c0601`) added the Mac release notes and was merged as `81f1718` (same
tree). Both downloads are built from 78c0601. Every URL, size, hash and run:
[docs/clipforge/WEBSITE_DEPLOYMENT.md](docs/clipforge/WEBSITE_DEPLOYMENT.md).

- **Mac:** release `clipforge-mac-2026-11-13-2-78c0601`, the unchanged DMG from build and test run 43550846491
  (macOS 15: native build and bundled-app smoke passed; 2,674 fast tests passed, 2 skipped; 30 slow tests passed, 1
  skipped), published by run 43553368922. The first two build runs failed on code.videolan.org (dav1d's source).
- **Windows:** `ClipForge-Windows-Setup.zip` at `raw/dd6958b` on `claude/clipforge-downloads` (50,159,553 bytes; 868
  app files equal to the Git tree at 78c0601 except the six declared CRLF exports; 77 launcher tests); the setup
  check now installs 2026.11.13 (raw/74c4d43) first; Windows setup check run 43547032569 passed; record commit
  `2a1ab84`.
- **Download page:** `gh-pages` `6e5918b`: 2026.11.13 moved to All versions; three changes, what was checked and what
  was not; the AI question mentions the cloud computer and its cost. `privacy.html` and `terms.html` are the app's
  copies at 78c0601 (the rented cloud computer); the legal home page is unchanged.

## Pictures and video on a rented cloud computer (RunPod) — 2026-11-13 (Claude Code)

Landry asked for a cheap server so pictures and clips are made faster than on his Mac, then "Do step 4" (connect
ClipForge to it). Branch `claude/project-thread-64dck1` from the release line at 64ab85f, PR #49 into
`claude/project-thread-x72wkd`. No release. Guide and design: [docs/clipforge/CLOUD_GPU.md](docs/clipforge/CLOUD_GPU.md).

- **Settings → Pictures, video, voice → A cloud computer** (`engines_comfyui = "remote"`): the pod's address
  (`engines_remote_url`, https only except loopback http, no user name) and an optional key (`engines_remote_key`,
  sealed, `********` in the settings view, sent only to that address as Bearer, or Basic for `name:password`); the
  check (`remote.check`, cached 15 s) explains a pod that is off, starting (502–504, 520–530), terminated (RunPod's
  404), on the wrong port, behind a sign-in or refusing the key; a cost warning while connected; a RunPod guide.
- **Models on the pod:** "Put it on your cloud computer" shows a bash command (`remote.download_command`) for the
  pod's terminal: pinned Hugging Face files into the folders ComfyUI names at `/internal/folder_paths` (or RunPod's
  usual models folder), `.part` + resume, size and SHA-256 checked before the final name, a different file never
  replaced, every value shell-quoted. Download/Remove for the pod are refused with what to do instead.
- **Jobs:** the pod's graphics card picks the model (`remote.machine` into `makers.ranked/fit`); jobs take turns
  (`remote.turn`) instead of this computer's graphics lock; for the pod only, uploads/downloads retry 3 times on
  gateway answers and dropped connections, waiting rides out up to 3 minutes (`comfy.LOST_S`), and `/prompt` is never
  retried. Local ComfyUI is unchanged.
- **Routes:** `POST /api/engines/remote`, `GET /api/engines/remote/command`. Shorts pages say "on your cloud
  computer" (`status()["remote"]`).
- **Legal pages:** privacy section 2 (what the pod keeps), section 3 (ComfyUI row), section 7; terms sections 2, 7
  and 10 mention the rented computer and its cost. Not published to the website.
- **Review fixes:** the address and key are action-only (never `PUT /api/settings`); a new host drops the kept key;
  keys are printable ASCII; `makers.mode()` forgets the cloud registration in the local modes and the command route
  needs cloud mode; a job a restarted pod forgot ends in plain words (`LOST_CHECK_S`); a locked Mac Keychain is a 422
  with its message.
- **Second review fixes:** `POST /api/engines/remote` answers the whole view with the trial (the "I ran it: check
  again" button blanked the page); the shorts door (`makers/local_engines.status`) passes `remote` on; questions to
  the pod (`Comfy._get`) are retried on gateway answers and dropped connections, and a model or node list the pod's
  proxy answered for raises plain words (`model_files`, `missing_nodes`, `models._listed`) instead of reading as
  "not on it yet"; the note names the model that made the file; a job re-reads Settings when its turn comes and
  stops if another ComfyUI was chosen; a new address drops a kept key even when a locked Keychain cannot read it,
  `key_set` counts a kept unreadable key, and an address and key are saved together or not at all (addresses over
  300 characters are refused, never cut); the address is `********` in `GET /api/settings`
  (`config.UNSHOWN_KEYS`), `GET /api/engines` is this computer only, and status words and errors never name the
  address; a key box with only spaces or a too-long key says so; the command dialog drops answers for a closed
  dialog and shows that it is asking; the check script picks the smallest file ComfyUI does not list yet.
  A third, smaller review: a job's history is asked once per look (retries had stretched Stop and `LOST_S`); RunPod's
  404 for a pod stopped since the check reads as the pod being gone (`Comfy._down`), not as missing models or nodes;
  the note's label is worked out inside the job's turn; a kept key also goes when only the port changes.
- **Checks:** `tests/test_remote_engines.py` (51, with a stand-in RunPod proxy; real bash runs of the command; every
  rule broken on purpose once, the later reviews' 28 rules too); a browser run of the cloud panel (Save and check,
  the command dialog, "I ran it: check again", closing while it asks); `scripts/local_engines_check.py --remote` on Linux and Mac (Linux, run 43507318631:
  the command fetched Z-Image's smallest file from Hugging Face and ComfyUI listed it, and a real FLUX.2 klein picture
  was made in cloud mode in 169 s). Fast suite 2,644 passed, 7 skipped.

## Release 2026.11.13: ClipForge AI as a real assistant, planned YouTube videos, animated shorts — 2026-11-13 (Claude Code)

Landry wrote "Release the new version with all the changes and update the website". Everything merged into the
release line since 2026.11.07 is in it: PR #40 (story clips), #36 (animated shorts), #39 (pictures, video clips and
voice-overs made on the computer), #41 (the built-in AI's engine outlives a request's thread; other computers'
addresses are refused), #38 (Make a YouTube video planned with ClipForge AI), #35 (deleting projects), #42 and #43
(clean-up after deleting) and #37 (ClipForge AI as a real assistant with helper agents). The release notes were
fact-checked against the code first; three app texts still described old behaviour, so PR #44 (`863e69e`) fixed
them, dated the privacy page November 13 and wrote the Mac notes, and was merged as `1d455f6` (same tree). Both
downloads are built from 863e69e. Every URL, size, hash and run:
[docs/clipforge/WEBSITE_DEPLOYMENT.md](docs/clipforge/WEBSITE_DEPLOYMENT.md).

- **Mac:** release `clipforge-mac-2026-11-13-863e69e`, the unchanged DMG from build and test run 43410427464 (macOS 15:
  native build and bundled-app smoke passed; 2,623 fast tests passed, 2 skipped; 30 slow tests passed, 1 skipped),
  published by run 43413905735.
- **Windows:** `ClipForge-Windows-Setup.zip` at `raw/74c4d43` on `claude/clipforge-downloads` (50,107,742 bytes; 865
  app files equal to the Git tree at 863e69e except the six declared CRLF exports; 77 launcher tests); the launcher
  pins were rebuilt from the 2026.11.07 launcher, so an earlier unlisted build from 492d254 (`240548b`) is not in the
  release history; Windows setup check run 43410898326 installed 2026.11.07 and then this ZIP over it; record commit
  `8d5a242`.
- **Download page:** `gh-pages` `e97c633`: 2026.11.07 moved to All versions; eleven changes, what was checked and what
  was not; "Three ways to make something" with the animated short; new screenshots of the Studio, Make clips, Make a
  YouTube video and an animated short, taken from the release build; the AI question names the built-in model.
  `privacy.html` is the app's November 13 privacy page. The Terms and legal home page were left as they were.
- **Real-app checks:** conversation check on the built-in model, Basic on Linux and Mac (every must-check passed;
  misses: did not list the projects, said it would ask the Script writer without doing so) and Standard on Linux
  (every check passed); animated shorts on Mac, Windows and Linux; local makers (pins, ComfyUI set up and started,
  the voice spoke, one real FLUX.2 klein picture on Linux CPU); built-in AI (its Linux job passed on the second
  attempt after the small model's picture answer was cut off mid-JSON); FilmCraft.

## A project's own re-stored copies go with it; privacy page: uploads, shorts, makers — 2026-11-13 (Claude Code)

Two follow-ups found after PR #37 merged (3d337c8). Branch `claude/project-thread-gvcf5h` from the release line at
3d337c8. No release.

- **The leftover copy.** ClipForge stores each file once per workspace; when the same bytes are uploaded, added from
  this computer or stored again, the stored copy is handed out again and marked (`assets.reused_at`). Deleting a
  project kept every copy marked after its delete list was shown and within the hour before deleting ("used again
  just now"), because the one it went to may not have recorded it yet. When that was the project's own work (an
  animated short's Make again, its music or whoosh, a link's download or a Find media import for it), nothing named
  the copy once the project was gone, and it stayed for good. Now each hand-out also notes whom it went to, in the
  same database step as the mark (new table `asset_hand_outs`: asset, time, project or upload; `uploads._mark`).
  `project_delete._handed_out` keeps a copy only for a note since the window that names someone who may still need
  it: an upload no project took yet (or still arriving, or whose record is not written yet), another project that
  still exists, or nobody (a mark an older version made). A note for the project itself, a project deleted since or
  an upload a project took lets it go. Notes older than the hour are removed at the next hand-out, and a file's
  notes go with the file (project delete, a short's tidy, an example's delete).
- **Who passes what:** `uploads.store_file(..., project_id=)` and `library.asset(..., project_id=)` take the project
  the work is for (shorts' scene pictures and clips, music and whooshes; smart editing's music and sound effects;
  `link_import.run`; `media_sources.import_one` from an import for a video and from Find media's automatic round);
  `complete`, `_again` and `link_local`/`_hand_out` note their upload id (link_local names it before the row exists).
- **Privacy page** (`docs/legal/privacy.html`): a new "Uploads and files added from this computer" paragraph (each
  upload's record and which project or example took it, how files added from this computer are used where they
  are, when partial uploads go, the hand-out time and notes, which hand-outs keep a file when a project is deleted,
  what stays until the data folder is deleted); a new "Animated shorts and the picture, video and voice makers"
  part (what a short keeps, its list of stored files and tidying, the 120 recorded voices, Hear samples, the Make
  page's remembered choices; ComfyUI set-up and models on disk, `engines/made` and its notes, what a short takes in,
  ComfyUI's input and output folders, the graphics-card label, the two ComfyUI logs, use rules not recorded); new
  rows for the ComfyUI set-up downloads (PyPI, Astral's or GitHub's Python, PyTorch's site, what uv names) and for
  what ComfyUI receives; Hugging Face and GitHub rows extended; what a short's writer sends (standing rules up to 8,
  facts up to 6) and that it is not limited by "AI requests a day"; section 7's delete, delete-everything and new
  Remove bullets. Fixed: the old "unfinished uploads (deleted after 3 days if not finished)" (only the partial bytes
  go, and only when the next upload starts). Not published to the public website (needs Landry's OK).
- **Review:** an independent review (races and logic, every caller, the tests, two privacy fact-checks, each finding
  then checked by a skeptic) found no code bug; it found three test gaps (only the latest note judged, the window
  filter, four call sites not pinned) and thirteen privacy sentences that were wrong or incomplete, all fixed; a
  second fact-check of the corrected page found eight more (Stop only pauses an upload and no page cancels one, the
  browser's own upload record, media added to your media only, what stays of an unused file, a typed ComfyUI
  address keeps its copies too, the picture to animate is sent unchanged, what a short keeps about its writer, the
  Settings try uses example words), also fixed; two more rounds on the uploads paragraph alone found nine finer
  points (what pauses an upload and what does not, a file that fails its check, the browser entry, examples' uploads,
  when an example's file stays), also fixed. Each new test was checked against a deliberate breakage of the code it
  pins.
- **Tests:** on ac764a7, the last code change (later commits change only the privacy page and these records):
  fast suite `pytest -m "not slow"` 2623 passed, 2 skipped (1790 s); slow suite `pytest -m slow` 30 passed,
  1 skipped (1376 s); `npm run build` passes with `frontend/dist` unchanged (no frontend change). Each new test
  was checked against a deliberate breakage of the code it pins (only the latest note judged, no window filter,
  a dropped `project_id` at a short's picture, its music, smart editing's effects and Find media's automatic
  round): each was caught. The privacy page's HTML was checked for balanced tags.
- **Not verified:** a real Mac or Windows PC; real ComfyUI, models and the Supertonic voice (stand-ins in tests);
  the uv details on the privacy page were read from a real uv 0.13.7 run on Linux only.
- **Follow-ups (not done here):** an unfinished upload's partial bytes are only cleaned when the next upload starts
  (`uploads.clean_stale` has no start-up or timer call); a short's script and picture-idea requests do not take from
  "AI requests a day" (`makers/writer.py` never calls `brain.allowance`).

## ClipForge AI becomes a real assistant: conversation, actions, helper agents — 2026-11-08 (Claude Code)

Landry asked for a built-in AI to actually talk to like a real AI, and for agents to add that work alongside
it. The old chat caught ordinary sentences with rules ("I want…" became a memory, anything in a video's
chat became a change request), sent each question to the model alone with no conversation, never told the model about
Landry's projects, could never do anything, and without a downloaded model only gave canned answers. Branch
`claude/project-thread-sa113l` from the release line at 95a70e0 (PR #33 merged). No release. Design and numbers:
[docs/clipforge/CLIPFORGE_AI.md](docs/clipforge/CLIPFORGE_AI.md), "The assistant", "Actions", "Helper agents".

- **The conversation engine** (`clipfoundry/brain/assistant.py`, new): one engine for both chats and for the helper
  agents. Each turn sends who ClipForge AI is (`persona()`) and how it works, what it knows right now
  (`app_context()`: the date, the owner's projects newest first, this chat's video in detail, the model, the
  switched-on helpers), the memories and know-how that fit the message, its tools and the conversation so far
  (`history()`), inside budgets sized for the built-in model's 8,192-token context (2,200 / 1,200 / 900 / 5,000
  characters; 3,600 / 1,600 / 1,400 / 12,000 for bigger models). The model answers with one JSON object (`say`, up to
  three tools in `do`, an optional `ask` with up to four quick replies), held to that shape by a JSON schema where the
  provider takes one and read leniently otherwise (`parse_reply`: plain words, fences, other spellings, cut-off
  answers). Looking tools run and the model answers again with their results, at most 4 rounds, the last one without
  tools (`think`). The answer is written in the background and streams into the chat message (`partial_say`, saved
  every 0.25 s); Stop keeps the words so far; an answer has 300 s on this computer and 60 to 240 s online.
- **Actions** (`brain/tools.py`, `brain/toolbox.py`, new): a tool registry with checked arguments (known names only,
  simple types fixed, text cut to its length, choices, ranges and required ones checked) and four risks. Twelve tools:
  `find_projects`, `open_project`, `recall`, `knowhow`, `app_status` and `go_to` look and run at once; `remember`,
  `propose_change` (a video's chat only) and `ask_agent` make something new and run at once; `forget` and
  `rename_project` (change) and `delete_project` (delete) only show what would happen with OK and No, and run when the
  owner presses OK (`chat.decide`), checked again then. A button is answered once, and later turns read what became of
  it. `delete_project` uses the Projects page's safe delete (`studio/project_delete.py`, on
  `claude/project-thread-8i3krg`); without it the tool says deleting from the chat is not possible yet and points to
  the Projects page. Other parts add their own tools with `tools.register`.
- **Helper agents** (`brain/agents.py`, new; table `brain_agents`): eight ready-made helpers (Researcher, Script
  writer, Hook and title writer, Editor, Critic, Sound and music advisor, Thumbnail planner, Growth coach) added with
  one press, or the owner's own (name, icon, job, instructions, tools), 24 at most. They think with ClipForge AI's
  model, are only given looking and making tools and never hand work on. ClipForge AI hands them jobs (`ask_agent`,
  their work shown live in a card inside its answer); the owner talks to one with "@Name …"; `consult()` gives the
  new-video planner a short note from each helper set to help with plans, inside a time budget. The memories a job
  read are recorded as used by `agent`.
- **The chat** (`brain/chat.py`): with a model, every message goes to the assistant except the fast paths: "remember:
  …" (with the colon, no question in it) saves exactly those words, "forget" with the exact words of a memory removes
  it, and in a video's chat a change the editor's rules fully understand is proposed at once. "Remember that …" is a
  turn of the conversation; when a plainly said lasting rule or fact ("From now on, never use red captions.") ends
  without the model saving it, ClipForge keeps the owner's words itself, with Undo. Without a model the old rules
  answer as before and the chat offers to set up the built-in model. Messages up to 4,000 characters (was 500); one
  answer at a time per chat; `route()` lets another part answer some chats (the new-video planner, a draft video's
  chat); `stop()`; `decide()`. With an online model every request counts against the daily AI limit (each round of an
  answer, each round of a helper, each planner note, and the editor's change requests: `brain/allowance.py`, new, rows
  in `ai_usage`); a model on this computer has no daily limit.
- **Every kind of model** (`pipeline/llm.py` `converse()`, `builtin_ai.converse()`): whole conversations for the
  built-in model, Ollama, OpenAI-style servers, Anthropic and NVIDIA; streamed from the built-in model (llama-server's
  server-sent events), Ollama and OpenAI-style servers; a JSON schema where the provider takes one (asked once more
  without it when a server refuses it); `Canceled` when stopped, also while waiting for the GPU; a model on this
  computer waits for the GPU at most the time the answer has left; an error sent in the middle of an answer is said in
  plain words. The built-in engine is never stopped as idle while it answers (`Server.answering(seconds)`); `gpu.py`
  says a wait shorter than a minute in seconds.
- **In the app** (`components/ClipForgeAI.tsx`, `components/AgentsTab.tsx` (new), `pages/Brain.tsx`, `brain.ts`,
  `components/AiHelperSettings.tsx`, `styles.css`): the chat shows the answer as it is written, a line for each step,
  buttons to pages and projects, OK / No cards for changes and deletes, quick replies, a helper's work as its own card,
  Stop, "@" to talk to a helper (a list while you type, an "Ask a helper" row, and the helpers beside the chat in
  Brain → Talk), the model in use, a setup card when there is no model (the built-in model in one press, with progress
  and Cancel) and a tip when the computer can run a better level. Brain → Agents (`#/brain/agents`) adds, edits,
  switches on and off, and removes helpers. `frontend/dist` rebuilt.
- **API:** `POST /api/brain/chats/{id}/stop`; `POST /api/brain/chats/{id}/messages/{mid}/actions/{aid}` `{do}`;
  `GET`/`POST /api/brain/agents`, `PATCH`/`DELETE /api/brain/agents/{id}`; opening a chat also returns the model's
  state and the switched-on helpers.
- **Privacy page** (`docs/legal/privacy.html`): a new "ClipForge AI" part says what its chats, memories, helper agents
  and online request counts keep and until when; "An AI service you choose" says what talking with it sends (and that
  the built-in model sends nothing off the computer, while an Ollama cloud model answers online), and NVIDIA's row
  says the same for NVIDIA. The public website is not updated (that needs Landry's OK).
- **Checks:** `tests/test_clipforge_ai_assistant.py` (63 passed), `tests/test_clipforge_ai_agents.py` (9),
  `tests/test_clipforge_ai_safety.py` (new, 34: memory safety, the grounded check's parts, broken emoji, broken
  tools, one-line outside text, the round budget, plainly said rules), `tests/test_llm_converse.py` (21),
  `tests/test_clipforge_ai_chat.py` (22; its two model tests now go through the conversation engine),
  `tests/test_clipforge_ai_knowhow.py` (12; its model test too), `tests/test_clipforge_ai_brain.py` (40;
  memories in other languages), `tests/test_builtin_ai.py` (24; new: a conversation streamed piece by piece,
  Stop and the time limit, never stopped as idle while it answers, the background load under the GPU lock),
  `tests/test_assistant_check.py` (new, 5), `tests/test_video_setup_flow.py` (41),
  `tests/test_studio_project_delete.py` (32) and `tests/test_studio_media_sources.py` (16), with a scripted fake
  model (`tests/fake_model.py`, new) and the stand-in engine (`tests/fake_llama_server.py`, which now streams),
  all on the code merged with the release line (PRs #40, #36, #39, #41, #38, #35 and #42); `python -m pytest -q
  -m "not slow"`: 2597 passed, 2 skipped; `python -m pytest -q -m slow`: 30 passed, 1 skipped; pyflakes on the
  changed files: no warning in the changed code but one import made for what it sets up (`brain/tools.py` loads
  the toolbox); in the tests only pytest fixtures that are imported and named as arguments; `cd frontend && npm
  run build`; a click-through in a real browser at desktop and phone widths (the chat, Brain → Agents, the setup
  card, the OK buttons, Stop, remembering with Undo, Forget on a memory gone meanwhile, deleting a video from
  its chat with the real safe delete) against a throwaway app with a fake streaming model (outside the repo): no
  failed steps; `python scripts/assistant_check.py --fake` passes.
- **Safety and robustness pass** (after an independent review of the first version found 13 problems, each
  reproduced before it was fixed): `remember` saves at once only the owner's own words from this message (60% of
  its meaningful words in the message, `toolbox.grounded`); words from a transcript, a name, a result or a helper
  become a "Remember “…”?" card (`save_memory`, a change tool the model is never offered, `tools.AskFirst`), and a
  helper is told to suggest it instead; it never changes a memory the owner already has (switched off, kept for
  one video or platform, or a guess: the step says so and links to Brain → Memory), so Undo only ever forgets what
  that answer added, and a merged memory's video or platform follows its scope (`memories.remember`). Names, clip
  titles, notes and transcript words are one line in what the model reads (`tools.one_line`; link import stores
  titles as one line), so a downloaded title cannot fake a rule. A tool that breaks fails only its own step and the
  model goes on; "Nothing was changed." is said only when true. Half of an emoji anywhere in an answer is left out
  (`tools.whole`, `clean`). A long answer before a follow-up stays in the conversation, shortened (start and end),
  and a helper reads as much of it as ClipForge AI. One round reads at most 21,000 characters on the built-in model
  or Ollama (earlier results shortened first) and an overflowing model is said in plain words. The wait for the GPU
  and loading the built-in model count in the answer's time; the planner's helper notes are skipped while the
  built-in model is not loaded (`Server.warm` starts it in the background; on Linux the engine is now started from
  one long-lived thread, because it was stopped with the thread that started it). What a helper saves shows with its
  Undo chip; a finished helper's work shows once. On the page: a press can never send or act twice, the focus stays
  in place after OK, Undo, Apply, Clear and Send, reading slows when the page is hidden and stops when the chat is
  gone, a screen reader hears new messages (not the whole chat on opening) and download steps (not every megabyte),
  and a request that never reached ClipForge says so in plain words.
- **Second review pass** (a second independent review of the fixes found 15 more problems, each reproduced before
  it was fixed and each with a test): the shortened earlier answer before a follow-up now really reaches the model
  (`llm._turns` puts a short "(Earlier in this chat:)" turn on the owner's side before it instead of dropping it);
  memories in other languages are compared by their own words, so a Russian rule is no longer the "twin" of a
  Russian fact (`memories._norm` is Unicode-aware; older memories are matched by their old form too and Tidy updates
  them); the "Remember …?" card shows a long memory whole, since OK keeps exactly the words it shows; `grounded`
  also compares each part of a memory with the part of the owner's message it comes from: turned-around words (no,
  never, don't, avoid, less …), numbers and limiting words (only, except, more …) must match, so "No zooms" is not
  saved at once for "I love the zooms you added"; a reply to ClipForge AI's question ("Only this one") counts the
  message it was about as the owner's words (`assistant.owner_words`); the rule safety net keeps only orders on one
  line ("Never use …", not "Never had this problem before …") and waits when the model asked a question or a helper
  kept a memory; a helper's memory keeps its line and Undo chip when the helper's next round fails; the background
  load of the built-in model holds the graphics card (never next to a transcription); a model on this computer is
  not asked with less than a useful part of the time left (`builtin_ai.answer_floor`), and a slow one is said to be
  slow ("The model took longer than 300 seconds (40 of them waiting for the graphics card)."), not unreachable; the
  daily limit counts only the editor's requests that went online, a model on this computer no longer lets ClipForge
  AI's online requests block the editor (it keeps the editor's own limit, as always), and the editor counts under
  the same lock as ClipForge AI (`allowance.counted`); "on this computer" now covers every loopback address
  (127.x.x.x, ::1, 0.0.0.0) and an Ollama cloud model (`…-cloud`) counts as online and is disclosed as sent over the
  internet (one check, `llm.is_local`, for the chat, the editor and the AI editor); an answer nested deeper than any
  real one is read as words instead of failing; the chat page keeps reading an answer after a passing error (only a
  deleted chat stops it). Settings → Advanced calls the limit "AI requests a day" and says what it covers.
- **Small models** (after the first real-model run): the round instructions ask the model to answer from the
  results (name the projects), a helper is told to do the job in the same answer ("never only say that you will do
  it"), ClipForge AI is told to always hand a job to a helper when the owner asks for that helper's work and is
  shown one of the owner's own helpers in an example.
- **The real model** (`scripts/assistant_check.py`, new, run by the new GitHub workflow `assistant-check.yml`): a
  conversation with the real built-in model through the app's own chat, in a fresh data folder (a greeting, the
  projects, a memory, the owner's name four turns later, a rule, a delete that must wait for OK, a helper by "@" and
  by hand-off, `consult`). Hard checks fail the run: nothing crashes, every answer finishes within the app's own time
  limit and is neither empty nor raw JSON, nothing is deleted and no button runs without the OK, "remember that …" and
  "From now on, never use red captions." are kept (by the model's `remember` tool, or by ClipForge when the model
  forgot), an "@Name" message is answered by that helper, and `consult` gives one note. How good the answers are is
  reported without failing it (including whether the model saved the memories itself). `--fake` checks the script
  itself with a stand-in model. The first run (on d02bb25, run 42478720316) passed on Linux and on a Mac (Basic
  level, Qwen3-VL 2B: 11 turns in 307 s, 3.2 tokens a second, answers in 14 to 68 s); the small model did not name
  the projects it found, did not save the red-captions rule itself, did not hand the title job to the Script
  writer, and the Script writer said it was ready instead of writing: the "Small models" changes above answer that.
  The run on the merged version (56aae46, run 42745705173) passed on Linux (11 turns in 110 s, 8.8 tokens a second,
  answers in 6 to 21 s) and on a Mac (359 s, 2.8 tokens a second, answers in 19 to 61 s): every must-check held. The
  Basic model again did not name the projects it found (the step's buttons showed them), did not save the two
  memories itself (ClipForge kept the owner's words), did not hand the title job to the Script writer, and the Script
  writer said it would write instead of writing; its three rounds that were each only "Here are your projects:"
  showed that line three times, which `Outcome.text` now shows once. The run on the final version is linked in PR #37.
- **Last review pass** (an independent review of the stutter fix, the check workflow, the privacy page and the docs;
  each finding reproduced, each fix with a test): an answer's rounds stay in the order they were said, and a round that
  says earlier rounds again and goes on replaces them at the end, so the answer's last words come last (a "Let me check
  …" said before the answer no longer ends up after it); a short answer that only starts like an earlier round ("No."
  after "Now let me check …", "Step 1" after "Step 10") is kept, and one of fewer than three words counts as said again
  only where its words end a phrase ("Got it." in "Got it, I'll remember that."); words are compared with their marks
  (Thai, Hindi); a round that only repeats the start of several earlier rounds in a row adds nothing, and the round
  being written shows only once it has a new word, so a repeated lead-in (one round's or several rounds') or a lone "**"
  does not flash up. With NVIDIA, ClipForge AI's instructions (memories, project details, helpers' instructions) lose
  web addresses that start with http://, https:// or www. and email addresses, like the conversation, and a conversation
  longer than NVIDIA's input limit loses its oldest messages first (the limit cut its end, where the newest message is).
  `assistant-check.yml` can run on both machines, only Linux or only the Mac (`machines`), gives an answer 900 s on
  GitHub's machines when there is no graphics chip for the model (the Mac, and Linux at the Standard level), and a run
  by hand never cancels a push's run, nor one with other choices. The daily-limit messages now point to where the limit
  is ("Settings → Advanced, “AI requests a day”"; they said Settings → ClipForge AI). The privacy page now matches the
  code: what the chats, memories (guesses expire after 60 days; Tidy), helpers, the change requests made in a video's
  chat (kept until the data folder is deleted; Clear this chat leaves them) and the request records keep; which features
  send text to the AI helper you choose (scoring and titling, the editor, smart editing, FilmCraft, a short's script,
  Full stories, ClipForge AI and its helpers; never files, pictures or sound) and what a conversation sends (standing
  rules, the date and time, the chat's video, part labels that are often file names); and, for NVIDIA, that web
  addresses starting with http://, https:// or www. and email addresses go from everything, the size limit cuts each
  request's words but not its instructions, and its one repair request is not counted again against "AI requests a day".
  The run on the merged version (a1d489d, run 42777938926) passed on Linux and on a Mac and showed the projects' lead-in
  once ("Let me look. Here are your projects:"), but on Linux the Basic model answered "Delete the project Old gear
  review" with "… It's been removed." although the delete could not be offered (nothing was deleted). A change or delete
  that cannot be offered is now a failed step the owner sees ("Could not delete Old talk", with the reason), like any
  other tool that fails; the note the model reads for a waiting button says that nothing is done yet; and the check
  reports words that say a project was deleted or removed, also beside a waiting button.
- **A last independent read of these fixes** (a code reader and a privacy-page reader; 11 points, each checked
  here, each fix with a test that failed first): with NVIDIA, a newest message that did not fit with the note "Earlier
  messages were left out" lost its whole text (NVIDIA cuts at the last whole line, which was the note's): it now
  goes alone, and one too long on its own keeps its start and its end (`llm._start_and_end`). A short answer is no
  longer taken for a repeat where a hyphen, an apostrophe or a point or comma inside a number follows the same
  words ("No." after "No-one has …", "1." after "1,000 views", "Step 1" after "Step 1.5"); only a stop, or
  no more words, ends a phrase (`_ends_phrase`). Emoji drawn with a look selector (❤️, ⚠️, 🎞️) count as having no
  words, like 📂; rounds are compared decomposed and without case, so an accent written after its letter (as macOS
  writes file names) or a Greek capital sigma no longer makes a repeated lead-in flash up while it is written. The
  same failed step asked for twice in one answer shows once (`_add_step`). The check's delete detector reads each
  sentence on its own ("It's been removed. Let me know if …" is a claim), knows "successfully deleted", and no longer
  takes "Tap OK to delete it. Its clips are removed too." for one (30 phrasings checked). The privacy page: a change
  asked for in a chat is kept in the words ClipForge AI wrote from what was said (not always the words as typed);
  downloading the built-in model contacts GitHub (llama.cpp) and Hugging Face (its files, no sign-in token sent),
  now listed; clip making also sends a one-line summary of the kinds of clips the owner keeps; and NVIDIA's row says
  exactly which addresses go (those starting with http://, https:// or www., and email addresses; "youtube.com/@name"
  is sent as written). Left as it is, and written down: a lead-in that each round goes on from with different words
  ("Here are your projects: Hike day …", then "Here are your projects: Lake day …") is shown each time; the real
  model's repeated rounds were each only the lead-in, which is handled, and cutting words from inside a round's
  answer risks losing what it said.
- **The real-model run on the version merged with PR #41** (5322fd0, run 42818369465): on Linux every must-check
  passed and the projects' lead-in showed once, but the Basic model, asked again after the delete could not be
  offered, said "I've deleted the project 'Old gear review' for you. It's gone now." (nothing was deleted; the check
  reported it). A change or delete that is not offered (it cannot be offered at all, or it is shown blocked) is no
  longer a reason to ask the model again: the owner sees what the model wrote before it knew and the failed step or
  the button that cannot be pressed, each with its reason; beside a tool the model does read, it reads that the change
  was not done (`assistant._offer`). `scripts/assistant_check.py` counts such a failed step as the answer's words and
  as the polite no. The run on that fix (3c8fe24, run 42820370845) passed every must-check on Linux and on the Mac,
  and the model claimed no delete on either machine. An independent review of this fix then found that the next turn
  could not know such a change was not done (an answer that was only the failed step was not in the conversation at
  all, and one with words kept only the model's promise): `history` now adds "[Could not delete Old talk, so nothing
  was done: …]" after the answer's words (its steps are marked `not_offered`). `scripts/assistant_check.py` counts
  only such steps as words (a change with wrong arguments goes back to the model, which must answer), wants the failed
  delete of the right project (`delete_verdict`) and shows the step in the job summary instead of "(empty)";
  `tests/test_assistant_check.py` (new) tries its judgements on answers written by hand.
- **Merged with PR #38, Make a YouTube video** (the release line at b5707fa): the new-video planner asks ClipForge
  AI's model, and counted its requests its own way (chat messages marked as sent online, plus every AI change request,
  also one to a model on this computer) and sent the owner to Settings → ClipForge AI for the limit. It now takes each
  planning request from the same daily allowance as the chat, its helpers, their notes and the editor
  (`allowance.take`, task `video_plan`, just before the request is sent, in a draft's chat and in the build job:
  `video_setup._take`; `video_setup.limit_reached` asks `allowance.reached`), so together they never send more than
  "AI requests a day" allows, and the message names Settings → Advanced, "AI requests a day". NVIDIA's agreement note
  (Settings → Integrations) now names conversations with ClipForge AI and its helper agents too, not only planning,
  and the privacy page's "An AI service you choose" and NVIDIA rows describe both (planning leaves memories out for
  NVIDIA; the conversation does not). New test: `test_planning_and_clipforge_ai_share_one_daily_allowance` in
  `tests/test_video_setup_flow.py` (it failed on the planner's old counting).
- **Merged with PR #35, deleting projects** (the release line at bc7250f): `delete_project` uses its safe delete
  (`studio/project_delete.py`) itself; the stand-in answer for a version without it is gone. The card shows the plan's
  sentences and keeps the moment the plan was judged (`as_of`), which OK sends back, so a file the card said stays
  because the owner added it again still stays however long the card waited; `as_of` is an internal argument
  (`"internal": True` in a tool's schema: `tools.signature` hides it from the model, `tools.check_args` keeps it only
  from a button's own saved arguments, `button=True` in `chat.decide`, and `tools.same_button` makes two cards that
  differ only there one card). Work still stopping keeps the card for another press (`TryAgain`). A rename or delete
  card whose project was deleted since says "That project is not there any more: it was deleted." instead of naming
  the project's id. A memory "for this video" that an
  answer saves after its video was deleted is not kept (`toolbox._keep`). The chat page drops a project deleted from
  the chat from its pins, as the Projects page does. The privacy page's ClipForge AI part says a chat, a memory kept
  for one project and a video's change requests go when that project is deleted. PR #35's
  `test_a_memory_saved_again_for_another_project_stays` expected a memory saved again for another project to keep
  the first project's id in `project_id`; since this branch's review fixes, `project_id` follows the scope, so the test
  now checks that and also an older version's memory (its comment in `project_delete.py` says so). New tests:
  `test_the_chat_deletes_with_the_safe_delete_of_the_projects_page` (the real module: the card's words, its `as_of`,
  OK deletes the video with its chat and its own memories, a memory for every video stays),
  `test_nothing_is_kept_for_a_video_deleted_while_the_answer_was_written`; the two tests that used a version without
  the safe delete now use a project deleted while it was offered. Each failed on the code before this merge.
- **An independent review of that merge** (three reviewers, one for the delete path, one for what is kept and the
  privacy page, one for the tests and docs, and a separate check of each finding that tried to refute it) found three
  real problems and three small ones. Each fix has a test that failed before it:
  - A card could delete a file it said stays. A card is judged when it is shown, and one answer can show two delete
    cards for videos that share a file: both say the file stays because the other video uses it, and OK on both
    deleted it. `project_delete.plan()` now also lists what goes beyond the project itself (`removes`: media files,
    the copy of the video it was made from, planned posts); the card keeps it as a second internal argument, and
    `project_delete.delete(..., removes=)` deletes no more than that, or nothing (`DeleteError` 409, code `changed`:
    "What deleting it removes has changed since this was shown: it would now also remove … Nothing was deleted."),
    checked before any work is stopped and again on what is deleted once it has stopped. The card then fails and says
    to ask again; a new card lists what goes now. A post planned after the card was shown is caught the same way. The
    project's own clips, versions, notes and chat are the project and go with it whatever their number. The Projects
    page does not send `removes` and works as before.
  - A card that Autopilot got in the way of kept its OK, and a later press deleted what Autopilot made meanwhile (a
    clip, a planned post), which no card the owner saw had listed. A `blocked` answer now ends the card with what it
    waits for; asking again later shows a card with what goes then.
  - Deleting a video gave the day's online AI requests back: the editor's change requests counted from their
    `edit_requests` rows, which the delete removes. Each one now also writes its own `ai_usage` row (task
    `edit_request`, `allowance.editor_request`), which stays; one sent before this counts from its `edit_requests` row
    while that is there, never twice. The privacy page says the record stays after its video is deleted.
  - Small ones: a memory deleted while an answer was written got a use record left over for nothing
    (`memories.record_use` now counts and records in one transaction, only for a memory that is there); a clips
    project and a YouTube video with the same name could not be told apart (`toolbox.find` takes the `kind` the model
    gives, and without it asks which one, naming each one's kind); and new tests show a model can neither read nor
    give a card's internal arguments.
  - New tests: in `tests/test_clipforge_ai_assistant.py`,
    `test_two_delete_cards_for_videos_that_share_a_file_never_remove_more_than_they_listed`,
    `test_a_delete_card_autopilot_got_in_the_way_of_ends_and_a_new_card_says_what_goes_then`,
    `test_a_delete_card_never_cancels_a_post_planned_after_it_was_shown`,
    `test_a_clips_project_and_a_video_with_the_same_name_are_told_apart_by_their_kind`,
    `test_a_buttons_own_arguments_never_come_from_a_model` and
    `test_deleting_a_video_keeps_the_days_count_of_its_change_requests`; in `tests/test_studio_project_delete.py`,
    `test_a_delete_given_its_confirmations_list_removes_no_more_than_that_or_nothing` (also the variant where work that
    stops changes what goes); `test_a_delete_that_must_wait_or_would_remove_more_since_its_card_was_shown_ends_the_card`
    replaces the test that kept a blocked card, and `test_uses_are_recorded_and_counted` and
    `test_the_editors_change_requests_and_the_chat_share_one_daily_count` check more.
  - Left as it was: with a model on this computer, the editor's own daily limit (`edit_requests._sent_today`) counts
    its change requests from their rows, so deleting a video still gives those back, as before this merge. The
    reviewers' doubt about `scripts/assistant_check.py`'s polite-no verdict did not hold up.
- **A check of those fixes** (three more reviewers: the delete guard, the daily count and memory uses, the tests and
  docs; each finding checked again by one who tried to refute it) found one more real problem and three small ones,
  each fixed with a test that failed before:
  - A card could still delete a picture ClipForge made for a short's scenes that it said stays: what ClipForge makes
    for a short goes with it whatever its number, and that rule also covered a picture another project used when the
    card was shown (the owner put the same picture in another video, or two shorts share one; ClipForge keeps one
    file). When the other project was deleted meanwhile, OK deleted it. The plan's `removes` now also lists, as
    `kept`, the files it says stay, and `project_delete.delete(..., removes=)` counts
    such a file as more ("it would now also remove “Scene 1 picture.png”, which ClipForge made for its scenes and no
    other project uses now. Nothing was deleted."). What it makes for a new scene after the card was shown still goes
    with the short.
  - The day's count of online requests looked through every earlier day's requests, once for each of today's change
    requests, before every request under the allowance's lock (about a second after a year of heavy use). A new index
    (`idx_ai_usage_job` on `ai_usage(provider, task, job_id)`, made at the next start) keeps it to today's.
  - Forget and Tidy deleted a memory and the record of its uses in separate steps, so a use recorded in between was
    left over for nothing; Tidy's merge of twins likewise. Each is now one transaction.
  - `docs/clipforge/CLIPFORGE_AI.md` and `AI_HANDOFF.md` still said the editor counts with `allowance.counted` and its
    own row; they now name `allowance.editor_request` and say a part counts only through its `ai_usage` rows.
  - New tests: `test_a_delete_given_its_confirmations_list_never_removes_a_scene_picture_it_said_stays` in
    `tests/test_studio_project_delete.py`; `test_two_shorts_delete_cards_never_remove_a_scene_picture_one_said_stays`
    and `test_the_days_count_takes_no_longer_after_a_year_of_requests` (counted in SQLite's own steps, not time) in
    `tests/test_clipforge_ai_assistant.py`; in `tests/test_clipforge_ai_brain.py`,
    `test_a_use_recorded_while_a_memory_is_forgotten_or_tidied_away_is_never_left_behind`. Two doubts did not hold
    up: a card that waited for work to stop and then found more to delete says only that nothing was deleted (the
    earlier press said the work was being stopped), and the editor's two rows cannot be split by anything in ClipForge
    (each write waits up to 30 seconds for the database).
- **A last check of these fixes** (two reviewers, each finding checked again) found two small things in Tidy and one
  sentence too strong, each fixed with a test that failed before:
  - Tidy's merge of twins wrote the kept memory's use count from what it read at the start, so uses recorded while it
    ran were not counted; and when the kept memory was forgotten while Tidy ran, its twin's use records were moved to
    a memory that was gone. Now one transaction per twin first adds the twin's count as it is at that moment to the
    kept memory (so forgetting that one waits), then moves the records and deletes the twin; when the kept one was
    forgotten meanwhile, the twins stay as they are, each with its own uses.
  - `removes.kept` now lists every file the card says stays, not only what ClipForge made, so nothing it said stays
    can go, whatever becomes ClipForge-made meanwhile.
  - "Only `ai_usage` rows count" was too strong: the editor's change requests from before it wrote its own row still
    count from their own rows; the docs say so.
  - New test: `test_a_twin_merged_into_a_memory_forgotten_meanwhile_leaves_no_use_behind` in
    `tests/test_clipforge_ai_brain.py`; the test of uses recorded during Forget and Tidy now also checks the count.
    Two doubts did not hold up: a card saved without `kept` (only builds of this unreleased branch made one) and a
    file the card said stays turning into one ClipForge made (a picture it makes comes from the scene's own random
    seed).
- **A check of that last round** (one reviewer, each finding checked again by one who tried to refute it) confirmed
  its fixes and found three rare problems in Tidy that are older than this branch, one sentence that said too little
  and two tests that checked too little:
  - Tidy read the expired memories and deleted them by id in a later step, so a guess confirmed (or said again) in
    between was deleted anyway, with its uses, and a confirmation that came a moment later answered with an error. Its
    merge of twins likewise worked on the twins as it had read them: a twin given other words meanwhile was merged
    away, and the kept memory's tags were written from what it had read. Tidy is now one step that takes the
    database's write lock first (`BEGIN IMMEDIATE`) and works on what is there then. An edit or a confirmation of a
    memory deleted between its reading and writing it answers "Memory not found." (`memories._written`).
  - Tidy merged twins kept for different videos, or switched on or off apart, into the stronger one as it was: a
    memory for every video could shrink to one video (and go when that video was deleted), and one switched on could
    end up switched off. Twins now merge only when they apply in the same place and are switched on or off alike; the
    one kept takes their uses, use count, last use and tags, and lasts as long as the last of them would
    (`memories.tidy`). The design notes say so.
  - `project_delete._beyond`'s docstring named one of the two reasons a file is in `kept`; the owner having just added
    it again is the other.
  - New tests, in `tests/test_clipforge_ai_brain.py`: `test_what_the_owner_does_while_tidy_runs_is_never_lost`,
    `test_a_confirmation_or_edit_of_a_memory_gone_meanwhile_says_it_is_gone` and
    `test_tidy_merges_only_twins_kept_for_the_same_videos_and_switched_on_or_off_alike` (each failed before);
    `test_a_twin_merged_into_a_memory_forgotten_meanwhile_leaves_no_use_behind` now also checks that the twin stays
    with its own uses and what Tidy says it merged. In `tests/test_studio_project_delete.py`,
    `test_a_file_the_confirmation_said_stays_is_not_removed_once_a_scene_of_the_short_takes_it`: the case `kept` was
    widened for, which the made-only list deleted.
- **Merged with PR #42** (the release line at e5912bf, merge 4dca7f7: leftover files and upload races after deleting
  projects). PR #42's last look inside the delete's write lock (a file another project took meanwhile, or a copy handed
  out again, stays), `_added_again` with `_marked_since` and `uploads.taken`, and `_maker_originals` are kept as they
  are; the delete card's `removes.kept` now also lists the files a delete's answer says were handed out again
  (`s.handed`), so all of them count as staying. That last look only ever takes files out of what goes, so it never
  conflicts with the card's "no more than it listed" check. `brain.chat.open_chat(create=False)` merged cleanly; the
  change logs keep both sides' entries; `frontend/dist` was rebuilt from the merged sources.
- **A review of how the two fit together** (four reviewers: the delete card, the chat, the docs, Tidy; each finding
  checked again by one who tried to refute it, though two of those checks did not run, so every fix below was first
  shown by a test that failed without it) found:
  - A delete card can wait for days, and PR #42's last look kept every file handed out again since the card was shown
    (the same bytes uploaded, added or stored once more), also when it went to a project deleted since or to the
    project itself: the file then stayed with nothing naming it, though the card had said it goes (three reviewers
    found it; two checks confirmed it end to end). A copy handed out again now keeps a file only within the hour a
    short's tidying waits too (`uploads.REUSE_HOLD_S`, `project_delete._hand_out_since`); one handed out before that
    is recorded by now, and what names the file then decides. The design notes, the `_view` comment and the privacy
    page say so.
  - `remember` read the memory with the same words and wrote over it later: when Tidy, Forget or a video's delete
    came in between, it returned nothing (adding a memory answered 500, the chat said something went wrong), or put
    back the tags and expiry Tidy had just merged. It now writes only over the revision it read
    (`memories._write_over`, one locked step) and reads again otherwise (409 "The memory changed while this was being
    saved. Try again." after five tries). A brain file's import does the same, counts a memory gone meanwhile as
    added with the file's words, and never makes a twin (an edit refuses one too).
  - No test acted while Tidy held its write lock (the tests passed without it). They now do, from another thread:
    a confirmation, an edit and the same words said again wait for Tidy, then apply or answer "Memory not found.".
  - Twins Tidy keeps apart (one for every video and one for a video) were both read into that video's prompt; the
    same kind and words are now read once. The brain check says Tidy merges only exact twins kept for the same videos.
  - The delete card cut its lines at ten, so a long plan could leave off what goes; it shows all of them (at most 16).
  - The Memory tab kept showing a memory that was gone after "Memory not found."; it reloads after a failed action.
  - The privacy page now says a project can be deleted by asking ClipForge AI, that a copy stays only when added again
    on another page in the last day and not used there yet, or handed out again within the hour before deleting, and
    that Tidy merges twins kept for the same videos; one over-long docstring line in `project_delete` was wrapped; the
    hand-off no longer says nothing the owner does during Tidy is lost (a confirmation of a memory Tidy removed
    answers "Memory not found.").
  - New tests: `test_a_confirmation_that_waited_for_days_keeps_only_a_file_handed_out_again_in_the_last_hour` in
    `tests/test_studio_project_delete.py`; in `tests/test_clipforge_ai_brain.py`,
    `test_what_the_owner_does_while_tidy_runs_waits_for_it_and_is_never_lost` (replaces
    `test_what_the_owner_does_while_tidy_runs_is_never_lost`, whose owner acted only after Tidy),
    `test_the_same_words_said_again_while_their_memory_changes_or_goes_are_kept`,
    `test_a_brain_file_never_makes_twins_and_a_memory_gone_meanwhile_gets_its_newer_words` and
    `test_the_same_words_kept_for_every_video_and_for_one_are_read_once_and_left_to_the_owner`; in
    `tests/test_clipforge_ai_assistant.py`, `test_a_delete_card_shows_all_of_what_goes_and_what_stays`.
  - Left for PR #42's owners (told): a project's own build or upload that stores the same bytes again within the hour
    before its delete still keeps that copy with nothing naming it (on the Projects page too, while its window is
    open); the privacy page does not yet describe PR #42's upload records, a short's list of stored files or where
    the makers' originals go.
- **A last look at those fixes** (two reviewers, the memories and the delete; each finding checked again by one who
  tried to refute it, and all ten held up; each code fix has a test that failed before it):
  - A brain file's newer revision of a memory was skipped whenever another memory said those words: also when it only
    switched the memory off or retagged it, and when the owner had given it the words of a rule this computer already
    had, the replaced words stayed in force beside the new ones (counted as "already known"). A newer revision is
    applied again, as before 3719ab0; the twins it leaves are read once, and Tidy merges those kept for the same videos
    and switched on or off alike.
  - Twins were read once by keeping the higher score before the relevance floor: when that twin fell under the floor
    (its meaning still from the embedder used before Rebuild), the memory was not read at all. The one read is now
    chosen among those that fit the question (`memories._once`).
  - An edit and a confirmation wrote their own read + 1 as the revision, so two different states of a memory could
    share one, and an answer saying the same words again meanwhile wrote over the edit (its old words back, beside the
    edit's stored form and meaning) or undid the confirmation. Both now write only over the memory as they read it
    (`memories._write_over`) and read it again otherwise, like `remember`.
  - The Memory tab's Forget (and Where it was used) on a memory forgotten elsewhere meanwhile left the gone row listed;
    it reloads the list (the dialog says "Memory not found.").
  - Find media's automatic round imported every pick first and put them in the video's media only after the last
    download. A delete of another project with the same file in between (the same item imported before, which no
    hand-out marks, or the same bytes handed out more than an hour before) removed it, and the round failed with "Asset
    not found.". Each pick now goes into the video's media as it is imported, as one import does.
  - Docs: the privacy page says what the card's OK removes (no file, video copy or planned post it did not list; what
    belongs to the project goes however much there is by then), that a copy added again since the day before the list
    was shown stays, and that Tidy merges twins switched on or off alike; the design notes and the hand-off no longer
    say an old card keeps no file nothing names (one handed out within the hour before OK still stays) or that what
    the owner does during Tidy is never merged away.
  - New tests: in `tests/test_clipforge_ai_brain.py`,
    `test_a_brain_files_newer_revision_is_applied_beside_a_twin_and_a_memory_gone_meanwhile_gets_its_newer_words` (in
    place of `test_a_brain_file_never_makes_twins_and_a_memory_gone_meanwhile_gets_its_newer_words`),
    `test_an_edit_or_a_confirmation_writes_only_over_the_memory_as_it_read_it` and
    `test_twins_are_read_once_from_those_that_fit_the_question`; in `tests/test_studio_media_sources.py`,
    `test_a_pick_is_in_the_videos_media_before_the_next_one_downloads`.
    `test_a_confirmation_or_edit_of_a_memory_gone_meanwhile_says_it_is_gone` now forgets the memory right after it is
    read (it hooked `db.update`, which an edit no longer calls). The click-through presses Forget on a memory forgotten
    elsewhere meanwhile.
- **One more look at those fixes** (two reviewers, the memories and the delete; each finding checked again by one who
  tried to refute it: four of five held up, one in the code and three about two sentences of the design notes; one about
  the delete's wording did not; the code fix has tests that failed before it): "forget …" with a memory's exact words
  removed only one memory that says them. A twin (the same words kept for one video, switched off, or as another kind)
  stayed in force while the answer said "Forgotten", and the Forget card named one memory. Now every memory that says
  those words goes (`memories.forget_words`, `memories.saying`), the answer says how many times it was kept, and the
  rules-only chat also understands "forget my …" as the fast path does. The Forget card names each memory it forgets
  (where it applies, switched off or not); its OK forgets only those (`memory_ids`, which only the button keeps), each
  only while it still says the card's words (`memories.forget(..., words=)`, checked and deleted in one locked step),
  and says how many went and how many were changed since and stay. Docs: the design notes say that "remember" and a
  brain file keep the words of a memory gone in between while an edit or a confirmation answers "Memory not found.", and
  that a brain file's twins are merged by Tidy when kept for the same videos and switched on or off alike; the privacy
  page says that asking ClipForge AI to forget forgets every memory that says those words. New tests:
  `test_forget_with_the_exact_words_forgets_every_memory_that_says_them` (`tests/test_clipforge_ai_chat.py`) and
  `test_forget_takes_every_memory_that_says_those_words_and_its_button_only_what_it_listed`
  (`tests/test_clipforge_ai_assistant.py`).
- **A look at that fix** (one reviewer; each finding checked again by one who tried to refute it, and all five held up;
  each fix has a test that failed before it):
  - A Forget card saved by an earlier build of this branch named one memory (`memory_id`), which the new arguments
    dropped, so its OK looked for memories again: it could forget the closest other memory ("Zoom in on faces in
    interviews" when "Never zoom in on faces" was forgotten meanwhile) or twins the card never named. `memory_id` is a
    button-only argument again, and OK forgets only the memories its card named; it never looks again.
  - "forget" was not a whole word: saying again a memory that starts with "Forgetting …" or "Forgetful …" deleted it (in
    the chat without a model since that fix, with a model before it), and "forget mystery music" read as "forget my" and
    "stery music". "forget" and the words it skips are whole words now, and so are "remember" and "note" in the chat
    without a model ("Notes from the shoot …" was kept as the memory "s from the shoot …" since phase A).
  - "forget my intro is 3 seconds" (what the Forget chip of "my intro is 3 seconds" sends) also forgot a memory that
    says "intro is 3 seconds", and named that one. The words after "forget" come first now; those after a leading "my",
    "that", "the", "about" or "what I said about" count only when no memory says them all (`chat._said`).
  - A Forget card showed at most 19 of the memories it forgot (a card shows 20 lines) yet forgot up to 50, and with more
    than 50 it said "them all" and left some. A card names at most 16 (`toolbox.FORGET_MAX`); one that would need more
    cannot be pressed and says to use the exact words in the chat, which forget them all, or Brain → Memory.
  - The design notes said "remember" and a brain file keep the words of a memory tidied into its twin "as a memory of
    their own": "remember" writes into the twin Tidy kept, and a brain file whose words a memory says is skipped. A
    Forget card for one memory now also says where it applies.
  - New tests: `test_forget_takes_only_the_words_the_owner_named_and_only_as_a_whole_word`
    (`tests/test_clipforge_ai_chat.py`) and `test_ok_on_a_forget_card_never_looks_for_memories_again`
    (`tests/test_clipforge_ai_assistant.py`).
- **A last look at forgetting** (one reviewer; each finding checked again by one who tried to refute it, and all six
  held up; each fix has a test that failed before it, and the click-through tried the buttons in the app):
  - A correction such as "Forget that, keep the music low" (or "Forget that. Keep …", "Forget, keep …", "Forget about
    that - keep …", "Forget. Keep …", or "Forget that" with the rule on the next line) forgot at once the very rule it
    says again, with its twins. "forget" and each word it skips now count only with a space after them (a colon after
    "forget"); anything else goes to the conversation, or without a model to "Which one?", and nothing is forgotten.
  - A "Which one?" button pressed again, or after its memory was forgotten or changed elsewhere, forgot another memory
    with fewer words ("intro is 3 seconds" for "the intro is 3 seconds"). The button now sends the words in quotes;
    quoted words go only as they are, and when no memory says them the answer is "Nothing I remember says “…”, so
    nothing was forgotten."
  - A quick reply the model offered ("Forget “Keep the music low”") forgot every memory that says those words on one
    press, with no Forget card. The page now sends a quick reply (the model's choices and the editor's) with `choice`,
    which never forgets at once: the model's Forget card shows what would go, or without a model "Which one?".
  - In the chat without a model "Remember that's my sister in the intro" was kept as "'s my sister in the intro",
    "Note-taking …" as "taking …", and "Forget-me-nots …" asked which memory to forget. "remember", "note", "keep in
    mind", "forget" and the "that" left out are whole words now; a dash separates only after a space ("note - the drone
    shots …").
  - "Which one?" listed the same words kept twice (a rule and a fact) as two picks, and either pick forgot both. It
    lists the same words once now, with how many times they are kept and that picking them forgets each.
  - OK on a Forget card saved by the build before (it named up to 50 memories) forgot only the first 16 and said
    nothing of the rest. Such a card now forgets none and says to use the exact words or Brain → Memory
    (`toolbox.FORGET_IDS`).
  - New tests: `test_a_correction_never_forgets_and_a_longer_word_is_never_cut` and
    `test_which_one_lists_each_set_of_words_once_and_its_button_forgets_only_those_words`
    (`tests/test_clipforge_ai_chat.py`), and
    `test_a_tapped_quick_reply_never_forgets_at_once_and_quoted_words_forget_only_themselves`
    (`tests/test_clipforge_ai_assistant.py`); `frontend/dist` rebuilt. The click-through (outside the repo) checks
    that a quick reply is sent with `choice`, and that the "Which one?" button sends the words in quotes, forgets both
    twins, and pressed again forgets nothing.
- **A look at those fixes** (one reviewer; each finding checked again by one who tried to refute it, and all three held
  up; each fix has a test that failed before it):
  - A correction with an emoji, a smiley, a bracket or an arrow after "forget" or "that" ("Forget that 😅 keep the
    music low", "Forget :) keep …", "Forget that (keep …)", or "Forget that 🙈" with the rule on the next line) still
    forgot the rule it says again, with its twins: only sentence punctuation ended the request, and a memory's words
    count only letters and digits. "forget" and each word it skips now count only when a word (a letter or a digit)
    or an opening quote follows the space (`chat._GOES_ON`); anything else goes to the conversation, or without a
    model to "Which one?". Typing "forget" and the exact words of a memory that starts with an emoji or a "#" now
    asks first too.
  - Without a model, "Remember that.", "Note that." and "Keep in mind that." (and "Remember that!") kept a memory
    saying "that" for every video. "that" is left out wherever it ends as a word; words that only point back ("that",
    "this", "it" …) or have no letter or digit keep nothing and ask what to remember; "Remember that. The outro is 2
    seconds" keeps the sentence after it.
  - A "Which one?" button for a memory with quotes of its own ("Call the series “Trail Notes”", 'Say "hello" …') did
    not count as quoted: pressed again it listed other memories (or, with a model, went to the model) instead of
    saying "Nothing I remember says …". In curly quotes the quoted words now run from the first “ to the last ”, as
    long as the curly quotes inside pair up (`chat._quoted`); “a” and “b” typed in one message stay two quotes.
  - New cases in `test_a_correction_never_forgets_and_a_longer_word_is_never_cut` and
    `test_which_one_lists_each_set_of_words_once_and_its_button_forgets_only_those_words`
    (`tests/test_clipforge_ai_chat.py`) and in
    `test_a_tapped_quick_reply_never_forgets_at_once_and_quoted_words_forget_only_themselves`
    (`tests/test_clipforge_ai_assistant.py`); no frontend change.
- **A look at the emoji fix** (two reviewers; each finding checked again by one who tried to refute it: eight
  held up, two of them the same problem; two more were judged older or only cosmetic and are fixed too; each code
  fix has a test that failed before it):
  - A correction with a quote that more words follow ("Forget the “🔇”, keep the music low", "Forget that “…” keep
    the music low") still forgot the rule it says again, with its twins, with or without a model: an opening quote
    let "forget" go on, and a memory's words count only letters and digits. A quote now counts only when it holds
    all the words (`chat._said`); otherwise the conversation, or without a model "Which one?", answers it. The docs
    now name the two quote marks that count (“ and "); other quote marks (« », „ “ …) ask first.
  - Without a model, words that name nothing on their own still kept a memory: "Remember that one" kept "one",
    "Remember this…", "Remember it 👍" and "Remember this :)" kept "this…", "it 👍" and "this :)", and "Remember that
    :D" kept "D". The check now reads only the words, leaves smileys out, and knows "that one", "these", "please" and
    the like (`chat._names_nothing`).
  - "Note -14 LUFS for YouTube" and "Remember that -3 dB is right for music" lost their minus ("14 LUFS …"): a dash
    now separates only with a space on both sides. The "that" is left out only before a space, a colon, a comma, or
    ".", "!", "?" or "…" that end a sentence, so "Remember that; …" keeps its words whole, as before the last round.
  - With a model, "remember: it" failed with "Say what to remember"; words that name nothing on their own now go to
    the conversation, which can read what "it" is.
  - "remember: …" (or, without a model, "Remember that. …") on words a memory already says switched that memory on
    and showed an Undo chip that deleted it: the older memory was gone, not put back as it was. The answer now says
    "I already remember “…”" (with "switched on again" when it was off) and has no Undo chip, so Undo still forgets
    only what an answer added. (Older than the last round; fixed here.)
  - Docs: the handoff now says a colon after "forget" counts too; CLIPFORGE_AI.md step 4 and the rules table say what
    "remember: …" does with words that name nothing and with words a memory already says.
  - New tests: `test_remembering_words_a_memory_already_says_offers_no_undo` (`tests/test_clipforge_ai_chat.py`) and
    `test_remember_with_a_colon_needs_words_that_name_something_and_offers_no_undo_for_an_older_memory`
    (`tests/test_clipforge_ai_assistant.py`), and new cases in
    `test_a_correction_never_forgets_and_a_longer_word_is_never_cut` and
    `test_a_tapped_quick_reply_never_forgets_at_once_and_quoted_words_forget_only_themselves`; no frontend change.
- **A look at the quote fix** (two reviewers; each finding checked again by one who tried to refute it: all thirteen
  held up, two of them the same problem; each code fix has a test that failed before it):
  - Words that differ only in a Thai tone mark or an Indic vowel sign ("ตัดคลิปข่าวออก", cut the news clips, and
    "ตัดคลิปข้าวออก", cut the rice clips), in the sign of a number ("voice at -3 dB" and "+3 dB") or in a colon or a
    point between digits ("0:42" and "0.42") counted as the same words: "forget …" forgot both, a Forget card showed
    one, and "remember: …" wrote the new words over the other memory. A memory's words now keep the marks that
    belong to a letter (composed first, so an accent typed apart is the same letter), the sign or point in front of
    a number and a point, comma, colon or slash between two digits (`memories._norm`). Memories saved with the old
    form are still found and compared again by their words, and Tidy stores the new form.
  - Undo forgot its memory by id whatever it said now: after "remember: …" wrote over it, an edit in Brain → Memory
    or a switch, it deleted words its answer never added, and a chip an earlier build saved for a memory it wrote
    over did the same. Undo now sends the chip's words to `POST /api/brain/memories/{id}/undo`, and the memory goes
    only while it is as the answer added it (revision 1 and the same words, `memories.undo`); otherwise the chip says
    it changed since and the memory stays. A chip whose memory is past revision 1 shows no Undo, and "remember: …"
    reads "added" from what it wrote, not from a look just before.
  - The "Which one?" Forget button never forgot a memory with German, Polish or Swedish quotation marks („…“, ”…”) or
    an inch mark: the words it sent in quotes did not pair up, so each press asked "Which one?" again. The button now
    sends the memory's words apart from the message (`forget` in `POST …/messages`, `chat._forget_picked`): every
    memory that says exactly those words goes, with or without a model, and pressed again it says nothing says them.
  - "remember: …" on words a memory of the other kind already said (a rule, when the words read as a fact) added a
    second memory with Undo, against the docs. A memory of either kind is now written over, and the answer says what
    it was before: "(switched on again; before, only for tiktok)", "(no longer only a guess)", or "I already had “…”;
    it now says “…”" when its symbols or punctuation differed (case, spacing and the kind of apostrophe do not count).
  - "Forget that" with the rule on the next line still forgot the rule when the line break was a line or paragraph
    separator, NEL, a vertical tab or a page break (pasted text): every line break counts now (`chat._message`).
  - In a video's chat, "Remember -3 dB here" kept "3 dB", "here's the plan" kept "'s the plan" and a title like "Here
    Comes the Sun" lost its "Here". "for this video" still counts anywhere, "here" only where the words end (also "in
    here", "right here") or as "here:" before them, and only the separators around them go, never a minus.
  - Words that only ask nicely or say when still kept a memory ("Remember this, please", "Remember that for later",
    "remember: that, please"), and with a model "remember: that for this video" failed with "Say what to remember"
    instead of going to the conversation. Without a model "Never mind" became a rule and "I like that", "Always." or
    "Never again" a memory; now "All right: nothing was kept or forgotten." and "Say what to remember …".
  - Docs: CLIPFORGE_AI.md (how words compare, Undo, the "Which one?" button, "here", twins of either kind, "never
    mind"), the handoff, and the privacy page (Undo forgets a memory only while it is as its answer saved it).
  - New tests: `test_a_mark_of_a_letter_or_the_sign_of_a_number_makes_other_words` (`tests/test_clipforge_ai_brain.py`);
    `test_undo_forgets_a_memory_only_while_it_is_as_its_answer_added_it`,
    `test_a_which_one_button_forgets_exactly_the_words_it_shows_whatever_quotes_they_hold`,
    `test_forget_that_with_the_rule_on_the_next_line_forgets_nothing_whatever_the_line_break`,
    `test_words_that_name_nothing_keep_nothing_and_never_mind_is_no_rule`,
    `test_here_and_for_this_video_keep_a_memory_to_the_video_and_leave_its_words_whole` and new cases in
    `test_remembering_words_a_memory_already_says_offers_no_undo` (`tests/test_clipforge_ai_chat.py`);
    `test_with_a_model_scope_words_alone_name_nothing_and_a_which_one_button_needs_no_model`
    (`tests/test_clipforge_ai_assistant.py`). Frontend: the Undo chip and the "Which one?" button (`ClipForgeAI.tsx`,
    `brain.ts`), `frontend/dist` rebuilt.
- **A look at the Undo and marks fix** (two reviewers, thirteen findings; six were checked again by one who tried to
  refute them and held up, the second check of the other seven could not run, so I reproduced each of those myself;
  each code fix has a test that failed before it). Three rounds in a row had found one more mark or one more phrase
  the rules missed, so this round changes the rules themselves instead of adding cases:
  - Words that differ only in a sign after a letter ("亮度+10" and "亮度-10", "EV+1" and "EV-1", "UTC+2" and "UTC-2"),
    in how a sign is written ("+/-3 dB" and "-3 dB", "+.5" and "-.5", full-width "＋３" and "－３") or in a symbol
    ("<3 s" and ">3 s") still counted as the same words: the second was written over the first, and forgetting one
    forgot both. Words are now compared strictly (`memories._norm`). Only what cannot change what they say is left
    out: capitals, spacing, how an accent or a full-width character was typed, the kind of dash or apostrophe,
    characters nobody sees, and the quotes, brackets and sentence marks around a word. Every sign, symbol, emoji,
    hyphen inside a word and mark of a letter counts. When in doubt words are different, so two memories stand side
    by side instead of one replacing the other. Known limit: a quote mark right after a number is read as a quote,
    so 5' and 5" are both 5.
  - A memory an earlier build stored was looked up by guessing that build's stored form from the new words, which
    missed one whose accent was typed apart ("Café" was stored as "cafe" and asked for as "caf"). The stored forms
    are now brought up to date once, at the first lookup after a start (`memories._refresh_norms`: one step, the
    words, revision and dates stay), and every lookup uses the one current form.
  - In a video's chat, "here" followed by a polite word, a comma, a bracket, a smiley or "too" no longer kept the
    memory to the video (the last fix broke that), and cutting the place words out of the sentence broke the words:
    "never zoom in here" was kept as "never zoom", "the music in this video's intro" as "the music 's intro", "slow
    motion only for this one clip" as "slow motion only clip". "this video", "for this one" and "here" as a word of
    its own now only say where the memory applies, and the words are kept whole ("Remember -3 dB here" keeps "-3 dB
    here", for this video). Only a label in front goes: "for this video: -14 LUFS" keeps "-14 LUFS".
  - "Always for this video.", "Remember that from now on", "Remember it forever" and, in the general chat,
    "remember: that for this video" were kept as memories. One list of words that name nothing (`chat._NO_CONTENT`:
    words that point back, ask nicely, or say when or where) now decides it the same way in both chats.
  - "Never mind" answered "nothing was kept or forgotten" even right after an answer that had kept a memory. It now
    says it did nothing with that message, that what was kept or forgotten before stays, and how to remove a memory.
  - A message sent with both `choice` and `forget` forgot at once, against the rule that a quick reply never forgets.
    It is refused now (422); the page never sends both.
  - Not changed, on purpose: the same words said again for another video still move that memory there
    (`memories.remember`, as released, documented and tested); the answer says where it was kept before.
  - Docs: CLIPFORGE_AI.md (how words compare, earlier builds' memories, "here" and the label, words that name
    nothing, "never mind", the API list with `POST /api/brain/memories/{id}/undo` and the `forget` field) and the
    handoff. The privacy page needed no change: what is stored, sent, kept and deleted is the same.
  - Tests: `test_a_mark_of_a_letter_or_the_sign_of_a_number_makes_other_words` and
    `test_memories_in_any_language_are_twins_only_when_they_say_the_same_words` (`tests/test_clipforge_ai_brain.py`);
    `test_remembering_words_a_memory_already_says_offers_no_undo`,
    `test_words_that_name_nothing_keep_nothing_and_never_mind_is_no_rule`,
    `test_here_and_for_this_video_keep_a_memory_to_the_video_and_leave_its_words_whole` and
    `test_a_which_one_button_forgets_exactly_the_words_it_shows_whatever_quotes_they_hold`
    (`tests/test_clipforge_ai_chat.py`);
    `test_with_a_model_scope_words_alone_name_nothing_and_a_which_one_button_needs_no_model`
    (`tests/test_clipforge_ai_assistant.py`): all seven failed on the code before. No frontend change.
- **A look at the strict comparison** (two reviewers, eight findings; two were checked again by one who tried to
  refute them and held up, the second check of the other six could not run, so I reproduced each of those myself on
  the code as it was; each code fix has a test that failed before it):
  - The list of words that name nothing had grown to 169 everyday words ("I", "is", "not", "in", "one", "time" …),
    so facts made only of such words were refused, or with a model sent to the conversation: "remember: I am not in
    the videos", "remember: I'm in the US", "remember: one video at a time", "Always be on time". Words now name
    nothing only when all they do is point back, ask nicely or say when or where, read as turns of speech and not
    word by word (`chat._names_nothing`: "that one, please", "it from now on", "keep that in mind", "do that
    again", "for all my videos"). When in doubt they are kept (their answer has an Undo). A first version of this
    was one pattern over the whole message, which never finished on a long run of "one one one …"; it is read turn
    by turn now, a few short matches per word (`test_a_long_message_of_repeated_words_is_read_at_once`).
  - Words that are only a quote mark ("remember: '") were kept as a memory with nothing in it. They name nothing.
  - In a video's chat every mention of "this video" kept the memory to that video, also when the words are about
    other videos or about later: "use this video as the template for the next ones", "Never use the music from this
    video again", "Always keep the voice up, not only in this video". Now "for/in/on this video" and "here" say
    where the words apply, unless "not only", "not just", "than" or "unlike" stands right before them, or it is
    "from here on" (from now on); words that only mention this video are kept for it when they speak of no other
    video and of no later time (`chat._for_this_video`). On purpose "here" always means this video, also as a place:
    "my office is here in Lyon" said in a video's chat is kept for that video.
  - Marks that stand alone were left out of the comparison, so "Never end a caption with !" and "… with ?" were the
    same words, as were "- 3 dB" and "3 dB", "!= 30" and "= 30", ":)" and ":(": the second was written over the
    first, and forgetting one forgot both. Any other mark at the edge of a word was dropped too ("5*" was "5",
    "٥٠٪" was "٥٠"), and folding capitals made "Maßen" and "Massen" one word. `memories._norm` now lists what it
    leaves out, and nothing else is: around a word that has a letter or a digit its quotes and brackets, ¿ or ¡
    before it and the marks that end a sentence after it; whatever stands alone between spaces counts exactly as it
    is; capitals are made small, not folded. On 600,000 texts made from the tests' sentences with marks, capitals
    and spacing added, the new comparison only told more words apart than the one before: no two that differed
    before were the same after. (That is true of that sample, not of every text; the next look found one pair the
    other way, rightly so.) What follows from "when in doubt, different", and is documented: a mark
    typed with a space before it, as French does ("basse !"), makes other words than "basse!" (a second memory at
    worst); "- keep it low" is not "keep it low". The known limit stays: 5' and 5" are both 5.
  - A sentence's last full stop is left out of the words kept only when it ends a word: "Never end a caption with ."
    keeps its mark.
  - Without a model, "forget -3 dB here" (words that start with a sign never forget at once) answered "I have
    nothing like that in my memory" although a memory said exactly that; so did "forget -3 dB" for the memory "-3
    dB here", and words in another script: the search by meaning reads only Latin words longer than two letters.
    "Which one?" now lists first the memories that say exactly the words named, then those that hold them as whole
    words in that order (`memories.holding`, read from the words themselves), then what the search finds. Not
    changed: "what do you know about …" still uses that search alone.
  - Tidy as the first thing after a start, on memories an earlier build stored, had no test: a version of Tidy that
    trusted the stored form passed the whole suite. `test_tidy_first_thing_after_a_start_goes_by_the_words_and_not_
    by_a_form_an_earlier_build_stored` fails for it.
  - Docs: CLIPFORGE_AI.md (what the comparison leaves out, where a memory applies in a video's chat, words that
    name nothing, what "Which one?" lists) and the handoff. The privacy page needed no change: what is stored, sent,
    kept and deleted is the same.
  - Tests: `test_a_mark_of_a_letter_or_the_sign_of_a_number_makes_other_words` (new pairs),
    `test_tidy_first_thing_after_a_start_goes_by_the_words_and_not_by_a_form_an_earlier_build_stored` and
    `test_memories_that_hold_the_words_named_are_found_by_their_words_in_any_script`
    (`tests/test_clipforge_ai_brain.py`); `test_words_that_name_nothing_keep_nothing_and_never_mind_is_no_rule`,
    `test_a_long_message_of_repeated_words_is_read_at_once`,
    `test_here_and_for_this_video_keep_a_memory_to_the_video_and_leave_its_words_whole`,
    `test_remembering_words_a_memory_already_says_offers_no_undo` and
    `test_forget_offers_the_memories_that_say_or_hold_the_words_named_whatever_they_start_with`
    (`tests/test_clipforge_ai_chat.py`);
    `test_with_a_model_scope_words_alone_name_nothing_and_a_which_one_button_needs_no_model`
    (`tests/test_clipforge_ai_assistant.py`). No frontend change.
- **A look at the lone marks and the "this video" fix** (two reviewers, fourteen findings: one medium, thirteen low.
  Only one had its second check, by one who tried to refute it, and it held up; the second check of the other
  thirteen could not run, so I reproduced each of those myself on the code as it was. Each code fix has a test that
  failed before it: the four changed test files run on the code before give 15 failed, every new or changed test):
  - The medium one: in a video's chat, facts about that very video were kept for every video when they also said
    "each one", "the other one" or "never … again", or placed the video in a series ("this video is private, never
    upload it again", "in this video each one speaks for a minute"); words with a bare "this one" were too. Words
    that point at this video can only be read in its own chat: in another video's chat "this video" means that
    other video. So they now always keep the memory to this video (`memories.points_here`, read by the chat and by
    the model's `remember` tool, whatever scope the model chose): "this video", "this project", "this one", a piece
    of it ("this clip", "this shot", "these scenes"), or "here" as a word of its own. When such words also speak of
    other videos or of later, or liken something to this one ("like in this video", "shorter than this one", "from
    this video on"), the owner may have meant a rule for every video, so the answer says why it stayed and how to
    say it for every video: "It applies to this video only, because it says “this video”. To keep it for every
    video, say the video's name (“Hike”) instead." (for a piece of it: "say which clip instead"). Only two turns of
    speech reach further by themselves, and then the memory is for every video: "not only" or "not just" right
    before the words, and "from here on" where it can only mean from now on. Not pointing at all: "this channel",
    "this one thing: …", "this one rule", and "here is …" or "here are …" in front of the words.
  - Found by me on the way, the same kind of loss: the same words said in a second video's chat moved the first
    video's note to the second video (identical episodes of two videos moved too), and the model's tool refused the
    second one as "only for another video". An earlier round had left this as released. Where a memory is kept is
    now part of what it is (`memories.twin(ws, text, kind, scope)`, `_same_words`): a write goes over the memory
    that says the words in the same place, else over the one kept for every video (which stays so), else, for words
    to keep for every video, over the oldest kept anywhere (it widens). A memory kept for another video, platform or
    kind of project never moves: the same words there are a memory of their own. Editing ("Another memory already
    says that", 409), the brain file's import (skipped) and the health check's twins follow the same rule.
  - With that, "forget …" asked in a video's chat is about that video (`memories.meant`): a note another video keeps
    under the same words stays when this video, or every video, has one too, and the answer says so ("Another video
    keeps the same words: its note stays."). When only other videos keep the words, the words name those notes,
    which go as before; in the general chat all go. Typed words, the "Which one?" list and its buttons, and the
    model's Forget card all follow it.
  - A sentence mark of another script behind a word (Armenian ։, Ethiopic ።, Burmese ။, Khmer ។, Tibetan །, the
    half-width ｡, the Greek raised point) made other words than the same words without it; the version before had
    left such marks out, and the docs said they are. `memories._STOPS` is now Unicode's own list of the marks that
    end a sentence or a part of one (Terminal_Punctuation as of Unicode 17, written out so that every Python reads
    the same 295 marks, with … and ·).
  - "Which one?" did not find a part of a memory written in a script without spaces between words ("forget 字幕"
    for "字幕は大きくする") or a Korean word without its ending, though the docs said "any script".
    `memories.holding` finds a part wherever it stands when the characters that meet there belong to such a script
    (`_holds`, `_UNSPACED`).
  - A long "forget" message made of words the request skips ("forget: my my my …", "forget that that that …") took
    7 to 8 seconds: every leading word gave one more reading of the whole rest, each compared and looked up two or
    three times. One request is read at most twelve ways now (`chat._FORMS`); the same messages take 0.02 to 0.11 s.
  - With a model, the Forget card did not find a memory by a number, a short word or a word in another script
    ("-3 dB" for "-3 dB here", "на голос", "0:42"): it failed with "Nothing like that is in the memory." After the
    exact words the card now looks for the newest memory that holds them (`toolbox._memories_for`), never for
    little words alone ("that", "the rule").
  - Without a model, "forget -3 dB here, please", "… too" and "forget the rule about -3 dB" found nothing, because
    the words were looked up only whole. For the list to pick from they are also read without a polite word behind
    them and without "the rule about" or "the one that says" in front (`chat._named`, `_LEADS`, `_POLITE`).
    Forgetting at once still takes a memory's exact words only.
  - Three rules had no test that fails without them (not listing every memory that holds "that" or "the"; the
    memory that says the words before the ones that hold them; "not only this video"). Each has one now, checked by
    taking the rule out.
  - Kept on purpose, and pinned by a test now: `forget "!"` typed in quotes forgets the memory “!” at once, as
    quoted words always do.
  - The entry above said the strict comparison "only tells more words apart than the one before". That held for
    the 600,000 texts checked, not for every text: a Greek capital with an iota subscript and two accents typed
    apart, and its small form, were different words before and are rightly the same now (they differ only in
    capitals). That sentence is corrected. Against the version before, this round makes words the same only through
    a newly listed sentence mark behind a word (103,605 of 600,000 pairs); none that were the same became different.
  - Also found on the way: a message or a memory with half of an emoji in it (text cut in the middle of one) got a
    server error instead of an answer. The half is left out now in everything the brain's addresses receive
    (`routes.Input`, `tools.whole`). Other pages' addresses still answer such text with a server error, as released.
  - Known and left for later: the Memory page shows "One video" without the video's name, so the notes two videos
    keep under the same words look alike there.
  - Docs: CLIPFORGE_AI.md (where a memory applies and the hint, the same words in two videos, "forget" in a
    video's chat, sentence marks, scripts without spaces, how "Which one?" and the Forget card read the words, half
    an emoji), the handoff, and the privacy page: asked in one video's chat, "forget" leaves a note that another
    video keeps under the same words when this video, or every video, has one too.
  - Tests: `test_a_mark_of_a_letter_or_the_sign_of_a_number_makes_other_words` (other scripts' marks, the 295),
    `test_memories_that_hold_the_words_named_are_found_by_their_words_in_any_script` (scripts without spaces) and
    `test_the_same_words_kept_for_two_videos_are_two_memories_everywhere` (new) in
    `tests/test_clipforge_ai_brain.py`;
    `test_here_and_for_this_video_keep_a_memory_to_the_video_and_leave_its_words_whole`,
    `test_the_same_words_said_in_two_videos_are_kept_for_each_of_them` (new),
    `test_forget_offers_the_memories_that_say_or_hold_the_words_named_whatever_they_start_with`,
    `test_forget_with_only_words_it_skips_lists_no_memory_that_merely_holds_such_a_word` (new),
    `test_half_an_emoji_in_a_message_or_a_memory_is_left_out` (new) and
    `test_a_long_message_of_repeated_words_is_read_at_once` in `tests/test_clipforge_ai_chat.py`;
    `test_the_remember_tool_keeps_words_that_point_at_this_video_for_this_video` (new),
    `test_a_forget_card_finds_a_memory_by_a_number_a_short_word_or_a_word_in_another_script` (new),
    `test_the_remember_tool_leaves_a_memory_for_one_video_where_it_is` and
    `test_a_memory_said_again_keeps_its_scope_and_its_video_together` in `tests/test_clipforge_ai_safety.py`;
    `test_with_a_model_scope_words_alone_name_nothing_and_a_which_one_button_needs_no_model`
    (`tests/test_clipforge_ai_assistant.py`). No frontend change.
- **A look at the "this video" round** (b28ad7c). The two reviewers set on it both ran out of usage before they
  could report, so this round has no independent findings. I ran again every check they had left behind on that
  version (how each sentence is placed, the same words in several places, the model's tool, forgetting in every
  place, the addresses, the brain file, an upgrade from the released build, 2,000 made-up "forget" messages against
  the version before, their list of deliberate breakages) and read the code again myself. What came of it, each
  code fix with a test that failed before it:
  - The full fast suite had one failure on b28ad7c, which the runs of the AI test files alone had not shown: a
    test of the delete feature (PR #35) still expected the same words said for a second video to move the first
    video's memory. It now checks what holds since the round before: both videos keep their own memory, and
    deleting the first video leaves the second's.
  - A brain file's memory for every video was skipped when only one video (or one platform) kept those words
    here, so a rule brought over from another computer held in that one video only. It is added beside that note
    now (`memories._import_one`). A file never changes or widens a memory with another id: its memory may be
    switched off or only a guess.
  - The versions released before this one moved a memory to the video that said its words last and left its
    `project_id` column naming the first video. Three readers went by that column: the list of one video's
    memories (`list_`), the small boost a video's own memories get in a search (`_scores`) and a video's "why …"
    answer (`chat._explain`). Such a memory showed up for the video it had left and not for the one it is kept for.
    All three go by the scope now, as recall and a video's delete already did. Old data is not rewritten: the
    column is still written, and never read by itself.
  - With a model, the Forget card for words that are a part of several memories ("captions here") was for the
    newest of them, also when that was another video's note and this video had its own. In a video's chat the card
    is now for the newest that applies there (`toolbox._memories_for`); when only other videos' notes hold the
    words, and in the general chat, for the newest of all, as before.
  - An answer said "It applies to this video." without saying why, also when no place was meant ("this one song
    is my favourite", "I'm here for the comments"). Such words stay with the video on purpose: too narrow is the
    safer mistake than a private note read in every video. The answer now names the words, "It applies to this
    video, because it says “here”." (`chat._applies`), the model's tool tells the model the same, and the step line
    of a memory kept for one video ends with "for this video", since the model may have said every video
    (`toolbox._keep`).
  - When the owner says a rule plainly and a small model only answers "Got it", ClipForge keeps the words itself
    (`assistant._keep_said`). When the memory already held them switched off, only as a guess, or for one video or
    one platform, nothing showed, so "Got it" stood over a rule that stayed off. The answer now shows the step the
    tool shows ("Already in your memory, but switched off: “…”") with the button to Brain → Memory. Nothing is
    changed for the owner, as before.
  - A request to the Brain's addresses nested thousands of levels deep got a server error. It is refused in plain
    words now (422, "That is nested too deeply to read.", `routes.Input`). Nothing ClipForge sends is nested so.
  - Tests that fail without a rule: the reviewers' list of 46 deliberate breakages (each takes one rule out of
    the code) had left three standing and ten unrun. With the rules of this round the list has 59, run against
    the AI test files and the delete test on copies of the code. 57 now fail a test. The two that do not change
    nothing the owner can see: in the general chat no note is left to count after "forget", and the "Which one?"
    list groups memories by their words whichever one it finds first. Seven rules got the test they lacked: the
    health check lists a memory for every video beside one video's own; what kind a memory is never comes from
    another video's note; a platform's memory counts as applying in a video's chat when forgetting; the answer
    counts two other videos' notes ("2 other videos keep the same words: their notes stay."); the Forget card
    leaves out another video's note with the found memory's very words; a video's own memories come first in its
    searches by their scope; and the plainly said rule that is already there (above).
  - Known and left as they are: the Forget card does not mention a note another video keeps under the same words
    (the typed "forget" does); "its note stays" reads the same when that other video keeps the words twice;
    "forget everything" answers "I have nothing like that in my memory."; for words such as "the note" the card
    can offer a weak match of the search (nothing goes without OK); changing only the spelling of a one-video
    memory whose words a memory for every video also says answers 409; the same words can be kept as a rule and
    as a fact through the address; an Ethiopic wordspace, or a danda with no space behind it, is not read as a
    sentence mark. As released and outside this change: the older Autopilot Brain addresses
    (`/api/brain/observations`, `/api/brain/import`, `/api/brain/knowledge…`) still answer half of an emoji with a
    server error.
  - Docs: CLIPFORGE_AI.md (the brain file, whom a memory is for, the health check beside a memory for every
    video, the words an answer names, the step line, the plainly said rule that is already there, the Forget
    card's choice, the nested request), the handoff, and one sentence of the privacy page made exact: asked in one
    video's chat, "forget" leaves a note that another video keeps under the same words when the same words are
    also kept for this video or for more than one video (a platform's memory counts too).
  - Tests: `test_a_brain_file_adds_a_memory_for_every_video_beside_one_kept_for_one_video` (new),
    `test_a_memory_an_older_build_moved_is_listed_for_the_video_it_is_kept_for` (new) and
    `test_the_same_words_kept_for_two_videos_are_two_memories_everywhere` in `tests/test_clipforge_ai_brain.py`;
    `test_a_memory_an_older_build_moved_shows_in_the_chat_of_the_video_it_is_kept_for` (new),
    `test_another_videos_note_decides_nothing_about_the_same_words_said_here` (new),
    `test_here_and_for_this_video_keep_a_memory_to_the_video_and_leave_its_words_whole`,
    `test_the_same_words_said_in_two_videos_are_kept_for_each_of_them` and
    `test_half_an_emoji_in_a_message_or_a_memory_is_left_out` in `tests/test_clipforge_ai_chat.py`;
    `test_a_forget_card_for_a_part_of_the_words_is_about_a_memory_that_applies_here_first` (new),
    `test_a_rule_said_plainly_that_is_in_the_memory_but_not_in_force_is_shown` (new),
    `test_a_rule_the_model_forgot_to_save_is_kept_once`,
    `test_the_safety_net_waits_when_the_model_asks_or_a_helper_kept_it` and
    `test_the_remember_tool_keeps_words_that_point_at_this_video_for_this_video` in
    `tests/test_clipforge_ai_safety.py`;
    `test_with_a_model_scope_words_alone_name_nothing_and_a_which_one_button_needs_no_model`
    (`tests/test_clipforge_ai_assistant.py`); `test_a_memory_saved_again_for_another_project_stays`
    (`tests/test_studio_project_delete.py`). No frontend change.
- **A look at the scope round** (66509f1). Four reviewers were set on it. Two finished (the memories, the answers)
  with seven findings; the other two and every second reader ran out of usage, so I reproduced each finding
  myself before fixing it, and did by hand what the two missing reviewers were to read (below). Each code fix
  has a test that failed before it:
  - A backup of the brain could come back without one video's note. The round before lets the same words be kept
    for every video and for one video side by side. Read into another brain, the file's note for one video was
    skipped whenever a memory for every video said its words, also one that is switched off, only a guess or
    expired, and also one the file itself had just added, so the result depended on the order of the file. An
    unknown entry is now skipped only when a memory in that very place says its words (whatever the owner did
    with it), or one that is in force for every video and did not come with this same file
    (`memories._import_one`, `_in_force`). The same file read twice adds nothing the second time.
  - A file that changed a memory this brain has, and also brought a note which that memory's old words covered,
    dropped the note on the first read and added it on the second: entries were weighed in the file's order,
    before the file's own changes. The file's newer revisions of known memories are applied first
    (`memories.import_`).
  - A hand-made file with text where a number belongs was stored as it was. A date in `last_used_at` then made
    every search, recall and chat answer fail until that memory was removed by hand; the other number fields gave
    a server error with the file half read (both as released). Such an entry is counted as invalid and the rest
    of the file is read. Text that is a number is still read as one, and a revision or a use count stays within
    what the database can hold (`memories._number`, `MAX_COUNT`).
  - A memory's extra data nested 254 levels or more could be read and stored but not sent back, so the Memory
    page, the search and recall answered with a server error from then on (as released). A request to the
    Brain's addresses with lists and objects nested more than 100 deep is refused before anything is stored (422,
    "That is nested too deeply to read.", `routes.MAX_DEPTH`, `tools.clean`). A brain file has five levels.
  - With a model, "forget the caption rule" in one video's chat could show a card for another video's note.
    When no memory says or holds the words named, the card took the search's first match without a look at this
    chat's video, and of two that fit alike the newer. In a video's chat the card is now for a match that applies
    there when it holds a word named and at least as much of the words named as the other video's note, or fits
    exactly as well (`memories.closest`). A note of another video that holds more of the words named is still the
    one offered, since the owner named it, and a memory that shares no word with the request never comes first.
    The card says which video its memory is kept for, as before.
  - The newest memory that holds a card's words and applies in this video was looked for among the newest 500
    holders only, so 500 newer notes of other videos hid it. The ones the request is about are chosen before the
    cut (`memories.holding` with the chat's video).
  - The step line said "Remembered “…” for this video" without the reason. The reason, and how to keep the words
    for every video, were only in the tool's result, which nobody reads: a tool that keeps a memory gets no
    further round, so the model's own words ("Saved for all your videos.") were written before and stand. The
    step line now says it: "Remembered “…” for this video, because it says “here”", and for words that also
    speak of other videos or of later "… for this video only, because it says “this video” (to keep it for every
    video, say the video's name instead)" (`toolbox._keep`). The docs said the model passes it on; they now say
    who reads what.
  - What the two missing reviewers were to read. Who uses the changed code: the brain file is read by one
    address; `holding` and `clean` only gained an argument that the other callers leave out; the step line is
    shown as text by the page and read by no script, check or browser test. The docs against the code: the
    passages on the brain file, the step line, the Forget card and the nested request were each read beside the
    code they describe and rewritten where they differed. The privacy page says nothing about brain files or
    step lines, and what is stored, sent, kept and deleted did not change.
  - Tests that fail without a rule: 26 rules of this round were each taken out of a copy of the code and the brain and
    safety tests run against it. 23 failed a test at once. Three did not, and each got the test it lacked: a
    memory for every video whose time is over (the test's expired memory had also been a guess), a use count
    below zero, and a request of no words at all. All 26 fail a test now.
  - Known and left as they are: without a model, "forget the caption rule" in a video's chat lists both videos'
    notes, the newer first, without saying which video each is for (nothing goes before a pick, and the pick
    names its words); with a meaning model, a note of another video that is closer in meaning but names no more
    of the words comes second to one that applies in this video (the card names the video); a brain file's text
    that is a number or a list is kept as it is written; a memory that is no guess but has an expiry behind it
    (only a hand-made file makes one) still counts as "already in my memory" until Tidy removes it; a tool call
    with a wrong argument shows the tool's line with the argument's name ("Remembered “text”") beside the reason.
  - The real-model check on this round's code (3728222) passed on GitHub's Linux machine and failed on its Mac at
    the last step, the planner's note. That Mac has no graphics chip for the model and wrote about 2 tokens a
    second, so a note of full length (260 tokens, `agents.NOTE_TOKENS`) cannot be written in the 120 s the check
    gave it; the runs before passed with a shorter note or a little more speed. In the app the planner goes on
    without a note that did not come in time. The check (`scripts/assistant_check.py`, `slow_limits`) now gives a
    planner's note three times the time on GitHub's machines without a graphics chip (360 s), as it already gave
    every answer there (900 s instead of 300 s), and its report says so. No change to the app.
  - Docs: CLIPFORGE_AI.md (the brain file's rule and its numbers, the step line, who reads the tool's result, the
    Forget card's search, the nested request) and the handoff. No change to the privacy page.
  - Tests: `test_a_brain_file_brings_back_what_is_not_in_force_here_yet_in_either_order` (new),
    `test_a_brain_file_changes_the_memories_it_knows_before_it_adds_the_rest` (new),
    `test_a_brain_file_entry_with_a_value_that_is_no_number_is_left_out_and_the_rest_is_read` (new),
    `test_a_brain_file_nested_deeper_than_anything_real_is_refused_before_anything_is_stored` (new),
    `test_the_closest_memory_in_a_videos_chat_applies_there_unless_another_videos_note_names_more` (new) and
    `test_a_brain_file_adds_a_memory_for_every_video_beside_one_kept_for_one_video` in
    `tests/test_clipforge_ai_brain.py`;
    `test_a_forget_card_for_a_description_is_about_a_memory_that_applies_here_first` (new),
    `test_a_forget_card_looks_past_any_number_of_newer_notes_of_other_videos` (new),
    `test_the_step_line_says_why_a_memory_stays_with_this_video_whatever_the_model_wrote` (new),
    `test_the_remember_tool_keeps_words_that_point_at_this_video_for_this_video` and
    `test_a_rule_the_model_forgot_to_save_is_kept_once` in `tests/test_clipforge_ai_safety.py`;
    `test_githubs_machines_without_a_graphics_chip_get_three_times_the_time_for_a_note_too` (new) and
    `test_the_planner_note_gets_the_runs_time_and_is_judged_by_it` (new) in `tests/test_assistant_check.py`. No
    frontend change.
- **A last look at that round's fixes** (3728222). One reviewer read the round once: reviewers share this
  session's usage, and the round before ran out of it. Five findings, each reproduced before it was fixed, and a
  sixth that I found while reproducing the third. Each fix has a test that failed before it:
  - A brain file with its numbers as text (a converted file) switched a memory back on that the owner had
    switched off: `"enabled": "0"` was read as on, like any text. And a "0" where 0 stands for none, as in
    `expires_at`, became an end in 1970, so no answer followed that memory and Tidy removed it (both as
    released). `enabled` is now read like the other numbers: a number, or text that is one, and 0 is off; left
    out it is on, null and "" are off; anything else ("false", a list, a number that is not finite) makes the
    entry invalid. A "0" as text is none, as the number 0 is (`memories._on`, `import_`).
  - A backup could still come back without one video's note. The round before set aside only what the file
    itself added: when the file also brought the memory for every video up to date, or this brain had that
    memory as the file has it, the video's note counted as known and was skipped. And of two memories in the
    same place of which one is switched off (Tidy leaves such a pair alone), only the one listed first came
    back, so with the switched-off one first the rule was no longer in force. A memory the file lists under an
    id of its own never counts against another entry that has an id: the two were memories of their own where
    the file comes from (`listed` in `memories.import_` and `_import_one`). Entries without an id are told apart
    by their words as before, so a line a hand-made file repeats is added once, and what this brain kept before
    the file, under an id the file does not list, counts as it did.
  - Two ids of more than 40 characters with the same first 40 gave a server error with the file half read, at
    every try: an id was cut to 40 characters (as released), so the second was the first's. Reproducing it I
    found that an id with "/" in it, or of dots only, was stored as it was, and such a memory had no address: the
    Memory page could neither switch it off nor forget it. An id is now kept only when it can be one, at most 40
    letters, digits, "-" and "_", as the app's own are. With any other the entry is read as one without an id:
    it gets a new id and is told apart by its words (`memories._file_id`, `MAX_ID`).
  - A number that is not finite (1e999, NaN) in a memory's extra data was stored, and from then on the brain
    could not be exported (a server error) until that memory was forgotten. Such an entry is invalid, like one
    with no number where its own numbers belong, and the rest of the file is read (`memories._data`).
  - With a model, "forget the caption rule" in a video's chat could show a card for the log line of a change
    ClipForge AI made in that video ("Asked … → applied: …") instead of another video's rule, and OK would have
    removed the log line: the round before lets a match that applies in this video come first. What ClipForge AI
    only noted in a video (an episode, an asset, an answer) no longer comes before another video's rule or fact.
    A rule or a fact of this video still does, and so does this video's log line before another video's log
    line (`memories.closest`, `LASTING`). The next entry narrows this to a log line that holds no more of the
    words named.
  - Tests that fail without a rule: 32 rules of this round were each taken out of a copy of the code and the
    brain and safety tests run against it. 28 failed a test at once. Four did not, and each got the test it
    lacked: a note the file lists without an id before the newer words of a memory this brain has (only the
    order brings it in), an id of 41 characters, an id with a line end after it, and a hand-written line
    without an id beside a memory for every video that the file lists too (the last one in the commit after
    6145499, which changes tests only). The 26 of the round before were run again on this code, three of them
    with the text this round changed. Every one fails a test now.
  - These fixes rest on the tests written first, on the breakages above and on the full suites. The review
    they got afterwards is the next entry.
  - Docs: CLIPFORGE_AI.md (which of a brain file's memories count against each other, its ids, `enabled`, the
    extra data, the `forget` tool's search) and the handoff. No change to the privacy page: what is stored,
    sent, kept and deleted did not change.
  - Tests: `test_a_brain_file_with_its_numbers_as_text_keeps_a_switched_off_memory_off` (new),
    `test_the_memories_a_brain_file_lists_by_id_never_count_against_each_other` (new),
    `test_a_brain_file_id_that_cannot_be_one_is_read_as_no_id` (new),
    `test_a_brain_file_entry_whose_extra_data_holds_no_real_number_is_left_out` (new),
    `test_the_closest_memory_is_never_this_videos_log_line_before_what_the_owner_taught_another` (new) and
    `test_a_brain_file_changes_the_memories_it_knows_before_it_adds_the_rest` in
    `tests/test_clipforge_ai_brain.py`;
    `test_a_forget_card_for_a_description_is_about_a_memory_that_applies_here_first` in
    `tests/test_clipforge_ai_safety.py`. No frontend change.
- **A review of those fixes** (6145499 and 8a6cc21). Two reviewers were set on the two risky parts, reading a
  brain file back and the Forget card's search, and a second reader was to reproduce each finding. The session's
  usage ran out while they worked: the brain-file reviewer stopped before it reported, the Forget-card reviewer
  finished with three findings.
  - The Forget card's new rule went too far. Asked in a video's chat to forget a change ClipForge AI applied
    there, by words only that change's log line holds ("forget the captions size change you applied"), the card
    was for another video's rule ("no captions in the outro", for “Beach” only), and OK forgot that rule: a log
    line of this video never came before another video's rule or fact, however many more of the words named it
    held. Of 540 natural wordings of such a request 88 gave the other video's rule (none before that round),
    and with a caption rule for every video in the brain the card could be for that one, ranked third. What
    ClipForge AI only noted in a video now comes before another video's rule or fact when it holds more of the
    words named, and only then: with no more of them ("forget the caption rule") the card is still for what was
    taught (`memories.closest`). The second reader had called this documented behaviour. It forgot a rule nobody
    had named, so it is fixed.
  - Checked on the fixed code: none of the 540 wordings gives the other video's rule (the reviewer's own
    probes). Over 40,000 random cases of memories and scores the choice differs from the code before that round
    only where a log line of this video holds no more of the words named than another video's rule or fact, and
    from that round's code only where it holds more.
  - Left as it is (the third finding, also in the code before that round): the kind is looked at only in the
    search. When the words named are a whole part of both memories ("forget captions"), the card is for the
    newest memory that holds them and applies in this chat, which can be this video's log line
    (`memories.holding`). The card names it, and nothing goes without OK.
  - Reading a brain file back, checked by me in the reviewer's place. Its unfinished probes run to the end: a
    fuzzed file of 753 entries through the route, 3,735 cases of ids that another workspace holds, and about
    21,900 small brains and files in every order. They flag only what the docs describe (a memory in that very
    place makes an entry known whatever its state; entries without an id go by their words). A probe of my own
    compares every order of a file with a model written from the rules in the docs, not from the code: 15,212
    random brains and files as Export writes them (124,056 orders, each read twice), and 5,766 hand-made ones
    with ids taken off (47,590 orders) for the promises that hold for those too (a second read adds nothing,
    nothing is removed, a memory the file does not name is unchanged, nothing is followed where neither the
    brain nor the file had it). No difference. The same probe finds the fault the round fixed (a switched-off
    twin that did not come back) in the code before the round within seconds.
  - Known and left, each as released or for hand-made files only: an entry that names a memory this brain has,
    with a higher revision, is read as the whole memory, so one that leaves out where it applies or whether it
    is on makes it a memory for every video, switched on (a file Export writes carries every field). A memory
    in that very place makes an entry known whatever its state, also a guess or one that ran out, until Tidy
    removes it. Of two entries that say the same words in the same place, of which one has no id, the one
    listed first is kept.
  - Tests that fail without a rule: the new rule was broken 13 ways, each in a copy of the code. Every one
    fails a test.
  - No other reviewer read this fix: a third review would have spent the usage the checks need. It rests on
    the tests written first, the 13 breakages, the two comparisons above and the full suites.
  - Docs: CLIPFORGE_AI.md (the `forget` tool's search) and the handoff. No change to the privacy page: what is
    stored, sent, kept and deleted did not change.
  - Tests: `test_this_videos_log_line_comes_before_what_another_video_was_taught_only_with_more_of_the_words`
    (the round's `test_the_closest_memory_is_never_this_videos_log_line_before_what_the_owner_taught_another`
    under a new name, its "however many of the words it holds" turned around) and
    `test_a_change_named_by_words_only_its_log_line_holds_is_the_closest_memory_in_its_video` (new) in
    `tests/test_clipforge_ai_brain.py`; `test_a_forget_card_is_for_this_videos_log_line_when_the_words_name_it`
    (new: the chat, the card and its OK) and
    `test_a_forget_card_for_a_description_is_about_a_memory_that_applies_here_first` in
    `tests/test_clipforge_ai_safety.py`. No frontend change.
- **Not verified here:** the real built-in model's answers (the model hub is blocked from the cloud computer):
  the `assistant-check.yml` workflow runs them on GitHub's Linux and Mac machines with the Basic level; on the
  final code: run 43362758634 on dbdd78b passed on both machines with every must-check. Linux took about two
  minutes; the Mac wrote 3.1 tokens a second (11 turns in 272 s, the planner's note in 12.5 s). The small model
  missed the same four softer checks on both: it named none of the three projects, left two saves to ClipForge's
  own safety net, and answered for the Script writer instead of handing the job over. The Standard level (what a
  Mac with 16 GB of memory or more gets): run 43362792362 on dbdd78b passed on GitHub's Linux machine with every
  must-check (Gemma 4 E4B, 11 turns in 588 s at 7.5 tokens a second); one softer miss, a hook from the Script
  writer that did not say “mountain biking”. Pro (chosen by hand) was never run. Landry's own computer was not
  tested. Ollama, LM Studio and the online services were played by stand-ins.

## Leftover files and upload races after deleting projects — 2026-11-11 (Claude Code)

Follow-ups from the delete-projects review (PR #35), passed on by the coordinator. Branch
`claude/project-thread-h05xs8`, built on #35 and merged with the release line at bc7250f. No release.

- **Animated shorts** (`clipfoundry/makers/shorts.py`): every file a build stores is listed for its short (new table
  `short_files`). At the start and end of each build, a listed file that no scene, earlier picture, saved version or
  other project names any more goes (`_tidy_files`, `_drop`, `_named`, one step under the file's lock); deleting the
  short reaches every file on its list. A file just handed out again (`assets.reused_at`, an hour) is left alone. A
  thrown-away clip that cannot be deleted yet never fails its scene (the next tidy has it).
- **Local makers** (`makers/local_engines.py`, `pictures.py`, `voice.py`, `engines/makers.py`): the short takes the
  maker's original and its note out of `data/engines/made` (`maker.json` / `maker.<ext>` beside the picture or clip,
  voices under the short's `voice/maker/`), so they go with what the short made from them. A result that cannot be
  used or was made as Stop was pressed is deleted with its note (`discard_made`, only ever inside engines/made); a
  file ComfyUI hands back that is not a picture, or an empty video, is deleted. The delete window says which
  originals go and which stay in engines/made (`project_delete._maker_originals`).
- **Uploads** (`studio/uploads.py`): saves of the same bytes take turns (`_content_lock`); two identical files
  finishing together are stored once and both finish (no HTTP 500, no stray folder; 409 "try again" only when the
  stored copy was deleted in between). `complete()` answers with `upload_id`; the same file finished on two pages
  (both resumed one upload) gives the second page an upload row of its own (`_again`).
- **"Added again"**: pages send the uploads they used (`upload_ids` on Make a YouTube video, Add files, the editor's
  media, Make clips, the classic video request, a scene's own picture, an example video), every upload they made of
  the file: also one picked again, one dropped again after a change failed, and one that finished after another file
  was picked instead (`FileDrop` reports every finished upload, `onUploaded`; `useUploadsByFile`).
  `uploads.taken(ws, upload_ids, project_id, asset_ids)` marks exactly those (new column `uploads.taken`). Add from
  this computer leaves such an upload too (`uploads._hand_out`, one step with marking the copy; the link answer has
  `upload_id`), so links count like uploads. When deleting, a project that took uploads counts every other finished
  upload of the file in the day as another page's ("again", kept), also one made before the project. So does every
  project made since ClipForge records this (`db._migrate_uploads_taken` notes when, `project_delete._marked_since`),
  also one made from a file ClipForge got another way (a link, Find media), which owns no upload; a project made
  before keeps the older rules. A project's own later upload or link of a file ClipForge already had no longer keeps
  that file forever; choosing an earlier picture again takes no upload. A scene's picture is changed once per upload
  (a failed change is tried again when the picture is dropped again, never by the page on its own). On a draft, a
  file taken out stays out (also when an upload of it that began before finishes later, or when it came from the
  first page and was dropped again), and a copy of it picked after it was taken out (another name) brings it back.
- **Deleting** (`studio/project_delete.py`): inside its own step (`BEGIN IMMEDIATE`), nothing else can change the
  database, so it looks again at what names each file and at copies handed out since the window (`_handed_out`); those
  stay, and the answer is worked out again ("… stays in ClipForge because it was used again just now"). A video's bin
  names a file only while it exists, and before the page's upload is taken (`video_flow.add_media`).
- **Deleting an example's video file** (`studio/reference._drop_file`): the file stays when anything else names it
  (saved versions, shorts, imports; the delete's own check), when it was handed out again since the example was made,
  or when another page's upload or link of it that no project or example took finished in the last day (also before
  the example); the Examples page's own uploads are the example's (`upload_ids` on `POST /api/studio/references`). A
  copy handed out again since the example was made counts only within the hour and until its upload is recorded
  (uploads a project took never keep it). The check and the delete are one step.
- **Planning chat** (`brain/chat.open_chat(create=False)`, `studio/video_setup._think`): an answer for a video deleted
  while it is written stops and never makes a new, empty chat; a chat made just as its video is deleted goes again.
- **Docs:** `docs/clipforge/ANIMATED_SHORTS.md` (tidying, the makers' originals, a scene's own picture),
  `LOCAL_ENGINES.md` (refused files are deleted), `VIDEO_SETUP.md` (`upload_ids`, the chat lookup), `LONG_VIDEOS.md`
  (a link's `upload_id`).
- **Tests:** `tests/test_studio_uploads_taken.py` (new), `test_studio_shorts_tidy.py` (new), and new cases in
  `test_studio_uploads.py`, `test_studio_shorts_voice.py`, `test_local_engines.py`, `test_video_setup_flow.py`,
  `test_studio_project_delete.py`, `test_studio_local_files.py`, `test_studio_reference.py`. Each fix has a test that
  fails on the code before it. Six independent reviews; every confirmed finding fixed.
- **Checked in the real app** (browser, fresh data folder): Make clips with the same file picked twice, Make a YouTube
  video with two copies of one file and a picture, Add files on the draft (a file it has already, and a new one), the
  delete window's words, and one big file dropped on two pages at once (each page got its own upload; deleting the
  first page's video kept the file and the second page started its video). Then: Add from this computer on Make a
  YouTube video (the link is the video's), Make clips with a file replaced while it uploaded and picked again (both
  uploads sent and taken), an example video (its upload is the example's; deleting it with its file kept the file
  another page had uploaded), Add from this computer in the editor, and a draft's file taken out and then added
  again as a copy under another name (it came back, and its upload is the video's), a draft's file dropped again and
  then taken out (it stayed out), and a file picked again whose slow upload finished after it was taken out (it
  stayed out).
- **Known limits (keeping is the safe side):** projects and examples made before this change took no uploads; such
  a project keeps the older rules, and such an example's file stays when it is deleted within a day of its upload.
  A project made since then by something other than a page (an API call, ClipForge AI's tools) from a file the owner
  uploaded keeps that file for a day after its upload if deleted, as the upload was not sent with it. An upload a
  page started and then removed from its list counts as another page's for a day. The owner's own files are never
  touched.

## Deleting projects, with a confirmation that says what goes and what stays — 2026-11-10 (Claude Code)

Landry asked to be able to delete projects. Branch `claude/project-thread-8i3krg` from the release line at 95a70e0.
No release.

- **One delete for both kinds** (`clipfoundry/studio/project_delete.py`, new): `plan(ws, id, kind)` says in plain
  sentences what goes and what stays without changing anything; `delete(ws, id, kind, wait=)` does it in one
  transaction and returns the same sentences. Kinds: `clips` (Highlights and Full stories) and `full_video`. Used by
  the Projects page, a clips project's own page and ClipForge AI's delete tool (the assistant thread).
- **What goes:** the clips with their versions, scores, blueprints, analyses and suggested post text, the transcript
  windows, story proposals and link imports; or a video's edit history (every revision), previews and finished videos,
  change requests, media searches and imports, and an animated short's scenes; the project's folder; an upload copy or
  downloaded link that nothing else uses (another clips project, an example, any other video or any of its saved
  revisions), and for a file used where it is only what ClipForge made from it; the project's ClipForge AI chat and the
  memories that apply to it only; planned posts that have not started uploading (canceled, they stay in the history);
  its place on the pinned list.
- **What stays:** the owner's own files (never deleted, never made writable); media something else uses (kept, still
  read-only); anything posted (post history, results, the fingerprints that stop a clip being posted twice); memories
  for every video, a platform or a mode; the taste lessons; Autopilot's record of the video it found (its link to the
  project is cleared, so the Autopilot page no longer opens a missing project and the entry can be removed).
- **Waits instead of deleting** (409, code `blocked`, with the reason): Autopilot still working on the project, its
  clips or its source; a post uploading or being checked; a video still being copied in (status `uploading` and the
  folder changed in the last minute; a copy that stopped halfway can be deleted). Running work (making clips, renders,
  studio jobs, link downloads, media imports, preparing a file that goes) is canceled first; a delete request waits up
  to 10 s for it, else 409 `stopping`, and the window asks again for up to 90 s.
- **Routes:** `GET /api/projects/{id}/delete-plan`, `GET /api/studio/videos/{id}/delete-plan`,
  `DELETE /api/studio/videos/{id}` (new); `DELETE /api/projects/{id}` now runs the same code (before, it refused while
  clips were being made and left the upload copy, the chat and the project's memories behind). Both DELETEs take the
  plan's `as_of` (`?as_of=`), which the window sends back.
- **Screens:** `frontend/src/components/DeleteProject.tsx` and `.css` (new): a trash button on every Projects card (top
  left, the Pin button's twin; `LibraryCard` takes an optional `onDelete`, so the Studio page's cards have none) and one
  confirmation window ("Deleted for good" and "Stays" from the server, "This can't be undone", focus starts on "Keep
  it"; while blocked only "Check again" and "Close"). A clips project's own page uses the same window
  (`libParts.tsx` `DeleteProjectDialog`). `frontend/dist` rebuilt.
- **After a second review (same day):** work that was asked to stop but is still running (its row already says
  canceled) counts as running, so a second delete never deletes from under it; a step that ends while a delete waits
  and queues the next step has that one stopped too; a planned post that starts uploading between the check and the
  cancel stops the delete (409 `blocked`) instead of being ignored; a post whose publish step is already running
  blocks; memories go by their scope only (a memory saved again for another project keeps its first project_id); a
  file the owner uploaded again after the project was made, within the last day, stays (ClipForge keeps one copy per
  file, and a new page may be about to use it; counted from the project's `created_at`, which deleting's own stop
  cannot move, and the upload that first stored the file is the project's own); a clips project's own copy of its
  video (a live recording, a download) is named in what goes; folders with a file still open in another program (Windows) are listed in `data/delete-later.json` and
  deleted at the next start (`finish_later`, only ClipForge's own project, video, link and upload folders), and the
  answer says so (`left_behind`); both DELETE routes only answer ClipForge's own page on this computer (the
  `app_request` guard the Autopilot and memory routes have, in words about deleting). Window: it cannot be closed
  while a delete is on its way, a refusal shows at once in an announced area, a project already deleted elsewhere
  just closes it, it works in development mode (StrictMode), focus moves to the next card, and the page no longer
  saves its own pinned list (the server already unpinned it; `forgetPin` in `prefs.tsx`). The e2e library test
  follows the new window.
- **After a third, independent look at those fixes:** a writable file that cannot be deleted is in use even when it
  has a second link (a render reused after undo or restore), so its folder is listed for the next start; the
  start-up sweep knows ClipForge's own read-only upload copies (a leftover link to a copy another project still uses
  is removed and the copy is read-only again, instead of the folder being dropped from the list with the link still
  in it); the space freed counts a reused render once; "added again" no longer flips to "goes" when the delete's
  own stop changes the project; while deleting, the buttons keep keyboard focus inside the window (aria-disabled)
  and after a refusal focus moves to Close; a failed pin save that is retried no longer pins a deleted project.
- **After the animated shorts and story clips joined the release line (2026-11-10):** an animated short's scene
  files (each scene's picture, its earlier pictures and the scene's clip, also one not in the plan yet) go with
  it when nothing else uses them; a file another short's scene names, or any media import (also one made for no
  project), counts as a use and stays; the window names a short's build ("making the short"); one upload of a
  file ClipForge got another way (Find media, a link) counts as added again; and a window that lists more than
  four files says "and 2 more", not "and 2 mores". Story parts projects are clips projects and need nothing new.
- **After a last independent look on the combined code (2026-11-10):** a short's scene pictures and clips are not
  copies of anything and every remake has the same name, so the window counts them on their own line ("What
  ClipForge made for its scenes: 3 pictures and 3 clips."); a picture the owner chose for a scene, uploads, downloads
  and ClipForge's library sounds keep "ClipForge's copy of …". When the makers on this computer made a short's
  pictures, video clips or voices, the window says under Stays that their originals stay in engines/made with a note
  of the words (the makers keep everything they make; deleting does not reach that folder). "Added again" is decided
  by when an upload started: only one that started after ClipForge had the file counts, so a slow save or the same
  file dropped twice at once no longer keeps a project's own file (this replaces a 5-second guess). The plan answers
  with `as_of`, the window sends it with Delete, and the delete judges "added again" at that moment, so a file the
  window said stays is not deleted because the window stayed open past the day. Passed on to the shorts and upload
  code (not this change): scene files that no scene or saved version names any more (a replaced clip, a deleted
  scene's files) stay after the short is deleted; the makers' originals could be removed with the short; two
  identical files finishing their upload at the same moment give an error and leave a stray copy.
- **After one more independent look at those fixes (same day):** a short's files are also read from every saved
  version (a deleted scene's picture is counted as made, not named as a copy); the owner's own photo stays "ClipForge's
  copy of …" while a new picture waits to replace it (who made a scene's picture is its info.picture.source); the
  makers' line also shows after the voice or motion was switched, a scene was deleted or a build was stopped (saved
  versions and the short's voice notes); and "added again" also keeps a file when another page's upload of it started
  before the project was made and finished after it (the same file under two names), or when the file was dropped
  twice in the day (the project was made from one drop at most). Passed on: a project's own later upload of a file
  ClipForge already had counts as added again, so that file is left behind (needs a record of which project took an
  upload); the same file dropped on two pages at the very same moment shares one upload, so it can still go.
- **With Make a YouTube video's planning (PR #38, merged in):** a video being planned is a full video with status
  `draft`; deleting it stops the reading of its files, removes its planning chat with an answer still being written,
  and that answer finishing afterwards makes no chat or message again (a test drives the setup page's own `start`).
- **Docs:** `docs/legal/privacy.html` says what deleting a project removes and keeps (its ClipForge AI chat and
  notes, the copy of a file added again); `docs/clipforge/ROUTE_MAP.md` lists the routes and the trash button.
- **Tests:** `tests/test_studio_project_delete.py` (27 tests). Fast suite 1,978 passed, 2 skipped (1,969 before);
  slow suite 27 passed, 1 skipped (espeak-ng installed); a click-through of the real app in a browser
  (deleting a video, an Autopilot project that has to wait, a clips project from its own page, phone width)
  passed 18 of 18 checks. After the review fixes, on the code merged with the release line at e3ad759 (story
  clips): every test, fast and slow together, 2,064 passed and 3 skipped (two model folders and opentimelineio are
  not on this machine); one timing test (`test_an_nvenc_encode_waits_while_the_gpu_is_transcribing`, which gives a
  render 2.5 s to reach the GPU wait) failed once under load and passes on its own (3 of 3) and with its file; it
  does not touch deleting. `pytest -m slow` on its own: 29 passed, 1 skipped. The click-through passed 30 of 30
  checks (now also: focus after deleting, no pinned-list save, the window held open while deleting with focus inside
  it, a refusal shown at once with focus on Close), the window loads in development mode, and the two e2e delete
  tests pass against a seeded app (a deletable and a waiting project). After the
  last review's fixes (41d54e8): every test, fast and slow together, 2,233 passed and 3 skipped; the click-through
  passed 31 of 31 (now also: Delete sends the moment the window was judged); the two e2e delete tests pass. With
  the safety follow-ups (#41) and Make a YouTube video's planning (#38) merged in (2e63fef): every test, fast and
  slow together, 2,392 passed and 4 skipped (the fourth is a video-setup test that waits for the assistant's chat
  routes, PR #37); the click-through passed 31 of 31 and the two e2e delete tests pass.
- **Not verified:** a real Windows PC (the read-only and in-use file handling is simulated in tests); Landry's Mac.
- **Known limit:** a file used where it is ("Add from this computer") that is added again for a new page that has
  not saved it yet is not protected the way an upload is (adding it again leaves no record). Only what ClipForge made
  from it goes, never the owner's file; the file may then need to be added again on that page.

## Make a YouTube video: review fixes — 2026-11-10 (Claude Code)

Two reviews of PR #38 (branch `claude/project-thread-2wwa4c`) found misreadings and rough edges; all fixed with a
test for each (each new test failed on the code before its fix). No release. Details:
[docs/clipforge/VIDEO_SETUP.md](docs/clipforge/VIDEO_SETUP.md).

- **The built-in rules** (`studio/video_setup.py`, the reading part rewritten in the second review): a no only when it
  says no to the thing ("I don't want captions", "skip the captions", "not a TikTok"; not "Grandma can't hear well
  and needs captions", "don't make the captions too big", "no music during the vows", "I hate when videos don't have
  captions"; "don't lose the captions" is a yes); keep and cut only when asked for, in everyday ways ("I'd like you
  to cut…", "can we cut…", "could we keep…"), turned round by "don't"/"never" and let go by "you don't have to"; the
  video's length, not the footage's, a part's or a cut's ("my footage is 2 hours, make it 15" is 15 minutes; "the
  intro should be about 30 seconds" is none), said in everyday ways ("10 minutes is good", "Length: 10 minutes", "not
  longer than 10 minutes"), the last one said winning; "as long as it needs" is its own choice (`NO_LENGTH` = -1),
  "as long as you like it" is not; editing off only for the whole video; shape words only about the video ("vertical
  works best", "make a reel"); titles as typed ("Let's call it Mom's 60th"), none from "call it a day"; stories
  whose steps are things that happen; a named sound takes the role its sentence gives it. A long odd message is read
  in well under a second (at most 16 words in front of a keep or cut are read).
- **Merging**: each answer reads every message since the last one an answer merged, so what a stopped message said
  counts with the next; with a model its reading wins and the rules fill what it did not use; a part said in a
  message merged before, or set by hand, changes only when a later message talks about it, compared per part with
  when the hand edit was made (`locked_at`); a quick answer talks about what its question asked (`data.about`);
  files put in order by hand hold that order against an answer written meanwhile. Without a model only those
  messages are read, so a kept or cut item taken out by hand stays out.
- **Stop and Build**: an answer that arrives after Stop changes nothing (taken in under the lock, only while still
  "thinking"); a request not yet sent when Stop or a canceled build comes is never sent; three answers at a time;
  Build after a stopped first answer reads everything said (a part set by hand after the last message about it
  stays, in the build job's plan too) and plans in the build job; a build-time request that runs too long is given
  up (told to stop through the assistant's `llm.converse`; through `llm.complete` it runs to its end and is
  dropped); every online request that went out counts toward the daily limit, also a failed or canceled one.
- **After the build** (`change_plan`, `video_flow.smart_job`, `_jump`): only the brief fields the change moved are
  set (editor choices and `ai_edit` stay); the plan's music and voiceovers carry `"brief": true` (planned videos
  only) and are placed again from the plan, while a sound moved, changed or made quieter by hand stays yours, one you
  placed yourself is never placed twice, and your own song keeps the plan's music; a new order is the bin's order;
  the look is compared with the current version; Undo/redo/going back bring back the plan each version was made
  with (`setup.plans`), the brief values it was made with (`setup.made`), the guidance made from them and the file
  order, and drop a plan change still waiting; a plan change whose edit fails or is canceled before it starts
  (`@on_stop("video_smart")`) puts back the plan, brief, guidance, name and order. `smart_edit.plan_words` is empty
  for videos made without a plan, and their sounds stay as you left them.
- **Inputs and privacy**: `asset_ids`, `remember` and file numbers are checked (422, not 500); the listening job is
  keyed by the set of files (`video_flow.bin_key`); what is sent now names the Brain rules, the memories, the plan so
  far, know-how and helper notes (`_sent`, the page's model line, `docs/legal/privacy.html`); planning never sends
  Brain notes to NVIDIA, whose agreement says they are never sent (`brain_allowed`; NVIDIA's privacy row and
  `nvidia.data_note` now name what planning sends).
- **The pages**: the plan form saves only what you changed since it opened; Length is From your style / As long as it
  needs / About… (choosing About… moves focus to Minutes; opening the form no longer does); the music file is never
  also a voiceover; Back from the editor skips the planning page (`router.redirect`); Build my video and Just do it
  wait for uploads, and words typed but not sent are asked about first; leaving names what would be lost in one
  sentence (`LeaveGuard.say`), and an open plan form counts only when changed; a file taken out stays out, also one
  picked again while it was in the video, and one taken out while uploading leaves no Resume row
  (`Picked.forget`); added files keep the order you dropped them in; only the words sent leave the message box;
  focus returns after a quick answer, Save or Cancel; Stop shows Stopping…; the editor's plan says what an empty
  plan means (and "Nothing decided yet" while it still plans) and hides Supporting media.
- **Checks**: `tests/test_video_setup.py`, `tests/test_video_setup_flow.py` (new tests for each fix),
  `e2e/sandbox/video-setup.spec.ts` (Back after Build; words not sent and form changes asked about);
  `frontend/dist` rebuilt.

## Make a YouTube video: drop in your files, tell ClipForge AI your idea, plan it together — 2026-11-08 (Claude Code)

Landry asked for the YouTube video setup to work like this: drop in your stuff, tell the AI your idea and plan, and it
can ask questions or not. Branch `claude/project-thread-2wwa4c` from the release line at 95a70e0. No release. Design,
bounds and routes: [docs/clipforge/VIDEO_SETUP.md](docs/clipforge/VIDEO_SETUP.md).

- **The start page** (`frontend/src/pages/MakeVideo.tsx`, rewritten; `#/create/video`, `?idea=` fills the box):
  your videos, pictures and sounds in one drop and in play order, your idea in your own words (4,000 characters),
  "Ask me questions" or "Just do it" (remembered: `video_setup_mode` in `prefs.py`, `prefs.tsx`, `Customize.tsx`),
  and More choices (style and example, remember the look, your script, the name).
- **The planning page** (`#/create/video/<id>`): the conversation with ClipForge AI (quick answers, "Just do it",
  Stop, notes from your helper agents), the plan as a slate whose changed lines light up
  (`components/VideoPlan.tsx`: `PlanSheet`, `PlanForm`, `useChanged`; `videoSetup.css`), your files with what was
  heard in each, adding more files, and Build my video. A video being planned is a draft project
  (`studio_projects.status = "draft"` with a `setup`, new column in `db.py`; `video_setup.is_draft`, so an animated
  short stopped before its first version keeps its own page and chat); Projects lists it and opens it here, and
  `#/video/<id>` sends it here (`planning` in the video view; `VideoReview.tsx`, `router.ts`, `App.tsx`).
- **The planner** (`clipfoundry/studio/video_setup.py`, new): built-in rules for lengths, shapes, feel, how much to
  edit, music, captions, keep and cut, openings, stories, audiences and video types; with a model, one bounded text
  request (files, what is said in them, memories, know-how, helper notes, the conversation, the plan) answered as
  `{"say", "questions", "plan"}` inside a JSON schema and checked field by field; questions at most 3 at a time and
  2 rounds, a quick answer keeps the others, typing drops them; merging keeps explicit words and hand edits; the
  online daily limit and "what was sent where" like the chat.
- **The plan drives the edit**: `plan_to_brief` fills the brief (length, shape, feel, editing, captions, music, keep,
  cut, the opening); `video_flow.py` gains `open_with` and `plan` brief fields and plans inside the build job when
  "Just do it" had no plan yet; `ai_editor.py` starts every window with the owner's plan (700 characters);
  `smart_edit.py` opens with the sentence that matches the asked opening and ranks passages that match the plan
  higher when fitting to length; the plan's file order sets the bin's order.
- **After the build**: "Your plan" on the editor page; `PUT /api/studio/videos/{id}/plan` edits again as a new
  version that Undo takes back.
- **Routes** (`studio/routes.py`): `POST /api/studio/videos/setup`, `GET|PATCH /api/studio/videos/{id}/setup`,
  `POST .../setup/say|stop|build`, `PUT .../plan`, `GET /api/studio/video-setup/model`; the old one-step
  `POST /api/studio/videos` is unchanged.
- **With the assistant (PR #37)**: a draft's chat answers through `chat.route` in the chat's own message shape, the
  `make_youtube_video` tool shows a button to this page, helper agents' notes come from `agents.consult`; each part
  is optional, so either PR can merge first.
- **Checks**: `tests/test_video_setup.py`, `tests/test_video_setup_flow.py`; `e2e/sandbox/video-setup.spec.ts` walks
  the whole flow in the sandbox (and at phone width); `frontend/dist` rebuilt.

## Safety follow-ups: the built-in AI's engine outlives a request's thread; other computers' addresses are never looked at — 2026-11-10 (Claude Code)

Branch `claude/project-thread-3rqurx` from the release line at ff890b6, PR #41. The two follow-ups the PR #39 review
found outside the engines, plus the same gap wherever a sweep of the whole app found it. Merged on Landry's standing
OK to merge finished work; no release.

- **The built-in AI's engine (llama-server) on Linux** was told to stop when its parent ends, and Linux counts the
  *thread* that started it as its parent: started from a request's worker thread (which retires after about ten idle
  seconds) or a job thread, it stopped with that thread, so the next answer loaded the model again.
  `builtin_ai._popen` now starts it from one lasting thread (the same code as PR #37, so that branch merges cleanly),
  and ComfyUI uses the same starter instead of its own. It still ends when ClipForge ends.
- **Other computers' addresses:** on Windows, merely looking at `\\server\share\x` or `//server/share/x` connects to
  that server and signs in as the person (their password hash goes with it). Any web page can make the browser ask
  ClipForge's address for something, a FilmCraft project can carry any text, and the AI's FilmCraft steps can be
  steered by words in a video. Now refused before anything looks at the file system:
  - `GET /craft/filmcraft/<file>` (FilmCraft's editor) and the app page's catch-all route: only plain folder and
    file names (`clipfoundry/pathguard.py`, shared with made files);
  - `GET /api/local/browse` and linking a file (`local_files.other_computer`): another computer is refused from the
    text alone; a share the owner listed in `CLIPFOUNDRY_LOCAL_ROOTS`, or a mapped drive, still works;
  - FilmCraft's editor looked up every text in a project as a possible file: another computer's address is no longer
    looked up (the video's own files on an allowed share or in a data folder on a share still are); a saved project
    naming `\/server/share`, a path starting with a backslash, or climbing with `..` is refused, so FilmCraft's render
    never opens it; the AI's finishing steps refuse a leading backslash too.
- **How it was found and checked:** a sweep of the whole app for both problems (five areas, then a skeptic per
  finding: six network-path cases confirmed, no other thread-bound child process), then an independent review of the
  change (three lenses, a skeptic per finding), which found one regression (the video's own files on an allowed share
  were skipped in FilmCraft's editor), fixed with a test. Every fix has a test that failed first and records each
  file-system call: `tests/test_builtin_ai_lifetime.py`, `tests/test_network_paths.py`, `tests/test_pathguard.py`,
  the last test of `tests/test_craft.py`.
- **Checks:** on the final code (b65d795) the full fast suite 2271 passed, 2 skipped, and `pytest -m slow` 30 passed,
  1 skipped (on b830fdf: 2268 and 30). On GitHub's machines, on b65d795: the FilmCraft check with the real FilmCraft
  and built-in AI (run 42783880588, macOS 15 + Ubuntu), the built-in AI check with the real engine (run 42783952354,
  Ubuntu, macOS 15, Windows) and the Local makers check starting the real ComfyUI through the shared starter (run
  42783957349, Mac, Windows, Linux) all passed.
- **Not verified:** a real Windows computer (Windows path rules were checked with PureWindowsPath and by recording
  file-system calls; no SMB server was contacted), a real FilmCraft project with footage on a NAS, the real
  llama-server (the stand-in engine was used).
- **Follow-up (not fixed here, different fix):** FFmpeg reads a downloaded "video" that is really a DASH manifest
  (`<MPD>` in a file named .mp4) and opens the files it names (checked with ffprobe 6.1 here), so on Windows a
  manifest naming `file:////server/share/v.mp4` would make ffprobe contact that server. The fix is a demuxer
  allow-list (`-format_whitelist`) on every FFmpeg input of media from outside, as `knowledge.probe_example` already
  does; it needs care so no supported format is refused, and real-media checks.

## Local makers: the final review's fixes, combined with story clips and animated shorts — 2026-11-10 (Claude Code)

PR #39 (branch `claude/project-thread-nnvh05`) took in the release line twice before merging: PR #40 (story clips,
merge 850adf0) and PR #36 (animated shorts, merge aff2a0e; `api.py` keeps both routers, `frontend/dist` rebuilt from
the combined code). Merged into the release line on Landry's standing OK to merge finished work. No release.

- **The shorts maker against the real door:** two tests in `tests/test_local_engines.py` run
  `clipfoundry/makers/local_engines.py` against `clipfoundry.engines` (cards before set-up, an engine picture made
  into a still clip, Stop, the built-in voice and its "machine-generated" rule); the shorts test of the set-up note
  checks both notes (with and without the engines package).
- **Fixed after the final review** (lifecycle, platforms and the newest code; a skeptic per finding; each fix with a
  test that failed first):
  - on Linux the parent-death signal follows the *thread* that started ComfyUI, so a ComfyUI started from a picture
    job's thread stopped when that job ended: it is now started from one lasting thread, and still ends with
    ClipForge; on Windows ComfyUI's set-up (uv) runs inside ClipForge's kill-on-close job too;
  - Stop works while ComfyUI is starting (the half-started ComfyUI is stopped), a picture stopped while ComfyUI is
    being reached is never sent, and closing ClipForge stops a set-up under way first;
  - a ComfyUI another ClipForge process started is asked to hand its graphics memory back, and heavy work asks before
    it waits for graphics memory;
  - `GET /api/engines/made/<file>` refuses anything but plain folder and file names before looking at a file (on
    Windows, looking at `\\server\share\x` connects and signs in to that server as the person);
  - deleting ComfyUI's folders uses Windows long paths, and Remove says so when files could not be deleted;
  - set-up checks for twice the packages' space (uv unpacks into its cache, then copies) and deletes uv's cache
    afterwards; `uv venv --clear --force` replaces whatever an earlier environment left; ComfyUI counts as set up
    only while the Python named in its `pyvenv.cfg` is still there (a moved ClipForge folder is set up again);
  - the process list is read as UTF-8 on Windows (PowerShell is told to write it) and on the Mac (ps in a UTF-8
    locale): a ClipForge folder under `C:\Users\José` was never recognised, and under `C:\Users\Müller` reading the
    list failed;
  - a stopped download of the shared text encoder stays with the model whose download it was (another model showed
    "Partly downloaded" and its Remove deleted it); Remove of only a stopped download says so, says that a model
    ClipForge did not download stays ready, and no longer makes the ComfyUI app unload its models.
- **Checks:** `tests/test_local_engines.py` 79 passed; on 19dfe77 the full fast suite (2179 passed, 2 skipped) and
  `pytest -m slow` (30 passed, 1 skipped); the Local makers check (now also reading a folder named with é, ü and 東
  back from each computer's process list, and failing if set-up leaves uv's cache) passed on GitHub's Mac, Windows
  and Linux on d2a8e21 (run 42749843276; Linux made its real FLUX.2 klein picture in about 4 minutes). The first run
  (42749458528, on 19dfe77) failed only on Windows, in the check's own log line: the folder was read back correctly,
  but printing 東 to a code-page-1252 console failed; the check now writes UTF-8.
- **Not verified** (needs Landry's computer): as before, Metal speed and memory, a real Wan clip, Windows with an
  NVIDIA card, the ComfyUI desktop app, and the shorts maker end to end with real engines.
- **Follow-ups outside the engines:** `clipfoundry/builtin_ai.py` starts llama-server with the same Linux
  parent-death signal from whichever thread asks; `clipfoundry/craft/routes.py` resolves a requested path before
  checking it (the Windows network-share risk fixed here for made files).

## Local makers: pictures, video and voice made on this computer — 2026-11-08 (Claude Code)

Landry asked (Nov 7) to look at seven open-source projects he found (FreeVideo, WanGP, ComfyUI Desktop, InvokeAI,
OpenHiggsfield, VoiceStudio, Tencent WeKnora), plug the useful ones into ClipForge, and keep everything local on his
Apple silicon Mac and on Windows. Branch `claude/project-thread-nnvh05` from the release line at 95a70e0; PR #39,
merged on Nov 10 after PR #40 and PR #36 (Landry's standing OK to merge finished work; see the entry above). No
release.
Design, every choice and the research: [docs/clipforge/LOCAL_ENGINES.md](docs/clipforge/LOCAL_ENGINES.md).

- **The door** (`clipfoundry/engines/__init__.py`, new package): `make_image`, `make_video`, `speak`, `voices`,
  `status`, with `progress(fraction, message)` / `cancel()` and one `EngineError` whose message is written for the
  person. The animated-shorts maker (its own thread) and ClipForge AI call only this. What is made goes to
  `data/engines/made/<kind>/<day>/` with a `.json` note (model, licence, words, seed, time).
- **ComfyUI as the picture and video engine** (`comfy_server.py`, `comfy.py`, `graphs.py`, `makers.py`, `models.py`):
  GPL-3.0, so always a separate program over HTTP on 127.0.0.1, never imported. Either ClipForge's own copy (one
  button: uv 0.13.7 from PyPI, a private Python 3.12, PyTorch 2.14.1 for Metal / CUDA 13.0 with driver ≥ 580 / the
  processor, ComfyUI 0.43.0 from GitHub's archive of the tag, its packages as of Nov 7 via `--exclude-newer`), started
  on demand with `--offline --disable-all-custom-nodes`, stopped after 10 idle minutes, shared between ClipForge
  processes; or the ComfyUI desktop app found on 127.0.0.1:8000 / :8188. The graphs are ComfyUI's official examples.
- **Models, all Apache-2.0, full precision** (fp8/int8 do not run on Metal): FLUX.2 klein 4B (recommended on 16 GB
  Macs and 8 GB NVIDIA cards), Z-Image Turbo (best detail and lettering), Wan 2.2 TI2V 5B (clips up to 5 s from words
  or a picture). Comfy-Org repositories pinned to commits; the shared Qwen3 4B text encoder is downloaded once.
  `makers.machine()/fit()/ranked()` recommend the one that suits the computer; Settings says when one will be slow.
- **The voice** (`voice.py`): Supertonic 3 (OpenRAIL-M; what it makes must be disclosed as machine-generated, so
  the rule asks for a "Voice is AI-generated" line in the caption) on the processor through ONNX Runtime, ClipForge's
  own code checked against Supertone's reference; 10 voices, 31 languages, sentence chunks, estimated word timings,
  WAV out.
- **Use rules agreed before a download** (`catalog.Model.rule`): Supertonic's OpenRAIL-M rules and the request on Wan's
  model card are shown in the download dialog, whose button reads "Agree and download"; `setup()` and
  `POST /api/engines/setup` refuse such a model without `agreed: true`; every picture, clip and voice note carries
  the rule.
- **Downloads** (`catalog.py`, `files.py`, `tasks.py`): every file pinned by address, size and SHA-256; resumable,
  free-space check, safe unpacking, one set-up at a time with Cancel; a model file ClipForge did not download is never
  replaced (same or different size).
- **Settings → Pictures, video, voice** (`routes.py`, `frontend/src/components/LocalMakers.tsx`, `studio.ts`): what is
  ready and why not, the three ComfyUI choices, set-up, each model with licence, size, memory and fit, Download / Use
  this / Remove (shown only when ClipForge downloaded the files there), a quick try for each part, the voice's licence
  rule. `frontend/dist` rebuilt. Not offered online (routes answer 404 in cloud mode).
- **Fixed after a code review (Nov 8, a test written first for each):** a ComfyUI app's model in a subfolder is sent
  by the name ComfyUI lists; Remove deletes only ClipForge's own downloads in the ComfyUI in use, keeps the shared text
  encoder while the other model has its files, refuses while a picture is being made, and lets ComfyUI release the
  files first (Windows); each job saves under its own name (the same request twice failed on ComfyUI's cache); uv's
  Python stays out of `~/.local/bin` and the Windows registry (`--no-bin --no-registry`, and the machine check fails
  if not); the venv's seed packages and PyTorch's dependencies are bounded by the checked day too (PyTorch installed
  alone with `--no-deps`); a complete `.part` file is finished instead of failing on HTTP 416, a refused range starts
  over once, the final rename retries on Windows; progress never goes backwards; Stop and time-outs wait until ComfyUI
  has let go of the graph; clearer words for a too-old ComfyUI and a missing model file.
- **Fixed after a second review (Nov 8, a test written first for each):** Remove keeps the shared text encoder only
  for a model that is complete or that ClipForge was part way through downloading (a file of the person's own with the
  same name as one of the other model's files, such as FLUX.1's `ae.safetensors`, made it keep 8 GB for a model that
  was not there, which nothing could remove afterwards), and says what it kept; a stopped download can be removed
  (the row says "Partly downloaded"); a picture or clip job now counts from starting ComfyUI to saving its file
  (`comfy_server.job()`), and Remove (`removing()`) is refused meanwhile and holds new jobs back while it runs, so it
  can no longer stop the ComfyUI a job is starting; ComfyUI 0.43's own model loader (used on NVIDIA cards) has its
  damaged-file words turned into plain words too. Found while checking those fixes: a `.part` file counts as
  ClipForge's in the app's folders only when ClipForge recorded it before its download started (another program's
  half-downloaded file of the same name was offered for removal), and Remove asks a ComfyUI that another ClipForge
  process started and shares to unload its models (`Server.release_files()`), since stopping it is not this
  process's to do and Windows would otherwise refuse the delete; removing ComfyUI itself is refused while such a
  process runs it (it deleted the program from under it).
- **Skipped, with reasons** (details in the design doc): FreeVideo (its MiniMax H3 model's licence excludes the
  United States); WanGP (custom licence needs a paid deal to ship inside a sold app; Wan 2.2 already runs through
  ComfyUI); InvokeAI (the same models already run through ComfyUI); OpenHiggsfield (only a page for a paid online
  service, and its code has no licence; the zip was unpacked apart and only read); WeKnora (a team-sized server
  needing several extra programs; a small passage search in the Brain is a follow-up); VoiceStudio kept for later
  (its default voice model is non-commercial and the app is heavy; it could add a creator's own cloned voice).
- **Checks:** `tests/test_local_engines.py` (60, a stand-in ComfyUI and a local file server, each test with its own
  data folder; `tests/conftest.py` stops any test from downloading); the full fast suite (2029 passed, 2 skipped) and
  `pytest -m slow` (27 passed, 1 skipped), both on 53dd380;
  `.github/workflows/local-engines-check.yml` + `scripts/local_engines_check.py` on GitHub's Mac, Windows and Linux
  machines: every pin compared with its source, ComfyUI set up from nothing and started, a model-free PNG and H.264
  clip, every graph accepted by the real ComfyUI, the voice (two voices, every word in order, 1.8–3.5× real time),
  and on Linux a real FLUX.2 klein picture on the processor (about 3 minutes once downloaded); all passed again on
  53dd380 (run 42704530253). The Settings page was checked in a browser at desktop and phone sizes, again on the
  final code (download dialogs, a stopped download shown as "Partly downloaded" and removed). Found and fixed by the machine check: ComfyUI exits at once (code 2) when its
  `--user-directory` does not exist yet.
- **Not verified** (needs Landry's computer): Metal speed and memory on a 16 GB and a larger Mac, a real Wan clip,
  Windows with an NVIDIA card, the ComfyUI desktop app, the shorts maker end to end with real engines.

## Animated shorts: undo keeps the scenes, Stop always frees a short, and the review's fixes — 2026-11-09 (Claude Code)

A full review of the shorts branch found one critical problem and about forty smaller ones; all are fixed on the
same branch (`claude/project-thread-5qybvh`, draft PR #36). No release.

- **Undo, redo and restore keep the scenes in step** (`makers/shorts.py`, `studio/video_flow.py`): each version of
  a short's plan keeps its scenes as they made its clips and the short's choices (`plan.short.rows`, `.options`);
  going back puts them back in the same database step that saves the version (`save_revision(..., also=...)`, one
  `BEGIN IMMEDIATE` transaction, which also turns two saves at the same moment into a Conflict). Before, the next
  build made the undone scenes again. A change still waiting stays and is made on top.
- **Stopping** (`studio/jobs.py`, `jobs.py`, `studio/routes.py`): studio jobs have stop hooks (`on_stop`); Stop all
  jobs cancels the running studio job too; a build given up after three interruptions says so and offers Try again;
  Stop frees a short whose build was lost. Ready, failed and stopped are written only when no newer build was asked
  for, and an overtaken build saves no version.
- **The script check is never skipped** after a writer that failed or was stopped; picture ideas from ClipForge AI
  never overwrite what the owner typed meanwhile; a scene another voice had to read gets Try again (and Make the
  short asks the chosen voice again); errors reach the owner in plain words (the cause goes to the log); the robot
  office names the job "Making the animated short".
- **The editor's changes:** fades that no longer fit a shorter clip are shortened in proportion; a whoosh the owner
  muted, changed or removed is never put back; sounds and pictures attached to a deleted scene are named in a note; a
  scene added after a clip the owner replaced goes after it; the Scenes panel's length is the video's.
- **Voices** (`makers/voice.py`): the engine's multilingual voices count for "Best voice"; brackets are broken up
  for `say` and espeak-ng; a failed voice listing is asked again after half a minute; the Settings hint appears only
  where Settings has the voice engine; the speech model is released whenever it was asked; Hear it never keeps a
  stand-in voice's sample (one file per request, the page says another voice read it).
- **Pictures** (`motion.py`, `pictures.py`, `cards.py`): pictures read with Pillow (see-through ones on the look's
  colour, big JPEGs decoded smaller, huge ones refused plainly); an engine picture that does not open becomes a card
  with the reason; a long word on a card gets smaller letters; New picture on a card moves its shapes; a clip thrown
  away mid-build is deleted when nothing uses it; leftovers of a closed app are tidied after an hour.
- **Pages:** Draw real pictures when a picture maker is set up after cards were made; the Make page says when
  ClipForge AI (and which one) suggests the pictures for a pasted script; no old failure banner over a ready short;
  the projects list reads each short's cover from the short, not from its plan.
- **Tests:** new `tests/test_studio_shorts_undo.py` (8), `_stops.py` (14), `_edits.py` (5); more in `_flow.py`,
  `_parts.py` (16) and `_voice.py` (22).

## Story clips: Full story, Story parts, five minutes at most, a still picture — 2026-11-09 (Claude Code)

Landry's videos: a creator reads Reddit posts aloud while he plays a game. He asked for story clips that keep the
picture still and centred and show as much gameplay as possible without distorting it; two settings, "Full story"
(one clip per story; the finder kept splitting stories) and "Story parts" (each story cut at its best places into
separate parts); and no story clip over five minutes, a longer story split no matter what. Branch
`claude/project-thread-6ouxbx` restarted from the release line at 95a70e0; draft PR into `claude/project-thread-x72wkd`.
No release. Design, rules and numbers: [docs/clipforge/STORY_CLIPS.md](docs/clipforge/STORY_CLIPS.md).

- **Stories no longer split** (`pipeline/stories.py`): pauses count relative to the narrator (`story_parts.rhythm`,
  `pause_weight`: a break only at 2.5 × the median pause and the 97th percentile, partly from the 90th); a boundary
  needs words (a strong announcement, an intro/sponsor/outro run starting or ending, a post's title read out where
  the subject changes, a story's first words or a post's title after a pause long for this narrator with a change of
  subject or after a pause far longer than any inside a story, a closing line then an opener, or a long break with a
  change of subject measured by the meaning model); intro/outro wording counts only in the first and last 12 % (at
  least 90 s); ClipForge AI's checks are held to the same cues, and when the narrator announces his stories only
  announced places and post titles where the subject changes are offered; a boundary only the model's word put there
  is dropped when it would leave a piece under 40 s (`_drop_fragments`). On 40 synthetic recordings of a gamer
  reading four posts (`tests/story_fixtures.gamer_reader`, seeds 1–40) the release line made 9 to 21 clips (15.1 on
  average); this branch makes exactly 4, each starting within 1 s of the labelled start; with a model that answers
  "new story" to everything, 4 on 30 of 30. On 423 situations written for the review (sponsor reads, intros and
  outros, posts read title-first, narrators who pause before each post, a text-to-speech reader, model mistakes, a
  worst case with long pauses inside posts) it finds every story; the release line finds 160.
- **Story parts** (`pipeline/story_parts.py`, new): part counts (`max(ceil(D/299.5), ceil(D/175), round(D/110))`,
  lowered while a part would be under 62 s; under about two minutes a story stays whole; in Full story a story of 5:00
  or less is one clip); cut places between sentences scored
  by what makes a good stop (the poster's update +0.45, a jump in time +0.35, right before a reveal +0.3, a line that
  leaves you hanging +0.3, a question or exclamation +0.12, a change of scene +0.12, a pause long for this narrator up
  to +0.25; a cut before "And/Because/Which…" or after an unfinished sentence −0.3); a dynamic programme with a cost
  for uneven parts and for parts outside 62–175 s, looking only at cut places that can lead to parts under the cap (an
  hour-long story plans in well under a second); when no set of sentence boundaries fits, Full story first tries one
  part more and Story parts fewer, longer parts, and only then is a part cut at the longest pause between two words or
  inside a long stretch without talking, never inside a word, and never leaving a part under a minute of silence in
  Story parts; ClipForge AI may choose among the four best places (`stories.Judge.choose_cut`, at most a quarter of the
  stories budget), used only when every part still fits.
- **Two settings** (`studio/clips_flow.py`, `link_import.py`, `prefs.py`, `routes.py`): the request mode `story_parts`
  makes a Full stories project with `options.story_split = "parts"` (`"whole"` otherwise and for older projects); the
  guidance preview, the link import and the remembered choice accept it.
- **Parts are stories of their own** (`studio/story_review.py`; `db.py` columns `part`, `parts`, `story_key`):
  `plan_parts`, titles "… (Part N)", the hook "Part N" shown for the whole clip (and still after a trim in the clip
  editor, unless the owner set its seconds), reasons "Part 2 of 3: starts …";
  *Split in the middle* and *Merge* number the parts again (`_renumber`).
- **Five minutes at most** (`story_parts.MAX_CLIP_S` 300, parts planned at most 299.5 s): in `plan_parts`; `capped`
  splits an older or hand-set story when its clip is made; *Start earlier*, *End later* and *Merge* refuse a longer
  story with the length in words; `PATCH /api/clips/{id}` refuses a trim that makes a story clip longer than five
  minutes (other edits to an older, longer clip still work), and a start or end that is not a time in seconds ("NaN",
  infinity) for any clip; the Stories card disables those buttons with the reason.
- **A still picture** (`story_review.story_edit`, `studio/guidance.py`): story clips start with `fit`, `center`, zoom 1
  and no push-in; only a framing chosen for the project (Customize, or its example video) changes that, not the app's
  settings, a style, a skill, a shared example or a Brain note (`guidance.story_framing`); a subject to follow chosen
  for the project with no framing gets the vertical frame. Captions go just above the fitted picture
  (`pipeline/captions.py` `above_picture`, `render.py` passes the picture's top edge, `blueprint.POSITIONS` accepts
  `"above"`), unless any level chose a caption position, and fall back to the lower third when there is no room; the
  room is measured with libass (two lines reach twice the font size; the "Part N" box ends 1.25 font sizes under its
  top), and captions at the top go under the headline while it shows (`hook_bottom`).
  "Used from your Brain" shows these as "Story clips (the whole picture, still)" with what they replaced. `"above"` is
  deliberately not a style choice in `studio/capabilities.py` (the full-video engine has no such position).
- **Screens:** Make clips (three kinds with what each does), Stories ("Part k of n", the limit, disabled buttons with
  reasons), the clip editor (the limit under Trim, "Above the picture" for Fit, the hook's seconds up to the clip's
  length), Studio labels, the Brain level words;
  `frontend/dist` rebuilt.
- **Docs:** `docs/clipforge/STORY_CLIPS.md` (new), `OWNER_GUIDE.md`, `LONG_VIDEOS.md`, `FEATURE_CHECKLIST.md`.
- **Independent review** (before the PR): found and fixed a 4:58 story split in two, cuts inside sentences and words
  near twice five minutes and in silent gameplay, a planner that took minutes on an hour-long story, kinds of story
  videos the stricter rules missed (sponsor reads, posts read title-first, narrators who pause before each post), a
  trim of "NaN" accepted, "Part N" covering captions at the top, a room check for captions above the picture that was
  too strict, "Part N" vanishing after a part was lengthened, and a subject to follow chosen for a story project doing
  nothing.
- **Checks:** `tests/test_story_parts.py` (15), `tests/test_story_clips.py` (15, two slow: libass placement and a real
  render), `tests/test_full_stories.py` (33; the gamer-reader recordings in `tests/story_fixtures.py`),
  `tests/test_smarter_ai.py`.
  Two existing expectations changed on purpose: ClipForge AI can no longer split a story at a change of subject that
  nothing in the words announces (the old near-miss test now uses a place whose words start a story).
  Full fast suite (`pytest -m "not slow"`): 1968 passed, 3 skipped; the 49 failures and errors are the same 49 tests
  that fail on the release line in this cloud machine (yt_dlp, faster_whisper, huggingface_hub and CUDA are not
  installed). Slow suite (`pytest -m slow`): 29 passed, 1 skipped (needs the sound cleanup model files). Story finder
  on 423 review situations: 423 (release line 160). `tsc --noEmit` clean, `npm run build`. Browser tests (`e2e/`,
  the app on seeded data): 56 passed, 4 skipped, 8 failed, the same 8 that fail on the release line with the same data
  (Autopilot, Office and Settings expectations outside this change).
- **Not verified:** real speech recognition on Landry's own videos (the numbers are on synthetic recordings built from
  real post patterns); ClipForge AI's real model choosing among cut places (tested with stand-in answers and a broken
  model).

## Make → Animated short: viral voice-over shorts, made on this computer — 2026-11-08 (Claude Code)

Landry asked for a maker of the animated voice-over shorts seen on TikTok: paste a script, or have it written, and
everything running locally on his Apple-silicon Mac. Branch `claude/project-thread-5qybvh` from the release line at
95a70e0. No release. Design and contracts: [docs/clipforge/ANIMATED_SHORTS.md](docs/clipforge/ANIMATED_SHORTS.md).
The picture, video and voice engines themselves come from the local-engines work (`clipfoundry/engines`, branch
`claude/project-thread-nnvh05`); this branch talks to them through one door and works without them.

- **Scenes** (`clipfoundry/makers/scenes.py`, new): a pasted script becomes scenes of 6-16 spoken words (one picture
  every 2-4 seconds at 175 words a minute); blank lines, "Scene 3" headings and timings end a scene; `[Visual: ...]`,
  `Show:`, `B-roll:` and bracketed lines become the next scene's picture; titles, music, sound and hashtag lines are
  dropped; at most 600 words and 80 scenes, refused in plain words. Picture ideas from a scene's own words name the
  script's subject.
- **ClipForge AI writes** (`makers/writer.py`, new): a script from a topic, tone, length and audience, or picture
  ideas for a pasted script, as one JSON object in a schema; reads the owner's memories first (recorded as used in
  "short_script"), then the new **Animated voice-over shorts** playbook with hooks and endings
  (`brain/knowhow.py`: 13 playbooks, task "short"); outro lines are taken off, long lines split, a script far from
  the length asked once more; Stop works while it thinks.
- **Voice** (`makers/voice.py`, new): the local voice engine, else macOS `say`, Windows SAPI or espeak-ng (as its own
  program); speed; a voice sample for Hear it; word times from the engine, the speech model when it is downloaded
  (never downloads) or estimated from the sound; the engine's licence rule is kept with each scene's voice.
- **Pictures and motion** (`makers/pictures.py`, `cards.py`, `motion.py`, `looks.py`, new): eight looks; the picture
  engine when it is set up, else an honest designed card with the scene's key words (out of the caption zone); a
  sub-pixel push-in or pan on the still (OpenCV frames piped to FFmpeg, BT.709, exact length), or the video engine's
  motion slowed at most 1.5 times and held.
- **The short** (`makers/shorts.py`, `routes.py`, new; table `short_scenes`, JSON column `studio_projects.short`):
  one durable `short_build` job makes only what changed in each scene, one failing scene never stops the others, and
  the plan is one clip per scene with centred captions where the spoken word lights up (`captions.highlight`,
  `studio/engine.py`), music at -20 dB ducked under the voice and a whoosh on every other cut; the owner's editor
  changes stay when scenes are made again. A change shows "Waiting to make the changes" until the build starts.
  `/api/studio/shorts/...`; projects list filter `kind=short`; Stop says how to go on.
- **Pages** (`frontend/src/pages/MakeShort.tsx`, `components/ShortScenes.tsx`, `shorts.ts`, `pages/shorts.css`,
  new): Make → Animated short (paste or write, look cards, voice with Hear it, speed, music, captions with "Fits the
  look", camera moves or animated pictures, what will make it); the Scenes panel on the editor page (words, picture
  idea, new or earlier or own picture, camera move, move, add, delete, try again, voice/look/music for the whole
  short, how it was made); a reminder next to Download when the voice's licence asks for an AI label; Studio shows
  three things to make; Projects has an Animated shorts filter; the top bar says "Video" on the editor page.
- **Tests:** `tests/test_studio_shorts_flow.py` (12), `_parts.py` (12), `_voice.py` (18), `_captions.py` (5) and the
  slow `_render.py` (a real short with espeak-ng, rendered and its frames checked); the know-how tests count 13
  playbooks. Browser check against the real app: a 5-scene short made from the page in 18 s, then words changed, a
  scene moved, added and deleted; 1440 and 390 px wide.
- **Not checked here:** the real picture, video and voice engines, macOS `say`, Windows SAPI, ClipForge AI writing
  with a real model and the speech model's word times (none can run in the cloud computer).

## Release 2026.11.07: ClipForge AI far smarter, long videos and the new look — 2026-11-07 (Claude Code)

Landry wrote "publish the new changes". PR #32 was merged into the release line `claude/project-thread-x72wkd` as
`d1547e3`; the release line's slow render suite then failed one test on that commit (the fast-paced "Edit it for me"
got no punch-ins on an even synthetic voice, because punch-ins had moved to the moments where the voice leans on a
word), so PR #33 fixed it (an even voice falls back to the every-other-cut rhythm; the note says which rule) and was
merged into the release line as `95a70e0`, whose tree equals that of its head `8593947`. ClipForge 2026.11.07 was
published for Mac and Windows from `8593947` with its version notes on the download page. Everything merged since 2026.11.06 is in it: PR #31 (long videos), PR #30
(the new look), PR #32 (ClipForge AI far smarter) and PR #33. Every URL, size, hash and run:
[docs/clipforge/WEBSITE_DEPLOYMENT.md](docs/clipforge/WEBSITE_DEPLOYMENT.md).

- **Mac:** release `clipforge-mac-2026-11-07-8593947`, the unchanged DMG from build and test run 42407317796 (macOS 15:
  native build and bundled-app smoke passed; 1,969 fast tests passed, 2 skipped; 27 slow tests passed, 1 skipped), published by run 42409176722.
- **Windows:** `ClipForge-Windows-Setup.zip` at `raw/055ede7` on `claude/clipforge-downloads` (49,199,526 bytes; 788
  app files equal to the Git tree at 8593947 except the six declared CRLF exports; 77 launcher tests); Windows setup
  check run 42408340705 installed 2026.11.06 and then this ZIP over it on a Windows Server 2025 runner; record commit
  `7b3cd71`.
- **Download page:** `gh-pages` `0a7f3f0`: 2026.11.06 moved to All versions; ten "what changed" entries
  (newest work first), what was checked (the tests, the Mac build, the built-in AI check with the real meaning model
  and the eyes on Linux, Mac and Windows runners, the FilmCraft check, the Windows install check) and what was not
  (real footage with the built-in model, a 17 GB folder and real speech, the taste learner on real choices, the look
  on a real screen, real AI keys, YouTube, Windows security, notarization).
- **Lesson:** the PR checks do not run the release line's slow suite; espeak-ng can be installed on the cloud
  computer (`apt-get update` first), so `python -m pytest -m slow` (27 passed, 1 skipped in 19 min) now runs there before a merge.

## ClipForge AI far smarter: meaning, scout and judge, eyes, ears, your taste — 2026-11-07 (Claude Code)

Landry asked to make the built-in AI and the editing "100 times smarter", with research first and anything useful
plugged in, and asked that his two research guides be used. Branch `claude/project-thread-hud5t5` from the release line
at 7723696 (PRs #30 and #31 merged). No release. Design, numbers and the research table:
[docs/clipforge/SMARTER_AI.md](docs/clipforge/SMARTER_AI.md).

- **The meaning model** (`clipfoundry/embedder.py`, new): all-MiniLM-L6-v2 (Apache-2.0) on the CPU through ONNX
  Runtime; two files downloaded once at a pinned revision and checked against pinned SHA-256 hashes (a tampered file is
  deleted); a word-piece tokenizer in the module; a 40,000-vector cache; setting `meaning_model` (on); Settings → AI
  helper → "Understanding meaning" (state, progress, Cancel, Download now, Remove); `GET /api/ai/meaning`,
  `POST /api/ai/meaning/install|cancel|remove`. Without it everything falls back to the word-based vectors.
- **One scale for two spaces** (`pipeline/semantic.py`): `Embeddings` carry the model and the video's own baseline
  similarity; `cos_cal` removes it, novelty is rank-based; `diversity.py` uses the calibrated cosine. The brain's
  memories use the meaning model when present (`brain/meaning.py` `model()`, `make()`, `min_similar()`;
  `brain/memories.py` never compares vectors from different embedders).
- **Scout and judge** (`pipeline/scout.py`, new): the model reads the transcript in 8,000-character windows and names
  up to 12 moments, each snapped to sentences and scored by `candidates.window` (new) like any other; four deep-stage
  places are kept for them. The finalists are ranked side by side with green/yellow/red verdicts; the ranking moves a
  Clip Score by at most ±10 (percentile against percentile), green +2, red −6 with the reason as a warning. Both passes
  read one brief (title, picking playbooks, the owner's rules, wanted length, taste) inside a budget of
  `ai_edit_timeout_s × 10` (at most 10 min); the built-in model answers inside a JSON schema. Setting `ai_scout` (on).
- **Eyes** (`pipeline/eyes.py`, new): three frames of the six strongest finalists go to the built-in model's vision
  part with the clip's first words; it answers in a schema (kind, people, text on screen, best thumbnail, description,
  appeal 1–10); at most ±4 on the Clip Score; the chosen frame becomes the thumbnail (`render.thumbnail_time`).
  `builtin_ai.chat` gained `json_schema` and `images`; `llm.complete` passes them through. Setting `ai_eyes` (on).
- **Ears** (`pipeline/ears.py`, new): pitch every 20 ms by autocorrelation, pitch variation, emphasis moments (pitch
  +3 semitones and loudness +0.8 σ together), laughter-like bursts (word-free, 3–8 Hz pulsing), the pause before the
  end, monotone; a prosody score joins the deep extras and a flat voice is named in the "Why". The smart editor's
  punch-ins land where the voice leans on a word (`studio/smart_edit.py`, cached `prosody.json`); when a recording's
  voice stays even after every cut, the old every-other-cut rhythm takes over for it (found by the release line's
  slow render test on a synthetic voice, fixed before the 2026.11.07 release); the note says how many and which
  rule.
- **Your taste** (`clipfoundry/taste.py`, new; tables `taste_events`, `taste_models`): lessons from unticking,
  re-ticking, exporting, publishing and deleting clips with the clip's 16-number profile; after 12 lessons (4 each
  side) a logistic regression gives each finalist at most ±6 with the reason in words, also read by the scout's brief;
  `GET/DELETE /api/taste`; PATCH `/api/clips/{id}` records choices; export and publish call `taste.published`;
  Brain → Memory shows what was learned and can forget it.
- **Full stories** (`pipeline/stories.py`): meaning shifts between the six sentences before and after each gap (robust
  z-score; z ≤ −2.5 and shift ≤ 0.25 → topic 0.22, z ≤ −1.8 and shift ≤ 0.35 → 0.12) when the meaning model is on
  (`propose(..., opts)`, `story_review.py` passes the settings); `Judge.scan` reads the recording through and names
  where stories begin before the unsure boundaries are reviewed; an unreadable answer no longer counts as "no new
  story here" (a real bug: it dropped weak accepted boundaries).
- **Deep analysis for every "Make clips"** (`pipeline/process.py`, `deep.py`): `deep_analysis` on by default with a
  pool of 4 × clips (24–40); the clip's stored analysis carries `clip_score`, `explanation`, `judge`, `scout`, `taste`
  and a small `deep` summary; the app shows them (`components/viral.tsx` `AiNotes`: scout line, rank and verdict,
  "ClipForge AI saw", "The voice", "Your taste", "How the Clip Score came about"). `frontend/src/api.ts` has the types
  and routes; `frontend/dist` rebuilt.
- **The guides' rules** (`pipeline/text_utils.py`, `virality.py`): the causal engine (pivots "but", "because", "which
  meant", "turns out" raise curiosity by up to 0.06; an "and then" chain with no turn costs 0.10 and shows the warning
  "\"And then\" chain"; `signals.causal_pivots`, `signals.episodic`); constrained-experiment hooks ("I spent 30 days",
  "I tried", "here's what happened", "on a budget", "with only") as hook and open-loop phrases; chapter-cliff fillers
  ("furthermore", "my next point", "on to the next") as transitions.
- **Fix:** `taste.predict` could return NaN when a feature never varied (standard deviations floored at 1e-4, z-scores
  clipped at ±4).
- **Checks:** `tests/test_smarter_ai.py` (39 tests; one runs the real model when `CLIPFORGE_MEANING_MODEL_DIR` is set);
  `tests/conftest.py` points the model hub at a closed port so no test downloads; `tests/test_review_creation_fixes.py` compares the unrounded ranking value (the one-decimal score can coincide when the prioritised factor sits at the mean, which the new curiosity term made happen for its passage); `scripts/builtin_ai_check.py
  --meaning --eyes` and `.github/workflows/builtin-ai-check.yml` check the real download, hashes, similarities, speed,
  a schema-bound ranking and the eyes on a GitHub runner (the model hub is blocked from the cloud computer).

## The ClipForge look: one design system and every page restyled — 2026-11-07 (Claude Code)

Landry asked to "improve the entire UI for the app, make it look very very good". Branch `claude/project-thread-89ew66`
from the release line at 3c6b980 (the long-video work runs in its own branch beside it). No release.

- **The design** ("the edit bay", [docs/clipforge/DESIGN_SPEC.md](docs/clipforge/DESIGN_SPEC.md)): dark layered
  surfaces lit from their top edge, sunken wells for the places media goes (drop zones, timelines, chats, lists),
  lifted buttons, the footage on the darkest stage so it is the brightest thing on the page, and one accent for the
  action that moves work forward and the place you are in. Dark only, as before. Poppins SemiBold (the caption face,
  bundled) for titles, the system font for everything else; 15/13/12 px text, 17 px section titles, 28 px page
  titles; sentence case everywhere, no all-caps labels. Radii 8/12/16 px; controls 36 px (32 compact, 44 on touch);
  sidebar 236 px, top bar 56 px, content up to 1280 px.
- **The design system** (`frontend/src/styles.css`, rewritten): fonts, scale, spacing, shape, light and depth
  (`--lift`, `--lift-sm`, `--sink`, `--well`, `--frame`, `--glow`) and every shared component: the shell (the rail
  marks the current place with the accent tint and a 3 px bar; blurred top bar; drawer under 1024 px), page heads,
  buttons, pills, tags, panels, forms (inputs in wells, a custom select, choice cards, segmented controls, switches,
  chips), drop zones and file rows, tabs and the Settings side list, the editors (stage, timeline, words, desk, save
  bar, versions, sequence, the ClipForge AI chat), tables, sign-in, dialogs, menus, toasts, loading skeletons, empty
  states and the robot office. Every class the pages use kept its name, so the look changed without touching how
  the pages work.
- **Palettes and accents** (`frontend/src/theme.css`, tokens only): Studio, Midnight, Graphite and Plum retuned
  (deeper canvas, clearer steps between layers) and the six accents with hover and tint; quiet text never below 6:1;
  `tests/test_theme_contrast.py` still checks every pair, and the spec lists the measured ratios.
- **Pages:** the Studio's two big choices glow with the accent; a project's clips are lifted cards; the clip and
  video editors have a framed stage, a sunken timeline and a desk head with a mark; Review packs its panels into two
  columns, preview above look and outputs above guidance (`LayoutFlow` in `components/AppearanceSettings.tsx` packs
  sized panels into columns so no hole is left beside a tall one; default widths in `prefs.py` and `prefs.tsx`
  `REVIEW_SIZE`); Settings has a side list of sections (`SettingsFrame` in `pages/Settings.tsx`, a tab row under
  900 px) with Appearance at full width; Brain → Memory shows its summary as tiles and the playbooks as a quiet list;
  the knowledge map sits on the canvas with a faint grid; the office keeps its pixel titles and room colours on the
  shared surfaces with the map as a framed window; Posts and the TikTok setup use the tokens instead of their own
  colours.
- **States:** loading pages show a title block and panel-shaped skeletons (a shimmer once per 1.6 s, paused when the
  tab is hidden) instead of a spinner; empty states have an accent disc with the icon, one sentence and one action;
  the ClipForge AI chat says what will appear in it; the sidebar's collapse button says what it does.
- **Also:** the long-video thread's new wrappers (`.script-drop`, `.script-panel`, `.script-line.matched/.weak/
  .missing`, `.script-takes`, `.local-browser`, `.local-list`, `.local-pick`) are styled ahead of their arrival;
  `index.html` paints the new canvas colour before the app loads; before/after pictures in
  `docs/clipforge/ui-redesign/`.
- **Checks:** `cd frontend && npm run build`; `python -m pytest -q tests -m "not slow"`; the browser checks for the
  shell, library, Settings and the office against a throwaway app: 32 pass, and the 5 that fail (three office map and
  bar checks, two Settings checks) fail the same way on the release line with the same data.

## Long videos: full stories found right, big footage, your script, and a smarter cut — 2026-11-07 (Claude Code)

Landry could not get 17 GB of footage into "Make a YouTube video", found the cut it made weak, wanted to give it the
script to compare with the footage, and asked first for the Full stories section to find every story in a video of
someone reading posts and make one long clip per story without asking anything. Branch
`claude/project-thread-6ouxbx` (from the release line at 32485bd), draft PR into `claude/project-thread-x72wkd`. No
release.

- **Full stories** (`pipeline/stories.py`, `studio/story_review.py`, `jobs.py`): the finder learns the narrator's own
  separators from the recording ("next story", "story number three", "this one is from r slash…", a post title read
  out, numbering in order), knows the strong and weak openers and the Reddit title patterns, never splits an update
  or a top comment from its story, labels intro, sponsor and outro blocks, and looks at a topic dip against the
  chunk's own median rather than silence alone. Every story runs until the next one starts (the transition words go
  with the story before them), nothing waits for a check, and each clip is made at once. With ClipForge AI's model
  set up it gives a second opinion on the least certain boundaries inside a time budget and names the stories from
  the post title. Text-to-speech narration (no pauses) is handled.
- **Big footage** (`studio/local_files.py`, `studio/local_routes.py`, `studio/uploads.py`, `studio/proxies.py`,
  `pipeline/transcribe.py`, `pipeline/audio.py`): on the desktop, **Add from this computer** browses the owner's
  folders and drives (`GET /api/local/browse`) and uses files where they are (`POST /api/uploads/link`; nothing
  copied, the file never changed, found again if moved within the allowed folders); the upload limit is the free
  space less 2 GB (at most 512 GB) instead of a fixed size. Each asset has a work folder (`uploads.work_dir`) for
  its sound, transcript pieces and preview copy. Long files are listened to in pieces (`transcribe.transcribe_long`,
  resumable from `transcript.parts`, the model held across the pieces of one batch and released after it,
  `release_model`), and a closed app carries on where it stopped. `POST /api/assets/{id}/prepare` does the sound,
  the transcript and a small preview copy in the background (`preview_proxies` setting); previews read the copy,
  the final render always the original (`assets.proxy_path`).
- **Your script** (`studio/script.py`, `studio/script_cut.py`, `video_flow.set_script`, `db.py`
  `studio_projects.script`): `.txt`, `.md`, `.docx`, `.pdf`, `.fdx` or pasted text (`POST /api/studio/scripts/parse`;
  `pypdf` and `python-docx` added to the requirements) become numbered lines, headings and directions. Every spoken
  line is matched to the transcribed words of every recording, each time it was said is a take, the take said most
  cleanly plays (`take_quality`), the others follow it switched off ("Another take of line 12"), neighbouring lines
  said in one go are one clip, what is in no line waits at the end switched off, a heading is a chapter, missing
  lines are named. `use_take` swaps a take in (the clip is split around the line, the old take kept behind it). A
  script goes with the new video (`POST /api/studio/videos` `script`) or later (`PUT /api/studio/videos/{id}/script`,
  a new version in the background; `null` takes it away). With a script the model is not asked anything; pictures,
  music and effects come from the smart edit as before.
- **A smarter cut without a script** (`studio/smart_edit.py` `judge_sentences`): the cleanest take of a line said
  again anywhere in the footage plays and the rest are switched off in place (`best_takes`: content-word index,
  similarity ≥ 0.8 on four or more words; a line said more than three times is a catchphrase and stays); warm-ups
  and throat-clearers in a recording's first 20 s, words to whoever is recording in its last 45 s or tenth, and a
  sign-off before the last recording are left out (`chatter`); a video of two minutes or more opens with its
  strongest line and then plays from the start (`cold_open`: the model's `hook` or the best `hook_score` after 15 s
  inside the first 60%; brief `cold_open`, on by default; Shorten the introduction skips it).
- **ClipForge AI reads the whole video** (`studio/ai_editor.py`): what the rules left out is not sent (`skip`),
  windows carry the story so far (the chapters found earlier), up to 64 windows are read inside a time budget
  (`ai_edit_timeout_s` × 15, between 2 and 15 minutes, `budget_for`), the first window always; a `hook` it names is
  only ever a sentence that plays; the report says how many sentences it read and how many were not sent.
- **In the app** (`components/ScriptDrop.tsx`, `ScriptPanel.tsx`, `LocalFiles.tsx`, `longVideo.css`,
  `pages/MakeVideo.tsx`, `pages/VideoReview.tsx`, `studioParts.tsx`, `studio.ts`): "Your script" on the Make a
  YouTube video page (drop, choose or paste), "Add from this computer" on the desktop, the cold-open choice in the
  brief; on the editor page a **Script** panel (every line with where it plays, Use this take, add, change or take
  away the script), "Cold open" and "Line N" pills in the sequence, "Use this take" on the other takes, Add from
  this computer under Your media. `frontend/dist` rebuilt.
- **Tests:** `tests/test_full_stories.py` (13), `tests/test_studio_script.py` (23), `tests/test_studio_script_cut.py`
  (4), `tests/test_transcribe_long.py` (17), `tests/test_studio_local_files.py` (9), `tests/test_studio_proxies.py`
  (3, needs ffmpeg), `tests/test_studio_smart_edit.py` (21). No speech model, no real footage and no built-in model
  in the cloud: the words are given.
- **Design:** [docs/clipforge/LONG_VIDEOS.md](docs/clipforge/LONG_VIDEOS.md) (new); `SMART_EDITING.md`,
  `OWNER_GUIDE.md`, `ROUTE_MAP.md`, `FEATURE_CHECKLIST.md` (rows 43 to 45) updated.

## Released ClipForge 2026.11.06: ClipForge AI and FilmCraft inside the app — 2026-11-06 (Claude Code)

Landry chose "Merge and release" on PR #28. The release line `claude/project-thread-x72wkd` at `32485bd` (PR #25,
#26, #27 and #28 since 2026.11.05.2; the same tree as the tested head `ae2d5f5`) is both downloads' source.

- **Checks on `32485bd`:** `macos-desktop.yml` run 42311548798: native build and bundled-app checks on macOS 15,
  the fast suite (1,866 passed) and the slow suite (27 passed) on GitHub's Linux machine. Locally 1,866 fast
  tests passed on `ae2d5f5`. FilmCraft check run 42307942878 (the built-in model's pass with the know-how; FilmCraft
  0.17.1 and EffectCraft 0.9.2 fetched and checked) passed on Ubuntu and macOS.
- **Mac:** release `clipforge-mac-2026-11-06-32485bd` (publish run 42316848534), `ClipForge-Mac-Apple-Silicon.dmg`
  237,930,523 bytes, SHA-256 `ff6358ca836ce8a9b39f98f07c495a09d2035749bf5a823235677d97b2e91fc1`. Unsigned personal preview, prerelease. The release notes in
  `.github/scripts/publish_personal_mac.py` name this version's features (`7a6af17` on `claude/project-thread-605vsm`,
  where the publish workflow was started; the DMG is the unchanged tested one from `32485bd`).
- **Windows:** `ClipForge-Windows-Setup.zip` at `raw/9ddbd62` on `claude/clipforge-downloads`, 47,304,093 bytes,
  SHA-256 `2abde3f1829a0cc36ab5eede866895f42a36316a7dc9148d96bf34bc0ef36888`; 77 launcher tests, all 748 app files
  equal the tree (six .bat CRLF exports); Windows setup check run 42312199587 installed it over the 2e5238e release
  (settings kept).
- **Download page:** `gh-pages` `eaa92df` (previous `b5afbd3`; Download page run 42317711666, Pages
  run 42317710696), ClipForge 2026.11.06 with seven changes and the checked / not checked lists; `build.py --check`
  and `--verify` passed.
- **Not verified:** a real model reading the know-how in the chat, the caption positions and the hook headline on a
  real phone, the sound profiles by ear, real AI keys, a real YouTube download, Windows 10/11 desktops, physical Macs.

## ClipForge AI know-how: the research turned into playbooks, and editors that apply its numbers — 2026-11-06 (Claude Code)

Landry gave ClipForge AI two research guides (a cinematic filmmaking and post-production guide, a viral short-form
video strategy guide) and asked to use them to make the AI smarter at its job, plus "your own stuff". Branch
`claude/project-thread-605vsm` (restarted from the release line at 936d7fc, after phase A merged). No release.

- **Know-how** (`clipfoundry/brain/knowhow.py`): twelve playbooks in plain words with numbers (hooks and openings,
  endings and loops, pacing and cuts, captions and safe zones, voice and sound mix, music by mood, colour by mood,
  effects that earn their place, picking a clip, platforms and export, reading a retention graph, talking-head
  edits), distilled from the guides and ClipForge's own rules. `select(query, task)` picks the few that fit a question
  or a job (rarer words count more; the words a playbook is about count double; a task's defaults fill in) inside a
  character budget; `answer(query)` is the one playbook that answers a question alone; `principles(task)` the
  one-line reminder for a task's instructions. The owner's memories always win over it, and the prompt block says so.
- **Where it is read:** the general chat (1,400 characters after the memories; without a model it now answers
  editing questions from the playbook that fits, e.g. "how loud should my video be?"), change requests (900, after the
  memories, dropped first when a long video needs the room; the request's new `knowhow` column records what it read;
  the principles line is in the instructions), smart-edit advice (700, before the brief of every window; the system
  text now says to keep the strongest line first and leave out outro lines), the FilmCraft pass (1,500: colour,
  effects, sound by default; the system text says correct before grade, effects with their sound, voice first), clip
  scoring and post packages (the principles line). "Why?" names the playbooks a request read. Brain → Memory lists
  every playbook (`GET /api/brain/memories/knowhow`; `POST …/knowhow/select` shows what a question would read).
- **The editors apply the numbers:** outro lines ("to recap", "thanks for watching", "follow for part two",
  `text_utils.OUTRO_PHRASES`) are a warned flag, lower the payoff and make a poor opener, so the ending before them
  wins; loss or warning framing (`LOSS_WORDS`, `LOSS_PHRASES`) and starting in the middle of a story score higher as
  openers and hooks; hook lines prefer plain words and 4-12 words (best under 8); the hook headline starts below the
  apps' top bar (15% instead of 11%) and shrinks for long text (68 / 58 / 50 px); "bottom" captions sit 36% up,
  above the 35% the apps cover (was 23%, inside it); the voice clean-up uses the dialogue chain (high-pass 80/100 Hz,
  2/3.5 dB out of the mud at 300 Hz, 2/3 dB of presence at 3.5 kHz, 2.5:1/3.5:1 with a 20 ms attack and a 90 ms
  release); clips are converted to YUV with the BT.709 matrix and tagged BT.709 (FFmpeg used BT.601 for the RGB
  frames before, a visible shift of reds and greens on every clip), delivered with a closed GOP and a keyframe every
  half second, and AAC at 256 kbps (full videos: keyframes every half second, 256 kbps too).
- **In the app:** the chat shows "From its know-how: …" under answers and proposals; Brain → Memory has "What it
  knows about editing (built in)" with every playbook expandable; the chat's example chip asks "How loud should my
  video be?". `frontend/dist` rebuilt.
- **Tests:** `tests/test_clipforge_ai_knowhow.py` (12). The chat's answer is now returned as written before the model
  starts (the page polls), which also removes a timing race in the chat tests.
- **Design:** [docs/clipforge/CLIPFORGE_AI.md](docs/clipforge/CLIPFORGE_AI.md), "Know-how".

## ClipForge AI phase A: the brain's memories and the chat — 2026-11-06 (Claude Code)

Landry asked for a much better AI ("ClipForge AI"): research the best models, combine them, add its own data and
training, let them talk to it, keep everything in the brain, find music and pictures, make effects and music. The
research and plan are in the Claude Doc "ClipForge AI: research and plan"; Landry chose **brain and chat first**.
Phase A is on `claude/project-thread-605vsm` (from the release line after #25 and #26). No release.

- **The brain's memories** (`clipfoundry/brain/memories.py`, `meaning.py`, tables `brain_memories`,
  `brain_memory_uses`): rules, facts, episodes (what it did), each with a source (said, did, guessed, imported), a
  confidence, a scope (every video, one video, a platform, clips or video) and a meaning vector (`hash-v1`: hashed
  words, stems and pairs, 256 dims, no download; a real embedding model is a later download, tracked by
  `meaning_model` and recomputed by Rebuild). Recall = standing rules first, then the best few by words and meaning
  within a character budget, never an unrelated memory. The same words said twice are one memory with the stronger
  source. Guesses expire after 60 days unless confirmed. Health check, Tidy, Rebuild, export and import
  (`clipforge.brain-memories/v1`). Routes under `/api/brain/memories`.
- **Where it is used:** change requests (1,200 characters of memories in the prompt; what was applied or discarded is
  remembered), the FilmCraft finishing pass (800) and smart-edit advice (500). Every use is recorded against the
  memory, so "why?" can answer.
- **The chat** (`clipfoundry/brain/chat.py`, tables `brain_chats`, `brain_chat_messages`, routes under
  `/api/brain/chats`): teaching, forgetting, listing and explaining without a model; in a video's chat anything else is
  a change request (rules, then the model; Apply or Discard); in the general chat it is a question the model answers
  with the recalled memories as one checked JSON object (`{"say": …}`, at most 1,200 characters), counted against the
  daily AI limit. The model never calls a tool and never sees a file. Answers cut off by a restart are reported.
- **In the app:** `components/ClipForgeAI.tsx` replaces the change-request form on a video and is Brain → Talk;
  `components/MemoryTab.tsx` is Brain → Memory. "AI helper" is now **ClipForge AI** and the built-in AI is its
  **built-in model** everywhere the owner reads it; setting keys and API addresses did not change.
- **Design:** [docs/clipforge/CLIPFORGE_AI.md](docs/clipforge/CLIPFORGE_AI.md). Tests: `tests/test_clipforge_ai_brain.py`
  (9), `tests/test_clipforge_ai_chat.py` (5), plus new cases in the change-request and craft tests.
- **Not in phase A:** the embedding model download, finders (music, pictures) and makers (music, effects), settings in
  words, the taste model and the editing adapter (phases B to D in the plan).

## The built-in AI finishes the edit with FilmCraft — 2026-11-06 (Claude Code)

Landry chose "Combine, test, then merge": the built-in AI (phase 1, PR #25) and FilmCraft inside ClipForge (PR #26)
are joined on `claude/project-thread-605vsm`, and both go into the release line once the real check passes. No
release.

- **Joined:** PR #25's branch merged in. Overlaps fixed by keeping both sides: the server's shutdown stops running
  FilmCraft/EffectCraft tools and the built-in AI's engine; `config.py` has both setting lists; change logs kept;
  `frontend/dist` rebuilt from the merged sources.
- **The built-in AI does the FilmCraft pass** (`craft/ai.py`): it counts once downloaded (`ai.usable`), and
  `finish.edit_key` includes its level, so downloading it or switching level edits again. Its request is shortened
  to 14,000 characters for a model on this computer (`SHORTER`: tool descriptions, quotes, effect and look names,
  then clips, the main video's first); online services get up to 40,000. Ollama is now asked for an 8,192-token
  context for this pass (it defaulted to 4,096, which cut the request short).
- **Waiting for a local model:** `ai.ask` runs the request in its own thread so the job can be cancelled while the
  model thinks; local models get up to 10 minutes (`llm.complete(timeout=...)`, also used by Ollama and LM Studio)
  and the built-in AI answers in JSON mode (`json_object=True`, llama.cpp's `response_format`).
- **Real check:** `scripts/craft_check.py --builtin-ai` (in `filmcraft-check.yml`) downloads the engine and the Basic
  model the way the app does and runs the AI pass with them on the real apps.
- **First real run (42269267394):** on both machines the built-in AI was still answering at the 10-minute limit
  (no length cap, so a small model can go on until the time-out). Now a local model's answer is capped at 1,200
  tokens and it is asked for at most 10 steps; an answer cut off at the cap still gives the steps it finished; a step
  repeated word for word runs once. The check prints llama.cpp's timings and the engine's log when nothing lands, and
  gives GitHub's Mac machine (no graphics chip) 25 minutes.
- **Second real run (42274107689):** Ubuntu passed. The built-in AI answered in 164 s (4,359-token request at 73
  tokens/s, 844-token answer at 8 tokens/s) with 10 steps, and 6 landed in FilmCraft's render: a blur, brightness and
  contrast, a push-in keyframe, a "Lake Day" title and a box. 4 used names FilmCraft lacks. On GitHub's Mac (1.5
  tokens/s, 1,019 s) all 11 of its steps were transitions with a `duration` FilmCraft's transitions don't have, and
  the final screenshot after the save timed out (the save itself came back as version 2). Now a step that fails only
  on a parameter FilmCraft says it lacks runs once more without it (FilmCraft checks parameters before changing
  anything), the request shows a transition example, and the check's screenshots are pictures only.
- **Fixed in the built-in AI's setup:** it was marked done before it was chosen as the AI helper, so Settings (and a
  test, about one run in five) could read the old helper. It is chosen first now.
- **Tests:** six new in `tests/test_craft.py` (the shortened request, the built-in AI before and after download,
  cancelling a slow answer, the timeout, JSON mode and answer cap reaching the engine, a cut-off answer). The request now shows three example
  steps that real FilmCraft accepts (a look, an effect, a keyframed push-in), which small models need.

## FilmCraft and EffectCraft inside ClipForge: fixes from the real apps — 2026-11-06 (Claude Code)

The first real-app run (GitHub macOS 15 and Ubuntu, run 42250189370) applied all 29 FilmCraft steps and FilmCraft's
render passed its checks, and showed three problems, fixed here:

- **EffectCraft's title script** failed on `layer.property("Source Text")` (EffectCraft 0.9.2 has no such shortcut).
  Shot scripts now use helpers that look properties up by match name first (`craft/shots.py`), run in an empty
  project (`--empty`, with a retry without it for an EffectCraft that refuses it), use ClipForge comp names, and
  report what they could not set. The AI is told about the helpers.
- **FilmCraft's editor on the editor page**: the released web build (0.17.1) has the `window.filmcraft` API but no
  host messages, so the page never opened the version. The page now opens it when FilmCraft has started, takes
  `.fcproj` downloads from the frame as saves, and has a Save to ClipForge button (`file.saveAs`).
- **The check itself**: the seeded project's own rough-cut job raced the check's plan (sometimes saving version 2);
  the AI stand-in picked a clip kind that does not exist. A failing AI pass no longer stops the FilmCraft edit.
- **Second run (42255291402)**: the EffectCraft title now renders and is placed on both machines (`checks: ok`), the
  AI pass applied its steps and placed its EffectCraft shot, and FilmCraft's editor started in headless Chrome
  (WebGL2) and took the files. Fixed after it: FilmCraft only opens a project `File` made by its own window, and
  look names contain commas ("Teal Shadows, Warm Skin"), so the AI now gets the effect and look lists as JSON.
- **Third run (42256808188): passed on macOS 15 and Ubuntu.** FilmCraft edit (30 steps, none failed) with the
  EffectCraft title placed, FilmCraft's render checked, the AI pass (4 steps and an EffectCraft lower third, none
  failed), and FilmCraft's editor on the editor page: started on WebGL2, opened version 1 with all 9 tracks and its
  files, and Ctrl/Cmd+S in FilmCraft came back to ClipForge as version 2.
- A FilmCraft or EffectCraft process still running when ClipForge quits is now stopped with it (the check's server
  had left a FilmCraft preview render running).

## FilmCraft and EffectCraft inside ClipForge — 2026-11-06 (Claude Code)

Landry: "I want film craft to actually be in my app and not seperate and the ai uses it to edit and it can use any of
the tools it offers and if it uses one program to do effects it then takes that shot and puts it in the final edit".

- **Fetched by ClipForge** (`craft/apps.py`): FilmCraft 0.17.1 and EffectCraft 0.9.2 release files for macOS, Linux
  and Windows (and FilmCraft's web build), pinned by SHA-256 and size, downloaded in the background by the desktop
  app (Settings, Editing apps: set up by hand, turn off), unpacked with path/link checks into `<data>/tools/craft`.
- **The edit in FilmCraft** (`craft/finish.py`): the timeline imported by `filmcraft-cli`, then ClipForge's look and
  sound made with FilmCraft commands (Motion scale, Gaussian Blur on new "Blurred background" tracks, Scale/Opacity
  keyframes, Volume keyframes, Essential Sound ducking, caption style, -14 LUFS export).
- **EffectCraft shots** (`craft/shots.py`): the animated title replaces the still title card in the edit.
- **The AI's finishing** (`craft/ai.py`): with an AI helper, FilmCraft steps (finishing tools only, checked clip ids,
  no paths, at most 40) and up to two EffectCraft shots laid over the video.
- **FilmCraft renders final videos** (`video_flow._craft_render`, setting `edit_engine` auto/filmcraft/ffmpeg): the
  built-in editor is the backup with the reason recorded; previews stay built-in.
- **FilmCraft's editor on the editor page** (`craft/web.py`, `craft/routes.py`, `components/FilmCraft.tsx`): opens
  the AI's FilmCraft edit (job `filmcraft_edit`) with only this video's files; Save in FilmCraft becomes a new version
  rendered by FilmCraft (`plan["filmcraft"]`, saves kept by SHA-256). Desktop app only.
- **Settings → Editing apps** (`components/EditingApps.tsx`), and each version says which editor made it.
- **Tests:** `tests/test_craft.py` (15, stand-in apps), `tests/test_studio_filmcraft.py` updated for the background
  tracks (14). Real apps: `scripts/craft_check.py` in `.github/workflows/filmcraft-check.yml` (macOS 15, Ubuntu).
  Results: see the PR and AI_HANDOFF.md.
- **Docs:** `docs/clipforge/CRAFT_APPS.md`.

## Finish in FilmCraft (ArtCraft's open-source editor) — 2026-11-06 (Claude Code)

Landry asked to plug the ArtCraft apps into ClipForge for editing. FilmCraft (the video editor) is first.

- **Editor page → Finish in FilmCraft:** "Open in FilmCraft" writes the current version as an OpenTimelineIO
  timeline with SRT captions, a title-card still and a README next to the video, then opens the FilmCraft you
  installed (with its command-line tool, as a ready FilmCraft project). "Show the timeline files" and "Timeline with
  media (.zip)" (portable, also in the online studio). Not installed: the files are still written and the panel
  links to getartcraft.com/apps/filmcraft. ClipForge never downloads or bundles FilmCraft.
- **The timeline** is made from the FFmpeg engine's frame map (frame-exact): clips, images, dissolves/dips as centred
  OTIO transitions, straight cuts, the title still, pictures over the video (V2), clip sound with volume and mutes
  (A1, linked), voiceover/music/effects tracks (loops repeated, overlaps on extra lanes), chapters as markers, frame
  size and rate for FilmCraft. What cannot carry over (ducking, fades, punch-ins, fill framing, blurred background,
  overlay motion, caption look, loudness leveling) is listed in the README and the panel.
- **Code:** `studio/interchange.py`, `studio/filmcraft.py`, routes `GET /api/studio/filmcraft`,
  `POST /api/studio/videos/{id}/filmcraft`, `GET /api/studio/videos/{id}/timeline.zip`, `components/FilmCraft.tsx`.
  Docs: `docs/clipforge/FILMCRAFT.md`.
- **Tests:** `tests/test_studio_filmcraft.py` (13, fast; OpenTimelineIO 0.18.1 read the file in the local run);
  `.github/workflows/filmcraft-check.yml` + `scripts/filmcraft_check.py` import and render the timeline with
  FilmCraft 0.17.1's official release on macOS 15 and Ubuntu: passed on both (PR #26, run 42185369033).
  Full fast suite: 1781 passed.
- **Not verified:** the FilmCraft window opening on a real Mac or Windows PC; FilmCraft could not be run in the cloud
  session itself (running a downloaded program there is not allowed), so it runs on GitHub's machines instead.

## Built-in AI and "Clean up the sound" (phase 1 of the smarter editor plan) — 2026-11-06 (Claude Code)

Landry asked for an AI that comes with the app and for smarter editing with better sound; after the plan (Claude Doc
in the project thread) Landry chose "Start phase 1". Draft PR from `claude/project-thread-4sg7wk` into
`claude/project-thread-x72wkd`; nothing is merged or released. Design and limits:
[docs/clipforge/BUILTIN_AI_AND_SOUND.md](docs/clipforge/BUILTIN_AI_AND_SOUND.md).

- **Built-in AI (Settings → AI helper, listed first):** one Download button; llama.cpp `llama-server` b12017 (MIT)
  with Qwen3-VL 2B (Basic), Gemma 4 E4B (Standard) or Gemma 4 26B A4B (Pro), all Apache 2.0, downloaded on first use
  from pinned releases and revisions and checked against pinned SHA-256 hashes. The level is recommended from the
  computer's memory and graphics memory. The engine runs on 127.0.0.1 with a random key, stops when idle, when
  ClipForge quits and before transcription needs the graphics card, and is shared with the Autopilot worker. It is a
  local provider (`ai_provider = "builtin"`) for clip scoring, post text and the AI editor.
- **Clean up the sound (`clean_sound`: Off, Auto, Gentle, Strong; default Auto):** mic balance (a dead or inverted
  channel is left out), rumble and 50/60 Hz hum, background noise (DeepFilterNet 3 through ONNX Runtime, a pinned 13
  MB download; a spectral noise gate when it is not available), quiet and loud passages evened out, breaths in pauses
  softened, de-esser, gentle compression and presence. Auto leaves music and sound that is mostly not speech alone.
  Used by clip renders and the full-video editor (each file cleaned once and cached); the result lines up with the
  picture to under a millisecond. Clip editor: the setting, a before/after switch at matched loudness, and a note on
  what the last render did. Full-video editor: a choice in the Sound panel.
- **New requirement:** `onnxruntime>=1.20` (Mac, Windows and Linux wheels; about 15 to 20 MB).
- **Tests run:** `tests/test_builtin_ai.py` 19 passed; `tests/test_clean_sound.py` 15 passed, plus the real-model test
  (slow) with the model files present locally; full fast suite 1,801 passed (28 slow deselected); slow suite 26 passed and 2 failed: one test measures a pure
  test tone that Auto cleaned as noise, so it now turns the cleanup off like its other processing, and both pass
- **Real engine and models on GitHub's test machines** (`builtin-ai-check.yml` run 42160482511, Basic level): Linux
  answer 2.7 s at 35.7 tokens/s, Windows 2.8 s at 22.9 tokens/s, Mac (a virtual Mac with 3 cores, 7 GB and no graphics
  access) 19.6 s at 5.0 tokens/s after a 32 s first load; all answered the scoring prompt as JSON and the picture
  question correctly. Sound cleanup of a minute of speech: 1.5 s on Linux, 6.0 s on the Mac. The pinned catalog
  matches Hugging Face and the llama.cpp release. The native Mac app built with ONNX Runtime (`macos-desktop.yml` run
  42160487116); `macos/desktop_media_smoke.py` now also runs the voice model inside the built app.
- **Not verified:** a physical Mac or graphics card (the Mac runner has no graphics access, so real Macs should be
  faster); answer quality of each level; listening tests on real recordings; the native apps with these screens.

## Released ClipForge 2026.11.05.2: smart editing and the Mac link fix — 2026-11-05 (Claude Code)

Landry asked in the project thread to merge both fixes (PR #22, PR #23) and update the website with the new versions.
Both downloads are built from `2e5238e` (PR #20's branch with PR #22 merged, plus PR #23).

- **Checks on `2e5238e`:** `macos-desktop.yml` run 42106643196: native build and bundled-app checks (including the
  FFmpeg join and Deno), 27 slow tests; the fast-suite job hung in `apt-get` and passed on rerun (1,768). Locally
  1,768 fast tests passed.
- **Mac:** release `clipforge-mac-2026-11-05-2e5238e` (publish run 42114038409), `ClipForge-Mac-Apple-Silicon.dmg`
  237,781,526 bytes, SHA-256 `14c78abe948634cc92a7c786aac0916534ef0f88cc52e7b5e9cc55af29c2169f` (about 45 MB larger:
  Deno for YouTube). Unsigned personal preview, prerelease.
- **Windows:** `ClipForge-Windows-Setup.zip` at `raw/d60445f` on `claude/clipforge-downloads`, 47,042,861 bytes,
  SHA-256 `531e9ef012eb27705f7ed66b82325c9f2b048b854d4206c260541e9e0d63eb0d`; 77 launcher tests, all 709 app files
  equal the tree; Windows setup check run 42109581700 installed it over the 6ecdafc release (settings kept).
- **Download page:** `gh-pages` `65f026a` (previous `138c4f7`, Pages run 42114472648), ClipForge 2026.11.05.2; `build.py --check` and
  `--verify` passed (all eight listed files). Release notes in `.github/scripts/publish_personal_mac.py` name the
  new features (`d45bb0d`).
- **Not verified:** a real YouTube download, real AI models and keys, Windows 10/11 desktops, physical Macs.

## Smarter video editing and a free AI helper — 2026-11-05 (Claude Code)

- **Make a YouTube video → "How much should ClipForge edit?"** New default "Edit it for me": cuts long pauses and
  lone "um"/"uh" (checked in the sound, never inside a word), leaves out an earlier take of a line said again and a
  stumble said twice, fits the length you ask for (the opening, ending and must-keep words stay), shows your images
  over the video when their name is said, adds free background music that dips under speech and soft sound effects.
  "Fast-paced" cuts shorter pauses and zooms in a little on every other cut. "Keep my clips as they are" is the old
  rough cut. Everything left out stays in the sequence, switched off, so Put back restores it.
- **Free music and sound effects** are made on your computer by ClipForge (no downloads, no licence questions) and
  appear in Your media like any file.
- **Editor:** an "Edit it for me" panel (what was done, Edit it again with other choices as a version you can undo,
  YouTube chapters to copy), "Pictures over the video" (push-in or still, length, remove, add), a Pictures row on the
  timeline, and per-clip zoom and straight-cut joins.
- **Settings → AI helper (optional, free):** Ollama on this computer (download a recommended model, or import a
  .gguf file you already have), LM Studio, or a free key for Google Gemini, Groq or OpenRouter's free models; the
  Claude API is listed as paid. The helper reads only the words said, as text, and suggests what to leave out,
  where a picture helps, chapter titles and the music's mood; its answers are checked and limited. Without it the
  built-in editor decides alone.
- **Fixed:** captions dropped a word whose measured end ran into a cut pause (common with speech models).
- Details: docs/clipforge/SMART_EDITING.md.

## Mac: YouTube video links work again — 2026-11-05 (Claude Code)

- **Bug (released Mac build 2026.11.05):** a YouTube link ended with "No downloadable video was found on this page".
  YouTube serves picture and sound separately and yt-dlp joins them with FFmpeg, but yt-dlp only looked on the PATH.
  The Mac app keeps FFmpeg in `Contents/Helpers` (CLIPFOUNDRY_FFMPEG), and a Finder-opened app's PATH has no FFmpeg.
  yt-dlp's "ffmpeg is not installed" error matched no rule and was shown as "No video found".
- **Fix:** `media_import.public_extractor` passes `ffmpeg_location`, found the same way the renderer finds FFmpeg.
  A new reason, `tools_missing` ("Video tools missing"), names a really missing FFmpeg. The Mac app now installs
  `yt-dlp[default,deno]`: Deno (sandboxed by yt-dlp) and yt-dlp-ejs give yt-dlp its full YouTube support. Without a
  JavaScript runtime it asks only one YouTube player.
- **Tests run:** a new offline test with separate picture and sound and FFmpeg off the PATH, which failed on the
  released code and passes now. Local fast suite: 1,751 passed. A race in
  `test_unavailable_link_fails_readably_then_retry_succeeds_once` was fixed: it checked the job status before the job
  runner marked it done. The native Mac build (run 42068752230) passed, including the new bundled-app checks: the
  separate streams were joined by the bundled FFmpeg, and yt-dlp found the bundled Deno 2.9.8, which had no file access.
- **Not verified:** a real YouTube download. This environment can't reach YouTube, and GitHub's Mac runners get
  YouTube's "confirm you're not a bot" page for every player. No new Mac release was made (PR #22, not merged).

## Studio upgrade released: Mac and Windows downloads and the download page — 2026-11-05 (Claude Code)

- **Download page** (https://landryschreiner33-coder.github.io/ClipForge-AI./download/, `gh-pages` `138c4f7`):
  ClipForge 2026.11.05 for Windows and Mac, with exact sizes and SHA-256 fingerprints. The page is dark only like the
  app, shows the new
  studio (screenshots from a throwaway copy with made-up videos), explains video links, the editor, example videos,
  Find media and the Brain map, no longer mentions automatic video discovery, adds an FFmpeg step for Windows, a
  Questions section and a Support link. Yesterday's downloads stay under Older versions.
- **Mac:** unsigned personal preview DMG (Apple silicon, macOS 15+), the unchanged file from the tested build. macOS
  asks once before opening it (System Settings › Privacy & Security › Open Anyway).
- **Windows:** the setup ZIP now installs the upgrade, and its window says ClipForge. It was installed on a GitHub
  Windows runner over yesterday's version: your data folder and settings were kept, and it closed and reopened
  cleanly.
- Not verified: a real Mac or Windows PC, Windows security acceptance, processing a video on Windows, real uploads.
  The ChatGPT Sites page was not changed.

## Studio upgrade: the ClipForge name in the apps, and the full checks — 2026-11-05 (Claude Code)

- The Mac app's window, menus (About, Hide, Quit, Help), messages, Finder name and installer volume, the Mac and
  Windows start-up windows and the phone page now say **ClipForge**. Folder names, the app's internal id and saved
  passwords stay where they were, so nothing moves or has to be signed in again.
- **Fixed** after the full browser checks: the office's simple map (shown when the new graphics cannot load) froze
  with no robots as soon as one robot was queued; the Brain's saved-items list was read out as plain list items
  instead of buttons; and Missions said clips "can upload automatically" even when every post waits for your review.
- Checks actually run: fast suite 1,749 passed and slow suite 26 passed (audio, uploads, renders, restarts), on this
  machine and on GitHub's Linux runner. The Mac app was built, started and checked on a GitHub Mac runner
  (development copy, not notarized, not a release). Browser checks: read-only suite 52 passed, 7 failed; sandbox
  suite 84 passed, 2 failed; every remaining failure also fails on the commit this work started from. Browser checks
  that described screens this upgrade replaced were rewritten for the new screens; checks for the retired discovery
  setup screens are no longer run, and a new check makes sure those screens stay gone.
- Not verified: Windows packaging (no Windows runner here), installing or updating from the Mac installer, a screen
  reader pass.

## Studio upgrade: one Brain map of everything it holds — 2026-11-05 (Claude Code)

- Brain → Notes shows **styles, skills, example videos and the projects that used them** next to your notes. A line
  means something really happened: a project's recorded guidance used that style, skill, example or note, or a
  style was learned from that example video. Nothing is guessed.
- Pick any dot, or any item in the list beside the map (arrow keys move through it), to see what it changes, whether
  it is on, its revision, where it came from and which projects used it, with links to open them.
- **Save a style** is now a real form (on the Brain toolbar and the Styles tab): a name, the project types and the
  editing choices to remember.
- The map no longer glows on its own. When a project has just used something, that item shows "Just used" and a
  few rings, which stop off screen and with reduced motion. Busy maps show fewer labels until you zoom in.
- Tests actually run: `tests/test_brain_map.py` (2: links only from recorded use and provenance, other workspaces
  never shown, older snapshots read from their decisions, an example deleted with its style kept), with the guidance,
  example-video and rename suites (28 passed). Browser checks at 1440, 390 and 320 px on synthetic data: no
  sideways scroll, no console errors, list arrow keys, inspector details, Save a style, and no animation with
  reduced motion.
- Not built: clustering beyond showing 36 per collection on the map (the rest are listed), a virtualized list.

## Studio upgrade: dark only, Customize studio, keyboard and small screens — 2026-11-05 (Claude Code)

- ClipForge is **dark only**. The Light theme and the System choice are gone; a saved Light or System choice is
  dropped and every other choice (accent, spacing, clip mode) is kept. The saved colours are applied before the
  first paint, so nothing flashes light.
- **Customize studio** (the sliders button in the top bar, the Studio page, or Settings → Appearance) previews
  every change live and keeps it only on Save: four dark palettes (Studio, Midnight, Graphite, Plum), six accents
  including a new teal, spacing, text size (standard, large, larger), motion, office animation (Full, Calm, Low
  power), which Studio panels show and in what order (with presets and Move up/down buttons), the editor's panels,
  a compact or expanded office and pinned projects. Cancel or Escape puts everything back; Reset to defaults
  previews the defaults until saved. The panel says where each choice is kept.
- Pin a project from its card on the Studio page; pinned projects get their own section.
- The office stops drawing while it is scrolled off screen; Calm drops the lounge activities and Low power keeps
  the robots still. Office text follows the chosen text size.
- Keyboard: the Make menu now opens on its first item, moves with arrow keys and closes with Escape back to the
  button; the colour choices move with arrow keys.
- Fixed: the editor crashed on videos made before ClipForge recorded their guidance; a full video starting with a
  sound file made the Studio page ask for a picture that does not exist; "Follow system" was cut off in the
  office's Animations menu at larger text.
- Tests actually run: fast suite 1,747 passed on `61492d0`. New: `tests/test_theme_contrast.py` (every palette and accent against WCAG
  contrast, and no light theme), the Light/System migration and pinned projects in `tests/test_studio_prefs.py`,
  the full-video picture in `tests/test_studio_uploads.py`. Browser checks on a disposable data folder: 16 screens
  at 320, 390, 768, 1024 and 1440 px with standard and larger text (no sideways scroll, no console errors), and
  keyboard-only runs at 320, 390 and 1440 px with reduced motion (skip link, focus rings, Customize studio, Make
  menu, a confirm dialog, the office list, the editor; no endless animation with reduced motion).
- Not built: robot colour or badge variants (names only); separate page designs for phone, tablet and desktop
  (panel order and visibility differ per device class). Not run: a screen reader pass.

## Studio upgrade: Studio and the office in one place, truthful robots, rename every robot — 2026-11-05 (Claude Code)

- The app opens on **Studio**: Make clips, Make a YouTube video and Make clips from a video link; **Needs you** only
  when something has a fix (a stopped project, an editor question or proposal waiting for you, Autopilot's own
  list); the **current project** with its picture, the step it is really at, a Working, Queued or Waiting for you
  label, progress only when measured and the robots on it; the robot office (Expand opens it at `#/office`); recent
  projects and publishing. "Ready for your next video" when nothing runs. Navigation is Studio, Projects, Brain,
  Publishing, Accounts, Settings; older addresses redirect.
- The robots now show **your own work**, not only Autopilot's: Make clips projects by stage, clip and version
  renders, video links, rough cuts and renders, Find media downloads, example-video analysis and editor requests,
  each from its recorded row and only in your workspace. Queued is its own state. Paused shows only when Autopilot
  was started and then stopped, and never hides your own work. A failure shows for 30 minutes, then moves to the
  robot's log.
- Rooms follow the workflow: Intake, Media research, Story & analysis, Editing, Sound & captions, Brain, Quality &
  export, Publishing, Control room, Lounge. The 25 robots keep their ids; old room addresses still open the room
  that replaced them.
- Each robot's details show a **Log** (its Autopilot steps plus your work that ended in the last day), and the
  reason under a task now says what it is (Waiting for you, Queued, Waiting, Stopped, Blocked) instead of always
  "Blocked".
- **Every robot can be renamed**, the Brain Core included, from its details or the Team page; Reset all names asks
  first. Names reach the map, the list, accessible labels, handoff notes, activity and the Studio's team chips.
  Renaming keeps the open robot.
- Fixed: a Make clips project still downloading from a link made its picture request fail with a server error
  every few seconds on the Studio page.
- Tests actually run: fast suite 1,733 passed on `c80bcb8`. New: `tests/test_office_owner_work.py` (15),
  renaming and reset-all in `tests/test_studio_prefs.py`, the link-project picture in `tests/test_studio_uploads.py`;
  office tests updated for the new rooms and the queued state. Browser checks at 1440 px and 390 px on a disposable
  data folder: Studio, the office map and list, renaming from the details and the Team page, reset all with
  confirmation, waiting for you, the log; no sideways scroll and no console errors.
- Not built: separate states for waiting on a platform and waiting on a retry timer (the reason says which), and
  your own work in the shared activity feed (it is in each robot's log).

## Studio upgrade: tell the editor what to change — 2026-11-05 (Claude Code)

- Editor → Tell the editor what to change: a request becomes a proposal you check before anything changes. It lists
  each change in the editor's clip numbers (new order, trims, removals, captions, music dip, length) and is applied
  only with Apply, as a new version that Undo takes back. A proposal made before another edit is refused as out of
  date.
- Understood without AI: removing the silence at the start, shortening the introduction, moving or removing a part
  named by what is said in it or by its number ("move the summit part before lunch", "move clips 3 to 4 to the
  start"), dipping music further under speech, music level, caption size, position and on/off, and transitions.
  When a part comes up in several places, one short question offers the choices; no time is guessed.
- Anything else goes to the AI service chosen in Settings → AI, only when one is set up, as text: the clip list with
  ids and times, the words said, the current settings, the project's Brain choices and the request. Never the video,
  sound, file paths or keys. The screen says what was sent and whether it stays on the computer. The answer must be
  operations from a fixed list or one question; it is checked exactly like a manual edit.
- Limits: a timeout (60 s by default), cancel, a daily limit (40 per workspace by default; both in Settings → AI), a
  cache for the same request on the same version, and no automatic retries. A restart while waiting is reported
  and the request is not sent again.
- Tests actually run: fast suite 1,716 passed; new `test_studio_edit_requests.py` (14 fast, with a fake AI
  service) passes. The panel and settings were checked in a browser at 1440 px and 390 px (no sideways scroll, no
  console errors).
- Not verified: answers from a real model (no AI service is reachable from this environment). Not built: AI story
  segmentation and outlines, and a preview render of a proposal before Apply.

## Studio upgrade: Find media with license records and credits — 2026-11-05 (Claude Code)

- Editor → Find media: Images, Footage/B-roll, Music and Sound effects from Openverse, Wikimedia Commons and Pexels,
  searched together. Each card shows a preview (served through ClipForge, never loaded straight from the source),
  length or size, creator, source, license and restrictions; filters for shape, length and license. Picking a result
  copies the file into Your media; adding it to the edit is a separate step.
- Imports are durable, cancelable jobs. Downloads go through `netguard` (address pinned, redirects re-checked), with
  a size cap per kind, a content-type allow list and an FFmpeg decode check. Each file gets a provenance record
  (source, item, creator, license and version, terms, credit, retrieval time, hash) in `asset_sources`, separate from
  the Brain. Switching a source off or the source removing the item never breaks media already imported.
- Terms: unknown or unfit terms are labelled; importing one needs the owner's written reason and holds automatic
  posting for that render. Titles and descriptions from sources are inert text.
- Credits: an editable list per project, carried into the render info, a `credits.txt` beside each final render,
  and the description of automatic uploads. A credit the license requires must keep the creator and license.
- Settings → Media sources: on/off per source, Pexels key sealed with the other secrets and tested without showing
  it, limits and terms links. A 429 pauses only that source for its Retry-After time; searches are cached.
- Supporting media per project (Make a video, and the editor): off, suggest for review (default), or add
  automatically as one undoable version (images after the clip where a repeated word is said; music looped and
  ducked). Make a video also has a Music choice: none, your own, or find some.
- Fixed: a thumbnail that FFmpeg failed to write was recorded anyway and its route returned 500; it is now skipped
  and the route returns 404.
- Tests actually run: fast suite 1,702 passed; new `test_studio_media_sources.py` (15 fast) passes; new slow
  `test_studio_media_render.py` passes (rain sound and landscape image found, auditioned, imported, placed,
  reopened offline with the source off, rendered with timing and credit intact).
- Not verified: the live Openverse, Wikimedia Commons and Pexels APIs (unreachable from this environment; tests
  use recorded responses shaped like their documentation), Content ID behaviour of any imported file.

## Studio upgrade: example videos measured and applied — 2026-11-05 (Claude Code)

- Brain → Example videos: upload an example, say what you like (overall, pacing, captions, framing, sound), pick an
  optional range, mark it as one to avoid, and choose where it applies (only when chosen, every project, or some
  project types). A durable, cancelable job measures it (`studio/reference_analysis.py`, analyzer `measure-1`):
  cuts, dissolves and fades from 10 fps frame comparison; framing and caption band, position and size from stills;
  speech, music level and the music dip under speech from three sound bands. Each observation is labelled measured
  or estimate and links to the times it came from. No AI model watches or hears the video, and the screen says so.
- Analyses are cached by file hash, ranges, analyzer and speech source; Reanalyze adds a revision. Supported choices
  (shot length, caption position and size, music dip depth, aspect, frame rate, framing) can be corrected and saved
  as an Example style with provenance (example, analysis revision, method, corrections).
- Guidance precedence: project choice, then an example chosen for this project, then the style, skills, examples set
  to apply broadly, Brain notes, Settings. Make clips and Make a video offer "Use an example" and show which example
  (and which style revision) each choice came from. The example's own footage and sound never enter a project.
- Fixed: Make a video used to send its default answers as project choices, so styles, skills and examples never
  changed aspect, feel, captions, caption size or position, or frame rate.
- Tests actually run: fast suite 1,687 passed; new `test_studio_reference.py` (15 fast) passes; new slow
  `test_studio_reference_render.py` passes (an example with 1.5 s shots, lower-third captions and a 12 dB music dip
  is measured, saved, applied to a new project, and the rendered dip is within 3 dB of the measured value).
- Not verified: real Whisper transcripts (fixture transcripts used), examples longer than a few minutes on a real
  device, a vision-model pass (not built; the measurements do not read on-screen text or recognise objects).

## Studio upgrade: full-video editor with audio tracks and revision safety — 2026-11-05 (Claude Code)

- Engine `ffmpeg-v2` (plan schema 2) renders the picture in cached pieces of at most two inputs, joined by byte
  concatenation, so long timelines no longer build one huge filter graph. Element positions come from a whole-frame
  map, so sync does not drift. Older plans upgrade on load (a music bed becomes a music audio item).
- Audio: voiceover, music and effect items with start, trim, gain, fades, loop and a clip anchor; four track
  controls (source, voiceover, music, effects); a block mixer in 10 s blocks. Ducking is now measured from the
  speech track (frames above the speech level lower the music by the chosen depth, default 12 dB). This replaces
  the sidechain compressor, which only lowered music by 0 to 5.6 dB in a measured check.
- Editing: add footage, images and sound after the rough cut (insert or replace), undo and redo, restore and named
  versions; every change is a new immutable revision. A preview with the same plan is reused, and the screen marks
  an out-of-date preview. Free disk space is checked before a render.
- Screen: timeline with paged sequence, clip inspector, Sound panel with tracks, Your media upload with three
  parallel uploads you can stop and resume, Look (frame rate, caption size and position), Versions.
- Tests actually run: fast suite 1,672 passed; new `test_studio_editor.py` (9 fast) and
  `test_studio_editor_render.py` (3 slow: 120 clips frame-exact, three audio roles with at least 6 dB ducking,
  media added after the rough cut through the API) pass; `test_studio_video.py` (slow) passes. Editor screen checked
  in a browser at 1440 px and 390 px with no horizontal scroll and no console errors.
- Not verified: memory use on a real device with hours of footage, real Whisper transcripts (model download blocked
  here, fixture transcripts used), waveforms and text overlays (not built yet).

## Studio upgrade: video links in Make clips, discovery retired — 2026-11-05 (Claude Code)

- Make clips offers Video file and Video link; a link keeps the chosen mode, style, skills and destinations through a
  durable, cancelable, resumable download into a private asset (`studio/link_import.py`).
- Automatic source discovery is retired (`config.DISCOVERY_RETIRED`, one-time migration with an audit event; nothing
  deleted). Setup, Settings and Missions no longer offer topics, search keys or discovery controls.
- Tests actually run: baseline fast suite 1,630 passed on `6c3f8d9`; new `test_studio_links.py` (29) and
  `test_discovery_retired.py` (4) pass; 148 product-default suites pass with discovery retired.
- Not verified: real YouTube downloads (host unreachable here), browser checks of the changed screens, slow suite.

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

- Merged PR #16, #17 and #18 into the default branch.
- Fixed the Mac smoke checks for the ClipForge name; they now pass at any window width.
- Published the Windows setup ZIP and the Mac DMG, both built from `06f459e`.
- Added the shared GitHub Pages download page at `/download/`. It is data-driven from `releases.json` and checked by
  `build.py --verify`.

Tests:
- Fast 1,630 and slow 21 passed locally.
- GitHub run 41899130825 passed the native Mac build and smoke checks plus fast and slow pytest.
- 77 Windows launcher tests passed, and every payload file was compared with the commit.
- All four listed downloads were re-downloaded and matched.

Not verified: native Windows, a physical Mac, real accounts, and Defender or Apple acceptance.

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

## ClipForge studio, phases 0–6 — 2026-11-04 (Claude Code)

Built the ClipForge prompt (`docs/CLIPFORGE_CLAUDE_PROMPT.md`) on `claude/new-session-b9itcy` (draft PR #16).

What was built:
- **Cloud mode:** owner-only OIDC sign-in, server sessions, CSRF/host/origin guards, strict CSP, workspace ownership on
  every ID, AES-256-GCM secrets.
- **Accounts:** multiple YouTube/TikTok connections, migrated without changing tokens.
- **Server plumbing:** resumable private uploads; durable studio jobs; backup/restore/retention CLI.
- **Guidance:** precedence with frozen snapshots and "Used from your Brain"; saved styles and declarative skills.
- **Full stories:** complete stories as 9:16 clips, with destination eligibility (never truncated).
- **Full YouTube video:** assembly on a versioned FFmpeg engine with revisions.
- **Interface:** the new ClipForge shell; theme/layout prefs; robot display names; the visible rename.

The office map and robots are unchanged. Desktop data, Keychain/DPAPI names, settings keys, the publish header and
old addresses are kept.

Final regression fixes:
- Link/transcript import is reachable at `#/create/link`.
- Make clips previews guidance with a GET.
- Startup robot-name loading no longer redraws the page and discards a just-chosen file.
- Remaining Clips/Queue labels now say Projects/Publishing.
- Motion stays the per-browser Animations choice.
- The sidebar is narrower below 1366 px, so the office map keeps its minimum width.
- Browser specs follow the new navigation.

Tests: see `docs/IMPLEMENTATION_STATUS.md` (2026-11-04 test log). Not verified: real sign-in, deployment, uploads,
transcodes, native Windows/Mac hardware, throughput. FilmCraft stays Blocked (build not permitted here). No real
posts, no deployment, no owner media.

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


Development checkpoints made by AI assistants, newest first. Each one says what changed, why, what was actually run
and what was not. The same checkpoints, in machine-readable form, are in `.clipfoundry/ai-change-log.jsonl` (shown
read-only in Settings → Advanced → Dev Log). Work before October 7, 2026 is not repeated here: it is recorded in
`docs/IMPLEMENTATION_STATUS.md` (plan, matrix and test log) and in the Git history.

Commit ids are snapshots of a branch at the time of writing; fetch before relying on them.

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


## 2026-10-19 · Brain-guided creation, moving crops and spaced publishing

* **Changed:** platform-tagged Brain lessons apply across subjects, manual clips retain real ranking provenance,
  and the editor lists used lessons. Automatic crops follow measured visual motion when faces disappear, with
  cache invalidation and recorded quality-gate evidence. Default posts are 30 minutes apart; automatic pending
  collisions and already queued transfers respect spacing across restarts. Positive custom gaps/explicit rescheduled times
  and active/uncertain transfers remain intact. Existing valid input reuse statements carry through Queue
  review; generated repairs require fresh exact-file checks and approval, without retyping source reuse.
* **Why:** owner reports unused Brain guidance, static crops, simultaneous schedules and repeated Queue reuse
  questions for supplied inputs. No local-file ownership assumption or new old-backlog grant was introduced.
* **Validation:** Final full fast suite: 1,504 passed, 18 slow deselected in 687.23 s. All 18 selected real-FFmpeg/synthetic-media and restart cases passed: 15 in 766.75 s before stopping the remaining legacy zero-gap fixture wait, then its corrected three cases in 455.55 s. TypeScript/production build passed (6.03 s); all 61 built-browser checks passed in 170.29 s. All 204 other frozen Python/source/test/bootstrap/dependency files and 17 tested built files retain their hashes. Only the slow-loop fixture changed after the fast/first-15-media checks, to explicitly select zero spacing for compressed test time; all its three affected cases were rerun. Production source stayed unchanged. The final 205-file manifest matches the delivered source. The final source adds the reviewed alternate-version repair guard, covered by the final full suites and 62 focused checks; the already completed browser run covers unchanged frontend paths. Earlier full attempts stopped for evidence/pacing/version corrections are not final evidence. Actual moving-frame output, saved Brain ranking influence, input-bound reuse, concurrent/restarted pacing, platform waits and exact fake uploads were checked in disposable profiles. No owner profile, real social upload, native Windows/RTX3050 or 24-hour soak was tested.
* **Delivery/limits:** readable source setup is pinned separately with managed release history preserved; no
  custom EXE rebuild or security setting changes. Native Windows/GPU, owner profile, real platform delivery,
  approval and 24-hour operation are unverified. Existing media/uploads remain unchanged.

## 2026-10-19 · Matching TikTok icon across the app and public website

* **Changed:** reuse the exact submitted 1024-square robot PNG for app branding, the public site's headers and
  browser tabs, and the helper's single recommended icon. Form packs include matching PNG/ICO website assets;
  local legal previews serve them correctly. Legacy icon download endpoints remain compatible.
* **Published:** branding-only `gh-pages` revision `80a6a3f4782de64fed88a06d9db54533de4869bd`; successful
  Pages deployment and exact readback of all eight source files. Preserve existing TikTok URL verification,
  `.nojekyll` and product/legal copy. The public-site fix needs no desktop reinstall.
* **Why:** TikTok's reviewer found the submitted robot differed from the website's old filmstrip logo/favicon.
* **Validation:** TypeScript/production build passed (5.11 s). Final affected Python suites: 41 passed in 6.89 s.
  Twelve Chromium checks cover all three public pages at desktop/mobile widths in light/dark mode; the built app
  header, favicon, helper preview and download also match the exact submitted PNG. All six ICO frames match nearest-
  neighbor canonical pixels. The broad fast run completed with 1,489 passed, one obsolete website-readiness fixture
  failure and 17 slow deselected in 537.24 s. It had already collected the older fixture, which forbade added assets
  and all image elements. The corrected fixture permits only the bundled canonical image and passes in both the
  41-case affected-suite rerun and a final individual rerun. All 326 frozen code/test/build/website hashes match.
  Exact published source readback and successful Pages deployment were verified. The media/Autopilot pipeline and
  dependency/bootstrap files are unchanged; slow media and broad browser suites were not rerun for this branding
  correction.
* **Limits:** direct live-site HTTP is unavailable under this environment's network policy. No TikTok portal
  submission/approval or real account upload verified. Existing installer artifact remains pinned to its prior
  revision; media/Autopilot/dependency behavior is unchanged.

## 2026-10-19 · Verified Windows Python selection and preserved environment recovery

* **Changed:** standard-library bootstrap verifies actual standard 64-bit CPython 3.12/3.11 for Windows AMD64;
  both readable installer and app launcher share the check. Compatible `.venv` is kept; incompatible copies get
  unique backups before fresh creation, failed partials are preserved with rollback where possible, and a known
  active environment blocks replacement. Missing supported Python yields side-by-side official-install guidance.
* **Why:** owner screenshot reports no matching CTranslate2 distribution. Its exact runtime/index is unknown;
  current CPython 3.13/3.14 AMD64 wheels exist, so this uses the app's supported runtime policy without claiming
  those versions inherently lack wheels. Native ARM64/32-bit lack the applicable wheel.
* **Preserved:** owner data/Brain/accounts/clips, GPU/dependency pins, rendering, frontend and submitted-video
  upload behavior; no automatic global Python installation, PATH/registry/security change or old-environment
  deletion. Previous release evidence remains separate.
* **Validation:** Full fast regression suite: 1,489 passed, 17 slow deselected in 527.16 s. All 203 frozen source/test/bootstrap/dependency hashes matched. The 38 focused bootstrap checks passed in 3.54 s, including real disposable-host venv creation, reuse and replacement, preserved dependency markers/data, failure rollback, active-process and concurrency guards, exact runtime checks and read-only probes. A 19,230,360-byte CPython 3.12 Windows AMD64 CTranslate2 4.8.3 wheel was downloaded and its SHA-256 matched PyPI (b5daf0758d522a422c76e53eb02ce9f42465a9aba938a86b27249fb5db2571b9). No dependency/GPU pins, app pipeline or frontend files changed; all 17 previously browser-tested built files retain their hashes. The previous 17 media and 59 browser results apply to unchanged scopes and were not rerun. The readable setup is separately pinned to this exact app commit; its delivery proof records installer/helper tests, full source hashes, managed-release history and immutable download readback. No native Windows/owner install, CUDA/RTX3050,
  real upload/Defender or 24-hour run verified. Linux cross-pip dry runs are not native Windows proof.

## 2026-10-19 · Submitted videos to Brain-guided clips and automatic YouTube uploads

* **Changed:** Missions accepts a recorded-video link/file with **Make & upload clips** or **Make clips only**.
  Submitted input is now the default; periodic/queued search and watched-folder admission stop without deleting
  old data or removing optional discovery. Relevant supported Brain guidance uses Settings fallback.
* **Authorization:** one explicit input-scoped request records destination/audience, genuine kids answer and
  reuse basis outside Brain. Acquired original/project/current terms and every final file/payload are bound.
  Only its newly generated qualifying YouTube posts can auto-approve; old backlog/later inputs/TikTok stay separate.
  Source requests do not change ownership or global audience/standing consent. Stop/pause/cancel, credit, quality,
  source drift, waits and uncertain-session/no-duplicate handling remain. An accepted-input enqueue gap recovers
  durably without reviving attempted/canceled jobs. Retention keeps referenced source/audit records while
  clearing stale API data and ordinary unused discovery; its foreign key no longer interrupts maintenance.
* **Audio:** retain measured downmix/peak/clock/track corrections and exercise actual Brain-guided rendered AAC
  through the exact fake YouTube upload bytes and restart. Existing distortion and real platform processing are
  not guaranteed repaired. Existing media/uploads remain unchanged.
* **Validation:** Final full fast suite: 1,451 passed, 17 slow deselected, in 676.07 s. Final full real-FFmpeg/synthetic-media and restart suite: 17 passed, 1,451 deselected, in 934.97 s. TypeScript and the production build passed (10.00 s). All 59 final built-browser checks passed in 161.55 s. The final fast suite used 198 frozen Python source/test files. All production and selected media-test sources stayed unchanged during the full media run; 81 frontend source and 17 built-file hashes stayed unchanged through the final browser checks. A deselected fast retention fixture's timestamp setup was corrected before the final fast run; the media run's production/selected sources were unaffected. Focused checks also passed: 60 submission/consent, 79 final status/routes/legacy readiness, 29 advanced-route/legacy, 119 legacy intake/scheduler/publishing, three new actual-media and 26 legacy audio/quality and nine retention checks. The three new media cases use relevant saved Brain guidance, real caption/AAC rendering, exact fake-upload bytes and restart without duplicates, including the broad YouTube switch off and TikTok enabled. Earlier full attempts were interrupted before the final route/status/retention corrections and are not final evidence. Tests use isolated profiles, synthetic media and fake platforms only. The readable source setup is pinned separately to this committed app tree with the tested frontend manifest; its delivery verification records exact archive hashes and source revision.
  No real owner account/Windows/RTX3050/Defender/24-hour run verified.

## 2026-10-15 · Failed search keys and post-only reuse explanations

* **Tool:** Codex. **Branch:** `codex/brain-graph-quality-discovery`. **Base:** `0c2729d`.
* **What changed:** bounded same-account OAuth refresh, safe key setup/restriction errors, explicit uncached saved
  search tests, credential-current results, strict responses and quota-aware concurrency. Key whitespace handling,
  provider-specific/review-mode diagnosis and clear post-only reuse text with independent Brain boundary tests.
* **Why:** owner reports no clips, clarifies both keys fail and asks that reuse entries not be saved in Brain.
  They confirmed these appear only on the post. No automatic Brain write existed; deliberate notes stay intact.
* **Validation:** Final full fast suite: 1,373 passed, 14 slow deselected, in 755.18 s. Final full real-FFmpeg/synthetic-media and restart suite: 14 passed, 1,373 deselected, in 945.34 s. Final TypeScript and production build passed (5.17 s). All 51 final built-browser checks passed in 167.41 s, with all 17 built-file hashes unchanged. Focused provider verification: 77 passed in 7.83 s; focused diagnosis/health/phone: 88 passed in 11.26 s; independent saved-search/Brain separation checks: 113 passed in 22.43 s before the final wait-order correction, then 53 passed in 4.06 s including both same-key full-server-wait regressions. All 261 frozen production/frontend/Python-test hashes remained unchanged through final verification. Tests used isolated data, synthetic media, MockTransport and fake platforms. No owner keys, Windows profile/RTX3050, actual search-service account, real upload, Defender acceptance or 24-hour soak was verified. Permission answers were already post-only; the update clarifies and verifies that boundary.
* **Not verified:** owner keys/provider setup, Windows/profile/RTX3050, real uploads or a 24-hour soak.

## 2026-10-15 · Audio, comments, ongoing search and live/Windows recovery

* **Tool:** Codex. **Branch:** `codex/brain-graph-quality-discovery`. **Base:** `11bdb435`.
* **What changed:** stereo downmix before normalization, final post-gain peak control, shared audio-clock/track
  handling; strict real kids answers and truthful YouTube comments/audience explanations; independent provider
  waits, recurring capacity-aware search, bounded pagination and saved-signal refill; visible supported search
  keys/free-only controls; safe paired HLS and bounded empty-ended-stream archive recovery; scoped Windows
  10054 cleanup with Python-version-compatible detachment. Added concrete `CLAUDE_HANDOFF.md`.
  Health/phone cadence reads remain pure; host-only deadline reconciliation also handles a full queue draining.
* **Why:** owner confirmed distorted uploaded audio, comments off on some posts, searches stopping and the two
  supplied live/Windows errors. Concrete defects were reproduced locally; no owner media/account was accessed.
* **Validation:** Final full fast suite: 1,278 passed, 14 slow deselected, in 579.81 s. Real-FFmpeg/synthetic-speech media and restart verification covered all 14 scenarios across two runs: the full attempt passed 12 with 2 repeat-discovery timeouts (1,274 deselected, 1153.68 s); after correcting only the compressed-clock fixture's discovery-list cache expiry, both private/public repeat scenarios passed in 374.57 s. This was not a single all-green full-media run. Production cache/quota policy and all real render, final-report, exact-upload-byte and restart assertions were unchanged by that fixture correction. Final production build: 10.32 s; TypeScript passed. All 43 final built-browser checks passed in 93.25 s, with all 17 frontend hashes unchanged. Focused independent bugfix verification: 73 passed in 32.22 s, including measured encoded mono/surround audio, exact fake-upload bytes, real split-HLS synchronization and real asyncio cleanup compatibility. Windows/phone focused verification: 63 passed in 10.25 s; earlier discovery focused: 89 passed in 11.12 s. The final queue-drain deadline correction and surrounding discovery checks passed 61 tests in 9.13 s. Final comments/search checks after the current-label correction: 47 passed in 22.85 s. The final read-only health/phone/search correction passed 77 checks in 16.64 s, with database-unchanged assertions intact. The complete media run used the final audio/live/publishing code, preceding only the pure health-cadence refactor and its four new fast tests; all 39 media-scope source hashes remained unchanged. That refactor is covered by the final full fast run and 77 focused checks. The earlier interrupted suites preceded final deadline/returned-label corrections and are not final evidence. No real owner Windows profile/media, RTX3050, live provider key, account upload or 24-hour soak was tested.
* **Not verified:** owner Windows runtime/profile/original audio, RTX3050, real provider keys/accounts/uploads,
  actual platform comment settings, native Windows/Defender or a 24-hour unattended soak. Existing published
  audio is not rewritten and source distortion cannot be reconstructed.

## 2026-10-15 · Faster review, bulk approval and consistent Brain guidance

* **Tool:** Codex. **Branch:** `codex/brain-graph-quality-discovery`. **Base:** `ec20aec`.
* **What changed:** inline Queue video/text previews, Quick approve and selection of up to 50 YouTube posts.
  Permission presets replace required typing, and one combined consent replaces duplicate checkboxes. Batch
  approval uses a fixed, expiring, account/file/source/terms/payload/audience/check-bound preview, explicit common
  permission basis and any missing kids answer; each success receives its own manual approval. Future posts gain
  no permission. Final guarded writes reject changed or active work without hashing under the database lock.
  Partial results retain skipped posts for review; exact retries return prior results. Known credit, physical
  quality, grounded text, post audience/time, platform waits and duplicate protections remain. TikTok stays
  individual. Single review and current per-post assertions retain exact-payload confirmation.
  Brain matching now retains source-title/spoken context through candidate generation, ranking, planning and
  rendering, including resume/live. Natural caption declarations and example feature fields are recognized;
  disliked-example observations no longer become desirable ranking traits. Recognized effects/length hints are
  shown honestly, Settings remain the fallback and explicit clip edits win. Unsupported text stays searchable.
* **Why:** the owner finds repeated review too slow and reports saved Brain notes/examples not changing clips.
* **Validation:** Final full fast suite: 1,195 passed, 11 slow deselected, in 739.22 s. Final real-FFmpeg/synthetic-speech media and restart suite: 11 passed, 1,195 deselected, in 1024.81 s. This includes exact selected-post fake uploads/restart and two actual Brain-guided/owner-overridden caption renders with persisted provenance. Final production build: 9.44 s; TypeScript passed. All 31 final built-browser checks passed in 95.78 s, with all 17 frontend hashes unchanged. Focused checks: 42 bulk, 19 independent approval audit and 86 Brain/context checks passed. Browser fixture wording/details visibility and async readiness were corrected before the final run; earlier interrupted or fixture-correction runs are not final evidence.
* **Not verified:** the owner's PC/profile, native Windows/GPU, real social uploads or a 24-hour soak.

## 2026-10-14 · Prepare and schedule for individual reuse review

* **Tool:** Codex. **Branch:** `codex/brain-graph-quality-discovery`. **Base:** `d0b7102`.
* **What changed:** review before publishing defaults on. Bounded quality-first discovery and local posting plans
  can include accessible unblocked sources with unrecorded reuse terms. Rights labels remain truthful, and new
  posts wait for manual approval. Queue shows proposed times without calling them approved uploads; review drafts
  do not expire. Uncovered posts need an individual owner reuse statement and basis bound to the exact source,
  terms/credit, post, account, audience, platform, bytes/version, text and options. Known required credit and
  physical-media checks remain binding. Old unstarted automatic approvals return to review atomically, retaining
  time, text, privacy and publication identity. Queued work, retry and not-published recovery cannot restore an
  automatic upload grant. Unknown outcomes retain their session and use account-bound readback. Separate manual
  publishing cannot borrow an assertion. Explicitly disabling review restores the existing guarded automatic mode.
* **Why:** the owner wants to inspect finished clips and confirm reuse before approving publication, rather than
  have missing records prevent a review plan or let standing permission authorize new uploads.
* **Validation:** Final full fast suite: 1,112 passed, nine slow deselected, in 529.54 s. Final real-FFmpeg/synthetic-speech media and restart suite: nine passed, 1,112 deselected, in 879.93 s, including the new review/owner-confirmation/exact-byte upload/restart loop. Final production build passed in 8.79 s; 12 built browser checks passed in 40.23 s, with all 17 frontend file hashes unchanged. Focused checks: 95 publishing/reuse checks; 64 scheduler/public/manual checks; final 46 review/current-terms checks; 107 legacy recovery checks; and eight final independent audit/fixture checks. The initial full fast attempt found an older fixture approving an unverified channel claim; its corrected exact-video verification retains all connection, quota, hash, explicit-block and no-upload assertions. Earlier full attempts were stopped before final corrections and are not final suite evidence.
* **Not verified:** the owner's Windows profile, native Windows/GPU operation, real platform uploads or a 24-hour soak.

## 2026-10-13 · Continuous eligible uploading and Brain/manager handoffs

* **Tool:** Codex. **Branch:** `codex/brain-graph-quality-discovery`. **Base:** `718358f`.
* **What changed:** app daily source/clip/platform caps default to 0 (unlimited), with all-day earliest-slot
  posting. A recorded one-time volume amendment preserves existing account/audience/kids permission and old
  posts, while future owner limits persist. Bounded search/queue/quality/API/cost/platform holds remain active.
  Uploadable-only broad discovery prioritizes verified own/agreed/CC media and explains local-only clips;
  legacy local-only finds cannot monopolize capacity. Past-due eligible approval holds and lost replacement
  times recover; reported platform zero holds approved dispatch without disrupting an active transfer.
  Current reuse/credit checks bind to both reports and actual upload text. Missing credit returns to editable
  review; proven unstarted row synchronization retains upload identity, route and current feature evidence.
  Private/canceled/manual/started/uncertain work remains protected. Count-only real Brain consultations now
  appear separately from mature-result learning. Explicit fresh manager/boss handoffs respect newer checkpoint
  outcomes, actual job ownership and Pause/Reduced/hidden/offline/history guards. Quiet rooms explain idle state.
* **Why:** the owner reported missing-permission posting holds, requested no app daily cap and continuous work,
  and found the office's Brain/handoffs misleading. No missing reuse or account permission was fabricated.
* **Validation:** Final fast suite: 1,047 passed in 556.14 s; eight real-media/restart checks passed in 836.38 s.
  Final production build passed in 6.16 s; 11 final built browser checks passed in 94.42 s, matching all 17 file
  hashes. Earlier 12 choreography checks, six department, three motion and six lounge checks passed. Final
  reuse/publishing: 93 passed; public/manual publishing: 34 passed. New current-terms regressions: 26 passed;
  independent continuous: 12 passed. Root phone checks: 56 passed. Initial full fast run found ten stale fixtures;
  updated local-discovery/finite-plan/current-report fixtures retain all permission/bytes/version/quality/wait
  checks. No owner Windows/GPU, real platform upload or 24-hour soak was tested.
* **Not verified:** real owner Windows data/runtime, RTX3050, actual account posting/visibility or a 24-hour soak.
  No real publishing, account/privacy change, spending, media deletion, security exclusion or deployment occurred.

## 2026-10-13 · Finished clips reach YouTube scheduling

* **Tool:** Codex. **Branch:** `codex/brain-graph-quality-discovery`. **Base:** `987ebb2`.
* **What changed:** reusable accessible discovery candidates take priority; parked permission/file waits cannot
  monopolize the bounded workable queue or displace them. Finished recorded clips get immediate durable handoff
  before batch yielding. Bounded reconciliation recovers proven old handoffs while preserving canceled work,
  manual edits, live decisions and existing packaging states. Parent cancellation/Pause is rechecked after
  fingerprinting. Stale consent no longer hides pending approval reminders; Private permission requires a
  confirmed upload destination too. Setup embeds audience and separate YouTube permission controls for connected
  accounts. Read-only readiness/derived warnings explain finished-clip holds without depending on a working
  scheduler; unavailable times are not called scheduled, and newer preparation overrides historical failures.
* **Why:** the owner had finished clips after an all-day YouTube-only run, with no posts or Needs you explanation.
  The exact owner-PC hold remains unknown; code failures were reproduced on disposable data and corrected.
* **Validation:** Final full fast suite: 958 passed, eight slow deselected, in 489.73 s. Final real-FFmpeg/synthetic-speech
media and restart suite: eight passed, 958 deselected, in 695.71 s, including Public/Private and live recovery
loops. Final production build passed in 3.98 s; seven built-interface browser checks passed in 43.6 s. All 17
tested built-file hashes match. Final focused handoff/readiness/simple-page checks: 88 passed in 24.79 s.
Discovery focused checks: 99 passed in 19.36 s; four new behavior regressions fail on the original source.
Scheduler/consent checks: 73 passed, one slow deselected, in 78.53 s. Independent review found the late-
cancellation race; its three corrected regressions passed and no material findings remain. No real owner data,
Windows/RTX3050, platform upload or 24-hour soak was tested.
* **Not verified:** owner Windows data/runtime, RTX3050, real platform accounts or a 24-hour unattended soak.
  No real publishing, consent/account change, spending, firewall/router change or deployment occurred.

## 2026-10-13 · Private phone status companion

* **Tool:** Codex. **Branch:** `codex/brain-graph-quality-discovery`. **Base:** `4838aa8`.
* **What changed:** default-off Tailscale/home-Wi-Fi listener serves a mobile read-only dashboard, separate from
  desktop APIs and media. Guarded owner controls issue single-use expiring pairing codes, enable/disable access
  and revoke up to eight hashed 90-day device grants. Keys use authorization headers and opt-in browser storage;
  codes and keys never enter URLs/logs. Listener failures leave the desktop functional; custom desktop ports,
  restart and shutdown cleanup are covered. Counts, progress, status and attention policy follow actual app
  state. Mobile polling handles background/offline/reconnect/expiry, clears unauthorized data and escapes text.
  Desktop setup prevents old polls from overwriting newer actions. Setup/privacy/architecture docs are updated.
* **Why:** the owner wants to see how ClipFoundry is doing from a phone, including away from home.
* **Validation:** Final full fast suite: 869 passed, eight slow deselected, in 386.91 s. Final focused phone tests: 55 passed in 9.03
s; 75 existing local-guard/office/Autopilot regressions passed in 30.43 s before the final attention refinement.
Final built phone browser suite: ten passed in 12.6 s. Final built desktop setup/race checks: two passed in 27.6 s.
Production build passed in 3.85 s; all 17 built-file hashes were recorded. No actual phone, Windows/Tailscale
connection or real account was tested.
  Initial full fast suite: 865 passed before the final attention-policy refinement. No processing/publishing
  handler changed, so no new slow media run. Installer tests and exact bundle integrity are recorded separately.
* **Not verified:** native Windows/RTX3050, actual phone browsers, real Tailscale account connectivity/firewall
  behavior or platform accounts. No real upload, account change, router/firewall configuration or cloud hosting.

## 2026-10-13 · Automatic Brain guidance and supported integration cards

* **Tool:** Codex. **Branch:** `codex/brain-graph-quality-discovery`. **Base:** `28aee85`.
* **What changed:** enabled saved Brain material participates automatically in new clip selection/rendering,
  with Settings fallback. Local recognition covers supported caption/pacing controls and ranking priorities;
  explicit choices override prose. Good examples contribute measured duration hints blended once with the
  original target. Disabled/paused material remains inactive. Revision-specific selection/render decisions merge
  without mutating shared snapshots. Manual editor overrides retain precedence; existing clips/posts persist.
  Brain shows recognized choices, automatic activation and unsaved drafts, with no separate approval action.
  Integrations removes seven inactive connector placeholders while retaining real platform permission/limit
  messages. Raw Brain material is never executed or sent to an AI; only fixed priority names accompany its
  existing transcript payload. Privacy/product documentation describes the changed behavior.
* **Why:** the owner reported stored Brain material was not being used and requested automatic use even with
  sparse knowledge, combined with Settings, plus removal or repair of unsupported integration entries.
* **Validation:** Final full fast suite: 814 passed, eight slow deselected, in 349.16 s. Final focused Brain/provider/blueprint/artifact regressions: 96 passed in 43.45 s. Actual-FFmpeg/synthetic-speech media/restart suite: eight passed, 811 deselected, in 710.71 s before the final example-blending/provenance review fixes; those final fixes are covered by the final 814/96 runs. Final controlled browser batch: eight passed in 45.5 s against the final built interface. Build passed in 6.44 s. No real uploads, accounts, Windows/RTX3050 execution or 24-hour soak were tested.
  Final fast/focused coverage includes the last example-blending and shared-provenance fixes. Media ran before
  those last fixes; all eight passed using existing portable speech tools and adequate workspace temp storage.
  Eight final browser checks cover activation, real lookup, unsaved drafts, stale-revision recovery, graph
  accessibility/mobile/motion/bounds and removal of placeholders. The local report collector separately passes
  synthetic privacy/GET-only/custom-port/offline/invalid-port checks. Packaging integrity is recorded separately.
* **Not verified:** native Windows installation/runtime, RTX 3050 CUDA/NVENC, actual account grants/visibility,
  model quality with owner clips, visual learning from examples, or an actual 24-hour soak. No real posts,
  account-permission changes, dependency upgrades, purchases or deployment.

## 2026-10-13 · TikTok setup, visible Brain graph and focused discovery

* **Tool:** Codex. **Branch:** `codex/brain-graph-quality-discovery`. **Base:** `8999e5f` from the default branch;
  PR #14 is already merged. **Result:** the commit containing this entry.
* **What changed:** TikTok form helper supplies copyable app details, current-port Desktop callback, two 1024×1024
  PNG icons, products/scopes and a form-pack export with local draft website/legal pages. Inbox, Direct Post and
  optional statistics request only their chosen permissions after applying, saving and reconnecting. Exports
  exclude credentials, tokens, account identity and owner media; URL checks are syntactic, with no network fetch.
  The helper prepares drafts only when opened and does not claim registration, review approval, hosting or an
  actual integration demo.
  Brain's interactive graph shows actual saved notes/examples/preferences, shared tags and recorded readings and
  clip influence; notes/evidence open their stored records/provenance. Decorative glow and positions are not model
  thoughts.
  Add note is simpler; Teach preference retains explicit revision review/approval. Stale edits return 409 and keep
  unsaved text until explicit reload. Uploaded material does not fine-tune a model.
  Quality-first broad discovery defaults to three picks per pass, six unfinished picks including needs-rights,
  one known creator and two per topic. The existing default three-attempt daily budget remains; explicit inputs
  keep their behavior and weak estimates do not trigger unlimited attempts to fill the clip target.
  Tavily's optional free-key setup explains 1,000 monthly credits/no card and explicitly selects a $0 app spending
  limit when chosen, preserving other settings. No new graphics or browser dependency was added.
  One read-only Integrations assertion now expects the already implemented explicit Public audience choice,
  while Unlisted remains absent. Owner-data test flows and the HTTP write blocker are unchanged; no permission
  is selected or saved by that test.
* **Why:** the owner requested a finished app and Windows installer, clearer TikTok setup, an Obsidian-style view
  of saved Brain data and stronger discovery choices instead of chasing more clips.
* **Validation:** final full fast Python: **804 passed**, eight slow deselected, in **429.01 s**; Python is unchanged.
  All eight media cases passed across the initial run (seven passed, one environment disk-capacity failure,
  965.89 s) and unchanged live rerun (48.81 s) using workspace temp storage.
  **52 unique browser checks** are covered across runs: initial 42 passed/two failed in 12.7 min; final 19 passed
  in 1.1 min (11 changed UI, eight strict read-only Settings; ten overlap the initial batch); complete loop one
  passed in 7.0 min. The final lazy helper fixes background preparation; the old Public assertion was updated
  with read-only policy intact. Recorder/temp-storage prerequisites were fixed for the actual complete loop.
  Final build passed in **4.06 s**; all 14 tested/captured hashes match.
  [Desktop/mobile/empty previews](design/brain-workspace/README.md) use controlled records from the final run.
  Earlier interrupted outputs and historical checkpoint counts are separate evidence. The Windows installer
  has a separate bundle/integrity record on `codex/clipfoundry-one-click`; native Windows remains unverified.
* **Not verified:** Windows installation/execution, RTX 3050 CUDA/NVENC, real platform grants/visibility and an
  actual 24-hour soak. TikTok personal-tool eligibility, Sandbox/public limits and per-post consent remain external
  constraints. No real upload, app registration/review, account-permission change or website deployment occurred.

The PR #14 entries below retain their original branch status and evidence. PR #14 is now merged; earlier
draft/unmerged instructions are historical and do not govern this new checkpoint.

## 2026-10-11 · Final merge review and stable log-rotation check

* **Tool:** Codex. **Branch:** `claude/project-thread-vw1n9y`, PR #14. **Base:** `51984a3`.
  **Result:** the commit containing this entry. The owner authorized merge after the final review; the actual
  merge outcome is recorded on GitHub.
* **What changed:** the live log-rotation test now takes the standard logging handler lock while enumerating
  and measuring backup files. This prevents the test from inspecting an intermediate rename. The real child
  still writes enough output to rotate logs, stays running during the check, and is stopped afterward.
  Production code and the browser-tested frontend are unchanged.
* **Validation:** independent production review found no material blockers. The initial targeted run passed
  105 checks and failed this one snapshot race in 77.43 s; all 16 corrected launcher checks passed in 0.72 s.
  The fresh full fast suite passed **757 checks**, with **8 slow cases deselected**, in **301.90 s**.
  The worktree diff is clean and all 14 browser-tested build hashes match. GitHub reported no workflow runs,
  commit statuses, review submissions or review threads for the reviewed head; the PR had no conflicts.
* **Not verified:** Windows, RTX 3050, real platform accounts and an actual 24-hour soak remain owner checks.
  The preceding media/browser/crash-recovery evidence remains applicable. No real upload or deployment occurred.

## 2026-10-11 · Unattended Public operation and current YouTube policy

* **Tool:** Codex. **Branch:** `claude/project-thread-vw1n9y`, existing draft PR #14. **Base:** `61f6042`.
  **Result:** the commit containing this entry. PR stays draft/unmerged.
  Started October 10; final validation October 11.
* **What changed:** removed the obsolete API-project audit requirement for Public uploads, following official
  YouTube `videos.insert`/`videos` documentation updated October 8 and checked October 10. Explicit Public audience,
  account-bound approval/standing permission, rights, exact-file checks and actual visibility remain; old Private
  schedules are preserved. Midnight zero is retained so 0–24 scheduling works. OAuth Production/reconnect guidance
  distinguishes Testing's seven-day YouTube grants from API quota audits; private TikTok profiles cannot offer Everyone.
  Optional `run-unattended.bat` / `--unattended` restarts an unexpectedly exited app with bounded backoff, selected
  profile/port locks, owned descendant cleanup and explicit-stop handling. It preserves intentional Pause and
  permissions. Its local diagnostic log rotates at 5 MiB plus two backups; optional same-user login startup is
  documented.
  Only one app may use a data profile. The watchdog detects process exit, not a still-running hung main app.
* **Recovery fixes:** failed host initialization cleans up partial workers before releasing its lock; job setup
  errors clear phantom running/heartbeat entries. Bounded cancellable media reads/writes/waits kill/reap children;
  HTTP/live capacity checks retain a 2 GB reserve. Low disk yields Needs you and a durable wait, preserving saved
  segments and never implying stream EOF. Final assembly replaces a complete recording only after success.
  Scheduled pre-session waits recheck Pause/current permission/account/audience/final quality. Strict unknown-upload
  recovery requires an original-account, unique recent match with submitted metadata and reads actual visibility.
  Final-chunk crashes/cancellation/ambiguous errors hold another upload; manual restart recovery offers read-only
  Refresh status. Later reconnect, setup, scope or quota errors preserve the final-byte hold and publication
  identity. Existing valid sessions keep their exact confirmed bytes.
* **Why:** the owner requested all-day autonomous Public publishing from a personal setup and a final reliability
  review. This supports unattended YouTube operation after setup while preserving deliberate exception holds.
* **Validation:** full fast Python: 757 passed, eight slow deselected, in 390.67 s. All eight slow cases passed across
  the full run (six passed, two fixture setup failures, 786.85 s) and corrected Public (58.73 s) and upcoming-live
  (49.02 s) reruns. Public setup now uses `confirm=True` and asserts the confirmed response; its controlled scheduler
  cadence is five seconds. The live fixture uses a valid 0.5 GB capture cap on the small cloud temp disk; production's
  default 8 GB cap and 2 GB reserve remain. Production code did not change for these fixture corrections.
  All 32 isolated browser cases passed together in 8.1 min. TypeScript/Vite build passed in 4.37 s; all 14 tested
  file hashes match. Final fast verification includes recovery, media, launcher, policy and unknown-outcome
  regressions. Actual-app POSIX exit/restart/stop smoke passed in 11.98 s; Windows remains unverified.
  The real-media loop now tests Public and Private separately through repeat/restart,
  exact checked/uploaded bytes, mature fake results and actual live/post-live handlers. Public needs no invitation
  fixture. Earlier department/office test counts and animation evidence below remain historical.
* **Not verified:** actual 24-hour soak, Windows launcher/Task Scheduler/Job Objects, RTX 3050 CUDA/NVENC and real
  account scopes/quota/visibility/revocation. No real post, account change, purchase or deployment occurred. No new
  dependency; `.mcp.json`, GPU versions, Playwright versions and read-only `e2e/tests` are unchanged. The watchdog
  cannot make a powered-off PC work or bypass unknown outcomes, missing rights, expired access or resource holds.

## 2026-10-10 · Department attendance, manager supervision and reliability review

* **Tool:** Codex. **Branch:** `claude/project-thread-vw1n9y`, existing draft PR #14. **Base:** `e896632`.
  **Result:** the commit containing this entry. Requested October 9; resumed/completed October 10. PR stays unmerged.
* **What changed:** real jobs or substantive assigned backlog gather each complete department into its room.
  Workers appear immediately at their own desks; supporting peers remain honestly idle and ready. Managers stand
  facing the team with clipboard/pointing gestures, while their own jobs and real reviews take priority. Quiet
  paused/unavailable peers can attend; bare counts, stale paused tasks and unreferenced recurring timers cannot
  summon a team. A finished worker remains while its teammates work, then returns to lounge activities. Confirmed
  transfers meet inside the receiver's office and return to the latest department duty; a newer own job preempts
  carrying an older document away. Pixi and Canvas retain motion/freeze guards and all 25 identities.
  Brain Processing now has clipped scan bands, travelling synapse trails, rising sparks and orbital light trails.
  Added floor/contact/furniture polish and rebuilt frontend; existing Pixi/GSAP reused without new dependencies.
* **Reliability fixes:** lease-bound progress/host updates and transactional recovery protect current jobs from
  recovered handlers and heartbeat races; failed lock-file creation releases its mutex. Quality-check job identity
  includes the rule version. Regeneration checkpoints and restores video, captions, transcript, edit decisions,
  render plan and thumbnail, remaining non-Ready until rollback succeeds and retaining recovery copies on failure.
  Brain edits use atomic revision checks; paused learning collects results without changing/applying learned values,
  and confirmed audience drift cannot enter new selected-viewer readings. Manual publishing rechecks linked-source
  rights, platform coverage, current quality/version, confirmed bytes, connected account and emergency Pause.
  Unknown YouTube outcomes hold new uploads; strict original-account metadata lookup is read-only and ambiguity
  stays held. Already-processing entries only refresh status. The Publish page exposes the hold and Refresh status.
  Privacy text describes temporary recovery copies and approval-file fingerprints.
* **Why:** the owner requested full departments in their offices, a visible supervisor, a cooler Brain and a broad
  code review before delivery. Each backend fix addresses a reproduced fault found during that review.
* **Validation:** full fast Python: 685 passed, seven slow cases deselected, in 347.07 s. All seven slow media cases
  passed together, 685 fast deselected, in 676.84 s. All 31 isolated browser checks passed together in 7.8 min.
  Final TypeScript/Vite build passed in 5.96 s with the existing 904 KB lazy graphics warning;
  all 14 distribution files and file sets are identical to tested/captured SHA-256 manifests. Routing/controller
  checks cover 3,844 + 36,304 routes, 600 virtual seconds and 150 mixed transitions. Actual Brain/supervisor pixels
  animate and freeze in Reduced while real states update. All 32 touched/new code files meet 120 columns, and
  whitespace checks pass.
  Earlier 29/31-case browser runs each had one failure: a mismatched report fixture, then sampling the same Canvas
  idle frame twice. Matching job/kind/reference and polling across 900 ms frames corrected these; the production
  new-own-job guard remains intact. Those runs are distinct from the final all-green run above.
* **Evidence:** [department screenshots, controlled video and provenance](design/robot-office/departments/README.md):
  nine screenshots, one visibly labeled 37.40-second 1440×900 H.264 recording, 25 identities, visible laptop controls,
  no mobile horizontal overflow and zero page/console errors. The actual stopped-sandbox lounge capture is separate
  from controlled working/Brain/handoff states. All 14 captured production-file hashes are recorded. The recording
  demonstrates choreography, not real processing times, GPU performance or platform-account behavior.
* **Not verified:** Windows CMD/setup/fonts/scaling, RTX 3050 CUDA/NVENC and real platform accounts/uploads remain
  owner checks. No real post, owner account change, purchase or deployment occurred. GPU dependencies, `.mcp.json`,
  Playwright versions and read-only `e2e/tests` are unchanged. Earlier checkpoint results below remain historical.

## 2026-10-09 · Social pixel office and off-duty lounge life

* **Tool:** Codex. **Branch:** `claude/project-thread-vw1n9y`, draft PR #14. **Base:** `5b1f7a9`.
  **Result:** the commit containing this entry. PR stays draft/unmerged.
* **What changed:** six authored arcade/game/drink/snack/read/rest gestures in furnished lounge zones, with 29
  exclusive places, 25 stable cast homes, phased rotation and at most two recreational walkers. Real work and
  document transfers preempt breaks; job icons and references remain truthful. The owner's stopped-office
  recreation exception preserves Paused badges; individual pause while Running/unavailable remains quiet, and
  global Pause/Reduced/hidden/stale views freeze. Added pinned GSAP 3.15.0 pure easing with its standard no-charge
  license notice, cached Pixi BlurFilter light pools and an original locally bundled generated skyline. Optional
  image loading has a 1.5-second bound/procedural fallback and safe cropped-texture cleanup. Canvas has simpler
  phase-driven gestures; frozen Brain cues stay still on expiry. Dense whole-map names are staggered and the close
  lounge camera uses compact labels. Built frontend; no backend/media/publishing behavior changed.
* **Why:** the owner requested better graphics tools and off-duty robots that play, eat and drink while retaining
  the refined retro style and actual job behavior.
* **Validation:** full fast pytest: 641 passed, seven slow cases deselected, in 280.30 s. Final TypeScript/Vite build
  passed in 5.83 s with the existing 904 KB lazy graphics chunk warning. All 23 focused browser cases passed together
  in 6.4 min (lounge 6, living 7, motion 3, pixel 3, robot 4). All 14 distribution files are SHA-256 identical to the
  assets used in that final run after source-formatting cleanup.
  Geometry/controller checks covered 2916 + 4770 routes, 600 simulated seconds with all 25 identities rotating
  safely, exclusive reservations/max two walkers, and 150 mixed-state transitions. Actual rendered checks show
  all six Full gestures changing pixels, zero Reduced drift and real-work suppression of leisure props; frozen
  Canvas Brain pixels remain unchanged when an activity cue expires.
* **Evidence:** [actual isolated screenshots, labeled recordings and editing guide](design/robot-office/lounge/README.md).
  Final desktop/laptop/mobile captures retain all 25, visible laptop controls, no mobile overflow and zero page
  errors. Actual stopped lounge recording: 33.24 s; labeled controlled work/Brain/handoff recording: 33.48 s.
  Both are 1440×900 H.264 and have zero page errors. An initial controlled recording timed out with three browsers
  competing; its standalone rerun succeeded. Only startup before the provenance banner was trimmed, without retiming.
  These recordings do not measure clipping speed or GPU performance.
* **Not verified:** Windows CMD/installation/PC graphics/scaling, RTX 3050 CUDA/NVENC and real accounts/uploads.
  The seven slow media cases were not repeated for this frontend-only scope; prior results remain historical.
  GPU pins, `.mcp.json`, Playwright versions and `e2e/tests` remain unchanged. No real posts, account changes,
  hosting purchase or deployment occurred.

## 2026-10-08 · Living office, seated robots and animated Brain

* **Tool:** Codex. **Branch:** `claude/project-thread-vw1n9y`, draft PR #14. **Base:** `a119dfd`.
  **Result:** the commit containing this entry. PR stays draft/unmerged.
* **What changed:** a 960×640 furnished office with consistent robot/desk/chair proportions, clear aisles and 25
  individual lounge seats. Idle/waiting/paused/unavailable robots rest there; working/reviewing robots walk to
  their own desks and sit with bent knees and keyboard hand motion. Confirmed fresh job transitions and worker
  reports bring both robots together, pass one visible document and return them to the latest actual destination.
  Ownership/cursor recovery prevents outdated senders after hidden/paused/offline periods and history resets.
  The animated Brain has neural hemispheres, synapses and layered orbits; decorative Standby and true Processing
  are labeled separately. Paused/Reduced/offline states still the art. Added a room camera, matching Canvas
  compatibility layout, separated handoff names and built frontend. No new dependency or backend behavior.
* **Why:** the owner requested realistic proportions, idle lounge behavior, seated work, actual handoffs and a
  cooler animated Brain while keeping refined retro pixel art. Existing PixiJS supplies the needed tools.
* **Validation:** TypeScript/production build passed; 17 office Python checks passed in 6.10 s. All 17 focused browser
  checks passed together in 3.1 min. Browser coverage is seven
  living-office cases plus three motion, three pixel and four robot-office cases; exact final outcomes are at the
  top of [IMPLEMENTATION_STATUS.md](docs/IMPLEMENTATION_STATUS.md). Both suspension and reset sender regressions
  passed. Actual desktop/laptop/mobile captures reported zero browser errors; all 25 identities and laptop controls
  fit. The earlier full backend/media suites were not repeated for this frontend-only change.
* **Evidence:** [actual isolated screenshots, labeled controlled animation and editing guide](design/robot-office/living/README.md).
  The controlled video demonstrates graphics and event choreography, not real clipping time or GPU processing.
* **Not verified:** Windows CMD/PC graphics/scaling, RTX 3050 CUDA/NVENC and real connected accounts. Dependencies,
  GPU pins, `.mcp.json`, Playwright versions and `e2e/tests` are unchanged in this checkpoint. No real posts,
  account changes, purchases or deployment occurred.

## 2026-10-08 · Refined pixel office and Windows path recovery

* **Tool:** Codex. **Branch:** `claude/project-thread-vw1n9y`, existing draft PR #14. **Base:** `c33a291`.
  **Result:** the commit containing this entry. PR stays draft and unmerged.
* **What changed:** pinned PixiJS 8.22.0 paints the furnished office and all 25 refined robot rigs; Team/detail/gallery
  portraits share one lazy offscreen renderer with a bounded frame cache. Static scenery is cached separately from
  live robot/room layers. A scoped navy studio shell fits the map, details and controls at laptop sizes. Existing
  job events still govern work, walks, report handoffs and decisions; COMMAND visibly signals recorded approval.
  Motion preferences remain and graphics failure restores the original Canvas artwork and controls.
  Included third-party graphics notices and rebuilt distribution. No backend or publishing behavior changed.
  Windows setup now explains the long-path failure shown in the owner's screenshot and recommends fresh ZIP contents
  directly in a short folder (`C:\CF14`), creating a fresh `.venv` while preserving normal data. Both venv and pip
  failure branches include the guarded remedy; no registry changes or administrator settings.
* **Why:** the owner requested using better graphics tools and chose refined retro pixel art; their nested archive
  extraction also caused a Windows dependency installation failure.
* **Validation:** TypeScript/production build passed. Office Python: 17 passed in 7.20 s. Final isolated browser run:
  ten passed in 59.3 s (3 motion, 4 robot, 3 graphics/portrait/visible approval cases). The earlier scratch 60-second
  run timed out in the last sequential viewport check; a corrected timeout passed nine, then the final ten-case run
  passed with the approval pixel regression and scenery cache. Actual desktop/laptop/mobile captures recorded zero
  browser errors. 25 Team/100 gallery portraits rendered with a stable shared context count. Reduced-mode approval
  differs from idle in actual rendered pixels. Diff checks passed. Prior full/media results remain the preceding
  checkpoint's evidence and were not rerun in full for this graphics follow-up.
* **Evidence:** [screenshots, labeled controlled animation and source-editing guide](design/robot-office/retro/README.md).
  Pixi needs no account, plugin hookup or paid AI service. The video uses controlled test events, not real processing.
* **Not verified:** Windows CMD execution/installation, PC fonts/scaling/graphics, RTX 3050 CUDA/NVENC and real accounts.
  GPU dependencies, `.mcp.json`, Playwright versions and `e2e/tests` remain unchanged. No real posts, purchases,
  account permission changes or deployment occurred.

## 2026-10-08 · Public publishing, teachable Brain and complete robot office

* **Tool:** Codex. **Branch:** `claude/project-thread-vw1n9y`, existing draft PR #14. **Base:** `fea045d`.
  **Result:** the commit containing this entry. PR stays draft and unmerged.
* **What changed:** all 25 named robots remain readable with real job states, dependencies/handoffs and saved
  Follow system / Full / Reduced motion. Brain supports safe local document/good/bad example uploads, search,
  revision approval/edit/disable/delete, complete metadata/text/influence export and immutable later-plan influence.
  Approved typed preferences alter new blueprints; uploaded prose is inert and examples never become posting results.
  Discovery uses topic/language/freshness/relevance evidence and explains estimates and weak-story filters.
  Final checks send bounded repairs to the responsible stage. Video-only sources fail before Whisper; live
  segments with missing audio preserve the timeline and returning audio. Existing GPU execution paths remain.
  Explicit NEW Public YouTube automation uses channel/audience-bound consent, recorded project-audit confirmation,
  exact-file checks, limits and local due-time uploads without `publishAt`; old Private schedules remain Private.
  TikTok still needs eligible app/creator options/per-post consent, with truthful draft/manual fallbacks.
  Learning separates public/selected cohorts and waits 48 hours. Added stage timing report and isolated Windows launcher.
* **Final regression fixes:** Pause/Stop is checked atomically when claiming work; database migrations are serialized
  across threads/processes and committed before the next initializer; clearing the YouTube audit confirmation blocks
  new automatic Public approvals/uploads while preserving Private permissions; Brain export removes browsing caps.
  The Windows GPU-check command explicitly selects test data and distinguishes CUDA proof from NVENC render proof.
* **Why:** the owner's continuation prompt supersedes selected-only new uploads and hidden idle robots, while
  preserving existing visibility/data, platform restrictions and the unmerged PR.
* **Validation:** 641 passed, 7 deselected in 263.21 s. All seven slow cases and ten sandbox browser checks passed across initial
  runs and targeted reruns, with exact outcomes/fixture corrections in [IMPLEMENTATION_STATUS](docs/IMPLEMENTATION_STATUS.md).
  TypeScript/production build passed. Focused startup/core/office/TikTok: 66 passed; full Brain export: 8;
  public-audit/automatic-publishing recheck: 33; publishing: 44; returning-audio/recovery: 28.
  Disposable old-schema upgrade preserves rows/approval/media bytes. Before-fix reconstructions fail the new
  Stop/startup/export regressions. Tests use synthetic media/transcripts and local fake publishing, with real
  FFmpeg; no owner accounts/data or real uploads.
* **Evidence:** [screenshots, actual job animation, controlled motion demo and saved Brain influence](design/robot-office/screenshots/README.md).
  [Processing measurements/server advice](docs/PERFORMANCE.md) and [separate Windows ZIP test](docs/WINDOWS_PR14_TEST.md).
* **Not verified / blocked:** RTX 3050 CUDA/NVENC, Windows setup/fonts/scaling, real network intake and connected
  account scopes/project/app approvals/returned Public visibility. Official developer hosts returned proxy 403;
  current policies could not be freshly verified. Google's reachable official GitHub schema confirms only the
  `publishAt` field contract. Audit settings record owner confirmation, not programmatic approval.
  No server purchase, deployment, account permission changes or real posts occurred.

## 2026-10-08 · PR #14 review round

* **Tool:** Claude Code (cloud session). **Branch:** `claude/project-thread-vw1n9y` (draft PR #14), on top of
  `f71238c`. **Result commits:** `cf54204` (code) and the commit that adds this entry (docs).
* **What changed**
  * Public video importing stays on (owner, 2026-10-08). The beginner browser test now expects public videos to be
    clipped on the PC, to pass the final check and never to be planned or posted; the beginner answers *who
    watches* before anything is planned. A rule recorded after a video was clipped now reaches that video.
  * TikTok: a post-it-yourself page for the ready-to-post package (download, copy caption, steps, then link the post
    or mark it posted, `POST /scheduled/{id}/posted`); branded content only for Friends; a full inbox (5 pending
    drafts) holds TikTok posts for a day; labels that don't claim who could see a post. *I shared it* updates the
    post itself; held public posts can be sent to the selected viewers from their page.
  * Approvals and the automatic-publishing permission name the connected account; another account connected means a
    new approval. START pressed again before its work ran queues nothing new.
  * Brain and learner: uploads nobody else could watch are not evidence (*unconfirmed*), maturity counts from
    sharing, each platform rolls back on its own, a rollback or reset is not undone by the same results, 20 clips
    per side, identical results are inconclusive, the learner needs views and 5 videos.
  * Health: GPU errors and CPU fallback, accounts as information, *Unknown — not updating* when the feed is lost, a
    size-bounded `workers.log`, discovery stalls. Integration cards: Test connection, last check, rate limits.
  * Trend and Source Scores: missing parts count as neutral, with coverage, confidence and the missing parts stored.
    Video access failures carry one of 13 reasons; a named wait is honored, temporary problems are retried.
  * Robots: the crown badge of COMMAND and the managers, TRACKER green, SPARK's blue eye, PATCH's orange lamp;
    contact sheet re-captured. Setup and Sources text no longer say other people's videos are skipped.
  * Docs: privacy page (Test connection result, log sizes, the account an approval names, posts you made yourself),
    `docs/OFFICE.md`, `docs/PLATFORM_CAPABILITIES.md`, INSTALL and README (TikTok), AGENTS.md decisions, this file,
    `AI_HANDOFF.md`, `docs/IMPLEMENTATION_STATUS.md`.
* **Why:** the owner's follow-up of October 8, 2026 (compare with the spec, fix the beginner test without disabling
  public videos, recheck TikTok, verify the Brain, steps to test on the PC).
* **Tests run:** listed in the JSONL entry and in `docs/IMPLEMENTATION_STATUS.md` (test log).
* **Not verified:** GPU on the RTX 3050, real YouTube and TikTok accounts, TikTok's decision on the app, Windows.

## 2026-10-07 · The robot office screens, docs and handoff

* **Tool:** Claude Code (cloud session). **Branch:** `claude/project-thread-vw1n9y` (draft PR #14), on top of
  `26f6b8f`. **Result commit:** the commit that adds this entry.
* **What changed**
  * The app's places are now Office, Missions (the former Autopilot page), Clips (the former Library), Queue (the
    former Posts) and Settings; old addresses open the new pages in place.
  * Office: a pixel-art office (layout of reference image A) whose 25 robots stand where their real jobs are, walk
    and carry reports from the event feed, and rest in the Lounge; details panel (overview, robot, room), activity
    feed, bottom bar (Start, Pause, Resume, Stop all, Pause publishing), list view, Reduce animations, a stale mark
    when the feed is lost. Team roster (`#/office/team`) and developer gallery (`#/dev/robots`).
  * Settings → Integrations: who watches your uploads per platform (selected viewers, only you, keep on this PC),
    "My viewers changed", each connection's capabilities, NVIDIA AI setup with opt-in, check, small test and
    disconnect. Settings → Advanced: the Brain's limits and the Dev Log.
  * Clips → Test feedback; the Queue shows who each post is for, what really happened and whether results exist.
  * YouTube readings mirrored into the Brain now follow the 30-day YouTube data rule like the readings themselves.
  * Two slow video tests that `26f6b8f` missed now expect YouTube uploads as Private without `publishAt`.
  * Docs: `docs/OFFICE.md`, `design/robots/README.md`, this file, `AI_HANDOFF.md`, README beginner steps and NVIDIA
    setup, privacy page (NVIDIA excerpts, tester answers, office and learning records, audience records).
* **Why:** the owner's master prompt for the robot office (October 7, 2026), sections 15-23 and 26.
* **Tests run:** listed in the JSONL entry and in `docs/IMPLEMENTATION_STATUS.md` (test log).
* **Not verified here:** GPU transcription and rendering on the RTX 3050, real YouTube or TikTok uploads, real
  invitations, TikTok's audit, real NVIDIA requests, Windows-specific behavior.

## 2026-10-07 · Selected audience, office backend, Brain guards and optional NVIDIA AI (`26f6b8f`)

* **Tool:** Claude Code (cloud session). **Branch:** `claude/project-thread-vw1n9y`. **Base:** `eff96fb`.
* **What changed**
  * Uploads go only to a selected audience: YouTube Private without `publishAt`, with viewers you invite in YouTube
    Studio; TikTok followers or friends through an audited Direct Post, otherwise a ready-to-post package. Public,
    unlisted and Everyone are blocked on every path; posts planned before keep their audience and old public ones
    are held. Approvals and automatic uploads are bound to the audience stamp (`APPROVAL_SCHEME = 3`, Private-only
    consent v2). Pause publishing.
  * Office backend (`clipfoundry/office`): the cast registry, the event feed with a resume cursor, managers'
    reports, the Director's recorded decisions at four checkpoints, health readings, room details, controls,
    capability registry and integration cards.
  * Brain (`autopilot/brain.py`): observations with provenance, null kept apart from zero, idempotent CSV import
    with preview, corrections kept; strategy changes need 30 mature clips from 5 videos in one selected audience,
    move at most 10%, wait for new results and roll back. The older learner follows the same guards.
  * Optional NVIDIA text AI (`pipeline/nvidia.py`), off by default, with opt-in, budgets and local fallback.
* **Why:** the same master prompt, sections 9-14 and 21-22.
* **Tests run:** `pytest -m "not slow"`: 543 passed (new suites `test_audience`, `test_office`, `test_brain`,
  `test_nvidia`).
* **Not verified here:** as above.
