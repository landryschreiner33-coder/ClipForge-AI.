"""Everything the local makers download, pinned: the address, the size and the SHA-256 of each file, and the licence
it comes under. Nothing is fetched from an address that is not written here (models from Hugging Face honour
HF_ENDPOINT, a mirror). scripts/local_engines_check.py compares every pin with its source and installs the whole set
on Mac, Windows and Linux test machines; docs/clipforge/LOCAL_ENGINES.md explains each choice.

Licences (checked Nov 7 2026): only permissive ones (Apache-2.0, MIT, BSD) or ones that allow commercial use without
conditions that bind ClipForge. ComfyUI is GPL-3.0 and therefore only ever runs as a separate program that ClipForge
talks to over HTTP; nothing of it is imported or shipped inside ClipForge.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

from .files import Pinned

# ------------------------------------------------------------------ the installer (uv) and Python
UV_VERSION = "0.13.7"
UV = {  # the wheels on PyPI (a wheel is a zip; the program is <dist>.data/scripts/uv)
    "mac-arm64": Pinned("uv-0.13.7-py3-none-macosx_11_0_arm64.whl",
                        "https://files.pythonhosted.org/packages/40/a5/8756c38ace102fa13fd4e653e8bc40e1f65924f1c0a0d23350339dac97e5/uv-0.13.7-py3-none-macosx_11_0_arm64.whl",
                        14454941, "f91a229093163eefca89ea1b220a221d64c3beade05d03519a6584d1797a5a5f"),
    "windows-x64": Pinned("uv-0.13.7-py3-none-win_amd64.whl",
                          "https://files.pythonhosted.org/packages/8e/4f/041b59d2a38807a3e31ef41064cf3e45d2752fe0409d89040d52778049ae/uv-0.13.7-py3-none-win_amd64.whl",
                          15330939, "2835e2ab397d0db86323b9975dce75ecd76aa9cfa0d6a2aea84734aae7f8c9b3"),
    "linux-x64": Pinned("uv-0.13.7-py3-none-manylinux_2_17_x86_64.manylinux2014_x86_64.whl",
                        "https://files.pythonhosted.org/packages/b9/93/0e053a2ca4523ee9825ccbedeb7121470d0a188933f11688b6d90d7f5c08/uv-0.13.7-py3-none-manylinux_2_17_x86_64.manylinux2014_x86_64.whl",
                        17202345, "2c9bdc4a872b60a93c5f26c0791089ea11585a4f9d3b3c017d78eb8487505e25"),
}
UV_NOTICE = ("uv " + UV_VERSION + " by Astral, https://github.com/astral-sh/uv, under the MIT or Apache-2.0 licence. "
             "ClipForge uses it to give ComfyUI a Python of its own; uv checks every Python and package it downloads.\n")

# The Python ComfyUI runs on: python-build-standalone (PSF licence), installed by uv, which checks each download
# against the checksums built into it.
PYTHON_VERSION = "3.12"

# ------------------------------------------------------------------ ComfyUI
COMFYUI = {
    # v0.43.0 (Oct 27 2026) is ComfyUI's latest published release; the v0.44 tags after it are not releases yet
    "version": "0.43.0",
    "file": "ComfyUI-0.43.0.tar.gz",
    "url": "https://github.com/comfyanonymous/ComfyUI/archive/refs/tags/v0.43.0.tar.gz",
    "size": 0,            # filled from scripts/local_engines_check.py --pins (GitHub's archive of the tag)
    "sha256": "",
    "inner": "ComfyUI-0.43.0",
    # --offline: its page may not reach the internet and the paid online ("partner") nodes are not loaded;
    # no add-on nodes are loaded either, so ComfyUI runs exactly the nodes that were checked
    "flags": ("--offline", "--disable-all-custom-nodes"),
}
COMFYUI_NOTICE = ("ComfyUI " + COMFYUI["version"] + ", https://github.com/comfyanonymous/ComfyUI, under the GNU "
                  "General Public License version 3 (GPL-3.0). It is a separate program: ClipForge downloads its "
                  "official source release to this computer and talks to it over HTTP on 127.0.0.1. Its source, "
                  "licence and authors are in this folder.\n")

# The model folders ComfyUI reads (ClipForge keeps its models in <models>/comfy/<folder>).
MODEL_FOLDERS = ("diffusion_models", "text_encoders", "vae", "checkpoints", "loras", "clip_vision")

# ------------------------------------------------------------------ PyTorch for this computer
TORCH_VERSION = "2.14.1"        # 2.15.0 (Oct 28) is under the two weeks ComfyUI asks new versions to settle
TORCHVISION_VERSION = "0.29.1"  # released with 2.14.1; ComfyUI 0.43 does not use torchaudio
TORCH = {
    "mps": {"label": "Apple silicon (Metal)", "index": "",
            "packages": [f"torch=={TORCH_VERSION}", f"torchvision=={TORCHVISION_VERSION}"],
            "bytes": 130_000_000, "disk": 600_000_000},
    "cuda": {"label": "an NVIDIA graphics card (CUDA 13.0)", "index": "https://download.pytorch.org/whl/cu130",
             "packages": [f"torch=={TORCH_VERSION}", f"torchvision=={TORCHVISION_VERSION}"],
             "bytes": 3_200_000_000, "disk": 6_500_000_000,
             "min_driver": 580.0},  # CUDA 13.0 needs driver 580 or newer (Windows and Linux)
    "cpu": {"label": "the processor (no graphics card)", "index": "https://download.pytorch.org/whl/cpu",
            "packages": [f"torch=={TORCH_VERSION}", f"torchvision=={TORCHVISION_VERSION}"],
            "bytes": 250_000_000, "disk": 1_100_000_000},
}

# ComfyUI's other packages resolve to what PyPI had on this day, so a later release of one of them cannot change a
# set-up that was checked (uv's --exclude-newer); PyTorch itself is pinned above.
EXCLUDE_NEWER = "2026-11-07T00:00:00Z"
CONSTRAINTS = (f"torch=={TORCH_VERSION}\n"
               f"torchvision=={TORCHVISION_VERSION}\n"
               "numpy<3\n")
CONSTRAINTS_ID = f"2026-11-07/{TORCH_VERSION}/{TORCHVISION_VERSION}/numpy<3"
SETUP_EXTRA_BYTES = 450_000_000   # ComfyUI's own packages (transformers, scipy, av, its page...) and Python
SETUP_EXTRA_DISK = 1_600_000_000


# ------------------------------------------------------------------ models
def hf_url(repo: str, revision: str, path: str) -> str:
    base = (os.environ.get("HF_ENDPOINT") or "https://huggingface.co").rstrip("/")
    return f"{base}/{repo}/resolve/{revision}/{path}"


@dataclass(frozen=True)
class ModelFile:
    """One model file: the ComfyUI folder it goes in, its name there, and where it comes from."""
    folder: str
    name: str
    repo: str
    revision: str
    path: str
    size: int
    sha256: str

    @property
    def pin(self) -> Pinned:
        return Pinned(self.name, hf_url(self.repo, self.revision, self.path), self.size, self.sha256)


@dataclass(frozen=True)
class Model:
    id: str
    role: str                  # "image" | "video" | "voice"
    name: str
    maker: str
    licence: str
    licence_url: str
    about: str                 # one plain sentence for Settings
    files: tuple[ModelFile, ...]
    graph: str = ""            # the graph builder in graphs.py (pictures and video)
    memory_gb: float = 0.0     # the Mac memory it runs well with (Apple silicon shares it with the graphics)
    vram_gb: float = 0.0       # the NVIDIA graphics-card memory it runs well with (less works, more slowly)
    seconds: dict = field(default_factory=dict)  # a rough time for one picture or clip: {"mac": .., "nvidia": ..}
    defaults: dict = field(default_factory=dict)  # steps, cfg, sampler, scheduler, shift, fps, frame rules...

    @property
    def bytes(self) -> int:
        return sum(f.size for f in self.files)


# ------------------------------------------------------------------ the voice (runs inside ClipForge on the processor)
_ST3 = ("Supertone/supertonic-3", "724fb5abbf5502583fb520898d45929e62f02c0b")  # the revision supertonic-py 1.3.1 pins


def _st3(path: str, size: int, sha256: str) -> ModelFile:
    folder, _, name = path.rpartition("/")
    return ModelFile(folder, name, _ST3[0], _ST3[1], path, size, sha256)


SUPERTONIC_3 = Model(
    id="supertonic-3", role="voice", name="Supertonic 3", maker="Supertone Inc.",
    licence="OpenRAIL-M (BigScience Open RAIL-M, Aug 18 2022)",
    licence_url=f"https://huggingface.co/{_ST3[0]}/blob/{_ST3[1]}/LICENSE",
    about="A fast, natural voice that runs on the processor: 10 voices, 31 languages, about 400 MB.",
    files=(
        _st3("onnx/duration_predictor.onnx", 3700147, "c3eb91414d5ff8a7a239b7fe9e34e7e2bf8a8140d8375ffb14718b1c639325db"),
        _st3("onnx/text_encoder.onnx", 36416150, "c7befd5ea8c3119769e8a6c1486c4edc6a3bc8365c67621c881bbb774b9902ff"),
        _st3("onnx/vector_estimator.onnx", 256534781, "883ac868ea0275ef0e991524dc64f16b3c0376efd7c320af6b53f5b780d7c61c"),
        _st3("onnx/vocoder.onnx", 101424195, "085de76dd8e8d5836d6ca66826601f615939218f90e519f70ee8a36ed2a4c4ba"),
        # small files kept in git, not LFS: their SHA-256 comes from scripts/local_engines_check.py --pins
        _st3("onnx/tts.json", 8253, ""),
        _st3("onnx/unicode_indexer.json", 277676, ""),
        _st3("voice_styles/F1.json", 292046, ""), _st3("voice_styles/F2.json", 292423, ""),
        _st3("voice_styles/F3.json", 290794, ""), _st3("voice_styles/F4.json", 291808, ""),
        _st3("voice_styles/F5.json", 291479, ""), _st3("voice_styles/M1.json", 291748, ""),
        _st3("voice_styles/M2.json", 292055, ""), _st3("voice_styles/M3.json", 290198, ""),
        _st3("voice_styles/M4.json", 291522, ""), _st3("voice_styles/M5.json", 291469, ""),
        _st3("LICENSE", 15007, ""),
    ),
    defaults={"steps": 8, "speed": 1.05, "chunk": 300, "chunk_ko": 120, "pause_s": 0.3},
)
# The licence's use rules (Attachment A) bind whoever uses the voice; the one that matters for posting is (e): what it
# makes must be clearly labelled as machine-generated where it is shown. Settings says so before the download.
SUPERTONIC_RULE = ("Supertonic's licence (OpenRAIL-M) lets you use the voice for free, also commercially, with use "
                   "rules: no impersonating real people, nothing illegal or harmful, and anything it makes must be "
                   "clearly labelled as machine-generated where you post it (for example the AI-generated label on "
                   "TikTok and YouTube).")


# ------------------------------------------------------------------ pictures and video (run in ComfyUI)
# Each set is the one in ComfyUI's official example for the model, in the full-precision files: the smaller "fp8"
# and "int8" files do not run on a Mac (PyTorch has no Metal support for those number formats), and one set for every
# computer keeps what was checked and what runs the same. Repositories are pinned to a commit.
_ZIT = ("Comfy-Org/Z-Image-Turbo", "6fc90a3b1b653e935a0d175e260736de25b84df5")
_KLEIN = ("Comfy-Org/Flux-2-Klein-4B", "5b3abca5c0dc1ecd4eaf3340868d09063fc1c965")
_WAN22 = ("Comfy-Org/Wan-2.2", "ee6f4a40737a995bf5818954cfce6d59443b0f04")
_WAN21 = ("Comfy-Org/Wan-2.1", "123acf1cc74bccbb9bfff8ac1ee72edc08c2341d")


def _hf(repo: tuple[str, str], path: str, size: int, sha256: str) -> ModelFile:
    """A file from a ComfyUI "split_files/<folder>/<name>" repository."""
    parts = path.split("/")
    return ModelFile(parts[-2], parts[-1], repo[0], repo[1], path, size, sha256)


# The Qwen3 4B text encoder is the same file for both picture models (same name, size and SHA-256), so a second
# picture model downloads only its own files and removing one keeps it for the other.
_QWEN3_4B_ZIT = _hf(_ZIT, "split_files/text_encoders/qwen_3_4b.safetensors", 8044982048,
                    "6c671498573ac2f7a5501502ccce8d2b08ea6ca2f661c458e708f36b36edfc5a")
_QWEN3_4B_KLEIN = _hf(_KLEIN, "split_files/text_encoders/qwen_3_4b.safetensors", 8044982048,
                      "6c671498573ac2f7a5501502ccce8d2b08ea6ca2f661c458e708f36b36edfc5a")

Z_IMAGE_TURBO = Model(
    id="z-image-turbo", role="image", name="Z-Image Turbo", maker="Tongyi Lab (Alibaba)",
    licence="Apache-2.0", licence_url="https://huggingface.co/Tongyi-MAI/Z-Image-Turbo",
    about="The best pictures: realistic, detailed, and good at words written in the picture. About 21 GB.",
    files=(
        _hf(_ZIT, "split_files/diffusion_models/z_image_turbo_bf16.safetensors", 12309866400,
            "2407613050b809ffdff18a4ac99af83ea6b95443ecebdf80e064a79c825574a6"),
        _QWEN3_4B_ZIT,
        _hf(_ZIT, "split_files/vae/ae.safetensors", 335304388,
            "afc8e28272cd15db3919bacdb6918ce9c1ed22e96cb12c4d5ed0fba823529e38"),
    ),
    graph="zimage", memory_gb=24, vram_gb=12,
    seconds={"mac": 150, "nvidia": 15},
    # ComfyUI's official example: 8 steps, no guidance, res_multistep/simple, AuraFlow shift 3
    defaults={"clip_type": "lumina2", "steps": 8, "cfg": 1.0, "sampler": "res_multistep", "scheduler": "simple",
              "shift": 3.0, "step": 16, "max_pixels": 2_100_000},
)

FLUX2_KLEIN_4B = Model(
    id="flux2-klein-4b", role="image", name="FLUX.2 klein 4B", maker="Black Forest Labs",
    licence="Apache-2.0", licence_url="https://huggingface.co/black-forest-labs/FLUX.2-klein-4B",
    about="Quick, good pictures in 4 steps; the one for a Mac with 16 GB of memory. About 16 GB.",
    files=(
        _hf(_KLEIN, "split_files/diffusion_models/flux-2-klein-4b.safetensors", 7751105712,
            "ec3d4e733a771f61c052fb4856c48b336c55eaf2c65487c2a1faeb9bbda7a343"),
        _QWEN3_4B_KLEIN,
        _hf(_KLEIN, "split_files/vae/flux2-vae.safetensors", 336211292,
            "868fe7b343cc8f3a19dbcfcafbc3d5f888802be3f89bd81b65b3621a066ce8f3"),
    ),
    graph="flux2", memory_gb=16, vram_gb=8,
    seconds={"mac": 60, "nvidia": 6},
    # ComfyUI's official example for the distilled 4B: 4 steps, no guidance, euler, the FLUX.2 schedule
    defaults={"clip_type": "flux2", "steps": 4, "cfg": 1.0, "sampler": "euler", "step": 16,
              "max_pixels": 2_100_000},
)

# Wan's own default negative words (Chinese, as the model was trained with them): over-saturated, over-exposed,
# static, blurry, subtitles, worst quality, JPEG artefacts, extra fingers, deformed hands and faces, fused fingers,
# a still picture, a cluttered background, three legs, crowds in the background, walking backwards.
WAN_NEGATIVE = ("色调艳丽，过曝，静态，细节模糊不清，字幕，风格，作品，画作，画面，静止，整体发灰，最差质量，低质量，JPEG压缩残留，"
                "丑陋的，残缺的，多余的手指，画得不好的手部，画得不好的脸部，畸形的，毁容的，形态畸形的肢体，手指融合，"
                "静止不动的画面，杂乱的背景，三条腿，背景人很多，倒着走")

WAN22_TI2V_5B = Model(
    id="wan2.2-ti2v-5b", role="video", name="Wan 2.2 (5B)", maker="Wan team (Alibaba)",
    licence="Apache-2.0", licence_url="https://huggingface.co/Wan-AI/Wan2.2-TI2V-5B",
    about="Short clips of up to 5 seconds from words or from a picture. About 23 GB. On a Mac a clip takes minutes.",
    files=(
        _hf(_WAN22, "split_files/diffusion_models/wan2.2_ti2v_5B_fp16.safetensors", 9999658848,
            "456f901338bd9eadbded3828b819109a9b68e8a525ca5cf8d0049a69fcfeca1e"),
        _hf(_WAN21, "split_files/text_encoders/umt5_xxl_fp16.safetensors", 11366399385,
            "7b8850f1961e1cf8a77cca4c964a358d303f490833c6c087d0cff4b2f99db2af"),
        _hf(_WAN22, "split_files/vae/wan2.2_vae.safetensors", 1409400960,
            "e40321bd36b9709991dae2530eb4ac303dd168276980d3e9bc4b6e2b75fed156"),
    ),
    graph="wan22_5b", memory_gb=32, vram_gb=12,
    seconds={"mac": 600, "nvidia": 90},
    # ComfyUI's official example: 20 steps, cfg 5, uni_pc/simple, SD3 shift 8, 24 frames a second, 1280x704
    defaults={"steps": 20, "cfg": 5.0, "sampler": "uni_pc", "scheduler": "simple", "shift": 8.0, "fps": 24,
              "step": 32, "max_pixels": 1280 * 704, "max_seconds": 5.0, "negative": WAN_NEGATIVE},
)

MODELS: tuple[Model, ...] = (Z_IMAGE_TURBO, FLUX2_KLEIN_4B, WAN22_TI2V_5B, SUPERTONIC_3)


def by_id(model_id: str) -> Model | None:
    return next((m for m in MODELS if m.id == model_id), None)


def for_role(role: str) -> list[Model]:
    return [m for m in MODELS if m.role == role]
