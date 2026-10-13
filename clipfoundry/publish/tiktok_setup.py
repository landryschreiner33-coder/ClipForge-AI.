"""A local form-writing aid, not a TikTok registration, review decision or account connection.

The packet is deliberately assembled from a small allowlist: no settings dump, credentials, account identity,
tokens or owner files can enter it. Public addresses are checked syntactically, never fetched by this helper.
"""
from __future__ import annotations

import io
import ipaddress
import json
import zipfile
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field

from .. import config
from . import tiktok

SOURCES = {
    "Register an app": "https://developers.tiktok.com/docs/en/getting-started-create-an-app",
    "Desktop sign-in": "https://developers.tiktok.com/doc/login-kit-desktop/",
    "Sandbox": "https://developers.tiktok.com/docs/en/add-a-sandbox",
    "App review": "https://developers.tiktok.com/doc/app-review-guidelines/",
    "Posting rules": "https://developers.tiktok.com/doc/content-sharing-guidelines/",
}
DESCRIPTION = ("ClipFoundry is a local-first, single-user desktop video editor. It turns long videos into "
               "captioned vertical clips on the owner's computer. For an eligible TikTok developer app, the "
               "owner signs in with TikTok, previews a clip, and explicitly chooses to send it to their TikTok "
               "inbox or approve a Direct Post. Reuse permission is checked before publishing. This is a "
               "personal desktop tool, not a public multi-user service.")
LIMITATIONS = [
    "TikTok's production review rejects private/personal utility tools. ClipFoundry currently fits that "
    "category; completing these fields does not make it eligible or guarantee approval.",
    "Sandbox is for target-user testing, not Public posts. An unaudited Direct Post requires a private TikTok "
    "account and Only me; up to five users can post in a 24-hour period.",
    "A private TikTok profile cannot offer Everyone. Every TikTok upload still needs a preview, a supported "
    "privacy choice and your approval; there is no standing automatic TikTok permission.",
    "Inbox posting still depends on TikTok approving the app and granting video.upload. Without that, export "
    "the prepared video and caption and post them yourself in TikTok.",
]
CHECKLIST = [
    {"id": "app", "label": "Created the app and selected Desktop in the TikTok developer portal."},
    {"id": "products", "label": "Added Login Kit, Content Posting API and only the permissions used below."},
    {"id": "redirect", "label": "Registered the exact local redirect address in Login Kit Desktop."},
    {"id": "target", "label": "Created a Sandbox, added my own target user and applied its changes."},
    {"id": "credentials", "label": "Saved that Sandbox's client key and secret in ClipFoundry, then connected."},
    {"id": "website", "label": "Published a real website with visible working Terms and Privacy links."},
    {"id": "ownership", "label": "Completed URL ownership verification in TikTok's portal."},
    {"id": "demo", "label": "Recorded the current sandbox flow showing every requested product and permission."},
]
SCOPE_NOTES = {
    "user.info.basic": "Login Kit identifies the connected account and shows its nickname and avatar.",
    "video.upload": "Content Posting API transfers the chosen clip to the owner's TikTok inbox. The owner "
                    "finishes the post in TikTok.",
    "video.publish": "Content Posting API retrieves current creator/privacy options, previews the exact clip "
                     "and posts only after the owner's explicit consent for that post.",
    "video.list": "Display API reads the owner's posted videos and the metrics TikTok returns for feedback. "
                  "It does not read arbitrary users' private data or grant a discovery/search API.",
}


class SetupDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    website: str = Field(default="", max_length=2048)
    terms: str = Field(default="", max_length=2048)
    privacy: str = Field(default="", max_length=2048)
    completed: list[str] = Field(default_factory=list, max_length=len(CHECKLIST))
    mode: str = "inbox"
    read_stats: bool = False


def public_url(value: str) -> str:
    """Reject local placeholders and credential-bearing links without making any network requests."""
    if not value:
        return "Add the real public HTTPS address after you publish this page."
    if any(ord(c) < 33 or ord(c) == 127 for c in value) or "\\" in value:
        return "Use a complete public HTTPS address without spaces or control characters."
    try:
        u = urlsplit(value)
        host = (u.hostname or "").lower().rstrip(".")
        port = u.port
    except ValueError:
        return "This address is not a valid URL."
    if u.scheme != "https" or not host or u.username or u.password or u.query or u.fragment:
        return "Use a public HTTPS page without sign-in details, query parameters or a fragment."
    if port not in (None, 443):
        return "Use the site's normal public HTTPS address."
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        return "Use the website's public domain name, not an IP address."
    if ("." not in host or host == "localhost" or host.endswith((".localhost", ".local", ".internal", ".test"))
            or host in ("example.com", "example.org", "example.net") or host.endswith(".example")):
        return "Use your real published domain; localhost and example addresses cannot be reviewed."
    return ""


def form_packet(settings: dict, redirect: str, draft: SetupDraft | None = None) -> dict:
    if draft is None:
        direct = bool(settings.get("tiktok_direct_post", True))
        inbox = bool(settings.get("tiktok_inbox_upload", True))
        mode = "both" if direct and inbox else "direct" if direct else "inbox"
        draft = SetupDraft(mode=mode, read_stats=bool(settings.get("tiktok_read_stats", True)))
    if draft.mode not in ("inbox", "direct", "both"):
        raise ValueError("Choose Inbox, Direct Post or both.")
    prefs = {"tiktok_direct_post": draft.mode in ("direct", "both"),
             "tiktok_inbox_upload": draft.mode in ("inbox", "both"), "tiktok_read_stats": draft.read_stats}
    scopes = tiktok.scopes(prefs)
    urls = {k: getattr(draft, k).strip() for k in ("website", "terms", "privacy")}
    errors = {k: why for k, value in urls.items() if (why := public_url(value))}
    done = set(draft.completed) & {r["id"] for r in CHECKLIST}
    checklist = [{**row, "completed": row["id"] in done} for row in CHECKLIST]
    products = ["Login Kit (Desktop)", "Content Posting API"]
    if draft.read_stats:
        products.append("Display API")
    review = "\n\n".join([DESCRIPTION, *(f"{s}: {SCOPE_NOTES[s]}" for s in scopes),
                           "All TikTok transfers require the owner's explicit confirmation. Direct Post uses "
                           "fresh creator information, no preselected privacy, interactions off by default, "
                           "commercial disclosure and the relevant TikTok music/branded-content consent.",
                           "Personal-use eligibility is unresolved. No public-service, audit approval, live "
                           "website or successful real-account demo is claimed by this draft."])
    return {
        "name": "ClipFoundry", "category": "Video / video editing (choose the closest option in the portal)",
        "description": DESCRIPTION, "platform": "Desktop", "redirect_uri": redirect,
        "mode": draft.mode, "read_stats": draft.read_stats, "preferences": prefs, "products": products,
        "scopes": scopes, "scope_notes": {s: SCOPE_NOTES[s] for s in scopes}, "urls": urls,
        "url_errors": errors, "url_check": "Format only; reachability, ownership and TikTok approval unverified.",
        "review_explanation": review, "checklist": checklist, "completed_count": len(done),
        "portal_status": "Check TikTok's developer portal; ClipFoundry cannot verify app review or audit status.",
        "limits": LIMITATIONS, "sources": SOURCES,
        "icon": {"width": 1024, "height": 1024, "format": "PNG", "max_bytes": 5 * 1024 * 1024,
                 "dark_url": "/api/publish/tiktok/setup/icon/dark",
                 "light_url": "/api/publish/tiktok/setup/icon/light"},
        "demo_steps": [
            "Use your own Sandbox target user and content you own or have permission to publish.",
            "Show ClipFoundry opening, Connect TikTok, TikTok's consent screen and the returned account nickname.",
            "Preview the exact clip, caption, manual privacy selection, interaction controls and disclosures.",
            "Show the requested inbox or Direct Post flow and its real result; do not present a controlled preview "
            "or fake-platform test as a real integration demo.",
            "If requesting video.list, show the actual returned video metrics and missing values.",
            "Upload one to five demo videos, each no larger than 50 MB. Hide app codes and tokens in the recording.",
        ],
    }


def export_packet(packet: dict) -> bytes:
    invalid = [name for name, value in packet["urls"].items() if value and public_url(value)]
    if invalid:
        raise ValueError("Fix these public HTTPS addresses before downloading: " + ", ".join(invalid) +
                         ". Leave them blank if the pages are not published yet.")
    text = ["ClipFoundry — TikTok app form draft", "", packet["portal_status"], "", *packet["limits"], ""]
    for name in ("name", "category", "platform", "description", "redirect_uri", "review_explanation"):
        text.extend([f"{name.replace('_', ' ').title()}:", str(packet[name]), ""])
    text.extend(["Products: " + ", ".join(packet["products"]), "Scopes: " + ", ".join(packet["scopes"]), ""])
    for name, value in packet["urls"].items():
        text.append(f"{name.title()}: {value or '[add your real published HTTPS page]'}")
    text.extend(["", packet["url_check"], "", "Your checklist (self-reported, not platform verification):"])
    text.extend(f"[{'x' if row['completed'] else ' '}] {row['label']}" for row in packet["checklist"])
    text.extend(["", "Demo recording:", *packet["demo_steps"], "", "Official guides:"])
    text.extend(f"{name}: {url}" for name, url in SOURCES.items())
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("form-draft.txt", "\n".join(text) + "\n")
        z.writestr("form-draft.json", json.dumps(packet, ensure_ascii=False, indent=2) + "\n")
        for theme in ("dark", "light"):
            z.write(config.ROOT_DIR / "design" / "tiktok" / f"app-icon-{theme}.png", f"app-icon-{theme}.png")
        for name in ("index.html", "privacy.html", "terms.html", "site.css"):
            z.write(config.ROOT_DIR / "docs" / "legal" / name, f"website-preview/{name}")
        z.writestr("website-preview/READ-ME.txt", "These are local draft pages, not a deployed website. Review "
                   "the product, contact and legal text before publishing. TikTok expects a real developed "
                   "official website, active visible policy links and verified URL ownership. Hosting these "
                   "files alone does not guarantee eligibility or approval. Never expose ClipFoundry's local "
                   "API, credentials or your data folder as the public website.\n")
    return data.getvalue()
