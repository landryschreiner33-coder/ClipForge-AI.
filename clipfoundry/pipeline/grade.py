"""Colour: phone HDR turned into normal video, automatic correction once per recording, recordings matched to each
other, and looks.

Everything a shot needs is baked into one small 3D colour table (a 33x33x33 ``.cube`` file) and applied by FFmpeg's
``lut3d`` filter, which every FFmpeg build has (the Mac build has no zscale/zimg, and ``eq``/``hqdn3d`` exist only in
GPL builds). The table is computed here in numpy from a few frames of the recording, so the same maths runs on every
computer and in every renderer (short clips and full videos), and a render is reproducible: the analysis is cached and
the table is cached by a hash of everything that went into it.

Order inside the table (each step is a pure function of the pixel's colour, so it can live in a table):

1. HDR to SDR, only for HLG or PQ footage (iPhone and most Android phones record HLG by default). Display light
   normalised so HDR reference white (203 nits) is 1.0, BT.2020 to BT.709 primaries in linear light, FFmpeg's Mobius
   tone curve (param 0.3) on the brightest channel with its highlight desaturation, then BT.1886 (gamma 2.4) encoding.
   This is the same maths as ``zscale=t=linear:npl=203,zscale=p=bt709,tonemap=mobius:param=0.3,zscale=t=bt709``
   (BT.2408 18% grey, HLG 38%, lands at 42-43%, reference white at 84%). Without it the picture is flat and grey.
2. White balance: the light's colour is read from the greyest fifth of the unclipped, not-too-dark pixels (grey things
   show a cast; a blue sky or green grass is just coloured) and checked against the brightest pixels' colour. A cast
   under 1 degree is invisible and left alone; when the two agree (under 3 degrees) 70% of the cast is removed, 35%
   when they roughly agree (3-8 degrees), 60% of that for a strong cast (over 10 degrees, maybe the light's mood) and
   nothing for a very strong one (over 16 degrees: a sunset, a stage, a neon sign) or when they disagree. Gains are
   kept within 0.85-1.18. A game or screen recording (almost no skin tones) gets half.
3. Levels, only when clearly off: foggy blacks (darkest 0.5% above 10%) are deepened half way, dim whites (brightest
   0.5% under 80%) lifted toward 92%, and very dark or bright mid-tones moved half way toward normal (gamma 0.8-1.25,
   at most half a stop of exposure change in all); a gentle S-curve only on flat footage such as log. Levels change
   brightness only, so colours keep their saturation. A well-exposed picture is left as it is.
4. Vibrance on flat footage only (low-saturation colours gain most), at 30% inside skin tones.
5. Matching (full videos): a recording's average colour cast and brightness are nudged toward the main recording's,
   mid-tones only, capped.
6. A look (warm, film, teal and orange...), clearly recognisable at 100% and mixed in by its strength, with skin
   tones protected.
7. A soft gamut clip: colours outside the displayable range move toward grey instead of clipping channel by channel.

The analysis is per recording or per clip, never per frame, so nothing flickers or "breathes".

Noisy footage (low light, webcams) is measured too (Immerkaer's noise estimate on the flattest parts of a few
full-resolution frames) and cleaned with ``atadenoise`` (moderate) or ``fftdnoiz`` (heavy), both LGPL and built in.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np

from .. import config
from .common import Cancelled
from .ffmpeg_utils import NO_WINDOW, ffmpeg_bin, ffprobe_bin, run_process

VERSION = 1
LUT_SIZE = 33
SAMPLE_WIDTH = 256           # analysis frames are this wide
SAMPLES = 10                 # frames looked at per recording or clip
NOISE_SAMPLES = 3            # full-resolution crops for the noise estimate
NOISE_CROP = (640, 360)

LOOKS = {  # value: shown name
    "natural": "Natural",
    "bright": "Clean and bright",
    "warm": "Warm",
    "cool": "Cool",
    "film": "Film",
    "teal_orange": "Teal and orange",
    "moody": "Moody",
    "vintage": "Vintage",
    "mono": "Black and white",
}
LOOK_WORDS = {  # what each look does, in plain words (shown next to the choice and in render notes)
    "natural": "colours corrected, no added style",
    "bright": "lifted mid-tones and a little more colour, for a clean, airy picture",
    "warm": "a warmer, golden picture",
    "cool": "a cooler, bluer picture",
    "film": "a soft film curve, gentle highlights, slightly muted colour",
    "teal_orange": "blue-green shadows and warm highlights, skin left alone",
    "moody": "darker mid-tones, muted colour and cool shadows",
    "vintage": "faded blacks, soft highlights and a warm, yellowed tint",
    "mono": "black and white with a little extra contrast",
}

# BT.709 / BT.2020 luma weights and the BT.2020 -> BT.709 primaries matrix (linear light)
W709 = np.array([0.2126, 0.7152, 0.0722])
W2020 = np.array([0.2627, 0.6780, 0.0593])
M2020_TO_709 = np.array([[1.660491, -0.587641, -0.072850],
                         [-0.124550, 1.132900, -0.008349],
                         [-0.018151, -0.100579, 1.118730]])

# HDR
REF_WHITE_NITS = 203.0       # BT.2408 HDR reference white: linear 1.0
HLG_PEAK_NITS = 1000.0       # the HLG reference display
MOBIUS_J = 0.3               # FFmpeg tonemap=mobius default param
MOBIUS_PEAK_HLG = 10.0       # FFmpeg's default signal peak for HLG (1000 nits in its 100-nit units)
DESAT = 2.0                  # FFmpeg tonemap's default highlight desaturation
HLG_A, HLG_B, HLG_C = 0.17883277, 0.28466892, 0.55991073
PQ_M1, PQ_M2 = 2610 / 16384, 2523 / 4096 * 128
PQ_C1, PQ_C2, PQ_C3 = 3424 / 4096, 2413 / 4096 * 32, 2392 / 4096 * 32

# Correction limits
WB_CLAMP = (0.85, 1.18)
WB_MIN_SHARE = 0.05          # at least this share of pixels must be usable for white balance
GREY_SHARE = 0.2             # the greyest fifth of the usable pixels tells the light's colour
WB_MIN_CAST = 1.0            # degrees: a smaller cast is not visible and is left alone
WB_STRONG = 10.0             # degrees: a stronger cast is corrected less (it may be the light's mood)...
WB_DELIBERATE = 16.0         # ...and one this strong is a sunset, a stage or a neon sign: left alone
WB_AGREE = (3.0, 8.0)        # degrees between the greys' and the brightest pixels' colour: agree / roughly agree
BLACK_FROM, BLACK_TO, BLACK_MAX = 0.10, 0.03, 0.05
WHITE_FROM, WHITE_TO, WHITE_GAIN_MAX = 0.80, 0.92, 1.2
MID_RANGE, MID_TARGET = (0.25, 0.66), (0.38, 0.52)
GAMMA_RANGE = (0.8, 1.25)
MAX_STOPS = 0.5
FLAT_SPREAD = 0.45           # p95 - p5 of luma under this: flat footage such as log (gets a gentle S-curve)
FLAT_CHROMA = 0.06           # mean chroma under this: washed-out colour (gets vibrance)
VIBRANCE_MAX = 0.2
SKIN_KEEP = 0.7              # share of a saturation or tint change kept away from skin
MATCH_STRENGTH = 0.7
MATCH_CHROMA_MAX = 0.02      # at most this much change in Cb/Cr (normalised) when matching
MATCH_GAMMA = (0.9, 1.1)
MATCH_PIXELS = 1500          # pixels kept with a recording's statistics for matching
MATCH_SKIN = 0.02            # recordings with at least this share of skin-coloured pixels are matched to each other

# Noise (8-bit luma code values)
NOISE_NONE, NOISE_HEAVY, NOISE_MAX = 1.5, 3.5, 10.0


# ---------------------------------------------------------------- source colour
_probe_lock = threading.Lock()
_probe_cache: dict[tuple, dict] = {}


def source_colour(path: str | Path) -> dict:
    """The colour tags of a file's first video stream (cached by path, size and time): transfer, primaries, matrix,
    range, pixel format and, for PQ, the brightest pixel the file claims (MaxCLL). Missing tags are empty strings."""
    p = Path(path)
    try:
        st = p.stat()
        key = (str(p), st.st_size, st.st_mtime_ns)
    except OSError:
        key = (str(p), 0, 0)
    with _probe_lock:
        if key in _probe_cache:
            return dict(_probe_cache[key])
    out = {"transfer": "", "primaries": "", "matrix": "", "range": "", "pix_fmt": "", "width": 0, "height": 0,
           "max_cll": 0.0}
    try:
        res = run_process([ffprobe_bin(), "-v", "error", "-select_streams", "v:0", "-print_format", "json",
                           "-show_entries", "stream=color_transfer,color_primaries,color_space,color_range,pix_fmt,"
                           "width,height:stream_side_data=max_content", str(p)], timeout=30.0)
        data = json.loads(res.stdout or b"{}")
        streams = data.get("streams") or []
        if res.returncode != 0 or not streams:
            return out  # not cached: a timeout or a file still being written is read again next time
        s = streams[0]
        out.update({"transfer": s.get("color_transfer") or "", "primaries": s.get("color_primaries") or "",
                    "matrix": s.get("color_space") or "", "range": s.get("color_range") or "",
                    "pix_fmt": s.get("pix_fmt") or "", "width": int(s.get("width") or 0),
                    "height": int(s.get("height") or 0)})
        for sd in s.get("side_data_list") or []:
            if sd.get("max_content"):
                out["max_cll"] = float(sd["max_content"])
        if out["transfer"] == "smpte2084" and not out["max_cll"]:
            out["max_cll"] = _frame_peak(p)
    except Exception:  # noqa: BLE001 - an unreadable file is graded as untagged SDR (and fails later if broken)
        return out
    with _probe_lock:
        _probe_cache[key] = dict(out)
    return out


def _frame_peak(p: Path) -> float:
    """A PQ file's brightest pixel in nits from its first frame (HEVC HDR10 keeps MaxCLL and the mastering display
    there, not on the stream): MaxCLL, else the mastering display's peak, else 0 (1000 nits is assumed)."""
    try:
        res = run_process([ffprobe_bin(), "-v", "error", "-select_streams", "v:0", "-read_intervals", "%+#1",
                           "-print_format", "json", "-show_entries", "frame_side_data=max_content,max_luminance",
                           str(p)], timeout=30.0)
        frames = json.loads(res.stdout or b"{}").get("frames") or []
    except Exception:  # noqa: BLE001
        return 0.0
    cll = lum = 0.0
    for sd in (frames[0].get("side_data_list") or []) if frames else []:
        if sd.get("max_content"):
            cll = float(sd["max_content"])
        if sd.get("max_luminance"):
            num, _, den = str(sd["max_luminance"]).partition("/")
            try:
                lum = float(num) / float(den or 1)
            except (ValueError, ZeroDivisionError):
                pass
    return cll or lum


def hdr_kind(colour: dict | None) -> str | None:
    """'hlg' or 'pq' for HDR footage, None for normal (SDR) video."""
    t = (colour or {}).get("transfer") or ""
    if t == "arib-std-b67":
        return "hlg"
    if t == "smpte2084":
        return "pq"
    return None


def input_matrix(colour: dict | None, height: int = 0) -> str:
    """The YCbCr matrix to read a file with. Untagged HD (720 lines or more) is BT.709 and untagged SD is BT.601,
    the usual convention; FFmpeg's own fallback is BT.601 for everything, which turns HD reds and greens wrong."""
    m = (colour or {}).get("matrix") or ""
    if m in ("bt2020nc", "bt2020c"):
        return "bt2020"
    if m in ("bt470bg", "smpte170m", "bt601"):
        return "bt601"
    if m == "bt709":
        return "bt709"
    if m == "fcc":
        return "fcc"
    if m == "smpte240m":
        return "smpte240m"
    if hdr_kind(colour) or (colour or {}).get("primaries") == "bt2020":
        return "bt2020"
    h = int(height or (colour or {}).get("height") or 0)
    return "bt709" if h >= 720 or h == 0 else "bt601"


def input_range(colour: dict | None) -> str:
    return "pc" if (colour or {}).get("range") in ("pc", "jpeg", "full") else "tv"


def high_depth(colour: dict | None) -> bool:
    fmt = (colour or {}).get("pix_fmt") or ""
    return any(tag in fmt for tag in ("10", "12", "16", "p010", "p016"))


# ---------------------------------------------------------------- transfer functions
def hlg_to_display(e: np.ndarray) -> np.ndarray:
    """HLG signal (BT.2020 R'G'B', 0-1) to display light in units of HDR reference white (203 nits)."""
    e = np.clip(e, 0.0, 1.0)
    scene = np.where(e <= 0.5, e * e / 3.0, (np.exp((e - HLG_C) / HLG_A) + HLG_B) / 12.0)
    ys = np.maximum(scene @ W2020, 1e-12)[..., None]
    # BT.2100 OOTF for a 1000-nit display: system gamma 1.2
    return HLG_PEAK_NITS * ys ** 0.2 * scene / REF_WHITE_NITS


def pq_to_display(e: np.ndarray) -> np.ndarray:
    """PQ signal (SMPTE ST 2084, BT.2020 R'G'B', 0-1) to display light in units of 203 nits."""
    e = np.clip(e, 0.0, 1.0)
    p = e ** (1.0 / PQ_M2)
    nits = 10000.0 * (np.maximum(p - PQ_C1, 0.0) / (PQ_C2 - PQ_C3 * p)) ** (1.0 / PQ_M1)
    return nits / REF_WHITE_NITS


def _mobius(x: np.ndarray, j: float, peak: float) -> np.ndarray:
    a = -j * j * (peak - 1.0) / (j * j - 2.0 * j + peak)
    b = (j * j - 2.0 * j * peak + peak) / max(peak - 1.0, 1e-6)
    return np.where(x <= j, x, (b * b + 2.0 * b * j + j * j) / (b - a) * (x + a) / (x + b))


def to_sdr(rgb: np.ndarray, kind: str, max_cll: float = 0.0) -> np.ndarray:
    """HDR R'G'B' (BT.2020, HLG or PQ) to SDR R'G'B' (BT.709, gamma 2.4), 0-1."""
    lin = hlg_to_display(rgb) if kind == "hlg" else pq_to_display(rgb)
    lin = lin @ M2020_TO_709.T
    if kind == "hlg":
        peak = MOBIUS_PEAK_HLG
    else:  # PQ: the brightest pixel the file declares, else a 1000-nit master (FFmpeg's units are 100 nits)
        peak = min(100.0, max(REF_WHITE_NITS / 100.0 * 2.5, (max_cll or 1000.0) / 100.0))
    luma = lin @ W709
    over = np.maximum(luma - DESAT, 1e-6) / np.maximum(luma, 1e-6)
    lin = lin + (luma[..., None] - lin) * over[..., None]
    sig = np.maximum(lin.max(axis=-1), 1e-6)
    lin = lin * (_mobius(sig, MOBIUS_J, peak) / sig)[..., None]
    lin = _gamut_clip(lin)
    return np.clip(lin, 0.0, 1.0) ** (1.0 / 2.4)


def _gamut_clip(x: np.ndarray) -> np.ndarray:
    """Colours outside 0-1 move toward their own grey (luma) just far enough to fit, instead of clipping each
    channel (which shifts hue)."""
    y = np.clip(x @ W709, 0.0, 1.0)[..., None]
    d = x - y
    hi = np.where(d > 1e-9, (1.0 - y) / np.maximum(d, 1e-9), np.inf)
    lo = np.where(d < -1e-9, y / np.maximum(-d, 1e-9), np.inf)
    t = np.minimum(1.0, np.minimum(hi.min(axis=-1, keepdims=True), lo.min(axis=-1, keepdims=True)))
    return y + d * t


# ---------------------------------------------------------------- YCbCr helpers (gamma domain, BT.709)
def _ycc(x: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    y = x @ W709
    return y, (x[..., 2] - y) / 1.8556, (x[..., 0] - y) / 1.5748


def _rgb(y: np.ndarray, cb: np.ndarray, cr: np.ndarray) -> np.ndarray:
    r = y + 1.5748 * cr
    b = y + 1.8556 * cb
    g = (y - 0.2126 * r - 0.0722 * b) / 0.7152
    return np.stack([r, g, b], axis=-1)


def skin_mask(x: np.ndarray) -> np.ndarray:
    """0-1 weight of how much a colour looks like skin (any skin tone): Cb 77-127 and Cr 133-173 in 8-bit codes
    (Chora's 2008), with soft edges of 6 codes, and not near black."""
    y, cb, cr = _ycc(x)
    cb8, cr8 = 128 + 224 * cb, 128 + 224 * cr

    def band(v, lo, hi, soft=6.0):
        return np.clip((v - (lo - soft)) / soft, 0, 1) * np.clip(((hi + soft) - v) / soft, 0, 1)

    return band(cb8, 77, 127) * band(cr8, 133, 173) * np.clip((y - 0.08) / 0.07, 0, 1)


def _luma(x: np.ndarray) -> np.ndarray:
    return (x @ W709)[..., None]


def _saturate(x: np.ndarray, amount: float, skin: np.ndarray | None = None) -> np.ndarray:
    """Multiply colourfulness by `amount` (skin keeps only 30% of the change)."""
    y = _luma(x)
    k = amount if skin is None else 1.0 + (amount - 1.0) * (1.0 - SKIN_KEEP * skin)[..., None]
    return y + (x - y) * k


def _vibrance(x: np.ndarray, amount: float, skin: np.ndarray) -> np.ndarray:
    """More colour for the least colourful pixels; vivid ones and skin barely change."""
    y, cb, cr = _ycc(x)
    c = np.hypot(cb, cr)
    k = 1.0 + amount * np.clip(1.0 - c / 0.35, 0.0, 1.0) * (1.0 - SKIN_KEEP * skin)
    return _rgb(y, cb * k, cr * k)


def _lin_gains(x: np.ndarray, gains) -> np.ndarray:
    return (np.clip(x, 0, None) ** 2.4 * np.asarray(gains)) ** (1 / 2.4)


def _smooth(x: np.ndarray) -> np.ndarray:
    c = np.clip(x, 0, 1)
    return c * c * (3 - 2 * c)


def _shoulder(x: np.ndarray, knee: float = 0.85) -> np.ndarray:
    """Soft roll-off of the brightest values: identity below `knee`, reaching 1.0 asymptotically."""
    span = 1.0 - knee
    return np.where(x <= knee, x, knee + span * np.tanh((x - knee) / span))


# ---------------------------------------------------------------- looks
def _look(name: str, x: np.ndarray, skin: np.ndarray) -> np.ndarray:
    """A look at full strength: each is clearly recognisable at 100% (the strength mixes it with the plain picture)."""
    if name == "bright":
        x = np.clip(x, 0, 1) ** 0.86
        return _vibrance(x, 0.22, skin)
    if name == "warm":
        return _saturate(_lin_gains(x, (1.09, 1.0, 0.85)), 1.05, skin)
    if name == "cool":
        return _saturate(_lin_gains(x, (0.91, 0.99, 1.12)), 0.97, skin)
    if name == "film":
        x = x + 0.3 * (_smooth(x) - x)
        x = 0.045 + (1.0 - 0.045) * _shoulder(np.clip(x, 0, None), 0.78)
        y, cb, cr = _ycc(x)
        cb = cb + 0.03 * (1 - y) ** 2 - 0.015 * y ** 2
        cr = cr - 0.01 * (1 - y) ** 2 + 0.02 * y ** 2
        return _saturate(_rgb(y, cb, cr), 0.85, skin)
    if name == "teal_orange":
        x = x + 0.25 * (_smooth(x) - x)
        y, cb, cr = _ycc(x)
        away = 1.0 - skin
        cb = cb + 0.07 * (1 - y) ** 2 * away - 0.04 * y ** 2
        cr = cr - 0.06 * (1 - y) ** 2 * away + 0.035 * y ** 2
        return _saturate(_rgb(y, cb, cr), 1.05, skin)
    if name == "moody":
        x = np.clip(x, 0, 1) ** 1.18
        x = x + 0.25 * (_smooth(x) - x)
        x = _shoulder(x, 0.78)
        y, cb, cr = _ycc(x)
        cb = cb + 0.035 * (1 - y) ** 2 * (1 - skin)
        return _saturate(_rgb(y, cb, cr), 0.72, skin)
    if name == "vintage":
        x = 0.08 + 0.84 * _shoulder(np.clip(x, 0, None), 0.78)
        x = _lin_gains(x, (1.06, 1.0, 0.85))
        return _saturate(x, 0.78, skin)
    if name == "mono":
        y = x @ W709
        y = y + 0.2 * (_smooth(y) - y)
        return np.repeat(y[..., None], 3, axis=-1)
    return x


@dataclass
class Grade:
    """Everything one shot's colour table is made from."""
    hdr: str | None = None
    max_cll: float = 0.0
    wb: tuple[float, float, float] = (1.0, 1.0, 1.0)
    black: float = 0.0
    gain: float = 1.0
    gamma: float = 1.0
    s_curve: float = 0.0
    vibrance: float = 0.0
    match_gamma: float = 1.0
    match_cb: float = 0.0
    match_cr: float = 0.0
    look: str = "natural"
    strength: float = 1.0
    notes: list[str] = field(default_factory=list)

    def corrects(self) -> bool:
        return (any(abs(g - 1.0) > 1e-4 for g in self.wb) or self.black > 1e-4 or abs(self.gain - 1) > 1e-4
                or abs(self.gamma - 1) > 1e-4 or self.s_curve > 1e-4 or self.vibrance > 1e-4
                or abs(self.match_gamma - 1) > 1e-4 or abs(self.match_cb) > 1e-5 or abs(self.match_cr) > 1e-5)

    def active(self) -> bool:
        """Whether this grade changes any colour at all (no table is made or applied otherwise)."""
        return bool(self.hdr) or self.corrects() or (self.look in LOOKS and self.look != "natural"
                                                      and self.strength > 1e-3)

    def key(self) -> str:
        data = {k: (round(v, 5) if isinstance(v, float) else [round(g, 5) for g in v] if isinstance(v, tuple) else v)
                for k, v in self.__dict__.items() if k != "notes"}
        data["v"] = VERSION
        data["n"] = LUT_SIZE
        return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()[:24]

    def to_json(self) -> dict:
        d = dict(self.__dict__)
        d["wb"] = list(self.wb)
        return d

    @classmethod
    def from_json(cls, d: dict) -> "Grade":
        d = dict(d or {})
        d["wb"] = tuple(d.get("wb") or (1.0, 1.0, 1.0))
        known = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        return cls(**known)

    def summary(self) -> dict:
        """What the render notes show."""
        return {"hdr": self.hdr, "corrected": self.corrects(), "look": self.look, "strength": round(self.strength, 2),
                "notes": list(self.notes)}


def _levels(v: np.ndarray, g: Grade, black: float | None = None) -> np.ndarray:
    v = np.clip((v - (g.black if black is None else black)) * g.gain, 0.0, None)
    if abs(g.gamma - 1) > 1e-6:
        v = v ** g.gamma
    if g.s_curve > 0:
        v = v + g.s_curve * (_smooth(v) - v)
    return v


def _tone(x: np.ndarray, g: Grade) -> np.ndarray:
    """Levels. A black offset (haze, a lifted black) comes off each channel alike, the inverse of how it got there:
    taken off brightness alone it would crush saturated colours whose brightness is low (a deep blue). Gain,
    mid-tones and contrast then change brightness only, so every colour keeps its saturation (the same curve on each
    channel would turn a contrast boost into a colour boost too). Near black, where a ratio is unstable, the
    channels are curved alike."""
    if g.black > 0:
        x = np.clip(x - g.black, 0.0, None)
    y = np.clip(x @ W709, 0.0, None)
    ratio = np.minimum(_levels(y, g, 0.0) / np.maximum(y, 1e-4), 4.0)
    near_black = np.clip(y / 0.05, 0.0, 1.0)[..., None]
    return near_black * (x * ratio[..., None]) + (1.0 - near_black) * _levels(x, g, 0.0)


def apply(x: np.ndarray, g: Grade) -> np.ndarray:
    """The grade as a function of colour: R'G'B' in (the file's own encoding) -> BT.709 R'G'B' out, 0-1."""
    x = np.asarray(x, dtype=np.float64)
    if g.hdr:
        x = to_sdr(x, g.hdr, g.max_cll)
    if any(abs(v - 1.0) > 1e-6 for v in g.wb):
        x = _lin_gains(x, g.wb)
    if g.black > 0 or abs(g.gain - 1) > 1e-6 or abs(g.gamma - 1) > 1e-6 or g.s_curve > 0:
        x = _tone(x, g)
    skin = None
    if g.vibrance > 0:
        skin = skin_mask(np.clip(x, 0, 1))
        x = _vibrance(x, g.vibrance, skin)
    if abs(g.match_gamma - 1) > 1e-6 or g.match_cb or g.match_cr:
        x = np.clip(x, 0, None) ** g.match_gamma
        y, cb, cr = _ycc(x)
        mid = np.clip(4.0 * y * (1.0 - y), 0, 1)  # blacks and whites stay neutral
        x = _rgb(y, cb + g.match_cb * mid, cr + g.match_cr * mid)
    if g.look in LOOKS and g.look != "natural" and g.strength > 0:
        base = _gamut_clip(x)
        skin = skin_mask(np.clip(base, 0, 1))
        styled = _look(g.look, base, skin)
        x = base + min(1.0, max(0.0, g.strength)) * (styled - base)
    return np.clip(_gamut_clip(x), 0.0, 1.0)


def cube_text(g: Grade, size: int = LUT_SIZE) -> str:
    """The grade as a .cube 3D LUT (red changes fastest, then green, then blue)."""
    s = np.linspace(0.0, 1.0, size)
    b, gg, r = np.meshgrid(s, s, s, indexing="ij")
    grid = np.stack([r, gg, b], axis=-1).reshape(-1, 3)
    out = apply(grid, g)
    rows = "\n".join(f"{a:.6f} {c:.6f} {d:.6f}" for a, c, d in out)
    return (f"# ClipForge grade v{VERSION}\nLUT_3D_SIZE {size}\nDOMAIN_MIN 0 0 0\nDOMAIN_MAX 1 1 1\n" + rows + "\n")


def lut_dir() -> Path:
    d = config.data_dir() / "cache" / "luts"
    d.mkdir(parents=True, exist_ok=True)
    return d


def lut_file(g: Grade) -> Path:
    """The grade's table on disk (made once, reused by every render that needs the same one)."""
    path = lut_dir() / f"grade-{g.key()}.cube"
    if not path.is_file():
        tmp = path.with_suffix(f".{os.getpid()}.{threading.get_ident()}.tmp")
        tmp.write_text(cube_text(g), encoding="ascii")
        os.replace(tmp, path)
    return path


# ---------------------------------------------------------------- measuring a recording
def _frame_cmd(path: str, t: float, colour: dict, w: int, h: int, *, crop: tuple[int, int] | None = None,
               gray: bool = False) -> list[str]:
    m, rng = input_matrix(colour), input_range(colour)  # the source's height decides untagged HD, not the sample's
    if crop:
        vf = f"crop={crop[0]}:{crop[1]}:(iw-{crop[0]})/2:(ih-{crop[1]})/2,format=gray"
        fmt = "gray"
    else:
        vf = f"scale={w}:{h}:flags=area:in_color_matrix={m}:in_range={rng},format=rgb48le"
        fmt = "rgb48le"
    if gray and not crop:
        fmt = "gray"
    return [ffmpeg_bin(), "-nostdin", "-hide_banner", "-loglevel", "error", "-ss", f"{max(0.0, t):.3f}", "-i", path,
            "-map", "0:v:0", "-frames:v", "1", "-an", "-sn", "-vf", vf, "-f", "rawvideo", "-pix_fmt", fmt, "pipe:1"]


def sample_times(ranges: list[tuple[float, float]], n: int = SAMPLES) -> list[float]:
    """`n` times spread evenly over the used ranges (seconds), away from their very edges."""
    ranges = [(a, b) for a, b in ranges if b - a > 0.05]
    total = sum(b - a for a, b in ranges)
    if total <= 0:
        return []
    out = []
    for k in range(n):
        want = (k + 0.5) / n * total
        for a, b in ranges:
            if want <= b - a:
                out.append(a + want)
                break
            want -= b - a
    return out


def _decode(cmd: list[str], size: int, cancelled: Callable[[], bool] | None) -> bytes | None:
    if cancelled is not None and cancelled():
        return None
    try:
        res = run_process(cmd, timeout=60.0, cancel=cancelled)
    except Exception:  # noqa: BLE001 - one unreadable frame is skipped
        return None
    if res.returncode != 0 or len(res.stdout or b"") < size:
        return None
    return res.stdout[:size]


def sample(path: str, times: list[float], colour: dict, cancelled: Callable[[], bool] | None = None
           ) -> tuple[list[np.ndarray], list[np.ndarray]]:
    """(small frames as SDR BT.709 R'G'B' floats, full-resolution grey centre crops as 8-bit luma)."""
    w0, h0 = int(colour.get("width") or 0), int(colour.get("height") or 0)
    if not w0 or not h0:
        return [], []
    # the file's stored size; FFmpeg rotates phone video upright while decoding, so the frame may be the other way
    w = SAMPLE_WIDTH
    h = max(2, int(round(SAMPLE_WIDTH * h0 / w0 / 2)) * 2)
    frames: list[np.ndarray] = []
    crops: list[np.ndarray] = []
    cw, ch = min(NOISE_CROP[0], w0 // 2 * 2), min(NOISE_CROP[1], h0 // 2 * 2)
    cw, ch = min(cw, ch * 4), min(ch, cw * 4)
    noisy = times[1::max(1, len(times) // NOISE_SAMPLES)][:NOISE_SAMPLES]
    jobs = [(t, False) for t in times] + [(t, True) for t in noisy]

    def one(job):
        t, noise = job
        if noise:
            return job, _decode(_frame_cmd(path, t, colour, w, h, crop=(cw, ch)), cw * ch, cancelled)
        got = _decode(_frame_cmd(path, t, colour, w, h), w * h * 6, cancelled)
        if got is None:  # a rotated phone video: the frame comes out the other way round
            got = _decode(_frame_cmd(path, t, colour, h, w), w * h * 6, cancelled)
            return (job, got, (w, h)) if got is not None else (job, None)
        return job, got, (h, w)

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(one, jobs))
    kind = hdr_kind(colour)
    for item in results:
        (t, noise), data = item[0], item[1]
        if data is None:
            continue
        if noise:
            crops.append(np.frombuffer(data, np.uint8).reshape(ch, cw).astype(np.float64))
            continue
        hh, ww = item[2]
        px = np.frombuffer(data, "<u2").reshape(hh, ww, 3).astype(np.float64) / 65535.0
        frames.append(to_sdr(px, kind, float(colour.get("max_cll") or 0)) if kind else px)
    return frames, crops


def noise_sigma(gray: np.ndarray) -> float:
    """Immerkaer's fast noise estimate (8-bit code values), on the flattest 10% of 64-pixel tiles so texture does not
    count as noise."""
    if gray.shape[0] < 8 or gray.shape[1] < 8:
        return 0.0
    k = (gray[:-2, :-2] - 2 * gray[:-2, 1:-1] + gray[:-2, 2:]
         - 2 * gray[1:-1, :-2] + 4 * gray[1:-1, 1:-1] - 2 * gray[1:-1, 2:]
         + gray[2:, :-2] - 2 * gray[2:, 1:-1] + gray[2:, 2:])
    a = np.abs(k)
    tile = 64
    th, tw = a.shape[0] // tile, a.shape[1] // tile
    if th == 0 or tw == 0:
        return float(math.sqrt(math.pi / 2) * a.mean() / 6)
    blocks = a[:th * tile, :tw * tile].reshape(th, tile, tw, tile).mean(axis=(1, 3)).ravel()
    flat = np.sort(blocks)[:max(1, len(blocks) // 10)]
    return float(math.sqrt(math.pi / 2) * flat.mean() / 6)


def measure(frames: list[np.ndarray], crops: list[np.ndarray] | None = None) -> dict | None:
    """Statistics of a recording (or clip) from its sampled frames; None when nothing could be read."""
    if not frames:
        return None
    px = np.concatenate([f.reshape(-1, 3) for f in frames])
    lin = px ** 2.4
    y_lin = lin @ W709
    y, cb, cr = _ycc(px)
    skin = skin_mask(px) > 0.5
    ok = (lin.max(axis=1) < 0.95) & (y_lin > 0.02)
    skin_share = float(skin.mean())
    if skin_share > 0.30:
        ok &= ~skin
    usable = float(ok.mean())
    st = {"pixels": int(len(px)), "usable": usable, "skin": skin_share,
          "p005": float(np.percentile(y, 0.5)), "p05": float(np.percentile(y, 5)),
          "p50": float(np.percentile(y, 50)), "p95": float(np.percentile(y, 95)),
          "p995": float(np.percentile(y, 99.5)), "chroma": float(np.hypot(cb, cr).mean()),
          "cb": float(cb.mean()), "cr": float(cr.mean())}
    if ok.sum() >= 64:
        sel = lin[ok]
        sog = np.mean(sel ** 6, axis=0) ** (1 / 6)
        wp = np.percentile(sel, 99, axis=0)
        # the light's colour from the greyest pixels: grey things (clouds, walls, shirts, roads) show the cast, while
        # a blue sky or green grass is simply coloured and does not count
        mean = np.maximum(sel.mean(axis=1, keepdims=True), 1e-6)
        dev = np.abs(sel / mean - 1.0).max(axis=1)
        k = max(64, int(len(sel) * GREY_SHARE))
        idx = np.argpartition(dev, min(k, len(sel)) - 1)[:k]
        grey = sel[idx].mean(axis=0)
        st.update({"sog": [float(v) for v in sog], "wp": [float(v) for v in wp], "grey": [float(v) for v in grey],
                   "wb_angle": _angle(sog, wp), "cast": _angle(grey, np.ones(3)), "cast_agree": _angle(grey, wp)})
    if crops:
        st["noise"] = float(np.median([noise_sigma(c) for c in crops]))
    # a fixed, evenly spread sample of the pixels, kept with the statistics so recordings can be matched to each
    # other later (after their own correction) without decoding them again
    step = max(1, len(px) // MATCH_PIXELS)
    st["px"] = np.round(px[::step][:MATCH_PIXELS], 4).tolist()
    return st


def _angle(a, b) -> float:
    a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    cos = float(np.dot(a, b) / max(1e-12, np.linalg.norm(a) * np.linalg.norm(b)))
    return math.degrees(math.acos(max(-1.0, min(1.0, cos))))


def correction(st: dict | None, *, screen: bool = False) -> Grade:
    """The automatic correction for statistics `st` (see the module docstring for every limit). `screen`: the
    picture may be a game or a screen recording, whose colours are deliberate: white balance is halved."""
    g = Grade()
    if not st:
        return g
    # white balance, from the greyest pixels' colour, only when the brightest pixels agree on it
    cast, agree = st.get("cast"), st.get("cast_agree")
    if cast is not None and st.get("usable", 0) >= WB_MIN_SHARE and cast >= WB_MIN_CAST:
        strength = 0.0
        if cast > WB_DELIBERATE or agree is None or agree > WB_AGREE[1]:
            g.notes.append("White balance left alone: the picture's colours look deliberate")
        else:
            strength = (0.7 if agree < WB_AGREE[0] else 0.35) * (0.6 if cast > WB_STRONG else 1.0)
        if screen:
            strength *= 0.5
        e = np.maximum(np.asarray(st["grey"], dtype=float), 1e-6)
        gains = e.mean() / e
        gains = gains / float(np.dot(W709, gains))
        gains = np.clip(1.0 + strength * (gains - 1.0), *WB_CLAMP)
        if strength and float(np.max(np.abs(gains - 1.0))) >= 0.015:
            g.wb = tuple(float(v) for v in gains)
            warm = gains[0] > gains[2]
            g.notes.append(f"White balance: a {'blue' if warm else 'warm'} cast reduced "
                           f"({int(round(strength * 100))}% of the measured cast)")
    # levels, only when clearly off: lifted (foggy) blacks, dim whites, very dark or very bright mid-tones
    lo, mid, hi = st["p005"], st["p50"], st["p995"]
    if lo > BLACK_FROM:
        g.black = min(BLACK_MAX, (lo - BLACK_TO) * 0.5)
        g.notes.append("Blacks deepened (they were washed out)")
    top = hi - g.black
    if hi < WHITE_FROM and top > 0.2:
        g.gain = min(WHITE_GAIN_MAX, WHITE_TO / top)
        g.notes.append("Brightest parts lifted toward white")
    elif g.black > 0 and top > 0:
        g.gain = min(WHITE_GAIN_MAX, max(1.0, hi / top))  # the whites stay where they were
    new_mid = max(1e-4, (mid - g.black) * g.gain)
    if new_mid < MID_RANGE[0] or new_mid > MID_RANGE[1]:
        target = MID_TARGET[0] if new_mid < MID_RANGE[0] else MID_TARGET[1]
        target = new_mid + (target - new_mid) * 0.5  # half way: a dark or bright scene may be meant that way
        gamma = math.log(target) / math.log(min(0.999, max(1e-4, new_mid)))
        g.gamma = float(min(GAMMA_RANGE[1], max(GAMMA_RANGE[0], gamma)))
        g.notes.append("Mid-tones " + ("brightened" if g.gamma < 1 else "darkened"))
    # at most half a stop of exposure change at the mid-tones
    after = max(1e-4, min(1.0, new_mid) ** g.gamma)
    stops = math.log2(max(1e-6, after ** 2.4) / max(1e-6, mid ** 2.4))
    if abs(stops) > MAX_STOPS:
        want = (mid ** 2.4 * 2 ** math.copysign(MAX_STOPS, stops)) ** (1 / 2.4)
        g.gamma = float(min(GAMMA_RANGE[1], max(GAMMA_RANGE[0], math.log(want) / math.log(min(0.999, new_mid)))))
    if st["p95"] - st["p05"] < FLAT_SPREAD:
        g.s_curve = 0.15
        g.notes.append("A little contrast added (the picture was flat)")
    if st["chroma"] < FLAT_CHROMA:
        g.vibrance = float(min(VIBRANCE_MAX, VIBRANCE_MAX * (FLAT_CHROMA - st["chroma"]) / FLAT_CHROMA * 2))
        if g.vibrance >= 0.02:
            g.notes.append("Colour brought back (it was washed out); skin tones kept natural")
        else:
            g.vibrance = 0.0
    return g


def corrected_stats(st: dict, g: Grade) -> dict | None:
    """Average brightness and mid-tone colour cast of a recording's sampled pixels (already SDR) after its own
    correction `g` (for matching recordings to each other); None without a pixel sample."""
    if not st or not st.get("px"):
        return None
    px = np.asarray(st["px"], dtype=np.float64).reshape(-1, 3)
    base = Grade(**{**g.__dict__, "hdr": None, "look": "natural", "notes": [], "match_gamma": 1.0,
                    "match_cb": 0.0, "match_cr": 0.0})
    y, cb, cr = _ycc(apply(px, base))
    weights = np.clip(4 * y * (1 - y), 0, 1) + 1e-6
    return {"p50": float(np.percentile(y, 50)), "cb": float(np.average(cb, weights=weights)),
            "cr": float(np.average(cr, weights=weights))}


def match(g: Grade, mine: dict, ref: dict) -> Grade:
    """Nudge `g` so this recording's average cast and brightness move toward the reference recording's."""
    dcb = max(-MATCH_CHROMA_MAX, min(MATCH_CHROMA_MAX, (ref["cb"] - mine["cb"]) * MATCH_STRENGTH))
    dcr = max(-MATCH_CHROMA_MAX, min(MATCH_CHROMA_MAX, (ref["cr"] - mine["cr"]) * MATCH_STRENGTH))
    gamma = 1.0
    if 0.02 < mine["p50"] < 0.98 and 0.02 < ref["p50"] < 0.98:
        want = mine["p50"] + (ref["p50"] - mine["p50"]) * MATCH_STRENGTH
        gamma = max(MATCH_GAMMA[0], min(MATCH_GAMMA[1], math.log(want) / math.log(mine["p50"])))
    if abs(dcb) < 0.002 and abs(dcr) < 0.002 and abs(gamma - 1) < 0.01:
        return g
    g.match_cb, g.match_cr, g.match_gamma = float(dcb), float(dcr), float(gamma)
    g.notes.append("Matched to the main recording's colour and brightness")
    return g


def denoise_filter(sigma: float | None) -> str:
    """The denoise step for a measured noise level (8-bit codes), or '' when the picture is clean enough."""
    if sigma is None or sigma < NOISE_NONE:
        return ""
    s = min(NOISE_MAX, sigma)
    if s < NOISE_HEAVY:
        return "atadenoise=0a=0.02:0b=0.04:1a=0.02:1b=0.04:2a=0.02:2b=0.04:s=7"
    return f"fftdnoiz=sigma={s:.1f}:amount=0.9"


def denoise_for(stats: dict | None, opts: dict, scale: float = 1.0) -> str:
    """The denoise step for footage measured as `stats`, unless "Clean up noise" is off. `scale`: the size the
    picture is cleaned at, as a share of the size the noise was measured at (full size); grain mostly averages away
    when a picture is made smaller (a 360p preview, a 4K recording), so it is cleaned less."""
    if opts.get("clean_picture") is False or not stats or stats.get("noise") is None:
        return ""
    return denoise_filter(float(stats["noise"]) * max(0.0, min(1.0, scale)))


# ---------------------------------------------------------------- choices and the filter text
def choices(opts: dict) -> tuple[bool, str, float]:
    """(automatic correction on, look, strength 0-1) from render options or a plan's "color"."""
    auto = opts.get("auto_color")
    auto = True if auto is None else bool(auto)
    look = opts.get("look") if opts.get("look") in LOOKS else "natural"
    try:
        strength = float(opts.get("look_strength", 100) if opts.get("look_strength") is not None else 100) / 100.0
    except (TypeError, ValueError):
        strength = 1.0
    return auto, look, max(0.0, min(1.0, strength))


def for_footage(path: str, ranges: list[tuple[float, float]], opts: dict, *, cache: Path | None = None,
                screen: bool | None = None, cancelled: Callable[[], bool] | None = None
                ) -> tuple[Grade, dict | None]:
    """The grade of one piece of footage (`ranges` in seconds of the file) for options `opts`, and the measured
    statistics. The measurement is cached in `cache` (a JSON file) when given. `screen`: whether the picture may be
    a game or a screen recording; None decides from the picture (almost no skin tones)."""
    colour = source_colour(path)
    auto, look, strength = choices(opts)
    stats = None
    if auto or opts.get("clean_picture") is not False:
        times = sample_times(ranges)
        key = hashlib.sha256(json.dumps([VERSION, str(path), [round(t, 3) for t in times], colour],
                                        sort_keys=True).encode()).hexdigest()[:24]
        saved = None
        if cache is not None and cache.is_file():
            try:
                saved = json.loads(cache.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                saved = None
        if saved and saved.get("key") == key:
            stats = saved.get("stats")
        else:
            frames, crops = sample(path, times, colour, cancelled)
            if cancelled is not None and cancelled():
                raise Cancelled()  # what was read so far is not this footage's measurement
            stats = measure(frames, crops)
            if cache is not None and stats is not None:
                try:
                    cache.parent.mkdir(parents=True, exist_ok=True)
                    cache.write_text(json.dumps({"key": key, "stats": stats}), encoding="utf-8")
                except OSError:
                    pass
    if screen is None:
        screen = bool(stats) and stats.get("skin", 0) < 0.01
    g = correction(stats, screen=screen) if auto else Grade()
    g.hdr = hdr_kind(colour)
    g.max_cll = float(colour.get("max_cll") or 0.0)
    if g.hdr:
        g.notes.insert(0, f"HDR phone video ({'HLG' if g.hdr == 'hlg' else 'PQ'}) converted to normal video")
    g.look, g.strength = look, strength
    return g, stats


def rgb_filters(colour: dict, g: Grade, denoise: str, cwd: Path, height: int = 0) -> str:
    """Filters that turn a decoded (already scaled) picture into BT.709 RGB with the grade applied: the denoise step
    first (on the original YCbCr), then a correct YCbCr->RGB conversion, then the colour table in 16 bits."""
    parts = [denoise] if denoise else []
    parts.append(f"scale={to_rgb_chain(colour, height)}")
    lut = lut_filter(g, cwd)
    if lut:
        parts += ["format=gbrp16le", lut]
    return ",".join(parts)


def yuv_filters(colour: dict, g: Grade, denoise: str, cwd: Path, height: int = 0) -> str:
    """The same for a picture that stays YCbCr (the full-video engine): back to BT.709 limited range 4:2:0 and
    tagged as such, so an HDR source never leaves HDR tags on normal video."""
    lut = lut_filter(g, cwd)
    read = to_rgb_chain(colour, height)  # the matrix; the range is each frame's own (see to_rgb_chain)
    parts = [denoise] if denoise else []
    if lut:
        parts += [f"scale={read},format=gbrp16le", lut, "scale=out_color_matrix=bt709:out_range=tv"]
    else:
        parts.append(f"scale={read}:out_color_matrix=bt709:out_range=tv")
    parts += ["format=yuv420p", "setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709:range=tv"]
    return ",".join(parts)


def to_rgb_chain(colour: dict, height: int = 0) -> str:
    """Filter options that read a file's YCbCr correctly (for the `scale` filter that turns it into RGB). The matrix
    is given (FFmpeg reads untagged HD as BT.601); the range is left to each frame's own tag, because a scale or an
    overlay earlier in the chain may already have turned full-range video into limited range and re-tagged it, and
    a preview proxy is limited range whatever its original was."""
    return f"in_color_matrix={input_matrix(colour, height)}"


def lut_filter(g: Grade, cwd: Path) -> str:
    """``lut3d`` for grade `g`, or '' when it changes nothing. Paths are relative to the FFmpeg run's folder."""
    if not g.active():
        return ""
    from .ffmpeg_utils import filter_path

    return f"lut3d=file={filter_path(lut_file(g), cwd)}:interp=tetrahedral"
