"""POST /runs, GET /runs, GET /runs/{job_id}(/stream|/log), POST /runs/{job_id}/cancel."""

from __future__ import annotations

import html
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, StreamingResponse
from sqlalchemy.orm import Session, sessionmaker

from ansiblaster.db import session_scope
from ansiblaster.deps import get_job_manager, get_session_factory, templates
from ansiblaster.jobs import STREAM_DONE, JobManager, stdout_log_path
from ansiblaster.models import Run, TargetOS

router = APIRouter(prefix="/runs")

_RECENT_RUNS_LIMIT = 50


@router.get("")
async def list_runs(request: Request, session_factory=Depends(get_session_factory)):
    with session_scope(session_factory) as session:
        runs = list(session.query(Run).order_by(Run.created_at.desc()).limit(_RECENT_RUNS_LIMIT))
        session.expunge_all()
    return templates.TemplateResponse(request, "partials/run_list.html", {"runs": runs})


@router.post("")
async def create_run(
    request: Request,
    job_manager: JobManager = Depends(get_job_manager),
    session_factory: sessionmaker[Session] = Depends(get_session_factory),
):
    form = await request.form()

    try:
        target_os = TargetOS(form.get("target_os", ""))
    except ValueError:
        return PlainTextResponse("Invalid target OS.", status_code=400)

    target_host = str(form.get("target_host") or "").strip()
    target_user = str(form.get("target_user") or "").strip()
    target_password = str(form.get("target_password") or "")
    roles = [role for role in form.getlist("roles") if role]
    playbooks = [playbook for playbook in form.getlist("playbooks") if playbook]

    try:
        target_port = int(form.get("target_port", ""))
    except ValueError:
        return PlainTextResponse("Port must be a number.", status_code=400)

    if not target_host or not target_user:
        return PlainTextResponse("Target host and username are required.", status_code=400)

    try:
        run = job_manager.start_job(
            target_os=target_os,
            target_host=target_host,
            target_port=target_port,
            target_user=target_user,
            target_password=target_password,
            roles=roles,
            playbooks=playbooks,
        )
    except ValueError as exc:
        return PlainTextResponse(str(exc), status_code=400)

    # start_job()'s returned Run reflects only the moment it was inserted (status=pending) --
    # ansible-runner's background thread may already have updated (or even finished) it by
    # the time we render the response, so re-fetch rather than trust that stale snapshot.
    run = _get_run_or_404(session_factory, run.id)
    return templates.TemplateResponse(
        request,
        "partials/run_detail.html",
        {"run": run, "initial_log": _read_log_if_present(run)},
        status_code=201,
    )


@router.get("/{job_id}")
async def run_detail(
    request: Request,
    job_id: str,
    session_factory: sessionmaker[Session] = Depends(get_session_factory),
):
    run = _get_run_or_404(session_factory, job_id)
    return templates.TemplateResponse(
        request,
        "partials/run_detail.html",
        {"run": run, "initial_log": _read_log_if_present(run)},
    )


@router.get("/{job_id}/log")
async def run_log(
    job_id: str, session_factory: sessionmaker[Session] = Depends(get_session_factory)
):
    run = _get_run_or_404(session_factory, job_id)
    return PlainTextResponse(_read_log_if_present(run))


@router.get("/{job_id}/stream")
async def run_stream(job_id: str, job_manager: JobManager = Depends(get_job_manager)):
    job = job_manager.get_job(job_id)
    if job is None:
        raise HTTPException(
            status_code=404,
            detail="This job isn't currently tracked (already finished, or the app restarted).",
        )

    async def event_generator() -> AsyncIterator[str]:
        while True:
            item = await job.queue.get()
            if item is STREAM_DONE:
                # No payload needed: run_detail.html's container listens for this event via
                # hx-trigger="sse:done" and just re-fetches the whole fragment, which reflects
                # whatever final status/rc/log jobs.py has since written to the DB/log file.
                yield "event: done\ndata: \n\n"
                break
            yield _format_sse_event(item)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.post("/{job_id}/cancel")
async def cancel_run(job_id: str, job_manager: JobManager = Depends(get_job_manager)):
    if not job_manager.cancel(job_id):
        raise HTTPException(status_code=404, detail="This job isn't currently tracked.")

    # The actual status transition (running -> canceled) happens asynchronously once
    # ansible-runner notices the cancel signal; the already-open SSE stream's "done" event
    # will trigger run_detail.html to refresh itself once that happens, so this response only
    # needs to acknowledge the request, not reflect the final state.
    return HTMLResponse('<span class="cancel-pending">Cancel requested&hellip;</span>')


def _get_run_or_404(session_factory: sessionmaker[Session], job_id: str) -> Run:
    with session_scope(session_factory) as session:
        run = session.get(Run, job_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Run not found.")
        session.expunge(run)
        return run


def _read_log_if_present(run: Run) -> str:
    if not run.artifact_dir:
        return ""
    log_path = stdout_log_path(run)
    if not log_path.is_file():
        return ""
    return log_path.read_text(errors="replace")


def _format_sse_event(data: str) -> str:
    """Format one ansible-runner stdout chunk as an SSE 'message' event.

    Each line becomes its own `data:` line per the SSE spec (a single data field can't
    contain a literal newline). Lines are HTML-escaped because htmx's sse extension swaps
    event data in as raw HTML (hx-swap="beforeend" on the log <pre>) -- escaping keeps
    arbitrary task/module output from being interpreted as markup.
    """
    lines = data.splitlines() or [""]
    body = "\n".join(f"data: {html.escape(line)}" for line in lines)
    return f"{body}\n\n"
