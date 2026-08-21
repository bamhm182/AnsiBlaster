"""JobManager: launches ansible-runner jobs, tracks them, and fans out live log lines.

Each call to start_job() creates a Run row (status=pending), builds that job's ephemeral
playbook + inventory, and launches ansible-runner's run_async() -- which spawns its own
background thread and handles per-job isolation via private_data_dir internally (see
CLAUDE.md's "Job execution model"). JobManager just keeps a small in-process registry mapping
job_id -> JobHandle (the runner's thread/Runner object, an asyncio.Queue feeding that job's
SSE stream, and a cancel event) so routes.py can attach to a running job's log stream or
request cancellation.

ansible-runner's callbacks (event_handler, status_handler, finished_callback) all fire from
its own background thread, never from the asyncio event loop thread -- so every callback here
either opens its own short-lived DB session (session_scope is safe to call from any thread;
what's unsafe is sharing one Session across threads) or hands off to the loop via
call_soon_threadsafe before touching the asyncio.Queue.
"""

from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import ansible_runner

from ansiblaster.db import session_scope
from ansiblaster.inventory import build_inventory
from ansiblaster.models import Run, RunStatus, TargetOS

# Sentinel pushed onto a job's queue once ansible-runner has finished, so the SSE route can
# stop iterating without polling the run's status separately.
STREAM_DONE = object()

# ansible-runner's own status strings (see ansible_runner.runner.Runner.status_callback),
# mapped onto our RunStatus. "starting"/"running" aren't terminal so they're handled
# separately in _status_handler rather than through this map.
_TERMINAL_STATUS_MAP: dict[str, RunStatus] = {
    "successful": RunStatus.SUCCESSFUL,
    "failed": RunStatus.FAILED,
    "timeout": RunStatus.FAILED,
    "canceled": RunStatus.CANCELED,
}


@dataclass
class JobHandle:
    """Everything JobManager needs to track one in-flight (or just-finished) job."""

    job_id: str
    queue: asyncio.Queue
    cancel_event: threading.Event
    thread: threading.Thread
    runner: Any  # ansible_runner.runner.Runner -- the package ships no type stubs


class JobManager:
    """Owns the in-process job registry; the only thing routes.py should talk to directly."""

    def __init__(self, *, session_factory, roles_path: str, artifacts_path: str) -> None:
        self._session_factory = session_factory
        self._roles_path = roles_path
        self._artifacts_path = artifacts_path
        self._jobs: dict[str, JobHandle] = {}

    def get_job(self, job_id: str) -> JobHandle | None:
        return self._jobs.get(job_id)

    def start_job(
        self,
        *,
        target_os: TargetOS,
        target_host: str,
        target_port: int,
        target_user: str,
        target_password: str,
        roles: list[str],
    ) -> Run:
        """Create the Run row and launch its ansible-runner job. Returns the new Run.

        Must be called with an asyncio event loop running (it's meant to be called from a
        FastAPI route handler) -- the loop is captured so ansible-runner's background-thread
        callbacks can safely hand log lines back to this job's asyncio.Queue.
        """
        if not roles:
            raise ValueError("At least one role must be selected to start a run.")

        loop = asyncio.get_running_loop()

        with session_scope(self._session_factory) as session:
            run = Run(
                target_os=target_os,
                target_host=target_host,
                target_port=target_port,
                target_user=target_user,
                roles=list(roles),
            )
            session.add(run)
            session.flush()
            job_id = run.id
            private_data_dir_path = Path(self._artifacts_path) / job_id
            # ansible-runner requires private_data_dir to already exist -- it does not create
            # this top-level directory itself (only subdirectories underneath it).
            private_data_dir_path.mkdir(parents=True, exist_ok=True)
            private_data_dir = str(private_data_dir_path)
            run.artifact_dir = private_data_dir

        run_updater = _RunUpdater(job_id=job_id, session_factory=self._session_factory)
        queue: asyncio.Queue = asyncio.Queue()
        cancel_event = threading.Event()

        def _event_handler(event_data: dict) -> bool:
            line = event_data.get("stdout")
            if line:
                loop.call_soon_threadsafe(queue.put_nowait, line)
            return True

        def _status_handler(status_data: dict, runner_config: Any) -> None:
            if status_data.get("status") == "running":
                run_updater.mark_running()

        def _finished_handler(runner: Any) -> None:
            status = _TERMINAL_STATUS_MAP.get(runner.status, RunStatus.ERROR)
            run_updater.mark_finished(status, runner.rc)
            loop.call_soon_threadsafe(queue.put_nowait, STREAM_DONE)

        try:
            thread, runner = ansible_runner.run_async(
                private_data_dir=private_data_dir,
                ident=job_id,
                playbook=_build_playbook(roles, target_os),
                inventory=build_inventory(
                    target_os=target_os,
                    target_host=target_host,
                    target_port=target_port,
                    target_user=target_user,
                    target_password=target_password,
                ),
                roles_path=[self._roles_path],
                quiet=True,
                rotate_artifacts=0,
                # Without this, ansible-playbook's stdout (and so each event's "stdout" field
                # we stream/store) is full of raw ANSI color escape codes -- fine in a real
                # terminal, garbled control-character noise in a browser <pre> or a plain-text
                # log file. Ansible has no built-in "plain output" flag; this env var is the
                # documented way to force it off regardless of TTY detection.
                envvars={"ANSIBLE_NOCOLOR": "1"},
                event_handler=_event_handler,
                status_handler=_status_handler,
                finished_callback=_finished_handler,
                cancel_callback=cancel_event.is_set,
            )
        except Exception:
            run_updater.mark_finished(RunStatus.ERROR, None)
            raise

        self._jobs[job_id] = JobHandle(
            job_id=job_id,
            queue=queue,
            cancel_event=cancel_event,
            thread=thread,
            runner=runner,
        )
        return run

    def cancel(self, job_id: str) -> bool:
        """Signal a tracked job to stop. Returns False if the job isn't tracked (never
        started, or the process has since restarted and lost its in-memory registry).
        """
        job = self._jobs.get(job_id)
        if job is None:
            return False
        job.cancel_event.set()
        return True


class _RunUpdater:
    """Lets ansible-runner's background-thread callbacks update a Run row safely.

    Each method opens and commits its own short-lived session rather than holding one across
    threads -- SQLAlchemy sessions aren't safe to share between threads, but the sessionmaker
    factory itself is.
    """

    def __init__(self, *, job_id: str, session_factory) -> None:
        self._job_id = job_id
        self._session_factory = session_factory

    def mark_running(self) -> None:
        with session_scope(self._session_factory) as session:
            run = session.get(Run, self._job_id)
            if run is not None and run.status == RunStatus.PENDING:
                run.status = RunStatus.RUNNING
                run.started_at = datetime.now(UTC)

    def mark_finished(self, status: RunStatus, return_code: int | None) -> None:
        with session_scope(self._session_factory) as session:
            run = session.get(Run, self._job_id)
            if run is not None:
                run.status = status
                run.return_code = return_code
                run.finished_at = datetime.now(UTC)


def stdout_log_path(run: Run) -> Path:
    """Path to the plain-text stdout log ansible-runner writes for a run.

    Mirrors ansible-runner's own convention (see ansible_runner.config._base.BaseConfig):
    given private_data_dir=run.artifact_dir and ident=run.id (both set in start_job()), the
    console log lands at <private_data_dir>/artifacts/<ident>/stdout. May not exist yet if the
    job hasn't started writing output.
    """
    return Path(run.artifact_dir) / "artifacts" / run.id / "stdout"


def _build_playbook(roles: list[str], target_os: TargetOS) -> list[dict[str, Any]]:
    """The ephemeral playbook applying the selected roles to the single generated host.

    become is only enabled for Linux targets (see inventory.py's ansible_become_password
    note) -- Windows targets (either connection method) are expected to connect as an
    already-administrative account, and Ansible's become defaults (sudo) don't apply to
    WinRM/PSRP connections anyway.
    """
    play: dict[str, Any] = {"hosts": "all", "roles": list(roles)}
    if target_os is TargetOS.LINUX:
        play["become"] = True
    return [play]
