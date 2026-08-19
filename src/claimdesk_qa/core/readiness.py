"""Wait for a dependency to become ready — the replacement for ``sleep``.

Why this module exists at all
-----------------------------
The most common way a containerised test suite becomes flaky is this line:

```python
subprocess.run(["docker", "compose", "up", "-d"])
time.sleep(10)          # "should be enough"
```

It is wrong in both directions. On a fast machine it wastes ten seconds on every
run. On a loaded CI agent it is not enough, and the suite fails with a connection
error that looks like a product defect. The fix is not a bigger number — it is to
**ask the service whether it is ready** and to fail with a message that says what
was being waited for.

The probe is injectable so this logic can be unit-tested without starting a
server: the framework's own tests drive it with a fake probe, which is why
``tests/framework`` needs no application running.
"""

from __future__ import annotations

import time
from collections.abc import Callable

import httpx

from claimdesk_qa.core.exceptions import ServiceNotReadyError
from claimdesk_qa.core.logging import get_logger

logger = get_logger(__name__)

#: A probe returns ``(ready, detail)``. ``detail`` is shown in the failure message.
Probe = Callable[[], tuple[bool, str]]

DEFAULT_INTERVAL_SECONDS = 0.5


def http_probe(url: str, *, timeout_seconds: float = 5.0) -> Probe:
    """A probe that treats any 2xx response as ready.

    Connection errors are ready-is-false, not exceptions: a service that has not
    started yet legitimately refuses connections, and that is the normal case
    while waiting rather than an error.
    """

    def _probe() -> tuple[bool, str]:
        try:
            response = httpx.get(url, timeout=timeout_seconds)
        except httpx.HTTPError as exc:
            return False, f"{type(exc).__name__}: {exc}"
        if response.is_success:
            return True, f"HTTP {response.status_code}"
        return False, f"HTTP {response.status_code}: {response.text[:200]}"

    return _probe


def wait_until_ready(
    probe: Probe,
    *,
    description: str,
    timeout_seconds: float,
    interval_seconds: float = DEFAULT_INTERVAL_SECONDS,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> float:
    """Poll ``probe`` until it reports ready. Returns how long that took.

    Args:
        probe: callable returning ``(ready, detail)``.
        description: what is being waited for, used in the failure message.
        timeout_seconds: total budget.
        interval_seconds: gap between attempts.
        sleep, monotonic: injected for testing, so the unit tests do not have to
            spend real seconds proving that a timeout times out.

    Raises:
        ServiceNotReadyError: with the number of attempts, the elapsed time and
            the last detail seen — everything needed to diagnose it from a CI log
            without reproducing the failure.
    """
    started = monotonic()
    attempts = 0
    detail = "no attempt made"

    while True:
        attempts += 1
        ready, detail = probe()
        elapsed = monotonic() - started
        if ready:
            logger.info(
                "%s became ready after %.2fs (%d attempt(s)): %s",
                description,
                elapsed,
                attempts,
                detail,
            )
            return elapsed

        if elapsed + interval_seconds > timeout_seconds:
            msg = (
                f"{description} did not become ready within {timeout_seconds:.0f}s "
                f"({attempts} attempt(s), last result: {detail}). "
                f"This is an environment problem, not a product defect."
            )
            raise ServiceNotReadyError(msg)

        sleep(interval_seconds)
