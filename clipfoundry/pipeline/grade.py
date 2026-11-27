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
   brightness, not colourfulness, except where a channel would go past full scale: the soft gamut clip then pulls
   that colour toward grey, so the whites are lifted only as far as the brightest channel allows. A well-exposed
   picture is left as it is, and so are flat graphics (a cartoon, slides: a few flat colours cover most of it).
4. Vibrance on flat footage only (low-saturation colours gain most), at 30% inside skin tones.
5. Matching (full videos): a recording's average colour cast and brightness are nudged toward the main recording's,
   mid-tones only, capped.
6. A look (warm, film, teal and orange...), clearly recognisable at 100% and mixed in by its strength, with skin
   tones protected.
7. A soft gamut clip: colours outside the displayable range move toward grey instead of clipping channel by channel.

Before a table is used, the grade is tried on a sample of the recording's own pixels (check_grade): when it would
lose detail in the brightest or darkest parts (a flat area made all one level loses none), wash out strong colours
or band a smooth gradient, the step that causes it is eased (guard) and the render notes say so. A chosen look is
eased only for losing detail or banding, never for being a look, and never below 30% of the owner's choice.

The analysis is per recording or per clip, never per frame, so nothing flickers or "breathes".

Noisy footage (low light, webcams) is measured too (Immerkaer's noise estimate on the flattest parts of a few
full-resolution frames) and cleaned with ``atadenoise`` (moderate) or ``fftdnoiz`` (heavy), both LGPL and built in.
"""
from __future__ import annotations

import base64
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

VERSION = 2                  # 2: max-channel white lift, flat graphics, the predicted check's pixel sample
LUT_SIZE = 33
SAMPLE_WIDTH = 256           # analysis frames are this wide
SAMPLES = 10                 # frames looked at per recording or clip
CHECK_FRAMES = 4             # frames read again, unaveraged, for the predicted check
CHECK_WIDTH = 320            # ... at this width, every pixel a real pixel (nearest-neighbour scaling)
CHECK_PIXELS = 16384         # ... of which this many are kept with the statistics (8-bit, about 64 KB as text)
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

GRAPHIC_TOP8 = 0.85         # the 8 commonest colours (32 levels a channel) cover this share: flat graphics...
GRAPHIC_SPAN = 12.0          # ...or 95% of the picture lies within this many luma codes (a flat colour field)

# The predicted check (check_grade): (warn, ease) limits on the grade applied to the recording's own pixels
CHECK_CLIP = (0.002, 0.005)  # share of pixels newly at full scale whose detail is lost (flat areas left out)
CHECK_CRUSH = (0.005, 0.01)  # share newly at black (Y <= 17 of 16-235, was over 20), the same way
CHECK_SAT = (0.01, 0.03)     # share of colourful pixels losing over 20% of their colourfulness (correction only)
CHECK_SLOPE = (1.5, 1.8)     # steepest part of the brightness curve over the levels the picture uses (banding)
CHECK_TRIES = 4
MERGE_CODES = 3              # 8-bit codes: a flat area's own noise, not detail

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
               gray: bool = False, neighbor: bool = False) -> list[str]:
    m, rng = input_matrix(colour), input_range(colour)  # the source's height decides untagged HD, not the sample's
    if crop:
        vf = f"crop={crop[0]}:{crop[1]}:(iw-{crop[0]})/2:(ih-{crop[1]})/2,format=gray"
        fmt = "gray"
    else:
        flags = "neighbor" if neighbor else "area"
        vf = f"scale={w}:{h}:flags={flags}:in_color_matrix={m}:in_range={rng},format=rgb48le"
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


def check_sample(path: str, times: list[float], colour: dict, cancelled: Callable[[], bool] | None = None
                 ) -> np.ndarray | None:
    """Pixels of a few of the sampled frames as SDR BT.709 R'G'B' floats (N x 3), every one a real pixel of the
    picture (nearest-neighbour scaling: a small highlight or a thin bright line is not averaged away), for the
    predicted check. None when nothing could be read."""
    w0, h0 = int(colour.get("width") or 0), int(colour.get("height") or 0)
    if not w0 or not h0 or not times:
        return None
    w = CHECK_WIDTH
    h = max(2, int(round(CHECK_WIDTH * h0 / w0 / 2)) * 2)
    picked = times[::max(1, len(times) // CHECK_FRAMES)][:CHECK_FRAMES]

    def one(t):
        got = _decode(_frame_cmd(path, t, colour, w, h, neighbor=True), w * h * 6, cancelled)
        if got is None:  # a rotated phone video
            got = _decode(_frame_cmd(path, t, colour, h, w, neighbor=True), w * h * 6, cancelled)
        return got

    with ThreadPoolExecutor(max_workers=4) as pool:
        got = [g for g in pool.map(one, picked) if g is not None]
    if not got:
        return None
    px = np.concatenate([np.frombuffer(g, "<u2").reshape(-1, 3) for g in got]).astype(np.float64) / 65535.0
    kind = hdr_kind(colour)
    return to_sdr(px, kind, float(colour.get("max_cll") or 0)) if kind else px


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


def _span(y: np.ndarray, share: float) -> float:
    """The narrowest range of values that holds `share` of `y`."""
    v = np.sort(y)
    k = max(1, int(math.ceil(share * len(v))) - 1)
    if k >= len(v):
        return float(v[-1] - v[0])
    return float(np.min(v[k:] - v[:len(v) - k]))


def measure(frames: list[np.ndarray], crops: list[np.ndarray] | None = None,
            check: np.ndarray | None = None) -> dict | None:
    """Statistics of a recording (or clip) from its sampled frames (and the unaveraged pixels of check_sample for
    the predicted check); None when nothing could be read."""
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
          "cb": float(cb.mean()), "cr": float(cr.mean()),
          # the brightest channel's 99.5th percentile: how far the whites can be lifted before a colour clips
          "p995_max": float(np.percentile(px.max(axis=1), 99.5))}
    # flat graphics (a cartoon, slides, a title card): a few flat colours cover most of the picture, or nearly all
    # of it is one brightness. Camera footage has noise and light falling off, so its colours spread.
    q = np.clip((np.clip(px, 0.0, 1.0) * 32).astype(np.int64), 0, 31)
    counts = np.bincount(q[:, 0] * 1024 + q[:, 1] * 32 + q[:, 2], minlength=32768)
    st["top8"] = float(np.sort(counts)[-8:].sum() / max(1, len(px)))
    st["span95"] = _span(y, 0.95) * 219
    st["graphic"] = bool(st["top8"] >= GRAPHIC_TOP8 or st["span95"] <= GRAPHIC_SPAN)
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
    if check is not None and len(check):
        # an evenly spread sample of real pixels (8-bit), for the predicted check
        step = max(1, len(check) // CHECK_PIXELS)
        kept = np.clip(np.round(check[::step][:CHECK_PIXELS] * 255), 0, 255).astype(np.uint8)
        st["check_px"] = base64.b64encode(kept.tobytes()).decode("ascii")
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
    if st.get("graphic"):
        # a cartoon, slides or a title card: its flat colours are drawn that way (the levels' rules would read a
        # dark background as underexposure and lift every colour drawn on it)
        g.notes.append("Flat colours (a cartoon or graphics): left as drawn")
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
    # dim whites are judged by the brightest channel, not brightness: a saturated orange or red is dim in
    # brightness but already at full scale in one channel, and lifting it would clip it (the soft gamut clip would
    # then wash it toward grey)
    hi_max = float(st.get("p995_max", hi))
    if lo > BLACK_FROM:
        g.black = min(BLACK_MAX, (lo - BLACK_TO) * 0.5)
        g.notes.append("Blacks deepened (they were washed out)")
    top = hi - g.black
    top_max = hi_max - g.black
    if hi_max < WHITE_FROM and top_max > 0.2:
        g.gain = min(WHITE_GAIN_MAX, WHITE_TO / top_max)
        g.notes.append("Brightest parts lifted toward white")
    elif g.black > 0 and top > 0:
        g.gain = min(WHITE_GAIN_MAX, max(1.0, hi / top))  # the whites stay where they were
        if top_max > 0:
            g.gain = min(g.gain, max(1.0, hi_max / top_max))  # ...and the brightest channel too
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
    # the half-stop cap may have undone or turned the mid-tone change: the note says what is left of it
    g.notes = [n for n in g.notes if not n.startswith("Mid-tones ")]
    if abs(g.gamma - 1) < 0.01:
        g.gamma = 1.0
    elif new_mid < MID_RANGE[0] or new_mid > MID_RANGE[1]:  # the net change at the mid-tones, gain included
        g.notes.append("Mid-tones " + ("brightened" if min(1.0, new_mid) ** g.gamma > mid else "darkened"))
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


# ---------------------------------------------------------------- the predicted check
_REASONS = {"clip": "lost detail in the brightest parts", "crush": "lost detail in the darkest parts",
            "sat": "washed out strong colours", "slope": "shown bands in smooth gradients"}
_STEP_NOTES = {"wb": "White balance:", "black": "Blacks deepened", "gain": "Brightest parts lifted",
               "gamma": "Mid-tones ", "s_curve": "A little contrast", "vibrance": "Colour brought back",
               "match": "Matched to the main"}


def check_pixels(st: dict | None) -> np.ndarray | None:
    """The unaveraged pixel sample kept with a recording's statistics (SDR R'G'B' 0-1, N x 3), or None."""
    raw = (st or {}).get("check_px")
    if not raw:
        return None
    try:
        data = np.frombuffer(base64.b64decode(raw), np.uint8)
    except (ValueError, TypeError):
        return None
    if not len(data) or len(data) % 3:
        return None
    return data.reshape(-1, 3).astype(np.float64) / 255.0


def _plain(g: Grade, **change) -> Grade:
    """`g` for pixels already in SDR (the check's sample is), without notes, with `change` applied."""
    return Grade(**{**g.__dict__, "hdr": None, "max_cll": 0.0, "notes": [], **change})


def _ramp_slope(g: Grade, ref: Grade | None, lo: float, hi: float) -> float:
    """The steepest part of `g`'s brightness curve on greys between `lo` and `hi` (of `ref`'s output when given):
    over 1.8, neighbouring 8-bit levels land two or more apart and a smooth gradient shows bands."""
    v = np.linspace(0.0, 1.0, 512)
    grey = np.repeat(v[:, None], 3, axis=1)
    base = apply(grey, ref) @ W709 if ref is not None else v
    out = apply(grey, g) @ W709
    use = (base >= lo) & (base <= hi)
    if use.sum() < 3:
        return 0.0
    db, do = np.diff(base), np.diff(out)
    ok = use[1:] & use[:-1] & (db > 1e-6)
    return float(np.max(do[ok] / db[ok])) if ok.any() else 0.0


def _merged(hit: np.ndarray, level: np.ndarray) -> float:
    """The share of pixels whose detail is lost where `hit` pixels all end up at one level (full scale, or
    black). A flat area (one colour, give or take MERGE_CODES of noise: a cartoon's white sky, a black
    background) loses nothing when it is made all one level; the pixels around its commonest level are left out."""
    if not hit.any():
        return 0.0
    v = level[hit]
    mode = float(np.argmax(np.bincount(np.clip(np.round(v), 0, 255).astype(int))))
    return float((np.abs(v - mode) > MERGE_CODES).sum() / len(hit))


def check_grade(px: np.ndarray, g: Grade, *, part: str = "correction") -> dict:
    """What grade `g` would do to the recording's own pixels `px` (SDR): the share of pixels newly clipped at full
    scale (`clip`) or crushed to black (`crush`), of colourful pixels washed out by more than a fifth (`sat`,
    correction only: a look may mean to), and the steepest part of the brightness curve (`slope`). `part`:
    "correction" judges the correction against the picture as it is; "look" judges the full grade against the
    corrected picture, so a look is judged only on what it adds."""
    corr = _plain(g, look="natural", strength=1.0)
    if part == "look":
        ref_g, out_g = corr, _plain(g)
    else:
        ref_g, out_g = None, corr
    ref = apply(px, ref_g) if ref_g is not None else px
    out = apply(px, out_g)
    y_ref, y_out = 16 + 219 * (ref @ W709), 16 + 219 * (out @ W709)
    top = ref.max(axis=1)
    found = {"clip": _merged((out.max(axis=1) >= 0.998) & (top < 0.97), 255 * top),
             "crush": _merged((y_out <= 17) & (y_ref > 20), y_ref), "sat": 0.0}
    if part == "correction":
        # against the white-balanced picture: taking a cast away is meant to change colours
        wb_only = apply(px, Grade(wb=g.wb)) if any(abs(v - 1) > 1e-6 for v in g.wb) else px
        # colourfulness as a share of the brightest channel, so making a colour darker or brighter is no change
        top0, top1 = wb_only.max(axis=1), out.max(axis=1)
        s0 = (top0 - wb_only.min(axis=1)) / np.maximum(top0, 1e-6)
        s1 = (top1 - out.min(axis=1)) / np.maximum(top1, 1e-6)
        colourful = (s0 > 0.25) & (top0 > 0.1)
        if colourful.sum() >= 200:
            found["sat"] = float((colourful & (s1 < 0.8 * s0)).sum() / colourful.sum())
    y = px @ W709
    lo, hi = max(0.06, float(np.percentile(y, 1))), float(np.percentile(y, 99))
    if part == "look":
        found["slope"] = _ramp_slope(_plain(g), corr, lo, hi)
        found["slope"] = found["slope"] if found["slope"] > _ramp_slope(corr, None, lo, hi) + 0.1 else 0.0
    else:
        found["slope"] = _ramp_slope(corr, None, lo, hi)
    return found


def _worst(found: dict, part: str) -> str | None:
    limits = {"clip": CHECK_CLIP, "crush": CHECK_CRUSH, "slope": CHECK_SLOPE}
    if part == "correction":
        limits["sat"] = CHECK_SAT
    over = [k for k in ("clip", "crush", "sat", "slope") if k in limits and found.get(k, 0) > limits[k][1]]
    return over[0] if over else None


def _ease(g: Grade, why: str) -> None:
    """One step back on the correction setting that causes `why`, else every setting half way to none."""
    if why == "clip" and g.gain > 1.001:
        g.gain = 1.0 if g.gain < 1.05 else 1 + (g.gain - 1) / 2
    elif why in ("clip", "crush", "slope") and g.s_curve > 0:
        g.s_curve = 0.0
    elif why == "crush" and g.black > 0:
        g.black = 0.0 if g.black < 0.01 else g.black / 2
    elif why == "sat" and g.vibrance > 0:
        g.vibrance = 0.0
    elif why == "sat" and g.gain > 1.001:
        g.gain = 1.0 if g.gain < 1.05 else 1 + (g.gain - 1) / 2
    elif why in ("clip", "slope") and abs(g.gamma - 1) > 0.01:
        g.gamma = 1.0 if abs(g.gamma - 1) < 0.05 else 1 + (g.gamma - 1) / 2
    else:
        g.wb = tuple(1 + (v - 1) / 2 for v in g.wb)
        g.black, g.gain, g.gamma = g.black / 2, 1 + (g.gain - 1) / 2, 1 + (g.gamma - 1) / 2
        g.s_curve, g.vibrance = g.s_curve / 2, g.vibrance / 2
        g.match_gamma, g.match_cb, g.match_cr = 1 + (g.match_gamma - 1) / 2, g.match_cb / 2, g.match_cr / 2


def _drop_notes(g: Grade) -> None:
    """Notes of correction steps that are no longer there."""
    gone = {"wb": all(abs(v - 1) < 1e-4 for v in g.wb), "black": g.black < 1e-4, "gain": abs(g.gain - 1) < 1e-4,
            "gamma": abs(g.gamma - 1) < 1e-4, "s_curve": g.s_curve < 1e-4, "vibrance": g.vibrance < 1e-4,
            "match": abs(g.match_gamma - 1) < 1e-4 and abs(g.match_cb) < 1e-5 and abs(g.match_cr) < 1e-5}
    g.notes = [n for n in g.notes if not any(gone[k] and n.startswith(head) for k, head in _STEP_NOTES.items())]


def guard(g: Grade, st: dict | None) -> Grade:
    """Grade `g` tried on the recording's own pixels first (check_grade): a correction that would clip, crush,
    wash out strong colours or band a gradient is eased one step at a time on the setting that causes it (at most
    CHECK_TRIES steps, then left out); a look that would clip, crush or band is eased to 60%, then 30% of its
    strength (never further: it is the owner's choice). The notes say what was eased and why. Without the pixel
    sample (statistics measured before it existed) the grade is returned unchanged."""
    px = check_pixels(st)
    if px is None or not g.active():
        return g
    g = Grade(**{**g.__dict__, "notes": list(g.notes)})
    if g.corrects():
        why = _worst(check_grade(px, g), "correction")
        first = why
        for _ in range(CHECK_TRIES):
            if why is None:
                break
            _ease(g, why)
            why = _worst(check_grade(px, g), "correction")
        if why is not None:  # still harmful after every step: no correction at all
            g.wb, g.black, g.gain, g.gamma, g.s_curve, g.vibrance = (1.0, 1.0, 1.0), 0.0, 1.0, 1.0, 0.0, 0.0
            g.match_gamma, g.match_cb, g.match_cr = 1.0, 0.0, 0.0
        if first is not None:
            _drop_notes(g)
            g.notes.append(("Colour correction eased" if g.corrects() else "Colour correction left out")
                           + f": it would have {_REASONS[first]}")
    if g.look in LOOKS and g.look != "natural" and g.strength > 1e-3:
        chosen = g.strength
        why = _worst(check_grade(px, g, part="look"), "look")
        first = why
        for share in (0.6, 0.3):
            if why is None:
                break
            g.strength = chosen * share
            why = _worst(check_grade(px, g, part="look"), "look")
        if first is not None:
            g.notes.append(f"The {LOOKS[g.look]} look eased to {int(round(g.strength * 100))}%: at "
                           f"{int(round(chosen * 100))}% it would have {_REASONS[first]}")
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
                screen: bool | None = None, cancelled: Callable[[], bool] | None = None, guarded: bool = True
                ) -> tuple[Grade, dict | None]:
    """The grade of one piece of footage (`ranges` in seconds of the file) for options `opts`, and the measured
    statistics. The measurement is cached in `cache` (a JSON file) when given. `screen`: whether the picture may be
    a game or a screen recording; None decides from the picture (almost no skin tones). `guarded`: the grade is
    tried on the footage's own pixels first (guard); the full-video engine does that itself after matching."""
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
            check = check_sample(path, times, colour, cancelled) if frames else None
            if cancelled is not None and cancelled():
                raise Cancelled()  # what was read so far is not this footage's measurement
            stats = measure(frames, crops, check)
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
    if guarded:
        g = guard(g, stats)
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
