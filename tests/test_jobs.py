from __future__ import annotations

import asyncio
import os

import pytest

from ansiblaster.db import init_db, make_engine, make_session_factory, session_scope
from ansiblaster.jobs import STREAM_DONE, JobManager
from ansiblaster.models import Run, RunStatus, TargetOS


class _FakeRunner:
    """Stand-in for ansible_runner.runner.Runner -- only .status/.rc are ever read."""

    def __init__(self, status: str = "successful", rc: int | None = 0):
        self.status = status
        self.rc = rc


def _make_job_manager(tmp_path):
    tmp_path.mkdir(parents=True, exist_ok=True)
    engine = make_engine(str(tmp_path / "test.db"))
    init_db(engine)
    session_factory = make_session_factory(engine)

    manager = JobManager(
        session_factory=session_factory,
        roles_path=str(tmp_path / "roles"),
        artifacts_path=str(tmp_path / "artifacts"),
    )
    return manager, session_factory


def _fake_run_async_recorder(
    calls: list[dict], *, stdout_lines=(), final_status="successful", rc=0
):
    """Build a fake ansible_runner.run_async that records its kwargs and immediately drives
    the callbacks it was given, as if a run had already completed.
    """

    def _fake_run_async(**kwargs):
        calls.append(kwargs)
        kwargs["status_handler"]({"status": "running"}, runner_config=None)
        for line in stdout_lines:
            kwargs["event_handler"]({"stdout": line})
        kwargs["finished_callback"](_FakeRunner(status=final_status, rc=rc))
        return (None, _FakeRunner(status=final_status, rc=rc))

    return _fake_run_async


async def test_start_job_creates_run_row_and_marks_it_successful(tmp_path, monkeypatch):
    calls: list[dict] = []
    monkeypatch.setattr(
        "ansiblaster.jobs.ansible_runner.run_async",
        _fake_run_async_recorder(calls, final_status="successful", rc=0),
    )
    manager, session_factory = _make_job_manager(tmp_path)

    run = manager.start_job(
        target_os=TargetOS.LINUX,
        target_host="192.168.1.10",
        target_port=22,
        target_user="root",
        target_password="hunter2",
        roles=["docker-host"],
    )

    with session_scope(session_factory) as session:
        fetched = session.get(Run, run.id)
        assert fetched.status == RunStatus.SUCCESSFUL
        assert fetched.return_code == 0
        assert fetched.started_at is not None
        assert fetched.finished_at is not None
        assert fetched.artifact_dir == str(tmp_path / "artifacts" / run.id)


async def test_start_job_creates_private_data_dir_before_launching(tmp_path, monkeypatch):
    """Regression test: ansible-runner requires private_data_dir to already exist -- it
    does not create that top-level directory itself, only subdirectories under it. A real
    (non-mocked) run fails immediately if start_job() doesn't create it first.
    """
    calls: list[dict] = []
    monkeypatch.setattr(
        "ansiblaster.jobs.ansible_runner.run_async", _fake_run_async_recorder(calls)
    )
    manager, _ = _make_job_manager(tmp_path)

    run = manager.start_job(
        target_os=TargetOS.LINUX,
        target_host="192.168.1.10",
        target_port=22,
        target_user="root",
        target_password="hunter2",
        roles=["docker-host"],
    )

    private_data_dir = calls[0]["private_data_dir"]
    assert private_data_dir == str(tmp_path / "artifacts" / run.id)
    assert os.path.isdir(private_data_dir)


async def test_start_job_streams_stdout_lines_then_sentinel(tmp_path, monkeypatch):
    calls: list[dict] = []
    monkeypatch.setattr(
        "ansiblaster.jobs.ansible_runner.run_async",
        _fake_run_async_recorder(calls, stdout_lines=["line one", "line two"]),
    )
    manager, _ = _make_job_manager(tmp_path)

    run = manager.start_job(
        target_os=TargetOS.LINUX,
        target_host="192.168.1.10",
        target_port=22,
        target_user="root",
        target_password="hunter2",
        roles=["docker-host"],
    )

    job = manager.get_job(run.id)
    lines = []
    for _ in range(3):
        lines.append(await asyncio.wait_for(job.queue.get(), timeout=1))

    assert lines == ["line one", "line two", STREAM_DONE]


async def test_start_job_maps_ansible_runner_terminal_statuses(tmp_path, monkeypatch):
    for ansible_status, expected in [
        ("successful", RunStatus.SUCCESSFUL),
        ("failed", RunStatus.FAILED),
        ("timeout", RunStatus.FAILED),
        ("canceled", RunStatus.CANCELED),
    ]:
        calls: list[dict] = []
        monkeypatch.setattr(
            "ansiblaster.jobs.ansible_runner.run_async",
            _fake_run_async_recorder(calls, final_status=ansible_status, rc=1),
        )
        manager, session_factory = _make_job_manager(tmp_path / ansible_status)

        run = manager.start_job(
            target_os=TargetOS.LINUX,
            target_host="192.168.1.10",
            target_port=22,
            target_user="root",
            target_password="hunter2",
            roles=["docker-host"],
        )

        with session_scope(session_factory) as session:
            assert session.get(Run, run.id).status == expected


async def test_start_job_builds_linux_playbook_with_become_and_matching_inventory(
    tmp_path, monkeypatch
):
    calls: list[dict] = []
    monkeypatch.setattr(
        "ansiblaster.jobs.ansible_runner.run_async", _fake_run_async_recorder(calls)
    )
    manager, _ = _make_job_manager(tmp_path)

    manager.start_job(
        target_os=TargetOS.LINUX,
        target_host="192.168.1.10",
        target_port=22,
        target_user="root",
        target_password="hunter2",
        roles=["docker-host", "apache"],
    )

    kwargs = calls[0]
    [play] = kwargs["playbook"]
    assert play["hosts"] == "all"
    assert play["become"] is True
    assert play["roles"] == ["docker-host", "apache"]
    assert kwargs["roles_path"] == [str(tmp_path / "roles")]

    host_vars = kwargs["inventory"]["all"]["hosts"]["target"]
    assert host_vars["ansible_connection"] == "ssh"
    assert host_vars["ansible_password"] == "hunter2"


async def test_start_job_windows_playbook_has_no_become(tmp_path, monkeypatch):
    calls: list[dict] = []
    monkeypatch.setattr(
        "ansiblaster.jobs.ansible_runner.run_async", _fake_run_async_recorder(calls)
    )
    manager, _ = _make_job_manager(tmp_path)

    manager.start_job(
        target_os=TargetOS.WINDOWS,
        target_host="10.0.0.5",
        target_port=5985,
        target_user="Administrator",
        target_password="hunter2",
        roles=["iis"],
    )

    [play] = calls[0]["playbook"]
    assert "become" not in play


async def test_start_job_records_playbooks_used(tmp_path, monkeypatch):
    calls: list[dict] = []
    monkeypatch.setattr(
        "ansiblaster.jobs.ansible_runner.run_async", _fake_run_async_recorder(calls)
    )
    manager, session_factory = _make_job_manager(tmp_path)

    run = manager.start_job(
        target_os=TargetOS.LINUX,
        target_host="192.168.1.10",
        target_port=22,
        target_user="root",
        target_password="hunter2",
        roles=["apache", "mysql", "php"],
        playbooks=["lamp"],
    )

    with session_scope(session_factory) as session:
        fetched = session.get(Run, run.id)
        assert fetched.playbooks == ["lamp"]
        assert fetched.roles == ["apache", "mysql", "php"]


async def test_start_job_requires_at_least_one_role(tmp_path):
    manager, _ = _make_job_manager(tmp_path)

    with pytest.raises(ValueError):
        manager.start_job(
            target_os=TargetOS.LINUX,
            target_host="192.168.1.10",
            target_port=22,
            target_user="root",
            target_password="hunter2",
            roles=[],
        )


async def test_start_job_marks_run_error_when_launch_raises(tmp_path, monkeypatch):
    def _raising_run_async(**kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr("ansiblaster.jobs.ansible_runner.run_async", _raising_run_async)
    manager, session_factory = _make_job_manager(tmp_path)

    with pytest.raises(RuntimeError):
        manager.start_job(
            target_os=TargetOS.LINUX,
            target_host="192.168.1.10",
            target_port=22,
            target_user="root",
            target_password="hunter2",
            roles=["docker-host"],
        )

    with session_scope(session_factory) as session:
        runs = session.query(Run).all()
        assert len(runs) == 1
        assert runs[0].status == RunStatus.ERROR
        assert runs[0].finished_at is not None


async def test_cancel_sets_cancel_event_for_known_job(tmp_path, monkeypatch):
    calls: list[dict] = []

    def _fake_run_async_not_finished(**kwargs):
        calls.append(kwargs)
        import threading

        return (threading.Thread(), _FakeRunner(status="running", rc=None))

    monkeypatch.setattr("ansiblaster.jobs.ansible_runner.run_async", _fake_run_async_not_finished)
    manager, _ = _make_job_manager(tmp_path)

    run = manager.start_job(
        target_os=TargetOS.LINUX,
        target_host="192.168.1.10",
        target_port=22,
        target_user="root",
        target_password="hunter2",
        roles=["docker-host"],
    )

    job = manager.get_job(run.id)
    assert job is not None
    assert not job.cancel_event.is_set()

    assert manager.cancel(run.id) is True
    assert job.cancel_event.is_set()


def test_cancel_returns_false_for_unknown_job(tmp_path):
    manager, _ = _make_job_manager(tmp_path)

    assert manager.cancel("does-not-exist") is False


def test_get_job_returns_none_for_unknown_job(tmp_path):
    manager, _ = _make_job_manager(tmp_path)

    assert manager.get_job("does-not-exist") is None
