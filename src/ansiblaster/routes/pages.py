"""GET / -- the main page: role checklist, playbook presets, apply form, run history."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from ansiblaster.db import session_scope
from ansiblaster.deps import get_app_settings, get_session_factory, templates
from ansiblaster.inventory import DEFAULT_PORTS, WINDOWS_HTTPS_PORT
from ansiblaster.models import Run
from ansiblaster.playbooks import discover_playbooks
from ansiblaster.role_vars import discover_role_variables
from ansiblaster.roles import discover_roles
from ansiblaster.settings import Settings
from ansiblaster.settings_store import (
    apply_host_overrides,
    apply_role_variable_overrides,
    get_host_overrides,
    get_role_variable_overrides,
)

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
        role_variable_overrides = get_role_variable_overrides(session)
        host_overrides = get_host_overrides(session)

    roles = discover_roles(settings.ansible.roles_path)
    role_variables = apply_role_variable_overrides(
        discover_role_variables(settings.ansible.roles_path, roles), role_variable_overrides
    )

    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "roles": roles,
            "role_variables": role_variables,
            "playbooks": discover_playbooks(settings.ansible.playbooks_path),
            "runs": recent_runs,
            "default_ports": {os_.value: port for os_, port in DEFAULT_PORTS.items()},
            "windows_https_port": WINDOWS_HTTPS_PORT,
            # Settings-popup host overrides layered on top of config.yaml's defaults.* (see
            # settings_store.py) -- a plain dict, not settings.defaults itself, so the Settings
            # popup's saved values win without needing a second template variable everywhere
            # defaults.ssh.username/etc. is already used.
            "defaults": apply_host_overrides(settings.defaults, host_overrides),
        },
    )
