"""FastAPI application factory: wires settings, DB, JobManager, static files, and routers."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from ansiblaster.db import init_db, make_engine, make_session_factory
from ansiblaster.jobs import JobManager
from ansiblaster.routes import router
from ansiblaster.settings import get_settings

STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    engine = make_engine(settings.database.path)
    init_db(engine)

    app.state.settings = settings
    app.state.session_factory = make_session_factory(engine)
    app.state.job_manager = JobManager(
        session_factory=app.state.session_factory,
        roles_path=settings.ansible.roles_path,
        artifacts_path=settings.ansible.artifacts_path,
    )

    yield


def create_app() -> FastAPI:
    app = FastAPI(title="Ansiblaster", lifespan=lifespan)
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    app.include_router(router)
    return app


app = create_app()
