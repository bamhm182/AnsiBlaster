from __future__ import annotations

import pytest
import yaml
from fastapi.testclient import TestClient

from ansiblaster.app import app
from ansiblaster.settings import get_settings


@pytest.fixture
def make_client(tmp_path, monkeypatch):
    """Factory for a TestClient wired to an isolated roles/playbooks/artifacts/db under
    tmp_path. Call with extra ANSIBLASTER_* env vars (e.g. make_client(ANSIBLASTER_DEFAULTS__SSH__USERNAME="deploy"))
    to set them *before* the app's lifespan loads settings -- plain `client` below can't do
    that, since by the time a test body runs, its TestClient has already started.

    `app` is the module-level FastAPI singleton (routes are registered once at import time),
    but its lifespan re-reads settings and rebuilds app.state (DB engine, JobManager) on every
    `with TestClient(app)` entry -- so per-test env vars here are enough for isolation without
    needing a fresh app instance per test.
    """

    def _make_client(**extra_env: str) -> TestClient:
        get_settings.cache_clear()
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("ANSIBLASTER_CONFIG", raising=False)
        monkeypatch.setenv("ANSIBLASTER_ANSIBLE__ROLES_PATH", str(tmp_path / "roles"))
        monkeypatch.setenv("ANSIBLASTER_ANSIBLE__PLAYBOOKS_PATH", str(tmp_path / "playbooks"))
        monkeypatch.setenv("ANSIBLASTER_ANSIBLE__ARTIFACTS_PATH", str(tmp_path / "artifacts"))
        monkeypatch.setenv("ANSIBLASTER_DATABASE__PATH", str(tmp_path / "db.sqlite3"))
        for key, value in extra_env.items():
            monkeypatch.setenv(key, value)
        return TestClient(app)

    yield _make_client

    get_settings.cache_clear()


@pytest.fixture
def client(make_client):
    with make_client() as test_client:
        yield test_client


def make_role(tmp_path, name: str, *, argument_specs: dict | None = None) -> None:
    role_dir = tmp_path / "roles" / name / "tasks"
    role_dir.mkdir(parents=True)
    (role_dir / "main.yml").write_text("---\n- name: noop\n  ansible.builtin.debug:\n")

    if argument_specs is not None:
        meta_dir = tmp_path / "roles" / name / "meta"
        meta_dir.mkdir(parents=True)
        (meta_dir / "argument_specs.yml").write_text(
            yaml.safe_dump({"argument_specs": {"main": {"options": argument_specs}}})
        )


def make_playbook(tmp_path, name: str, roles: list[str]) -> None:
    playbooks_dir = tmp_path / "playbooks"
    playbooks_dir.mkdir(parents=True, exist_ok=True)
    roles_yaml = "\n".join(f"    - {role}" for role in roles)
    (playbooks_dir / f"{name}.yml").write_text(f"---\n- hosts: all\n  roles:\n{roles_yaml}\n")
