from __future__ import annotations

import pytest

from ansiblaster.logging_config import APP_LOGGER_NAME, build_log_config


@pytest.mark.parametrize("level", ["info", "INFO", "Info"])
def test_build_log_config_is_case_insensitive(level):
    config = build_log_config(level)
    assert config["loggers"]["ansiblaster"]["level"] == "INFO"


@pytest.mark.parametrize("level", ["CRITICAL", "ERROR", "WARNING", "INFO"])
def test_uvicorn_access_pinned_to_warning_unless_debug(level):
    config = build_log_config(level)
    assert config["loggers"]["uvicorn.access"]["level"] == "WARNING"


def test_uvicorn_access_follows_debug():
    config = build_log_config("DEBUG")
    assert config["loggers"]["uvicorn.access"]["level"] == "DEBUG"


def test_uvicorn_and_uvicorn_error_follow_the_given_level():
    config = build_log_config("ERROR")
    assert config["loggers"]["uvicorn"]["level"] == "ERROR"
    assert config["loggers"]["uvicorn.error"]["level"] == "ERROR"


def test_app_logger_entry_has_its_own_handler_and_does_not_propagate():
    config = build_log_config("INFO")
    app_logger = config["loggers"][APP_LOGGER_NAME]
    assert app_logger["level"] == "INFO"
    assert app_logger["handlers"] == ["default"]
    assert app_logger["propagate"] is False


def test_does_not_mutate_uvicorns_own_logging_config_module_state():
    # build_log_config() must deep-copy uvicorn's LOGGING_CONFIG rather than mutate it in
    # place, or one call's level would leak into uvicorn's own module-level default for every
    # later call (including ones uvicorn itself might make elsewhere in the process).
    from uvicorn.config import LOGGING_CONFIG

    before = LOGGING_CONFIG["loggers"]["uvicorn.access"]["level"]
    build_log_config("DEBUG")
    assert LOGGING_CONFIG["loggers"]["uvicorn.access"]["level"] == before
