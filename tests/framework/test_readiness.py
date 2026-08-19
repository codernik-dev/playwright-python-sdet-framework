"""Unit tests for the readiness wait.

The probe, clock and sleep are all injected, so these tests prove that a 60-second
timeout times out — without spending 60 seconds doing it. A test suite that is
slow to test its own slowness stops being run.
"""

from __future__ import annotations

import pytest

from claimdesk_qa.core.exceptions import ServiceNotReadyError
from claimdesk_qa.core.readiness import wait_until_ready

pytestmark = pytest.mark.smoke


class FakeClock:
    """A monotonic clock that only advances when something sleeps."""

    def __init__(self) -> None:
        self.now = 0.0
        self.slept: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


def test_returns_immediately_when_already_ready() -> None:
    """A service that is already up must cost nothing — the case that runs most."""
    clock = FakeClock()

    elapsed = wait_until_ready(
        lambda: (True, "HTTP 200"),
        description="service",
        timeout_seconds=30,
        sleep=clock.sleep,
        monotonic=clock.monotonic,
    )

    assert elapsed == 0.0
    assert clock.slept == []


def test_polls_until_the_service_comes_up() -> None:
    clock = FakeClock()
    attempts = {"count": 0}

    def probe() -> tuple[bool, str]:
        attempts["count"] += 1
        return (attempts["count"] >= 3, "starting")

    wait_until_ready(
        probe,
        description="service",
        timeout_seconds=30,
        interval_seconds=0.5,
        sleep=clock.sleep,
        monotonic=clock.monotonic,
    )

    assert attempts["count"] == 3
    assert clock.slept == [0.5, 0.5]


@pytest.mark.negative
def test_times_out_with_a_message_that_blames_the_environment() -> None:
    """The message must make it obvious this is not a product defect.

    A connection error surfacing as a wall of red test failures is how teams start
    distrusting a suite. The wording matters as much as the behaviour.
    """
    clock = FakeClock()

    with pytest.raises(ServiceNotReadyError) as exc:
        wait_until_ready(
            lambda: (False, "Connection refused"),
            description="ClaimDesk at http://localhost:8000",
            timeout_seconds=2,
            interval_seconds=0.5,
            sleep=clock.sleep,
            monotonic=clock.monotonic,
        )

    message = str(exc.value)
    assert "ClaimDesk at http://localhost:8000" in message
    assert "Connection refused" in message  # the last thing actually observed
    assert "attempt(s)" in message  # how hard it tried
    assert "environment problem, not a product defect" in message


@pytest.mark.negative
def test_never_sleeps_past_the_deadline() -> None:
    """A wait budgeted at 2s must not take 2.5s because of a final sleep."""
    clock = FakeClock()

    with pytest.raises(ServiceNotReadyError):
        wait_until_ready(
            lambda: (False, "not yet"),
            description="service",
            timeout_seconds=2,
            interval_seconds=0.5,
            sleep=clock.sleep,
            monotonic=clock.monotonic,
        )

    assert clock.now <= 2.0


@pytest.mark.boundary
def test_a_zero_timeout_still_gives_the_probe_one_attempt() -> None:
    """Probe first, then check the clock — otherwise an up service could still fail."""
    clock = FakeClock()

    elapsed = wait_until_ready(
        lambda: (True, "HTTP 200"),
        description="service",
        timeout_seconds=0,
        sleep=clock.sleep,
        monotonic=clock.monotonic,
    )

    assert elapsed == 0.0
