"""Resolve GET / query parameters into a concrete run request -- the server-side half of the
"pre-fill / deploy from a URL" feature (see AGENTS.md's "URL parameters" section).

The browser pre-fills the Deploy form client-side from the same parameters (index.html's
applyUrlParams()), but a non-interactive client (curl, a script) never runs that JavaScript, so
`execute=1` is handled here, server-side, for everyone: the same parameters are resolved
against what's actually on disk / configured, then launched through routes/runs.py's
start_run() -- the same validation path as the form's POST /runs.

Anything that doesn't resolve (unknown playbook/role/preset/variable, no host) is reported as a
problem and blocks the run: an automatic deploy must never apply something other than what the
link asked for.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from ansiblaster.inventory import DEFAULT_PORTS, WINDOWS_HTTPS_PORT
from ansiblaster.models import TargetOS
from ansiblaster.settings import Settings
from ansiblaster.settings_store import apply_host_overrides, apply_role_variable_overrides

# ?preset= name -> (target OS/connection, default port). Mirrors the port-preset <option>s'
# data-preset attributes in index.html.
PRESETS: dict[str, tuple[TargetOS, int]] = {
    "ssh": (TargetOS.LINUX, DEFAULT_PORTS[TargetOS.LINUX]),
    "winrm": (TargetOS.WINDOWS, DEFAULT_PORTS[TargetOS.WINDOWS]),
    "winrm-secure": (TargetOS.WINDOWS, WINDOWS_HTTPS_PORT),
    "psrp": (TargetOS.WINDOWS_PSRP, DEFAULT_PORTS[TargetOS.WINDOWS_PSRP]),
    "psrp-secure": (TargetOS.WINDOWS_PSRP, WINDOWS_HTTPS_PORT),
}
# Which config.yaml/Settings-popup credential defaults each connection type uses.
_CREDENTIAL_PRESET = {
    TargetOS.LINUX: "ssh",
    TargetOS.WINDOWS: "winrm",
    TargetOS.WINDOWS_PSRP: "psrp",
}

_PER_ROLE_VAR_RE = re.compile(r"^vars\[([^\]]+)\]\[([^\]]+)\]$")
_GLOBAL_VAR_RE = re.compile(r"^vars\[([^\]]+)\]$")


@dataclass
class ResolvedRun:
    target_os: TargetOS
    target_host: str
    target_port: int
    target_user: str
    target_password: str
    roles: list[str]
    raw_variables: dict[str, dict[str, str]]


@dataclass
class ResolveResult:
    run: ResolvedRun | None = None
    problems: list[str] = field(default_factory=list)


def _param_list(params: Mapping[str, Any], *keys: str) -> list[str]:
    """Repeatable and/or comma-separated values for any of `keys`, in order, stripped."""
    values: list[str] = []
    for key in keys:
        raw = (
            params.getlist(key)
            if hasattr(params, "getlist")
            else [params[key]]
            if key in params
            else []
        )
        for item in raw:
            values.extend(part.strip() for part in str(item).split(","))
    return [value for value in values if value]


def _first(params: Mapping[str, Any], *keys: str) -> str | None:
    for key in keys:
        if key in params:
            return str(params[key])
    return None


def _default_as_text(value: Any) -> str:
    """A role variable's default as the plain text the form would have autofilled."""
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "true" if value else "false"
    return json.dumps(value)


def resolve_run_params(
    params: Mapping[str, Any],
    *,
    settings: Settings,
    roles_available: list[str],
    playbooks: dict[str, list[str]],
    role_variables: dict[str, dict[str, dict[str, Any]]],
    host_overrides: dict[str, dict[str, str]],
    role_variable_overrides: dict[str, Any],
) -> ResolveResult:
    """`role_variables` is discover_role_variables()'s raw output (overrides are layered here
    so a variable the URL doesn't set gets the same autofilled default the form would show)."""
    problems: list[str] = []

    preset_name = (_first(params, "preset") or "ssh").strip().lower()
    if preset_name not in PRESETS:
        problems.append(f'unknown preset "{preset_name}"')
        return ResolveResult(problems=problems)
    target_os, default_port = PRESETS[preset_name]

    # Roles: playbooks first, then explicit roles, de-duplicated, order preserved.
    selected: list[str] = []

    def add_role(name: str) -> None:
        if name not in selected:
            selected.append(name)

    for name in _param_list(params, "playbook", "playbooks"):
        if name not in playbooks:
            problems.append(f'unknown playbook "{name}"')
            continue
        for role in playbooks[name]:
            if role not in roles_available:
                problems.append(f'playbook "{name}" references unknown role "{role}"')
            else:
                add_role(role)
    for name in _param_list(params, "role", "roles"):
        if name not in roles_available:
            problems.append(f'unknown role "{name}"')
        else:
            add_role(name)
    if not selected and not problems:
        problems.append("no roles selected (use role= and/or playbook=)")

    # Host/port/credentials; blank credentials fall back to the same defaults the form shows.
    credentials = apply_host_overrides(settings.defaults, host_overrides)[
        _CREDENTIAL_PRESET[target_os]
    ]
    host = (_first(params, "host", "target_host") or "").strip()
    if not host:
        problems.append("host is required")
    port_text = _first(params, "port", "target_port")
    port = default_port
    if port_text is not None and port_text.strip():
        try:
            port = int(port_text)
        except ValueError:
            problems.append("port must be a number")
    user_text = _first(params, "user", "username", "target_user")
    user = (user_text.strip() if user_text is not None else "") or credentials["username"]
    password_text = _first(params, "password", "target_password")
    password = password_text if password_text is not None else credentials["password"]

    # Variables: start from each selected role's (override-aware) defaults, then apply
    # vars[<name>] (every selected role declaring it), then vars[<role>][<name>] last, so the
    # most specific value wins -- the same precedence the client-side prefill uses.
    specs = apply_role_variable_overrides(role_variables, role_variable_overrides)
    raw_variables: dict[str, dict[str, str]] = {}
    for role in selected:
        for var_name, spec in specs.get(role, {}).items():
            if spec.get("default") is not None:
                raw_variables.setdefault(role, {})[var_name] = _default_as_text(spec["default"])
    per_role: list[tuple[str, str, str]] = []
    for key, value in params.multi_items() if hasattr(params, "multi_items") else params.items():
        if match := _PER_ROLE_VAR_RE.match(key):
            per_role.append((match[1], match[2], str(value)))
        elif match := _GLOBAL_VAR_RE.match(key):
            owners = [r for r in selected if match[1] in specs.get(r, {})]
            if not owners:
                problems.append(f'no selected role declares variable "{match[1]}"')
            for role in owners:
                raw_variables.setdefault(role, {})[match[1]] = str(value)
    for role, var_name, value in per_role:
        if role not in selected:
            problems.append(f'variable for unselected role "{role}"')
        elif var_name not in specs.get(role, {}):
            problems.append(f'role "{role}" has no variable "{var_name}"')
        else:
            raw_variables.setdefault(role, {})[var_name] = value

    if problems:
        return ResolveResult(problems=problems)
    return ResolveResult(
        run=ResolvedRun(
            target_os=target_os,
            target_host=host,
            target_port=port,
            target_user=user,
            target_password=password,
            roles=selected,
            raw_variables=raw_variables,
        )
    )
