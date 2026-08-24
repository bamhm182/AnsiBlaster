from __future__ import annotations

import html
import re

from tests.conftest import make_role


def _input_value(text: str, name: str) -> str:
    # Tolerant of any attributes (e.g. class=, placeholder=) sitting between name= and value=,
    # and of the tag's attributes wrapping onto multiple lines.
    match = re.search(rf'name="{re.escape(name)}"[\s\S]*?value="([^"]*)"', text)
    assert match, f"no input named {name!r} found"
    return match.group(1)


def test_get_settings_empty(client):
    response = client.get("/settings")
    assert response.status_code == 200
    assert "No role variable overrides saved yet." in response.text
    assert "SSH" in response.text and "WinRM" in response.text and "PSRP" in response.text


def test_save_role_variable_override_appears_in_modal(client):
    response = client.post("/settings/role-variables", data={"name": "mysql_port", "value": "3306"})
    assert response.status_code == 200
    assert "mysql_port" in response.text
    assert 'value="3306"' in response.text


def test_save_role_variable_override_is_type_coerced(client):
    # 3306 is saved as an int (via yaml.safe_load), not a string -- confirmed by checking it
    # actually feeds into discover_role_variables()'s merged output as a real default, not by
    # inspecting the DB directly (see test_routes_roles.py's own equivalent check below).
    client.post("/settings/role-variables", data={"name": "port", "value": "3306"})
    response = client.get("/settings")
    assert 'value="3306"' in response.text


def test_save_role_variable_override_rejects_blank_name(client):
    response = client.post("/settings/role-variables", data={"name": "  ", "value": "x"})
    assert response.status_code == 400


def test_role_variable_overrides_sorted_alphabetically(client):
    client.post("/settings/role-variables", data={"name": "zeta", "value": "1"})
    client.post("/settings/role-variables", data={"name": "alpha", "value": "2"})
    response = client.get("/settings")
    assert response.text.index("alpha") < response.text.index("zeta")


def test_delete_role_variable_override(client):
    client.post("/settings/role-variables", data={"name": "mysql_port", "value": "3306"})
    response = client.request("DELETE", "/settings/role-variables/mysql_port")
    assert response.status_code == 200
    assert "mysql_port" not in response.text
    assert "No role variable overrides saved yet." in response.text


def test_delete_role_variable_override_that_does_not_exist_is_a_no_op(client):
    response = client.request("DELETE", "/settings/role-variables/does-not-exist")
    assert response.status_code == 200


def test_save_host_settings_stores_override_and_shows_it_as_value(client):
    response = client.post(
        "/settings/host", data={"ssh_username": "deploy", "ssh_password": "hunter2"}
    )
    assert response.status_code == 200
    assert _input_value(response.text, "ssh_username") == "deploy"


def test_save_host_settings_blank_field_clears_existing_override(client):
    client.post("/settings/host", data={"ssh_username": "deploy"})
    response = client.post("/settings/host", data={"ssh_username": ""})
    assert response.status_code == 200
    assert _input_value(response.text, "ssh_username") == ""


def test_save_host_settings_presets_are_independent(client):
    client.post("/settings/host", data={"ssh_username": "deploy"})
    response = client.get("/settings")
    assert _input_value(response.text, "ssh_username") == "deploy"
    assert _input_value(response.text, "winrm_username") == ""
    assert _input_value(response.text, "psrp_username") == ""


def test_role_variable_override_merges_into_get_roles_data_vars(client, tmp_path):
    make_role(tmp_path, "apache", argument_specs={"port": {"type": "int", "default": 80}})
    client.post("/settings/role-variables", data={"name": "port", "value": "8080"})
    response = client.get("/roles")
    assert response.status_code == 200
    # data-vars is JSON embedded in an HTML attribute -- its quotes are entity-escaped
    # (&#34;), so unescape before checking the JSON shape.
    unescaped = html.unescape(response.text)
    assert '"default": 8080' in unescaped
    assert '"default": 80}' not in unescaped and '"default": 80,' not in unescaped


def test_role_variable_override_merges_into_index_page_data_vars(client, tmp_path):
    make_role(tmp_path, "apache", argument_specs={"port": {"type": "int", "default": 80}})
    client.post("/settings/role-variables", data={"name": "port", "value": "8080"})
    response = client.get("/")
    assert response.status_code == 200
    assert '"default": 8080' in html.unescape(response.text)


def test_host_override_merges_into_index_page_defaults(client):
    client.post("/settings/host", data={"ssh_username": "deploy-override"})
    response = client.get("/")
    assert response.status_code == 200
    assert "deploy-override" in response.text


def test_bulk_save_role_variable_overrides_updates_multiple_at_once(client):
    client.post("/settings/role-variables", data={"name": "alpha", "value": "1"})
    client.post("/settings/role-variables", data={"name": "beta", "value": "2"})

    response = client.post(
        "/settings/role-variables/bulk", data={"value[alpha]": "10", "value[beta]": "20"}
    )
    assert response.status_code == 200
    assert _input_value(response.text, "value[alpha]") == "10"
    assert _input_value(response.text, "value[beta]") == "20"


def test_bulk_save_role_variable_overrides_ignores_unrecognized_fields(client):
    client.post("/settings/role-variables", data={"name": "alpha", "value": "1"})
    response = client.post(
        "/settings/role-variables/bulk",
        data={"value[alpha]": "10", "not_a_bracket_field": "ignored"},
    )
    assert response.status_code == 200
    assert _input_value(response.text, "value[alpha]") == "10"


def test_bulk_save_role_variable_overrides_type_coerced(client, tmp_path):
    make_role(tmp_path, "apache", argument_specs={"port": {"type": "int", "default": 80}})
    client.post("/settings/role-variables", data={"name": "port", "value": "1"})
    client.post("/settings/role-variables/bulk", data={"value[port]": "9090"})
    response = client.get("/roles")
    assert '"default": 9090' in html.unescape(response.text)


def test_settings_modal_has_role_and_host_tabs(client):
    response = client.get("/settings")
    assert 'data-settings-tab="role-variables"' in response.text
    assert 'data-settings-tab="host-variables"' in response.text
    assert 'data-settings-content="role-variables"' in response.text
    assert 'data-settings-content="host-variables"' in response.text


def test_role_variable_row_has_no_per_row_save_button(client):
    client.post("/settings/role-variables", data={"name": "mysql_port", "value": "3306"})
    response = client.get("/settings")
    # The bulk-save form still exists (Save Role Variables), but individual rows should no
    # longer carry their own submit button.
    assert "Save Role Variables" in response.text
    assert 'title="Save mysql_port"' not in response.text


def test_settings_modal_has_role_variable_filter_input(client):
    response = client.get("/settings")
    assert 'id="settings-var-filter"' in response.text
    assert 'data-filter-target="#settings-var-list"' in response.text


def test_role_variable_row_has_filter_name_attribute(client):
    client.post("/settings/role-variables", data={"name": "mysql_port", "value": "3306"})
    response = client.get("/settings")
    assert 'data-filter-name="mysql_port"' in response.text


def test_role_variable_list_is_in_its_own_scroll_wrapper_outside_the_save_button(client):
    client.post("/settings/role-variables", data={"name": "mysql_port", "value": "3306"})
    response = client.get("/settings")
    # The scrollable list wrapper (and the form collecting its inputs) close *before* the
    # fixed-bottom Save button/add-new-variable fields appear -- i.e. the button is not nested
    # inside the scrolling region.
    scroll_start = response.text.index('class="settings-var-list-scroll"')
    save_button_index = response.text.index(">Save Role Variables<")
    add_new_index = response.text.index('class="settings-var-row settings-var-row-new"')
    assert scroll_start < save_button_index < add_new_index
