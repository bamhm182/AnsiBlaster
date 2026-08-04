"""Role discovery: scans the configured roles directory for valid Ansible roles.

A subdirectory is treated as a role if it has a tasks/main.yml (or .yaml) entry point --
that's the one file every role that actually does something is expected to have, and it's
enough to distinguish e.g. roles/docker-host/ from a stray non-role directory under
roles_path.
"""

from __future__ import annotations

from pathlib import Path

_TASKS_ENTRYPOINTS = ("tasks/main.yml", "tasks/main.yaml")


def _looks_like_a_role(role_dir: Path) -> bool:
    return any((role_dir / entrypoint).is_file() for entrypoint in _TASKS_ENTRYPOINTS)


def discover_roles(roles_path: str | Path) -> list[str]:
    """Return the sorted names of every role found directly under roles_path.

    Returns an empty list if roles_path doesn't exist or isn't a directory, rather than
    raising -- a missing/misconfigured roles directory shouldn't break the page that lists
    them, it should just show no roles.
    """
    base = Path(roles_path)
    if not base.is_dir():
        return []

    return sorted(
        entry.name
        for entry in base.iterdir()
        if entry.is_dir() and not entry.name.startswith(".") and _looks_like_a_role(entry)
    )
