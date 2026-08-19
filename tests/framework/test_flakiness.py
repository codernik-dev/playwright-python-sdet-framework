"""The retry policy and the reproducibility seed.

The retry policy is the one piece of this framework that can silently destroy
its own value. Every assertion here is really the same assertion: a retry must
never be able to turn a real defect into a green build.
"""

from __future__ import annotations

import pytest

from claimdesk_qa.core.flakiness import MAX_RERUNS, effective_seed, reruns_for


@pytest.mark.parametrize("layer", ["api", "db", "framework"])
def test_api_and_database_tests_are_never_retried(layer: str) -> None:
    """Not even in CI, and this is the important one.

    A browser shares a machine with a compositor and a renderer, so a retry
    there answers a real question. An API or database test that fails
    intermittently is not flaky, it is **wrong** — a race, a shared-state
    assumption, a real product defect — and retrying it deletes the evidence.
    """
    assert reruns_for({layer}, is_ci=True) == 0
    assert reruns_for({layer}, is_ci=False) == 0


@pytest.mark.parametrize("layer", ["ui", "e2e"])
def test_browser_tests_are_retried_once_in_ci_only(layer: str) -> None:
    """Locally a flake should be reproduced — the developer is right there."""
    assert reruns_for({layer}, is_ci=True) == MAX_RERUNS
    assert reruns_for({layer}, is_ci=False) == 0


def test_the_retry_budget_is_one() -> None:
    """If one retry cannot decide whether a failure reproduces, two will not either.

    Pinned as a test because this is the number that gets quietly raised at 5pm
    by whoever is trying to ship.
    """
    assert MAX_RERUNS == 1


def test_a_mixed_marker_set_still_resolves() -> None:
    """Layer plus intent markers arrive together; only the layer decides."""
    assert reruns_for({"e2e", "smoke", "negative"}, is_ci=True) == MAX_RERUNS
    assert reruns_for({"api", "smoke", "negative"}, is_ci=True) == 0


# --------------------------------------------------------------------------- #
# the seed
# --------------------------------------------------------------------------- #


def test_a_configured_seed_is_used_exactly() -> None:
    """Reproducing a failure means using the number you were given, unmodified."""
    assert effective_seed(20260819, "any-run-id") == 20260819


def test_a_configured_seed_of_zero_is_honoured() -> None:
    """Zero is a seed, not "unset".

    Written because `if configured:` would silently ignore it, and the failure
    would be invisible: the run would still work, simply not with the seed the
    person asked for.
    """
    assert effective_seed(0, "any-run-id") == 0


def test_an_unset_seed_still_produces_one() -> None:
    """`faker_seed=None` in a report tells a reader nothing they can act on."""
    seed = effective_seed(None, "20260819-120000-ab12")

    assert isinstance(seed, int)
    assert seed >= 0


def test_the_derived_seed_is_stable_for_a_given_run() -> None:
    """The header, the fixture and the report must all print the same number."""
    assert effective_seed(None, "20260819-120000-ab12") == effective_seed(
        None, "20260819-120000-ab12"
    )


def test_different_runs_get_different_seeds() -> None:
    """Otherwise every run generates identical data and a collision hides forever."""
    assert effective_seed(None, "run-one") != effective_seed(None, "run-two")
