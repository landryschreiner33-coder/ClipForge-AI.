# Editor integration: FilmCraft evaluation and the engine adapter

> **2026-11-06:** FilmCraft is now plugged in as a hand-off, not as the render engine: "Open in FilmCraft" writes the
> cut as an OpenTimelineIO timeline with captions and opens it in a FilmCraft the person installed, and a GitHub
> check imports and renders that timeline with FilmCraft's official release. See [FILMCRAFT.md](FILMCRAFT.md).
> Rendering through FilmCraft (below) is still not done.

Checkpoint: 2026-11-04. Status: **FilmCraft integration Blocked; FFmpeg engine adapter Implemented** for the
operations listed in the capability table below.

## What was checked

| Item | Result |
| --- | --- |
| Pinned upstream | `storytold/filmcraft@57dc82ea2046c2ec479ab4d4d8167d90e5500b49` (2026-11-03). Upstream `HEAD` was `c9be142` on 2026-11-04; the pin was kept so the license/notice review matches what would be built. |
| License | `LICENSE-MIT` / `LICENSE-APACHE` ("MIT OR Apache-2.0"); `NOTICE` lists bundled third-party fonts and the egui icon font, with per-file attribution in `ATTRIBUTION.md`. Any redistributed build must ship `NOTICE`, both license texts and `ATTRIBUTION.md`. |
| Trademarks | `NOTICE` says the ArtCraft name, wordmark and logos (`docs/brand/`) are not covered by the code license. ClipForge uses none of them and keeps its own robot icon. No affiliation is claimed. |
| artcraft-services | Not used. Its separate license restricts competing products; nothing from it was copied. |
| Browser build (`docs/web.md`) | Static WebAssembly build; media stay on the viewer's device; single-threaded (frame rendering, decode, mixing and encoding run cooperatively on the UI thread). Hosting it is not cloud processing. Needs COOP/COEP for cross-origin isolation, WebGPU or WebGL2. |
| Headless CLI (`apps/filmcraft-cli`) | `import`, `exec <command>`, `run script.jsonl`, `inspect`, `export out.mp4 [--preset] [--start --end]`, `render`, `probe`, and an MCP server on stdio. Time is integer ticks (254,016,000,000 per second). |
| Control channel | Loopback TCP with a 64-hex-character token (`docs/control-protocol.md`). It must never be exposed publicly; ClipForge would only call the CLI as a job-scoped subprocess. |
| Linux limits (`docs/gaps.md`) | G3: its own H.264 decoder is 8-bit 4:2:0 only, so 10-bit/4:2:2 camera media do not open on Linux without hardware decode. G6: no real-world media corpus yet (VFR phone/screen recordings untested upstream). G9: little routine Linux runtime testing. Linux aarch64 release packages are documented in `docs/releasing.md`; ARM64 behaviour was not measured here. |
| Own codecs | FilmCraft encodes AAC with its own Rust encoder. ClipForge's earlier upload defect was in stored AAC packet timing, so any FilmCraft export must pass the same raw-packet check (`pipeline/audio_timing.require_valid`) before it can publish. |

## Why the experiment is Blocked

The bounded experiment requires compiling and running upstream code (`cargo build --release -p filmcraft-cli`).
This session's safety policy refused that command, because a Cargo build executes third-party build scripts
downloaded from the internet. No workaround was attempted. Nothing about FilmCraft's real behaviour (import of
mixed rates, trims, captions, export timing, memory, throughput, ARM64) has been measured; none is claimed.

**Remaining action (owner):** approve building and running FilmCraft in a session, or run the harness on a
machine you control:

```bash
cargo build --release -p filmcraft-cli            # inside a checkout of the pinned commit
FILMCRAFT_CLI=/abs/path/target/release/filmcraft-cli \
  .venv/bin/python scripts/filmcraft_experiment.py --out /tmp/filmcraft-experiment
```

The harness (`scripts/filmcraft_experiment.py`) makes three synthetic files with different frame and sample rates
(24 fps / 44.1 kHz stereo, 30 fps / 48 kHz stereo, 25 fps / 32 kHz mono), a still image and a music bed. It
imports them, records the CLI's command list, saves and reopens the project, and exports to MP4 on the headless
worker. It then checks the output duration, the opening audio and the stored AAC packet timing (with timestamp
auto-repair disabled), and records wall time and peak memory. The trim/reorder/B-roll/caption command IDs have to be
mapped from that printed command list. The harness records any it cannot find as unsupported rather than guessing.

## Decision for this build

Until the experiment passes, **full-video assembly renders through ClipForge's own FFmpeg engine** behind a
versioned adapter (`clipfoundry/studio/engine.py`). The adapter is what a FilmCraft engine would implement
later; swapping engines does not change the saved edit plan.

**Engine `ffmpeg-v2`, plan schema 2 (2026-11-05).** The first engine (`ffmpeg-v1`) built one FFmpeg filter graph
with every input, so memory and open files grew with the number of clips. `ffmpeg-v2` renders in pieces:

| Step | What happens | Bound |
| --- | --- | --- |
| Frame map | Every element (title card, clip, image) ends on the output frame nearest its ideal end; the next starts one transition earlier. Rounding never accumulates. | — |
| Picture | Each element body and each join between two neighbours is its own FFmpeg run (at most two inputs), encoded without B-frames and cached by content (`pieces-preview/`, `pieces-final/` per project). The pieces are joined by byte concatenation and muxed by stream copy. | 2 inputs per process |
| Captions | Burned into each piece from the same output-timeline captions, shifted to the piece. | — |
| Sound | Each clip's sound and each audio item is decoded to raw samples of exactly its frame length (gain, mute, fades, loops applied), then mixed in 10-second blocks into speech, ducking and non-ducking buses. Ducking is measured from the speech bus (default 12 dB, adjustable 0–30 dB), then one constant loudness gain, the limiter and the rebuilt sample clock are applied as before. | 10 s blocks |
| Disk | Free space is checked before anything starts; a render that would fill the disk is refused with the size needed. | — |
| Reuse | A revision whose plan equals an already rendered one (after undo, redo or going back) links that artifact instead of rendering again. | — |

| Adapter call | FFmpeg engine (`ffmpeg-v2`) |
| --- | --- |
| `capabilities()` | Declares the supported operations below, tracks, caption sizes/positions, frame rates and ducking range; anything else is reported as unsupported before render. |
| `upgrade(plan)` | Reads a schema-1 plan as schema 2 (its music bed becomes a looping, ducking item on the music track). Stored revisions are never rewritten. |
| `validate(plan)` | Checks every clip and audio item references an asset of the same project/workspace, ranges, fades, gains and every operation is declared. |
| `render(plan, out, progress, cancelled)` | Server render from full originals; cancellable between and inside pieces; progress by frames done. |
| `preview(plan)` | Low-resolution render of the same plan (same code path, smaller size and faster preset). |

Supported operations: ordered clips with source in/out trims, insert, replace and split; still images for a set
duration; cross-dissolve/fade-through-black transitions; title cards; burned-in captions from the source transcript
with per-word corrections, three sizes and four positions; per-clip gain, mute, sound fades and framing; voiceover,
music and effects items on their own tracks with start time or clip attachment, trim, loop, gain, mute, fades and
ducking; per-track gain and mute; aspect ratio 16:9, 9:16, 1:1 or 4:5 with fit (blurred background) or fill;
24/25/30/50/60 fps. Mixed frame rates and sample rates are normalised to the plan's output rate. The final audio
clock is rebuilt after all filters and the output must pass the raw AAC packet check.

Not supported (reported, never silently dropped): colour grading, keyframed motion, picture-in-picture, speed
changes, effects plugins, multicam, and project interchange formats other than ClipForge's own JSON edit plan
(`clipforge.edit-plan/v2`).
