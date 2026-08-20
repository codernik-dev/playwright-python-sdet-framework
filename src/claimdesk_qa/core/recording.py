"""What a test did, kept in memory, attached to the report only when it fails.

The problem this solves
-----------------------
When a suite goes red at 03:00, the question is never "which assertion failed" -
the report already says that. It is **"what actually happened before it?"** The
HTTP exchanges and the SQL that ran are the answer, and by the time anyone reads
the report the process that knew them has exited.

:class:`~claimdesk_qa.api.client.ApiClient` and
:class:`~claimdesk_qa.db.connection.Database` each already keep their own recent
history. That is not enough on its own: one test routinely uses three clients (a
customer, an adjuster and an admin) plus a database connection, and a reader
wants **one timeline**, not four fragments they have to interleave by hand.

So there is one recorder per test, and the objects push into whichever recorder is
active. A ``ContextVar`` carries it - the same mechanism the correlation id uses -
which keeps the clients free of any parameter for something they should not have
to know about.

Two properties matter more than the feature itself:

* **Recording never fails a test.** With no recorder active every call is a
  no-op, so a client built outside a test - in a script, in a REPL, in the
  readiness probe - behaves exactly as before.
* **It is bounded.** A parametrised test that makes a thousand requests must not
  turn its own evidence into a memory problem, so each stream keeps the most
  recent :data:`MAX_RECORDED_ENTRIES` and says how many it dropped.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Protocol

#: Enough to explain a failure, small enough that attaching it stays free.
MAX_RECORDED_ENTRIES = 100


class Renderable(Protocol):
    """Anything that can describe itself for a human reading a failure.

    A structural type rather than a base class, deliberately: ``core`` must not
    import ``api`` or ``db`` - the dependency arrows in this framework point one
    way - and a Protocol lets those layers hand their own value objects over
    without either side importing the other.
    """

    def render(self) -> str: ...


@dataclass
class Stream:
    """One bounded, ordered sequence of recorded entries."""

    label: str
    empty_message: str
    _entries: deque[str] = field(init=False, repr=False)
    _dropped: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        self._entries = deque(maxlen=MAX_RECORDED_ENTRIES)

    def add(self, item: Renderable) -> None:
        """Render immediately rather than keeping the object.

        Rendering now costs a string; keeping the object would keep whatever it
        references alive - a response body, a connection - for the rest of the
        test.
        """
        if len(self._entries) == MAX_RECORDED_ENTRIES:
            self._dropped += 1
        self._entries.append(item.render())

    def __len__(self) -> int:
        return len(self._entries)

    def render(self) -> str:
        if not self._entries:
            return self.empty_message
        body = "\n\n".join(self._entries)
        if self._dropped:
            header = (
                f"[{self._dropped} earlier {self.label} entries dropped; "
                f"showing the most recent {MAX_RECORDED_ENTRIES}]\n\n"
            )
            return header + body
        return body


@dataclass
class Recording:
    """Everything one test recorded."""

    http: Stream = field(
        default_factory=lambda: Stream(label="HTTP", empty_message="(no HTTP requests recorded)")
    )
    sql: Stream = field(
        default_factory=lambda: Stream(label="SQL", empty_message="(no SQL executed)")
    )

    def is_empty(self) -> bool:
        """True when there is nothing worth attaching."""
        return not len(self.http) and not len(self.sql)


_active: ContextVar[Recording | None] = ContextVar("claimdesk_qa_recording", default=None)


def active_recording() -> Recording | None:
    """The recorder for the test currently running, or ``None`` outside one."""
    return _active.get()


def record_http(exchange: Renderable) -> None:
    """Add one request/response pair. A no-op when no test is recording."""
    recording = _active.get()
    if recording is not None:
        recording.http.add(exchange)


def record_sql(query: Renderable) -> None:
    """Add one executed statement. A no-op when no test is recording."""
    recording = _active.get()
    if recording is not None:
        recording.sql.add(query)


@contextmanager
def recording() -> Iterator[Recording]:
    """Make a fresh recorder current for the duration of one test.

    The token is reset in a ``finally`` block, so a test that raises cannot leave
    its recorder attached and start collecting the *next* test's traffic - which
    would be worse than collecting nothing, because the evidence would look
    genuine while describing the wrong test.
    """
    fresh = Recording()
    token = _active.set(fresh)
    try:
        yield fresh
    finally:
        _active.reset(token)
