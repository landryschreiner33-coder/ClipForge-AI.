"""Secrets at rest: OAuth tokens and API client secrets for publishing.

ClipForge never asks for, sees or stores a Google or TikTok password: you sign in on Google's or TikTok's own page
and ClipForge receives an access token (and a refresh token) through OAuth.

On Windows those tokens are encrypted with DPAPI (CryptProtectData, current-user scope), so only your Windows account
on this PC can decrypt them; a copy of the database on another PC or account is useless. On macOS, new secrets are
encrypted with a key in the login Keychain. Linux desktops use owner-readable, base64-encoded (not encrypted) storage
unless a key file is configured.

Cloud mode (``CLIPFOUNDRY_MODE=cloud``) always uses AES-256-GCM with a 32-byte key read from
``CLIPFOUNDRY_SECRET_KEY_FILE``, a file managed separately from the data folder. It fails closed: without a usable
key nothing is sealed or unsealed, and base64 or plaintext values are never accepted as stored secrets.
"""
from __future__ import annotations

import base64
import binascii
import ctypes
import hashlib
import os
import secrets
import sys
from pathlib import Path

from .pipeline.common import log

DPAPI = "dpapi:"
LOCAL = "local:"
AESGCM = "aesgcm:v1:"
_AAD = b"ClipForge sealed secret v1"
KEY_ENV = "CLIPFOUNDRY_SECRET_KEY_FILE"
_ENTROPY = b"ClipFoundry publishing tokens"
_UI_FORBIDDEN = 0x01


class SecretError(RuntimeError):
    """A stored secret cannot be decrypted (e.g. the database was copied to another Windows account)."""


def _dpapi(data: bytes, protect: bool) -> bytes:
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    def blob(b: bytes) -> tuple[Blob, object]:
        buf = ctypes.create_string_buffer(b, len(b))
        return Blob(len(b), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), buf

    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    src, _keep1 = blob(data)
    ent, _keep2 = blob(_ENTROPY)
    out = Blob()
    if protect:
        fn = crypt32.CryptProtectData
        fn.argtypes = [ctypes.POINTER(Blob), wintypes.LPCWSTR, ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
                       wintypes.DWORD, ctypes.POINTER(Blob)]
        ok = fn(ctypes.byref(src), "ClipFoundry", ctypes.byref(ent), None, None, _UI_FORBIDDEN, ctypes.byref(out))
    else:
        fn = crypt32.CryptUnprotectData
        fn.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
                       wintypes.DWORD, ctypes.POINTER(Blob)]
        ok = fn(ctypes.byref(src), None, ctypes.byref(ent), None, None, _UI_FORBIDDEN, ctypes.byref(out))
    if not ok:
        raise OSError(ctypes.get_last_error(), "DPAPI call failed")
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        kernel32.LocalFree(ctypes.cast(out.pbData, ctypes.c_void_p))


def _cloud() -> bool:
    return os.environ.get("CLIPFOUNDRY_MODE", "").strip().lower() == "cloud"


_key_cache: dict[tuple[str, float], bytes] = {}


def _key() -> bytes | None:
    """The 32-byte deployment key (base64, 64 hex characters, or 32 raw bytes in the key file); None if unset."""
    path = os.environ.get(KEY_ENV, "").strip()
    if not path:
        return None
    try:
        mtime = os.stat(path).st_mtime
    except OSError as exc:
        raise SecretError("The secret key file cannot be read, so saved connections stay locked.") from exc
    if (path, mtime) in _key_cache:
        return _key_cache[(path, mtime)]
    raw = Path(path).read_bytes()
    text = raw.strip()
    key = b""
    if len(text) == 64:
        try:
            key = binascii.unhexlify(text)
        except (binascii.Error, ValueError):
            key = b""
    if not key:
        try:
            key = base64.b64decode(text, validate=True)
        except (binascii.Error, ValueError):
            key = b""
    if len(key) != 32:
        key = raw if len(raw) == 32 else b""
    if len(key) != 32:
        raise SecretError("The secret key file must hold 32 random bytes (for example `openssl rand -base64 32`).")
    _key_cache.clear()
    _key_cache[(path, mtime)] = key
    return key


def _key_id(key: bytes) -> str:
    return hashlib.sha256(b"clipforge-key-id" + key).hexdigest()[:12]


def _gcm_seal(text: str, key: bytes) -> str:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM as _AES

    nonce = secrets.token_bytes(12)
    data = _AES(key).encrypt(nonce, text.encode("utf-8"), _AAD)
    return f"{AESGCM}{_key_id(key)}:" + base64.b64encode(nonce + data).decode("ascii")


def _gcm_unseal(stored: str) -> str:
    key = _key()
    if key is None:
        raise SecretError("This saved secret is encrypted with the server key, but no key file is configured.")
    key_id, _, blob = stored[len(AESGCM):].partition(":")
    if key_id != _key_id(key):
        raise SecretError("This saved secret was encrypted with a different server key. Restore the original key "
                          "file or reconnect the account.")
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM as _AES

    try:
        raw = base64.b64decode(blob, validate=True)
        return _AES(key).decrypt(raw[:12], raw[12:], _AAD).decode("utf-8")
    except (InvalidTag, ValueError, binascii.Error) as exc:
        raise SecretError("This saved secret is damaged or was changed, so it was not used.") from exc


def keyed() -> bool:
    """Whether new secrets are sealed with the deployment key (always in cloud mode)."""
    return _cloud() or (sys.platform not in ("win32", "darwin") and bool(os.environ.get(KEY_ENV, "").strip()))


def seal(text: str) -> str:
    """Protect a secret for storage (empty stays empty)."""
    if not text:
        return ""
    if keyed():
        key = _key()
        if key is None:  # cloud mode without its key: refuse rather than store anything readable
            raise SecretError("Cloud mode needs CLIPFOUNDRY_SECRET_KEY_FILE before it can save any secret.")
        return _gcm_seal(text, key)
    if sys.platform == "darwin":
        try:
            from . import macos_secrets

            return macos_secrets.seal(text)
        except Exception as exc:
            raise SecretError("macOS Keychain could not protect this connection. Unlock your login Keychain "
                              "and allow ClipForge's Python to use it, then try connecting again.") from exc
    if sys.platform == "win32":
        try:
            return DPAPI + base64.b64encode(_dpapi(text.encode("utf-8"), True)).decode("ascii")
        except OSError as exc:  # should not happen on a normal Windows account
            log.warning("Windows DPAPI unavailable (%s); storing the secret unencrypted", exc)
    return LOCAL + base64.b64encode(text.encode("utf-8")).decode("ascii")


def unseal(stored: str) -> str:
    """Recover a secret stored with `seal`. Values saved before sealing existed are returned as-is."""
    if not stored:
        return ""
    if stored.startswith(AESGCM):
        return _gcm_unseal(stored)
    if _cloud() and not stored.startswith(("keychain:", DPAPI)):
        raise SecretError("This secret was saved without encryption on another computer. Cloud mode does not use it: "
                          "enter it again or reconnect the account.")
    if stored.startswith("keychain:"):
        if sys.platform != "darwin" or not stored.startswith("keychain:v1:"):
            raise SecretError("This connection needs its original Mac Keychain. Reconnect the account here.")
        try:
            from . import macos_secrets

            return macos_secrets.unseal(stored)
        except Exception as exc:
            raise SecretError("macOS could not unlock this saved connection. Unlock your login Keychain, "
                              "or reconnect this account if the profile came from another Mac.") from exc
    if stored.startswith(DPAPI):
        if sys.platform != "win32":
            raise SecretError("This secret was encrypted by Windows for another PC or account.")
        try:
            return _dpapi(base64.b64decode(stored[len(DPAPI):]), False).decode("utf-8")
        except (OSError, ValueError) as exc:
            raise SecretError("Windows could not decrypt this secret (was the data folder copied from another "
                              "PC or Windows account?).") from exc
    if stored.startswith(LOCAL):
        return base64.b64decode(stored[len(LOCAL):]).decode("utf-8")
    return stored


def upgrade(stored: str) -> str:
    """Re-seal a base64 or plaintext value with the deployment key (a one-time cloud migration of desktop data).
    Values that are already encrypted (or that only another computer can decrypt) are returned unchanged."""
    if not stored or stored.startswith((AESGCM, "keychain:", DPAPI)):
        return stored
    key = _key()
    if key is None:
        raise SecretError("Configure CLIPFOUNDRY_SECRET_KEY_FILE before migrating secrets.")
    plain = base64.b64decode(stored[len(LOCAL):]).decode("utf-8") if stored.startswith(LOCAL) else stored
    return _gcm_seal(plain, key)


def protection() -> str:
    if keyed():
        return "encrypted with AES-256-GCM using the server's separately stored key"
    if sys.platform == "darwin":
        return "encrypted with a key stored in your macOS login Keychain"
    return ("encrypted with Windows DPAPI (only your Windows account on this PC can read them)"
            if sys.platform == "win32" else "stored in the local database, readable only by your user account")


def restrict_file(path: os.PathLike | str) -> None:
    """Owner-only permissions on POSIX (Windows profile folders are already per-user)."""
    if os.name == "posix":
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
