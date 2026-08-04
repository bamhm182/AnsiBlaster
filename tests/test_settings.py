from __future__ import annotations

import pytest

from ansiblaster.settings import CONFIG_PATH_ENV_VAR, get_settings, load_settings


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
    assert settings.defaults.linux.username == ""
    assert settings.defaults.linux.password == ""
    assert settings.defaults.windows.username == ""
    assert settings.defaults.windows.password == ""


def test_yaml_config_file_is_loaded(tmp_path, monkeypatch):
    config_file = tmp_path / "custom.yaml"
    config_file.write_text(
        """
        server:
          port: 9000
        ansible:
          roles_path: /srv/ansible/roles
        defaults:
          linux:
            username: deploy
        """
    )
    monkeypatch.setenv(CONFIG_PATH_ENV_VAR, str(config_file))

    settings = load_settings()

    assert settings.server.port == 9000
    assert settings.ansible.roles_path == "/srv/ansible/roles"
    assert settings.defaults.linux.username == "deploy"
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
    monkeypatch.setenv("ANSIBLASTER_DEFAULTS__WINDOWS__USERNAME", "Administrator")
    monkeypatch.setenv("ANSIBLASTER_DEFAULTS__WINDOWS__PASSWORD", "hunter2")

    settings = load_settings()

    assert settings.defaults.windows.username == "Administrator"
    assert settings.defaults.windows.password == "hunter2"
    # Untouched section stays default.
    assert settings.defaults.linux.username == ""


def test_get_settings_is_cached_singleton():
    first = get_settings()
    second = get_settings()

    assert first is second


def test_get_settings_reflects_env_at_first_call(monkeypatch):
    monkeypatch.setenv("ANSIBLASTER_SERVER__PORT", "6000")

    settings = get_settings()

    assert settings.server.port == 6000
