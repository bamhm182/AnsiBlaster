from __future__ import annotations

from ansiblaster.db import init_db, make_engine, make_session_factory, session_scope
from ansiblaster.models import Run, RunStatus, TargetOS


def test_run_defaults(tmp_path):
    engine = make_engine(str(tmp_path / "test.db"))
    init_db(engine)
    session_factory = make_session_factory(engine)

    with session_scope(session_factory) as session:
        run = Run(
            target_os=TargetOS.LINUX,
            target_host="192.168.1.10",
            target_port=22,
            target_user="root",
            roles=["docker-host"],
        )
        session.add(run)
        session.flush()
        run_id = run.id

    assert run_id is not None

    with session_scope(session_factory) as session:
        fetched = session.get(Run, run_id)
        assert fetched is not None
        assert fetched.status == RunStatus.PENDING
        assert fetched.roles == ["docker-host"]
        assert fetched.return_code is None
        assert fetched.started_at is None
        assert fetched.finished_at is None
        assert fetched.created_at is not None


def test_run_with_windows_target(tmp_path):
    engine = make_engine(str(tmp_path / "test.db"))
    init_db(engine)
    session_factory = make_session_factory(engine)

    with session_scope(session_factory) as session:
        run = Run(
            target_os=TargetOS.WINDOWS,
            target_host="10.0.0.5",
            target_port=5985,
            target_user="Administrator",
            roles=["iis", "dotnet"],
        )
        session.add(run)
        session.flush()
        run_id = run.id

    with session_scope(session_factory) as session:
        fetched = session.get(Run, run_id)
        assert fetched.target_os == TargetOS.WINDOWS
        assert fetched.roles == ["iis", "dotnet"]


def test_run_ids_are_unique(tmp_path):
    engine = make_engine(str(tmp_path / "test.db"))
    init_db(engine)
    session_factory = make_session_factory(engine)

    with session_scope(session_factory) as session:
        run_a = Run(
            target_os=TargetOS.LINUX,
            target_host="10.0.0.1",
            target_port=22,
            target_user="root",
            roles=["docker-host"],
        )
        run_b = Run(
            target_os=TargetOS.LINUX,
            target_host="10.0.0.2",
            target_port=22,
            target_user="root",
            roles=["docker-host"],
        )
        session.add_all([run_a, run_b])
        session.flush()
        assert run_a.id != run_b.id
