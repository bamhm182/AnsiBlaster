"""Application settings: YAML config file + environment variable overrides.

Discovery: the `ANSIBLASTER_CONFIG` env var names an explicit config file; if it's unset,
`./config.yaml` (relative to the current working directory) is used if present. The file is
entirely optional -- every setting below has a built-in default, so a missing file (e.g. a
fresh container with no volume mounted) is not an error.

Precedence, highest first: constructor kwargs (mainly useful in tests) > `ANSIBLASTER_*` env
vars > the YAML file > the defaults declared on each model. Env vars use `ANSIBLASTER_` as a
prefix and `__` to address nested keys, e.g. `ANSIBLASTER_SERVER__PORT`,
`ANSIBLASTER_DEFAULTS__LINUX__PASSWORD`.

See CLAUDE.md's "Configuration file" section for the full key reference.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, Field
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)

CONFIG_PATH_ENV_VAR = "ANSIBLASTER_CONFIG"
DEFAULT_CONFIG_FILE = Path("config.yaml")


class ServerSettings(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8000


class AnsibleSettings(BaseModel):
    roles_path: str = "/opt/ansible/roles"
    playbooks_path: str = "/opt/ansible/playbooks"
    artifacts_path: str = "/opt/ansiblaster/artifacts"


class DatabaseSettings(BaseModel):
    path: str = "/opt/ansiblaster/ansiblaster.db"


class LoggingSettings(BaseModel):
    level: str = "INFO"


class TargetCredentials(BaseModel):
    """Default username/password pre-filled into the apply form for one target OS."""

    username: str = ""
    password: str = ""


class DefaultsSettings(BaseModel):
    linux: TargetCredentials = Field(default_factory=TargetCredentials)
    windows: TargetCredentials = Field(default_factory=TargetCredentials)


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
