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


def test_main_passes_default_log_level_lowercased_to_uvicorn(monkeypatch):
    calls = []
    monkeypatch.setattr(main_module.uvicorn, "run", lambda *a, **kw: calls.append((a, kw)))

    main_module.main()

    assert len(calls) == 1
    _, kwargs = calls[0]
    assert kwargs["log_level"] == "warning"
    assert kwargs["host"] == "0.0.0.0"
    assert kwargs["port"] == 8000


def test_main_respects_log_level_env_var_override(monkeypatch):
    monkeypatch.setenv("ANSIBLASTER_LOGGING__LEVEL", "DEBUG")
    calls = []
    monkeypatch.setattr(main_module.uvicorn, "run", lambda *a, **kw: calls.append((a, kw)))

    main_module.main()

    assert calls[0][1]["log_level"] == "debug"
