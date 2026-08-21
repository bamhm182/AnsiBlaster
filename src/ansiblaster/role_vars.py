"""Role variable discovery: parses each role's `meta/argument_specs.yml` (or `.yaml`).

This is Ansible's own standard for declaring a role's inputs (ansible-core 2.11+, normally
consumed by `ansible-doc`/`ansible-lint`) -- not an AnsiBlaster-specific format. A role
declares its variables under `argument_specs.main.options`, each option optionally carrying
`type`, `default`, `required`, and `description`. Reading this file (rather than
`defaults/main.yml`) is deliberate: `defaults/main.yml` has no way to express "this variable
exists but has no default and must be filled in" -- everything in it already has a value.

A role with no argument_specs file simply has no entry in the result -- exposing variables in
the Deploy column's Variables area is opt-in per role, not automatic for every role directory.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

ARGUMENT_SPECS_ENTRYPOINTS = ("meta/argument_specs.yml", "meta/argument_specs.yaml")


def _normalize_option(spec: Any) -> dict[str, Any] | None:
    """One `options.<var_name>` entry -> {"type", "default", "required", "description"}.

    Returns None for a non-dict entry (malformed) so the caller can skip just that one
    variable rather than discarding the whole role's variables over one bad entry. Missing
    keys get safe fallbacks: "type" is treated as "str" (the input-rendering default),
    "default" as absent, "required" as False, "description" as "".
    """
    if not isinstance(spec, dict):
        return None
    return {
        "type": spec.get("type") if isinstance(spec.get("type"), str) else "str",
        "default": spec.get("default"),
        "required": bool(spec.get("required", False)),
        "description": spec.get("description") if isinstance(spec.get("description"), str) else "",
    }


def _options_from_argument_specs(content: Any) -> dict[str, dict[str, Any]]:
    """Drill into content["argument_specs"]["main"]["options"], defensively at every level --
    a syntactically valid YAML file can still be the wrong *shape* (e.g. a plain list, or
    argument_specs.main.options being a string), which must degrade to "no variables for this
    role" rather than raising.
    """
    if not isinstance(content, dict):
        return {}
    argument_specs = content.get("argument_specs")
    if not isinstance(argument_specs, dict):
        return {}
    main = argument_specs.get("main")
    if not isinstance(main, dict):
        return {}
    options = main.get("options")
    if not isinstance(options, dict):
        return {}

    result: dict[str, dict[str, Any]] = {}
    for var_name, spec in options.items():
        if not isinstance(var_name, str):
            continue
        normalized = _normalize_option(spec)
        if normalized is not None:
            result[var_name] = normalized
    return result


def discover_role_variables(
    roles_path: str | Path, roles: list[str]
) -> dict[str, dict[str, dict[str, Any]]]:
    """{role: {var_name: {"type", "default", "required", "description"}}} for every role in
    `roles` that has a meta/argument_specs.yml(.yaml) with a usable argument_specs.main.options
    block.

    A role with no such file, unreadable/malformed YAML, or the wrong shape is simply absent
    from the result (never present with an empty {}) -- mirrors discover_roles()'s and
    discover_playbooks()'s "missing/bad data on disk = no data, never raise" philosophy, since
    this reads config files, not user input (contrast routes/runs.py's variable *submission*
    handling, which is deliberately strict).
    """
    base = Path(roles_path)
    variables: dict[str, dict[str, dict[str, Any]]] = {}

    for role in roles:
        role_dir = base / role
        for entrypoint in ARGUMENT_SPECS_ENTRYPOINTS:
            spec_path = role_dir / entrypoint
            if not spec_path.is_file():
                continue
            try:
                content = yaml.safe_load(spec_path.read_text())
            except yaml.YAMLError:
                break  # this role's file is malformed -- don't also try the other extension
            options = _options_from_argument_specs(content)
            if options:
                variables[role] = options
            break  # found the entrypoint (usable or not) -- don't fall through to .yaml too

    return variables
