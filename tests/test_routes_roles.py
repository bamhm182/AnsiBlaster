from __future__ import annotations

import logging

from tests.conftest import make_role


def test_list_roles_returns_discovered_roles(client, tmp_path):
    make_role(tmp_path, "docker-host")
    make_role(tmp_path, "apache")

    response = client.get("/roles")

    assert response.status_code == 200
    assert "docker-host" in response.text
    assert "apache" in response.text


def test_list_roles_empty(client):
    response = client.get("/roles")

    assert response.status_code == 200
    assert "No roles found" in response.text


def test_list_roles_bakes_data_vars_attribute_from_argument_specs(client, tmp_path):
    make_role(tmp_path, "apache", argument_specs={"apache_listen_port": {"type": "int"}})

    response = client.get("/roles")

    assert response.status_code == 200
    assert "data-vars=" in response.text
    assert "apache_listen_port" in response.text


def test_role_with_no_argument_specs_gets_empty_data_vars(client, tmp_path):
    make_role(tmp_path, "docker-host")

    response = client.get("/roles")

    assert response.status_code == 200
    assert "data-vars='{}'" in response.text


def test_role_files_lists_the_roles_files(client, tmp_path):
    make_role(tmp_path, "docker-host")

    response = client.get("/roles/docker-host/files")

    assert response.status_code == 200
    assert "tasks/main.yml" in response.text
    # index.html's selectDefaultViewerFile() matches on this attribute to auto-select
    # tasks/main.yml when a role has more than one file.
    assert 'data-relpath="tasks/main.yml"' in response.text


def test_role_files_unknown_role_404s(client):
    response = client.get("/roles/does-not-exist/files")

    assert response.status_code == 404


def test_role_file_returns_content(client, tmp_path):
    make_role(tmp_path, "docker-host")

    response = client.get("/roles/docker-host/file", params={"path": "tasks/main.yml"})

    assert response.status_code == 200
    assert "noop" in response.text


def test_role_file_path_traversal_404s(client, tmp_path):
    make_role(tmp_path, "docker-host")
    (tmp_path / "secret.txt").write_text("nope")

    response = client.get("/roles/docker-host/file", params={"path": "../../secret.txt"})

    assert response.status_code == 404


def test_list_roles_logs_the_loaded_count_at_info(client, tmp_path, caplog):
    make_role(tmp_path, "docker-host")
    make_role(tmp_path, "apache")

    with caplog.at_level(logging.INFO, logger="ansiblaster.routes.roles"):
        client.get("/roles")

    assert "Loaded 2 role(s)" in caplog.text


def test_list_roles_logs_missing_directory_at_info(client, caplog):
    # No make_role() call -- the configured roles directory (under an isolated tmp_path, per
    # the client fixture) is never created, so this exercises the "missing dir" branch.
    with caplog.at_level(logging.INFO, logger="ansiblaster.routes.roles"):
        client.get("/roles")

    assert "does not exist" in caplog.text
