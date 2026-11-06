# FilmCraft and EffectCraft inside ClipForge

FilmCraft (a video editor) and EffectCraft (motion graphics) are free, open-source apps from the ArtCraft team
(<https://getartcraft.com>). ClipForge uses them as part of its own editing, so a person installs nothing else:

1. **ClipForge fetches them itself.** `clipfoundry/craft/apps.py` pins one release of each (FilmCraft 0.17.1,
   EffectCraft 0.9.2) with every file's SHA-256 and size, for macOS (universal), Linux x86-64/arm64 and Windows
   x64/arm64, plus FilmCraft's web build. The desktop app downloads the missing parts in the background about 20 s
   after it starts (Settings, Editing apps can turn this off, or set them up by hand). Downloads come only from the
   apps' GitHub releases, are checked against the pinned checksum, are unpacked with checks against files outside
   the folder, links and devices, and replace nothing until everything worked. They live in
   `<data>/tools/craft/<app>-<version>-<part>/`. The online studio never fetches programs.
2. **The AI edits with FilmCraft's own tools** (`craft/finish.py`). The cut becomes a FilmCraft project (the
   frame-exact OpenTimelineIO timeline and SRT captions of `studio/interchange.py`, imported by `filmcraft-cli`).
   ClipForge's own decisions are then made with FilmCraft commands on the clips they belong to: Motion scale for
   punch-in zooms and "fill the frame", Gaussian Blur on the copies on the "Blurred background" tracks under pictures
   that do not fill the frame, Scale and Opacity keyframes for the push-in and fades of pictures over the video,
   Volume keyframes for sound fades, Essential Sound (dialogue/music types, Generate Ducking) for music dipping under
   speech, the caption track's style (burned in on export), and the export's loudness (-14 LUFS).
3. **EffectCraft makes effect shots and they go into the final edit** (`craft/shots.py`). The opening title is an
   animated EffectCraft composition (script → `effectcraft-cli render`, ProRes), imported into the FilmCraft project
   and swapped in for the title clip (`clip.replaceFromBin`).
4. **With an AI helper set up, the AI finishes the edit** (`craft/ai.py`): it is sent FilmCraft's clip list with
   times and the words said in each clip, the video's title, size and length, and FilmCraft's tool list (never the
   video, the sound or file paths), and answers with FilmCraft steps and at most two EffectCraft shots. Only
   finishing tools are allowed (effects and keyframes, colour presets, transitions, speed, titles and shapes, caption
   style, Essential Sound, markers), clip ids must belong to the sequence, no parameter may name a file or address,
   at most 40 steps. Shot scripts may not use files, programs, the network, saving or rendering. Settings, Editing
   apps turns this off.
5. **FilmCraft renders the final video.** `video_flow._render` uses `finish.render` for final videos when FilmCraft is
   set up (setting `edit_engine`: `auto`, the default, falls back to the built-in FFmpeg editor if FilmCraft fails
   and records why; `filmcraft` fails instead; `ffmpeg` never uses FilmCraft). The file is checked like the built-in
   editor's renders: length within two frames, size, sound, the AAC timing check. Previews stay with the built-in
   editor (quick). The same plan reuses the FilmCraft edit already made (`report.json` key), so the video rendered is
   the edit the person saw in the editor.
6. **FilmCraft's editor is on the editor page** (`craft/web.py`, `craft/routes.py`, `components/FilmCraft.tsx`). The
   web build is served from this computer at `/craft/filmcraft/` and framed on the same address with `?host=parent`.
   The page hands it the version's files (`filmcraft.importUrl`, each one `/files/<name>` in the editor) and the
   project, with every path rewritten to those names; the files are served only from the list ClipForge wrote
   (`<video>/filmcraft/web-r<N>.json`). FilmCraft's Save comes back as `filmcraft:save`; the page sends it to
   ClipForge, which maps the names back, asks for files the person added in the editor, refuses any other path or
   address, keeps the project under its SHA-256 (`<video>/filmcraft/saves/`) and saves a new version whose plan
   names it (`plan["filmcraft"]`). That version's preview and final video are rendered by FilmCraft from the save.
   Undo, redo and going back keep it; any other edit in ClipForge starts again from ClipForge's cut. Desktop app
   only (the online studio's security headers and server do not offer it).

## Settings

| Setting | Default | |
|---|---|---|
| `edit_engine` | `auto` | `auto` / `filmcraft` / `ffmpeg`: who makes final videos |
| `craft_auto_install` | on | the desktop app fetches the apps in the background |
| `craft_ai_finish` | on | with an AI helper, the AI finishes the edit with FilmCraft's tools |

Environment: `CLIPFOUNDRY_FILMCRAFT_CLI` / `CLIPFOUNDRY_EFFECTCRAFT_CLI` use another copy of a command-line tool;
`CLIPFOUNDRY_CRAFT_GPU=off` renders on the processor (machines without a usable graphics card, CI).

## Routes

`GET /api/craft`, `POST /api/craft/install`, `GET /craft/filmcraft/<file>` (the web build),
`GET /api/studio/videos/{id}/filmcraft/editor`, `POST .../filmcraft/prepare` (job `filmcraft_edit`),
`GET .../filmcraft/project`, `GET|POST .../filmcraft/files/{name}`, `POST .../filmcraft/save`.

## Checks

* `tests/test_craft.py`: stand-in `filmcraft-cli` and `effectcraft-cli` programs (they answer like the real ones and
  record what they were asked): installing and unpacking safely, the native steps, the whole edit and render, a
  failing step, the AI pass with refused steps and shots, the engine choice and fallback, the editor session and
  saves, hand-finished versions, the routes.
* `.github/workflows/filmcraft-check.yml` runs `scripts/craft_check.py` with the real apps on macOS 15 and Ubuntu:
  ClipForge's own install, the edit (every step must apply), the EffectCraft title, the AI pass with a stand-in
  answer, FilmCraft's render, and FilmCraft's editor on the editor page in headless Chrome (open, then Save back as
  version 2).

## Limits

Both apps are early releases (FilmCraft 0.17, EffectCraft 0.9); the built-in editor stays as the backup. FilmCraft's
editor needs WebGPU or WebGL2 in the app's web view. Windows has not been tried with the real apps yet.
