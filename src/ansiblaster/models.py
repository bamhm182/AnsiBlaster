"""ORM models for run history.

See CLAUDE.md's "Data model & routes" section for the schema this mirrors.
"""

from __future__ import annotations

import enum
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Enum, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from ansiblaster.db import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _new_id() -> str:
    return str(uuid.uuid4())


class TargetOS(str, enum.Enum):
    """Target host's OS *and* connection method -- Windows has two: WINDOWS means the `winrm`
    connection plugin, WINDOWS_PSRP means `psrp` (see inventory.py). Both are still just
    "Windows" for every other decision keyed off this enum (become is skipped for anything
    that isn't LINUX -- see jobs.py -- rather than enumerating every non-Linux member)."""

    LINUX = "linux"
    WINDOWS = "windows"
    WINDOWS_PSRP = "windows_psrp"


class RunStatus(str, enum.Enum):
    """Lifecycle status of a run: pending -> running -> one of the terminal states."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCESSFUL = "successful"
    FAILED = "failed"
    CANCELED = "canceled"
    ERROR = "error"


class Run(Base):
    """A single ansible-runner job: one target host, a set of roles, its status/log location.

    The target's password is intentionally not a column here — it is only ever held in
    memory for the life of the request/job (see CLAUDE.md's password-persistence note).
    """

    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_new_id)

    target_os: Mapped[TargetOS] = mapped_column(Enum(TargetOS), nullable=False)
    target_host: Mapped[str] = mapped_column(String, nullable=False)
    # Default port (22 for linux, 5985 for windows) is chosen by the route/form, not here.
    target_port: Mapped[int] = mapped_column(Integer, nullable=False)
    target_user: Mapped[str] = mapped_column(String, nullable=False)

    # Snapshot of the actual roles applied, regardless of whether they were checked
    # individually or via a playbook preset -- playbooks themselves aren't tracked here, only
    # what they expanded to (see CLAUDE.md's "Playbooks (role presets)" section).
    roles: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)

    # Snapshot of the role variables actually applied at submit time (role -> var name ->
    # typed value), empty for a role with no meta/argument_specs.yml or with none of its
    # variables filled in. Like `roles`, this is an immutable record of what was submitted,
    # not a live reference to that role's current argument_specs (which could change on disk
    # after the run) -- see CLAUDE.md's "Role variables (argument_specs)" section. Unlike the
    # target password, this *is* persisted: a variable named e.g. "mysql_root_password" would
    # be stored here in the clear with no redaction. That's a known gap, not solved here.
    variables: Mapped[dict[str, dict[str, Any]]] = mapped_column(JSON, nullable=False, default=dict)

    status: Mapped[RunStatus] = mapped_column(
        Enum(RunStatus), nullable=False, default=RunStatus.PENDING
    )
    return_code: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    artifact_dir: Mapped[str | None] = mapped_column(String, nullable=True, default=None)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"Run(id={self.id!r}, target={self.target_user}@{self.target_host}:"
            f"{self.target_port}, os={self.target_os}, status={self.status})"
        )
