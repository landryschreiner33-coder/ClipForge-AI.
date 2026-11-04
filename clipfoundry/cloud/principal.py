"""Who a request acts for. Desktop mode has one implicit owner; cloud mode has the signed-in session's owner.

The workspace always comes from the server-side session, never from anything the browser sends, so a request can
only ever reach its own workspace's data.
"""
from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass

from . import settings as cloud_settings


@dataclass(frozen=True)
class Principal:
    user_id: str
    workspace_id: str
    session_id: str = ""
    subject: str = ""
    name: str = ""
    csrf: str = ""

    @property
    def primary(self) -> bool:
        """The workspace that holds the desktop data and the (single-workspace) Autopilot, Brain notes and settings."""
        return self.workspace_id == cloud_settings.PRIMARY_WORKSPACE


LOCAL_OWNER = Principal(user_id="local-owner", workspace_id=cloud_settings.PRIMARY_WORKSPACE, subject="local",
                        name="This computer")

_current: ContextVar[Principal | None] = ContextVar("clipforge_principal", default=None)


class NotSignedIn(PermissionError):
    pass


def current() -> Principal:
    """The principal of the running request. Desktop mode: the local owner. Cloud mode outside an authenticated
    request (a background worker calling request code by mistake) raises instead of guessing."""
    if not cloud_settings.enabled():
        return _current.get() or LOCAL_OWNER
    p = _current.get()
    if p is None:
        raise NotSignedIn("No signed-in session for this request")
    return p


def workspace_id() -> str:
    return current().workspace_id


def bind(p: Principal | None):
    """Set the principal for the current context; returns the token for `reset`."""
    return _current.set(p)


def reset(token) -> None:
    _current.reset(token)
