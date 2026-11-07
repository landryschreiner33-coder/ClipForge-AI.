"""Talking to a ComfyUI server (github.com/comfyanonymous/ComfyUI, GPL-3.0), the program that runs the picture and
video models. ComfyUI is a separate program; ClipForge only talks to it over its local HTTP API, the same way its own
web page does:

* POST /prompt          a graph of nodes in ComfyUI's "API format" (graphs.py builds them), answered with an id
* GET  /history/<id>    the finished graph's output files (empty while it still runs)
* GET  /view            one output file
* POST /upload/image    a picture to animate (image-to-video)
* POST /interrupt       stop the running graph (Cancel); POST /queue {"delete": [...]} drops a waiting one
* GET  /system_stats    which ComfyUI, PyTorch and graphics device it runs on, and its memory
* GET  /object_info/<n> whether a node type exists (an older ComfyUI may lack a node a graph needs)
* GET  /models/<folder> the model files it can see
* POST /free            unload its models, so the memory goes back to other work
* ws   /ws?clientId=    progress while it works (sampler steps, the node it is on)

Nothing here sends anything but the graph, the prompt words inside it and a picture to animate. The address is
ClipForge's own ComfyUI on 127.0.0.1, or the one the person typed in Settings.
"""
from __future__ import annotations

import json
import logging
import mimetypes
import time
import uuid
from pathlib import Path
from typing import Callable
from urllib.parse import quote, urlsplit

import httpx

from . import EngineError

log = logging.getLogger(__name__)

POLL_S = 1.0
Progress = Callable[[float, str], None]
Cancel = Callable[[], bool]

# Words in ComfyUI's error text and what they mean for the person.
_PLAIN = (
    (("out of memory", "outofmemory", "mps backend out of memory", "cuda error: out of memory", "not enough memory"),
     "The computer ran out of memory for this model. Close other programs, choose a smaller size, or use the lighter "
     "model in Settings, Pictures, video, voice."),
    (("value not in list",), "ComfyUI does not have a model file this needs. Download the model in Settings, "
     "Pictures, video, voice."),
    (("error while deserializing header", "safetensors", "invalid load key", "unexpected eof"),
     "A model file ComfyUI tried to load is damaged or incomplete. Remove the model and download it again in "
     "Settings, Pictures, video, voice."),
    (("does not exist", "node type not found", "cannot execute because node"),
     "This ComfyUI is missing a part the graph needs; it may be too old. Update ComfyUI, or use ClipForge's own copy."),
)


def plain(message: str) -> str:
    low = (message or "").lower()
    for words, text in _PLAIN:
        if any(w in low for w in words):
            return text
    return (message or "ComfyUI stopped without saying why.").strip()[:400]


def local_address(url: str) -> bool:
    """Whether an address is this computer (only then may ClipForge write into that ComfyUI's model folders)."""
    host = (urlsplit(url).hostname or "").lower()
    return host in ("127.0.0.1", "localhost", "::1")


class Comfy:
    """One ComfyUI server at `base` (for example http://127.0.0.1:8188)."""

    def __init__(self, base: str, *, timeout: float = 30.0) -> None:
        self.base = base.rstrip("/")
        self.timeout = timeout
        self.client_id = uuid.uuid4().hex

    # ------------------------------------------------------------------ plain requests
    def _get(self, path: str, **params) -> httpx.Response:
        try:
            return httpx.get(self.base + path, params=params or None, timeout=self.timeout, trust_env=False)
        except httpx.HTTPError as exc:
            raise EngineError(f"ComfyUI at {self.base} did not answer ({exc.__class__.__name__}).") from exc

    def _post(self, path: str, body: dict | None = None, **kwargs) -> httpx.Response:
        try:
            return httpx.post(self.base + path, json=body, timeout=self.timeout, trust_env=False, **kwargs)
        except httpx.HTTPError as exc:
            raise EngineError(f"ComfyUI at {self.base} did not answer ({exc.__class__.__name__}).") from exc

    def stats(self) -> dict:
        r = self._get("/system_stats")
        if r.status_code != 200:
            raise EngineError(f"ComfyUI at {self.base} answered {r.status_code}; is it ComfyUI?")
        try:
            data = r.json()
        except ValueError as exc:
            raise EngineError(f"The program at {self.base} is not ComfyUI.") from exc
        if not isinstance(data, dict) or "system" not in data:
            raise EngineError(f"The program at {self.base} is not ComfyUI.")
        return data

    def alive(self) -> bool:
        try:
            self.stats()
            return True
        except EngineError:
            return False

    def missing_nodes(self, classes: list[str]) -> list[str]:
        """The node types of `classes` this ComfyUI does not have."""
        missing = []
        for cls in dict.fromkeys(classes):
            r = self._get(f"/object_info/{quote(cls, safe='')}")
            try:
                found = r.status_code == 200 and cls in (r.json() or {})
            except ValueError:
                found = False
            if not found:
                missing.append(cls)
        return missing

    def model_files(self, folder: str) -> list[str] | None:
        """The files ComfyUI sees in one model folder (diffusion_models, text_encoders, vae...); None when this
        ComfyUI cannot list them."""
        r = self._get(f"/models/{quote(folder, safe='')}")
        if r.status_code != 200:
            return None
        try:
            names = r.json()
        except ValueError:
            return None
        return [str(n) for n in names] if isinstance(names, list) else None

    def upload_image(self, path: Path) -> str:
        """Hand a picture to ComfyUI (for LoadImage); returns the name ComfyUI knows it by."""
        mime = mimetypes.guess_type(path.name)[0] or "image/png"
        name = f"clipforge-{uuid.uuid4().hex[:12]}{path.suffix.lower() or '.png'}"
        try:
            with open(path, "rb") as fh:
                r = httpx.post(self.base + "/upload/image", files={"image": (name, fh, mime)},
                               data={"type": "input", "overwrite": "true"}, timeout=max(self.timeout, 120.0),
                               trust_env=False)
        except OSError as exc:
            raise EngineError(f"Could not read the picture to animate ({exc}).") from exc
        except httpx.HTTPError as exc:
            raise EngineError(f"ComfyUI did not take the picture ({exc.__class__.__name__}).") from exc
        if r.status_code != 200:
            raise EngineError(f"ComfyUI did not take the picture (it answered {r.status_code}).")
        got = r.json()
        sub = str(got.get("subfolder") or "")
        return f"{sub}/{got['name']}" if sub else str(got["name"])

    def interrupt(self, prompt_id: str = "") -> None:
        try:
            self._post("/queue", {"delete": [prompt_id]}) if prompt_id else None
            self._post("/interrupt", {"prompt_id": prompt_id} if prompt_id else {})
        except EngineError:
            pass

    def free(self) -> None:
        """Unload ComfyUI's models so their memory goes back to the computer (it reloads them when needed)."""
        try:
            self._post("/free", {"unload_models": True, "free_memory": True})
        except EngineError:
            pass

    # ------------------------------------------------------------------ running a graph
    def submit(self, graph: dict) -> str:
        r = self._post("/prompt", {"prompt": graph, "client_id": self.client_id})
        if r.status_code != 200:
            raise EngineError(plain(_validation_text(r)))
        try:
            got = r.json()
        except ValueError as exc:
            raise EngineError("ComfyUI answered the request in an unexpected way.") from exc
        if got.get("node_errors"):
            raise EngineError(plain(_errors_text(got["node_errors"])))
        pid = str(got.get("prompt_id") or "")
        if not pid:
            raise EngineError("ComfyUI did not accept the request.")
        return pid

    def history(self, prompt_id: str) -> dict | None:
        r = self._get(f"/history/{quote(prompt_id, safe='')}")
        if r.status_code != 200:
            return None
        try:
            return (r.json() or {}).get(prompt_id)
        except ValueError:
            return None

    def wait(self, prompt_id: str, *, progress: Progress | None = None, cancel: Cancel | None = None,
             timeout_s: float = 1800.0, steps_node: str = "", labels: dict[str, str] | None = None) -> dict:
        """Wait for a submitted graph; returns its history entry. Progress comes from ComfyUI's websocket (sampler
        steps of `steps_node`, the node it is on); without one, the history is polled."""
        cancel = cancel or (lambda: False)
        labels = labels or {}
        deadline = time.monotonic() + timeout_s
        ws = _socket(self.base, self.client_id)
        last_poll = 0.0
        try:
            while True:
                if cancel():
                    self.interrupt(prompt_id)
                    raise EngineError("Stopped.")
                if time.monotonic() > deadline:
                    self.interrupt(prompt_id)
                    raise EngineError(f"ComfyUI took longer than {timeout_s / 60:.0f} minutes, so it was stopped. "
                                      "Try a smaller size or the lighter model.")
                if ws is not None:
                    msg = _receive(ws, 1.0)
                    if msg == "closed":
                        ws = None
                    elif isinstance(msg, dict):
                        done = _on_message(msg, prompt_id, progress, steps_node, labels)
                        if done == "error":
                            entry = self.history(prompt_id) or {}
                            raise EngineError(plain(_entry_error(entry) or _message_error(msg)))
                        if done == "interrupted":
                            raise EngineError("ComfyUI stopped the work (it was interrupted).")
                        if done == "success":
                            entry = self.history(prompt_id)
                            if entry:
                                return entry
                else:
                    time.sleep(0.25)
                if time.monotonic() - last_poll >= (POLL_S if ws is None else 5.0):
                    last_poll = time.monotonic()
                    entry = self.history(prompt_id)
                    if entry:
                        status = entry.get("status") or {}
                        if status.get("status_str") == "error":
                            raise EngineError(plain(_entry_error(entry)))
                        if status.get("completed", True) or entry.get("outputs"):
                            return entry
        finally:
            if ws is not None:
                try:
                    ws.close()
                except Exception:  # noqa: BLE001
                    pass

    @staticmethod
    def output_files(entry: dict) -> list[dict]:
        """Every file a finished graph saved: [{filename, subfolder, type, node}] (pictures, videos, audio)."""
        files = []
        for node, out in (entry.get("outputs") or {}).items():
            if not isinstance(out, dict):
                continue
            for key, items in out.items():
                if key == "animated" or not isinstance(items, list):
                    continue
                for item in items:
                    if isinstance(item, dict) and item.get("filename"):
                        files.append({"filename": str(item["filename"]), "subfolder": str(item.get("subfolder") or ""),
                                      "type": str(item.get("type") or "output"), "node": str(node), "key": key})
        return files

    def download(self, file: dict, dest: Path) -> Path:
        dest.parent.mkdir(parents=True, exist_ok=True)
        params = {"filename": file["filename"], "subfolder": file.get("subfolder", ""), "type": file.get("type", "output")}
        part = dest.with_name(dest.name + ".part")
        try:
            with httpx.stream("GET", self.base + "/view", params=params, timeout=max(self.timeout, 300.0),
                              trust_env=False) as r:
                if r.status_code != 200:
                    raise EngineError(f"ComfyUI did not hand over the result (it answered {r.status_code}).")
                with open(part, "wb") as fh:
                    for block in r.iter_bytes(1 << 20):
                        fh.write(block)
        except httpx.HTTPError as exc:
            part.unlink(missing_ok=True)
            raise EngineError(f"ComfyUI did not hand over the result ({exc.__class__.__name__}).") from exc
        if not part.stat().st_size:
            part.unlink(missing_ok=True)
            raise EngineError("ComfyUI handed over an empty file.")
        part.replace(dest)
        return dest

    def run(self, graph: dict, *, progress: Progress | None = None, cancel: Cancel | None = None,
            timeout_s: float = 1800.0, steps_node: str = "", labels: dict[str, str] | None = None) -> list[dict]:
        """Submit `graph`, wait for it and return its output files."""
        if progress:
            progress(0.02, "Sending the request to ComfyUI")
        pid = self.submit(graph)
        entry = self.wait(pid, progress=progress, cancel=cancel, timeout_s=timeout_s, steps_node=steps_node,
                          labels=labels)
        files = self.output_files(entry)
        if not files:
            raise EngineError("ComfyUI finished but saved nothing.")
        return files


# ------------------------------------------------------------------ the websocket (optional)
def _socket(base: str, client_id: str):
    try:
        from websockets.sync.client import connect
    except Exception:  # noqa: BLE001 - polling works without it
        return None
    parts = urlsplit(base)
    scheme = "wss" if parts.scheme == "https" else "ws"
    try:
        return connect(f"{scheme}://{parts.netloc}{parts.path.rstrip('/')}/ws?clientId={client_id}", open_timeout=5,
                       close_timeout=2, max_size=64 << 20, proxy=None)
    except TypeError:  # an older websockets without the proxy argument
        try:
            return connect(f"{scheme}://{parts.netloc}{parts.path.rstrip('/')}/ws?clientId={client_id}",
                           open_timeout=5, close_timeout=2, max_size=64 << 20)
        except Exception:  # noqa: BLE001
            return None
    except Exception:  # noqa: BLE001 - an address that does not take websockets: poll instead
        return None


def _receive(ws, timeout: float):
    try:
        raw = ws.recv(timeout=timeout)
    except TimeoutError:
        return None
    except Exception:  # noqa: BLE001 - the connection closed: fall back to polling
        return "closed"
    if isinstance(raw, (bytes, bytearray)):
        return None  # preview pictures
    try:
        msg = json.loads(raw)
    except ValueError:
        return None
    return msg if isinstance(msg, dict) else None


def _on_message(msg: dict, prompt_id: str, progress: Progress | None, steps_node: str,
                labels: dict[str, str]) -> str:
    kind, data = msg.get("type"), msg.get("data") or {}
    if not isinstance(data, dict) or (data.get("prompt_id") and data.get("prompt_id") != prompt_id):
        return ""
    if kind == "execution_error":
        return "error"
    if kind == "execution_interrupted":
        return "interrupted"
    if kind == "execution_success":
        return "success"
    if kind == "executing":
        node = data.get("node")
        if node is None and data.get("prompt_id") == prompt_id:
            return "success"  # older ComfyUI: "executing" with no node means the graph finished
        if progress and node is not None:
            progress(0.1 if str(node) != steps_node else 0.15, labels.get(str(node), "Working"))
    elif kind == "progress" and progress:
        value, top = float(data.get("value") or 0), float(data.get("max") or 0)
        if top > 0 and (not steps_node or str(data.get("node")) == steps_node):
            progress(0.15 + 0.75 * min(1.0, value / top), f"Step {int(value)} of {int(top)}")
    return ""


def _message_error(msg: dict) -> str:
    data = msg.get("data") or {}
    return str(data.get("exception_message") or data.get("exception_type") or "")


def _entry_error(entry: dict) -> str:
    for item in (entry.get("status") or {}).get("messages") or []:
        if isinstance(item, (list, tuple)) and len(item) == 2 and item[0] == "execution_error":
            data = item[1] or {}
            return str(data.get("exception_message") or data.get("exception_type") or "")
    return ""


def _errors_text(node_errors: dict) -> str:
    parts = []
    for node, err in (node_errors or {}).items():
        for e in (err or {}).get("errors") or []:
            parts.append(f"{(err or {}).get('class_type', node)}: {e.get('message', '')} {e.get('details', '')}".strip())
    return "; ".join(parts)[:400] or "ComfyUI refused the request."


def _validation_text(r: httpx.Response) -> str:
    try:
        body = r.json()
    except ValueError:
        return f"ComfyUI refused the request (it answered {r.status_code})."
    if body.get("node_errors"):
        return _errors_text(body["node_errors"])
    err = body.get("error") or {}
    return str(err.get("message") or err.get("details") or f"ComfyUI refused the request ({r.status_code}).")
