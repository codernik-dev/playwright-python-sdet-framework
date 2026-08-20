"""Unit tests for logging and correlation identifiers."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from claimdesk_qa.core.correlation import (
    NO_REQUEST_ID,
    _current_request_id,
    get_request_id,
    request_id_context,
    request_id_for,
)
from claimdesk_qa.core.logging import (
    RequestIdFilter,
    configure_logging,
    get_logger,
    per_test_log,
)

pytestmark = pytest.mark.smoke


# --------------------------------------------------------------------------- #
# correlation ids
# --------------------------------------------------------------------------- #


def test_request_id_is_stable_across_runs() -> None:
    """Stability is the feature: it lets you compare a test's requests over time."""
    node_id = "tests/api/test_auth.py::test_login"

    assert request_id_for(node_id) == request_id_for(node_id)


def test_different_tests_get_different_request_ids() -> None:
    a = request_id_for("tests/api/test_auth.py::test_login")
    b = request_id_for("tests/api/test_auth.py::test_logout")

    assert a != b


def test_request_id_is_safe_as_an_http_header_value() -> None:
    """Node ids contain '/', ':' and brackets; a header value must not."""
    generated = request_id_for('tests/ui/test_x.py::test_case[a b|"c"]')

    assert generated.isascii()
    assert not set(generated) & set(' "/:[]|')
    assert len(generated) <= 32


def test_run_id_can_be_folded_in_to_separate_concurrent_runs() -> None:
    node_id = "tests/api/test_auth.py::test_login"

    assert request_id_for(node_id, run_id="r1") != request_id_for(node_id, run_id="r2")


# --------------------------------------------------------------------------- #
# logging configuration
# --------------------------------------------------------------------------- #


def test_configure_logging_is_idempotent(tmp_path: Path) -> None:
    """Calling it twice must not double every line - conftest can be imported twice."""
    log_file = tmp_path / "worker-main.log"

    configure_logging(level="INFO", worker_log=log_file)
    configure_logging(level="INFO", worker_log=log_file)
    logger = get_logger()

    assert len(logger.handlers) == 2  # console + file, not four


def test_messages_reach_the_worker_log_file(tmp_path: Path) -> None:
    log_file = tmp_path / "worker-main.log"
    configure_logging(level="INFO", worker_log=log_file)

    get_logger("probe").info("hello from the worker")

    assert "hello from the worker" in log_file.read_text(encoding="utf-8")


def test_a_record_from_a_child_logger_still_reaches_the_file(tmp_path: Path) -> None:
    """Regression test. Logging must never be able to fail or swallow a line.

    The formatter references %(request_id)s. When the filter lived on the logger
    instead of on the handlers, records emitted through a CHILD logger reached the
    parent's handlers via callHandlers without ever passing the parent's filters -
    so request_id was missing, the formatter raised KeyError, and the line
    vanished. Nothing failed loudly; the log was simply empty.
    """
    log_file = tmp_path / "worker-main.log"
    configure_logging(level="INFO", worker_log=log_file)

    logging.getLogger("claimdesk_qa.thirdparty.deeply.nested").warning("from a child logger")

    contents = log_file.read_text(encoding="utf-8")
    assert "from a child logger" in contents


def test_request_id_filter_does_not_overwrite_an_explicit_value() -> None:
    """An explicit extra={"request_id": ...} must win over the ambient context."""
    record = logging.LogRecord("n", logging.INFO, "p", 1, "m", None, None)
    record.request_id = "qa-explicit"

    with request_id_context("qa-ambient"):
        RequestIdFilter().filter(record)

    # __dict__ is what the formatter interpolates, so it is what actually matters.
    assert record.__dict__["request_id"] == "qa-explicit"


def test_context_variable_is_restored_after_the_block() -> None:
    """A failing test must not leave its id in effect and mislabel later output.

    Compared against the ambient value rather than the module default, because
    these tests themselves run inside a correlation context: the autouse per-test
    log fixture in tests/conftest.py has already set one. Asserting the default
    here would be asserting that the framework is NOT doing its job.
    """
    outer = get_request_id()

    with request_id_context("qa-inner"):
        assert get_request_id() == "qa-inner"

    assert get_request_id() == outer


def test_context_variable_is_restored_even_when_the_block_raises() -> None:
    outer = get_request_id()

    def _explode() -> None:
        with request_id_context("qa-inner"):
            msg = "boom"
            raise RuntimeError(msg)

    with pytest.raises(RuntimeError):
        _explode()

    assert get_request_id() == outer


def test_the_default_outside_any_context_is_a_placeholder() -> None:
    """Session setup and collection log before any test owns the context."""
    assert NO_REQUEST_ID == "-"
    assert _current_request_id.get(NO_REQUEST_ID) is not None


# --------------------------------------------------------------------------- #
# per-test log capture
# --------------------------------------------------------------------------- #


def test_per_test_log_captures_only_its_own_window(tmp_path: Path) -> None:
    configure_logging(level="DEBUG", worker_log=tmp_path / "worker.log")
    logger = get_logger("probe")
    test_log = tmp_path / "test.log"

    logger.info("before")
    with per_test_log(test_log, request_id="qa-abc123"):
        logger.info("during")
    logger.info("after")

    captured = test_log.read_text(encoding="utf-8")
    assert "during" in captured
    assert "before" not in captured
    assert "after" not in captured
    assert "qa-abc123" in captured


def test_debug_detail_reaches_the_files_even_when_the_console_is_quiet(
    tmp_path: Path,
) -> None:
    """Regression test for empty artefact logs.

    Setting the LOGGER to INFO drops debug records before any handler sees them,
    so every per-test log file ends up empty - which is discovered at the worst
    possible moment, while triaging a real failure. The logger stays at DEBUG and
    only the console is levelled.
    """
    worker_log = tmp_path / "worker.log"
    configure_logging(level="INFO", worker_log=worker_log)

    with per_test_log(tmp_path / "test.log", request_id="qa-debug"):
        get_logger("probe").debug("fine-grained detail")

    assert "fine-grained detail" in worker_log.read_text(encoding="utf-8")
    assert "fine-grained detail" in (tmp_path / "test.log").read_text(encoding="utf-8")


def test_the_correlation_id_reaches_every_destination_not_just_the_test_file(
    tmp_path: Path,
) -> None:
    """Regression test for a real bug.

    Handler-level filters mutate the shared LogRecord, so whichever handler ran
    first stamped its own default and every later handler left the attribute
    alone. The per-test file showed "[-]" and correlation was silently useless.
    The filter now lives on the logger and reads one context variable, so all
    destinations agree.
    """
    worker_log = tmp_path / "worker.log"
    configure_logging(level="DEBUG", worker_log=worker_log)

    with per_test_log(tmp_path / "test.log", request_id="qa-shared"):
        get_logger("probe").info("correlated line")

    assert "qa-shared" in worker_log.read_text(encoding="utf-8")
    assert "qa-shared" in (tmp_path / "test.log").read_text(encoding="utf-8")


def test_the_handler_is_removed_even_when_the_test_raises(tmp_path: Path) -> None:
    """A leaked handler would bleed one test's output into every later test's file."""
    configure_logging(level="DEBUG", worker_log=tmp_path / "worker.log")
    logger = get_logger()
    before = len(logger.handlers)

    def _explode() -> None:
        with per_test_log(tmp_path / "t.log", request_id="qa-x"):
            msg = "boom"
            raise RuntimeError(msg)

    with pytest.raises(RuntimeError):
        _explode()

    assert len(logger.handlers) == before
