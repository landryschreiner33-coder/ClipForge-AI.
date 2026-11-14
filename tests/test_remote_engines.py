"""A ComfyUI on the person's rented cloud computer (clipfoundry/engines/remote.py): the address and the key, the check
in plain words, pictures and clips made there through a stand-in of RunPod's proxy (which checks the key, can be
"off" or "starting", and can drop a connection), waiting out a moment without an answer, never sending a request
twice, the Settings view and routes, and the command that puts a model on the cloud computer, run for real in bash.

The real ComfyUI behind a stand-in cloud address is checked by scripts/local_engines_check.py --remote on GitHub's
machines; a real RunPod pod is not reachable from the tests."""
from __future__ import annotations

import base64
import dataclasses
import hashlib
import json
import shutil
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

import httpx
import pytest

from clipfoundry import config
from clipfoundry.engines import EngineError, catalog, comfy, makers, remote
from test_local_engines import FakeComfy, FileServer, png_bytes  # noqa: F401 - the stand-ins of the local tests

KEY = "s3cret-token"


# ------------------------------------------------------------------ a stand-in of a cloud computer's proxy
class CloudProxy:
    """What sits between ClipForge and a pod's ComfyUI: RunPod's proxy. `state` "on" passes requests on to ComfyUI
    (checking the key when `key` is set), "starting" answers 502 like the proxy while ComfyUI is not up, "off" answers
    404 with a page like RunPod's. `gateway` maps a path start to how many more times it answers 502 first, `drop` to
    how many more times the connection is closed without an answer (after passing the request on, when
    `drop_after_forward`)."""

    def __init__(self, target: str, key: str = "") -> None:
        self.target, self.key, self.state = target, key, "on"
        self.gateway: dict[str, int] = {}
        self.drop: dict[str, int] = {}
        self.drop_after_forward = False
        self.seen: list[tuple[str, str, str]] = []  # (method, path, Authorization)
        owner = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a) -> None:
                pass

            def _answer(self, code: int, body: bytes, ctype: str = "text/html") -> None:
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(body)

            def _take(self, table: dict[str, int], path: str) -> bool:
                for start, n in list(table.items()):
                    if path.startswith(start) and n > 0:
                        table[start] = n - 1
                        return True
                return False

            def _handle(self, method: str) -> None:
                path = urlsplit(self.path).path
                n = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(n) if n else b""
                owner.seen.append((method, path, self.headers.get("Authorization") or ""))
                if owner.state == "off":
                    return self._answer(404, b"<html>404 Not Found</html>")
                if owner.state == "starting" or owner._take_gateway(path):
                    return self._answer(502, b"<html>502 Bad Gateway</html>")
                if owner.key and self.headers.get("Authorization") != f"Bearer {owner.key}":
                    return self._answer(401, b'{"error": "unauthorized"}', "application/json")
                dropping = self._take(owner.drop, path)
                if dropping and not owner.drop_after_forward:
                    self.close_connection = True
                    self.connection.close()
                    return None
                headers = {k: v for k, v in self.headers.items() if k.lower() in ("content-type",)}
                r = httpx.request(method, owner.target + self.path, content=body, headers=headers, timeout=30,
                                  trust_env=False)
                if dropping:
                    self.close_connection = True
                    self.connection.close()
                    return None
                return self._answer(r.status_code, r.content, r.headers.get("content-type", "application/json"))

            def do_GET(self) -> None:  # noqa: N802
                self._handle("GET")

            def do_POST(self) -> None:  # noqa: N802
                self._handle("POST")

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def _take_gateway(self, path: str) -> bool:
        for start, n in list(self.gateway.items()):
            if path.startswith(start) and n > 0:
                self.gateway[start] = n - 1
                return True
        return False

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture(autouse=True)
def _own_data_folder(monkeypatch, tmp_path):
    monkeypatch.setenv("CLIPFOUNDRY_DATA", str(tmp_path / "data"))
    yield
    comfy.use_remote("")
    remote.forget()


@pytest.fixture
def fake_comfy(tmp_path, monkeypatch):
    c = FakeComfy(tmp_path)
    monkeypatch.setattr(comfy, "_socket", lambda base, cid: None)  # the stand-in has no websocket: poll
    monkeypatch.setattr(comfy, "POLL_S", 0.05)
    monkeypatch.setattr(comfy, "RETRY_WAIT_S", 0.01)
    yield c
    c.stop()


@pytest.fixture
def cloud(fake_comfy):
    p = CloudProxy(fake_comfy.url, key=KEY)
    yield p
    p.stop()


@pytest.fixture
def cloud_settings(monkeypatch, cloud):
    """ClipForge set to use "A cloud computer" at the stand-in proxy's address, with its key."""
    values = dict(config.DEFAULT_SETTINGS, engines_comfyui="remote", engines_remote_url=cloud.url,
                  engines_remote_key=KEY)
    from clipfoundry import engines

    monkeypatch.setattr(makers, "_settings", lambda: values)
    monkeypatch.setattr(engines, "_settings", lambda: values)
    makers.forget_found()
    return values


@pytest.fixture
def no_local_graphics(monkeypatch):
    """A cloud job must not wait for this computer's graphics card."""
    from clipfoundry import gpu

    def refuse(*a, **k):
        raise AssertionError("a cloud job asked for this computer's graphics card")

    monkeypatch.setattr(gpu.manager, "heavy", refuse)


def nvidia_stats(fake: FakeComfy, monkeypatch, vram_gb: int = 24) -> None:
    """The stand-in ComfyUI answers /system_stats like RunPod's 4090 pod."""
    stats = {"system": {"os": "posix", "comfyui_version": "0.43.0", "ram_total": 61 * (1 << 30)},
             "devices": [{"name": "cuda:0 NVIDIA GeForce RTX 4090 : cudaMallocAsync", "type": "cuda",
                          "vram_total": vram_gb * (1 << 30)}]}
    real = fake.server.RequestHandlerClass.do_GET

    def do_get(handler):
        if urlsplit(handler.path).path == "/system_stats":
            data = json.dumps(stats).encode()
            handler.send_response(200)
            handler.send_header("Content-Type", "application/json")
            handler.send_header("Content-Length", str(len(data)))
            handler.end_headers()
            handler.wfile.write(data)
            return None
        return real(handler)

    monkeypatch.setattr(fake.server.RequestHandlerClass, "do_GET", do_get)


# ------------------------------------------------------------------ the address and the key
def test_what_the_person_pastes_becomes_an_address():
    runpod = "https://abc123xyz4567-8188.proxy.runpod.net"
    assert remote.normalize("abc123xyz4567") == runpod  # the pod's ID alone
    assert remote.normalize("  ABC123XYZ4567 ") == runpod
    assert remote.normalize("abc123xyz4567-8188.proxy.runpod.net") == runpod  # no https://
    assert remote.normalize(runpod + "/") == runpod
    assert remote.normalize(runpod + "/?workflow=x#top") == runpod
    assert remote.normalize(runpod + "/index.html") == runpod
    assert remote.normalize("http://abc123xyz4567-8188.proxy.runpod.net") == runpod  # RunPod: always https
    assert remote.normalize(f"<{runpod}>") == runpod
    assert remote.normalize("https://comfy.example.com:8443/comfy/") == "https://comfy.example.com:8443/comfy"
    assert remote.normalize("http://127.0.0.1:8188") == "http://127.0.0.1:8188"  # a tunnel to this computer
    assert remote.normalize("") == ""
    assert remote.normalize("localhost:8188") == "https://localhost:8188"  # a word is not a pod's ID
    for bad, words in (("http://192.168.1.20:8188", "https://"), ("https://me:pw@comfy.example.com", "Key box"),
                       ("ftp://comfy.example.com", "not a web address"), ("https://exa mple.com", "one line"),
                       ("https://comfy.example.com:port", "not a web address"), ("x" * 400, "one line")):
        with pytest.raises(EngineError, match=words):
            remote.normalize(bad)
    assert remote.clean_key("  abc  ") == "abc" and remote.clean_key("") == ""
    with pytest.raises(EngineError, match="one line"):
        remote.clean_key("two words")


def test_cloud_settings_are_checked_and_the_key_is_kept_sealed(monkeypatch):
    from fastapi.testclient import TestClient

    from clipfoundry import api, db

    assert config.validate_settings({"engines_comfyui": "remote"}) == {"engines_comfyui": "remote"}
    assert config.validate_settings({"engines_remote_url": "http://comfy.example.com"}) == {}  # never in clear
    assert config.validate_settings({"engines_remote_url": "http://localhost:80@evil.example"}) == {}
    assert config.validate_settings({"engines_remote_url": "https://a-8188.proxy.runpod.net/"}) == {
        "engines_remote_url": "https://a-8188.proxy.runpod.net"}
    assert config.validate_settings({"engines_remote_key": "a key"}) == {}
    assert "engines_remote_key" in config.SECRET_KEYS
    client = TestClient(api.app)
    client.put("/api/settings", json={"engines_remote_key": KEY})  # not from here (POST /api/engines/remote)
    assert db.get_settings()["engines_remote_key"] == ""
    db.save_settings({"engines_remote_key": KEY})
    assert client.get("/api/settings").json()["engines_remote_key"] == "********"
    with db.connect() as conn:
        stored = conn.execute("SELECT value FROM settings WHERE key = 'engines_remote_key'").fetchone()["value"]
    assert KEY not in stored  # sealed (secure.py), never plain text in the database
    assert db.get_settings()["engines_remote_key"] == KEY
    assert "s3cret" not in json.dumps(client.get("/api/engines").json())


def test_the_key_goes_only_to_the_cloud_computer(cloud, fake_comfy):
    comfy.use_remote(cloud.url, KEY)
    there = comfy.Comfy(cloud.url)
    assert there.remote and there.headers["Authorization"] == f"Bearer {KEY}" and not there.trust_env
    elsewhere = comfy.Comfy(fake_comfy.url)
    assert not elsewhere.remote and elsewhere.headers == {}
    comfy.use_remote("https://other.example.com", "")
    assert not comfy.Comfy(cloud.url).remote  # the old address no longer gets the old key
    assert comfy.Comfy("https://other.example.com").trust_env  # over the internet: this computer's proxy settings
    assert comfy.auth_headers("me:pw") == {"Authorization": "Basic " + base64.b64encode(b"me:pw").decode()}


def test_the_websocket_carries_the_key_too(monkeypatch):
    import websockets.sync.client as ws_client

    got = []
    monkeypatch.setattr(ws_client, "connect", lambda url, **kw: got.append((url, kw)) or "socket")
    comfy.use_remote("https://abc-8188.proxy.runpod.net", KEY)
    assert comfy._socket("https://abc-8188.proxy.runpod.net", "c1") == "socket"  # noqa: SLF001
    url, kw = got[-1]
    assert url == "wss://abc-8188.proxy.runpod.net/ws?clientId=c1"
    assert kw["additional_headers"]["Authorization"] == f"Bearer {KEY}" and "proxy" not in kw
    comfy._socket("http://127.0.0.1:8188", "c2")  # noqa: SLF001 - not the cloud computer: no key, no proxy
    assert "additional_headers" not in got[-1][1] and got[-1][1]["proxy"] is None


# ------------------------------------------------------------------ the check, in plain words
def test_the_check_says_what_is_wrong(cloud, fake_comfy, monkeypatch):
    nvidia_stats(fake_comfy, monkeypatch)
    view = remote.check({"engines_remote_url": ""})
    assert view["base"] is None and "Paste your cloud computer's web address" in view["why"]
    settings = {"engines_remote_url": cloud.url, "engines_remote_key": KEY}
    view = remote.check(settings, max_age=0)
    assert view["base"] == cloud.url and view["gpu"] == "NVIDIA GeForce RTX 4090" and view["vram_mb"] == 24 * 1024
    assert view["version"] == "0.43.0" and view["device"] == "cuda" and view["key_set"]
    assert remote.machine(view)["flavor"] == "cuda"
    cloud.state = "starting"
    assert remote.check(settings)["base"] == cloud.url  # asked again only after a while
    view = remote.check(settings, max_age=0)
    assert view["base"] is None and "not ready" in view["why"] and "502" in view["why"]
    cloud.state = "on"
    view = remote.check({"engines_remote_url": cloud.url, "engines_remote_key": "wrong"}, max_age=0)
    assert view["base"] is None and "said no" in view["why"]
    view = remote.check({"engines_remote_url": "http://127.0.0.1:9"}, max_age=0)
    assert view["base"] is None and "Nothing answered at the address you saved" in view["why"]
    assert "127.0.0.1" not in view["why"]  # these words reach other pages: never the address itself
    files = FileServer({"/system_stats": b"<html>JupyterLab</html>"})
    try:
        view = remote.check({"engines_remote_url": files.url}, max_age=0)
        assert view["base"] is None and "not ComfyUI" in view["why"]
    finally:
        files.stop()


@pytest.mark.parametrize("code,words", [(404, "RunPod has nothing running at this address"),
                                         (200, "use the one for port 8188"), (524, "not ready"),
                                         (302, "somewhere else")])
def test_runpods_answers_in_plain_words(monkeypatch, code, words):
    url = "https://abc123xyz4567-8888.proxy.runpod.net" if code == 200 else "https://abc123xyz4567-8188.proxy.runpod.net"
    monkeypatch.setattr(remote.httpx, "get", lambda u, **k: httpx.Response(code, text="<html></html>",
                                                                          request=httpx.Request("GET", u)))
    view = remote.check({"engines_remote_url": url}, max_age=0)
    assert view["base"] is None and words in view["why"]


def test_a_slow_cloud_computer(monkeypatch):
    def slow(u, **k):
        raise httpx.ReadTimeout("slow", request=httpx.Request("GET", u))

    monkeypatch.setattr(remote.httpx, "get", slow)
    view = remote.check({"engines_remote_url": "https://abc123xyz4567-8188.proxy.runpod.net"}, max_age=0)
    assert "took too long" in view["why"]


# ------------------------------------------------------------------ making pictures and clips there
def test_a_picture_made_on_the_cloud_computer(cloud_settings, cloud, fake_comfy, monkeypatch, no_local_graphics):
    from clipfoundry import engines

    nvidia_stats(fake_comfy, monkeypatch)
    fake_comfy.have(catalog.Z_IMAGE_TURBO)
    fake_comfy.have(catalog.FLUX2_KLEIN_4B)
    st = engines.status("image")
    # a 24 GB graphics card suits the best picture model (this Mac's memory does not matter)
    assert st["ready"] and st["remote"] and st["model"] == "z-image-turbo"
    assert st["engine"] == "ComfyUI on your cloud computer (NVIDIA GeForce RTX 4090) · Z-Image Turbo"
    seen = []
    path = engines.make_image("A lighthouse at dusk", seed=3, progress=lambda f, m: seen.append(m))
    assert path.suffix == ".png" and makers.png_size(path) == (1088, 1920)
    assert path.parent.parent.parent == config.data_dir() / "engines" / "made"
    note = json.loads(path.with_suffix(".json").read_text())
    assert note["model"] == "z-image-turbo" and "cloud computer" in note["engine"] and note["seed"] == 3
    assert fake_comfy.prompts and fake_comfy.prompts[-1]["5"]["inputs"]["text"] == "A lighthouse at dusk"
    assert seen[0] == "Sending the request to ComfyUI" and seen[-1] == "Saving"
    asked = {(m, p) for m, p, _ in cloud.seen}
    assert {("POST", "/prompt"), ("GET", "/view"), ("GET", "/system_stats")} <= asked
    assert all(auth == f"Bearer {KEY}" for _, _, auth in cloud.seen)  # every request carried the key


def test_a_clip_from_a_picture_on_the_cloud_computer(cloud_settings, cloud, fake_comfy, tmp_path, no_local_graphics):
    from clipfoundry import engines

    fake_comfy.have(catalog.WAN22_TI2V_5B)
    start = tmp_path / "start.png"
    start.write_bytes(png_bytes(64, 64))
    cloud.gateway["/upload/image"] = 1  # the proxy answers for ComfyUI once: the picture is sent again
    path = engines.make_video("The waves roll in", image=start, seconds=2.0, width=480, height=832, seed=1)
    assert path.read_bytes()[4:8] == b"ftyp"
    assert len(fake_comfy.uploads) == 1 and fake_comfy.prompts[-1]["12"]["inputs"]["image"] == fake_comfy.uploads[0]
    assert ("POST", "/upload/image", f"Bearer {KEY}") in cloud.seen


def test_a_moment_without_an_answer_is_waited_out(cloud_settings, cloud, fake_comfy, no_local_graphics):
    from clipfoundry import engines

    fake_comfy.have(catalog.FLUX2_KLEIN_4B)
    cloud.gateway["/history/"] = 3  # the proxy answers for ComfyUI three times while it works,
    cloud.drop["/history/"] = 2     # the connection drops twice,
    cloud.drop["/view"] = 1         # and so does the download's once
    path = engines.make_image("a cat")
    assert makers.png_size(path)[0] > 0 and len(fake_comfy.prompts) == 1
    assert sum(1 for m, p, _ in cloud.seen if p == "/view") == 2


def test_a_cloud_computer_that_stops_answering_ends_the_job_in_plain_words(cloud_settings, cloud, fake_comfy,
                                                                            monkeypatch, no_local_graphics):
    from clipfoundry import engines

    fake_comfy.have(catalog.FLUX2_KLEIN_4B)
    fake_comfy.polls_before_done = 10_000
    monkeypatch.setattr(comfy, "LOST_S", 0.5)
    real_submit = comfy.Comfy.submit

    def submit_then_stop(self, graph):
        pid = real_submit(self, graph)
        cloud.state = "off"  # the pod was stopped (or its RunPod money ran out) while it worked
        return pid

    monkeypatch.setattr(comfy.Comfy, "submit", submit_then_stop)
    started = time.monotonic()
    with pytest.raises(EngineError, match="stopped answering"):
        engines.make_image("a cat")
    assert time.monotonic() - started < 30


def test_a_ComfyUI_on_this_computer_still_ends_the_job_at_once(fake_comfy):
    """Waiting out a missing answer is for a cloud computer only: a ComfyUI on this computer that is gone is gone."""
    c = comfy.Comfy("http://127.0.0.1:9")
    with pytest.raises(EngineError, match="did not answer"):
        c._poll("p1", {})  # noqa: SLF001


def test_a_request_is_never_sent_twice(cloud_settings, cloud, fake_comfy, no_local_graphics):
    from clipfoundry import engines

    fake_comfy.have(catalog.FLUX2_KLEIN_4B)
    cloud.drop["/prompt"] = 1
    cloud.drop_after_forward = True  # ComfyUI got it, but its answer was lost on the way
    with pytest.raises(EngineError, match="did not answer"):
        engines.make_image("a cat")
    assert len(fake_comfy.prompts) == 1


def _forget_after_submit(fake: FakeComfy) -> None:
    """The cloud computer's ComfyUI restarts: the job is in neither its queue nor its history any more."""
    fake.polls_before_done = 10_000
    fake.stops_after = 0
    fake._interrupted_at = fake._queue_asks  # noqa: SLF001 - its queue is empty from the next ask on


def test_a_job_the_cloud_computer_lost_ends_in_plain_words(cloud_settings, cloud, fake_comfy, monkeypatch,
                                                            no_local_graphics):
    """A pod whose ComfyUI restarted forgot the job: ClipForge says so instead of waiting out the time limit (and
    keeping every other job waiting for its turn)."""
    from clipfoundry import engines

    fake_comfy.have(catalog.FLUX2_KLEIN_4B)
    monkeypatch.setattr(comfy, "LOST_CHECK_S", 0.3)
    real_submit = comfy.Comfy.submit

    def submit_then_restart(self, graph):
        pid = real_submit(self, graph)
        _forget_after_submit(fake_comfy)
        return pid

    monkeypatch.setattr(comfy.Comfy, "submit", submit_then_restart)
    started = time.monotonic()
    with pytest.raises(EngineError, match="restarted and lost"):
        engines.make_image("a cat")
    assert time.monotonic() - started < 20 and len(fake_comfy.prompts) == 1
    assert remote._turn.acquire(timeout=0) and (remote._turn.release() is None)  # noqa: SLF001 - its turn is over


def test_a_job_lost_in_an_outage_is_noticed_when_the_pod_answers_again(cloud_settings, cloud, fake_comfy, monkeypatch,
                                                                       no_local_graphics):
    from clipfoundry import engines

    fake_comfy.have(catalog.FLUX2_KLEIN_4B)
    assert comfy.LOST_CHECK_S >= 30  # only the outage makes it look now
    real_submit = comfy.Comfy.submit

    def submit_then_outage(self, graph):
        pid = real_submit(self, graph)
        cloud.state = "starting"  # RunPod's proxy answers 502 while the pod restarts
        _forget_after_submit(fake_comfy)
        threading.Timer(0.5, lambda: setattr(cloud, "state", "on")).start()
        return pid

    monkeypatch.setattr(comfy.Comfy, "submit", submit_then_outage)
    started = time.monotonic()
    with pytest.raises(EngineError, match="restarted and lost"):
        engines.make_image("a cat")
    assert time.monotonic() - started < 20


def test_a_job_that_finishes_while_it_is_looked_for_is_not_lost(cloud_settings, cloud, fake_comfy, monkeypatch,
                                                                no_local_graphics):
    """Gone from the queue because it just finished: the history is asked once more before calling it lost."""
    from clipfoundry import engines

    fake_comfy.have(catalog.FLUX2_KLEIN_4B)
    monkeypatch.setattr(comfy, "LOST_CHECK_S", 0.0)
    real_running = comfy.Comfy.running

    def finished_meanwhile(self, prompt_id):
        fake_comfy.polls_before_done = 0  # it finished between the history and the queue
        fake_comfy.stops_after, fake_comfy._interrupted_at = 0, fake_comfy._queue_asks  # noqa: SLF001
        return real_running(self, prompt_id)

    fake_comfy.polls_before_done = 10_000
    monkeypatch.setattr(comfy.Comfy, "running", finished_meanwhile)
    path = engines.make_image("a cat")
    assert makers.png_size(path)[0] > 0


def test_the_job_says_what_is_wrong_before_sending_anything(cloud_settings, cloud, fake_comfy):
    from clipfoundry import engines

    fake_comfy.have(catalog.FLUX2_KLEIN_4B)
    cloud.state = "starting"
    with pytest.raises(EngineError, match="not ready"):
        engines.make_image("a cat")
    cloud.state = "on"
    cloud_settings["engines_remote_key"] = "wrong"
    with pytest.raises(EngineError, match="said no"):
        engines.make_image("a cat")
    cloud_settings["engines_remote_key"] = KEY
    fake_comfy.models["vae"].clear()
    makers.forget_found()
    with pytest.raises(EngineError, match="none of the models ClipForge uses for pictures yet"):
        engines.make_image("a cat")
    assert not fake_comfy.prompts


def test_a_hiccup_while_asking_which_models_it_has_is_waited_out(cloud_settings, cloud, fake_comfy,
                                                                   no_local_graphics):
    """One gateway answer or dropped connection on a question is asked again: it never reads as "not on it yet"."""
    from clipfoundry import engines

    fake_comfy.have(catalog.FLUX2_KLEIN_4B)
    cloud.gateway["/models/"] = 1
    cloud.drop["/models/"] = 1
    assert engines.status("image")["ready"]
    makers.forget_found()
    cloud.gateway["/models/"] = 1
    cloud.gateway["/object_info/"] = 1
    cloud.drop["/object_info/"] = 1
    path = engines.make_image("a cat")
    assert makers.png_size(path)[0] > 0 and len(fake_comfy.prompts) == 1


def test_a_cloud_computer_that_does_not_say_which_models_it_has_says_so(cloud_settings, cloud, fake_comfy, monkeypatch,
                                                                        no_local_graphics):
    """It answered the check, then never a question about its models (it is stopping): plain words, not "put a model
    on it", and nothing is sent."""
    from clipfoundry import engines

    fake_comfy.have(catalog.FLUX2_KLEIN_4B)
    assert engines.status("image")["ready"]  # the check is answered (and kept for a while)
    cloud.gateway["/models/"] = 1000
    st = engines.status("image")
    assert not st["ready"] and st["remote"] and "did not pass the request on" in st["why"]
    with pytest.raises(EngineError, match="did not pass the request on"):
        engines.make_image("a cat")
    cloud.gateway["/models/"] = 0
    cloud.gateway["/object_info/"] = 1000  # the models answer, the nodes do not: not "this ComfyUI lacks ..."
    with pytest.raises(EngineError, match="did not pass the request on"):
        engines.make_image("a cat")
    assert not fake_comfy.prompts
    by = {m["id"]: m for m in engines.overview()["models"]}  # the Settings page still opens
    assert set(by) >= {"flux2-klein-4b", "z-image-turbo"}


def test_a_pod_stopped_after_the_check_is_not_read_as_missing_models(cloud_settings, cloud, fake_comfy,
                                                                    no_local_graphics):
    """RunPod's proxy answers 404 for a stopped pod: while the check still says it is there, its model and node lists
    come back as 404 too. That says the pod is gone, never "put a model on it" or "this ComfyUI lacks ..."."""
    from clipfoundry import engines

    fake_comfy.have(catalog.FLUX2_KLEIN_4B)
    assert engines.status("image")["ready"]  # the check is answered (and kept for a while)
    cloud.state = "off"
    st = engines.status("image")
    assert not st["ready"] and "none of the models" not in st["why"] and "answered 404" in st["why"]
    real = comfy.Comfy.missing_nodes
    try:  # the models answer, then the pod stops before the nodes are asked about
        def stopped_before_the_nodes(self, classes):
            cloud.state = "off"
            return real(self, classes)

        cloud.state = "on"
        comfy.Comfy.missing_nodes = stopped_before_the_nodes
        with pytest.raises(EngineError) as err:
            engines.make_image("a cat")
    finally:
        comfy.Comfy.missing_nodes = real
    assert "lacks" not in str(err.value) and "answered 404" in str(err.value) and not fake_comfy.prompts
    # a ComfyUI that answers but does not know a model folder (an older one) still just has none there
    cloud.state = "on"
    comfy.use_remote(cloud.url, KEY)
    assert comfy.Comfy(cloud.url).model_files("no_such_folder") is None


def test_a_jobs_history_is_asked_once_each_time(cloud_settings, cloud, fake_comfy, monkeypatch, no_local_graphics):
    """While a job runs, an outage is waited out by the job itself (LOST_S, with Stop looked at between questions):
    each question about its history is asked once, so the give-up time and Stop are not stretched by retries."""
    from clipfoundry import engines

    fake_comfy.have(catalog.FLUX2_KLEIN_4B)
    fake_comfy.polls_before_done = 10_000
    monkeypatch.setattr(comfy, "LOST_S", 0.5)
    monkeypatch.setattr(comfy, "RETRY_WAIT_S", 2.0)  # a retry of each history question would wait 2 s, then 4 s
    real_submit = comfy.Comfy.submit

    def submit_then_gateway(self, graph):
        pid = real_submit(self, graph)
        cloud.state = "starting"  # the proxy answers 502 from now on
        return pid

    monkeypatch.setattr(comfy.Comfy, "submit", submit_then_gateway)
    started = time.monotonic()
    with pytest.raises(EngineError, match="stopped answering"):
        engines.make_image("a cat")
    assert time.monotonic() - started < 5


def test_the_note_names_the_model_that_made_it(cloud_settings, cloud, fake_comfy, monkeypatch, no_local_graphics):
    """Not whatever is chosen (or listed) after the job: the model is taken off the cloud computer while it works."""
    from clipfoundry import engines

    nvidia_stats(fake_comfy, monkeypatch)
    fake_comfy.have(catalog.FLUX2_KLEIN_4B)
    real_submit = comfy.Comfy.submit

    def submit_then_remove(self, graph):
        pid = real_submit(self, graph)
        for names in fake_comfy.models.values():
            names.clear()
        return pid

    monkeypatch.setattr(comfy.Comfy, "submit", submit_then_remove)
    path = engines.make_image("a cat")
    note = json.loads(path.with_suffix(".json").read_text())
    assert note["engine"] == "ComfyUI on your cloud computer (NVIDIA GeForce RTX 4090) · FLUX.2 klein 4B"
    assert note["model"] == "flux2-klein-4b"


def test_a_finished_job_does_not_bring_back_a_cloud_computer_no_longer_chosen(cloud_settings, cloud, fake_comfy,
                                                                              monkeypatch, no_local_graphics):
    """The person chose this computer's ComfyUI while a cloud picture was being made: when it is done, nothing about
    it (its note) asks the cloud computer again, which would hand its key out again."""
    from clipfoundry import engines

    monkeypatch.setattr(makers, "_settings", lambda: dict(cloud_settings))
    fake_comfy.have(catalog.FLUX2_KLEIN_4B)
    real_download = comfy.Comfy.download

    def download_then_switch(self, file, dest):
        got = real_download(self, file, dest)
        cloud_settings["engines_comfyui"] = "app"
        makers.mode(cloud_settings)  # what any page reading Settings now does
        remote.forget()
        return got

    monkeypatch.setattr(comfy.Comfy, "download", download_then_switch)
    path = engines.make_image("a cat")
    assert path.is_file() and comfy.remote_key(cloud.url) is None


def test_a_job_waiting_for_its_turn_follows_settings_when_its_turn_comes(cloud_settings, cloud, fake_comfy,
                                                                          monkeypatch, no_local_graphics):
    """Another ComfyUI chosen while it waited: it stops, sends nothing, and the cloud computer's key is not taken
    out again for it."""
    from clipfoundry import engines

    monkeypatch.setattr(makers, "_settings", lambda: dict(cloud_settings))  # each read is a copy, like the database's
    fake_comfy.have(catalog.FLUX2_KLEIN_4B)
    got: dict = {}
    remote._turn.acquire()  # noqa: SLF001 - another cloud job has the turn

    def make() -> None:
        try:
            got["path"] = engines.make_image("a cat")
        except EngineError as exc:
            got["error"] = str(exc)

    t = threading.Thread(target=make)
    try:
        t.start()
        time.sleep(0.8)
        cloud_settings["engines_comfyui"] = "app"  # the person chose the ComfyUI app meanwhile
        makers.mode(cloud_settings)
    finally:
        remote._turn.release()  # noqa: SLF001
    t.join(30)
    assert "changed while this waited" in got.get("error", "") and not fake_comfy.prompts
    assert comfy.remote_key(cloud.url) is None


def test_other_pages_never_get_the_cloud_computers_address(cloud_settings, cloud, fake_comfy, monkeypatch):
    """Whoever has the address can use the cloud computer: the words for other pages name it by its graphics card."""
    from clipfoundry import engines
    from clipfoundry.makers import local_engines

    where = urlsplit(cloud.url).hostname
    fake_comfy.have(catalog.FLUX2_KLEIN_4B)
    st = engines.status("image")
    assert st["ready"] and st["engine"] == "ComfyUI on your cloud computer · FLUX.2 klein 4B"  # no graphics card named
    cloud_settings["engines_remote_url"] = "http://127.0.0.1:9"  # nothing there
    makers.forget_found()
    st = engines.status("image")
    assert not st["ready"] and where not in json.dumps(st)
    with pytest.raises(EngineError) as err:
        comfy.use_remote("http://127.0.0.1:9", KEY)
        comfy.Comfy("http://127.0.0.1:9").history("p1")
    assert "did not answer" in str(err.value) and where not in str(err.value)
    # the shorts maker's door keeps saying it is the cloud computer (its pages say so instead of "on this computer")
    cloud_settings["engines_remote_url"] = cloud.url
    makers.forget_found()
    door = local_engines.status("image")
    assert door["ready"] and door["remote"] is True and where not in json.dumps(door)


def test_the_shorts_maker_knows_its_pictures_come_from_the_cloud_computer(cloud_settings, cloud, fake_comfy):
    from clipfoundry.makers import shorts

    fake_comfy.have(catalog.FLUX2_KLEIN_4B)
    shorts._status_cache.clear()  # noqa: SLF001
    view = shorts._engines()  # noqa: SLF001 - what the shorts pages get
    assert view["image"]["ready"] and view["image"]["remote"] is True and view["voice"]["remote"] is False
    shorts._status_cache.clear()  # noqa: SLF001


def test_cloud_jobs_take_turns(monkeypatch):
    from clipfoundry.pipeline.common import Cancelled

    first_in, release = threading.Event(), threading.Event()

    def hold() -> None:
        with remote.turn(lambda: False, None, 60):
            first_in.set()
            release.wait(10)

    t = threading.Thread(target=hold)
    t.start()
    first_in.wait(5)
    said = []
    with pytest.raises(Cancelled):
        with remote.turn(lambda: len(said) > 0, lambda f, m: said.append(m), 60):
            pass
    assert said == ["Waiting for your cloud computer: it is making another picture or clip"]
    with pytest.raises(EngineError, match="busy with another picture or clip"):
        with remote.turn(lambda: False, None, 1):
            pass
    release.set()
    t.join(5)
    with remote.turn(lambda: False, None, 1):  # free again
        pass


# ------------------------------------------------------------------ Settings
@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from clipfoundry import api

    return TestClient(api.app)


APP = {"X-ClipFoundry": "1"}


def test_settings_connects_a_cloud_computer(client, cloud, fake_comfy, monkeypatch):
    from clipfoundry import db

    nvidia_stats(fake_comfy, monkeypatch)
    fake_comfy.have(catalog.FLUX2_KLEIN_4B)
    assert client.post("/api/engines/remote", json={"url": cloud.url}).status_code == 403  # only ClipForge's page
    r = client.post("/api/engines/remote", json={"url": "http://192.168.1.20:8188"}, headers=APP)
    assert r.status_code == 422 and "https://" in r.json()["detail"]
    r = client.post("/api/engines/remote", json={"url": cloud.url + "/", "key": KEY}, headers=APP)
    assert r.status_code == 200
    d = r.json()
    # the page puts this answer straight in its state ("I ran it: check again"): the whole view, trial and all
    assert {"state", "role", "progress"} <= set(d["trial"]) and set(client.get("/api/engines").json()) <= set(d)
    s = db.get_settings()
    assert s["engines_comfyui"] == "remote" and s["engines_remote_url"] == cloud.url and s["engines_remote_key"] == KEY
    rv = d["comfyui"]["remote"]
    assert rv["found"] == cloud.url and rv["gpu"] == "NVIDIA GeForce RTX 4090" and rv["key_set"]
    assert KEY not in json.dumps(d)
    by = {m["id"]: m for m in d["models"]}
    assert by["flux2-klein-4b"]["ready"] and not by["z-image-turbo"]["ready"]
    assert not any(m["can_download"] or m["removable"] for m in d["models"] if m["role"] != "voice")
    assert by["z-image-turbo"]["recommended"] and by["z-image-turbo"]["fit"] == "good"  # for the cloud's 24 GB card
    assert d["roles"]["image"]["ready"] and d["roles"]["image"]["remote"]
    # the key stays when it is left out, and goes when it is emptied
    client.post("/api/engines/remote", json={"url": cloud.url}, headers=APP)
    assert db.get_settings()["engines_remote_key"] == KEY
    d = client.post("/api/engines/remote", json={"url": cloud.url, "key": ""}, headers=APP).json()
    assert db.get_settings()["engines_remote_key"] == "" and not d["comfyui"]["remote"]["found"]
    assert "said no" in d["comfyui"]["remote"]["why"]


def test_a_key_the_keychain_cannot_keep_is_said_plainly(client, cloud, monkeypatch):
    """A Mac whose login Keychain is locked cannot seal the key: Settings says so, and nothing is half saved."""
    from clipfoundry import db, secure

    def locked(text):
        raise secure.SecretError("macOS Keychain could not protect this connection. Unlock your login Keychain.")

    monkeypatch.setattr(secure, "seal", locked)
    r = client.post("/api/engines/remote", json={"url": cloud.url, "key": KEY}, headers=APP)
    assert r.status_code == 422 and "Keychain" in r.json()["detail"]
    s = db.get_settings()
    assert s["engines_remote_url"] == "" and s["engines_comfyui"] != "remote" and s["engines_remote_key"] == ""


def test_only_clipforges_own_page_sets_the_cloud_address_and_key(client, cloud):
    """The general settings route cannot point the key somewhere else (another page could call it)."""
    from clipfoundry import db

    client.post("/api/engines/remote", json={"url": cloud.url, "key": KEY}, headers=APP)
    r = client.put("/api/settings", json={"engines_remote_url": "https://elsewhere.example",
                                          "engines_remote_key": "theirs", "engines_comfyui": "remote"})
    assert r.status_code == 200
    s = db.get_settings()
    assert s["engines_remote_url"] == cloud.url and s["engines_remote_key"] == KEY


def test_a_key_is_only_sent_to_the_address_it_was_typed_for(client, cloud, fake_comfy):
    from clipfoundry import db

    client.post("/api/engines/remote", json={"url": cloud.url, "key": KEY}, headers=APP)
    port = urlsplit(cloud.url).port
    d = client.post("/api/engines/remote", json={"url": cloud.url + "/index.html"}, headers=APP).json()
    assert db.get_settings()["engines_remote_key"] == KEY and not d.get("note")  # the same computer keeps it
    before = len(cloud.seen)
    # the same stand-in by another name: to ClipForge another computer, so it does not get the key
    d = client.post("/api/engines/remote", json={"url": f"http://localhost:{port}"}, headers=APP).json()
    assert db.get_settings()["engines_remote_key"] == "" and "another address" in d["note"]
    assert not d["comfyui"]["remote"]["key_set"] and "said no" in d["comfyui"]["remote"]["why"]
    assert len(cloud.seen) > before and not any(auth for _m, _p, auth in cloud.seen[before:])
    # the same computer name at another port (two tunnels on this computer): another computer, so no key either
    client.post("/api/engines/remote", json={"url": cloud.url, "key": KEY}, headers=APP)
    other = CloudProxy(fake_comfy.url)
    try:
        assert urlsplit(other.url).hostname == urlsplit(cloud.url).hostname
        d = client.post("/api/engines/remote", json={"url": other.url}, headers=APP).json()
        assert db.get_settings()["engines_remote_key"] == "" and "another address" in d["note"]
        assert other.seen and not any(auth for _m, _p, auth in other.seen)
    finally:
        other.stop()


def test_choosing_this_computer_again_forgets_the_cloud_computer(client, cloud, fake_comfy):
    """Its key and its patience stay with it: a ComfyUI on this computer at the same address gets neither."""
    from clipfoundry import db

    client.post("/api/engines/remote", json={"url": cloud.url, "key": KEY}, headers=APP)
    assert comfy.Comfy(cloud.url).remote
    client.put("/api/settings", json={"engines_comfyui": "app", "engines_comfyui_url": cloud.url})
    client.get("/api/engines")
    c = comfy.Comfy(cloud.url)
    assert not c.remote and "Authorization" not in c.headers and comfy.remote_key(cloud.url) is None
    assert db.get_settings()["engines_remote_key"] == KEY  # kept for when the cloud computer is chosen again
    r = client.get("/api/engines/remote/command", params={"model": "flux2-klein-4b"})
    assert r.status_code == 409 and "A cloud computer" in r.json()["detail"]
    assert comfy.remote_key(cloud.url) is None


def test_a_key_that_cannot_be_read_still_stays_with_its_address(client, cloud, fake_comfy, monkeypatch):
    """A locked Keychain cannot open the kept key: Settings still says one is kept, and a new address still drops it
    (or the old key would reach the new address once the Keychain is unlocked)."""
    from clipfoundry import db, secure

    client.post("/api/engines/remote", json={"url": cloud.url, "key": KEY}, headers=APP)

    def locked(text):
        raise secure.SecretError("macOS Keychain is locked.")

    monkeypatch.setattr(secure, "unseal", locked)
    assert db.get_settings()["engines_remote_key"] == ""  # cannot be read right now
    assert client.get("/api/engines").json()["comfyui"]["remote"]["key_set"]  # but it is kept
    port = urlsplit(cloud.url).port
    d = client.post("/api/engines/remote", json={"url": f"http://localhost:{port}"}, headers=APP).json()
    assert "another address" in d["note"] and not db.setting_kept("engines_remote_key")
    monkeypatch.undo()
    assert db.get_settings()["engines_remote_key"] == ""


def test_an_address_clipforge_cannot_keep_whole_is_not_kept_in_part(client, cloud):
    from clipfoundry import db

    client.post("/api/engines/remote", json={"url": cloud.url, "key": KEY}, headers=APP)
    long = "a" * 60 + "." + "b" * 60 + "." + "c" * 60 + "." + "d" * 60 + "." + "e" * 40 + ".example.com"
    assert len(long) <= 300 < len("https://" + long)
    with pytest.raises(EngineError, match="cannot keep that address"):
        remote.normalize(long)
    assert config.validate_settings({"engines_remote_url": "https://" + long}) == {}  # never cut short
    r = client.post("/api/engines/remote", json={"url": long}, headers=APP)
    assert r.status_code == 422
    s = db.get_settings()
    assert s["engines_remote_url"] == cloud.url and s["engines_remote_key"] == KEY
    # whatever the address turns into, Settings keeps all of the change or none of it (never a new address with
    # the old key, or the old address with a new key)
    real = remote.normalize
    try:
        remote.normalize = lambda text: "https://" + "a" * 400
        r = client.post("/api/engines/remote", json={"url": "elsewhere", "key": "new-key"}, headers=APP)
    finally:
        remote.normalize = real
    assert r.status_code == 422
    s = db.get_settings()
    assert s["engines_remote_url"] == cloud.url and s["engines_remote_key"] == KEY


def test_pages_other_sites_could_read_do_not_show_the_cloud_address(client, cloud, fake_comfy):
    """A page on another site that tricks the browser into asking this app (its name pointed at this computer) gets
    neither the address nor the view that names it."""
    client.post("/api/engines/remote", json={"url": cloud.url, "key": KEY}, headers=APP)
    s = client.get("/api/settings").json()
    assert s["engines_remote_url"] == "********" and s["engines_remote_key"] == "********"
    assert cloud.url not in json.dumps(s)
    assert client.get("/api/engines", headers={"Host": "rebound.example:8765"}).status_code == 403
    assert client.get("/api/engines").json()["comfyui"]["remote"]["url"] == cloud.url  # its own page still can
    client.put("/api/settings", json=s)  # a page saving back what it read changes nothing
    assert client.get("/api/engines").json()["comfyui"]["remote"]["url"] == cloud.url


def test_a_key_box_with_only_spaces_or_too_much_says_so():
    with pytest.raises(EngineError, match="only spaces"):
        remote.clean_key("\u3000\xa0")  # spaces that look like nothing: not "remove the key"
    with pytest.raises(EngineError, match="too long"):
        remote.clean_key("k" * (remote.MAX_KEY + 1))
    assert remote.clean_key("") == ""  # Remove key


@pytest.mark.parametrize("key", ["tok\u200ben", "\ufefftoken", "tok\x80en", "tökén", "name:pässword"])
def test_a_key_that_cannot_be_sent_is_refused(key):
    with pytest.raises(EngineError, match="cannot send"):
        remote.clean_key(key)
    assert "engines_remote_key" not in config.validate_settings({"engines_remote_key": key})
    assert remote.clean_key("name:p@ss~w0rd!") == "name:p@ss~w0rd!"


def test_models_are_not_downloaded_into_or_removed_from_the_cloud_computer(client, cloud, fake_comfy):
    from clipfoundry import db

    db.save_settings({"engines_comfyui": "remote", "engines_remote_url": cloud.url, "engines_remote_key": KEY})
    r = client.post("/api/engines/setup", json={"what": "model", "model": "flux2-klein-4b"}, headers=APP)
    assert r.status_code == 409 and "Put it on your cloud computer" in r.json()["detail"]
    r = client.post("/api/engines/remove", json={"what": "model", "model": "flux2-klein-4b"}, headers=APP)
    assert r.status_code == 409 and "stays there" in r.json()["detail"]


def test_settings_gives_the_command_for_a_model(client, cloud, fake_comfy):
    from clipfoundry import db

    db.save_settings({"engines_comfyui": "remote", "engines_remote_url": cloud.url, "engines_remote_key": KEY})
    fake_comfy.models["text_encoders"].append("qwen_3_4b.safetensors")  # already there
    d = client.get("/api/engines/remote/command", params={"model": "flux2-klein-4b"}).json()
    assert d["asked"] and d["name"] == "FLUX.2 klein 4B" and d["where"] == str(fake_comfy.tmp / "app-models")
    assert [f["name"] for f in d["files"]] == ["flux-2-klein-4b.safetensors", "flux2-vae.safetensors"]
    assert "qwen_3_4b" not in d["command"] and KEY not in d["command"]
    assert str(fake_comfy.tmp / "app-models" / "diffusion_models") in d["command"]
    r = client.get("/api/engines/remote/command", params={"model": "wan2.2-ti2v-5b"})
    assert r.status_code == 409 and "use rules" in r.json()["detail"]
    assert client.get("/api/engines/remote/command", params={"model": "wan2.2-ti2v-5b", "agreed": True}).status_code == 200
    assert client.get("/api/engines/remote/command", params={"model": "supertonic-3"}).status_code == 409
    fake_comfy.have(catalog.FLUX2_KLEIN_4B)
    d = client.get("/api/engines/remote/command", params={"model": "flux2-klein-4b"}).json()
    assert d["command"] == "" and d["files"] == []
    cloud.state = "off"  # not reachable: the command finds ComfyUI's folder itself and takes every file
    d = client.get("/api/engines/remote/command", params={"model": "flux2-klein-4b"}).json()
    assert not d["asked"] and len(d["files"]) == 3 and "/workspace/runpod-slim/ComfyUI/models" in d["command"]


def test_the_online_studio_offers_no_cloud_computer(monkeypatch):
    from fastapi import HTTPException

    from clipfoundry.engines import routes

    monkeypatch.setenv("CLIPFOUNDRY_MODE", "cloud")
    for call in (lambda: routes.engines_remote({"url": "https://a-8188.proxy.runpod.net"}),
                 lambda: routes.engines_remote_command("flux2-klein-4b")):
        with pytest.raises(HTTPException) as err:
            call()
        assert err.value.status_code == 404


# ------------------------------------------------------------------ the command, run for real
needs_bash = pytest.mark.skipif(not shutil.which("bash") or not shutil.which("curl"), reason="needs bash and curl")


def tiny_model(srv: FileServer, monkeypatch, blobs: dict[str, bytes]) -> catalog.Model:
    def mf(folder, name, data):
        srv.blobs[f"/repo/resolve/{'a' * 40}/split_files/{folder}/{name}"] = data
        return catalog.ModelFile(folder, name, "repo", "a" * 40, f"split_files/{folder}/{name}", len(data),
                                 hashlib.sha256(data).hexdigest())

    monkeypatch.setattr(catalog, "hf_url", lambda repo, rev, path: f"{srv.url}/{repo}/resolve/{rev}/{path}")
    files = tuple(mf(folder, name, data) for (folder, name), data in
                  ((tuple(k.split("/")), v) for k, v in blobs.items()))
    return dataclasses.replace(catalog.FLUX2_KLEIN_4B, id="tiny", name="Tiny", files=files)


def run(command: str, home: Path, path_env: str | None = None) -> subprocess.CompletedProcess:
    env = {"HOME": str(home), "PATH": path_env or "/usr/local/bin:/usr/bin:/bin", "LANG": "C.UTF-8"}
    return subprocess.run(["bash", "-c", command], capture_output=True, text=True, timeout=120, env=env,
                          cwd=str(home))


@needs_bash
def test_the_command_puts_checked_files_into_comfyuis_folders(tmp_path, monkeypatch):
    srv = FileServer({})
    try:
        m = tiny_model(srv, monkeypatch, {"diffusion_models/m.safetensors": b"m" * 300_000,
                                          "vae/v.safetensors": b"v" * 1000})
        where = tmp_path / "pod" / "ComfyUI" / "models"
        folders = {"diffusion_models": str(where / "diffusion_models"), "vae": str(where / "vae")}
        command = remote.download_command(m, list(m.files), folders)
        out = run(command, tmp_path)
        assert out.returncode == 0, out.stdout + out.stderr
        assert (where / "diffusion_models" / "m.safetensors").read_bytes() == b"m" * 300_000
        assert (where / "vae" / "v.safetensors").read_bytes() == b"v" * 1000
        assert not list(where.rglob("*.part")) and "Done: Tiny is on this cloud computer" in out.stdout
        hits = len(srv.hits)
        out = run(command, tmp_path)  # again: checked, not downloaded again
        assert out.returncode == 0 and len(srv.hits) == hits and out.stdout.count("OK") == 2
        # a stopped download goes on where it stopped
        (where / "vae" / "v.safetensors").unlink()
        (where / "vae" / "v.safetensors.part").write_bytes(b"v" * 400)
        out = run(command, tmp_path)
        assert out.returncode == 0 and (where / "vae" / "v.safetensors").read_bytes() == b"v" * 1000
        assert srv.hits[-1] == (f"/repo/resolve/{'a' * 40}/split_files/vae/v.safetensors", "bytes=400-")
        # a damaged download is deleted, and the person is told to run it again
        (where / "vae" / "v.safetensors").unlink()
        srv.blobs[f"/repo/resolve/{'a' * 40}/split_files/vae/v.safetensors"] = b"x" * 1000
        out = run(command, tmp_path)
        assert "came down damaged and was deleted" in out.stdout and "Something did not work" in out.stdout
        assert not (where / "vae" / "v.safetensors").exists() and not (where / "vae" / "v.safetensors.part").exists()
        # someone else's file of the same name is never replaced
        (where / "vae" / "v.safetensors").write_bytes(b"q" * 1000)
        out = run(command, tmp_path)
        assert "left alone" in out.stdout and (where / "vae" / "v.safetensors").read_bytes() == b"q" * 1000
    finally:
        srv.stop()


@needs_bash
def test_the_command_finds_comfyuis_folder_itself_and_works_with_wget(tmp_path, monkeypatch):
    if not shutil.which("wget"):
        pytest.skip("needs wget")
    srv = FileServer({})
    try:
        m = tiny_model(srv, monkeypatch, {"vae/v.safetensors": b"v" * 2000})
        home_models = tmp_path / "ComfyUI" / "models"
        home_models.mkdir(parents=True)
        command = remote.download_command(m, list(m.files), {})
        tools = tmp_path / "tools"  # a computer without curl
        tools.mkdir()
        for name in ("bash", "wget", "wc", "tr", "cut", "sha256sum", "mkdir", "mv", "rm", "cat"):
            if shutil.which(name):
                (tools / name).symlink_to(shutil.which(name))
        out = run(command, tmp_path, path_env=str(tools))
        assert out.returncode == 0, out.stdout + out.stderr
        assert (home_models / "vae" / "v.safetensors").read_bytes() == b"v" * 2000
        (home_models.parent / "models").rename(home_models.parent / "elsewhere")
        out = run(command, tmp_path, path_env=str(tools))
        assert "could not find ComfyUI's models folder" in out.stdout
    finally:
        srv.stop()


@needs_bash
def test_what_the_cloud_computer_says_cannot_run_in_the_command(tmp_path, monkeypatch):
    """Folder names come from the cloud computer: they are quoted, so a name with shell in it is only a name."""
    srv = FileServer({})
    try:
        m = tiny_model(srv, monkeypatch, {"vae/v.safetensors": b"v" * 100})
        marker = tmp_path / "ran"
        odd = str(tmp_path / f"models'; touch {marker}; echo '$(touch {marker})") + "/vae"
        assert remote._linux_path(odd)  # noqa: SLF001
        out = run(remote.download_command(m, list(m.files), {"vae": odd}), tmp_path)
        assert out.returncode == 0, out.stdout + out.stderr
        assert not marker.exists() and (Path(odd) / "v.safetensors").read_bytes() == b"v" * 100
        assert not remote._linux_path("relative/vae") and not remote._linux_path("/a/../etc")  # noqa: SLF001
        assert not remote._linux_path("/a\nb")  # noqa: SLF001
    finally:
        srv.stop()


def test_the_real_models_command_names_every_pinned_file(monkeypatch):
    m = catalog.WAN22_TI2V_5B
    command = remote.download_command(m, list(m.files), {})
    for f in m.files:
        assert f.sha256 in command and str(f.size) in command and f.pin.url in command
    assert command.startswith("bash <<'CLIPFORGE'\n") and command.endswith("\nCLIPFORGE\n")
    assert "huggingface.co" in command and "/resolve/" in command
