"""Finish one known Windows disconnect cleanup without hiding application or network failures."""
from __future__ import annotations

import asyncio
from contextlib import contextmanager
import inspect
import sys

_WINDOWS = sys.platform == "win32"


def _reset_transport(context: dict):
    exception = context.get("exception")
    if not isinstance(exception, ConnectionResetError) or getattr(exception, "winerror", None) != 10054:
        return None
    # A protocol's own failure must still be reported, even if socket shutdown also failed afterwards.
    if exception.__context__ is not None:
        return None
    handle = context.get("handle")
    callback = getattr(handle, "_callback", None)
    function = getattr(callback, "__func__", None)
    if (getattr(function, "__module__", "") != "asyncio.proactor_events" or
            getattr(function, "__qualname__", "") != "_ProactorBasePipeTransport._call_connection_lost"):
        return None
    trace = exception.__traceback__
    if trace is None:
        return None
    while trace.tb_next is not None:
        trace = trace.tb_next
    # Native socket.shutdown raised inside asyncio itself, rather than inside a protocol callback.
    if trace.tb_frame.f_code is not function.__code__:
        return None
    transport = getattr(callback, "__self__", None)
    if transport is None or not getattr(transport, "_closing", False):
        return None
    if getattr(transport, "_called_connection_lost", True) or getattr(transport, "_sock", None) is None:
        return None
    return transport


@contextmanager
def disconnect_cleanup():
    """Scope the repair to this server loop; retain and restore any previous exception handler."""
    if not _WINDOWS:
        yield
        return
    loop = asyncio.get_running_loop()
    previous = loop.get_exception_handler()

    def report(current_loop, context):
        if previous is not None:
            previous(current_loop, context)
        else:
            current_loop.default_exception_handler(context)

    def handler(current_loop, context):
        transport = _reset_transport(context)
        if transport is None:
            report(current_loop, context)
            return
        try:
            # asyncio already notified the protocol. Retrying its callback would notify it twice.
            # Finish only the cleanup that Windows' reset interrupted after that notification.
            transport._sock.close()
            transport._sock = None
            if transport._server is not None:
                # CPython 3.13 tracks transports; 3.11/3.12 only count them. Select the accepted call before
                # invoking it: retrying after TypeError could detach twice if the method itself raised.
                detach = transport._server._detach
                signature = inspect.signature(detach)
                try:
                    signature.bind(transport)
                except TypeError:
                    signature.bind()
                    detach()
                else:
                    detach(transport)
                transport._server = None
            transport._called_connection_lost = True
        except Exception as exc:  # noqa: BLE001 - cleanup failures retain normal error reporting
            report(current_loop, {**context, "message": "Windows connection cleanup failed", "exception": exc})

    loop.set_exception_handler(handler)
    try:
        yield
    finally:
        if loop.get_exception_handler() is handler:
            loop.set_exception_handler(previous)
