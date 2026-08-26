from __future__ import annotations

import pytest

from ansiblaster.settings import (
    CONFIG_PATH_ENV_VAR,
    get_settings,
    load_settings,
    relevant_environment_variables,
)


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    """Ensure get_settings()'s lru_cache never leaks state between tests."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _isolated_cwd(tmp_path, monkeypatch):
    """Run every test from an empty directory so a stray ./config.yaml can't be picked up,
    and start with no ANSIBLASTER_CONFIG set unless a test opts in.
    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv(CONFIG_PATH_ENV_VAR, raising=False)
    yield tmp_path


def test_defaults_with_no_config_file_and_no_env_vars():
    settings = load_settings()

    assert settings.server.host == "0.0.0.0"
    assert settings.server.port == 8000
    assert settings.ansible.roles_path == "/opt/ansible/roles"
    assert settings.ansible.playbooks_path == "/opt/ansible/playbooks"
    assert settings.ansible.artifacts_path == "/opt/ansiblaster/artifacts"
    assert settings.database.path == "/opt/ansiblaster/ansiblaster.db"
    assert settings.logging.level == "INFO"
    assert settings.defaults.ssh.username == ""
    assert settings.defaults.ssh.password == ""
    assert settings.defaults.winrm.username == ""
    assert settings.defaults.winrm.password == ""
    assert settings.defaults.psrp.username == ""
    assert settings.defaults.psrp.password == ""


def test_yaml_config_file_is_loaded(tmp_path, monkeypatch):
    config_file = tmp_path / "custom.yaml"
    config_file.write_text(
        """
        server:
          port: 9000
        ansible:
          roles_path: /srv/ansible/roles
        defaults:
          ssh:
            username: deploy
        """
    )
    monkeypatch.setenv(CONFIG_PATH_ENV_VAR, str(config_file))

    settings = load_settings()

    assert settings.server.port == 9000
    assert settings.ansible.roles_path == "/srv/ansible/roles"
    assert settings.defaults.ssh.username == "deploy"
    # Unset keys still fall back to their defaults.
    assert settings.server.host == "0.0.0.0"
    assert settings.ansible.playbooks_path == "/opt/ansible/playbooks"


def test_missing_config_file_is_not_an_error():
    # No ANSIBLASTER_CONFIG, no ./config.yaml in the isolated cwd -- should just be defaults.
    settings = load_settings()

    assert settings.server.port == 8000


def test_env_var_overrides_yaml(tmp_path, monkeypatch):
    config_file = tmp_path / "config.yaml"
    config_file.write_text("server:\n  port: 9000\n")
    monkeypatch.setenv(CONFIG_PATH_ENV_VAR, str(config_file))
    monkeypatch.setenv("ANSIBLASTER_SERVER__PORT", "7000")

    settings = load_settings()

    assert settings.server.port == 7000


def test_nested_defaults_credentials_via_env_var(monkeypatch):
    monkeypatch.setenv("ANSIBLASTER_DEFAULTS__WINRM__USERNAME", "Administrator")
    monkeypatch.setenv("ANSIBLASTER_DEFAULTS__WINRM__PASSWORD", "hunter2")

    settings = load_settings()

    assert settings.defaults.winrm.username == "Administrator"
    assert settings.defaults.winrm.password == "hunter2"
    # Untouched sections stay default -- no fallback between ssh/winrm/psrp.
    assert settings.defaults.ssh.username == ""
    assert settings.defaults.psrp.username == ""
    assert settings.defaults.psrp.password == ""


def test_logging_level_env_var_override(monkeypatch):
    monkeypatch.setenv("ANSIBLASTER_LOGGING__LEVEL", "DEBUG")

    settings = load_settings()

    assert settings.logging.level == "DEBUG"


def test_get_settings_is_cached_singleton():
    first = get_settings()
    second = get_settings()

    assert first is second


def test_get_settings_reflects_env_at_first_call(monkeypatch):
    monkeypatch.setenv("ANSIBLASTER_SERVER__PORT", "6000")

    settings = get_settings()

    assert settings.server.port == 6000


def test_relevant_environment_variables_empty_by_default():
    assert relevant_environment_variables() == []


def test_relevant_environment_variables_includes_ansiblaster_prefixed_vars(monkeypatch):
    monkeypatch.setenv("ANSIBLASTER_SERVER__PORT", "9000")

    result = relevant_environment_variables()

    assert result == [("ANSIBLASTER_SERVER__PORT", "9000", False)]


def test_relevant_environment_variables_includes_puid_pgid(monkeypatch):
    monkeypatch.setenv("PUID", "1001")
    monkeypatch.setenv("PGID", "1001")

    result = relevant_environment_variables()

    assert ("PUID", "1001", False) in result
    assert ("PGID", "1001", False) in result


def test_relevant_environment_variables_excludes_unrelated_vars(monkeypatch):
    monkeypatch.setenv("PATH", "/usr/bin")
    monkeypatch.setenv("SOME_OTHER_VAR", "x")

    assert relevant_environment_variables() == []


def test_relevant_environment_variables_masks_sensitive_names(monkeypatch):
    monkeypatch.setenv("ANSIBLASTER_DEFAULTS__SSH__PASSWORD", "hunter2")

    result = relevant_environment_variables()

    assert len(result) == 1
    name, value, sensitive = result[0]
    assert name == "ANSIBLASTER_DEFAULTS__SSH__PASSWORD"
    assert value != "hunter2"
    assert sensitive is True


def test_dir_env_var_overrides_database_and_artifacts_defaults(monkeypatch):
    monkeypatch.setenv("ANSIBLASTER_DIR", "/home/user/.config/ansiblaster")

    settings = load_settings()

    assert settings.database.path == "/home/user/.config/ansiblaster/ansiblaster.db"
    assert settings.ansible.artifacts_path == "/home/user/.config/ansiblaster/artifacts"
    # Unrelated paths are untouched.
    assert settings.ansible.roles_path == "/opt/ansible/roles"


def test_dir_env_var_does_not_override_explicit_database_path(monkeypatch):
    monkeypatch.setenv("ANSIBLASTER_DIR", "/home/user/.config/ansiblaster")
    monkeypatch.setenv("ANSIBLASTER_DATABASE__PATH", "/custom/db/ansiblaster.db")

    settings = load_settings()

    assert settings.database.path == "/custom/db/ansiblaster.db"
    # artifacts_path wasn't separately overridden, so `dir` still applies to it.
    assert settings.ansible.artifacts_path == "/home/user/.config/ansiblaster/artifacts"


def test_dir_env_var_does_not_override_explicit_artifacts_path(monkeypatch):
    monkeypatch.setenv("ANSIBLASTER_DIR", "/home/user/.config/ansiblaster")
    monkeypatch.setenv("ANSIBLASTER_ANSIBLE__ARTIFACTS_PATH", "/custom/artifacts")

    settings = load_settings()

    assert settings.ansible.artifacts_path == "/custom/artifacts"
    assert settings.database.path == "/home/user/.config/ansiblaster/ansiblaster.db"


def test_dir_unset_leaves_hardcoded_defaults():
    settings = load_settings()

    assert settings.dir is None
    assert settings.database.path == "/opt/ansiblaster/ansiblaster.db"
    assert settings.ansible.artifacts_path == "/opt/ansiblaster/artifacts"


def test_dir_via_yaml_config_file(tmp_path, monkeypatch):
    config_file = tmp_path / "custom.yaml"
    config_file.write_text("dir: /srv/ansiblaster-data\n")
    monkeypatch.setenv(CONFIG_PATH_ENV_VAR, str(config_file))

    settings = load_settings()

    assert settings.database.path == "/srv/ansiblaster-data/ansiblaster.db"
    assert settings.ansible.artifacts_path == "/srv/ansiblaster-data/artifacts"


def test_relevant_environment_variables_sorted_by_name(monkeypatch):
    monkeypatch.setenv("ANSIBLASTER_SERVER__PORT", "9000")
    monkeypatch.setenv("ANSIBLASTER_DATABASE__PATH", "/data/db.sqlite")

    result = relevant_environment_variables()

    assert [name for name, _, _ in result] == [
        "ANSIBLASTER_DATABASE__PATH",
        "ANSIBLASTER_SERVER__PORT",
    ]
