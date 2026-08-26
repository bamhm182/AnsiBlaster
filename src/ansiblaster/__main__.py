"""Entrypoint: `uv run ansiblaster` starts uvicorn serving the app."""

from __future__ import annotations

import uvicorn

from ansiblaster.settings import get_settings


def main() -> None:
    settings = get_settings()
    uvicorn.run(
        "ansiblaster.app:app",
        host=settings.server.host,
        port=settings.server.port,
        # Lowercased: uvicorn's own log level names are lowercase ("info", "warning", ...),
        # while config.yaml/the ANSIBLASTER_LOGGING__LEVEL env var are conventionally written
        # upper-case (matching Python's own logging module constants) -- see settings.py's
        # LoggingSettings and CLAUDE.md's "Configuration file" section.
        log_level=settings.logging.level.lower(),
    )


if __name__ == "__main__":
    main()
