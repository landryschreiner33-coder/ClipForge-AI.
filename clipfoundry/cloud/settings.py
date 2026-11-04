"""Cloud deployment settings, read from the environment only (never from the database or a request).

Every value that decides who may sign in or where the server is reachable is configured by the operator.
`problems()` lists what is missing or unsafe; the app refuses to start in cloud mode while that list is not empty.
"""
from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit

MODE_ENV = "CLIPFOUNDRY_MODE"
PRIMARY_WORKSPACE = "local"  # the desktop data's workspace; the first configured owner signs in to it


def enabled() -> bool:
    return os.environ.get(MODE_ENV, "").strip().lower() == "cloud"


@dataclass(frozen=True)
class Owner:
    issuer: str
    subject: str

    @property
    def key(self) -> str:
        return f"{self.issuer}|{self.subject}"


@dataclass(frozen=True)
class CloudSettings:
    public_url: str
    allowed_hosts: tuple[str, ...]
    oidc_issuer: str
    oidc_client_id: str
    oidc_client_secret: str
    owners: tuple[Owner, ...]
    secret_key_file: str
    session_hours: float
    idle_hours: float
    trusted_proxies: tuple[str, ...]
    max_upload_bytes: int
    storage_limit_bytes: int
    signup: str

    @property
    def origin(self) -> str:
        p = urlsplit(self.public_url)
        return f"{p.scheme}://{p.netloc}"

    @property
    def secure_cookies(self) -> bool:
        return urlsplit(self.public_url).scheme == "https"


def _list(name: str) -> tuple[str, ...]:
    return tuple(x.strip() for x in os.environ.get(name, "").split(",") if x.strip())


def _number(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    try:
        return float(raw) if raw else default
    except ValueError:
        return float("nan")


def _gigabytes(name: str, default: float) -> int:
    """Bytes from a size in GB; -1 for an unreadable or non-positive value (reported by `problems`)."""
    value = _number(name, default)
    return int(value * (1 << 30)) if value == value and value > 0 else -1


def _secret(name: str) -> str:
    """A secret from NAME_FILE (preferred: not visible in the process environment) or NAME."""
    path = os.environ.get(f"{name}_FILE", "").strip()
    if path:
        try:
            return Path(path).read_text(encoding="utf-8").strip()
        except OSError:
            return ""
    return os.environ.get(name, "").strip()


def _owners() -> tuple[Owner, ...]:
    out = []
    for item in _list("CLIPFOUNDRY_OWNER_SUBJECTS"):
        issuer, sep, subject = item.rpartition("|")
        if sep and issuer and subject:
            out.append(Owner(issuer.strip(), subject.strip()))
        else:  # a bare subject belongs to the configured issuer
            out.append(Owner(os.environ.get("CLIPFOUNDRY_OIDC_ISSUER", "").strip().rstrip("/"), item))
    return tuple(out)


@lru_cache(maxsize=1)
def current() -> CloudSettings:
    public = os.environ.get("CLIPFOUNDRY_PUBLIC_URL", "").strip().rstrip("/")
    host = urlsplit(public).hostname or ""
    return CloudSettings(
        public_url=public,
        allowed_hosts=_list("CLIPFOUNDRY_ALLOWED_HOSTS") or ((host,) if host else ()),
        oidc_issuer=os.environ.get("CLIPFOUNDRY_OIDC_ISSUER", "").strip().rstrip("/"),
        oidc_client_id=os.environ.get("CLIPFOUNDRY_OIDC_CLIENT_ID", "").strip(),
        oidc_client_secret=_secret("CLIPFOUNDRY_OIDC_CLIENT_SECRET"),
        owners=_owners(),
        secret_key_file=os.environ.get("CLIPFOUNDRY_SECRET_KEY_FILE", "").strip(),
        session_hours=_number("CLIPFOUNDRY_SESSION_HOURS", 12.0),
        idle_hours=_number("CLIPFOUNDRY_SESSION_IDLE_HOURS", 4.0),
        trusted_proxies=_list("CLIPFOUNDRY_TRUSTED_PROXIES") or ("127.0.0.1", "::1"),
        max_upload_bytes=_gigabytes("CLIPFOUNDRY_MAX_UPLOAD_GB", 8.0),
        storage_limit_bytes=_gigabytes("CLIPFOUNDRY_STORAGE_LIMIT_GB", 150.0),
        signup=os.environ.get("CLIPFOUNDRY_PUBLIC_SIGNUP", "off").strip().lower() or "off",
    )


def reset() -> None:
    """Forget cached settings (tests change the environment)."""
    current.cache_clear()


def problems(s: CloudSettings | None = None) -> list[str]:
    """Everything that makes this cloud deployment unsafe to start, in plain words for the operator."""
    s = s or current()
    out: list[str] = []
    p = urlsplit(s.public_url)
    if not s.public_url:
        out.append("CLIPFOUNDRY_PUBLIC_URL is not set (the https:// address people open).")
    elif p.scheme != "https" and p.hostname not in ("localhost", "127.0.0.1"):
        out.append("CLIPFOUNDRY_PUBLIC_URL must use https:// (plain http is allowed only for localhost testing).")
    elif p.path not in ("", "/") or p.query or p.fragment:
        out.append("CLIPFOUNDRY_PUBLIC_URL must be only the scheme and host, e.g. https://studio.example.com")
    if not s.allowed_hosts:
        out.append("CLIPFOUNDRY_ALLOWED_HOSTS is empty.")
    if not s.oidc_issuer.startswith("https://"):
        out.append("CLIPFOUNDRY_OIDC_ISSUER must be the https:// issuer of the sign-in provider "
                   "(Google: https://accounts.google.com).")
    if not s.oidc_client_id:
        out.append("CLIPFOUNDRY_OIDC_CLIENT_ID is not set.")
    if not s.oidc_client_secret:
        out.append("CLIPFOUNDRY_OIDC_CLIENT_SECRET (or CLIPFOUNDRY_OIDC_CLIENT_SECRET_FILE) is not set.")
    if not s.owners:
        out.append("CLIPFOUNDRY_OWNER_SUBJECTS is empty: name the owner's stable account subject "
                   "(issuer|subject). Email addresses are not accepted as identities.")
    for owner in s.owners:
        if "@" in owner.subject:
            out.append(f"Owner subject {owner.subject!r} looks like an email address; use the provider's stable "
                       "subject ID instead.")
    if s.signup != "off":
        out.append("Public sign-up must stay off (CLIPFOUNDRY_PUBLIC_SIGNUP=off) until multi-user isolation is "
                   "verified.")
    out += key_file_problems(s.secret_key_file)
    if not (s.session_hours > 0 and s.idle_hours > 0):
        out.append("Session lengths must be positive numbers of hours.")
    if s.max_upload_bytes <= 0 or s.storage_limit_bytes <= 0:
        out.append("Upload and storage limits must be positive numbers of gigabytes.")
    return out


def key_file_problems(path: str) -> list[str]:
    if not path:
        return ["CLIPFOUNDRY_SECRET_KEY_FILE is not set (the separately managed key that encrypts saved tokens)."]
    f = Path(path)
    try:
        st = f.stat()
    except OSError:
        return [f"The secret key file {path} cannot be read."]
    out = []
    if os.name == "posix" and st.st_mode & (stat.S_IRWXG | stat.S_IRWXO):
        out.append(f"The secret key file {path} must be readable only by its owner (chmod 600).")
    from .. import config

    try:
        f.resolve().relative_to(config.data_dir().resolve())
        out.append("Keep the secret key file outside the data folder, so a data backup alone cannot decrypt tokens.")
    except ValueError:
        pass
    return out
