"""Application settings: YAML config file + environment variable overrides.

Discovery: the `ANSIBLASTER_CONFIG` env var names an explicit config file; if it's unset,
`./config.yaml` (relative to the current working directory) is used if present. The file is
entirely optional -- every setting below has a built-in default, so a missing file (e.g. a
fresh container with no volume mounted) is not an error.

Precedence, highest first: constructor kwargs (mainly useful in tests) > `ANSIBLASTER_*` env
vars > the YAML file > the defaults declared on each model. Env vars use `ANSIBLASTER_` as a
prefix and `__` to address nested keys, e.g. `ANSIBLASTER_SERVER__PORT`,
`ANSIBLASTER_DEFAULTS__SSH__PASSWORD`.

See CLAUDE.md's "Configuration file" section for the full key reference.
"""

from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, Field, model_validator
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)

CONFIG_PATH_ENV_VAR = "ANSIBLASTER_CONFIG"
DEFAULT_CONFIG_FILE = Path("config.yaml")

# AnsiBlaster's own persistent storage (the SQLite db + ansible-runner job artifacts) lives
# under this directory by default. Kept as named constants -- rather than inlined literals on
# AnsibleSettings.artifacts_path/DatabaseSettings.path below -- so Settings._apply_dir_override()
# can recognize "still the built-in default" without repeating the path strings.
_DEFAULT_DATA_DIR = "/opt/ansiblaster"
_DEFAULT_ARTIFACTS_PATH = f"{_DEFAULT_DATA_DIR}/artifacts"
_DEFAULT_DATABASE_PATH = f"{_DEFAULT_DATA_DIR}/ansiblaster.db"

# Same idea, one level down: roles_path/playbooks_path's own built-in defaults, named so
# AnsibleSettings._apply_path_override() below can recognize "still the built-in default"
# without repeating the path strings.
_DEFAULT_ANSIBLE_DIR = "/opt/ansible"
_DEFAULT_ROLES_PATH = f"{_DEFAULT_ANSIBLE_DIR}/roles"
_DEFAULT_PLAYBOOKS_PATH = f"{_DEFAULT_ANSIBLE_DIR}/playbooks"


class ServerSettings(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8000


class AnsibleSettings(BaseModel):
    roles_path: str = _DEFAULT_ROLES_PATH
    playbooks_path: str = _DEFAULT_PLAYBOOKS_PATH
    artifacts_path: str = _DEFAULT_ARTIFACTS_PATH

    # Base directory holding roles_path/playbooks_path as sibling subdirectories (`roles/`,
    # `playbooks/`) -- set via ANSIBLASTER_ANSIBLE__PATH or this section's own `path:` YAML
    # key. An alternative to overriding roles_path/playbooks_path individually when both
    # simply live side by side somewhere other than /opt/ansible, e.g. a single checked-out
    # Ansible repo laid out as <path>/roles and <path>/playbooks. Mirrors Settings.dir/
    # _apply_dir_override() below, one level down -- see there for the same caveats.
    path: str | None = None

    @model_validator(mode="after")
    def _apply_path_override(self) -> AnsibleSettings:
        """Fold `path` (ANSIBLASTER_ANSIBLE__PATH) into roles_path/playbooks_path's defaults.

        Same approach as Settings._apply_dir_override() -- only fills in whichever of
        roles_path/playbooks_path is still exactly the built-in default, so either one set
        explicitly (env var or YAML) always wins over `path`.
        """
        if self.path:
            base = Path(self.path)
            if self.roles_path == _DEFAULT_ROLES_PATH:
                self.roles_path = str(base / "roles")
            if self.playbooks_path == _DEFAULT_PLAYBOOKS_PATH:
                self.playbooks_path = str(base / "playbooks")
        return self


class DatabaseSettings(BaseModel):
    path: str = _DEFAULT_DATABASE_PATH


class LoggingSettings(BaseModel):
    """Governs the app's own logger and uvicorn's startup/error logging -- see
    logging_config.py for how this is actually applied (via a custom `log_config` dict, not
    uvicorn's `log_level`, which can't express the split logging_config.py needs). uvicorn's
    own per-request access logging is deliberately *not* governed by this: it's pinned to
    require DEBUG specifically, regardless of this setting, since it happens constantly under
    normal operation -- see logging_config.py's docstring. INFO by default, so the app's own
    infrequent-but-meaningful log lines (a role/playbook reload's outcome -- see
    routes/roles.py/routes/playbooks.py) show up without also needing DEBUG. Override with
    ANSIBLASTER_LOGGING__LEVEL (any level Python's logging module recognizes: "critical",
    "error", "warning", "info", "debug" -- case-insensitive).
    """

    level: str = "INFO"


class TargetCredentials(BaseModel):
    """Default username/password pre-filled into the apply form for one port preset."""

    username: str = ""
    password: str = ""


class DefaultsSettings(BaseModel):
    """One independent set of defaults per port preset -- winrm and psrp are both "Windows"
    but are otherwise unrelated here (no fallback between them): if you only configure one,
    the other's fields just start out blank, same as if neither were configured."""

    ssh: TargetCredentials = Field(default_factory=TargetCredentials)
    winrm: TargetCredentials = Field(default_factory=TargetCredentials)
    psrp: TargetCredentials = Field(default_factory=TargetCredentials)


def _resolve_config_path() -> Path | None:
    """Return the config file to load, or None if there isn't one to load."""
    explicit = os.environ.get(CONFIG_PATH_ENV_VAR)
    if explicit:
        return Path(explicit)
    return DEFAULT_CONFIG_FILE if DEFAULT_CONFIG_FILE.exists() else None


class Settings(BaseSettings):
    """Top-level settings, merged from a YAML file and `ANSIBLASTER_*` env vars."""

    model_config = SettingsConfigDict(
        env_prefix="ANSIBLASTER_",
        env_nested_delimiter="__",
    )

    server: ServerSettings = Field(default_factory=ServerSettings)
    ansible: AnsibleSettings = Field(default_factory=AnsibleSettings)
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    logging: LoggingSettings = Field(default_factory=LoggingSettings)
    defaults: DefaultsSettings = Field(default_factory=DefaultsSettings)

    # Top-level (not nested under a sub-model), so it's set via the plain env var
    # ANSIBLASTER_DIR or a top-level `dir:` key in config.yaml -- a single base directory for
    # AnsiBlaster's own persistent storage, as an alternative to overriding
    # ansible.artifacts_path/database.path individually when both should simply move
    # somewhere other than the hardcoded /opt/ansiblaster default (e.g. a non-root `uv run`
    # checkout on a host where /opt isn't writable: ANSIBLASTER_DIR=/home/user/.config/ansiblaster).
    # See _apply_dir_override() below for how it's folded in.
    dir: str | None = None

    @model_validator(mode="after")
    def _apply_dir_override(self) -> Settings:
        """Fold `dir` (ANSIBLASTER_DIR) into ansible.artifacts_path/database.path's defaults.

        Only fills in a path that's still exactly the built-in default -- an
        ansible.artifacts_path/database.path explicitly set (env var or YAML) always wins over
        `dir`, same as the general "more specific setting wins" precedent elsewhere in this
        file. Comparing against the hardcoded default string, rather than threading an
        explicit-vs-default flag through settings_customise_sources()'s source merging, is a
        deliberate simplification -- the one edge case it misses is a database.path/
        artifacts_path override that happens to equal the literal default path, which would
        still be treated as "unset" and replaced by `dir`.

        The resulting directories are created lazily wherever they're first needed (db.py's
        make_engine(), jobs.py's JobManager) -- same as the hardcoded default -- not here.
        """
        if self.dir:
            base = Path(self.dir)
            if self.database.path == _DEFAULT_DATABASE_PATH:
                self.database.path = str(base / "ansiblaster.db")
            if self.ansible.artifacts_path == _DEFAULT_ARTIFACTS_PATH:
                self.ansible.artifacts_path = str(base / "artifacts")
        return self

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        # Order = priority, highest first. The YAML source is resolved dynamically (rather
        # than fixed via model_config's yaml_file) so ANSIBLASTER_CONFIG can point anywhere,
        # and so tests can point at a temp file without needing a real cwd config.yaml.
        sources: list[PydanticBaseSettingsSource] = [init_settings, env_settings]
        config_path = _resolve_config_path()
        if config_path is not None:
            sources.append(YamlConfigSettingsSource(settings_cls, yaml_file=config_path))
        return tuple(sources)


def load_settings() -> Settings:
    """Load settings fresh from the current env vars and config file. Prefer get_settings()
    in application code; this is mainly for tests that need an uncached, freshly-loaded copy.
    """
    return Settings()


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide Settings singleton, loading and caching it on first call.

    Settings are static per process start (see CLAUDE.md) -- there's no settings UI/reload,
    so callers throughout the app should use this rather than constructing Settings() again.
    """
    return load_settings()


# Env var names that configure AnsiBlaster but fall outside the ANSIBLASTER_ prefix below --
# read by docker-entrypoint.sh, before this app (or even Python) ever starts, to remap the
# container's built-in user's uid/gid (see CLAUDE.md's "Distribution" section). Still part of
# the process's environment by the time the app runs, so still worth surfacing here.
_UNPREFIXED_RELATED_ENV_VARS = ("PUID", "PGID")

# Env vars whose name suggests a credential -- masked in relevant_environment_variables()'s
# output rather than shown in the clear, on the same "never show a secret back in plain text"
# precedent as the rest of this app's password handling (see CLAUDE.md's "runs table" note on
# why the target password/role variables are never persisted).
_SENSITIVE_ENV_NAME_RE = re.compile(r"password|secret|token", re.IGNORECASE)
_MASKED_ENV_VALUE = "•" * 12  # bullet character, not derived from the real value's length


def relevant_environment_variables() -> list[tuple[str, str, bool]]:
    """Currently-set environment variables that configure AnsiBlaster itself, for the Settings
    popup's read-only Environment tab (see routes/settings.py).

    "Currently set" means only variables actually present in os.environ are returned -- this
    isn't the full set of ANSIBLASTER_* keys the app recognizes (Settings' own field defaults
    already document that; see CLAUDE.md's "Configuration file" section), just what's actually
    overriding them in this process right now. Scope is every `ANSIBLASTER_` (this module's own
    env_prefix) env var plus PUID/PGID (see _UNPREFIXED_RELATED_ENV_VARS above) -- unrelated
    environment noise (PATH, HOME, etc.) is deliberately excluded.

    Returns a list of (name, display_value, sensitive) tuples sorted by name. A credential
    -shaped name (see _SENSITIVE_ENV_NAME_RE) has its value replaced with a fixed mask here,
    not by the caller/template, so the real value never reaches the modal's HTML at all --
    `sensitive` is passed through only so the template can style a masked row differently.
    """
    names = sorted(
        [name for name in os.environ if name.startswith("ANSIBLASTER_")]
        + [name for name in _UNPREFIXED_RELATED_ENV_VARS if name in os.environ]
    )
    result = []
    for name in names:
        sensitive = bool(_SENSITIVE_ENV_NAME_RE.search(name))
        value = _MASKED_ENV_VALUE if sensitive else os.environ[name]
        result.append((name, value, sensitive))
    return result
