from __future__ import annotations

import json

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
