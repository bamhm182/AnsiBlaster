from __future__ import annotations

import pytest

from ansiblaster import __main__ as main_module
from ansiblaster.settings import get_settings


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _isolated_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("ANSIBLASTER_CONFIG", raising=False)
    yield


def test_main_passes_no_log_level_kwarg(monkeypatch):
    """log_level (as opposed to log_config) must never be passed -- see logging_config.py's
    docstring for why: uvicorn.Config.configure_logging() would use it to stomp the
    uvicorn.access-specific level build_log_config() sets, undoing the whole split.
    """
    calls = []
    monkeypatch.setattr(main_module.uvicorn, "run", lambda *a, **kw: calls.append((a, kw)))

    main_module.main()

    assert len(calls) == 1
    _, kwargs = calls[0]
    assert "log_level" not in kwargs
    assert kwargs["host"] == "0.0.0.0"
    assert kwargs["port"] == 8000


def test_main_builds_log_config_from_the_configured_level(monkeypatch):
    calls = []
    monkeypatch.setattr(main_module.uvicorn, "run", lambda *a, **kw: calls.append((a, kw)))

    main_module.main()

    log_config = calls[0][1]["log_config"]
    assert log_config["loggers"]["ansiblaster"]["level"] == "INFO"
    assert log_config["loggers"]["uvicorn.access"]["level"] == "WARNING"


def test_main_respects_log_level_env_var_override(monkeypatch):
    monkeypatch.setenv("ANSIBLASTER_LOGGING__LEVEL", "DEBUG")
    calls = []
    monkeypatch.setattr(main_module.uvicorn, "run", lambda *a, **kw: calls.append((a, kw)))

    main_module.main()

    log_config = calls[0][1]["log_config"]
    assert log_config["loggers"]["ansiblaster"]["level"] == "DEBUG"
    # DEBUG is the one level where access logging is allowed through too.
    assert log_config["loggers"]["uvicorn.access"]["level"] == "DEBUG"
