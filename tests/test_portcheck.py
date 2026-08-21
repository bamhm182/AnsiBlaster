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


async def test_check_port_reports_banner_when_server_speaks_first():
    async def handle(reader, writer):
        writer.write(b"SSH-2.0-OpenSSH_10.2\r\n")
        await writer.drain()
        await asyncio.sleep(10)  # stay connected until the test tears the server down

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    try:
        port = server.sockets[0].getsockname()[1]
        result = await check_port("127.0.0.1", port)
        assert result.open is True
        assert result.banner == "SSH-2.0-OpenSSH_10.2"
    finally:
        server.close()
        await server.wait_closed()


async def test_check_port_open_with_no_banner_when_server_stays_silent():
    async def handle(reader, writer):
        await asyncio.sleep(10)  # never sends anything, like an HTTP/WinRM listener would

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    try:
        port = server.sockets[0].getsockname()[1]
        result = await check_port("127.0.0.1", port, banner_timeout=0.3)
        assert result.open is True
        assert result.banner is None
    finally:
        server.close()
        await server.wait_closed()


async def test_check_port_closed_when_connection_is_refused():
    result = await check_port("127.0.0.1", _unused_port())
    assert result.open is False
    assert result.banner is None


async def test_check_port_closed_on_connect_timeout():
    # TEST-NET-2 (RFC 5737): reserved for documentation, guaranteed non-routable, so this
    # either black-holes (hits our timeout) or gets an immediate "unreachable" -- either way
    # the check should come back closed, quickly, without raising.
    result = await check_port("198.51.100.1", 22, connect_timeout=0.3)
    assert result.open is False
    assert result.banner is None


async def test_check_port_closed_for_unresolvable_host():
    result = await check_port("this-host-does-not-resolve.invalid", 22, connect_timeout=0.3)
    assert result.open is False
    assert result.banner is None
