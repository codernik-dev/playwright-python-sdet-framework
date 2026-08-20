"""Correlation identifiers that join a test to the application's own logs.

Every HTTP request the framework makes carries ``X-Request-Id``. The application
echoes it in the response and writes it to its log. When a test fails in CI you
can therefore grep the application log for one identifier and see exactly the
requests that test made - instead of guessing from timestamps.

The identifier is derived from the test's node id by hashing, which makes it:

* **stable** - the same test produces the same id in every run, so you can compare
  a failure today against the same test's requests last week;
* **short** - it appears in log lines and must stay readable;
* **safe** - node ids contain characters that do not belong in an HTTP header.

The *current* id lives in a :class:`~contextvars.ContextVar` rather than being
passed through every call. Two things need it - the log formatter and the HTTP
client - and threading an argument through both would mean every helper in
between had to know about correlation. A context variable also behaves correctly
under threads and async, where a module-level global would not.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

_PREFIX = "qa"
_DIGEST_LENGTH = 10

NO_REQUEST_ID = "-"
"""Placeholder used outside any test, e.g. during collection or session setup."""

_current_request_id: ContextVar[str] = ContextVar("claimdesk_qa_request_id", default=NO_REQUEST_ID)


def request_id_for(node_id: str, *, run_id: str | None = None) -> str:
    """Build the ``X-Request-Id`` value for a test.

    Args:
        node_id: pytest node id, e.g. ``tests/api/test_auth.py::test_login``.
        run_id: optional run identifier, included so the same test in two
            different runs can still be told apart in a shared log stream.
    """
    digest = hashlib.sha256(node_id.encode("utf-8")).hexdigest()[:_DIGEST_LENGTH]
    if run_id:
        return f"{_PREFIX}-{run_id}-{digest}"
    return f"{_PREFIX}-{digest}"


def get_request_id() -> str:
    """The correlation id currently in effect, or ``-`` outside a test."""
    return _current_request_id.get()


@contextmanager
def request_id_context(request_id: str) -> Iterator[str]:
    """Make ``request_id`` current for the duration of the block.

    The token is reset in a ``finally`` block so a failing test cannot leave its
    id in effect and mislabel everything that runs after it.
    """
    token = _current_request_id.set(request_id)
    try:
        yield request_id
    finally:
        _current_request_id.reset(token)
