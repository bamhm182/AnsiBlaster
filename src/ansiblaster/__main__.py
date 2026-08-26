"""Entrypoint: `uv run ansiblaster` starts uvicorn serving the app."""

from __future__ import annotations

import uvicorn

from ansiblaster.logging_config import build_log_config
from ansiblaster.settings import get_settings


def main() -> None:
    settings = get_settings()
    uvicorn.run(
        "ansiblaster.app:app",
        host=settings.server.host,
        port=settings.server.port,
        # log_config, not log_level -- see logging_config.py's docstring for why passing both
        # would silently undo the split it makes between uvicorn's per-request access logging
        # and everything else.
        log_config=build_log_config(settings.logging.level),
    )


if __name__ == "__main__":
    main()
