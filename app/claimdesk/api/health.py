"""Liveness and readiness probes.

Two separate endpoints, because they answer different questions:

* ``/health``       - is the process up? Used by Docker and by a load balancer.
* ``/health/ready`` - can it actually serve traffic (database reachable)?

The test framework polls ``/health/ready`` before starting a run. That is what
replaces ``sleep 10`` after ``docker compose up`` - a readiness check that is
allowed to fail is infinitely better than a guess that is allowed to be wrong.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from claimdesk import __version__
from claimdesk.db import get_session

router = APIRouter(tags=["health"])


@router.get("/health")
def liveness() -> dict[str, str]:
    return {"status": "ok", "version": __version__}


@router.get("/health/ready")
def readiness(response: Response, session: Session = Depends(get_session)) -> dict[str, str]:
    try:
        session.execute(text("SELECT 1"))
    except Exception:  # any failure at all means "not ready"; the cause is in the server log
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "unavailable", "database": "unreachable"}
    return {"status": "ready", "database": "reachable"}
