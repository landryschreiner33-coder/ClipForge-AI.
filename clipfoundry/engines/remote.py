"""A ComfyUI on a rented cloud computer: for a computer that is too slow to make pictures and clips itself
(docs/clipforge/CLOUD_GPU.md).

Settings → Pictures, video, voice → "A cloud computer": the person rents a computer with a fast graphics card (a RunPod
"pod" with RunPod's ComfyUI template), pastes its web address (https://<pod id>-8188.proxy.runpod.net) and, only if
their server asks for one, a key. ClipForge then sends each picture or clip there the way it does to a ComfyUI on this
computer (comfy.py): the words, the graph and a picture to animate go up; the finished file comes back into
<data>/engines/made with its note, like any other.

What differs from a ComfyUI on this computer:
* the address is https (the key and the words cross the internet); plain http only to this computer (a tunnel)
* check() says in plain words what is wrong: the pod is off, still starting, the address is not ComfyUI, the key...
* a cloud computer that stops answering for a moment is waited for (comfy.LOST_S); uploads and downloads are tried
  again; a request is never sent twice
* this computer's graphics card is not used, so a job does not wait for it; jobs to the cloud computer still go one at
  a time from this app (turn), as they do on this computer
* ClipForge cannot put model files on it: download_command() writes a command the person pastes into the pod's
  terminal, which downloads the pinned files (catalog.py) from Hugging Face straight onto the pod and checks each
  one's size and SHA-256 before ComfyUI can see it
"""
from __future__ import annotations

import contextlib
import re
import shlex
import threading
import time
from urllib.parse import urlsplit, urlunsplit

import httpx

from . import Cancel, EngineError, Progress, catalog
from .comfy import GATEWAY, Comfy, local_address, use_remote

PROBE_TIMEOUT_S = 10.0
CACHE_S = 15.0
RUNPOD_PORT = 8188  # the ComfyUI port of RunPod's ComfyUI template
_POD_ID = re.compile(r"^(?=[a-z0-9]*\d)[a-z0-9]{8,24}$")  # a pod's ID: letters and digits
_RUNPOD_HOST = re.compile(r"^([a-z0-9]+)-(\d+)\.proxy\.runpod\.net$")
MAX_KEY = 1024

# Where RunPod's ComfyUI templates (and the usual Docker images) keep ComfyUI's models, for when ClipForge could not ask
# the cloud computer itself: the current template's folder first.
MODEL_FOLDERS = ("/workspace/runpod-slim/ComfyUI/models", "/workspace/ComfyUI/models",
                 "/workspace/madapps/ComfyUI/models", "/ComfyUI/models", "/opt/ComfyUI/models", "/app/ComfyUI/models")

_cache_lock = threading.Lock()
_cache: dict = {"at": 0.0, "key": None, "view": None}
_turn = threading.Lock()


# ------------------------------------------------------------------ the address and the key
def normalize(text: str) -> str:
    """The address as ClipForge keeps it, from what the person pasted: a RunPod pod's ID alone becomes its ComfyUI
    address, a missing https:// is added, and the page's own path, query or "#" part are dropped. EngineError (plain
    words) for what cannot be a cloud ComfyUI's address. "" stays "" (no cloud computer)."""
    raw = (text or "").strip().strip("<>\"'").strip()
    if not raw:
        return ""
    if len(raw) > 300 or any(c.isspace() or ord(c) < 32 for c in raw):
        raise EngineError("Paste only the web address, on one line, without spaces.")
    if _POD_ID.match(raw.lower()):
        return f"https://{raw.lower()}-{RUNPOD_PORT}.proxy.runpod.net"
    if "://" not in raw:
        raw = "https://" + raw
    try:
        parts = urlsplit(raw)
        host = (parts.hostname or "").lower()
        port = parts.port
    except ValueError as exc:
        raise EngineError("That is not a web address. Paste the one RunPod shows, like "
                          "https://abc123xyz-8188.proxy.runpod.net") from exc
    if parts.scheme.lower() not in ("http", "https") or not host:
        raise EngineError("That is not a web address. Paste the one RunPod shows, like "
                          "https://abc123xyz-8188.proxy.runpod.net")
    if parts.username or parts.password:
        raise EngineError("Leave the name and password out of the address: put them in the Key box as name:password.")
    scheme = parts.scheme.lower()
    if scheme == "http" and not local_address(raw):
        if host.endswith(".proxy.runpod.net"):
            scheme = "https"  # RunPod's addresses all work with https
        else:
            raise EngineError("Use the address that starts with https://, so nobody on the way can read what ClipForge "
                              "sends. (Plain http:// only works for a ComfyUI on this computer.)")
    netloc = f"[{host}]" if ":" in host else host
    if port:
        netloc += f":{port}"
    path = parts.path.rstrip("/")
    # ComfyUI's page itself is at "/"; its address in a browser can end in a page name or ?/# parts: not part of it
    if path.lower().endswith((".html", "/index")):
        path = path.rsplit("/", 1)[0]
    return urlunsplit((scheme, netloc, path, "", ""))


def clean_key(text: str) -> str:
    """The key as it is kept (sealed like a password, secure.py): "" removes it. It is sent in a header as it is, so
    only printable ASCII: letters, digits and the symbols on a US keyboard."""
    key = (text or "").strip()
    if len(key) > MAX_KEY or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in key):
        raise EngineError("Paste only the key, on one line, without spaces.")
    if any(not 33 <= ord(c) <= 126 for c in key):
        raise EngineError("The key has a letter ClipForge cannot send (like é, or an invisible character copied with "
                          "it). Copy the key again, or choose one with only letters, digits and symbols.")
    return key


def host(url: str) -> str:
    try:
        return urlsplit(url).hostname or url
    except ValueError:
        return url


def _runpod_port(url: str) -> int | None:
    m = _RUNPOD_HOST.match(host(url).lower())
    return int(m.group(2)) if m else None


# ------------------------------------------------------------------ is it there?
def check(settings: dict, max_age: float = CACHE_S) -> dict:
    """The cloud computer in Settings: {"base": its address when its ComfyUI answers (else None), "url", "host",
    "why": what is wrong in plain words, "gpu", "vram_mb", "ram_mb", "version", "device"}. Asked at most every
    `max_age` seconds (0: now). Never raises."""
    url = str(settings.get("engines_remote_url") or "").rstrip("/")
    key = str(settings.get("engines_remote_key") or "")
    use_remote(url, key)  # every request to that address (and only to it) carries the key
    view = {"base": None, "url": url, "host": host(url) if url else "", "why": "", "gpu": "", "vram_mb": 0,
            "ram_mb": 0, "version": "", "device": "", "key_set": bool(key)}
    if not url:
        view["why"] = "Paste your cloud computer's web address (Settings, Pictures, video, voice)."
        return view
    ident = (url, key)
    with _cache_lock:
        if _cache["key"] == ident and _cache["view"] is not None and time.monotonic() - _cache["at"] < max_age:
            return dict(_cache["view"])
    try:
        view.update(_probe(url))
    except Exception as exc:  # noqa: BLE001 - a check must never break the page asking
        view["why"] = f"Could not check your cloud computer ({exc.__class__.__name__})."
    with _cache_lock:
        _cache.update(at=time.monotonic(), key=ident, view=dict(view))
    return view


def forget() -> None:
    with _cache_lock:
        _cache.update(at=0.0, key=None, view=None)


def _probe(url: str) -> dict:
    client = Comfy(url, timeout=PROBE_TIMEOUT_S)
    name = host(url)
    try:
        r = httpx.get(client.base + "/system_stats", timeout=PROBE_TIMEOUT_S, trust_env=client.trust_env,
                      headers=client.headers, follow_redirects=False)
    except httpx.TimeoutException:
        return {"why": f"Your cloud computer ({name}) took too long to answer. If you just started it, wait a minute "
                       "and press Check again."}
    except httpx.ConnectError:
        return {"why": f"Nothing answered at {name}. Check that your cloud computer is on (in RunPod: Pods, then "
                       "Start) and that the address is right."}
    except httpx.HTTPError as exc:
        return {"why": f"Could not reach {name} ({exc.__class__.__name__}). Check the address."}
    code = r.status_code
    if code in (401, 403):
        return {"why": f"Your cloud computer said no (it answered {code}). It may need a key, or the key here is not "
                       "right."}
    if code in GATEWAY:
        return {"why": f"Your cloud computer is there, but its ComfyUI is not ready (it answered {code}). After you "
                       "press Start in RunPod it takes a few minutes: wait, then press Check again."}
    if code == 404 and name.endswith(".proxy.runpod.net"):
        return {"why": "RunPod has nothing running at this address. Start your pod (in RunPod: Pods, then Start), "
                       "wait a few minutes, then press Check again. If it is on, copy the address again from Connect."}
    if 300 <= code < 400:
        return {"why": "That address sends ClipForge somewhere else (a sign-in page?). Paste the address of the "
                       "ComfyUI itself."}
    try:
        stats = r.json() if code == 200 else None
    except ValueError:
        stats = None
    if not isinstance(stats, dict) or not isinstance(stats.get("system"), dict):
        port = _runpod_port(url)
        hint = (f" This is the address for port {port}: use the one for port {RUNPOD_PORT} (\"Connect to HTTP "
                f"Service [Port {RUNPOD_PORT}]\")." if port and port != RUNPOD_PORT else "")
        return {"why": f"That address answers, but it is not ComfyUI (it answered {code}).{hint}"}
    out = {"base": client.base, "why": ""}
    out.update(_machine_view(stats))
    return out


def _machine_view(stats: dict) -> dict:
    system = stats.get("system") or {}
    devices = [d for d in (stats.get("devices") or []) if isinstance(d, dict)]
    first = devices[0] if devices else {}
    name = str(first.get("name") or "")
    name = re.sub(r"^\w+:\d+\s*", "", name)          # "cuda:0 NVIDIA GeForce RTX 4090 : cudaMallocAsync"
    name = re.sub(r"\s*:\s*\w+$", "", name).strip()   # → "NVIDIA GeForce RTX 4090"
    kind = str(first.get("type") or "")

    def mb(value) -> int:
        try:
            return max(0, int(float(value) / (1 << 20)))
        except (TypeError, ValueError):
            return 0

    return {"gpu": name[:80] if kind != "cpu" else "", "vram_mb": mb(first.get("vram_total")) if kind != "cpu" else 0,
            "ram_mb": mb(system.get("ram_total")), "version": str(system.get("comfyui_version") or "")[:40],
            "device": kind[:20]}


def machine(view: dict) -> dict:
    """The cloud computer as makers.fit and makers.ranked see a computer (which model suits it)."""
    device = view.get("device") or ""
    flavor = "cuda" if device == "cuda" else "mps" if device == "mps" else "cpu" if device == "cpu" else ""
    return {"flavor": flavor, "memory_mb": int(view.get("ram_mb") or 0), "vram_mb": int(view.get("vram_mb") or 0),
            "gpu": {"name": view.get("gpu") or "", "vram_mb": int(view.get("vram_mb") or 0)}}


# ------------------------------------------------------------------ one job at a time
@contextlib.contextmanager
def turn(cancel: Cancel, progress: Progress | None, max_wait_s: float):
    """This app's pictures and clips go to the cloud computer one at a time (the way they take turns on this
    computer's graphics card), so a job's time limit is not used up waiting in the cloud computer's own line."""
    from ..pipeline.common import Cancelled

    deadline = time.monotonic() + max(1.0, max_wait_s)
    told = False
    while not _turn.acquire(timeout=0.5):
        if cancel():
            raise Cancelled()
        if time.monotonic() > deadline:
            raise EngineError(f"Your cloud computer was busy with another picture or clip for {max_wait_s / 60:.0f} "
                              "minutes. Try again when it has finished.")
        if progress and not told:
            progress(0.0, "Waiting for your cloud computer: it is making another picture or clip")
            told = True
    try:
        yield
    finally:
        _turn.release()


# ------------------------------------------------------------------ putting models on it
def remote_folders(base: str) -> dict[str, str]:
    """Where the cloud computer's ComfyUI keeps each kind of model file (GET /internal/folder_paths), as paths on that
    computer; a folder it does not name, or names in a way that cannot be a Linux path, is left out."""
    try:
        r = Comfy(base, timeout=PROBE_TIMEOUT_S)._get("/internal/folder_paths")  # noqa: SLF001
        data = r.json() if r.status_code == 200 else {}
    except (EngineError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    aliases = {"diffusion_models": ("diffusion_models", "unet"), "text_encoders": ("text_encoders", "clip")}
    out: dict[str, str] = {}
    for folder in catalog.MODEL_FOLDERS:
        for name in aliases.get(folder, (folder,)):
            paths = data.get(name)
            first = paths[0] if isinstance(paths, list) and paths else None
            if isinstance(first, str) and _linux_path(first):
                out[folder] = first.rstrip("/")
                break
    return out


def _linux_path(path: str) -> bool:
    return (path.startswith("/") and 1 < len(path) <= 400 and ".." not in path.split("/")
            and not any(ord(c) < 32 or ord(c) == 127 for c in path))


def command_for(model_id: str, settings: dict, agreed: bool = False) -> dict:
    """What Settings shows for putting one model on the cloud computer: {"model", "name", "command" ("" when it
    already has every file), "files", "bytes", "where", "asked": whether the cloud computer said where its models
    go and which files it has}."""
    m = catalog.by_id(model_id)
    if m is None or m.role == "voice":
        raise EngineError("Unknown model." if m is None else "The voice runs inside ClipForge, not on the cloud "
                                                               "computer.")
    if m.rule and not agreed:
        raise EngineError(f"{m.name} comes with use rules; agree to them first. {m.rule}")
    view = check(settings, max_age=0)
    files = list(m.files)
    folders: dict[str, str] = {}
    if view["base"]:
        from . import models

        folders = remote_folders(view["base"])
        files = models.missing(m, "remote", view["base"])
    command = download_command(m, files, folders) if files else ""
    known = {f.folder for f in files} <= set(folders)
    where = (folders.get("diffusion_models") or "").rpartition("/")[0] if known and folders else ""
    return {"model": m.id, "name": m.name, "command": command, "bytes": sum(f.size for f in files),
            "files": [{"name": f.name, "folder": f.folder, "bytes": f.size} for f in files], "where": where,
            "asked": bool(view["base"]), "why": view["why"]}


def download_command(model: catalog.Model, files: list[catalog.ModelFile], folders: dict[str, str]) -> str:
    """A command to paste into the cloud computer's terminal (bash): it downloads `files` from their pinned addresses
    into ComfyUI's model folders there (`folders`, else the first of MODEL_FOLDERS that exists), resumes a stopped
    download, checks each file's size and SHA-256 before giving it its name (a damaged one is deleted), never
    replaces a different file of the same name, and says what to do next. Everything in it is quoted."""
    q = shlex.quote
    gb = sum(f.size for f in files) / 1e9
    lines = [
        "bash <<'CLIPFORGE'",
        f"# ClipForge: puts {model.name} on this cloud computer for ComfyUI ({len(files)} "
        f"file{'s' if len(files) != 1 else ''}, {gb:.1f} GB),",
        "# from Hugging Face at a fixed version; each file is checked (SHA-256) before ComfyUI can see it.",
        "size_of() { wc -c < \"$1\" | tr -d ' '; }",
        "sum_of() { if command -v sha256sum >/dev/null 2>&1; then sha256sum \"$1\"; else shasum -a 256 \"$1\"; fi"
        " | cut -d' ' -f1; }",
        "get() {",
        "  dir=\"$1\"; name=\"$2\"; size=\"$3\"; sum=\"$4\"; url=\"$5\"; file=\"$dir/$name\"; part=\"$file.part\"",
        "  mkdir -p \"$dir\" || return 1",
        "  if [ -f \"$file\" ]; then",
        "    echo \"Checking $name (it is already there)...\"",
        "    if [ \"$(size_of \"$file\")\" = \"$size\" ] && [ \"$(sum_of \"$file\")\" = \"$sum\" ]; then echo \"  OK\";"
        " return 0; fi",
        "    echo \"  A different file called $name is already in $dir, so it was left alone. Move it away and run"
        " this again.\"",
        "    return 1",
        "  fi",
        "  if [ -f \"$part\" ] && [ \"$(size_of \"$part\")\" -gt \"$size\" ]; then rm -f \"$part\"; fi",
        "  if [ ! -f \"$part\" ] || [ \"$(size_of \"$part\")\" != \"$size\" ]; then",
        "    echo \"Downloading $name ($((size / 1000000)) MB)...\"",
        "    if command -v curl >/dev/null 2>&1; then",
        "      curl -L --fail --retry 5 --retry-delay 5 -C - -o \"$part\" \"$url\" < /dev/null || return 1",
        "    else",
        "      wget -c -O \"$part\" \"$url\" < /dev/null || return 1",
        "    fi",
        "  fi",
        "  echo \"Checking $name...\"",
        "  if [ \"$(size_of \"$part\")\" != \"$size\" ] || [ \"$(sum_of \"$part\")\" != \"$sum\" ]; then",
        "    rm -f \"$part\"; echo \"  $name came down damaged and was deleted. Run this again.\"; return 1",
        "  fi",
        "  mv -f \"$part\" \"$file\" && echo \"  OK\"",
        "}",
    ]
    if any(f.folder not in folders for f in files):
        lines += ["models=\"\"",
                  "for d in " + " ".join(q(d) for d in MODEL_FOLDERS) + " \"$HOME/ComfyUI/models\"; do",
                  "  if [ -d \"$d\" ]; then models=\"$d\"; break; fi",
                  "done",
                  "if [ -z \"$models\" ]; then echo \"ClipForge could not find ComfyUI's models folder on this "
                  "computer.\"; exit 1; fi"]
    lines.append("ok=1")
    for f in files:
        where = q(folders[f.folder]) if f.folder in folders else f"\"$models\"/{q(f.folder)}"
        pin = f.pin
        lines.append(f"get {where} {q(f.name)} {int(f.size)} {q(f.sha256)} {q(pin.url)} || ok=0")
    done = f"Done: {model.name} is on this cloud computer. Go back to ClipForge and press \"I ran it: check again\"."
    again = ("Something did not work (see above). Paste the same command again: finished files are kept and a "
             "stopped download goes on where it stopped.")
    lines += ["echo", f"if [ \"$ok\" = 1 ]; then echo {q(done)};", f"else echo {q(again)}; fi", "CLIPFORGE"]
    return "\n".join(lines) + "\n"
