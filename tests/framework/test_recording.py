"""The per-test evidence recorder.

The properties worth pinning are the ones that would fail *silently*: a recorder
that leaks into the next test attributes one test's traffic to another, and a
recorder that raises outside a test turns a helper script into a crash. Neither
shows up as a red test unless something asserts it here.
"""

from __future__ import annotations

import contextvars
from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeVar

import pytest

from claimdesk_qa.core.recording import (
    MAX_RECORDED_ENTRIES,
    Recording,
    active_recording,
    record_http,
    record_sql,
    recording,
)


@dataclass
class FakeEntry:
    """Stands in for an Exchange or an ExecutedQuery.

    A fake rather than the real thing on purpose: this module must work for
    anything that can render itself, and testing it against a structural
    stand-in is what proves that, rather than proving it works for one class.
    """

    text: str

    def render(self) -> str:
        return self.text


T = TypeVar("T")


def outside_any_test(scenario: Callable[[], T]) -> T:
    """Run ``scenario`` where no recorder is active.

    Needed because of a genuinely confusing detail: this suite's own autouse
    ``_recorded_evidence`` fixture activates a recorder for **every** test,
    including these. Three tests here originally asserted
    ``active_recording() is None`` and failed — not because the recorder was
    broken, but because a test can never observe "no test is running" from
    inside a test.

    ``contextvars.Context()`` is a genuinely empty context, so every ContextVar
    reads its default inside ``run``. That reproduces the real situation being
    described — a client used by a script, or by the readiness probe, with no
    test around it — using public API and without reaching into module privates.
    """
    return contextvars.Context().run(scenario)


def test_nothing_is_recorded_outside_a_test() -> None:
    """Recording must never be a precondition for using a client."""

    def scenario() -> Recording | None:
        assert active_recording() is None
        # Must not raise. A client built in a script has no recorder, and the
        # framework refusing to work there would be a far worse defect than the
        # missing evidence it was trying to collect.
        record_http(FakeEntry("GET /claims -> 200"))
        record_sql(FakeEntry("SELECT 1"))
        return active_recording()

    assert outside_any_test(scenario) is None


def test_entries_are_captured_in_order_and_kept_apart() -> None:
    with recording() as recorded:
        record_http(FakeEntry("first"))
        record_sql(FakeEntry("SELECT 1"))
        record_http(FakeEntry("second"))

        assert recorded.http.render() == "first\n\nsecond"
        assert recorded.sql.render() == "SELECT 1"


def test_an_empty_recording_says_so_rather_than_rendering_nothing() -> None:
    """An empty attachment reads as a bug in the framework; a sentence does not."""
    recorded = Recording()

    assert recorded.is_empty()
    assert recorded.http.render() == "(no HTTP requests recorded)"
    assert recorded.sql.render() == "(no SQL executed)"


def test_the_recorder_does_not_leak_into_the_next_test() -> None:
    """The dangerous failure mode: evidence that looks real and is misattributed."""

    def scenario() -> tuple[str, str, Recording | None]:
        with recording() as first:
            record_http(FakeEntry("belongs to the first test"))
        with recording() as second:
            record_http(FakeEntry("belongs to the second test"))
        return first.http.render(), second.http.render(), active_recording()

    first_rendered, second_rendered, leftover = outside_any_test(scenario)

    assert "first" in first_rendered
    assert "first" not in second_rendered
    assert leftover is None


def test_the_recorder_is_reset_even_when_the_test_raises() -> None:
    """A failing test is exactly when this matters, so it is exactly what is tested."""

    def a_test_that_fails_midway() -> None:
        with recording():
            record_http(FakeEntry("before the failure"))
            raise RuntimeError("the test failed")

    def scenario() -> Recording | None:
        with pytest.raises(RuntimeError):
            a_test_that_fails_midway()
        return active_recording()

    assert outside_any_test(scenario) is None


def test_history_is_bounded_and_says_what_it_dropped() -> None:
    """A thousand-request test must not turn its evidence into a memory problem.

    Truncating silently would be worse than not recording at all: a reader would
    draw conclusions from a timeline that quietly began in the middle.
    """
    overflow = 5
    with recording() as recorded:
        for index in range(MAX_RECORDED_ENTRIES + overflow):
            record_http(FakeEntry(f"request {index}"))

    rendered = recorded.http.render()

    assert len(recorded.http) == MAX_RECORDED_ENTRIES
    assert f"{overflow} earlier HTTP entries dropped" in rendered
    assert "request 0" not in rendered
    assert f"request {MAX_RECORDED_ENTRIES + overflow - 1}" in rendered
