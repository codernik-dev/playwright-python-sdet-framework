"""Application entry point.

Run locally:

    uvicorn claimdesk.main:app --app-dir app --port 8000

Note the ``--app-dir app``: the application is deliberately *not* installed as part
of the test framework's package. Keeping it out of ``src/`` makes the black-box
boundary structural rather than merely a rule.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from claimdesk import __version__
from claimdesk.api import api_router
from claimdesk.api import health as health_api
from claimdesk.config import get_app_settings
from claimdesk.db import Base, SessionFactory, engine
from claimdesk.domain import DomainError
from claimdesk.seed import seed
from claimdesk.web.routes import router as web_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s [req=%(request_id)s] %(message)s",
)

REQUEST_ID_HEADER = "X-Request-Id"


class _RequestIdFilter(logging.Filter):
    """Guarantee every log record has a request_id, even outside a request."""

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "request_id"):
            record.request_id = "-"
        return True


for handler in logging.getLogger().handlers:
    handler.addFilter(_RequestIdFilter())

logger = logging.getLogger("claimdesk")


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    settings = get_app_settings()
    if settings.auto_migrate:
        Base.metadata.create_all(bind=engine)
        with SessionFactory() as session:
            seed(session)
        logger.info("Schema ensured and seed data applied")
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="ClaimDesk",
        version=__version__,
        description=(
            "Insurance claims intake and adjudication. This application exists as a "
            "fixture for an SDET automation framework."
        ),
        lifespan=lifespan,
    )

    @app.middleware("http")
    async def correlation_id(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """Echo the caller's request id, or mint one.

        The test framework sends a request id derived from the test's node id, so a
        failed test's HTTP call can be joined to this application's log with one
        grep. Twenty lines of code that turn "it failed in CI" into "here is the
        exact request that failed".
        """
        request_id = request.headers.get(REQUEST_ID_HEADER) or uuid.uuid4().hex
        response = await call_next(request)
        response.headers[REQUEST_ID_HEADER] = request_id
        logger.info(
            "%s %s -> %s",
            request.method,
            request.url.path,
            response.status_code,
            extra={"request_id": request_id},
        )
        return response

    @app.exception_handler(DomainError)
    async def domain_error_handler(_: Request, exc: DomainError) -> JSONResponse:
        """Map a business-rule violation onto the status code the rule declares."""
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.message})

    app.include_router(health_api.router)
    app.include_router(api_router)
    app.include_router(web_router)
    return app


app = create_app()
