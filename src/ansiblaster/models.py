"""ORM models for run history.

See CLAUDE.md's "Data model & routes" section for the schema this mirrors.
"""

from __future__ import annotations

import enum
import uuid
from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, Enum, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from ansiblaster.db import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _new_id() -> str:
    return str(uuid.uuid4())


class TargetOS(str, enum.Enum):
    """Operating system of a run's target host, determining connection method."""

    LINUX = "linux"
    WINDOWS = "windows"


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

    roles: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    playbooks: Mapped[list[str] | None] = mapped_column(JSON, nullable=True, default=list)

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
