"""Encrypt database secrets with a per-profile key held by the macOS login Keychain."""
from __future__ import annotations

import base64
import hashlib
import os
import re

from . import config, locks

PREFIX = "keychain:v1:"
SERVICE = "ClipForge profile encryption"
OLD_SERVICE = "ClipFoundry profile encryption"   # before the rename: moved to SERVICE the first time it is read


def _backend():
    # Choose Apple's backend explicitly; never silently select a plaintext third-party keyring.
    from keyring.backends.macOS import Keyring

    return Keyring()


def _key(identifier: str, create: bool = False) -> bytes:
    if not re.fullmatch(r"[0-9a-f]{32}", identifier):
        raise ValueError("Invalid Keychain reference")
    lock = locks.named("macos-secrets")
    if not lock.acquire(timeout=30):
        raise RuntimeError("Keychain setup is busy")
    try:
        backend = _backend()
        value = backend.get_password(SERVICE, identifier)
        if value is None:
            value = _move_old(backend, identifier)
        if value is None and create:
            value = base64.b64encode(os.urandom(32)).decode("ascii")
            backend.set_password(SERVICE, identifier, value)
        if value is None:
            raise ValueError("This Mac does not have the profile's encryption key")
        result = base64.b64decode(value, validate=True)
        if len(result) != 32:
            raise ValueError("Invalid Keychain encryption key")
        return result
    finally:
        lock.release()


def _move_old(backend, identifier: str) -> str | None:
    """A key saved under the old name ("ClipFoundry profile encryption") is saved under the new one, read back, and
    only then is the old item removed, so Keychain Access shows ClipForge. If any step fails the old item stays
    and is used: the key is never lost."""
    value = backend.get_password(OLD_SERVICE, identifier)
    if value is None:
        return None
    try:
        backend.set_password(SERVICE, identifier, value)
        if backend.get_password(SERVICE, identifier) == value:
            backend.delete_password(OLD_SERVICE, identifier)
    except Exception:  # noqa: BLE001 - the old item keeps working
        pass
    return value


def seal(text: str) -> str:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    identifier = hashlib.sha256(str(config.data_dir().resolve()).encode("utf-8")).hexdigest()[:32]
    nonce = os.urandom(12)
    aad = (PREFIX + identifier).encode("ascii")
    encrypted = AESGCM(_key(identifier, create=True)).encrypt(nonce, text.encode("utf-8"), aad)
    return PREFIX + identifier + ":" + base64.b64encode(nonce + encrypted).decode("ascii")


def unseal(stored: str) -> str:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    identifier, payload = stored.removeprefix(PREFIX).split(":", 1)
    raw = base64.b64decode(payload, validate=True)
    if len(raw) < 29:
        raise ValueError("Invalid encrypted secret")
    aad = (PREFIX + identifier).encode("ascii")
    return AESGCM(_key(identifier)).decrypt(raw[:12], raw[12:], aad).decode("utf-8")
