"""Logging that survives parallel execution and is attachable to a report.

Three destinations, each answering a different need:

* **Console** — what a developer watches while running locally.
* **One file per xdist worker** — the full narrative of that process. Two
  processes writing to one file interleave and lose lines, so each worker gets
  its own.
* **One file per test** — the slice a reader actually wants when triaging a single
  failure. This is what gets attached to the report in Phase 8.

Every record carries the ``request_id`` of the test that produced it, so a test
log line and an application log line can be joined on one identifier.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from pathlib import Path

from claimdesk_qa.core.correlation import get_request_id, request_id_context

LOG_FORMAT = "%(asctime)s %(levelname)-7s [%(request_id)s] %(name)s: %(message)s"
DATE_FORMAT = "%H:%M:%S"

_ROOT_LOGGER_NAME = "claimdesk_qa"


class RequestIdFilter(logging.Filter):
    """Stamp every record with the correlation id currently in effect.

    Two responsibilities:

    1. Guarantee the attribute exists. The formatter references
       ``%(request_id)s``, so a library that logs without it would otherwise raise
       ``KeyError`` inside the handler — turning a logging statement into a test
       failure. Logging must never be able to break a test.
    2. Read the value from the context variable rather than from per-handler
       state.

    Point 2 was a bug fix, and the bug is instructive. Each handler originally
    carried its own filter holding its own *default value*. Filters mutate the
    **shared** record object, so whichever handler ran first stamped its default
    onto the record, and every later handler found the attribute already present
    and left it alone. The per-test log showed ``[-]`` instead of the correlation
    id, and the whole point of correlation was silently lost.

    Reading from one context variable removes the ordering dependency: it no
    longer matters which handler filters the record first, because they all
    compute the same answer.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "request_id"):
            record.request_id = get_request_id()
        return True


def get_logger(name: str | None = None) -> logging.Logger:
    """Return a framework logger. Use module ``__name__`` for the name."""
    if name is None or name == _ROOT_LOGGER_NAME:
        return logging.getLogger(_ROOT_LOGGER_NAME)
    return logging.getLogger(f"{_ROOT_LOGGER_NAME}.{name}")


def configure_logging(*, level: str, worker_log: Path) -> logging.Logger:
    """Configure the framework logger for one worker process.

    Levels are set per destination, which matters more than it looks:

    * the **logger** is set to DEBUG, because a record filtered out at the logger
      never reaches any handler — set it to INFO and the debug detail is gone
      before the files ever see it;
    * the **console** is set to ``level`` (INFO by default), so watching a local
      run stays readable;
    * the **files** stay at DEBUG, because a log file exists precisely for the
      moment something failed and you want everything.

    Getting this backwards produces the worst possible outcome: an artefact
    directory full of empty log files, discovered while triaging a real failure.

    Idempotent: calling it twice does not double every line, which matters because
    pytest can import a conftest more than once in some layouts.

    Deliberately configures the ``claimdesk_qa`` logger rather than the root
    logger, so the framework's own output stays separate from third-party noise.
    """
    logger = get_logger()
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()
    for existing in list(logger.filters):
        logger.removeFilter(existing)

    formatter = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)

    # The filter goes on every HANDLER, not on the logger. A logger's filters are
    # only applied to records logged through that logger directly - records from a
    # child logger such as claimdesk_qa.api reach the parent's handlers via
    # callHandlers, which skips the parent's filters entirely. A logger-level
    # filter therefore leaves child records without request_id, the formatter
    # raises KeyError, and the line is silently dropped.
    console = logging.StreamHandler()
    console.setFormatter(formatter)
    console.addFilter(RequestIdFilter())
    console.setLevel(level)
    logger.addHandler(console)

    worker_log.parent.mkdir(parents=True, exist_ok=True)
    file_handler = logging.FileHandler(worker_log, encoding="utf-8")
    file_handler.setFormatter(formatter)
    file_handler.addFilter(RequestIdFilter())
    file_handler.setLevel(logging.DEBUG)
    logger.addHandler(file_handler)

    return logger


@contextmanager
def per_test_log(path: Path, *, request_id: str, level: str = "DEBUG") -> Iterator[Path]:
    """Capture this test's log lines into their own file.

    The handler is removed in a ``finally`` block, so a test that fails — or is
    interrupted — cannot leave a handler attached and start bleeding its output
    into every subsequent test's file.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(path, encoding="utf-8")
    handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT))
    handler.addFilter(RequestIdFilter())
    handler.setLevel(level)

    logger = get_logger()
    logger.addHandler(handler)
    with ExitStack() as stack:
        # Making the id current here means the console and worker log carry it too,
        # not just this file - so all three destinations agree for this window.
        stack.enter_context(request_id_context(request_id))
        stack.callback(handler.close)
        stack.callback(logger.removeHandler, handler)
        yield path
