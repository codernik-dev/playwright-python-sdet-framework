"""Guard for the db suite.

All shared fixtures live in `tests/_fixtures/` and are registered as plugins from
the root conftest. What remains here is the one thing specific to this layer: it
needs a running application, and the framework's own unit tests must not.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _require_application(app_ready: float) -> None:
    """Requested once, in one place, so a dead environment fails clearly."""
