"""DB-backed runtime-editable settings: role-variable-default overrides and host credential
overrides, both surfaced through the Settings popup (see CLAUDE.md's "Settings" section).

Backed by the single generic key/value `Setting` table (models.py) rather than bespoke tables
per setting kind -- this project has no schema-migration framework (db.py's init_db() only
creates missing *tables*, never adds columns to an already-existing one), so a new *kind* of
setting only ever needs a new key convention here, never a new column/table.

Two key namespaces share the one table:
  - "role_variable:<var_name>" -> the override value for every role's variable named
    <var_name>. Overrides are global by variable name, not scoped per role -- matches the
    Settings popup's "sorted alphabetically by variable name" / "+ to add a variable by name"
    design, which has no notion of "for role X only".
  - "host:<preset>:<field>" -> a username/password override for one port preset (ssh/winrm/
    psrp -- the same three presets settings.py's DefaultsSettings already covers). Each
    preset+field overrides (never merges with) the matching config.yaml default; leaving one
    unset just leaves it at the config.yaml value, same as config.yaml's own "no fallback
    between presets" precedent.
"""

from __future__ import annotations

from typing import Any

import yaml
from sqlalchemy import delete as sa_delete
from sqlalchemy import select
from sqlalchemy.orm import Session

from ansiblaster.models import Setting
from ansiblaster.settings import DefaultsSettings

_ROLE_VARIABLE_PREFIX = "role_variable:"
_HOST_PREFIX = "host:"

HOST_PRESETS = ("ssh", "winrm", "psrp")
HOST_FIELDS = ("username", "password")


def parse_override_value(raw: str) -> Any:
    """Best-effort type-preserving parse of a Settings-popup override value.

    `yaml.safe_load()` is a JSON superset, so text like "42", "true", or '["a", "b"]' parses
    to its natural Python type while a plain word just round-trips as a string -- the same
    technique routes/runs.py's `_coerce_value()` already uses for list/dict role-variable
    submissions. Blank input is kept as an explicit empty string rather than
    `yaml.safe_load("") -> None`, since a blank default is itself a meaningful, deliberate
    choice here (see "Role variables" in CLAUDE.md), not "no value provided".
    """
    if raw == "":
        return ""
    try:
        return yaml.safe_load(raw)
    except yaml.YAMLError:
        return raw


def _role_variable_key(var_name: str) -> str:
    return f"{_ROLE_VARIABLE_PREFIX}{var_name}"


def _host_key(preset: str, field: str) -> str:
    return f"{_HOST_PREFIX}{preset}:{field}"


def get_role_variable_overrides(session: Session) -> dict[str, Any]:
    """{var_name: value} for every saved override, in no particular order -- callers sort for
    display (the Settings popup lists them alphabetically by name)."""
    rows = session.execute(
        select(Setting).where(Setting.key.startswith(_ROLE_VARIABLE_PREFIX))
    ).scalars()
    return {row.key[len(_ROLE_VARIABLE_PREFIX) :]: row.value for row in rows}


def set_role_variable_override(session: Session, var_name: str, value: Any) -> None:
    session.merge(Setting(key=_role_variable_key(var_name), value=value))
    # session_scope's session is autoflush=False, so a merge() here isn't visible to a *later*
    # merge()/query in the same still-uncommitted session until something flushes it -- without
    # this, save_host_settings()'s up-to-six merge() calls in one session (one per preset/field)
    # would each try to INSERT the same not-yet-flushed row again instead of finding it via
    # merge()'s own existence check, and collide on the primary key at commit time.
    session.flush()


def delete_role_variable_override(session: Session, var_name: str) -> None:
    session.execute(sa_delete(Setting).where(Setting.key == _role_variable_key(var_name)))


def get_host_overrides(session: Session) -> dict[str, dict[str, str]]:
    """{preset: {field: value}} for every saved host override -- only presets/fields that
    actually have an explicit override are present."""
    rows = session.execute(select(Setting).where(Setting.key.startswith(_HOST_PREFIX))).scalars()
    result: dict[str, dict[str, str]] = {}
    for row in rows:
        _, preset, field = row.key.split(":", 2)
        result.setdefault(preset, {})[field] = row.value
    return result


def set_host_override(session: Session, preset: str, field: str, value: str) -> None:
    session.merge(Setting(key=_host_key(preset, field), value=value))
    # See set_role_variable_override()'s comment above -- same reasoning applies here, and
    # save_host_settings() is exactly the multi-call-per-session case that needs it.
    session.flush()


def delete_host_override(session: Session, preset: str, field: str) -> None:
    session.execute(sa_delete(Setting).where(Setting.key == _host_key(preset, field)))


def apply_role_variable_overrides(
    role_variables: dict[str, dict[str, dict[str, Any]]],
    overrides: dict[str, Any],
) -> dict[str, dict[str, dict[str, Any]]]:
    """Layer DB overrides on top of discover_role_variables()'s output: for every role/variable
    pair whose variable name has a saved override, replace that spec's "default" with the
    override value (type/required/description still come from the role's own argument_specs
    unchanged). Roles/variables with no matching override are untouched. Returns a new dict;
    never mutates the input, since callers may cache/reuse discover_role_variables()'s result.
    """
    if not overrides:
        return role_variables
    result: dict[str, dict[str, dict[str, Any]]] = {}
    for role, variables in role_variables.items():
        new_vars = {}
        for var_name, spec in variables.items():
            if var_name in overrides:
                spec = {**spec, "default": overrides[var_name]}
            new_vars[var_name] = spec
        result[role] = new_vars
    return result


def apply_host_overrides(
    defaults: DefaultsSettings, overrides: dict[str, dict[str, str]]
) -> dict[str, dict[str, str]]:
    """Layer DB host overrides on top of config.yaml's `defaults.*`, returning a plain
    {preset: {"username": ..., "password": ...}} dict for template use -- config.yaml's value
    wins only when there is no DB override for that exact preset+field."""
    result: dict[str, dict[str, str]] = {}
    for preset in HOST_PRESETS:
        config_defaults = getattr(defaults, preset)
        preset_overrides = overrides.get(preset, {})
        result[preset] = {
            "username": preset_overrides.get("username", config_defaults.username),
            "password": preset_overrides.get("password", config_defaults.password),
        }
    return result
