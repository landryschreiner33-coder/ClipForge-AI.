"""Exercise the real asyncio transport cleanup; emulate only Windows' native error code."""
from __future__ import annotations

import asyncio
from asyncio.proactor_events import _ProactorBasePipeTransport
import socket
from types import SimpleNamespace

import pytest


def native_disconnect_context(loop, *, winerror=10054, close_failure=False):
    sock = socket.socket()  # No connect or external network: shutdown on this socket fails natively.
    calls = []
    transport = object.__new__(_ProactorBasePipeTransport)
    transport._sock = sock
    transport._loop = loop
    transport._closing = True
    transport._called_connection_lost = False
    transport._protocol = SimpleNamespace(connection_lost=lambda error: calls.append(error))
    transport._server = SimpleNamespace(_detach=lambda obj: calls.append(obj))
    callback = transport._call_connection_lost
    try:
        callback(None)
    except OSError as raw:
        exception = ConnectionResetError("synthetic Windows socket reset")
        exception.winerror = winerror
        exception = exception.with_traceback(raw.__traceback__)
    else:
        raise AssertionError("The disconnected native socket unexpectedly accepted shutdown")
    if close_failure:
        class FailedClose:
            def close(self):
                raise OSError("synthetic close failure")
        transport._sock = FailedClose()
    handle = asyncio.Handle(callback, (None,), loop)
    context = {"message": "Exception in callback", "handle": handle, "exception": exception}
    return transport, sock, calls, context


def test_known_native_reset_finishes_cleanup_once_and_restores_handler(monkeypatch):
    from clipfoundry import asyncio_windows as fix

    monkeypatch.setattr(fix, "_WINDOWS", True)

    async def run():
        loop = asyncio.get_running_loop()
        forwarded = []
        previous = lambda current, context: forwarded.append(context)
        loop.set_exception_handler(previous)
        with fix.disconnect_cleanup():
            transport, sock, calls, context = native_disconnect_context(loop)
            try:
                assert calls == [None] and sock.fileno() != -1
                loop.call_exception_handler(context)
                assert calls == [None, transport]  # Protocol is notified once; server detached once.
                assert sock.fileno() == -1 and transport._sock is None and transport._server is None
                assert transport._called_connection_lost
                assert not forwarded
                # An unrelated application error on the same healthy loop remains visible.
                problem = {"message": "real failure", "exception": RuntimeError("real failure")}
                loop.call_exception_handler(problem)
                assert forwarded == [problem]
            finally:
                sock.close()
                transport._sock = None
        assert loop.get_exception_handler() is previous
        assert await asyncio.sleep(0, result="still running") == "still running"

    asyncio.run(run())


@pytest.mark.parametrize("case", ["other_code", "missing_callback", "unrelated_trace", "nested_failure"])
def test_other_errors_are_reported_and_not_repaired(monkeypatch, case):
    from clipfoundry import asyncio_windows as fix

    monkeypatch.setattr(fix, "_WINDOWS", True)

    async def run():
        loop = asyncio.get_running_loop()
        reported = []
        loop.set_exception_handler(lambda current, context: reported.append(context))
        transport, sock, calls, context = native_disconnect_context(loop, winerror=10053 if case == "other_code"
                                                                  else 10054)
        try:
            if case == "missing_callback":
                context.pop("handle")
            elif case == "unrelated_trace":
                context["exception"].__traceback__ = None
            elif case == "nested_failure":
                context["exception"].__context__ = RuntimeError("real protocol failure")
            with fix.disconnect_cleanup():
                loop.call_exception_handler(context)
            assert reported == [context] and calls == [None]
            assert sock.fileno() != -1 and not transport._called_connection_lost
        finally:
            sock.close()
            transport._sock = None

    asyncio.run(run())


def test_failure_to_finish_cleanup_still_reports_real_error(monkeypatch):
    from clipfoundry import asyncio_windows as fix

    monkeypatch.setattr(fix, "_WINDOWS", True)

    async def run():
        loop = asyncio.get_running_loop()
        reported = []
        loop.set_exception_handler(lambda current, context: reported.append(context))
        transport, sock, calls, context = native_disconnect_context(loop, close_failure=True)
        try:
            with fix.disconnect_cleanup():
                loop.call_exception_handler(context)
            assert len(reported) == 1 and str(reported[0]["exception"]) == "synthetic close failure"
            assert calls == [None] and not transport._called_connection_lost
        finally:
            sock.close()
            transport._sock = None

    asyncio.run(run())


def test_non_windows_leaves_handler_alone_and_nested_scopes_restore_safely(monkeypatch):
    from clipfoundry import asyncio_windows as fix

    async def run():
        loop = asyncio.get_running_loop()
        assert loop.get_exception_handler() is None
        monkeypatch.setattr(fix, "_WINDOWS", False)
        with fix.disconnect_cleanup():
            assert loop.get_exception_handler() is None
        monkeypatch.setattr(fix, "_WINDOWS", True)
        with fix.disconnect_cleanup():
            outer = loop.get_exception_handler()
            with fix.disconnect_cleanup():
                assert loop.get_exception_handler() is not outer
            assert loop.get_exception_handler() is outer
        assert loop.get_exception_handler() is None

    asyncio.run(run())
