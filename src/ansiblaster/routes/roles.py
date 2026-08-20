"""GET /roles -- rescans the roles directory and re-renders the checklist fragment.

Also the Viewer tab's read-only file browser for a role: GET /roles/{name}/files (the file
list) and GET /roles/{name}/file (one file's content) -- see browse.py for the path-safety
checks both of these rely on.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from ansiblaster.browse import NotFound, list_role_files, read_role_file
from ansiblaster.deps import get_app_settings, templates
from ansiblaster.roles import discover_roles
from ansiblaster.settings import Settings

router = APIRouter()


@router.get("/roles")
async def list_roles(request: Request, settings: Settings = Depends(get_app_settings)):
    roles = discover_roles(settings.ansible.roles_path)
    return templates.TemplateResponse(request, "partials/role_list.html", {"roles": roles})


@router.get("/roles/{name}/files")
async def role_files(request: Request, name: str, settings: Settings = Depends(get_app_settings)):
    try:
        files = list_role_files(settings.ansible.roles_path, name)
    except NotFound as exc:
        raise HTTPException(status_code=404, detail="Role not found.") from exc
    return templates.TemplateResponse(
        request, "partials/file_browser.html", {"files": files, "base_url": f"/roles/{name}"}
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
