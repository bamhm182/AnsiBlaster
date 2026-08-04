"""Entrypoint: `uv run ansiblaster` starts uvicorn serving the app."""

from __future__ import annotations

import uvicorn

from ansiblaster.settings import get_settings


def main() -> None:
    settings = get_settings()
    uvicorn.run("ansiblaster.app:app", host=settings.server.host, port=settings.server.port)


if __name__ == "__main__":
    main()
