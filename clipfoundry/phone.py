"""An optional private-network status companion, isolated from every desktop control and media route."""
from __future__ import annotations

import hashlib
import ipaddress
import math
import os
import re
import secrets
import shutil
import socket
import subprocess
import threading
import time
from collections import deque
from typing import Literal

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from . import __version__, config, db
from .publish.common import app_request, local_only

PAIRING_SECONDS = 300
DEVICE_SECONDS = 90 * 86400
MAX_DEVICES = 8
PAIR_ATTEMPTS = 20
RATE_SECONDS = 60
GLOBAL_RATE = 10
PEER_RATE = 5
_WIFI_RANGES = tuple(ipaddress.ip_network(r) for r in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"))
_TAILSCALE_RANGE = ipaddress.ip_network("100.64.0.0/10")
_PHONE_FILES = {"/": "index.html", "/app.js": "app.js", "/style.css": "style.css"}


def private_address(address: str, mode: str) -> str:
    """Only literal private IPv4 addresses; no hostname resolution, wildcard or public listening."""
    try:
        ip = ipaddress.IPv4Address(address)
    except ipaddress.AddressValueError as exc:
        raise ValueError("Choose this PC's private IPv4 address from the list.") from exc
    ranges = (_TAILSCALE_RANGE,) if mode == "tailscale" else _WIFI_RANGES if mode == "wifi" else ()
    if not any(ip in network for network in ranges):
        raise ValueError("Choose a Tailscale address for Tailscale, or a private home-network address for Wi-Fi.")
    return str(ip)


def discover_addresses() -> list[dict]:
    """Read existing local interfaces; never install, sign in to, or configure Tailscale or a firewall."""
    out: list[dict] = []
    executable = shutil.which("tailscale")
    if executable:
        try:
            result = subprocess.run([executable, "ip", "-4"], capture_output=True, text=True, timeout=2,
                                    check=False, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            if result.returncode == 0:
                for value in result.stdout.splitlines()[:8]:
                    try:
                        out.append({"mode": "tailscale", "address": private_address(value.strip(), "tailscale")})
                    except ValueError:
                        pass
        except (OSError, subprocess.TimeoutExpired):
            pass
    try:
        for row in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET, socket.SOCK_STREAM):
            try:
                entry = {"mode": "wifi", "address": private_address(row[4][0], "wifi")}
            except ValueError:
                continue
            if entry not in out:
                out.append(entry)
    except OSError:
        pass
    return out[:16]


def _title(value: object) -> str:
    """Media titles are useful to the paired owner; paths, URLs and arbitrary diagnostics are not."""
    text = " ".join(str(value or "").split())[:120]
    text = re.sub(r"(?i)(?:https?://|www\.)\S+|(?:[a-z]:[\\/]|/|\\\\)\S+", "[private detail]", text)
    return text


def status_snapshot() -> dict:
    """Explicitly select status fields. Never send settings, notes, tokens, raw errors or entire desktop records."""
    from .autopilot import home, routes, scout
    from .autopilot.host import supervisor
    from .office import health, view

    settings = db.get_settings()
    now = time.time()
    run = view.run_state(settings)
    host = supervisor.status()
    start, end = scout.day_bounds(settings, now)
    rows = db.select("scheduled_publications", "planned_at >= ? AND planned_at < ?", (start, end))
    counts = routes.today_posts(rows, now)
    processed = int(db.scalar("SELECT COUNT(*) FROM clips WHERE status = 'ready' AND created_at >= ? AND "
                              "project_id IN (SELECT id FROM projects WHERE origin IN ('autopilot', 'live'))",
                              (start,)) or 0)
    working = home.working(settings)
    progress = (working or {}).get("progress")
    if progress is not None:
        progress = float(progress)
        progress = max(0.0, min(1.0, progress)) if math.isfinite(progress) else None
    nxt = db.select("scheduled_publications", "status IN ('approved', 'awaiting_approval', 'publishing', "
                    "'reconciling', 'action_needed') AND planned_at >= ?", (now - 600,), "planned_at", 1)
    checks = health.check(settings)
    # Use the desktop's attention policy: automatic retries stay quiet and derived account/worker/sleep holds appear.
    # Only fixed descriptions cross the phone boundary; the desktop details may include diagnostics or paths.
    platforms = {}
    for platform in ("youtube", "tiktok"):
        account = db.get_account(platform) or {}
        platforms[platform] = {"connected": bool(account.get("has_tokens")),
                               "needs_reconnect": bool((account.get("info") or {}).get("needs_reconnect"))}
    action_titles = {"account": "An account needs attention",
                     "rights": "A video's reuse permission needs attention", "file": "A video needs a file",
                     "approve": "A post needs approval", "publish": "A post needs attention",
                     "gpu": "The GPU needs attention", "sleep": "PC sleep settings need attention",
                     "stopped": "Background work needs attention", "videos": "Videos need attention",
                     "other": "ClipFoundry needs attention on your PC"}
    needs = [{"kind": a["type"] if a.get("type") in action_titles else "other",
              "title": action_titles.get(a.get("type"), "ClipFoundry needs attention on your PC")}
             for a in home.needs_you(settings, platforms, bool(host["alive"]))[:8]]
    posts = home.post_counts()
    if posts["review"] and not any(a["kind"] == "approve" for a in needs):
        needs.append({"kind": "approve", "title": "Posts need approval on your PC"})
    if posts["fix"] and not any(a["kind"] == "publish" for a in needs):
        needs.append({"kind": "publish", "title": "Posts need attention on your PC"})
    return {
        "version": __version__, "server_time": now, "timezone": settings.get("autopilot_timezone"),
        "run": {k: run[k] for k in ("state", "label", "publishing_paused")},
        "workers": {"alive": bool(host["alive"]), "heartbeat_at": host.get("last_heartbeat")},
        "currently": home.currently(settings, bool(host["alive"])),
        "working": ({"title": _title(working.get("title")), "step": working.get("step"),
                     "progress": progress} if working else None),
        "today": {"daily": int(settings.get("autopilot_daily_target") or 15), "processed": processed,
                  **{k: counts[k] for k in ("published", "scheduled", "published_posts", "scheduled_posts")}},
        "posts": {k: int(posts[k]) for k in ("review", "fix", "ready", "scheduled")},
        "next_post": ({"platform": nxt[0]["platform"], "title": _title(nxt[0].get("title")),
                       "planned_at": nxt[0]["planned_at"], "status": nxt[0]["status"]} if nxt else None),
        "health": {k: checks[k] for k in ("status", "label", "checked_at")},
        "health_checks": [{k: c[k] for k in ("id", "label", "status", "checked_at")}
                          for c in checks["checks"]],
        "needs_you": needs[:8], "desktop_note": "Use ClipFoundry on your PC to make changes.",
    }


class PhoneManager:
    """Own one listener and one short-lived pairing challenge. Device grants survive normal app restarts."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._server = None
        self._thread: threading.Thread | None = None
        self._socket: socket.socket | None = None
        self._state = "off"
        self._error = ""
        self._code_hash = ""
        self._code_expires = 0.0
        self._attempts = 0
        self._global_attempts: deque[float] = deque()
        self._peer_attempts: dict[str, deque[float]] = {}
        self._candidates: list[dict] = []
        self._candidates_at = 0.0
        self.desktop_port = int(os.environ.get("CLIPFOUNDRY_PORT", "8765"))

    @property
    def running(self) -> bool:
        return bool(self._server and self._server.started and self._thread and self._thread.is_alive())

    def addresses(self) -> list[dict]:
        if time.monotonic() - self._candidates_at > 20 or not self._candidates_at:
            self._candidates = discover_addresses()
            self._candidates_at = time.monotonic()
        return list(self._candidates)

    def status(self) -> dict:
        settings = db.get_settings()
        enabled = bool(settings["phone_enabled"])
        running = self.running
        address = settings["phone_address"]
        port = int(settings["phone_port"])
        state = "running" if running else self._state
        if enabled and not running and state == "running":
            state = "failed"
        return {"enabled": enabled, "running": running, "state": state, "mode": settings["phone_mode"],
                "address": f"http://{address}:{port}" if address else "", "bind_address": address, "port": port,
                "error": self._error if self._error else
                ("Phone access stopped. Turn it off and enable it again." if state == "failed" else ""),
                "paired_devices": int(db.scalar("SELECT COUNT(*) FROM phone_devices WHERE expires_at > ?",
                                                 (time.time(),)) or 0), "addresses": self.addresses(),
                "device_lifetime_days": 90, "pairing_lifetime_seconds": PAIRING_SECONDS}

    def _clear_pairing(self) -> None:
        self._code_hash = ""
        self._code_expires = 0.0
        self._attempts = 0

    def stop(self) -> None:
        with self._lock:
            self._clear_pairing()
            server, thread, listener = self._server, self._thread, self._socket
            if server:
                server.should_exit = True
            if thread and thread.is_alive() and thread is not threading.current_thread():
                thread.join(timeout=5)
            if thread and thread.is_alive():
                server.force_exit = True
                thread.join(timeout=2)
            if thread and thread.is_alive():
                self._state = "failed"
                self._error = "Phone access is still closing. Restart ClipFoundry before enabling it again."
                return
            if listener:
                listener.close()
            self._server = self._thread = self._socket = None
            self._state = "off"
            self._error = ""

    def _start(self, address: str, port: int, allow_fallback: bool) -> int:
        import uvicorn

        if self._thread and self._thread.is_alive():
            raise ValueError("Phone access is still closing. Restart ClipFoundry before enabling it again.")
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            try:
                listener.bind((address, port))
            except OSError:
                if not allow_fallback:
                    raise
                listener.bind((address, 0))
            listener.listen(32)
            listener.setblocking(False)
            port = int(listener.getsockname()[1])
            self._socket = listener
            self._state = "starting"
            self._error = ""
            self._server = uvicorn.Server(uvicorn.Config(create_companion_app(self), host=address, port=port,
                                                        access_log=False, log_level="critical", proxy_headers=False,
                                                        lifespan="off", timeout_graceful_shutdown=2))
            self._thread = threading.Thread(target=self._serve, name="phone-status", daemon=True)
            self._thread.start()
            deadline = time.monotonic() + 3
            while self._thread.is_alive() and not self._server.started and time.monotonic() < deadline:
                time.sleep(0.02)
            if not self.running:
                raise ValueError("Phone access could not start. Try another port or restart ClipFoundry.")
            self._state = "running"
            return port
        except BaseException:
            listener.close()
            self.stop()
            raise

    def _serve(self) -> None:
        try:
            self._server.run(sockets=[self._socket])
        except (Exception, SystemExit):
            self._state = "failed"
            self._error = "Phone access stopped. Turn it off and enable it again."

    def enable(self, mode: str, address: str = "", port: int | None = None, desktop_port: int = 8765) -> dict:
        with self._lock:
            candidates = self.addresses()
            if not address:
                address = next((a["address"] for a in candidates if a["mode"] == mode), "")
            if not address:
                raise ValueError("No Tailscale address was found. Open Tailscale on this PC and phone, then try again."
                                 if mode == "tailscale" else
                                 "No home Wi-Fi address was found. Connect this PC to your home network first.")
            address = private_address(address, mode)
            chosen = port if port is not None else 8766
            if not 1024 <= chosen <= 65535 or (port is not None and chosen == desktop_port):
                raise ValueError("Choose a port from 1024 to 65535 that is different from ClipFoundry's desktop port.")
            if chosen == desktop_port:
                chosen = 8767 if desktop_port != 8767 else 8768
            self.stop()
            # Keep the requested configuration if binding fails, so its actual error is reviewable on the PC.
            db.save_settings({"phone_enabled": True, "phone_mode": mode, "phone_address": address,
                              "phone_port": chosen})
            try:
                chosen = self._start(address, chosen, allow_fallback=port is None)
            except Exception:  # a failed optional listener must leave desktop work running
                self._state = "failed"
                self._error = ("Phone access could not open this PC address and port. "
                               "Check the address or try another port.")
            else:
                if chosen == desktop_port:
                    self.stop()
                    self._state = "failed"
                    self._error = "Choose a phone port different from ClipFoundry's desktop port."
                    return self.status()
                db.save_settings({"phone_port": chosen})
            return self.status()

    def restore(self) -> None:
        settings = db.get_settings()
        if settings["phone_enabled"]:
            try:
                self.enable(settings["phone_mode"], settings["phone_address"], int(settings["phone_port"]),
                            self.desktop_port)
            except Exception:  # restored phone configuration is never required for desktop startup
                self._state = "failed"
                self._error = "Phone access could not restart. Turn it off and choose this PC's current address."

    def disable(self) -> dict:
        db.save_settings({"phone_enabled": False})
        self.stop()
        return self.status()

    def pairing(self) -> dict:
        with self._lock:
            if not self.running or not db.get_settings()["phone_enabled"]:
                raise HTTPException(409, "Enable phone access before making a pairing code.")
            if int(db.scalar("SELECT COUNT(*) FROM phone_devices WHERE expires_at > ?", (time.time(),)) or 0) \
                    >= MAX_DEVICES:
                raise HTTPException(409, "Eight devices are paired. Revoke phone access before pairing another.")
            code = f"{secrets.randbelow(100_000_000):08d}"
            self._code_hash = hashlib.sha256(code.encode("ascii")).hexdigest()
            self._code_expires = time.time() + PAIRING_SECONDS
            self._attempts = 0
            return {"code": code, "expires_at": self._code_expires, "address": self.status()["address"]}

    def _rate_limit(self, peer: str, now: float) -> None:
        cutoff = now - RATE_SECONDS
        while self._global_attempts and self._global_attempts[0] <= cutoff:
            self._global_attempts.popleft()
        self._peer_attempts = {p: deque(t for t in stamps if t > cutoff)
                               for p, stamps in self._peer_attempts.items() if stamps and stamps[-1] > cutoff}
        stamps = self._peer_attempts.setdefault(peer, deque())
        if len(self._global_attempts) >= GLOBAL_RATE or len(stamps) >= PEER_RATE:
            raise HTTPException(429, "Too many pairing attempts. Wait a minute and make a new code on your PC.",
                                headers={"Retry-After": "60"})
        self._global_attempts.append(now)
        stamps.append(now)

    def pair(self, code: str, peer: str) -> dict:
        with self._lock:
            now = time.time()
            self._rate_limit(peer, now)
            if not self.running or not db.get_settings()["phone_enabled"]:
                raise HTTPException(403, "Phone access is off.")
            self._attempts += 1
            digest = hashlib.sha256(code.encode("ascii")).hexdigest()
            valid = bool(self._code_hash and now < self._code_expires and self._attempts <= PAIR_ATTEMPTS and
                         secrets.compare_digest(digest, self._code_hash))
            if not valid:
                if now >= self._code_expires or self._attempts >= PAIR_ATTEMPTS:
                    self._clear_pairing()
                raise HTTPException(401, "This code is incorrect or expired. Make a new code on your PC.")
            token = secrets.token_urlsafe(32)
            expires = now + DEVICE_SECONDS
            with db.connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                conn.execute("DELETE FROM phone_devices WHERE expires_at <= ?", (now,))
                if conn.execute("SELECT COUNT(*) FROM phone_devices").fetchone()[0] >= MAX_DEVICES:
                    raise HTTPException(409, "Eight devices are paired. Revoke phone access on your PC first.")
                conn.execute("INSERT INTO phone_devices (id, token_hash, created_at, expires_at) VALUES (?, ?, ?, ?)",
                             (db.new_id(), hashlib.sha256(token.encode("ascii")).hexdigest(), now, expires))
            self._clear_pairing()
            return {"token": token, "expires_at": expires}

    def authorize(self, request: Request) -> None:
        value = request.headers.get("authorization", "")
        token = value[7:] if value.startswith("Bearer ") else ""
        if not self.running or not db.get_settings()["phone_enabled"] or not re.fullmatch(r"[A-Za-z0-9_-]{43}", token):
            raise HTTPException(401, "Pair this phone with ClipFoundry on your PC.")
        digest = hashlib.sha256(token.encode("ascii")).hexdigest()
        if not db.scalar("SELECT COUNT(*) FROM phone_devices WHERE token_hash = ? AND expires_at > ?",
                         (digest, time.time())):
            raise HTTPException(401, "This phone's access expired or was revoked. Pair it again on your PC.")

    def revoke(self) -> dict:
        with self._lock:
            self._clear_pairing()
            db.execute("DELETE FROM phone_devices")
        return self.status()


class PairBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(pattern=r"^[0-9]{8}$", min_length=8, max_length=8)


class EnableBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["tailscale", "wifi"] = "tailscale"
    address: str = Field(default="", max_length=64)
    port: int | None = Field(default=None, ge=1024, le=65535)


def create_companion_app(manager: PhoneManager) -> FastAPI:
    companion = FastAPI(title="ClipFoundry phone status", docs_url=None, redoc_url=None, openapi_url=None)

    @companion.middleware("http")
    async def private_responses(request: Request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = ("default-src 'none'; script-src 'self'; style-src 'self'; "
                                                     "connect-src 'self'; img-src 'self'; base-uri 'none'; "
                                                     "form-action 'none'; frame-ancestors 'none'")
        return response

    # Validation errors must never echo a submitted pairing code or authorization credential.
    from fastapi.exceptions import RequestValidationError

    @companion.exception_handler(RequestValidationError)
    async def invalid_pairing(request: Request, exc: RequestValidationError):
        return JSONResponse({"detail": "Enter the eight-digit pairing code shown on your PC."}, status_code=422)

    @companion.post("/api/pair")
    def pair(body: PairBody, request: Request) -> dict:
        return manager.pair(body.code, request.client.host if request.client else "unknown")

    @companion.get("/api/status", dependencies=[Depends(manager.authorize)])
    def snapshot() -> dict:
        return status_snapshot()

    @companion.get("/")
    @companion.get("/app.js")
    @companion.get("/style.css")
    def phone_file(request: Request):
        path = config.FRONTEND_DIST / "phone" / _PHONE_FILES[request.url.path]
        if not path.is_file():
            raise HTTPException(404, "The phone page is missing. Update ClipFoundry on your PC.")
        return FileResponse(path)

    return companion


def create_setup_router(manager: PhoneManager) -> APIRouter:
    router = APIRouter(prefix="/api/phone-monitor")

    @router.get("", dependencies=[Depends(local_only)])
    def status() -> dict:
        return manager.status()

    @router.post("/enable", dependencies=[Depends(app_request)])
    def enable(body: EnableBody, request: Request) -> dict:
        try:
            return manager.enable(body.mode, body.address, body.port, request.url.port or 8765)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @router.post("/disable", dependencies=[Depends(app_request)])
    def disable() -> dict:
        return manager.disable()

    @router.post("/pairing", dependencies=[Depends(app_request)])
    def pairing() -> dict:
        return manager.pairing()

    @router.post("/revoke", dependencies=[Depends(app_request)])
    def revoke() -> dict:
        return manager.revoke()

    return router


manager = PhoneManager()
router = create_setup_router(manager)
