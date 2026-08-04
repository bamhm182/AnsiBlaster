"""Playbook discovery: scans the configured playbooks directory for role presets.

A playbook here is a YAML file written like a normal Ansible playbook -- a list of plays,
each optionally with a `roles:` list -- but it is only ever read for its role *names*. It is
never executed directly by this app; selecting one just pre-checks those roles in the UI (see
CLAUDE.md's "Playbooks (role presets)" section). Vars/tags/conditionals on role entries are
irrelevant here and intentionally ignored.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

_PLAYBOOK_EXTENSIONS = (".yml", ".yaml")


def _role_name_from_entry(entry: Any) -> str | None:
    """Extract a role name from one item of a play's `roles:` list.

    Supports plain string entries (`- apache`) and dict entries (`- role: apache`, with any
    other keys such as vars ignored).
    """
    if isinstance(entry, str):
        return entry
    if isinstance(entry, dict):
        role = entry.get("role")
        if isinstance(role, str):
            return role
    return None


def _roles_from_playbook_content(content: Any) -> list[str]:
    """Aggregate role names across every play in a parsed playbook, in file order, deduped."""
    if not isinstance(content, list):
        return []

    roles: dict[str, None] = {}  # ordered set: dict preserves insertion order, dedupes keys
    for play in content:
        if not isinstance(play, dict):
            continue
        for entry in play.get("roles") or []:
            role_name = _role_name_from_entry(entry)
            if role_name:
                roles[role_name] = None
    return list(roles)


def discover_playbooks(playbooks_path: str | Path) -> dict[str, list[str]]:
    """Return {playbook_name: [role_names]} for every playbook found under playbooks_path.

    playbook_name is the filename stem (e.g. lamp.yml -> "lamp"). Files that don't exist,
    aren't valid YAML, or yield no roles (malformed, or simply not written with a `roles:`
    list) are skipped rather than raising or appearing as a useless empty preset -- one bad
    playbook file shouldn't break the whole preset list.
    """
    base = Path(playbooks_path)
    if not base.is_dir():
        return {}

    playbooks: dict[str, list[str]] = {}
    for entry in sorted(base.iterdir()):
        if (
            not entry.is_file()
            or entry.name.startswith(".")
            or entry.suffix.lower() not in _PLAYBOOK_EXTENSIONS
        ):
            continue

        try:
            content = yaml.safe_load(entry.read_text())
        except yaml.YAMLError:
            continue

        roles = _roles_from_playbook_content(content)
        if roles:
            playbooks[entry.stem] = roles

    return playbooks
