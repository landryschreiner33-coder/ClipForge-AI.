"""Local stand-ins for the Google (YouTube Data API) and TikTok (Content Posting API) servers used by the tests."""
from __future__ import annotations

import base64
import hashlib
import json
import re
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse


class _Server:
    def __init__(self) -> None:
        self.log: list[tuple[str, str]] = []
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a) -> None:
                pass

            def _body(self) -> bytes:
                n = int(self.headers.get("Content-Length") or 0)
                return self.rfile.read(n) if n else b""

            def _send(self, code: int, body: object = None, headers: dict | None = None) -> None:
                data = b"" if body is None else (body if isinstance(body, bytes) else json.dumps(body).encode())
                self.send_response(code)
                for k, v in (headers or {}).items():
                    self.send_header(k, v)
                if body is not None and not isinstance(body, bytes):
                    self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self) -> None:  # noqa: N802
                owner.log.append(("GET", self.path))
                owner.handle(self, "GET", b"")

            def do_POST(self) -> None:  # noqa: N802
                body = self._body()
                owner.log.append(("POST", self.path))
                owner.handle(self, "POST", body)

            def do_PUT(self) -> None:  # noqa: N802
                body = self._body()
                owner.log.append(("PUT", self.path))
                owner.handle(self, "PUT", body)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()

    def handle(self, h, method: str, body: bytes) -> None:  # pragma: no cover - overridden
        raise NotImplementedError


class FakeGoogle(_Server):
    """OAuth token/revoke endpoints, channels.list, videos.list and the resumable videos.insert upload."""

    def __init__(self) -> None:
        self.codes: dict[str, str] = {}          # code -> PKCE challenge it was issued for
        self.access = ""
        self.refresh_token = "refresh-" + secrets.token_hex(4)
        self.revoked = False
        self.grants: list[str] = []
        self.sessions: dict[str, dict] = {}
        self.videos: dict[str, dict] = {}
        self.fail_puts = 0                       # answer this many chunk uploads with 503
        self.rate_limit_puts = 0                 # answer this many chunk uploads with 429 (+ Retry-After if set)
        self.retry_after = ""
        self.drop_final_reply = False            # create the video on the last chunk, but lose the answer
        self.expire_sessions = False             # ...and forget the upload session right away
        self.hide_uploads = False                # new uploads do not show in the channel's uploads list yet
        self.lock_private = False                # behave like an unaudited API project
        self.quota_exceeded = False
        self.chunk_delay = 0.0
        self.analytics: dict | None = None      # a YouTube Analytics row for every video, or None = no data yet
        self.analytics_disabled = False         # the Analytics API is not enabled in the Cloud project
        self.default_statistics: dict | None = None  # statistics given to every new video (browser tests)
        self.scope = ("https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube.readonly "
                      "https://www.googleapis.com/auth/yt-analytics.readonly")
        self.api_key = "test-api-key"
        self.catalog: dict[str, dict] = {}       # public videos of other channels (discovery)
        self.popular: list[str] = []             # the mostPopular chart, in order
        self.search_quota_exceeded = False
        self.calls: dict[str, int] = {}
        super().__init__()

    def add_video(self, vid: str, title: str, channel: str = "UCother0000000000", views: int | None = 1000,
                  likes: int | None = 50, comments: int | None = 5, age_hours: float = 10.0, duration: str = "PT25M",
                  live_viewers: int | None = None, license_: str = "youtube", category: str = "22",
                  made_for_kids: bool = False, tags: list | None = None, description: str = "") -> dict:
        import datetime as _dt
        published = (_dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(hours=age_hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
        stats = {k: str(v) for k, v in (("viewCount", views), ("likeCount", likes), ("commentCount", comments))
                 if v is not None}
        item = {"id": vid, "snippet": {"title": title, "channelId": channel, "channelTitle": f"Channel {channel[-4:]}",
                                       "publishedAt": published, "categoryId": category, "tags": tags or [],
                                       "description": description,
                                       "liveBroadcastContent": "live" if live_viewers is not None else "none"},
                "statistics": stats, "contentDetails": {"duration": duration},
                "status": {"license": license_, "madeForKids": made_for_kids, "privacyStatus": "public"}}
        if live_viewers is not None:
            item["liveStreamingDetails"] = {"concurrentViewers": str(live_viewers)}
        self.catalog[vid] = item
        return item

    def approve(self, auth_url: str) -> str:
        """What happens in the browser: the user signs in on Google's page and approves; Google issues a code."""
        q = parse_qs(urlparse(auth_url).query)
        assert q["code_challenge_method"] == ["S256"]
        code = "code-" + secrets.token_hex(4)
        self.codes[code] = q["code_challenge"][0]
        return code

    def _authorized(self, h) -> bool:
        if parse_qs(urlparse(h.path).query).get("key") == [self.api_key]:
            return True
        return h.headers.get("Authorization") == f"Bearer {self.access}" and bool(self.access)

    def handle(self, h, method: str, body: bytes) -> None:
        u = urlparse(h.path)
        q = parse_qs(u.query)
        if u.path == "/o/oauth2/v2/auth":  # a browser test: the user approves on Google's page
            code = self.approve(h.path)
            return h._send(302, b"", {"Location": f"{q['redirect_uri'][0]}?state={q['state'][0]}&code={code}"})
        if u.path == "/token":
            form = {k: v[0] for k, v in parse_qs(body.decode()).items()}
            self.grants.append(form["grant_type"])
            if form.get("client_id") != "cid.apps.googleusercontent.com" or form.get("client_secret") != "csecret":
                return h._send(401, {"error": "invalid_client"})
            if form["grant_type"] == "authorization_code":
                challenge = self.codes.pop(form.get("code", ""), None)
                verifier = form.get("code_verifier", "")
                calc = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
                if challenge is None or calc != challenge:
                    return h._send(400, {"error": "invalid_grant", "error_description": "Bad code or verifier"})
                self.access = "access-" + secrets.token_hex(4)
                return h._send(200, {"access_token": self.access, "expires_in": 3599, "token_type": "Bearer",
                                     "refresh_token": self.refresh_token, "scope": self.scope})
            if form["grant_type"] == "refresh_token":
                if self.revoked or form.get("refresh_token") != self.refresh_token:
                    return h._send(400, {"error": "invalid_grant", "error_description": "Token has been expired or revoked."})
                self.access = "access-" + secrets.token_hex(4)
                return h._send(200, {"access_token": self.access, "expires_in": 3599, "scope": self.scope})
        if u.path == "/revoke":
            self.revoked = True
            return h._send(200, {})
        self.calls[u.path] = self.calls.get(u.path, 0) + 1
        if u.path == "/youtube/v3/channels":
            if not self._authorized(h):
                return h._send(401, {"error": {"code": 401, "message": "Invalid Credentials"}})
            if "id" in q:
                cid = q["id"][0]
                return h._send(200, {"items": [{"id": cid, "contentDetails": {"relatedPlaylists": {
                    "uploads": "UU" + cid[2:]}}}]})
            return h._send(200, {"items": [{"id": "UC123", "snippet": {"title": "Test Channel", "thumbnails": {
                "default": {"url": "https://yt3.example/avatar.jpg"}}}}]})
        if u.path == "/youtube/v3/playlistItems":
            if not self._authorized(h):
                return h._send(401, {"error": {"code": 401, "message": "Invalid Credentials"}})
            channel = "UC" + q["playlistId"][0][2:]
            ids = [v for v, it in self.catalog.items() if it["snippet"]["channelId"] == channel]
            items = [{"contentDetails": {"videoId": v}} for v in ids]
            if channel == "UC123" and not self.hide_uploads:  # the connected channel's own uploads, newest first
                items = [{"snippet": {"title": v["snippet"]["title"], "publishedAt": v["uploaded_at"],
                                      "resourceId": {"videoId": vid}}, "contentDetails": {"videoId": vid}}
                         for vid, v in reversed(self.videos.items())] + items
            return h._send(200, {"items": items})
        if u.path == "/youtube/v3/search":
            if not self._authorized(h):
                return h._send(401, {"error": {"code": 401, "message": "Invalid Credentials"}})
            if self.search_quota_exceeded:
                return h._send(403, {"error": {"code": 403, "message": "quota", "errors": [{"reason": "quotaExceeded"}]}})
            words = q.get("q", [""])[0].lower().split()
            live = q.get("eventType") == ["live"]
            hits = [it for it in self.catalog.values()
                    if (it["snippet"]["liveBroadcastContent"] == "live") == live
                    and (live or all(w in it["snippet"]["title"].lower() for w in words))]
            hits.sort(key=lambda it: -int(it["statistics"].get("viewCount", 0)))
            n = int(q.get("maxResults", ["25"])[0])
            return h._send(200, {"items": [{"id": {"kind": "youtube#video", "videoId": it["id"]}} for it in hits[:n]]})
        if u.path == "/youtube/v3/videos":
            if not self._authorized(h):
                return h._send(401, {"error": {"code": 401, "message": "Invalid Credentials"}})
            if q.get("chart") == ["mostPopular"]:
                return h._send(200, {"items": [self.catalog[v] for v in self.popular if v in self.catalog]})
            ids = q["id"][0].split(",")
            if len(ids) > 1 or ids[0] in self.catalog:
                return h._send(200, {"items": [self.catalog[v] for v in ids if v in self.catalog]})
            v = self.videos.get(ids[0])
            items = [{"id": v["id"], "status": v["status"], "processingDetails": {"processingStatus": "succeeded"},
                      "statistics": v.get("statistics", {})}] if v else []
            return h._send(200, {"items": items})
        if u.path == "/v2/reports":
            if not self._authorized(h):
                return h._send(401, {"error": {"code": 401, "message": "Invalid Credentials"}})
            if self.analytics_disabled:
                return h._send(403, {"error": {"code": 403, "message": "YouTube Analytics API has not been used",
                                               "errors": [{"reason": "accessNotConfigured"}]}})
            assert q["ids"] == ["channel==MINE"] and q["filters"][0].startswith("video==")
            names = q["metrics"][0].split(",")
            headers = [{"name": n, "columnType": "METRIC"} for n in names]
            rows = [[self.analytics[n] for n in names]] if self.analytics else []
            return h._send(200, {"kind": "youtubeAnalytics#resultTable", "columnHeaders": headers, "rows": rows})
        if u.path == "/upload/youtube/v3/videos" and method == "POST":
            if not self._authorized(h):
                return h._send(401, {"error": {"code": 401, "message": "Invalid Credentials"}})
            if self.quota_exceeded:
                return h._send(403, {"error": {"code": 403, "message": "quota", "errors": [{"reason": "quotaExceeded"}]}})
            assert q["uploadType"] == ["resumable"]
            sid = secrets.token_hex(6)
            self.sessions[sid] = {"meta": json.loads(body), "size": int(h.headers["X-Upload-Content-Length"]),
                                  "data": bytearray(), "type": h.headers["X-Upload-Content-Type"]}
            return h._send(200, {}, {"Location": f"{self.url}/upload-session/{sid}"})
        m = re.match(r"/upload-session/(\w+)", u.path)
        if m and method == "PUT":
            s = self.sessions.get(m.group(1))
            if s is None:  # the session expired (or was completed long ago)
                return h._send(404, {"error": {"code": 404, "message": "upload session not found"}})
            if not self._authorized(h):
                return h._send(401, {"error": {"code": 401, "message": "Invalid Credentials"}})
            rng = h.headers["Content-Range"]
            if rng.startswith("bytes */"):
                return self._progress(h, s)
            if self.chunk_delay:
                time.sleep(self.chunk_delay)
            if self.fail_puts > 0:
                self.fail_puts -= 1
                return h._send(503, {"error": {"code": 503, "message": "backend error"}})
            if self.rate_limit_puts > 0:
                self.rate_limit_puts -= 1
                return h._send(429, {"error": {"code": 429, "message": "rate limited",
                                               "errors": [{"reason": "rateLimitExceeded"}]}},
                               {"Retry-After": self.retry_after} if self.retry_after else None)
            a, b, total = map(int, re.match(r"bytes (\d+)-(\d+)/(\d+)", rng).groups())
            assert a == len(s["data"]) and b - a + 1 == len(body) and total == s["size"]
            s["data"] += body
            if self.drop_final_reply and len(s["data"]) >= s["size"]:
                self._progress(None, s)  # YouTube creates the video...
                if self.expire_sessions:
                    del self.sessions[m.group(1)]
                h.close_connection = True  # ...but its answer never arrives
                return None
            return self._progress(h, s)
        return h._send(404, {"error": {"code": 404, "message": f"no route {u.path}"}})

    def _progress(self, h, s: dict) -> None:
        if len(s["data"]) < s["size"]:
            headers = {"Range": f"bytes=0-{len(s['data']) - 1}"} if s["data"] else {}
            return h._send(308, None, headers)
        vid = "vid" + secrets.token_hex(4)
        wanted = s["meta"]["status"]["privacyStatus"]
        status = {"uploadStatus": "uploaded", "privacyStatus": "private" if self.lock_private else wanted,
                  "selfDeclaredMadeForKids": s["meta"]["status"]["selfDeclaredMadeForKids"]}
        if s["meta"]["status"].get("publishAt"):
            assert wanted == "private"  # YouTube only accepts publishAt on private videos
            status["publishAt"] = s["meta"]["status"]["publishAt"]
        video = {"id": vid, "snippet": s["meta"]["snippet"], "status": status, "bytes": bytes(s["data"]),
                 "uploaded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        if self.default_statistics:
            video["statistics"] = dict(self.default_statistics)
        self.videos[vid] = video
        if h is None:
            return None
        return h._send(200, {k: v for k, v in video.items() if k not in ("bytes", "uploaded_at")})


class FakeTikTok(_Server):
    """TikTok v2 OAuth, user info, creator_info, Direct Post / inbox init, chunk upload and status fetch."""

    MB = 1024 * 1024

    def __init__(self) -> None:
        self.codes: dict[str, tuple[str, str]] = {}  # code -> (hex challenge, redirect_uri)
        self.access = ""
        self.refresh_token = "rft-" + secrets.token_hex(4)
        self.scope = "user.info.basic,video.upload,video.publish,video.list"
        self.grants: list[str] = []
        self.revoked = False
        self.inits: list[dict] = []
        self.uploads: dict[str, dict] = {}
        self.status_calls: dict[str, int] = {}
        self.init_error = ""        # e.g. unaudited_client_can_only_post_to_private_accounts
        self.init_status = 403
        self.retry_after = ""       # sent as Retry-After with every error answer
        self.rate_limit_chunks = 0  # answer this many chunk uploads with 429
        self.rate_limit_status = 0  # answer this many status fetches with 429 rate_limit_exceeded
        self.fail_reason = ""       # makes status/fetch report FAILED
        self.duet_disabled = True
        self.stats: dict[str, dict] = {}   # public post id -> video.query fields
        self.authors: dict[str, tuple[str, str]] = {}  # public video id -> (author user name, display name): oEmbed
        self.default_stats: dict | None = None
        super().__init__()

    def approve(self, auth_url: str) -> str:
        q = parse_qs(urlparse(auth_url).query)
        assert q["code_challenge_method"] == ["S256"] and q["response_type"] == ["code"]
        assert re.fullmatch(r"[0-9a-f]{64}", q["code_challenge"][0])  # TikTok desktop: hex-encoded SHA-256
        code = "tcode-" + secrets.token_hex(4)
        self.codes[code] = (q["code_challenge"][0], q["redirect_uri"][0])
        return code

    def _ok(self, h, data: dict, code: int = 200) -> None:
        h._send(code, {"data": data, "error": {"code": "ok", "message": "", "log_id": "log1"}})

    def _err(self, h, code: str, status: int = 400) -> None:
        h._send(status, {"data": {}, "error": {"code": code, "message": code, "log_id": "log1"}},
                {"Retry-After": self.retry_after} if self.retry_after else None)

    def handle(self, h, method: str, body: bytes) -> None:
        u = urlparse(h.path)
        if method == "PUT" and u.path.startswith("/upload/"):
            return self.handle_upload(h, body)
        if u.path == "/oembed":  # TikTok's public embed API: the real author of a video, found by its number
            m = re.search(r"/video/(\d+)", parse_qs(u.query).get("url", [""])[0])
            vid = m.group(1) if m else ""
            if vid not in self.authors:
                return h._send(400, {"code": 400, "message": "Something went wrong"})
            uid, name = self.authors[vid]
            return h._send(200, {"version": "1.0", "type": "video", "title": "A video", "author_name": name,
                                 "author_url": f"https://www.tiktok.com/@{uid}", "author_unique_id": uid,
                                 "embed_product_id": vid, "embed_type": "video", "provider_name": "TikTok"})
        if u.path == "/v2/auth/authorize/":  # a browser test: the user approves on TikTok's page
            q = parse_qs(u.query)
            code = self.approve(h.path)
            return h._send(302, b"", {"Location": f"{q['redirect_uri'][0]}?state={q['state'][0]}&code={code}"
                                                  f"&scopes={q['scope'][0]}"})
        if u.path == "/v2/oauth/token/":
            form = {k: v[0] for k, v in parse_qs(body.decode()).items()}
            self.grants.append(form["grant_type"])
            if form.get("client_key") != "tkkey" or form.get("client_secret") != "tksecret":
                return h._send(200, {"error": "invalid_client", "error_description": "bad client"})
            if form["grant_type"] == "authorization_code":
                challenge, redirect = self.codes.pop(form.get("code", ""), ("", ""))
                calc = hashlib.sha256(form.get("code_verifier", "").encode()).hexdigest()
                if not challenge or calc != challenge or redirect != form.get("redirect_uri"):
                    return h._send(200, {"error": "invalid_grant", "error_description": "bad code/verifier"})
            elif self.revoked or form.get("refresh_token") != self.refresh_token:
                return h._send(200, {"error": "invalid_grant", "error_description": "expired"})
            self.access = "act." + secrets.token_hex(6)
            return h._send(200, {"access_token": self.access, "expires_in": 86400, "open_id": "open-1",
                                 "refresh_expires_in": 31536000, "refresh_token": self.refresh_token,
                                 "scope": self.scope, "token_type": "Bearer"})
        if u.path == "/v2/oauth/revoke/":
            self.revoked = True
            return h._send(200, {})
        if h.headers.get("Authorization") != f"Bearer {self.access}" or not self.access:
            return self._err(h, "access_token_invalid", 401)
        if u.path == "/v2/user/info/":
            return self._ok(h, {"user": {"open_id": "open-1", "display_name": "Test Creator",
                                         "avatar_url": "https://p16.example/avatar.jpg"}})
        if u.path == "/v2/post/publish/creator_info/query/":
            return self._ok(h, {"creator_avatar_url": "https://p16.example/avatar.jpg", "creator_username": "testcreator",
                                "creator_nickname": "Test Creator", "comment_disabled": False,
                                "duet_disabled": self.duet_disabled, "stitch_disabled": False,
                                "max_video_post_duration_sec": 600,
                                "privacy_level_options": ["PUBLIC_TO_EVERYONE", "MUTUAL_FOLLOW_FRIENDS", "SELF_ONLY"]})
        if u.path in ("/v2/post/publish/video/init/", "/v2/post/publish/inbox/video/init/"):
            req = json.loads(body)
            self.inits.append({"path": u.path, **req})
            if self.init_error:
                return self._err(h, self.init_error, self.init_status)
            src = req["source_info"]
            size, chunk, total = src["video_size"], src["chunk_size"], src["total_chunk_count"]
            if size < 5 * self.MB:
                assert chunk == size and total == 1
            else:
                assert 5 * self.MB <= chunk <= 64 * self.MB and total == size // chunk
            pid = "v_pub_file~" + secrets.token_hex(4)
            self.uploads[pid] = {"size": size, "data": bytearray(), "inbox": "inbox" in u.path,
                                 "privacy": (req.get("post_info") or {}).get("privacy_level", "")}
            return self._ok(h, {"publish_id": pid, "upload_url": f"{self.url}/upload/{pid}"})
        if u.path == "/v2/video/query/":
            assert "view_count" in parse_qs(u.query)["fields"][0]
            ids = json.loads(body)["filters"]["video_ids"]
            for i in ids:
                if self.default_stats and i not in self.stats:
                    self.stats[i] = dict(self.default_stats)
            return self._ok(h, {"videos": [{"id": i, **self.stats[i]} for i in ids if i in self.stats],
                                "cursor": 0, "has_more": False})
        if u.path == "/v2/post/publish/status/fetch/":
            if self.rate_limit_status > 0:
                self.rate_limit_status -= 1
                return self._err(h, "rate_limit_exceeded", 429)
            pid = json.loads(body)["publish_id"]
            up = self.uploads[pid]
            n = self.status_calls[pid] = self.status_calls.get(pid, 0) + 1
            if len(up["data"]) < up["size"] or n < 2:
                return self._ok(h, {"status": "PROCESSING_UPLOAD", "uploaded_bytes": len(up["data"])})
            if self.fail_reason:
                return self._ok(h, {"status": "FAILED", "fail_reason": self.fail_reason})
            if up["inbox"]:
                return self._ok(h, {"status": "SEND_TO_USER_INBOX"})
            ids = [7300000000000000001] if up["privacy"] == "PUBLIC_TO_EVERYONE" else []
            return self._ok(h, {"status": "PUBLISH_COMPLETE", "publicaly_available_post_id": ids})
        return self._err(h, "not_found", 404)

    def handle_upload(self, h, body: bytes) -> None:
        pid = urlparse(h.path).path.split("/")[-1]
        up = self.uploads[pid]
        if self.rate_limit_chunks > 0:
            self.rate_limit_chunks -= 1
            return h._send(429, None, {"Retry-After": self.retry_after} if self.retry_after else None)
        a, b, total = map(int, re.match(r"bytes (\d+)-(\d+)/(\d+)", h.headers["Content-Range"]).groups())
        assert a == len(up["data"]) and b - a + 1 == len(body) and total == up["size"]
        assert h.headers["Content-Type"] == "video/mp4"
        up["data"] += body
        h._send(201 if len(up["data"]) == up["size"] else 206, None)



class FakeTavily(_Server):
    """Tavily's search endpoint: web results (title, link, snippet), filtered by the requested domains."""

    def __init__(self) -> None:
        self.key = "tvly-test-key"
        self.pages: list[dict] = []
        self.requests: list[dict] = []
        self.fail = 0                            # answer this many searches with 500
        super().__init__()

    def add(self, url: str, title: str, score: float = 0.9, published_date: str | None = None) -> None:
        self.pages.append({"url": url, "title": title, "content": f"{title} ...", "score": score,
                           "published_date": published_date})

    def handle(self, h, method: str, body: bytes) -> None:
        if urlparse(h.path).path != "/search" or method != "POST":
            return h._send(404, {"detail": "not found"})
        if h.headers.get("Authorization") != f"Bearer {self.key}":
            return h._send(401, {"detail": {"error": "Unauthorized: missing or invalid API key."}})
        req = json.loads(body or b"{}")
        self.requests.append(req)
        if self.fail > 0:
            self.fail -= 1
            return h._send(500, {"detail": {"error": "Internal error"}})
        domains = req.get("include_domains") or []
        words = [w for w in re.findall(r"\w+", str(req.get("query", "")).lower()) if len(w) > 2]
        hits = [p for p in self.pages if (not domains or any(d in p["url"] for d in domains))
                and any(w in p["title"].lower() for w in words)]
        return h._send(200, {"query": req.get("query"), "results": hits[: int(req.get("max_results") or 5)],
                             "response_time": 0.01})


class FakeCommons(_Server):
    """Wikimedia Commons' MediaWiki API (search of video files with their license metadata) and its file server."""

    def __init__(self) -> None:
        self.pages: list[dict] = []
        self.files: dict[str, tuple[bytes, str]] = {}
        self.user_agents: list[str] = []
        super().__init__()

    def add(self, name: str, title: str, license_: str, license_name: str, artist: str = "Jane Doe",
            data: bytes = b"", mime: str = "video/mp4", length: float | None = 1800.0, restrictions: str = "",
            attribution_required: bool = True) -> dict:
        url = f"{self.url}/files/{name}"
        self.files[name] = (data or b"x" * 1000, mime)
        meta = [{"name": "length", "value": length}] if length is not None else []
        page = {"pageid": 1000 + len(self.pages), "ns": 6, "title": f"File:{name}", "index": len(self.pages) + 1,
                "imageinfo": [{"url": url, "descriptionurl": f"{self.url}/wiki/File:{name}",
                               "size": len(self.files[name][0]), "mime": mime, "metadata": meta,
                               "extmetadata": {
                                   "License": {"value": license_}, "LicenseShortName": {"value": license_name},
                                   "LicenseUrl": {"value": "https://creativecommons.org/licenses/by/4.0"},
                                   "Artist": {"value": f"<a href=\"https://example.org\">{artist}</a>"},
                                   "AttributionRequired": {"value": "true" if attribution_required else "false"},
                                   "Restrictions": {"value": restrictions}, "ObjectName": {"value": title}}}]}
        self.pages.append(page)
        return page

    def handle(self, h, method: str, body: bytes) -> None:
        u = urlparse(h.path)
        q = parse_qs(u.query)
        if u.path == "/w/api.php":
            self.user_agents.append(h.headers.get("User-Agent") or "")
            words = [w for w in re.findall(r"\w+", q.get("gsrsearch", [""])[0].lower())
                     if len(w) > 2 and w not in ("filetype", "video")]
            hits = [p for p in self.pages if any(w in p["imageinfo"][0]["extmetadata"]["ObjectName"]["value"].lower()
                                                 for w in words)]
            return h._send(200, {"batchcomplete": True, "query": {"pages": hits}})
        m = re.match(r"/files/(.+)$", u.path)
        if m and m.group(1) in self.files:
            data, mime = self.files[m.group(1)]
            return h._send(200, data, {"Content-Type": mime})
        return h._send(404, {"error": "not found"})
