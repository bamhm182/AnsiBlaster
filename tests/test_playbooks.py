from __future__ import annotations

import textwrap

from ansiblaster.playbooks import discover_playbooks


def _write_playbook(playbooks_dir, filename, content):
    playbooks_dir.mkdir(parents=True, exist_ok=True)
    (playbooks_dir / filename).write_text(textwrap.dedent(content))


def test_discover_playbooks_parses_string_role_entries(tmp_path):
    playbooks_dir = tmp_path / "playbooks"
    _write_playbook(
        playbooks_dir,
        "lamp.yml",
        """
        ---
        - name: LAMP Stack
          hosts: all
          roles:
            - apache
            - mysql
            - php
        """,
    )

    assert discover_playbooks(playbooks_dir) == {"lamp": ["apache", "mysql", "php"]}


def test_discover_playbooks_parses_role_dict_entries_and_ignores_vars(tmp_path):
    playbooks_dir = tmp_path / "playbooks"
    _write_playbook(
        playbooks_dir,
        "web.yaml",
        """
        ---
        - hosts: all
          roles:
            - role: apache
              vars:
                port: 8080
            - mysql
        """,
    )

    assert discover_playbooks(playbooks_dir) == {"web": ["apache", "mysql"]}


def test_discover_playbooks_aggregates_and_dedupes_across_multiple_plays(tmp_path):
    playbooks_dir = tmp_path / "playbooks"
    _write_playbook(
        playbooks_dir,
        "multi.yml",
        """
        ---
        - hosts: web
          roles:
            - apache
            - php
        - hosts: db
          roles:
            - mysql
            - apache
        """,
    )

    assert discover_playbooks(playbooks_dir) == {"multi": ["apache", "php", "mysql"]}


def test_discover_playbooks_skips_files_with_no_roles_key(tmp_path):
    playbooks_dir = tmp_path / "playbooks"
    _write_playbook(
        playbooks_dir,
        "tasks-only.yml",
        """
        ---
        - hosts: all
          tasks:
            - name: do a thing
              ansible.builtin.debug:
        """,
    )

    assert discover_playbooks(playbooks_dir) == {}


def test_discover_playbooks_skips_malformed_yaml_but_keeps_valid_ones(tmp_path):
    playbooks_dir = tmp_path / "playbooks"
    _write_playbook(playbooks_dir, "broken.yml", "roles: [unterminated")
    _write_playbook(
        playbooks_dir,
        "lamp.yml",
        """
        ---
        - hosts: all
          roles:
            - apache
        """,
    )

    assert discover_playbooks(playbooks_dir) == {"lamp": ["apache"]}


def test_discover_playbooks_ignores_non_yaml_files(tmp_path):
    playbooks_dir = tmp_path / "playbooks"
    _write_playbook(
        playbooks_dir,
        "lamp.yml",
        """
        ---
        - hosts: all
          roles:
            - apache
        """,
    )
    (playbooks_dir / "README.md").write_text("not a playbook")

    assert discover_playbooks(playbooks_dir) == {"lamp": ["apache"]}


def test_discover_playbooks_missing_directory_returns_empty_dict(tmp_path):
    assert discover_playbooks(tmp_path / "does-not-exist") == {}


def test_discover_playbooks_name_is_filename_stem(tmp_path):
    playbooks_dir = tmp_path / "playbooks"
    _write_playbook(
        playbooks_dir,
        "my-cool-stack.yaml",
        """
        ---
        - hosts: all
          roles:
            - apache
        """,
    )

    assert list(discover_playbooks(playbooks_dir).keys()) == ["my-cool-stack"]
