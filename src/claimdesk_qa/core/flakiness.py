"""The retry policy, and the reproducibility seed. Both exist to stop lying.

Retries are the most abused feature in test automation. ``--reruns 3`` turns a
red build green, and everybody involved is briefly happier and permanently worse
off: the defect is still there, the suite now takes three times as long to fail,
and the signal that something is wrong has been deliberately deleted.

So the policy here is narrow and written down:

1. **Retries are diagnostics, not a cure.** A rerun answers one question - "is
   this reproducible?" - and nothing else.
2. **UI and end-to-end only.** A browser genuinely shares a machine with a
   compositor, a renderer and a network stack. An API or database test that
   fails twice out of ten is not flaky, it is **wrong**, and retrying it hides a
   real defect in the product or in the test.
3. **CI only.** Locally a flake should be reproduced, not papered over. The
   developer is right there.
4. **One retry.** If one is not enough to decide whether it reproduces, the
   answer is not two.
5. **A test that passes on retry is reported as FLAKY, never as green.** This is
   the part that makes the other four honest - see
   ``pytest_terminal_summary`` in ``tests/conftest.py``.

The seed lives here for the same reason: a flake nobody can reproduce is a flake
nobody will fix, and the seed is what makes generated data reproducible.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable

#: One. Deliberately not configurable. A retry budget that can be raised will be
#: raised, at 5pm, by whoever is trying to ship.
MAX_RERUNS = 1

#: Layers where a retry is a legitimate diagnostic rather than a cover-up.
_RETRYABLE_LAYERS = frozenset({"ui", "e2e"})


def reruns_for(marker_names: Iterable[str], *, is_ci: bool) -> int:
    """How many times this test may be retried. Almost always zero.

    Args:
        marker_names: the test's markers, which already carry its layer.
        is_ci: whether this is an unattended run.

    Returns:
        ``MAX_RERUNS`` for a browser test in CI, otherwise ``0``.
    """
    if not is_ci:
        return 0
    if _RETRYABLE_LAYERS.isdisjoint(marker_names):
        return 0
    return MAX_RERUNS


def effective_seed(configured: int | None, run_id: str) -> int:
    """The seed this run actually used - never ``None``.

    Reporting ``faker_seed=None`` when none was configured is technically true
    and practically useless: a seed *was* used, it was simply derived rather than
    supplied, and a reader who wants to reproduce the run needs the number that
    was used, not the fact that they did not choose it.

    Deriving it from the run id keeps two properties at once: the data differs
    between runs (so a collision-by-luck cannot hide a bug for long), and any
    single run is exactly reproducible by passing this number back as
    ``FAKER_SEED``.
    """
    if configured is not None:
        return configured
    return int(hashlib.sha256(run_id.encode()).hexdigest()[:8], 16)
