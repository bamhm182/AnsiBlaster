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


class _RevalidatingStaticFiles(StaticFiles):
    """StaticFiles that makes browsers revalidate on every load.

    Starlette sends only ETag/Last-Modified, so browsers apply *heuristic* freshness and may
    keep serving an old style.css/script for a while after an upgrade -- a stale stylesheet
    against a newer page renders broken or missing UI. "no-cache" still lets the browser reuse
    its copy, but only after a cheap conditional request (304) confirms it's current.
    """

    def file_response(self, *args, **kwargs):
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "no-cache"
        return response


def create_app() -> FastAPI:
    app = FastAPI(title="AnsiBlaster", lifespan=lifespan)
    app.mount("/static", _RevalidatingStaticFiles(directory=str(STATIC_DIR)), name="static")
    app.include_router(router)
    return app


app = create_app()
