"""GET /playbooks -- rescans the playbooks directory and re-renders the preset button list."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from ansiblaster.deps import get_app_settings, templates
from ansiblaster.playbooks import discover_playbooks
from ansiblaster.settings import Settings

router = APIRouter()


@router.get("/playbooks")
async def list_playbooks(request: Request, settings: Settings = Depends(get_app_settings)):
    playbooks = discover_playbooks(settings.ansible.playbooks_path)
    return templates.TemplateResponse(
        request, "partials/playbook_list.html", {"playbooks": playbooks}
    )
