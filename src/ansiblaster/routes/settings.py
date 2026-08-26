"""The Settings popup: GET /settings (the modal's body fragment) plus the endpoints that save/
delete a role-variable-default override or save host credential overrides -- see
settings_store.py for the DB-backed key/value store this all reads and writes, and CLAUDE.md's
"Settings" section for the feature's design. The modal's third tab, Environment, is read-only
(backed by settings.py's relevant_environment_variables(), not the DB) and so has no route of
its own -- it rides along in every render of the fragment below like everything else here.

Every route here returns the same `partials/settings_modal_body.html` fragment (mirroring
routes/runs.py's re-fetch-and-re-render pattern for run_detail.html), so the modal reflects
whatever was just saved/removed without a full page reload -- htmx swaps it straight into
`#settings-modal-body`.
"""

from __future__ import annotations

import re

from fastapi import APIRouter, Depends, Form, HTTPException, Request

from ansiblaster.db import session_scope
from ansiblaster.deps import get_app_settings, get_session_factory, templates
from ansiblaster.settings import Settings, relevant_environment_variables
from ansiblaster.settings_store import (
    HOST_FIELDS,
    HOST_PRESETS,
    delete_host_override,
    delete_role_variable_override,
    get_host_overrides,
    get_role_variable_overrides,
    parse_override_value,
    set_host_override,
    set_role_variable_override,
)

router = APIRouter(prefix="/settings")

# Matches the value[<name>] bracket-notation field naming the Role Variables tab's bulk-save
# form uses for its existing rows (see settings_modal_body.html) -- same convention as
# routes/runs.py's vars[<role>][<var_name>], just one level shallower since there's no role to
# scope by here.
_BULK_VALUE_KEY_RE = re.compile(r"^value\[([^\]]+)\]$")


def _render_modal_body(request: Request, settings: Settings, session):
    role_variable_overrides = get_role_variable_overrides(session)
    host_overrides = get_host_overrides(session)
    return templates.TemplateResponse(
        request,
        "partials/settings_modal_body.html",
        {
            # Sorted alphabetically by variable name, per the feature's design.
            "role_variable_overrides": dict(sorted(role_variable_overrides.items())),
            # The saved override only (blank if none) goes in each field's value -- the
            # config.yaml default is shown as a placeholder instead (see host_config_defaults
            # below), not baked into the value, so leaving the field blank on save is
            # unambiguously "clear the override" rather than "explicitly set it to blank".
            "host_overrides": host_overrides,
            # A plain {preset: TargetCredentials} dict rather than settings.defaults itself, so
            # the template can index it by the same preset string it's already looping over
            # (Jinja's "." falls back from getattr to getitem for a dict, but not the reverse --
            # settings.defaults.ssh works, settings.defaults[preset] would not).
            "host_config_defaults": {
                preset: getattr(settings.defaults, preset) for preset in HOST_PRESETS
            },
            # Read-only -- see settings.py's relevant_environment_variables() docstring for
            # scope/masking. Recomputed on every render like everything else here, though
            # nothing in this module's own routes actually changes it.
            "environment_variables": relevant_environment_variables(),
        },
    )


@router.get("")
async def get_settings_modal(
    request: Request,
    settings: Settings = Depends(get_app_settings),
    session_factory=Depends(get_session_factory),
):
    with session_scope(session_factory) as session:
        return _render_modal_body(request, settings, session)


@router.post("/role-variables")
async def save_role_variable_override(
    request: Request,
    name: str = Form(...),
    value: str = Form(""),
    settings: Settings = Depends(get_app_settings),
    session_factory=Depends(get_session_factory),
):
    name = name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Variable name is required.")
    with session_scope(session_factory) as session:
        set_role_variable_override(session, name, parse_override_value(value))
        return _render_modal_body(request, settings, session)


@router.post("/role-variables/bulk")
async def save_role_variable_overrides_bulk(
    request: Request,
    settings: Settings = Depends(get_app_settings),
    session_factory=Depends(get_session_factory),
):
    """Save every existing role-variable override at once, from the Role Variables tab's single
    "Save Role Variables" button -- there's no per-row save button (see CLAUDE.md's "Settings
    popup" section). Only touches names already present as a value[<name>] field; adding a
    brand-new name is still its own small action (save_role_variable_override() above)."""
    form = await request.form()
    with session_scope(session_factory) as session:
        for key, value in form.multi_items():
            match = _BULK_VALUE_KEY_RE.match(key)
            if not match:
                continue
            set_role_variable_override(session, match.group(1), parse_override_value(str(value)))
        return _render_modal_body(request, settings, session)


@router.delete("/role-variables/{name}")
async def remove_role_variable_override(
    request: Request,
    name: str,
    settings: Settings = Depends(get_app_settings),
    session_factory=Depends(get_session_factory),
):
    with session_scope(session_factory) as session:
        delete_role_variable_override(session, name)
        return _render_modal_body(request, settings, session)


@router.post("/host")
async def save_host_settings(
    request: Request,
    settings: Settings = Depends(get_app_settings),
    session_factory=Depends(get_session_factory),
):
    form = await request.form()
    with session_scope(session_factory) as session:
        for preset in HOST_PRESETS:
            for field in HOST_FIELDS:
                value = str(form.get(f"{preset}_{field}", ""))
                # A field left blank means "no override, use config.yaml's default" -- not
                # "override it with an explicit blank" -- so a blank submission clears any
                # existing override instead of saving an empty string over a real default.
                if value == "":
                    delete_host_override(session, preset, field)
                else:
                    set_host_override(session, preset, field, value)
        return _render_modal_body(request, settings, session)
