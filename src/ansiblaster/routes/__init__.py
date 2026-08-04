"""Aggregates all route modules into one router for app.py to include."""

from __future__ import annotations

from fastapi import APIRouter

from ansiblaster.routes import pages, playbooks, roles, runs

router = APIRouter()
router.include_router(pages.router)
router.include_router(roles.router)
router.include_router(playbooks.router)
router.include_router(runs.router)
