"""Keep the ClipForge download page in step with releases.json.

Everything on index.html that belongs to one version is generated from releases.json: the version number and date,
what changed, what was tested, the download links, sizes and checksums, and the version history. Everything else on
the page is ordinary HTML you edit by hand. Standard library only, so any assistant or person can run it:

    python3 download/build.py            # rewrite the generated parts of index.html from releases.json
    python3 download/build.py --check    # exit 1 if releases.json is invalid or index.html is out of date
    python3 download/build.py --verify   # --check, then download every listed file and compare size and SHA-256

See UPDATING.md for the whole procedure. Never edit text between the generated markers by hand. In releases.json,
text may use **bold** and `code`; everything else is shown exactly as written.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import sys
import urllib.request
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
PAGE = HERE / "index.html"
DATA = HERE / "releases.json"
REPO = "https://github.com/landryschreiner33-coder/ClipForge-AI./"
PLATFORMS = ("windows", "mac")
REGION = re.compile(r"(<!-- generated:(?P<name>[a-z-]+) -->)(?P<body>.*?)(<!-- /generated:(?P=name) -->)", re.S)


class Invalid(ValueError):
    pass


def _file(entry: dict, where: str) -> None:
    for key in ("file", "url", "bytes", "sha256", "kind", "requires"):
        if key not in entry:
            raise Invalid(f"{where}: missing {key!r}")
    if not re.fullmatch(r"[A-Za-z0-9._-]+\.(zip|dmg)", entry["file"]):
        raise Invalid(f"{where}: file must be a plain .zip or .dmg name")
    # Only addresses that can never point at other bytes: a release asset or a file at a fixed commit.
    fixed = (rf"{re.escape(REPO)}releases/download/(?!latest/)[A-Za-z0-9._-]+/{re.escape(entry['file'])}"
             rf"|{re.escape(REPO)}raw/[0-9a-f]{{40}}/{re.escape(entry['file'])}")
    if not re.fullmatch(fixed, entry["url"]):
        raise Invalid(f"{where}: url must be this repository's release asset or a file at a full commit, "
                      "ending in the file name (never latest or a branch)")
    if not isinstance(entry["bytes"], int) or entry["bytes"] <= 0:
        raise Invalid(f"{where}: bytes must be the exact file size")
    if not re.fullmatch(r"[0-9a-f]{64}", entry["sha256"]) or len(set(entry["sha256"])) == 1:
        raise Invalid(f"{where}: sha256 must be the file's real 64-digit lower-case SHA-256")


def inline(text: str) -> str:
    """Escape text for the page, allowing only **bold** and `code`."""
    out = html.escape(text, quote=False)
    out = re.sub(r"`([^`]+)`", r"<code>\1</code>", out)
    out = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", out)
    if "**" in out or "`" in out:
        raise Invalid(f"unpaired ** or ` in {text[:60]!r}")
    return out


def _words(value, where: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise Invalid(f"{where}: must be some plain-English text")
    inline(value)


def _lines(value, where: str) -> None:
    if not isinstance(value, list) or not value:
        raise Invalid(f"{where}: must be a list with at least one item")
    for i, item in enumerate(value):
        _words(item, f"{where}[{i}]")


def _release(release: dict, where: str) -> None:
    for key in ("name", "version", "date", "source_commit", "summary", "files"):
        if key not in release:
            raise Invalid(f"{where}: missing {key!r}")
    date.fromisoformat(release["date"])
    if not re.fullmatch(r"[0-9a-f]{40}", release["source_commit"]):
        raise Invalid(f"{where}: source_commit must be a full 40-character commit")
    _words(release["summary"], f"{where}.summary")
    if "changes" in release:
        if not isinstance(release["changes"], list) or not release["changes"]:
            raise Invalid(f"{where}.changes: must be a list with at least one change")
        for i, change in enumerate(release["changes"]):
            if not isinstance(change, dict) or set(change) != {"title", "text"}:
                raise Invalid(f"{where}.changes[{i}]: needs exactly a title and a text")
            _words(change["title"], f"{where}.changes[{i}].title")
            _words(change["text"], f"{where}.changes[{i}].text")
    for key in ("checked", "not_checked"):
        if key in release:
            _lines(release[key], f"{where}.{key}")
    if not release["files"] or set(release["files"]) - set(PLATFORMS):
        raise Invalid(f"{where}: files must be keyed by windows and/or mac")
    for platform, entry in release["files"].items():
        _file(entry, f"{where}.{platform}")


def load() -> dict:
    data = json.loads(DATA.read_text(encoding="utf-8"))
    if data.get("schema") != 2:
        raise Invalid("releases.json: schema must be 2")
    cur = data["current"]
    _release(cur, "current")
    if set(cur["files"]) != set(PLATFORMS):
        raise Invalid("current: needs both a windows and a mac file")
    for key in ("changes", "checked", "not_checked"):
        if key not in cur:
            raise Invalid(f"current: missing {key!r}: every new version says what changed and what was tested")
    previous = data.get("previous", [])
    for i, release in enumerate(previous):
        _release(release, f"previous[{i}]")
    versions = [r["version"] for r in (cur, *previous)]
    if len(set(versions)) != len(versions):
        raise Invalid("releases.json: each version number may appear only once; give the new release its own")
    dates = [r["date"] for r in (cur, *previous)]
    if dates != sorted(dates, reverse=True):
        raise Invalid("releases.json: current must be the newest, and previous must go from newest to oldest")
    if previous and (cur["summary"] == previous[0]["summary"] or cur["changes"] == previous[0].get("changes")):
        raise Invalid("current: summary and changes are copied from the previous version; "
                      "write what changed in this one")
    return data


def mb(n: int) -> str:
    return f"{n / 1_000_000:.1f} MB"


LABEL = {"windows": "Windows", "mac": "Mac"}


def _changes(changes: list[dict]) -> str:
    return "<dl>" + "".join(f"<div><dt>{inline(c['title'])}</dt><dd>{inline(c['text'])}</dd></div>"
                            for c in changes) + "</dl>"


def _items(lines: list[str]) -> str:
    return "<ul>" + "".join(f"<li>{inline(line)}</li>" for line in lines) + "</ul>"


def render(data: dict) -> dict[str, str]:
    cur = data["current"]
    e = html.escape
    version = f'{e(cur["name"])} {e(cur["version"])}'
    released = e(_long_date(cur["date"]))
    title = f"<title>{version} downloads</title>"
    release = (
        f'\n<a class="release" href="#new"><span class="release-tag">Version {e(cur["version"])}</span>'
        f'<span class="release-text">{inline(cur["summary"])}\u00a0<span aria-hidden="true">→</span></span></a>\n')
    new = (
        f'\n<h2 id="new-title">What’s new in version {e(cur["version"])}</h2>\n'
        f'<p class="new-meta">Released {released}. {inline(cur["summary"])}</p>\n'
        f'<div class="more">{_changes(cur["changes"])}</div>\n')
    was_tested = (
        f'\n<h2 id="tested-title">What was tested in version {e(cur["version"])}</h2>\n'
        f'<div class="tested"><div><h3>Checked before release</h3>{_items(cur["checked"])}</div>'
        f'<div><h3>Not checked yet</h3>{_items(cur["not_checked"])}</div></div>\n')
    buttons = []
    for platform in PLATFORMS:
        f = cur["files"][platform]
        buttons.append(
            f'<a class="get-btn" data-os="{platform}" href="{e(f["url"])}">'
            f'<span class="get-os">Download for {LABEL[platform]}</span>'
            f'<span class="get-meta">{e(f["kind"])}, {mb(f["bytes"])}. {e(f["requires"])}</span></a>')
    hero = (
        '\n<div class="get">' + "".join(buttons) + "</div>\n"
        f'<p class="get-note">{version}, released {released}. '
        'Free. <a href="#check">Check your download</a>.</p>\n')
    rows = []
    for platform in PLATFORMS:
        f = cur["files"][platform]
        tested = f.get("tested_url")
        evidence = f'<a href="{e(tested)}">{e(f.get("tested_label", "Test run"))}</a>' if tested else "—"
        rows.append(
            f'<tr><th scope="row">{LABEL[platform]}<span class="cell-sub">{e(f["file"])}</span></th>'
            f'<td>{f["bytes"]:,} bytes</td>'
            f'<td><code class="hash">{f["sha256"]}</code>'
            f'<button type="button" class="copy" data-copy="{f["sha256"]}" hidden>Copy</button></td>'
            f"<td>{evidence}</td></tr>")
    commit = cur["source_commit"]
    checks = (
        '\n<table class="sums"><thead><tr><th scope="col">Download</th><th scope="col">Exact size</th>'
        '<th scope="col">SHA-256</th><th scope="col">Evidence</th></tr></thead><tbody>'
        + "".join(rows) + "</tbody></table>\n"
        f'<p class="small">Both are built from source commit <a href="{REPO}commit/{commit}"><code>{commit[:12]}</code></a>.'
        "</p>\n")
    older = []
    for old in data.get("previous", []):
        links = ", ".join(
            f'<a href="{e(f["url"])}">{LABEL[p]}</a> ({mb(f["bytes"])}, SHA-256 <code>{f["sha256"][:16]}…</code>)'
            for p, f in old["files"].items())
        more = (f'<details class="ver-more"><summary>What changed in {e(old["version"])}</summary>'
                f'{_changes(old["changes"])}</details>') if old.get("changes") else ""
        older.append(
            f'<li><h3>{e(old["name"])} {e(old["version"])}<span class="ver-date">{e(_long_date(old["date"]))}</span>'
            f'</h3><p class="ver-summary">{inline(old["summary"])}</p>{more}'
            f'<p class="ver-files">Download: {links}.</p></li>')
    previous = '\n<ul class="history">' + "".join(older) + "</ul>\n" if older else "\n<p>No older versions.</p>\n"
    win, mac = e(cur["files"]["windows"]["file"]), e(cur["files"]["mac"]["file"])
    how = (
        '\n<div class="how-check">'
        f'<p><b>Windows:</b> open PowerShell in your Downloads folder and run <code>Get-FileHash .\\{win}</code></p>'
        f'<p><b>Mac:</b> open Terminal and run <code>shasum -a 256 ~/Downloads/{mac}</code></p></div>\n')
    return {"title": title, "release": release, "hero": hero, "new": new, "tested": was_tested, "checksums": checks,
            "how-check": how, "older": previous, "version": f"{version}, released {released}"}


def _long_date(iso: str) -> str:
    d = date.fromisoformat(iso)
    return f"{d.strftime('%B')} {d.day}, {d.year}"


def apply(page: str, parts: dict[str, str]) -> str:
    seen = set()

    def swap(m: re.Match) -> str:
        seen.add(m["name"])
        if m["name"] not in parts:
            raise Invalid(f"index.html has an unknown generated block {m['name']!r}")
        return m.group(1) + parts[m["name"]] + m.group(4)

    out = REGION.sub(swap, page)
    if seen != set(parts):
        raise Invalid(f"index.html is missing generated blocks: {sorted(set(parts) - seen)}")
    return out


def verify(data: dict) -> None:
    releases = [data["current"], *data.get("previous", [])]
    checked: dict[str, tuple[int, str]] = {}
    for release in releases:
        for platform, f in release["files"].items():
            if f["url"] in checked:  # the same file listed twice is downloaded once
                if checked[f["url"]] != (f["bytes"], f["sha256"]):
                    raise Invalid(f"{f['url']} is listed twice with different sizes or SHA-256")
                continue
            checked[f["url"]] = (f["bytes"], f["sha256"])
            digest, size = hashlib.sha256(), 0
            request = urllib.request.Request(f["url"], headers={"User-Agent": "clipforge-download-check"})
            with urllib.request.urlopen(request, timeout=60) as response:
                while chunk := response.read(1 << 20):
                    digest.update(chunk)
                    size += len(chunk)
            ok = size == f["bytes"] and digest.hexdigest() == f["sha256"]
            print(f"{'OK  ' if ok else 'FAIL'} {release['version']} {platform}: {size:,} bytes {digest.hexdigest()}")
            if not ok:
                raise Invalid(f"{f['url']} does not match releases.json")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="only check; change nothing")
    ap.add_argument("--verify", action="store_true", help="check, then download and hash every listed file")
    a = ap.parse_args()
    try:
        data = load()
        page = PAGE.read_text(encoding="utf-8")
        new = apply(page, render(data))
        if a.check or a.verify:
            if new != page:
                raise Invalid("index.html is out of date: run python3 download/build.py and commit both files")
            if a.verify:
                verify(data)
            print("download page is in step with releases.json")
        elif new != page:
            PAGE.write_text(new, encoding="utf-8")
            print("index.html updated from releases.json")
        else:
            print("index.html already up to date")
    except (Invalid, ValueError, KeyError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
