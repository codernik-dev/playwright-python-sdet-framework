"""What "today" means, and why the test runner does not get to decide.

The bug this module exists to prevent
-------------------------------------
ClaimDesk refuses a claim whose incident date is in the future, and the suite
asserts both sides of that boundary — a date of *today* is accepted, *tomorrow*
is rejected.

Both the application and the framework answered "what is today?" with
``date.today()``, which is **the local date of whichever machine asked**. On a
developer's laptop that is one machine, so the two always agreed and both tests
passed.

They stop agreeing the moment those are two different machines, which is exactly
what Phase 10 built. A container runs UTC; this project is developed in IST
(UTC+05:30). Between **00:00 and 05:30 IST the runner's date is one day ahead of
the container's**, so:

* ``test_an_incident_dated_today_is_accepted`` sends a date the server considers
  *tomorrow* → ``422`` → **fails**;
* ``test_a_future_incident_date_is_rejected`` sends the day after that, which is
  still in the server's future → passes, hiding half the problem.

A test that fails for five and a half hours a day, only in the containerised
environment, and only for one of a matched pair of boundary tests. It would
present as flakiness, be blamed on the browser or the database, and survive for
months.

The fix is not "compute the offset". It is to make both sides answer the same
question the same way: **UTC, explicitly, on both sides of the boundary.** Then
they agree by construction, whatever timezone either machine is configured for.

The application was changed too, and not to make a test pass — the tests passed
before. A claims system that decides "is this date in the future" from whichever
timezone its server happens to be configured with is wrong on its own terms.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

__all__ = ["days_ago_utc", "today_utc", "tomorrow_utc"]


def today_utc() -> date:
    """Today in UTC, independent of the machine's timezone.

    Deliberately not ``date.today()``. That reads the local zone, which makes a
    date-boundary assertion depend on where the test runner happens to be — a
    dependency nobody declares and everybody forgets.
    """
    return datetime.now(UTC).date()


def days_ago_utc(days: int) -> date:
    """A UTC date in the past, for incident dates the application will accept."""
    return today_utc() - timedelta(days=days)


def tomorrow_utc() -> date:
    """The first date the application must refuse.

    Named for its meaning rather than written inline as ``today + 1``, because
    "the first refused value" is the *point* of the boundary test and a reader
    should not have to infer it from arithmetic.
    """
    return today_utc() + timedelta(days=1)
