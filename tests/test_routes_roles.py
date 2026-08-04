from __future__ import annotations

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
