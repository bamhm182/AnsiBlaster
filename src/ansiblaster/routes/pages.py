"""GET / -- the main page: role checklist, playbook presets, apply form, run history."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from ansiblaster.db import session_scope
from ansiblaster.deps import get_app_settings, get_session_factory, templates
from ansiblaster.inventory import DEFAULT_PORTS, WINDOWS_HTTPS_PORT
from ansiblaster.models import Run
from ansiblaster.playbooks import discover_playbooks
from ansiblaster.roles import discover_roles
from ansiblaster.settings import Settings

router = APIRouter()

_RECENT_RUNS_LIMIT = 50


@router.get("/")
async def index(
    request: Request,
    settings: Settings = Depends(get_app_settings),
    session_factory=Depends(get_session_factory),
):
    with session_scope(session_factory) as session:
        recent_runs = list(
            session.query(Run).order_by(Run.created_at.desc()).limit(_RECENT_RUNS_LIMIT)
        )
        session.expunge_all()  # keep the rows usable in the template after the session closes

    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "roles": discover_roles(settings.ansible.roles_path),
            "playbooks": discover_playbooks(settings.ansible.playbooks_path),
            "runs": recent_runs,
            "default_ports": {os_.value: port for os_, port in DEFAULT_PORTS.items()},
            "windows_https_port": WINDOWS_HTTPS_PORT,
            "defaults": settings.defaults,
        },
    )
