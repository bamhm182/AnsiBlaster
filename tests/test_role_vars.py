from __future__ import annotations

from ansiblaster.role_vars import discover_role_variables

from .conftest import make_role


def test_discover_role_variables_parses_yml(tmp_path):
    make_role(
        tmp_path,
        "apache",
        argument_specs={
            "apache_listen_port": {"type": "int", "default": 80, "description": "Listen port"},
        },
    )

    result = discover_role_variables(tmp_path / "roles", ["apache"])

    assert result == {
        "apache": {
            "apache_listen_port": {
                "type": "int",
                "default": 80,
                "required": False,
                "description": "Listen port",
            }
        }
    }


def test_discover_role_variables_parses_yaml_extension(tmp_path):
    role_dir = tmp_path / "roles" / "apache"
    (role_dir / "tasks").mkdir(parents=True)
    (role_dir / "tasks" / "main.yml").write_text("---\n- name: noop\n  ansible.builtin.debug:\n")
    (role_dir / "meta").mkdir(parents=True)
    (role_dir / "meta" / "argument_specs.yaml").write_text(
        "argument_specs:\n  main:\n    options:\n      foo:\n        type: str\n"
    )

    result = discover_role_variables(tmp_path / "roles", ["apache"])

    assert "apache" in result
    assert result["apache"]["foo"]["type"] == "str"


def test_discover_role_variables_missing_file_yields_no_entry(tmp_path):
    make_role(tmp_path, "apache")

    result = discover_role_variables(tmp_path / "roles", ["apache"])

    assert result == {}


def test_discover_role_variables_malformed_yaml_yields_no_entry(tmp_path):
    role_dir = tmp_path / "roles" / "apache"
    (role_dir / "tasks").mkdir(parents=True)
    (role_dir / "tasks" / "main.yml").write_text("---\n- name: noop\n  ansible.builtin.debug:\n")
    (role_dir / "meta").mkdir(parents=True)
    (role_dir / "meta" / "argument_specs.yml").write_text("{ not: valid: yaml")

    result = discover_role_variables(tmp_path / "roles", ["apache"])

    assert result == {}


def test_discover_role_variables_wrong_shape_yields_no_entry(tmp_path):
    role_dir = tmp_path / "roles" / "apache"
    (role_dir / "tasks").mkdir(parents=True)
    (role_dir / "tasks" / "main.yml").write_text("---\n- name: noop\n  ansible.builtin.debug:\n")
    (role_dir / "meta").mkdir(parents=True)
    # Valid YAML, but argument_specs.main.options isn't a dict.
    (role_dir / "meta" / "argument_specs.yml").write_text(
        "argument_specs:\n  main:\n    options: not-a-dict\n"
    )

    result = discover_role_variables(tmp_path / "roles", ["apache"])

    assert result == {}


def test_discover_role_variables_missing_keys_get_safe_fallbacks(tmp_path):
    make_role(tmp_path, "apache", argument_specs={"bare_var": {}})

    result = discover_role_variables(tmp_path / "roles", ["apache"])

    assert result["apache"]["bare_var"] == {
        "type": "str",
        "default": None,
        "required": False,
        "description": "",
    }


def test_discover_role_variables_required_true_no_default(tmp_path):
    make_role(
        tmp_path,
        "apache",
        argument_specs={"admin_email": {"type": "str", "required": True}},
    )

    result = discover_role_variables(tmp_path / "roles", ["apache"])

    spec = result["apache"]["admin_email"]
    assert spec["required"] is True
    assert spec["default"] is None


def test_discover_role_variables_mixes_roles_with_and_without_specs(tmp_path):
    make_role(tmp_path, "apache", argument_specs={"port": {"type": "int", "default": 80}})
    make_role(tmp_path, "docker-host")

    result = discover_role_variables(tmp_path / "roles", ["apache", "docker-host"])

    assert set(result.keys()) == {"apache"}


def test_discover_role_variables_skips_non_dict_option_entry(tmp_path):
    make_role(tmp_path, "apache", argument_specs={"good": {"type": "str"}, "bad": "not-a-dict"})

    result = discover_role_variables(tmp_path / "roles", ["apache"])

    assert set(result["apache"].keys()) == {"good"}
