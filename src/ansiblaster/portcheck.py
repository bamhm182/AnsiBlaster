"""Quick, service-agnostic TCP reachability check for the Deploy column's port status dot.

Deliberately just a raw connect-then-close, not a protocol-specific probe. SSH sends its
version banner unprompted the instant a connection opens, so it could be "banner grabbed" --
but WinRM is HTTP/SOAP underneath, and HTTP is request-driven: the server sends nothing until
it *receives* a request, so there's no unprompted banner to read there the way there is for
SSH. A bare TCP connect is the one check that means the same thing ("is something listening
here") for both connection types this app supports (see CLAUDE.md's "Ansible execution"
section), so that's what this does -- it says nothing about what's actually listening, only
that the port accepted a connection.
"""

from __future__ import annotations

import asyncio

DEFAULT_TIMEOUT = 2.0


async def check_port(host: str, port: int, timeout: float = DEFAULT_TIMEOUT) -> bool:
    """Return True if a TCP connection to host:port succeeds within timeout, else False.

    Any failure -- refused, timed out, unresolvable host, network unreachable -- is treated as
    "closed"; this is a best-effort UI hint, not something callers need to distinguish reasons
    for.
    """
    try:
        _reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=timeout
        )
    except (TimeoutError, OSError):
        return False

    writer.close()
    try:
        await writer.wait_closed()
    except OSError:
        pass  # the connection already told us what we needed to know
    return True
