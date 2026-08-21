"""Shared FastAPI dependency providers and the Jinja2Templates instance.

Kept separate from app.py (rather than defined there) so route modules can import these
without importing app.py itself -- app.py imports the route modules to build the app, so the
reverse import would be circular. Providers read state that app.py's lifespan attaches to
app.state at startup.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import Request
from fastapi.templating import Jinja2Templates
from markupsafe import Markup
from sqlalchemy.orm import Session, sessionmaker

from ansiblaster.inventory import connection_label
from ansiblaster.jobs import JobManager
from ansiblaster.settings import Settings

TEMPLATES_DIR = Path(__file__).parent / "templates"

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def _tojson_attr(value: Any) -> str:
    """JSON for embedding inside an HTML attribute, e.g. `data-roles="{{ roles | tojson }}"`.

    Deliberately *not* marked safe: Jinja's autoescaping then converts the resulting quotes
    to `&#34;` etc., which is exactly what's needed to embed valid JSON inside a
    double-quoted attribute value without it breaking out. Used by playbook_list.html.
    """
    return json.dumps(value)


def _tojson_script(value: Any) -> Markup:
    """JSON for embedding directly inside a <script> block as a JS literal/expression.

    Unlike `tojson` above, this *is* marked safe: autoescaping would otherwise HTML-entity-
    escape quotes and corrupt the JS (this is exactly what broke index.html's inline script
    before this fix -- `escape("hi")` produced `&#34;hi&#34;`, not valid JS). Also escapes
    `<`/`>`/`&` as unicode escapes so a string value can't prematurely close the surrounding
    `<script>` tag (e.g. a value containing `</script>`). Used by index.html.
    """
    dumped = json.dumps(value)
    dumped = dumped.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    return Markup(dumped)


def _run_connection_label(run: Any) -> str:
    """`{{ run | connection_label }}` -- SSH/WinRM/PSRP (see inventory.connection_label) rather
    than showing a Run's raw target_os value, since there's no Linux/Windows picker in the UI
    for that value to correspond to anymore (see CLAUDE.md's "Backend & UI" section). Takes the
    whole Run rather than being called as connection_label(run.target_os, run.target_port)
    directly from the template, only because Jinja filters are naturally single-argument.
    """
    return connection_label(run.target_os, run.target_port)


templates.env.filters["tojson"] = _tojson_attr
templates.env.filters["tojson_script"] = _tojson_script
templates.env.filters["connection_label"] = _run_connection_label


def get_app_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_session_factory(request: Request) -> sessionmaker[Session]:
    return request.app.state.session_factory


def get_job_manager(request: Request) -> JobManager:
    return request.app.state.job_manager
