"""The ComfyUI graphs ClipForge sends, in ComfyUI's "API format" ({node id: {"class_type", "inputs"}}; an input that
comes from another node is [node id, output index]). Each model family has one builder, written after the model's
official ComfyUI example; scripts/local_engines_check.py has a real ComfyUI check every graph here.

Two graphs need no model at all (`check_picture`, `check_video`): they prove that a ComfyUI takes ClipForge's
requests, reports progress, saves pictures and encodes MP4 video, on any computer, in seconds.
"""
from __future__ import annotations

import math

from .catalog import Model

PREFIX = "clipforge"


def _n(class_type: str, **inputs) -> dict:
    return {"class_type": class_type, "inputs": inputs}


def class_types(graph: dict) -> list[str]:
    return sorted({node["class_type"] for node in graph.values()})


# ------------------------------------------------------------------ sizes
def snap(value: float, step: int, lo: int, hi: int) -> int:
    return int(max(lo, min(hi, round(float(value) / step) * step)))


def picture_size(model: Model, width: int, height: int) -> tuple[int, int]:
    """The size `model` draws at: a multiple of its step, and no more pixels than it handles (same shape)."""
    step = int(model.defaults.get("step", 16))
    most = float(model.defaults.get("max_pixels", 2_100_000))
    w, h = max(64, int(width)), max(64, int(height))
    if w * h > most:
        k = math.sqrt(most / (w * h))
        w, h = w * k, h * k
    return snap(w, step, step * 4, 4096), snap(h, step, step * 4, 4096)


def video_shape(model: Model, width: int, height: int, seconds: float) -> tuple[int, int, int, int]:
    """(width, height, frames, fps) for `model`: its size step, its pixel budget, its frame rule (4n+1) and length."""
    d = model.defaults
    step, fps = int(d.get("step", 32)), int(d.get("fps", 24))
    most = float(d.get("max_pixels", 921_600))
    w, h = max(64, int(width)), max(64, int(height))
    if w * h > most:
        k = math.sqrt(most / (w * h))
        w, h = w * k, h * k
    w, h = snap(w, step, step * 4, 2048), snap(h, step, step * 4, 2048)

    def nearest(n: float) -> int:  # the model makes 4n + 1 frames
        return 4 * round((n - 1) / 4) + 1

    most = nearest(float(d.get("max_seconds", 5.0)) * fps)  # 5 seconds: 121 frames, as in Wan's own example
    frames = max(5, min(most, nearest(max(0.1, float(seconds)) * fps)))
    return w, h, frames, fps


# ------------------------------------------------------------------ checks without a model
def check_picture(width: int = 256, height: int = 256, color: int = 0x3366CC) -> tuple[dict, str]:
    return {"1": _n("EmptyImage", width=width, height=height, batch_size=1, color=color),
            "2": _n("SaveImage", images=["1", 0], filename_prefix=f"{PREFIX}/check")}, ""


def check_video(width: int = 256, height: int = 256, frames: int = 25, fps: int = 24) -> tuple[dict, str]:
    return {"1": _n("EmptyImage", width=width, height=height, batch_size=frames, color=0xCC6633),
            "2": _n("CreateVideo", images=["1", 0], fps=float(fps)),
            "3": _n("SaveVideo", video=["2", 0], filename_prefix=f"{PREFIX}/check", format="mp4",
                    **{"format.codec": "h264"})}, ""


# ------------------------------------------------------------------ pictures
def picture(model: Model, prompt: str, negative: str, width: int, height: int, seed: int, *,
            names: dict[str, str] | None = None, prefix: str = f"{PREFIX}/picture") -> tuple[dict, str]:
    """(graph, the node whose steps are the progress) for one picture. `names` maps a model file's name to the name
    the ComfyUI in use lists it by (a ComfyUI app may keep it in a subfolder: "flux2/<name>", "flux2\\<name>" on
    Windows); `prefix` is where ComfyUI saves it (a new one for each job: ComfyUI answers an identical graph from its
    cache without saving the file again)."""
    builder = {"zimage": _zimage, "flux2": _flux2}.get(model.graph)
    if builder is None:
        raise ValueError(f"no picture graph for {model.graph!r}")
    return builder(model, prompt, negative, width, height, seed, _files(model, names), prefix)


def _files(model: Model, names: dict[str, str] | None = None) -> dict[str, str]:
    """{ComfyUI folder: the name ComfyUI knows the model's file in it by}."""
    return {f.folder: (names or {}).get(f.name) or f.name for f in model.files}


def _zimage(model: Model, prompt: str, negative: str, width: int, height: int, seed: int, f: dict[str, str],
            prefix: str) -> tuple[dict, str]:
    """Z-Image (Tongyi-MAI): Qwen3 text encoder, a flow model with AuraFlow sampling, the FLUX autoencoder.
    Turbo needs no guidance (cfg 1), so the negative words are not used; the empty side is zeroed as in the
    official example."""
    d = model.defaults
    g = {
        "1": _n("UNETLoader", unet_name=f["diffusion_models"], weight_dtype="default"),
        "2": _n("CLIPLoader", clip_name=f["text_encoders"], type=d.get("clip_type", "lumina2"), device="default"),
        "3": _n("VAELoader", vae_name=f["vae"]),
        "4": _n("ModelSamplingAuraFlow", model=["1", 0], shift=float(d.get("shift", 3.0))),
        "5": _n("CLIPTextEncode", clip=["2", 0], text=prompt),
        "6": _n("ConditioningZeroOut", conditioning=["5", 0]),
        "7": _n("EmptySD3LatentImage", width=width, height=height, batch_size=1),
        "8": _n("KSampler", model=["4", 0], seed=int(seed), steps=int(d.get("steps", 8)), cfg=float(d.get("cfg", 1.0)),
                sampler_name=d.get("sampler", "res_multistep"), scheduler=d.get("scheduler", "simple"),
                positive=["5", 0], negative=["6", 0], latent_image=["7", 0], denoise=1.0),
        "9": _n("VAEDecode", samples=["8", 0], vae=["3", 0]),
        "10": _n("SaveImage", images=["9", 0], filename_prefix=prefix),
    }
    if negative and float(d.get("cfg", 1.0)) > 1.0:
        g["6"] = _n("CLIPTextEncode", clip=["2", 0], text=negative)
    return g, "8"


def _flux2(model: Model, prompt: str, negative: str, width: int, height: int, seed: int, f: dict[str, str],
           prefix: str) -> tuple[dict, str]:
    """FLUX.2 [klein] (Black Forest Labs): Qwen3 text encoder, the FLUX.2 autoencoder, its own step schedule; the
    distilled model needs no guidance (cfg 1)."""
    d = model.defaults
    g = {
        "1": _n("UNETLoader", unet_name=f["diffusion_models"], weight_dtype="default"),
        "2": _n("CLIPLoader", clip_name=f["text_encoders"], type=d.get("clip_type", "flux2"), device="default"),
        "3": _n("VAELoader", vae_name=f["vae"]),
        "4": _n("CLIPTextEncode", clip=["2", 0], text=prompt),
        "5": _n("EmptyFlux2LatentImage", width=width, height=height, batch_size=1),
        "6": _n("Flux2Scheduler", steps=int(d.get("steps", 4)), width=width, height=height),
        "7": _n("KSamplerSelect", sampler_name=d.get("sampler", "euler")),
        "8": _n("RandomNoise", noise_seed=int(seed)),
        "9": _n("CFGGuider", model=["1", 0], positive=["4", 0], negative=["10", 0], cfg=float(d.get("cfg", 1.0))),
        "10": _n("ConditioningZeroOut", conditioning=["4", 0]),
        "11": _n("SamplerCustomAdvanced", noise=["8", 0], guider=["9", 0], sampler=["7", 0], sigmas=["6", 0],
                 latent_image=["5", 0]),
        "12": _n("VAEDecode", samples=["11", 0], vae=["3", 0]),
        "13": _n("SaveImage", images=["12", 0], filename_prefix=prefix),
    }
    if negative and float(d.get("cfg", 1.0)) > 1.0:
        g["10"] = _n("CLIPTextEncode", clip=["2", 0], text=negative)
    return g, "11"


# ------------------------------------------------------------------ video
def video(model: Model, prompt: str, negative: str, width: int, height: int, frames: int, fps: int, seed: int,
          image: str = "", *, names: dict[str, str] | None = None, prefix: str = f"{PREFIX}/video") -> tuple[dict, str]:
    """(graph, the sampler node) for one clip; `image` is a picture ComfyUI already has (upload_image) to start
    from; `names` and `prefix` as for picture()."""
    builder = {"wan22_5b": _wan22_5b}.get(model.graph)
    if builder is None:
        raise ValueError(f"no video graph for {model.graph!r}")
    return builder(model, prompt, negative, width, height, frames, fps, seed, image, _files(model, names), prefix)


def _wan22_5b(model: Model, prompt: str, negative: str, width: int, height: int, frames: int, fps: int, seed: int,
              image: str, f: dict[str, str], prefix: str) -> tuple[dict, str]:
    """Wan 2.2 TI2V 5B (Alibaba, Apache-2.0): words to video, or a picture to video, in one model; umT5 text encoder,
    the Wan 2.2 autoencoder (16x smaller frames), 24 frames a second, as in ComfyUI's official example."""
    d = model.defaults
    g = {
        "1": _n("UNETLoader", unet_name=f["diffusion_models"], weight_dtype="default"),
        "2": _n("CLIPLoader", clip_name=f["text_encoders"], type="wan", device="default"),
        "3": _n("VAELoader", vae_name=f["vae"]),
        "4": _n("ModelSamplingSD3", model=["1", 0], shift=float(d.get("shift", 8.0))),
        "5": _n("CLIPTextEncode", clip=["2", 0], text=prompt),
        "6": _n("CLIPTextEncode", clip=["2", 0], text=negative or d.get("negative", "")),
        "7": _n("Wan22ImageToVideoLatent", vae=["3", 0], width=width, height=height, length=frames, batch_size=1),
        "8": _n("KSampler", model=["4", 0], seed=int(seed), steps=int(d.get("steps", 20)), cfg=float(d.get("cfg", 5.0)),
                sampler_name=d.get("sampler", "uni_pc"), scheduler=d.get("scheduler", "simple"),
                positive=["5", 0], negative=["6", 0], latent_image=["7", 0], denoise=1.0),
        "9": _n("VAEDecode", samples=["8", 0], vae=["3", 0]),
        "10": _n("CreateVideo", images=["9", 0], fps=float(fps)),
        "11": _n("SaveVideo", video=["10", 0], filename_prefix=prefix, format="mp4",
                 **{"format.codec": "h264"}),
    }
    if image:
        g["12"] = _n("LoadImage", image=image)
        g["7"]["inputs"]["start_image"] = ["12", 0]
    return g, "8"


LABELS = {"UNETLoader": "Loading the model", "CLIPLoader": "Loading the model", "VAELoader": "Loading the model",
          "CLIPTextEncode": "Reading the words", "KSampler": "Drawing", "SamplerCustomAdvanced": "Drawing",
          "VAEDecode": "Finishing", "SaveImage": "Saving", "CreateVideo": "Putting the frames together",
          "SaveVideo": "Saving", "LoadImage": "Reading the picture", "Wan22ImageToVideoLatent": "Preparing"}


def labels(graph: dict) -> dict[str, str]:
    return {nid: LABELS.get(node["class_type"], "Working") for nid, node in graph.items()}
