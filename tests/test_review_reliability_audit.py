"""Independent regressions for the Windows disconnect compatibility repair."""
from __future__ import annotations

import asyncio
from asyncio.proactor_events import _ProactorBasePipeTransport
import inspect
import socket
from types import SimpleNamespace


def _reset(loop, server):
    sock = socket.socket()
    notified = []
    transport = object.__new__(_ProactorBasePipeTransport)
    transport._sock = sock
    transport._loop = loop
    transport._closing = True
    transport._called_connection_lost = False
    transport._protocol = SimpleNamespace(connection_lost=lambda error: notified.append(error))
    transport._server = server
    callback = transport._call_connection_lost
    try:
        callback(None)
    except OSError as error:
        reset = ConnectionResetError("synthetic Windows disconnect")
        reset.winerror = 10054
        reset = reset.with_traceback(error.__traceback__)
    else:
        raise AssertionError("The unconnected socket unexpectedly accepted shutdown")
    return transport, sock, notified, {"handle": asyncio.Handle(callback, (None,), loop), "exception": reset}


def test_reset_detaches_real_asyncio_server_and_releases_wait_closed(monkeypatch):
    from clipfoundry import asyncio_windows as fix

    monkeypatch.setattr(fix, "_WINDOWS", True)

    async def run():
        loop = asyncio.get_running_loop()
        reported = []
        loop.set_exception_handler(lambda current, context: reported.append(context))
        server = asyncio.Server(loop, [], asyncio.Protocol, None, 100, None)
        transport, sock, notified, context = _reset(loop, server)
        attach = server._attach
        if inspect.signature(attach).parameters:
            attach(transport)
        else:
            attach()
        server.close()
        try:
            with fix.disconnect_cleanup():
                loop.call_exception_handler(context)
            await asyncio.wait_for(server.wait_closed(), timeout=1)
            assert not reported
            assert notified == [None]
            assert sock.fileno() == -1 and transport._sock is None
            assert transport._server is None and transport._called_connection_lost
        finally:
            sock.close()
            transport._sock = None
            server.close()

    asyncio.run(run())


def test_detach_typeerror_is_reported_without_repeating_side_effect(monkeypatch):
    from clipfoundry import asyncio_windows as fix

    monkeypatch.setattr(fix, "_WINDOWS", True)

    async def run():
        loop = asyncio.get_running_loop()
        reported = []
        calls = []
        loop.set_exception_handler(lambda current, context: reported.append(context))

        def detach(transport):
            calls.append(transport)
            raise TypeError("real server cleanup failure")

        transport, sock, notified, context = _reset(loop, SimpleNamespace(_detach=detach))
        try:
            with fix.disconnect_cleanup():
                loop.call_exception_handler(context)
            assert calls == [transport] and notified == [None]
            assert len(reported) == 1
            assert str(reported[0]["exception"]) == "real server cleanup failure"
            assert not transport._called_connection_lost
        finally:
            sock.close()
            transport._sock = None
            transport._server = None

    asyncio.run(run())
