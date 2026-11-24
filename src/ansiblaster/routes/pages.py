"""GET / -- the main page: role checklist, playbook presets, apply form, run history."""

from __future__ import annotations

from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, RedirectResponse

from ansiblaster.db import session_scope
from ansiblaster.deps import get_app_settings, get_job_manager, get_session_factory, templates
from ansiblaster.inventory import DEFAULT_PORTS, WINDOWS_HTTPS_PORT
from ansiblaster.jobs import JobManager
from ansiblaster.models import Run
from ansiblaster.playbooks import discover_playbooks
from ansiblaster.role_vars import discover_role_variables
from ansiblaster.roles import discover_roles
from ansiblaster.routes.runs import RunRequestError, start_run
from ansiblaster.settings import Settings
from ansiblaster.settings_store import (
    apply_host_overrides,
    apply_role_variable_overrides,
    get_host_overrides,
    get_role_variable_overrides,
)
from ansiblaster.url_params import resolve_run_params

router = APIRouter()

_RECENT_RUNS_LIMIT = 50


@router.get("/")
async def index(
    request: Request,
    settings: Settings = Depends(get_app_settings),
    session_factory=Depends(get_session_factory),
    job_manager: JobManager = Depends(get_job_manager),
):
    with session_scope(session_factory) as session:
        recent_runs = list(
            session.query(Run).order_by(Run.created_at.desc()).limit(_RECENT_RUNS_LIMIT)
        )
        session.expunge_all()  # keep the rows usable in the template after the session closes
        role_variable_overrides = get_role_variable_overrides(session)
        host_overrides = get_host_overrides(session)

    roles = discover_roles(settings.ansible.roles_path)
    raw_role_variables = discover_role_variables(settings.ansible.roles_path, roles)
    role_variables = apply_role_variable_overrides(raw_role_variables, role_variable_overrides)
    playbooks = discover_playbooks(settings.ansible.playbooks_path)

    # ?execute=1: launch the run server-side (so curl/scripts work too -- see url_params.py),
    # then hand a browser back to the page with the new run open, or a script a JSON summary.
    execute_error: str | None = None
    if request.query_params.get("execute") == "1" and not settings.server.allow_url_execute:
        execute_error = (
            "deployment via URL parameters is disabled "
            "(set server.allow_url_execute / ANSIBLASTER_SERVER__ALLOW_URL_EXECUTE=true)"
        )
        if not _wants_html(request):
            return JSONResponse({"error": execute_error}, status_code=403)
    elif request.query_params.get("execute") == "1":
        outcome = _execute_from_params(
            request,
            settings=settings,
            session_factory=session_factory,
            job_manager=job_manager,
            roles=roles,
            playbooks=playbooks,
            raw_role_variables=raw_role_variables,
            host_overrides=host_overrides,
            role_variable_overrides=role_variable_overrides,
        )
        if not isinstance(outcome, str):
            return outcome
        execute_error = outcome
        if not _wants_html(request):
            return JSONResponse({"error": execute_error}, status_code=400)

    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "roles": roles,
            "role_variables": role_variables,
            "playbooks": playbooks,
            # Shown as an error toast by index.html's applyUrlParams() when ?execute=1 was
            # refused (never silently ignored).
            "url_execute_error": execute_error,
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


def _wants_html(request: Request) -> bool:
    """A browser (Accept includes text/html) gets pages/redirects; curl & co (Accept: */*) get
    JSON. ?format=json forces the latter."""
    if request.query_params.get("format") == "json":
        return False
    return "text/html" in request.headers.get("accept", "")


def _execute_from_params(
    request: Request,
    *,
    settings: Settings,
    session_factory,
    job_manager: JobManager,
    roles: list[str],
    playbooks: dict[str, list[str]],
    raw_role_variables,
    host_overrides,
    role_variable_overrides,
):
    """Run what ?execute=1 asked for. Returns a Response on success, or an error string."""
    # A GET that deploys must not be triggerable by a page embedding it as an image/script/
    # fetch (browsers label those Sec-Fetch-Mode != "navigate"); curl sends no such header.
    mode = request.headers.get("sec-fetch-mode")
    if mode is not None and mode != "navigate":
        return "Refusing to execute: not a top-level navigation."

    result = resolve_run_params(
        request.query_params,
        settings=settings,
        roles_available=roles,
        playbooks=playbooks,
        role_variables=raw_role_variables,
        host_overrides=host_overrides,
        role_variable_overrides=role_variable_overrides,
    )
    if result.run is None:
        return "; ".join(result.problems)
    try:
        run = start_run(
            job_manager=job_manager,
            session_factory=session_factory,
            settings=settings,
            target_os=result.run.target_os,
            target_host=result.run.target_host,
            target_port=result.run.target_port,
            target_user=result.run.target_user,
            target_password=result.run.target_password,
            roles=result.run.roles,
            raw_variables=result.run.raw_variables,
        )
    except RunRequestError as exc:
        return str(exc)

    if _wants_html(request):
        # Same params minus execute (so a reload re-fills the form without launching again),
        # plus run=<id> for the page to open. Relative Location: works behind path-stripping
        # proxies (see AGENTS.md).
        kept = [(k, v) for k, v in request.query_params.multi_items() if k != "execute"]
        return RedirectResponse("?" + urlencode(kept + [("run", run.id)]), status_code=303)
    return JSONResponse(
        {
            "id": run.id,
            "status": run.status.value,
            "target": f"{run.target_user}@{run.target_host}:{run.target_port}",
            "roles": run.roles,
            # Relative to the app's base URL.
            "detail": f"runs/{run.id}",
            "stream": f"runs/{run.id}/stream",
            "log": f"runs/{run.id}/log",
        },
        status_code=201,
    )
