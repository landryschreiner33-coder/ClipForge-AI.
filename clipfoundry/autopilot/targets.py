"""Which connected account a planned post goes to.

A scheduled post either names its own connection (`connection_id`, for example one of the YouTube channels chosen
for a submitted video) or names none. A post without one goes to the platform's default connection, exactly as
before several accounts could be chosen: its approval, pacing and duplicate checks follow whichever account is the
default. A post that names its connection keeps it: changing the default never moves it to another account.

One exception keeps an upload whole: once a post without a connection of its own has begun uploading (or was
uploaded), it belongs to the account that upload went to. Changing the default in the middle never splits a post
between "approved for one account" and "uploaded to another".
"""
from __future__ import annotations

from .. import db


def begun_on(row: dict) -> str:
    """The connection a planned post's upload already went to (finished, under way, or of unknown outcome); ""
    when nothing was sent yet. An upload record that never started (no session, no bytes) decides nothing: the
    publisher starts a fresh one for the account the post goes to now."""
    row = row or {}
    if not row.get("publication_id"):  # only planned posts carry one
        return ""
    from ..publish import jobs

    pub = db.get_publication(row["publication_id"]) or {}
    if pub.get("connection_id") and (pub.get("status") in ("done", "action_needed") or jobs.transfer_started(pub)
                                     or jobs.unknown_outcome(pub)):
        return pub["connection_id"]
    return ""


def effective_connection_id(row: dict) -> str:
    """The connection this scheduled post or publication goes (or went) to; "" when none is connected at all.
    Its own connection; else the one its upload already began on; else today's default."""
    row = row or {}
    return row.get("connection_id") or begun_on(row) or db.default_connection_id(row.get("platform") or "")


def same_account(row: dict, connection_id: str) -> bool:
    """Does this planned post or publication count against a new post to `connection_id`? A new post without a
    connection of its own ("") is checked platform-wide, exactly as before accounts could be chosen: changing the
    default account must never send the old backlog out again. A post to a chosen account counts only that
    account's rows, so one clip can go to several chosen channels."""
    return not connection_id or effective_connection_id(row) == connection_id


def item_account(item: dict) -> str:
    """The provider account ID (YouTube channel ID, TikTok open_id) this post goes to now. A post bound to a
    connection names that connection's account ("" if it no longer exists). An unbound post goes to the platform's
    default account ("" when none is connected), as before; once its upload has begun, to the account that upload
    began on ("" while that account is disconnected)."""
    cid = (item or {}).get("connection_id") or ""
    if cid:
        return str((db.get_connection(cid) or {}).get("external_id") or "")
    began = begun_on(item)
    if began:
        acc = db.get_connection(began) or {}
        return "" if acc.get("status") == "disconnected" else str(acc.get("external_id") or "")
    from . import autopublish

    return autopublish.account_id((item or {}).get("platform") or "")


def account_name(acc: dict | None) -> str:
    acc = acc or {}
    return str(acc.get("nickname") or acc.get("display_name") or acc.get("external_id") or "")


def account_view(item: dict) -> dict:
    """The account a post goes to, for the owner to see: {connection_id, name, account_id, bound}. `bound` is False
    for a post that simply follows the platform's default account. The approve call names `account_id` back, so
    an approval is always for the account the owner was shown."""
    cid = effective_connection_id(item)
    acc = db.get_connection(cid) if cid else None
    return {"connection_id": cid, "name": account_name(acc), "account_id": str((acc or {}).get("external_id") or ""),
            "bound": bool((item or {}).get("connection_id") or begun_on(item))}


def usable(acc: dict | None) -> bool:
    """Connected, with tokens, and not flagged for Reconnect: new uploads to this account can start."""
    return bool(acc and acc.get("status") == "connected" and acc.get("has_tokens")
                and not (acc.get("info") or {}).get("needs_reconnect"))
