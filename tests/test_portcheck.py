from __future__ import annotations

import asyncio
import socket

from ansiblaster.portcheck import check_port


def _unused_port() -> int:
    """Bind to an ephemeral port and immediately release it -- reliably nothing is listening
    there afterward, so a connection attempt gets refused rather than hanging."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


async def test_check_port_true_when_something_is_listening():
    server = await asyncio.start_server(lambda reader, writer: None, "127.0.0.1", 0)
    try:
        port = server.sockets[0].getsockname()[1]
        assert await check_port("127.0.0.1", port) is True
    finally:
        server.close()
        await server.wait_closed()


async def test_check_port_false_when_connection_is_refused():
    assert await check_port("127.0.0.1", _unused_port()) is False


async def test_check_port_false_on_timeout():
    # TEST-NET-2 (RFC 5737): reserved for documentation, guaranteed non-routable, so this
    # either black-holes (hits our timeout) or gets an immediate "unreachable" -- either way
    # the check should come back False, quickly, without raising.
    assert await check_port("198.51.100.1", 22, timeout=0.3) is False


async def test_check_port_false_for_unresolvable_host():
    assert await check_port("this-host-does-not-resolve.invalid", 22, timeout=0.3) is False
