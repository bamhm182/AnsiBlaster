"""GET /roles -- rescans the roles directory and re-renders the checklist fragment.

Also the Viewer tab's read-only file browser for a role: GET /roles/{name}/files (the file
list) and GET /roles/{name}/file (one file's content) -- see browse.py for the path-safety
checks both of these rely on.
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request

from ansiblaster.browse import NotFound, list_role_files, read_role_file
from ansiblaster.db import session_scope
from ansiblaster.deps import get_app_settings, get_session_factory, templates
from ansiblaster.role_vars import discover_role_variables
from ansiblaster.roles import discover_roles
from ansiblaster.settings import Settings
from ansiblaster.settings_store import apply_role_variable_overrides, get_role_variable_overrides

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/roles")
async def list_roles(
    request: Request,
    settings: Settings = Depends(get_app_settings),
    session_factory=Depends(get_session_factory),
):
    roles_path = Path(settings.ansible.roles_path)
    roles = discover_roles(settings.ansible.roles_path)
    # A rescan is an infrequent, explicit action (unlike the per-request noise logging_config.py
    # keeps out of the way) -- its outcome is worth a line at INFO, the app's own default level,
    # so "why am I seeing 0 roles" is answerable from the log without turning on DEBUG.
    if not roles_path.is_dir():
        logger.info("Roles directory %s does not exist -- showing no roles.", roles_path)
    else:
        logger.info("Loaded %d role(s) from %s.", len(roles), roles_path)
    role_variables = discover_role_variables(settings.ansible.roles_path, roles)
    with session_scope(session_factory) as session:
        role_variables = apply_role_variable_overrides(
            role_variables, get_role_variable_overrides(session)
        )
    return templates.TemplateResponse(
        request,
        "partials/role_list.html",
        {"roles": roles, "role_variables": role_variables},
    )


@router.get("/roles/{name}/files")
async def role_files(request: Request, name: str, settings: Settings = Depends(get_app_settings)):
    try:
        files = list_role_files(settings.ansible.roles_path, name)
    except NotFound as exc:
        raise HTTPException(status_code=404, detail="Role not found.") from exc
    return templates.TemplateResponse(
        request, "partials/file_browser.html", {"files": files, "base_url": f"roles/{name}"}
    )


@router.get("/roles/{name}/file")
async def role_file(
    request: Request, name: str, path: str, settings: Settings = Depends(get_app_settings)
):
    try:
        content = read_role_file(settings.ansible.roles_path, name, path)
    except NotFound as exc:
        raise HTTPException(status_code=404, detail="File not found.") from exc
    return templates.TemplateResponse(
        request, "partials/file_content.html", {"path": path, "content": content}
    )
