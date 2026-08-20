"""Read-only file browsing for the Viewer tab: lists and reads files under a discovered role's
directory, or a discovered playbook's own file, for display in the UI (see CLAUDE.md's
"Backend & UI" section).

Every lookup re-validates its role/playbook name against the same rules roles.py/playbooks.py
use for discovery (rather than trusting the name straight off the URL), and every resolved path
is checked to still be inside its expected base directory before being read -- defense against
a role/playbook name, or a file path requested within one, containing `../` segments (or a
symlink) that tries to escape onto the rest of the filesystem.
"""

from __future__ import annotations

from pathlib import Path

from ansiblaster.playbooks import PLAYBOOK_EXTENSIONS
from ansiblaster.roles import looks_like_a_role


class NotFound(Exception):
    """A requested role/playbook/file doesn't exist, isn't valid, or would resolve outside its
    expected directory."""


def _resolve_within(base: Path, *parts: str) -> Path:
    """Join parts onto base and return the result, only if it's still inside base once both
    are resolved (symlinks and `..` segments included) -- raises NotFound otherwise.

    Used both for a role/playbook name onto roles_path/playbooks_path, and for a requested
    file path onto a specific role's own directory.
    """
    resolved_base = base.resolve()
    candidate = resolved_base.joinpath(*parts).resolve()
    if not candidate.is_relative_to(resolved_base):
        raise NotFound()
    return candidate


def _role_dir(roles_path: str | Path, role_name: str) -> Path:
    role_dir = _resolve_within(Path(roles_path), role_name)
    if not role_dir.is_dir() or not looks_like_a_role(role_dir):
        raise NotFound()
    return role_dir


def list_role_files(roles_path: str | Path, role_name: str) -> list[str]:
    """Every regular file under a role's directory, as paths relative to it (e.g.
    "tasks/main.yml"), sorted."""
    role_dir = _role_dir(roles_path, role_name)
    return sorted(str(p.relative_to(role_dir)) for p in role_dir.rglob("*") if p.is_file())


def read_role_file(roles_path: str | Path, role_name: str, relpath: str) -> str:
    role_dir = _role_dir(roles_path, role_name)
    file_path = _resolve_within(role_dir, relpath)
    if not file_path.is_file():
        raise NotFound()
    return file_path.read_text(errors="replace")


def _playbook_file(playbooks_path: str | Path, name: str) -> Path:
    base = Path(playbooks_path)
    for ext in PLAYBOOK_EXTENSIONS:
        candidate = _resolve_within(base, f"{name}{ext}")
        if candidate.is_file():
            return candidate
    raise NotFound()


def list_playbook_files(playbooks_path: str | Path, name: str) -> list[str]:
    """A playbook is a single file, not a directory -- this always returns exactly one entry,
    the playbook's own filename, so the Viewer tab's file browser can treat playbooks and roles
    the same way (a list of files to click through)."""
    return [_playbook_file(playbooks_path, name).name]


def read_playbook_file(playbooks_path: str | Path, name: str, relpath: str) -> str:
    file_path = _playbook_file(playbooks_path, name)
    if relpath != file_path.name:
        raise NotFound()
    return file_path.read_text(errors="replace")
