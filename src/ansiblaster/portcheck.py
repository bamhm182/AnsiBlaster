"""Quick, service-agnostic TCP reachability check for the Deploy column's status row.

Connects, then makes a best-effort attempt to read whatever the service sends first -- its
"banner" -- the same thing `nc host port` shows you for a protocol like SSH, which speaks
first the instant a connection opens (e.g. "SSH-2.0-OpenSSH_10.2"). Not every protocol does
that: WinRM is HTTP/SOAP underneath, and HTTP is request-driven, so a WinRM listener won't send
anything until it *receives* a request. This check never sends anything itself, so it treats
both the same way -- connect, then passively wait a short moment to see if anything arrives --
which means SSH-like protocols yield a real banner and HTTP-like ones just report "open, no
banner" instead of erroring or hanging.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

CONNECT_TIMEOUT = 2.0
BANNER_TIMEOUT = 1.5
BANNER_READ_LIMIT = 256


@dataclass
class PortCheckResult:
    open: bool
    banner: str | None = None


async def check_port(
    host: str,
    port: int,
    connect_timeout: float = CONNECT_TIMEOUT,
    banner_timeout: float = BANNER_TIMEOUT,
) -> PortCheckResult:
    """Connect to host:port and report whether it's open, plus any banner it volunteers.

    Any connect failure -- refused, timed out, unresolvable host, network unreachable -- is
    reported as closed; this is a best-effort UI hint, not something callers need to
    distinguish reasons for.

    Deliberately uses `asyncio.wait()` here, not `asyncio.wait_for()`: hostname resolution
    (as opposed to connecting to an already-numeric IP) runs `getaddrinfo` in a worker thread
    under the hood, and a *running* thread-pool call can't actually be interrupted by
    `Future.cancel()` -- it only prevents a call that hasn't started yet. `wait_for()` still
    waits for its cancelled inner task to actually finish unwinding before raising
    `TimeoutError`, so if DNS resolution for a bad/slow-to-fail hostname is itself slow (or a
    network's resolver just never answers), `wait_for()` silently keeps waiting past
    `connect_timeout` instead of enforcing it -- exactly what a "quick" reachability check must
    not do. `asyncio.wait()` has no such wait-for-cancellation-to-land behavior: it simply
    stops waiting once `connect_timeout` elapses and hands back whatever's still pending, so
    this function returns on schedule regardless of how long the abandoned resolution thread
    takes to finish on its own in the background.
    """
    connect_task = asyncio.ensure_future(asyncio.open_connection(host, port))
    _done, pending = await asyncio.wait({connect_task}, timeout=connect_timeout)
    if connect_task in pending:
        connect_task.cancel()
        return PortCheckResult(open=False)
    try:
        reader, writer = connect_task.result()
    except (TimeoutError, OSError):
        return PortCheckResult(open=False)

    banner: str | None = None
    try:
        data = await asyncio.wait_for(reader.read(BANNER_READ_LIMIT), timeout=banner_timeout)
        if data:
            # Take just the first line -- a status row is one line, and a version banner is
            # everything worth showing there anyway.
            banner = data.decode(errors="replace").splitlines()[0].strip() or None
    except (TimeoutError, OSError):
        pass  # nothing volunteered within the wait -- still open, just no banner (e.g. WinRM)
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except OSError:
            pass

    return PortCheckResult(open=True, banner=banner)
