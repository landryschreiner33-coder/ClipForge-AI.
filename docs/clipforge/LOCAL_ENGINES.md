# Local makers: pictures, video and voice made on this computer

This is the design, as built, of the November 2026 work that lets ClipForge make still pictures, short video clips
and voice-overs itself, on the owner's computer, for free. The animated-shorts maker
([ANIMATED_SHORTS.md](ANIMATED_SHORTS.md), built in its own thread) and ClipForge AI use them through one door,
`clipfoundry/engines/`.

**What Landry asked for (Nov 7 2026):** look at seven open-source projects he found (FreeVideo, WanGP, ComfyUI
Desktop, InvokeAI, OpenHiggsfield, VoiceStudio, Tencent WeKnora), plug the useful ones into ClipForge, and make sure
everything runs locally. His Mac is Apple silicon; the app also ships for Windows.

## In short

- **Pictures and video clips are made by ComfyUI**, a free, open-source program, run next to ClipForge and talked to
  over the computer's own network address (127.0.0.1). ClipForge either sets up a private copy of ComfyUI for itself
  (one button in Settings), or uses the ComfyUI desktop app when it is already installed.
- **Three models, all Apache-2.0** (free, also for commercial use): Z-Image Turbo and FLUX.2 klein 4B for pictures,
  Wan 2.2 (5B) for clips of up to 5 seconds. Settings recommends the one that suits the computer's memory.
- **The voice runs inside ClipForge**: Supertonic 3 (OpenRAIL-M, commercial use allowed with use rules that the
  person agrees to before the download), 10 voices, 31 languages, on the processor, no extra program.
- **Every download is pinned**: an exact address at a fixed version, the exact size and SHA-256 checksum. A file
  that does not match is refused. Nothing is downloaded from an address not written in `engines/catalog.py`.
- **Once downloaded, nothing goes online**: ComfyUI runs with `--offline`, without add-on nodes, and only listens on
  127.0.0.1. What it makes stays on the computer.

## Landry's list: what was plugged in, what was skipped, and why

Each project was checked on Nov 7–8 2026 from its own licence file, code and documentation (nothing from them was run
here). The rule: everything runs on the owner's computer, and the code and model files must allow commercial use in
the United States, on an Apple silicon Mac and on Windows.

| Project | What it is | Decision | Why |
|---|---|---|---|
| **ComfyUI Desktop** (Comfy-Org) | The leading free program that runs picture and video models | **Plugged in** | Runs on Apple silicon (Metal) and on Windows (NVIDIA or the processor). Its code is GPL-3.0, which is fine for a separate program ClipForge talks to over 127.0.0.1, and it runs the best free models whose licences allow commercial use. ClipForge sets up its own private copy with one button, or uses the ComfyUI desktop app if it is already installed. |
| **FreeVideo** (FlashML-org) | One-click launchers that install ComfyUI plus the MiniMax H3 video model | Skipped | The model's licence (MiniMax H3 Community License) excludes the United States, the EU, the UK and South Korea, requires "MiniMax H3" to be shown in any commercial app and needs separate permission above US$20 million revenue. Also: on a Mac it is an experimental preview (22–42 minutes for a 10-second clip on a 24 GB M5); on Windows it needs an RTX 30-series card or newer and about 99 GB of files. |
| **WanGP / Wan2GP** (DeepBeepMeep) | An all-in-one local app for many video, picture and voice models | Skipped | ClipForge already makes the same Wan 2.2 clips through ComfyUI. WanGP's own licence (WanGP Community License 2.0, not an open-source licence) needs a separate paid deal to ship it in, or expose it from, an app that is sold, and it counts its own local API and headless modes as part of the licensed software. On a Mac it only half works (no Mac install guide). |
| **InvokeAI** (Invoke) | A polished picture studio, Apache-2.0 | Not needed | ClipForge already makes the same pictures and clips with the same models (FLUX.2 klein 4B, Z-Image Turbo, Wan 2.2 5B) through ComfyUI; InvokeAI would be a second engine to look after with nothing new for creators. Its "FLUX.1 dev" bundle is also non-commercial. |
| **OpenHiggsfield** (wide-trace; the zip Landry attached) | A web page for Higgsfield's paid online service | Skipped | It makes nothing on the computer: every prompt goes, with the person's paid key, to an online service, and uploads go to a public cloud bucket. Its code has no licence, so none of it may be reused. The zip was unpacked into its own folder and only read, never run. |
| **VoiceStudio** (debpalash) | A large desktop voice app: voice cloning, dubbing, audiobooks | Maybe later, as an option | It could later let a creator narrate in a copy of their own voice. But its default voice model (OmniVoice) is non-commercial (CC-BY-NC), the app is AGPL-3.0 and heavy on a 16 GB Mac, and its commercially usable cloning models are recommended for NVIDIA. ClipForge's built-in voice (Supertonic 3, which VoiceStudio also ships) stays the default. |
| **WeKnora** (Tencent) | A team-sized document search and question-answering server | Skipped | MIT code, but it needs several extra programs (a database, Redis, a document reader with LibreOffice, usually Docker) and about 8 GB of memory for itself. A small built-in way for the Brain to find the right paragraph in a long document gives creators the useful part (see Follow-ups). |

**Ideas taken from them.** Already in this work: every model file is pinned with its repository, commit, size and
SHA-256 and carries its licence (FreeVideo); one-click downloads offer only full-precision models that allow
commercial use (InvokeAI's rule for its FLUX.2 bundle); each model is rated for this computer before it is downloaded
(InvokeAI's hardware table, FreeVideo's memory check); the note next to everything made records the model, its
licence, the prompt and the seed (FreeVideo, InvokeAI 7). The rest are listed under Follow-ups.

## How it fits together

| Part | File | What it does |
|---|---|---|
| The door | `engines/__init__.py` | `make_image`, `make_video`, `speak`, `voices`, `status`, and the Settings calls. One error class, `EngineError`, with a message written for the person. |
| What gets downloaded | `engines/catalog.py` | uv, Python, ComfyUI, PyTorch per computer, the models and the voice: address, size, SHA-256, licence. |
| Downloads | `engines/files.py` | Resumable downloads checked against the pin, free-space check, safe unpacking (no paths outside the folder). |
| Background set-ups | `engines/tasks.py` | One set-up at a time with progress and Cancel (a cancelled download keeps its partial file and resumes). |
| ClipForge's own ComfyUI | `engines/comfy_server.py` | Set-up with uv, start on demand, stop after 10 idle minutes, one copy shared between ClipForge processes. |
| Talking to ComfyUI | `engines/comfy.py` | `/prompt`, progress over the websocket (never going backwards), `/history`, `/view`, `/upload/image`, `/interrupt` and `/queue` (a stop waits until ComfyUI has really let go), `/free`. |
| The recipes | `engines/graphs.py` | The node graphs, copied from ComfyUI's official example for each model, and the size and length rounding. |
| Models in ComfyUI | `engines/models.py` | Which files a ComfyUI lacks and the names it lists them by, downloading them into its model folders, removal of ClipForge's own downloads. |
| Making things | `engines/makers.py` | Which ComfyUI and which model, recommended models for this computer, `make_image` / `make_video`. |
| The voice | `engines/voice.py` | Supertonic 3 with ONNX Runtime: text cleaning, sentence chunks, word timings, WAV out. |
| Settings page | `engines/routes.py`, `frontend/src/components/LocalMakers.tsx` | Settings → Pictures, video, voice. |

### The door (for the shorts maker and the AI)

Every call blocks (run it in a job thread) and takes `progress(fraction, message)` and `cancel() -> bool`.

| Call | Gives back |
|---|---|
| `make_image(prompt, negative="", style="", width=1080, height=1920, seed=None)` | Path of a PNG. The size is rounded to the model's step (16 pixels) and kept under about 2 megapixels, same shape. |
| `make_video(prompt, image=None, seconds=4.0, width=720, height=1280, seed=None)` | Path of a silent MP4 (H.264). Wan makes 4n+1 frames at 24 a second: 2 s = 49 frames, at most 5 s = 121; at most 1280×704 pixels. With `image`, the clip starts from that picture. |
| `speak(text, voice="default", speed=1.0, lang="en")` | `{"path", "duration_s", "words": [{"text", "start_s", "end_s"}], "word_timing": "estimated", "sample_rate", "voice", "model", "licence", "rule"}`: a mono WAV at 44.1 kHz. Sentence starts and ends are exact; words inside a sentence are spread by their length. |
| `voices()` | `[{"id", "name", "lang", "gender", "about"}]`: F1–F5 and M1–M5 once the voice is downloaded. |
| `status(role)` | `{"ready", "engine", "why"}` for "image", "video" or "voice". Never raises. |

Everything made goes to `data/engines/made/<image|video|voice>/<day>/`, with a note next to it (same name, `.json`)
naming the model, its licence and its use rules (`rule`), the words, the seed and the time taken. Each job saves under
a name of its own inside ComfyUI, so asking for the same picture twice makes it twice (ComfyUI answers an identical
request from its cache, with the file of the first time). The shorts maker takes what it uses out of there into its
project, with its note (docs/clipforge/ANIMATED_SHORTS.md, "Tidying"), so it goes when the short does; a test from
Settings stays in engines/made. Sizes that suit 9:16 shorts: pictures 1080×1920 (or 768×1344 to save time), clips 480×832 or 704×1280.

### ComfyUI: ClipForge's own, or the app already on the computer

Settings → Pictures, video, voice has three choices.

- **ClipForge's own (the default).** One button downloads, into ClipForge's data folder only:
  - uv 0.13.7 (MIT or Apache-2.0), from PyPI;
  - a private Python 3.12 (python-build-standalone), installed and checked by uv into that folder only: never onto
    the PATH (`~/.local/bin`) or into the Windows registry (`uv python install --no-bin --no-registry`);
  - PyTorch 2.14.1 and torchvision 0.29.1 for this computer: Apple silicon (Metal) from PyPI; an NVIDIA card with
    driver 580 or newer from PyTorch's CUDA 13.0 index; otherwise the processor build. They are installed on their
    own (`--no-deps`), because PyTorch's own index has no upload dates to cut off at; what PyTorch needs comes in the
    next step;
  - ComfyUI 0.43.0, the newest published release (Oct 27 2026), from GitHub's archive of the tag, checked against
    its SHA-256; its other packages, PyTorch's own and the environment's pip resolve to what PyPI had on Nov 7 2026
    (uv `--exclude-newer`), with PyTorch held at its pinned version.

  About 0.7 GB to download on a Mac (3.7 GB with NVIDIA), 2–8 GB on disk. Nothing else on the computer changes.
  ComfyUI starts when a picture or clip is needed, with `--listen 127.0.0.1 --offline --disable-all-custom-nodes
  --disable-metadata --preview-method none`, its own input/output/temp/user folders, and ClipForge's model folder
  (`extra_model_paths.yaml`, so models survive a ComfyUI update). It stops after 10 minutes without work (setting
  `engines_idle_minutes`) and when ClipForge closes; before heavy video work ClipForge asks it to hand its memory back.
- **The ComfyUI app on this computer.** ClipForge looks on 127.0.0.1:8000 (the desktop app), then :8188 (a manual
  install), or an address typed in. It downloads models into that ComfyUI's own model folders (only when it is on
  this computer) and never replaces a file it did not download itself. A model the person keeps in a subfolder
  there (`flux2/flux-2-klein-4b.safetensors`, `flux2\flux-2-klein-4b.safetensors` on Windows) is sent to ComfyUI by
  the name ComfyUI lists, which is the only name it accepts.
- **Off.** Pictures and clips are not made; the shorts maker uses designed cards instead.

ComfyUI is GPL-3.0. It always runs as a separate program that ClipForge talks to over HTTP; no ComfyUI code is
imported into or shipped with ClipForge, and the person's computer downloads ComfyUI's official source release (which
carries its licence). ClipForge writes a notice next to it.

### The models

All three come from Comfy-Org's repackaged repositories (the files ComfyUI's own examples use), pinned to a commit.
Only the full-precision files are used: the smaller "fp8" and "int8" files do not run on a Mac (PyTorch has no Metal
support for those number formats), and one set for every computer keeps what was checked and what runs the same.

| Model | For | Licence | Download | Runs well with | Settings |
|---|---|---|---|---|---|
| FLUX.2 klein 4B (Black Forest Labs) | pictures, recommended on 16 GB Macs and 8 GB NVIDIA cards | Apache-2.0 | 16.1 GB | Mac 16 GB, NVIDIA 8 GB | 4 steps, no guidance, euler |
| Z-Image Turbo (Tongyi Lab, Alibaba) | pictures, the best detail and lettering | Apache-2.0 | 20.7 GB | Mac 24 GB, NVIDIA 12 GB | 8 steps, res_multistep, shift 3 |
| Wan 2.2 TI2V 5B (Wan team, Alibaba) | clips of up to 5 s, from words or a picture | Apache-2.0 | 22.8 GB | Mac 32 GB, NVIDIA 12 GB | 20 steps, cfg 5, uni_pc, shift 8, 24 fps |

The two picture models share one file, the Qwen3 4B text encoder (8 GB, same name, size and SHA-256), so the second
one downloads only its own files, and removing one keeps it for the other. Wan uses the umT5-XXL text encoder in fp16.

**The licences, checked a second time (Nov 8) against each publisher's own pages.** Z-Image Turbo, FLUX.2 klein 4B,
Qwen3-4B (the text encoder), Wan 2.2 TI2V 5B with its VAE, and umT5-XXL are Apache-2.0. Comfy-Org's FLUX.2 klein file
has the same SHA-256 as Black Forest Labs' own. Black Forest Labs states that both its FLUX.1 and FLUX.2 autoencoders
(the VAE files of the two picture models) are Apache-2.0; ClipForge's copies are the same size to the byte as theirs
(Black Forest Labs hides the checksums behind a sign-in, so they could not be compared). None of the repositories
ClipForge downloads from asks for a sign-in, and none of these licences has a revenue cap. Apache-2.0 itself only asks
that the licence and notices travel with the files, which they do, since each person's computer downloads them from
their publisher's repository. Wan's model card adds a request on top of Apache-2.0: you are accountable for what you
make, and it must not break the law, harm people, share personal information to harm someone, spread misinformation
or target vulnerable groups. Settings shows it before the Wan download and asks the person to agree.

**Which one is recommended.** `makers.machine()` reads the computer (Mac memory, or the NVIDIA card's memory) and
`fit()` rates each model "good", "slow" or "cpu". Settings marks the first good one "Best for this computer" and says
plainly when one will be slow here ("This Mac has 16 GB of memory, so this one will be slow here."). The person's own
choice always wins (`engines_picture`, `engines_video`).

### The voice

Supertonic 3 (Supertone Inc.), about 400 MB of ONNX files, runs on the processor through ONNX Runtime (already part of
ClipForge): 10 voices (F1–F5, M1–M5), 31 languages, faster than real time (1.8–3.5× on GitHub's test machines). The
code that runs it is ClipForge's own (`voice.py`), checked against Supertone's reference implementation: text
cleaning, the latent length, the noise shape, the steps, the speed and the "na" fallback for other languages. Long
text is cut into sentences (300 characters, 120 for Korean) with 0.3 s pauses.

Its licence (BigScience OpenRAIL-M, Aug 18 2022, read at the pinned revision) allows commercial use, free, with use
rules (its Attachment A) that bind whoever uses the voice. The one that matters when posting is item (e): content may
not be placed anywhere "without expressly and intelligibly disclaiming that the information and/or content is machine
generated". So the rule ClipForge shows asks for a plain line such as "Voice is AI-generated" in the caption or
description; a platform's own AI label helps, but may not be enough on its own. The licence also says the app "shall
require" its users to follow these rules, so the voice's download button reads "Agree and download", under the rules.
Every `speak()` result and note carries the rule so the shorts maker can show it at export. Supertone's own sample
code, which `voice.py` was checked against, is MIT.

### Settings → Pictures, video, voice

What each part does, whether it is ready and why not, ComfyUI's three choices, the set-up button with its size, each
model with its licence, download size, the memory it needs and a fit note, Download / Use this / Remove, a quick try
for each part (a test picture, a 2-second test clip, "Hear it" with a voice choice) and where everything is kept. One
set-up runs at a time with progress and Cancel.

- **Download.** The dialog names the model, its maker and licence. For a model whose licence comes with use rules
  (`catalog.Model.rule`: Supertonic 3 and Wan 2.2) it shows them and the button reads "Agree and download"; the
  set-up route refuses such a model unless the request says `"agreed": true`.
- **Remove** is shown only when it would delete something: the files ClipForge downloaded itself into the folders of
  the ComfyUI in use (ClipForge's own, or the app's), and what a stopped download of ClipForge's left there (the row
  then says "Partly downloaded"; in the app's folders only a `.part` file ClipForge recorded before it started, never
  another program's). It never deletes a file of the person's own, nor a shared file another model there still
  needs: the picture models' text encoder stays while the other model is there or ClipForge is part way through
  downloading it (a file of the person's that only has the same name as one of its files does not count), and Remove
  then says what it kept. It is refused while a picture or clip is being made, from starting ComfyUI to saving the
  file, and none starts until it is done. ClipForge's own ComfyUI is stopped first (or, when another ClipForge
  process started it and shares it, asked to unload its models) and a ComfyUI app is asked to unload its models,
  because Windows will not delete a file a program still holds; a file Windows still holds is tried again for a few
  seconds. Removing ComfyUI itself is refused while another copy of ClipForge that is open runs it.

The online studio does not offer local makers (the routes answer 404 in cloud mode). Routes: `GET /api/engines`,
`POST /api/engines/setup|cancel|remove|try|try/cancel` (all need the app's own header), `GET /api/engines/made/<file>`
(this computer only).

## How it was checked

- **Tests:** `tests/test_local_engines.py` (79 tests) with a stand-in ComfyUI and a local file server: every pin is
  filled; licences and Mac-safe number formats; ComfyUI's start command (offline, no add-on nodes, folders that
  exist); PyTorch per computer and driver; uv's set-up commands (no Python on the PATH or in the registry, every
  package bounded by the checked day, PyTorch on its own); set-up refusals; resumed, wrong, oversized and cancelled
  downloads, a finished `.part` file and a refused range; archive escapes; shared and foreign model files (never
  replaced); removal in the app's folders (a shared file kept only for a model that still needs it, and said so;
  ClipForge's own copy untouched; nothing that is not ClipForge's, another program's `.part` file included; a
  stopped download; not while a picture is being made, from starting ComfyUI to saving it; a ComfyUI another
  ClipForge process shares is asked to let go of the files, and is not removed itself while that process runs it); recommended models; the graphs against ComfyUI's official examples;
  model files in a subfolder of the app; sizes and frame counts; making pictures and clips end to end; the same
  request twice with ComfyUI's cache; progress that never goes backwards; plain errors (also ComfyUI 0.43's own model
  loader's); cancel, and waiting until ComfyUI has really stopped; use rules agreed before a download and kept in
  each note; the voice's text handling, chunks and word times; the Settings view, routes and the app-header guard;
  cloud mode. Added after the final review (Nov 10): on Linux a ComfyUI started from a short-lived job's thread
  outlives it and still ends with ClipForge; Stop while ComfyUI is starting, and a picture stopped while ComfyUI is
  being reached is never sent; closing ClipForge stops a set-up under way; a ComfyUI another ClipForge process started
  hands its memory back, before heavy work waits for graphics memory; made files refuse other drives and network
  shares before anything is looked at; Windows long paths, and Remove saying when files could not be deleted; no
  second copy of PyTorch left after set-up; a moved ClipForge folder means set-up again; a ClipForge folder with é,
  ü or 東 in the process list (Windows, Mac); another model's stopped download of the shared text encoder stays with
  it; Remove on a ready model whose only ClipForge file is a stopped download says so. Two tests run the
  animated-shorts maker (`clipfoundry/makers/local_engines.py`) against this door.
  `tests/conftest.py` makes it impossible for any test to download from the internet.
- **Real machines** (`.github/workflows/local-engines-check.yml`, `scripts/local_engines_check.py`), on every push
  that touches the engines, on GitHub's Mac (Apple silicon), Windows and Linux machines:
  - compares every pin with its source (Hugging Face's checksums at the pinned commit, PyPI, GitHub's archive);
  - reads back, from the computer's own process list, a folder named with é, ü and 東 (how ClipForge recognises a
    ComfyUI it started);
  - sets ClipForge's own ComfyUI up from nothing exactly as the app does (and fails if the set-up left a Python on
    the PATH or in the Windows registry, or left uv's cache behind), and starts it;
  - makes a real picture (PNG) and a real H.264 clip with ComfyUI's model-free nodes;
  - sends every ClipForge graph to the real ComfyUI with stand-in model files: each must pass ComfyUI's validation
    and stop only at loading the stand-in model;
  - downloads the voice and speaks two voices, checking length, loudness and every word in order;
  - on Linux, downloads FLUX.2 klein 4B and makes a real picture on the processor.

  Every check passed on all three machines on Nov 8, on Nov 9 on the second review's fixes (run 42704530253), and
  on Nov 10 on the final code (run 42749843276), where each machine also read the folder named with é, ü and 東 back
  exactly. On Nov 10 setting ComfyUI up from nothing (now also deleting uv's cache) took 49 s on Linux and Windows
  and 74 s on the Mac; starting it took 12–19 s; the real FLUX.2 klein picture on Linux's processor took about 4
  minutes after a 1.5-minute model download (25 minutes on Nov 9, when Hugging Face was slow); the voice spoke at
  1.8–3.3 times real time.

## What cannot be checked from the cloud

These need Landry's computer (GitHub's machines have no usable graphics, and the cloud computer cannot reach Hugging
Face):

- pictures and clips on Apple silicon graphics (Metal), and how long they take on a 16 GB and a larger Mac;
- a real video clip with Wan 2.2 (needs a graphics card or a large Mac; minutes per clip);
- Windows with an NVIDIA card (CUDA 13.0, driver 580 or newer);
- using the ComfyUI desktop app already installed on the computer (its port, its model folders);
- the shorts maker using these engines end to end (its thread checks that once a real engine is ready).

## Follow-ups

- Outside the engines, found by the final review: `clipfoundry/builtin_ai.py` starts llama-server with the same
  Linux parent-death signal from whichever thread asks, so on Linux it can stop when that thread ends (fixed here for
  ComfyUI with one lasting starter thread); `clipfoundry/craft/routes.py` resolves a requested path before checking
  it, so on Windows a network-share path could make it connect to that share (fixed here for made files).
- When ComfyUI publishes 0.44 as a release, move the pin after the machine check passes.
- Supertonic's licence asks for "reasonable efforts to use the latest version" of the model: when the pins move, check
  Supertone/supertonic-3 for a newer revision (the pinned one is from May 6 2026).
- Smaller video model files for small NVIDIA cards (fp8), once one set per computer is worth the extra checking.
- LTX-2.5 as a second video model for Windows with NVIDIA: open weights (22B), but under the LTX-2.x Community
  License, which is free only below US$10 million yearly revenue and has use restrictions, and it recommends CUDA.
- For the shorts maker (ideas from WanGP and FreeVideo): a quick draft of each shot at 480p with a fixed seed, then
  only the chosen take at full size; one reference picture per recurring character or place, with every clip started
  from it; a time estimate before long jobs; plain quality levels (Light, Medium, High) instead of sampler numbers.
- A "small graphics card" setting built from ComfyUI's own flags (`--reserve-vram`, `--novram`), only if a 6–8 GB
  NVIDIA card runs out of memory in a real test (WanGP's memory profiles).
- The Brain: cut long reference documents into passages and find the right one by keywords and meaning with the
  embedder ClipForge already ships, so answers can say which paragraph they used (the useful part of WeKnora).
- A creator's own cloned voice, only with an engine whose licence allows commercial use, with the voice owner's
  consent stored next to it (VoiceStudio's rules).
