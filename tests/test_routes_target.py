from __future__ import annotations

import socket


def _unused_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def test_check_port_reports_open(client):
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    try:
        port = server.getsockname()[1]
        response = client.get("/target/check-port", params={"host": "127.0.0.1", "port": port})
        assert response.status_code == 200
        assert response.json() == {"open": True}
    finally:
        server.close()


def test_check_port_reports_closed(client):
    response = client.get(
        "/target/check-port", params={"host": "127.0.0.1", "port": _unused_port()}
    )
    assert response.status_code == 200
    assert response.json() == {"open": False}
