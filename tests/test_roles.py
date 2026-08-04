from __future__ import annotations

from ansiblaster.roles import discover_roles


def _make_role(roles_dir, name, tasks_filename="main.yml"):
    role_dir = roles_dir / name
    (role_dir / "tasks").mkdir(parents=True)
    (role_dir / "tasks" / tasks_filename).write_text(
        "---\n- name: noop\n  ansible.builtin.debug:\n"
    )
    return role_dir


def test_discover_roles_finds_valid_roles(tmp_path):
    roles_dir = tmp_path / "roles"
    _make_role(roles_dir, "docker-host")
    _make_role(roles_dir, "apache", tasks_filename="main.yaml")

    assert discover_roles(roles_dir) == ["apache", "docker-host"]


def test_discover_roles_ignores_non_role_subdirectories(tmp_path):
    roles_dir = tmp_path / "roles"
    _make_role(roles_dir, "docker-host")
    (roles_dir / "not-a-role").mkdir(parents=True)
    (roles_dir / "empty-tasks-dir" / "tasks").mkdir(parents=True)

    assert discover_roles(roles_dir) == ["docker-host"]


def test_discover_roles_ignores_hidden_directories(tmp_path):
    roles_dir = tmp_path / "roles"
    _make_role(roles_dir, "docker-host")
    _make_role(roles_dir, ".git")

    assert discover_roles(roles_dir) == ["docker-host"]


def test_discover_roles_ignores_files_at_top_level(tmp_path):
    roles_dir = tmp_path / "roles"
    _make_role(roles_dir, "docker-host")
    roles_dir.mkdir(exist_ok=True)
    (roles_dir / "README.md").write_text("not a role")

    assert discover_roles(roles_dir) == ["docker-host"]


def test_discover_roles_missing_directory_returns_empty_list(tmp_path):
    assert discover_roles(tmp_path / "does-not-exist") == []


def test_discover_roles_path_that_is_a_file_returns_empty_list(tmp_path):
    not_a_dir = tmp_path / "roles.txt"
    not_a_dir.write_text("oops")

    assert discover_roles(not_a_dir) == []
