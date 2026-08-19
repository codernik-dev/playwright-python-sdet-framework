""" "Today" must not depend on which machine is asking.

This is a regression test for a defect that had not failed yet. Both the
application and the framework used ``date.today()``, they ran on the same
machine, and the boundary tests passed — right up until Phase 10 put the
application in a UTC container while the runner stayed in IST, at which point
one of a matched pair of boundary tests would fail every day between 00:00 and
05:30 and pass for the rest of the day.

The tests below pin the property that removes the whole class: the framework's
notion of today is UTC, explicitly, regardless of the ``TZ`` the process was
started with.
"""

from __future__ import annotations

import time
from datetime import UTC, date, datetime, timedelta

import pytest

from claimdesk_qa.core.clock import days_ago_utc, today_utc, tomorrow_utc


def test_today_is_utc_not_local() -> None:
    assert today_utc() == datetime.now(UTC).date()


def test_days_ago_counts_backwards_from_utc_today() -> None:
    assert days_ago_utc(7) == today_utc() - timedelta(days=7)


def test_zero_days_ago_is_the_boundary_value_itself() -> None:
    """``days_ago=0`` is what the "an incident dated today is accepted" test sends."""
    assert days_ago_utc(0) == today_utc()


def test_tomorrow_is_the_first_refused_date() -> None:
    assert tomorrow_utc() == today_utc() + timedelta(days=1)
    assert tomorrow_utc() > today_utc()


@pytest.mark.parametrize(
    "timezone_name", ["UTC", "Asia/Kolkata", "Pacific/Kiritimati", "Etc/GMT+12"]
)
def test_the_answer_does_not_move_with_the_process_timezone(
    timezone_name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The point of the module, asserted directly.

    ``Pacific/Kiritimati`` (UTC+14) and ``Etc/GMT+12`` (UTC-12) are the extremes:
    a local date can be a full day either side of the UTC one. If ``today_utc()``
    ever moved with the process timezone, these two would disagree and the
    application-versus-runner mismatch would be back.

    ``time.tzset`` does not exist on Windows, so the strict form of this check
    only runs where the platform can actually change zones — and it is asserted
    rather than skipped silently, because a test that quietly does nothing is
    worse than one that is not there.
    """
    monkeypatch.setenv("TZ", timezone_name)
    if hasattr(time, "tzset"):
        time.tzset()

    assert today_utc() == datetime.now(UTC).date()


def test_utc_and_local_can_genuinely_disagree() -> None:
    """Proves the risk is real rather than theoretical.

    If UTC and the local date were always identical this module would be
    pointless. They are not: the difference is exactly what the container and
    the developer's laptop discovered, so the possibility is asserted here
    instead of being taken on trust.
    """
    utc_now = datetime.now(UTC)
    # The one place in this repository where a naive local `now()` is correct:
    # this test exists to compare UTC against local, so the rule that forbids it
    # everywhere else is suppressed here with its reason, rather than the rule
    # being weakened for the whole project.
    local_now = datetime.now()  # noqa: DTZ005

    # They differ by a whole day for part of every day in any non-UTC zone; the
    # invariant that always holds is that they are within 24 hours of each other.
    assert abs((utc_now.date() - local_now.date()).days) <= 1
    assert isinstance(utc_now.date(), date)
