from __future__ import annotations

import pytest

from ansiblaster.browse import (
    NotFound,
    list_playbook_files,
    list_role_files,
    read_playbook_file,
    read_role_file,
)


def _make_role(roles_dir, name):
    role_dir = roles_dir / name
    (role_dir / "tasks").mkdir(parents=True)
    (role_dir / "tasks" / "main.yml").write_text("---\n- name: noop\n")
    (role_dir / "defaults").mkdir()
    (role_dir / "defaults" / "main.yml").write_text("---\nfoo: bar\n")
    return role_dir


def _make_playbook(playbooks_dir, name):
    playbooks_dir.mkdir(parents=True, exist_ok=True)
    path = playbooks_dir / f"{name}.yml"
    path.write_text("---\n- hosts: all\n  roles:\n    - apache\n")
    return path


def test_list_role_files_returns_sorted_relative_paths(tmp_path):
    roles_dir = tmp_path / "roles"
    _make_role(roles_dir, "docker-host")

    assert list_role_files(roles_dir, "docker-host") == [
        "defaults/main.yml",
        "tasks/main.yml",
    ]


def test_read_role_file_returns_content(tmp_path):
    roles_dir = tmp_path / "roles"
    _make_role(roles_dir, "docker-host")

    assert read_role_file(roles_dir, "docker-host", "tasks/main.yml") == "---\n- name: noop\n"


def test_list_role_files_missing_role_raises_not_found(tmp_path):
    roles_dir = tmp_path / "roles"
    roles_dir.mkdir()

    with pytest.raises(NotFound):
        list_role_files(roles_dir, "does-not-exist")


def test_list_role_files_rejects_a_directory_that_isnt_a_role(tmp_path):
    roles_dir = tmp_path / "roles"
    (roles_dir / "not-a-role").mkdir(parents=True)

    with pytest.raises(NotFound):
        list_role_files(roles_dir, "not-a-role")


@pytest.mark.parametrize(
    "role_name",
    ["../../etc", "..%2F..%2Fetc"],
)
def test_list_role_files_rejects_traversal_in_role_name(tmp_path, role_name):
    roles_dir = tmp_path / "roles"
    _make_role(roles_dir, "docker-host")

    with pytest.raises(NotFound):
        list_role_files(roles_dir, role_name)


def test_read_role_file_rejects_traversal_in_path(tmp_path):
    roles_dir = tmp_path / "roles"
    _make_role(roles_dir, "docker-host")
    (tmp_path / "secret.txt").write_text("nope")

    with pytest.raises(NotFound):
        read_role_file(roles_dir, "docker-host", "../../secret.txt")


def test_read_role_file_rejects_absolute_path(tmp_path):
    roles_dir = tmp_path / "roles"
    _make_role(roles_dir, "docker-host")
    outside = tmp_path / "secret.txt"
    outside.write_text("nope")

    with pytest.raises(NotFound):
        read_role_file(roles_dir, "docker-host", str(outside))


def test_read_role_file_missing_file_raises_not_found(tmp_path):
    roles_dir = tmp_path / "roles"
    _make_role(roles_dir, "docker-host")

    with pytest.raises(NotFound):
        read_role_file(roles_dir, "docker-host", "tasks/does-not-exist.yml")


def test_list_playbook_files_returns_its_own_filename(tmp_path):
    playbooks_dir = tmp_path / "playbooks"
    _make_playbook(playbooks_dir, "lamp")

    assert list_playbook_files(playbooks_dir, "lamp") == ["lamp.yml"]


def test_read_playbook_file_returns_content(tmp_path):
    playbooks_dir = tmp_path / "playbooks"
    path = _make_playbook(playbooks_dir, "lamp")

    assert read_playbook_file(playbooks_dir, "lamp", "lamp.yml") == path.read_text()


def test_list_playbook_files_missing_playbook_raises_not_found(tmp_path):
    playbooks_dir = tmp_path / "playbooks"
    playbooks_dir.mkdir()

    with pytest.raises(NotFound):
        list_playbook_files(playbooks_dir, "does-not-exist")


def test_read_playbook_file_rejects_traversal_in_role_name(tmp_path):
    playbooks_dir = tmp_path / "playbooks"
    _make_playbook(playbooks_dir, "lamp")
    (tmp_path / "secret.yml").write_text("nope")

    with pytest.raises(NotFound):
        list_playbook_files(playbooks_dir, "../secret")
