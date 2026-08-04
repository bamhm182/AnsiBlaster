"""GET /roles -- rescans the roles directory and re-renders the checklist fragment."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from ansiblaster.deps import get_app_settings, templates
from ansiblaster.roles import discover_roles
from ansiblaster.settings import Settings

router = APIRouter()


@router.get("/roles")
async def list_roles(request: Request, settings: Settings = Depends(get_app_settings)):
    roles = discover_roles(settings.ansible.roles_path)
    return templates.TemplateResponse(request, "partials/role_list.html", {"roles": roles})
