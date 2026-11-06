# Finish in FilmCraft (ArtCraft's open-source editor)

Checkpoint 2026-11-06. Landry asked to plug the ArtCraft apps (getartcraft.com/apps, open source at
github.com/storytold) into ClipForge for editing. FilmCraft, the video editor among them, is the first one in.

## What it does

The editor page (`#/video/<id>`, Look tab) has a **Finish in FilmCraft** panel:

| Button | What happens |
| --- | --- |
| Open in FilmCraft | ClipForge writes the current version as an OpenTimelineIO timeline (`.otio`) with SRT captions, a title-card still and a README in `data/videos/<id>/filmcraft/v<rev>/`, then opens FilmCraft with it. Nothing is uploaded; FilmCraft reads the original files where they are. |
| Show the timeline files | The same files, shown in Finder / File Explorer. |
| Timeline with media (.zip) | A portable package: the timeline (pointing at `media/...` next to it), captions, title still, README and every file it uses, stored uncompressed. Also works in the online studio. |

If FilmCraft is not installed, the files are still written and the panel links to
https://getartcraft.com/apps/filmcraft. ClipForge never downloads, ships or builds FilmCraft.

**How FilmCraft is opened** (`clipfoundry/studio/filmcraft.py`):

* Found in `/Applications` or `~/Applications` (Mac), the installer's folder (`Software\FilmCraft\InstallDir`,
  Program Files or `%LOCALAPPDATA%\Programs`, Windows) or on PATH (Linux). `CLIPFOUNDRY_FILMCRAFT` and
  `CLIPFOUNDRY_FILMCRAFT_CLI` point at other copies. Paths never come from a request.
* With FilmCraft's command-line tool (`filmcraft-cli`: inside the Windows and Linux installs, a separate download on a
  Mac, found on PATH, `/usr/local/bin`, `/opt/homebrew/bin`, `~/bin`, `~/.local/bin`), the timeline and captions are
  first imported into a FilmCraft project (`<name> v<rev>.fcproj`) and the app opens the project. If that import fails
  the app imports the timeline itself.
* Without it, the app starts with the timeline and captions as files to import (`open -n -a FilmCraft.app --args ...`
  on a Mac): FilmCraft imports the timeline as a sequence and the captions onto it.
* The online studio (`CLIPFOUNDRY_MODE=cloud`) never starts programs; it offers the .zip.

## The timeline (`clipfoundry/studio/interchange.py`)

Made from the FFmpeg engine's own frame map, so every element shows exactly the frames it has in ClipForge's render.

| ClipForge | In the timeline |
| --- | --- |
| Clips and images, trims, order (left-out parts are not included) | V1, frame-exact; source times may be fractional frames |
| Dissolve / fade through black (a join overlaps two neighbours) | A cut at the middle of the overlap with an OTIO transition (`Cross Dissolve` / `Dip to Black`) reaching half the overlap to each side; same program length |
| Straight cut joins (`join: "cut"`) | Plain cuts |
| Opening title card | A still drawn exactly as the engine draws it (`Title card.png`); a dark matte with a marker if FFmpeg cannot draw it |
| Pictures over the video | V2, where the render shows them |
| Clip sound, volume, mute | A1 with the same cuts and constant-power crossfades, linked to the picture; volume as FilmCraft clip gain |
| Voiceover, music, sound effects | One track each (more lanes where items overlap); a looping bed as repeated copies of its file; item volume; track volume and mute |
| Chapters | Markers (all of them, also ones YouTube would not show) |
| Captions (with your word fixes) | SRT on the output timeline; FilmCraft imports it as a caption track |
| Frame size and rate | `metadata.filmcraft.settings` (FilmCraft's SequenceSettings); other editors ignore it |

Not carried over (listed in the README and in the panel, only when the video uses them): ducking under speech, sound
fades, punch-in zooms, "Fill the frame" framing, the blurred background, the push-in and fades of pictures over the
video, the caption look, the title as editable text, and ClipForge's final loudness leveling.

## Verification

* `tests/test_studio_filmcraft.py` (fast): the picture track against `engine.frame_map` at 24/25/30/60 fps with
  dissolves, dips, straight cuts and none; sound tracks, loops, overlapping effects, overlays, chapters, captions;
  the OpenTimelineIO library reading the file (when installed); the package, README and .zip; opening with stand-in
  programs (app only, app and command-line tool, a failing import, nothing installed); the online studio refusing.
* `.github/workflows/filmcraft-check.yml` runs `scripts/filmcraft_check.py` on GitHub's macOS 15 and Ubuntu machines
  against FilmCraft's official signed release (version and SHA-256 pinned). It makes real media with FFmpeg, imports
  both the "Open in FilmCraft" timeline and the unpacked .zip with FilmCraft's command-line tool, compares sequence
  size and rate, every clip's place and volume, transitions, markers, caption cues and offline files, renders the
  project in FilmCraft and checks the file's length, size and sound. On the Mac it also installs FilmCraft.app and
  checks that ClipForge finds it.
* Not verified: clicking Open in FilmCraft on a real Mac with FilmCraft installed (the window opening), Windows, and
  FilmCraft versions other than the pinned one. To move the pin, change `FILMCRAFT_VERSION` and the three SHA-256
  values (from that release's `SHA256SUMS.txt`) in the workflow.

## Licences and names

FilmCraft is MIT OR Apache-2.0 (Copyright the ArtCraft Team and the FilmCraft contributors). ClipForge contains none
of its code and only starts the copy the person installed. The ArtCraft name and logos are the ArtCraft Team's
trademarks: ClipForge says "FilmCraft, the free open-source editor from the ArtCraft team" and uses no logo.
`artcraft-services` (a separate, restrictive licence) is not used.

## The other Crafting Apps

All are early alpha (2026-11-06) and each can be driven by its own command-line tool, JSON channel or MCP server.
Planned next, each as an "open in" handoff like this one: PhotoCraft for thumbnails (phase 2 of the AI editor plan),
EffectCraft for animated titles (phase 3), SoundCraft for a voice track. Not planned: rendering ClipForge's videos
through FilmCraft (FFmpeg stays the engine; FilmCraft's own encoders would first need the raw AAC packet check in
`pipeline/audio_timing`).
