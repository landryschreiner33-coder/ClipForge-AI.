"""Checks before ClipFoundry fetches a URL it did not write itself.

Autopilot fetches media and signals from URLs that come from data: a signal feed's rows, a discovered source, a
redirect. Such a URL must not be able to make ClipFoundry reach into your own computer or network (a router's admin
page, another app's local API, a cloud metadata address) or read local files through ffmpeg. So:

* Only the expected schemes are used (http/https for downloads; http/https/rtmp/rtmps/srt/rtsp for live capture).
* The host is resolved and every address is checked. URLs that came from data must point to public addresses.
  URLs you typed yourself (a source you added by hand, a stream you configured) may point into your own network,
  because that is where your own recorder or media server lives; link-local, multicast and unspecified addresses
  are never used.
* Downloads follow redirects one hop at a time, checking every hop, and connect to exactly the address that was
  checked (TLS is still verified against the host name), so a DNS answer that changes between the check and the
  connection cannot redirect the request.
* Downloads are bounded: at most `max_bytes`, and a declared size above it is refused before anything is written.
* ffmpeg gets network protocols only (`-protocol_whitelist`), never `file`, `pipe`, `concat` or `data` for a URL.

Public HTTP live capture uses autopilot.stream_access: ffmpeg receives opaque loopback addresses, and this guard
checks and pins each actual upstream resource, including HLS playlists, keys and segments. Standalone ffmpeg_input
only checks the initial stream address; explicitly configured private streams retain that transport limitation.
"""
from __future__ import annotations

import ipaddress
import os
import socket
from pathlib import Path
from typing import Callable
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx

HTTP = ("http", "https")
STREAM = ("http", "https", "rtmp", "rtmps", "srt", "rtsp")
FFMPEG_NETWORK_PROTOCOLS = "http,https,tls,tcp,udp,rtmp,rtmps,rtmpt,rtmpts,rtmpe,srt,rtsp,crypto,httpproxy"
MAX_REDIRECTS = 5
Address = ipaddress.IPv4Address | ipaddress.IPv6Address


class UnsafeUrl(ValueError):
    """The URL may not be fetched (scheme, address, redirect or size)."""


def resolve(host: str) -> list[Address]:
    try:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise UnsafeUrl(f"{host} cannot be resolved ({exc.strerror or exc})") from exc
    out: list[Address] = []
    for info in infos:
        ip = ipaddress.ip_address(str(info[4][0]).split("%")[0])
        if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
            ip = ip.ipv4_mapped
        if ip not in out:
            out.append(ip)
    return out


def allowed(ip: Address, allow_private: bool) -> bool:
    if ip.is_loopback:  # (::1 also counts as "reserved")
        return allow_private
    if ip.is_link_local or ip.is_multicast or ip.is_unspecified or ip.is_reserved:
        return False
    return True if allow_private else ip.is_global


def check(url: str, *, schemes: tuple[str, ...] = HTTP, allow_private: bool = False) -> list[Address]:
    """The checked addresses of `url`'s host; raises UnsafeUrl when the URL may not be fetched."""
    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower()
    if scheme not in schemes:
        raise UnsafeUrl(f"“{scheme or 'no scheme'}” URLs are not used here (allowed: {', '.join(schemes)})")
    if not parts.hostname:
        raise UnsafeUrl("The URL has no host")
    if not allow_private and (parts.username or parts.password):
        raise UnsafeUrl("URLs from feeds may not carry a user name or password")
    addrs = resolve(parts.hostname)
    bad = [str(ip) for ip in addrs if not allowed(ip, allow_private)]
    if bad or not addrs:
        where = "a private, local or special network address" if allow_private is False else "a special address"
        raise UnsafeUrl(f"{parts.hostname} points to {where} ({', '.join(bad) or 'none'}); it is not fetched")
    return addrs


def _pinned(url: str, ip: Address) -> tuple[str, dict, dict]:
    """(URL with the checked address, headers, request extensions) so the connection goes to exactly that address."""
    parts = urlsplit(url)
    host = f"[{ip}]" if ip.version == 6 else str(ip)
    netloc = f"{host}:{parts.port}" if parts.port else host
    headers = {"Host": parts.netloc.rsplit("@", 1)[-1]}
    ext = {"sni_hostname": parts.hostname} if parts.scheme == "https" else {}
    return urlunsplit((parts.scheme, netloc, parts.path or "/", parts.query, "")), headers, ext


def open_checked(client: httpx.Client, url: str, *, allow_private: bool = False,
                 headers: dict[str, str] | None = None, method: str = "GET",
                 data: bytes | None = None) -> httpx.Response:
    """GET `url` (streaming), following redirects one checked hop at a time. The caller closes the response."""
    for _ in range(MAX_REDIRECTS + 1):
        ip = check(url, allow_private=allow_private)[0]
        target, pinned_headers, ext = _pinned(url, ip)
        req = client.build_request(method, target, content=data,
                                   headers={**(headers or {}), **pinned_headers}, extensions=ext)
        resp = client.send(req, stream=True, follow_redirects=False)
        if resp.is_redirect and resp.headers.get("location"):
            resp.close()
            next_url = urljoin(url, resp.headers["location"])
            if urlsplit(next_url).netloc != urlsplit(url).netloc:
                headers = {k: v for k, v in (headers or {}).items()
                           if k.lower() not in ("authorization", "cookie")}
            if resp.status_code == 303 or (resp.status_code in (301, 302) and method == "POST"):
                method, data = "GET", None
            url = next_url
            continue
        return resp
    raise UnsafeUrl(f"More than {MAX_REDIRECTS} redirects")


def get_text(client: httpx.Client, url: str, *, allow_private: bool = False, max_bytes: int = 10 << 20) -> str:
    """A small text document (e.g. a signal feed), size-bounded and address-checked."""
    r = open_checked(client, url, allow_private=allow_private)
    try:
        if r.status_code != 200:
            raise UnsafeUrl(f"The URL answered {r.status_code}")
        body = bytearray()
        for chunk in r.iter_bytes(1 << 16):
            body += chunk
            if len(body) > max_bytes:
                raise UnsafeUrl(f"The document is larger than {max_bytes >> 20} MB")
        return body.decode(r.encoding or "utf-8", "replace")
    finally:
        r.close()


def download(client: httpx.Client, url: str, dst: Path, *, allow_private: bool = False, max_bytes: int,
             accept: Callable[[httpx.Response], None] | None = None,
             progress: Callable[[int, int], None] | None = None,
             cancelled: Callable[[], bool] | None = None) -> int:
    """Download `url` to `dst` (via a .part file, replaced atomically). `accept` may reject the response by raising.
    Returns the number of bytes written; raises UnsafeUrl for a refused address, redirect or size."""
    tmp = dst.with_suffix(dst.suffix + ".part")
    r = open_checked(client, url, allow_private=allow_private)
    try:
        if accept:
            accept(r)
        declared = int(r.headers.get("content-length") or 0)
        if declared > max_bytes:
            raise UnsafeUrl(f"The file is {declared / 1e9:.1f} GB; the limit is {max_bytes / 1e9:.1f} GB")
        done = 0
        with open(tmp, "wb") as fh:
            for chunk in r.iter_bytes(1 << 20):
                if cancelled and cancelled():
                    from .pipeline.common import Cancelled

                    raise Cancelled()
                done += len(chunk)
                if done > max_bytes:
                    raise UnsafeUrl(f"The download passed the {max_bytes / 1e9:.1f} GB limit; stopped")
                fh.write(chunk)
                if progress:
                    progress(done, declared)
        os.replace(tmp, dst)
        return done
    finally:
        r.close()
        tmp.unlink(missing_ok=True)


def ffmpeg_input(url: str, *, allow_private: bool = False) -> list[str]:
    """ffmpeg input arguments for a network stream: the URL checked, and network protocols only."""
    check(url, schemes=STREAM, allow_private=allow_private)
    return ["-protocol_whitelist", FFMPEG_NETWORK_PROTOCOLS, "-i", url]
