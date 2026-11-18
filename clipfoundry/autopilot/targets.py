"""Which connected account a planned post goes to.

A scheduled post either names its own connection (`connection_id`, for example one of the YouTube channels chosen
for a submitted video) or names none. A post without one goes to the platform's default connection, exactly as
before several accounts could be chosen: its approval, pacing and duplicate checks follow whichever account is the
default. A post that names its connection keeps it: changing the default never moves it to another account.
"""
from __future__ import annotations

from .. import db


def effective_connection_id(row: dict) -> str:
    """The connection this scheduled post or publication goes (or went) to; "" when none is connected at all."""
    row = row or {}
    return row.get("connection_id") or db.default_connection_id(row.get("platform") or "")


def item_account(item: dict) -> str:
    """The provider account ID (YouTube channel ID, TikTok open_id) this post goes to now. A post bound to a
    connection names that connection's account ("" if it no longer exists); an unbound post goes to the platform's
    default account ("" when none is connected), as before."""
    cid = (item or {}).get("connection_id") or ""
    if cid:
        return str((db.get_connection(cid) or {}).get("external_id") or "")
    from . import autopublish

    return autopublish.account_id((item or {}).get("platform") or "")


def account_name(acc: dict | None) -> str:
    acc = acc or {}
    return str(acc.get("nickname") or acc.get("display_name") or acc.get("external_id") or "")


def account_view(item: dict) -> dict:
    """The account a post goes to, for the owner to see: {connection_id, name, account_id}."""
    cid = effective_connection_id(item)
    acc = db.get_connection(cid) if cid else None
    return {"connection_id": cid, "name": account_name(acc), "account_id": str((acc or {}).get("external_id") or "")}


def usable(acc: dict | None) -> bool:
    """Connected, with tokens: new uploads to this account can start (a reconnect is not needed)."""
    return bool(acc and acc.get("status") == "connected" and acc.get("has_tokens"))
