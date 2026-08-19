"""The HTTP client every API call goes through.

A facade over ``httpx`` with five responsibilities, each of which would otherwise
be repeated in every test:

1. **Authentication** — one identity per client, sent as a bearer header.
2. **No cookie jar** — see :class:`ApiClient` and ADR 0007. This one is a
   correctness control, not a convenience.
3. **Correlation** — every request carries the current test's ``X-Request-Id``.
4. **Timeouts** — mandatory, so a hung dependency fails a test instead of a job.
5. **Recording** — the last N exchanges are kept in memory and attached to the
   report when a test fails, so a CI failure can be diagnosed without a rerun.

The response wrapper exists for one reason: assertion messages. A bare
``assert response.status_code == 201`` tells you a number was wrong. The wrapper's
message tells you the method, the URL, the expected and actual status, the
correlation id and the response body — which is usually the whole diagnosis.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from types import TracebackType
from typing import Any, Self, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from claimdesk_qa.core.correlation import get_request_id
from claimdesk_qa.core.logging import get_logger

logger = get_logger(__name__)

ModelT = TypeVar("ModelT", bound=BaseModel)

REQUEST_ID_HEADER = "X-Request-Id"

#: Enough context to explain a failure, small enough to attach to a report.
MAX_RECORDED_EXCHANGES = 25

#: Response bodies are truncated in assertion messages; a 2 MB HTML error page in
#: a pytest traceback helps nobody.
MAX_BODY_IN_MESSAGE = 1500


@dataclass(frozen=True, slots=True)
class Exchange:
    """One request/response pair, kept for failure diagnosis."""

    method: str
    url: str
    status_code: int
    elapsed_ms: float
    request_body: str | None
    response_body: str

    def render(self) -> str:
        lines = [f"{self.method} {self.url} -> {self.status_code} ({self.elapsed_ms:.0f} ms)"]
        if self.request_body:
            lines.append(f"  request : {_truncate(self.request_body)}")
        lines.append(f"  response: {_truncate(self.response_body)}")
        return "\n".join(lines)


def _truncate(text: str, limit: int = MAX_BODY_IN_MESSAGE) -> str:
    if len(text) <= limit:
        return text
    return f"{text[:limit]}... [{len(text) - limit} more characters]"


class ApiResponse:
    """A response plus assertions that explain themselves when they fail."""

    def __init__(self, response: httpx.Response, request_id: str) -> None:
        self._response = response
        self._request_id = request_id

    @property
    def raw(self) -> httpx.Response:
        return self._response

    @property
    def status_code(self) -> int:
        return self._response.status_code

    @property
    def headers(self) -> httpx.Headers:
        return self._response.headers

    @property
    def elapsed_ms(self) -> float:
        return self._response.elapsed.total_seconds() * 1000

    def json(self) -> Any:
        return self._response.json()

    def expect_status(self, *expected: int) -> Self:
        """Assert the status code, failing with everything needed to diagnose it.

        Returns ``self`` so calls chain:
        ``claims.create(payload).expect_status(201).model(ClaimModel)``.
        """
        if self._response.status_code in expected:
            return self

        wanted = " or ".join(str(code) for code in expected)
        message = (
            f"Expected HTTP {wanted} but got {self._response.status_code}\n"
            f"  {self._response.request.method} {self._response.request.url}\n"
            f"  {REQUEST_ID_HEADER}: {self._request_id}\n"
            f"  response: {_truncate(self._response.text)}"
        )
        raise AssertionError(message)

    def model(self, model_type: type[ModelT]) -> ModelT:
        """Validate the body against a contract and return the typed object.

        A ``ValidationError`` is re-raised as an ``AssertionError``: a response
        that does not match its contract is a **product** failure, not a framework
        crash, and it must be reported as such.
        """
        try:
            return model_type.model_validate(self._response.json())
        except ValidationError as exc:
            message = (
                f"Response did not match the {model_type.__name__} contract\n"
                f"  {self._response.request.method} {self._response.request.url}\n"
                f"  {REQUEST_ID_HEADER}: {self._request_id}\n"
                f"  problems: {exc.error_count()}\n{exc}\n"
                f"  response: {_truncate(self._response.text)}"
            )
            raise AssertionError(message) from exc

    def detail(self) -> str:
        """The error message from a FastAPI error body, for asserting on wording."""
        try:
            body = self._response.json()
        except ValueError:
            return self._response.text
        detail = body.get("detail") if isinstance(body, dict) else None
        if isinstance(detail, str):
            return detail
        if isinstance(detail, list):
            return "; ".join(str(item.get("msg", item)) for item in detail)
        return self._response.text


@dataclass
class ApiClient:
    """One HTTP client for one identity.

    **There is deliberately no shared client and no cookie jar.** ClaimDesk returns
    a ``session`` cookie on login, and ``httpx.Client`` persists cookies by
    default. During Phase 3 that combination made an unauthenticated test pass:
    the request carried no ``Authorization`` header, but the leftover cookie
    authenticated it anyway, and the assertion "anonymous requests are rejected"
    passed while testing an authenticated request.

    That is the worst class of test defect — it does not fail, it passes for the
    wrong reason, and it would keep passing with authentication removed entirely.
    So cookies are discarded after every response and each identity gets its own
    client. See ``docs/adr/0007-no-shared-cookie-jar.md``.
    """

    base_url: str
    timeout_seconds: float
    token: str | None = None
    _client: httpx.Client = field(init=False, repr=False)
    _exchanges: deque[Exchange] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._client = httpx.Client(
            base_url=self.base_url,
            timeout=self.timeout_seconds,
            follow_redirects=False,
        )
        self._exchanges = deque(maxlen=MAX_RECORDED_EXCHANGES)

    # -- lifecycle --------------------------------------------------------- #

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def with_token(self, token: str | None) -> ApiClient:
        """A separate client for another identity. Never mutates this one.

        Returning a new client rather than swapping the token in place is what
        stops a test from accidentally reusing an admin token in a step meant to
        run as a customer.
        """
        return ApiClient(
            base_url=self.base_url,
            timeout_seconds=self.timeout_seconds,
            token=token,
        )

    # -- requests ---------------------------------------------------------- #

    @property
    def exchanges(self) -> list[Exchange]:
        return list(self._exchanges)

    def render_exchanges(self) -> str:
        """The recorded traffic, for attaching to a failing test's report."""
        if not self._exchanges:
            return "(no HTTP requests recorded)"
        return "\n\n".join(exchange.render() for exchange in self._exchanges)

    def request(
        self,
        method: str,
        path: str,
        *,
        json: Any | None = None,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        authenticate: bool = True,
    ) -> ApiResponse:
        request_id = get_request_id()
        merged: dict[str, str] = {REQUEST_ID_HEADER: request_id}
        if authenticate and self.token:
            merged["Authorization"] = f"Bearer {self.token}"
        if headers:
            merged.update(headers)

        response = self._client.request(
            method,
            path,
            json=json,
            params=_clean_params(params),
            headers=merged,
        )

        # Discard any Set-Cookie before it can authenticate a later request.
        self._client.cookies.clear()

        self._record(method, response, json)
        return ApiResponse(response, request_id)

    def _record(self, method: str, response: httpx.Response, request_body: Any | None) -> None:
        exchange = Exchange(
            method=method.upper(),
            url=str(response.request.url),
            status_code=response.status_code,
            elapsed_ms=response.elapsed.total_seconds() * 1000,
            request_body=None if request_body is None else str(request_body),
            response_body=response.text,
        )
        self._exchanges.append(exchange)
        logger.debug("%s", exchange.render())

    def get(self, path: str, **kwargs: Any) -> ApiResponse:
        return self.request("GET", path, **kwargs)

    def post(self, path: str, **kwargs: Any) -> ApiResponse:
        return self.request("POST", path, **kwargs)

    def patch(self, path: str, **kwargs: Any) -> ApiResponse:
        return self.request("PATCH", path, **kwargs)

    def delete(self, path: str, **kwargs: Any) -> ApiResponse:
        return self.request("DELETE", path, **kwargs)


def _clean_params(params: dict[str, Any] | None) -> dict[str, Any] | None:
    """Drop ``None`` values so an unset filter is absent rather than ``"None"``.

    Without this, ``params={"status": None}`` sends ``?status=None`` and the API
    rejects it — a confusing 422 caused entirely by the test.
    """
    if params is None:
        return None
    return {key: value for key, value in params.items() if value is not None}
