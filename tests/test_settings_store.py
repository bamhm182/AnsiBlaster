from __future__ import annotations

import pytest

from ansiblaster.db import init_db, make_engine, make_session_factory, session_scope
from ansiblaster.settings import DefaultsSettings
from ansiblaster.settings_store import (
    apply_host_overrides,
    apply_role_variable_overrides,
    delete_host_override,
    delete_role_variable_override,
    get_host_overrides,
    get_role_variable_overrides,
    parse_override_value,
    set_host_override,
    set_role_variable_override,
)


@pytest.fixture
def session_factory(tmp_path):
    engine = make_engine(str(tmp_path / "test.db"))
    init_db(engine)
    return make_session_factory(engine)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("", ""),
        ("plain text", "plain text"),
        ("42", 42),
        ("3.14", 3.14),
        ("true", True),
        ("false", False),
        ('["a", "b"]', ["a", "b"]),
        ('{"key": "val"}', {"key": "val"}),
    ],
)
def test_parse_override_value(raw, expected):
    assert parse_override_value(raw) == expected


def test_parse_override_value_falls_back_to_raw_string_on_bad_yaml():
    # An unclosed flow collection is invalid YAML -- parse_override_value() should degrade to
    # the raw string rather than raising.
    assert parse_override_value("[unterminated") == "[unterminated"


def test_role_variable_override_round_trip(session_factory):
    with session_scope(session_factory) as session:
        assert get_role_variable_overrides(session) == {}
        set_role_variable_override(session, "mysql_port", 3306)

    with session_scope(session_factory) as session:
        assert get_role_variable_overrides(session) == {"mysql_port": 3306}


def test_role_variable_override_delete(session_factory):
    with session_scope(session_factory) as session:
        set_role_variable_override(session, "mysql_port", 3306)
    with session_scope(session_factory) as session:
        delete_role_variable_override(session, "mysql_port")
    with session_scope(session_factory) as session:
        assert get_role_variable_overrides(session) == {}


def test_role_variable_override_set_again_overwrites(session_factory):
    with session_scope(session_factory) as session:
        set_role_variable_override(session, "mysql_port", 3306)
        set_role_variable_override(session, "mysql_port", 3307)
    with session_scope(session_factory) as session:
        assert get_role_variable_overrides(session) == {"mysql_port": 3307}


def test_host_override_round_trip(session_factory):
    with session_scope(session_factory) as session:
        assert get_host_overrides(session) == {}
        set_host_override(session, "ssh", "username", "deploy")

    with session_scope(session_factory) as session:
        assert get_host_overrides(session) == {"ssh": {"username": "deploy"}}


def test_host_override_delete(session_factory):
    with session_scope(session_factory) as session:
        set_host_override(session, "winrm", "password", "hunter2")
    with session_scope(session_factory) as session:
        delete_host_override(session, "winrm", "password")
    with session_scope(session_factory) as session:
        assert get_host_overrides(session) == {}


def test_host_override_is_independent_per_preset(session_factory):
    # ssh/winrm/psrp overrides don't fall back to each other, mirroring config.yaml's own
    # defaults.ssh/winrm/psrp independence (see settings.py's DefaultsSettings).
    with session_scope(session_factory) as session:
        set_host_override(session, "ssh", "username", "deploy")
    with session_scope(session_factory) as session:
        overrides = get_host_overrides(session)
        assert "winrm" not in overrides
        assert "psrp" not in overrides


def test_apply_role_variable_overrides_replaces_only_default():
    role_variables = {
        "apache": {
            "port": {"type": "int", "default": 80, "required": False, "description": ""},
        }
    }
    result = apply_role_variable_overrides(role_variables, {"port": 8080})
    assert result["apache"]["port"]["default"] == 8080
    # Everything else about the spec is untouched.
    assert result["apache"]["port"]["type"] == "int"
    assert result["apache"]["port"]["required"] is False


def test_apply_role_variable_overrides_is_global_by_name_across_roles():
    role_variables = {
        "apache": {"port": {"type": "int", "default": 80, "required": False, "description": ""}},
        "nginx": {"port": {"type": "int", "default": 80, "required": False, "description": ""}},
    }
    result = apply_role_variable_overrides(role_variables, {"port": 9090})
    assert result["apache"]["port"]["default"] == 9090
    assert result["nginx"]["port"]["default"] == 9090


def test_apply_role_variable_overrides_leaves_unmatched_variables_alone():
    role_variables = {
        "apache": {"port": {"type": "int", "default": 80, "required": False, "description": ""}}
    }
    result = apply_role_variable_overrides(role_variables, {"unrelated_var": "x"})
    assert result["apache"]["port"]["default"] == 80


def test_apply_role_variable_overrides_does_not_mutate_input():
    role_variables = {
        "apache": {"port": {"type": "int", "default": 80, "required": False, "description": ""}}
    }
    apply_role_variable_overrides(role_variables, {"port": 8080})
    assert role_variables["apache"]["port"]["default"] == 80


def test_apply_role_variable_overrides_no_overrides_returns_same_object():
    role_variables = {
        "apache": {"port": {"type": "int", "default": 80, "required": False, "description": ""}}
    }
    assert apply_role_variable_overrides(role_variables, {}) is role_variables


def test_apply_host_overrides_falls_back_to_config_defaults():
    defaults = DefaultsSettings()
    defaults.ssh.username = "configured-user"
    defaults.ssh.password = "configured-pass"
    result = apply_host_overrides(defaults, {})
    assert result["ssh"] == {"username": "configured-user", "password": "configured-pass"}
    assert result["winrm"] == {"username": "", "password": ""}
    assert result["psrp"] == {"username": "", "password": ""}


def test_apply_host_overrides_db_value_wins_over_config():
    defaults = DefaultsSettings()
    defaults.ssh.username = "configured-user"
    result = apply_host_overrides(defaults, {"ssh": {"username": "override-user"}})
    assert result["ssh"]["username"] == "override-user"
    # Password wasn't overridden -- still falls back to config.yaml (blank, here).
    assert result["ssh"]["password"] == ""
