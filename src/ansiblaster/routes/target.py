"""GET /target/check-port -- backs the Deploy column's port status dot (see CLAUDE.md's
"Backend & UI" section). A raw TCP connect can't be done from browser JS, so this is a plain
JSON endpoint rather than a rendered fragment; index.html's checkTargetPort() calls it directly
via fetch() rather than htmx, to avoid htmx's default closest-form scraping pulling the
password field into the request's query string.
"""

from __future__ import annotations

from fastapi import APIRouter

from ansiblaster.portcheck import check_port

router = APIRouter(prefix="/target")


@router.get("/check-port")
async def check_port_route(host: str, port: int) -> dict[str, bool]:
    return {"open": await check_port(host, port)}
