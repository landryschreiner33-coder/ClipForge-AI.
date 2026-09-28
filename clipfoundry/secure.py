"""Secrets at rest: OAuth tokens and API client secrets for publishing.

ClipFoundry never asks for, sees or stores a Google or TikTok password: you sign in on Google's or TikTok's own page
and ClipFoundry receives an access token (and a refresh token) through OAuth.

On Windows those tokens are encrypted with DPAPI (CryptProtectData, current-user scope), so only your Windows account
on this PC can decrypt them; a copy of the database on another PC or account is useless. On Linux and macOS they are
stored base64-encoded (not encrypted) in the database, which ClipFoundry keeps readable by your user account only.
"""
from __future__ import annotations

import base64
import ctypes
import os
import sys

from .pipeline.common import log

DPAPI = "dpapi:"
LOCAL = "local:"
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


def seal(text: str) -> str:
    """Protect a secret for storage (empty stays empty)."""
    if not text:
        return ""
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


def protection() -> str:
    return ("encrypted with Windows DPAPI (only your Windows account on this PC can read them)"
            if sys.platform == "win32" else "stored in the local database, readable only by your user account")


def restrict_file(path: os.PathLike | str) -> None:
    """Owner-only permissions on POSIX (Windows profile folders are already per-user)."""
    if os.name == "posix":
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
