from __future__ import annotations

from ansiblaster.db import session_scope
from ansiblaster.jobs import stdout_log_path
from ansiblaster.models import Run
from tests.conftest import make_role


class _FakeRunner:
    def __init__(self, status: str = "successful", rc: int | None = 0):
        self.status = status
        self.rc = rc


def _fake_run_async(calls, *, stdout_lines=(), final_status="successful", rc=0, finish=True):
    """Same recording/driving fake used in test_jobs.py, reused here through the real routes."""

    def _fake(**kwargs):
        calls.append(kwargs)
        kwargs["status_handler"]({"status": "running"}, runner_config=None)
        for line in stdout_lines:
            kwargs["event_handler"]({"stdout": line})
        if finish:
            kwargs["finished_callback"](_FakeRunner(status=final_status, rc=rc))
            return (None, _FakeRunner(status=final_status, rc=rc))
        return (None, _FakeRunner(status="running", rc=None))

    return _fake


def _base_form(**overrides):
    form = {
        "target_os": "linux",
        "target_host": "192.168.1.10",
        "target_port": "22",
        "target_user": "root",
        "target_password": "hunter2",
    }
    form.update(overrides)
    return form


def _only_run(client) -> Run:
    with session_scope(client.app.state.session_factory) as session:
        run = session.query(Run).one()
        session.expunge(run)
        return run


def test_create_run_success(client, tmp_path, monkeypatch):
    make_role(tmp_path, "docker-host")
    monkeypatch.setattr("ansiblaster.jobs.ansible_runner.run_async", _fake_run_async([]))

    response = client.post("/runs", data=_base_form(roles=["docker-host"]))

    assert response.status_code == 201
    assert "docker-host" in response.text
    assert "successful" in response.text


def test_create_run_ignores_a_submitted_playbooks_field(client, tmp_path, monkeypatch):
    """Playbooks aren't tracked on a run at all (see CLAUDE.md's "Playbooks (role presets)"
    section) -- the current UI never submits playbooks[], but a stray/legacy one shouldn't
    break anything if it somehow shows up."""
    make_role(tmp_path, "apache")
    make_role(tmp_path, "mysql")
    monkeypatch.setattr("ansiblaster.jobs.ansible_runner.run_async", _fake_run_async([]))

    response = client.post("/runs", data=_base_form(roles=["apache", "mysql"], playbooks=["lamp"]))

    assert response.status_code == 201
    run = _only_run(client)
    assert run.roles == ["apache", "mysql"]
    assert not hasattr(run, "playbooks")


def test_create_run_shows_connection_label_not_raw_os(client, tmp_path, monkeypatch):
    """The human-readable target line shows the connection preset (see
    inventory.connection_label), not the raw target_os enum value -- data-target-os (used by
    loadRunIntoDeploy()) still carries the raw value, deliberately, so this only checks for the
    label's presence rather than the raw value's absence."""
    make_role(tmp_path, "iis")
    monkeypatch.setattr("ansiblaster.jobs.ansible_runner.run_async", _fake_run_async([]))

    response = client.post(
        "/runs",
        data=_base_form(
            target_os="windows_psrp", target_port="5986", roles=["iis"], target_user="Administrator"
        ),
    )

    assert response.status_code == 201
    assert "PSRP (Secure)" in response.text


def test_create_run_requires_at_least_one_role(client, tmp_path, monkeypatch):
    make_role(tmp_path, "docker-host")
    monkeypatch.setattr("ansiblaster.jobs.ansible_runner.run_async", _fake_run_async([]))

    response = client.post("/runs", data=_base_form())

    assert response.status_code == 400


def test_create_run_rejects_invalid_os(client, monkeypatch):
    monkeypatch.setattr("ansiblaster.jobs.ansible_runner.run_async", _fake_run_async([]))

    response = client.post("/runs", data=_base_form(target_os="plan9", roles=["docker-host"]))

    assert response.status_code == 400


def test_create_run_rejects_non_numeric_port(client, monkeypatch):
    monkeypatch.setattr("ansiblaster.jobs.ansible_runner.run_async", _fake_run_async([]))

    response = client.post(
        "/runs", data=_base_form(target_port="not-a-number", roles=["docker-host"])
    )

    assert response.status_code == 400


def test_create_run_requires_host_and_user(client, monkeypatch):
    monkeypatch.setattr("ansiblaster.jobs.ansible_runner.run_async", _fake_run_async([]))

    response = client.post("/runs", data=_base_form(target_host="", roles=["docker-host"]))

    assert response.status_code == 400


def test_create_run_parses_vars_bracket_notation(client, tmp_path, monkeypatch):
    make_role(tmp_path, "apache", argument_specs={"apache_listen_port": {"type": "int"}})
    calls: list[dict] = []
    monkeypatch.setattr("ansiblaster.jobs.ansible_runner.run_async", _fake_run_async(calls))

    response = client.post(
        "/runs",
        data=_base_form(roles=["apache"], **{"vars[apache][apache_listen_port]": "8080"}),
    )

    assert response.status_code == 201
    run = _only_run(client)
    assert run.variables == {"apache": {"apache_listen_port": 8080}}
    [play] = calls[0]["playbook"]
    assert play["roles"] == [{"role": "apache", "vars": {"apache_listen_port": 8080}}]


def test_create_run_coerces_bool_and_float(client, tmp_path, monkeypatch):
    make_role(
        tmp_path,
        "apache",
        argument_specs={
            "enable_tls": {"type": "bool"},
            "load_factor": {"type": "float"},
        },
    )
    monkeypatch.setattr("ansiblaster.jobs.ansible_runner.run_async", _fake_run_async([]))

    response = client.post(
        "/runs",
        data=_base_form(
            roles=["apache"],
            **{
                "vars[apache][enable_tls]": "true",
                "vars[apache][load_factor]": "1.5",
            },
        ),
    )

    assert response.status_code == 201
    run = _only_run(client)
    assert run.variables == {"apache": {"enable_tls": True, "load_factor": 1.5}}


def test_create_run_rejects_missing_required_variable_with_400(client, tmp_path, monkeypatch):
    make_role(tmp_path, "apache", argument_specs={"admin_email": {"type": "str", "required": True}})
    monkeypatch.setattr("ansiblaster.jobs.ansible_runner.run_async", _fake_run_async([]))

    response = client.post("/runs", data=_base_form(roles=["apache"]))

    assert response.status_code == 400
    assert "admin_email" in response.text


def test_create_run_rejects_invalid_int_value_with_400(client, tmp_path, monkeypatch):
    make_role(tmp_path, "apache", argument_specs={"apache_listen_port": {"type": "int"}})
    monkeypatch.setattr("ansiblaster.jobs.ansible_runner.run_async", _fake_run_async([]))

    response = client.post(
        "/runs",
        data=_base_form(roles=["apache"], **{"vars[apache][apache_listen_port]": "not-a-number"}),
    )

    assert response.status_code == 400


def test_create_run_omits_blank_optional_variable_rather_than_storing_empty_string(
    client, tmp_path, monkeypatch
):
    make_role(
        tmp_path, "apache", argument_specs={"apache_listen_port": {"type": "int", "default": 80}}
    )
    monkeypatch.setattr("ansiblaster.jobs.ansible_runner.run_async", _fake_run_async([]))

    response = client.post(
        "/runs", data=_base_form(roles=["apache"], **{"vars[apache][apache_listen_port]": ""})
    )

    assert response.status_code == 201
    run = _only_run(client)
    assert run.variables == {}


def test_create_run_ignores_vars_for_a_role_not_in_roles_list(client, tmp_path, monkeypatch):
    make_role(tmp_path, "apache", argument_specs={"apache_listen_port": {"type": "int"}})
    make_role(tmp_path, "mysql")
    monkeypatch.setattr("ansiblaster.jobs.ansible_runner.run_async", _fake_run_async([]))

    response = client.post(
        "/runs",
        data=_base_form(roles=["mysql"], **{"vars[apache][apache_listen_port]": "8080"}),
    )

    assert response.status_code == 201
    run = _only_run(client)
    assert run.variables == {}


def test_create_run_variables_defaults_to_empty_dict_for_role_with_no_argument_specs(
    client, tmp_path, monkeypatch
):
    make_role(tmp_path, "docker-host")
    monkeypatch.setattr("ansiblaster.jobs.ansible_runner.run_async", _fake_run_async([]))

    response = client.post("/runs", data=_base_form(roles=["docker-host"]))

    assert response.status_code == 201
    run = _only_run(client)
    assert run.variables == {}


def test_run_detail_not_found(client):
    response = client.get("/runs/does-not-exist")

    assert response.status_code == 404


def test_run_detail_returns_run(client, tmp_path, monkeypatch):
    make_role(tmp_path, "docker-host")
    monkeypatch.setattr("ansiblaster.jobs.ansible_runner.run_async", _fake_run_async([]))
    client.post("/runs", data=_base_form(roles=["docker-host"]))
    run = _only_run(client)

    response = client.get(f"/runs/{run.id}")

    assert response.status_code == 200
    assert run.id in response.text
    assert "docker-host" in response.text


def test_run_log_returns_stdout_file_contents(client, tmp_path, monkeypatch):
    make_role(tmp_path, "docker-host")
    monkeypatch.setattr("ansiblaster.jobs.ansible_runner.run_async", _fake_run_async([]))
    client.post("/runs", data=_base_form(roles=["docker-host"]))
    run = _only_run(client)

    log_path = stdout_log_path(run)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text("TASK [docker-host] ***\nok: [target]\n")

    response = client.get(f"/runs/{run.id}/log")

    assert response.status_code == 200
    assert response.text == "TASK [docker-host] ***\nok: [target]\n"


def test_run_log_missing_file_returns_empty(client, tmp_path, monkeypatch):
    make_role(tmp_path, "docker-host")
    monkeypatch.setattr("ansiblaster.jobs.ansible_runner.run_async", _fake_run_async([]))
    client.post("/runs", data=_base_form(roles=["docker-host"]))
    run = _only_run(client)

    response = client.get(f"/runs/{run.id}/log")

    assert response.status_code == 200
    assert response.text == ""


def test_run_stream_unknown_job_404(client):
    response = client.get("/runs/does-not-exist/stream")

    assert response.status_code == 404


def test_run_stream_returns_lines_then_done_event(client, tmp_path, monkeypatch):
    make_role(tmp_path, "docker-host")
    monkeypatch.setattr(
        "ansiblaster.jobs.ansible_runner.run_async",
        _fake_run_async([], stdout_lines=["line one", "line two"]),
    )
    client.post("/runs", data=_base_form(roles=["docker-host"]))
    run = _only_run(client)

    response = client.get(f"/runs/{run.id}/stream")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "data: line one" in response.text
    assert "data: line two" in response.text
    assert "event: done" in response.text


def test_cancel_unknown_job_404(client):
    response = client.post("/runs/does-not-exist/cancel")

    assert response.status_code == 404


def test_cancel_known_job_accepts_request(client, tmp_path, monkeypatch):
    make_role(tmp_path, "docker-host")
    monkeypatch.setattr(
        "ansiblaster.jobs.ansible_runner.run_async",
        _fake_run_async([], finish=False),
    )
    client.post("/runs", data=_base_form(roles=["docker-host"]))
    run = _only_run(client)

    response = client.post(f"/runs/{run.id}/cancel")

    assert response.status_code == 200
    assert "Cancel requested" in response.text
    job = client.app.state.job_manager.get_job(run.id)
    assert job.cancel_event.is_set()


def test_list_runs_shows_created_run(client, tmp_path, monkeypatch):
    make_role(tmp_path, "docker-host")
    monkeypatch.setattr("ansiblaster.jobs.ansible_runner.run_async", _fake_run_async([]))
    client.post("/runs", data=_base_form(roles=["docker-host"]))

    response = client.get("/runs")

    assert response.status_code == 200
    assert "192.168.1.10" in response.text
