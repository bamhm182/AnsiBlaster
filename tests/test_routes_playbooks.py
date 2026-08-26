from __future__ import annotations

import json
import logging

from tests.conftest import make_playbook


def test_list_playbooks_returns_discovered_playbooks_with_roles_data_attribute(client, tmp_path):
    make_playbook(tmp_path, "lamp", ["apache", "mysql", "php"])

    response = client.get("/playbooks")

    assert response.status_code == 200
    assert "lamp" in response.text
    assert 'data-playbook="lamp"' in response.text
    # The roles list is embedded (HTML-escaped) as JSON for the client-side check script.
    assert json.dumps(["apache", "mysql", "php"]).replace('"', "&#34;") in response.text


def test_list_playbooks_empty(client):
    response = client.get("/playbooks")

    assert response.status_code == 200
    assert "No playbooks found" in response.text


def test_playbook_files_lists_its_own_file(client, tmp_path):
    make_playbook(tmp_path, "lamp", ["apache", "mysql", "php"])

    response = client.get("/playbooks/lamp/files")

    assert response.status_code == 200
    assert "lamp.yml" in response.text


def test_playbook_files_unknown_playbook_404s(client):
    response = client.get("/playbooks/does-not-exist/files")

    assert response.status_code == 404


def test_playbook_file_returns_content(client, tmp_path):
    make_playbook(tmp_path, "lamp", ["apache", "mysql", "php"])

    response = client.get("/playbooks/lamp/file", params={"path": "lamp.yml"})

    assert response.status_code == 200
    assert "apache" in response.text


def test_list_playbooks_logs_the_loaded_count_at_info(client, tmp_path, caplog):
    make_playbook(tmp_path, "lamp", ["apache", "mysql", "php"])

    with caplog.at_level(logging.INFO, logger="ansiblaster.routes.playbooks"):
        client.get("/playbooks")

    assert "Loaded 1 playbook(s)" in caplog.text


def test_list_playbooks_logs_missing_directory_at_info(client, caplog):
    # No make_playbook() call -- the configured playbooks directory is never created, so this
    # exercises the "missing dir" branch.
    with caplog.at_level(logging.INFO, logger="ansiblaster.routes.playbooks"):
        client.get("/playbooks")

    assert "does not exist" in caplog.text
