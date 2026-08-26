"""Builds the `log_config` dict passed to `uvicorn.run()` (see `__main__.py`).

Two concerns are deliberately decoupled here:

- The app's own logger (`"ansiblaster"`, and everything under it via the standard hierarchical
  naming every `ansiblaster.*` module gets for free from `logging.getLogger(__name__)`) plus
  uvicorn's own `"uvicorn"`/`"uvicorn.error"` loggers (startup/shutdown/errors) follow
  `settings.logging.level` directly.
- uvicorn's `"uvicorn.access"` logger (one line per HTTP request -- exactly the kind of thing
  that happens constantly under normal operation) is deliberately *not* tied to that same
  level: it only ever shows at `DEBUG`, regardless of what `settings.logging.level` is set to.
  This is what lets the app's own `INFO` default (see `settings.py`) surface meaningful,
  infrequent events -- a role/playbook reload's outcome (`routes/roles.py`/`routes/
  playbooks.py`) -- without also dragging in a line for every single request.

`uvicorn.run()`'s own `log_level` kwarg can't express this split: `uvicorn.Config.
configure_logging()` applies `log_config` first, but then -- if `log_level` is *also* given --
unconditionally overwrites `uvicorn.error`/`uvicorn.access`/`uvicorn.asgi` to that one same
level, undoing exactly the separation this module exists to make. So `__main__.py` passes
*only* `log_config` (built here) to `uvicorn.run()`, never `log_level`.
"""

from __future__ import annotations

import copy
from typing import Any

from uvicorn.config import LOGGING_CONFIG

APP_LOGGER_NAME = "ansiblaster"


def build_log_config(level: str) -> dict[str, Any]:
    """A copy of uvicorn's own default logging config, with `level` (any name Python's
    `logging` module recognizes -- case-insensitive) applied to uvicorn's own loggers and to
    a new `"ansiblaster"` logger entry, plus `"uvicorn.access"` pinned to `WARNING` unless
    `level` itself is `DEBUG` (see module docstring).
    """
    level = level.upper()
    config = copy.deepcopy(LOGGING_CONFIG)
    config["loggers"]["uvicorn"]["level"] = level
    config["loggers"]["uvicorn.error"]["level"] = level
    config["loggers"]["uvicorn.access"]["level"] = "DEBUG" if level == "DEBUG" else "WARNING"
    # Reuses uvicorn's own "default" handler/formatter (the same level-prefixed style as
    # uvicorn's own log lines) rather than falling back to Python logging's bare, unconfigured
    # default -- there'd otherwise be nothing to actually handle/print this logger's records.
    config["loggers"][APP_LOGGER_NAME] = {
        "handlers": ["default"],
        "level": level,
        "propagate": False,
    }
    return config
