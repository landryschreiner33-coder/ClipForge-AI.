# Smart editing and ClipForge AI

"Make a YouTube video" can now edit the rough cut instead of only placing the files one after another. The choice
is the brief field `smart_edit`: `smart` ("Edit it for me", the default in the app), `tight` ("Fast-paced") or
`off` ("Keep my clips as they are", the old rough cut; also the default for API callers that do not send it).

## What it does (clipfoundry/studio/smart_edit.py)

1. **Leaves out** sentences the brief asks to avoid, an earlier take of a line said again (a false start, or the same
   line twice), a stumble inside one sentence ("the water was the water was ..."), sentences ClipForge AI suggests,
   and, to fit the asked length, the weakest passages (scored by what is said; the opening, the ending and must-keep
   words stay). Left-out parts stay in the sequence switched off (`include: false`, outline "Left out (why): ..."),
   so Put back restores them.
2. **Cuts dead air:** pauses longer than 0.7 s (0.4 s fast-paced) and lone "um"/"uh", found from word timings and
   confirmed in the sound (`audio.wav`, 10 ms levels, 30 dB under the speaker). A cut never lands inside a word.
   Joins inside one recording are straight cuts (`join: "cut"`) with 10 ms sound fades; fast-paced punches in
   (`zoom: 1.1`) on every other cut. Silence before the first and after the last word is trimmed.
3. **Pictures over the video** (`plan.overlays`): an image whose file name is said appears then (or just after, at a
   jump cut); others are spread over long talking stretches, never in the first 3 s or last 2 s, 4 s apart, with a
   slow push-in and fades. Without speech, images stay in the sequence as before.
4. **Sound:** music under the whole video that dips under speech (your music file, a long audio file in the media
   bin, or free music made on this computer by `studio/library.py`, in the video's mood) and soft whooshes at
   recording changes and swishes for pictures. Library sounds are synthesized (no samples, no licence questions),
   cached in `data/library/` and added to the project's media like any file.
5. **Chapters** for the YouTube description (from ClipForge AI's topic changes, or file names), shown only when
   YouTube would accept them (three or more, first at 0:00, each at least 10 s).

Every step is written in `plan.notes` and summarized in `plan.smart` (level, options, stats, AI use). "Edit it for
me" again (`POST /api/studio/videos/{id}/smart`, job `video_smart`) makes a new version and keeps the look
(output, layout, captions, title, word fixes, ducking, tracks) and every sound or picture you placed yourself; items
the editor added carry `auto: true` and are replaced.

## The engine (clipfoundry/studio/engine.py)

New plan features, all validated: per-clip `join: "cut"` (only that boundary is a straight cut), per-clip `zoom`
(1.0 to 1.5, centred crop), and `overlays` (image or muted video over a clip's body; `motion` still/zoom, `fit`
fill/fit with a blurred background for other shapes). Each overlay is rendered as exactly one piece, so the piece
cache and the two-inputs-per-FFmpeg-run rule still hold. Captions count a word that starts inside a clip when most
of it is inside (speech models often let a word's end run into the pause that gets cut).

## ClipForge AI's model (clipfoundry/studio/ai_editor.py, clipfoundry/ai_setup.py)

Optional; the built-in rules work without it. It is the same AI service as clip scoring and "Tell the editor what
to change", chosen under **Settings → ClipForge AI** (`#/settings/ai`):

| Choice | Cost | Where it runs |
| --- | --- | --- |
| Ollama (download a model, or import a `.gguf` file you have) | Free | This computer |
| LM Studio | Free | This computer |
| Google Gemini | Free tier with daily limits (may be used to improve Google's products) | Online, your key |
| Groq | Free tier with daily limits | Online, your key |
| OpenRouter (`:free` models only) | Free, small daily limit | Online, your key |
| Claude API | Paid per use | Online, your key |

It is sent text only: the brief and the numbered sentences with their times, in windows of about 6,000 characters
(at most 8 requests per edit). The answer is read as one JSON object; unknown indices are ignored, must-keep
sentences are never cut, and at most 40 % of a window's sentences can be left out. A failure or a missing helper is
written in the notes and the built-in editor decides. A saved key is only sent to the address it was saved for:
switching to another service needs that service's key.

## Tests

`tests/test_studio_smart_edit.py` (fast: cutting rules, length fitting, pictures, music/effects, AI advice checks,
Edit it again, engine rules, routes, AI setup against a fake local Ollama) and `tests/test_studio_smart_render.py`
(slow: real speech via espeak-ng, final render checked frame by frame and by sound level).
