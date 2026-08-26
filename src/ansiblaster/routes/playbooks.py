"""GET /playbooks -- rescans the playbooks directory and re-renders the preset button list.

Also the Viewer tab's read-only file browser for a playbook: GET /playbooks/{name}/files (its
one-entry file list -- a playbook is a single file, not a directory) and
GET /playbooks/{name}/file (that file's content) -- see browse.py for the path-safety checks
both of these rely on.
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request

from ansiblaster.browse import NotFound, list_playbook_files, read_playbook_file
from ansiblaster.deps import get_app_settings, templates
from ansiblaster.playbooks import discover_playbooks
from ansiblaster.settings import Settings

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/playbooks")
async def list_playbooks(request: Request, settings: Settings = Depends(get_app_settings)):
    playbooks_path = Path(settings.ansible.playbooks_path)
    playbooks = discover_playbooks(settings.ansible.playbooks_path)
    # See routes/roles.py's equivalent logging for why this is worth an INFO line: a rescan is
    # an infrequent, explicit action, not per-request noise.
    if not playbooks_path.is_dir():
        logger.info(
            "Playbooks directory %s does not exist -- showing no playbooks.", playbooks_path
        )
    else:
        logger.info("Loaded %d playbook(s) from %s.", len(playbooks), playbooks_path)
    return templates.TemplateResponse(
        request, "partials/playbook_list.html", {"playbooks": playbooks}
    )


@router.get("/playbooks/{name}/files")
async def playbook_files(
    request: Request, name: str, settings: Settings = Depends(get_app_settings)
):
    try:
        files = list_playbook_files(settings.ansible.playbooks_path, name)
    except NotFound as exc:
        raise HTTPException(status_code=404, detail="Playbook not found.") from exc
    return templates.TemplateResponse(
        request,
        "partials/file_browser.html",
        {"files": files, "base_url": f"playbooks/{name}"},
    )


@router.get("/playbooks/{name}/file")
async def playbook_file(
    request: Request, name: str, path: str, settings: Settings = Depends(get_app_settings)
):
    try:
        content = read_playbook_file(settings.ansible.playbooks_path, name, path)
    except NotFound as exc:
        raise HTTPException(status_code=404, detail="File not found.") from exc
    return templates.TemplateResponse(
        request, "partials/file_content.html", {"path": path, "content": content}
    )
