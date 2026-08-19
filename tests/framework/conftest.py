"""Fixtures for the framework's own unit tests.

These tests must be hermetic: they exercise framework code only and must never
depend on a running application, a database, or the developer's local ``.env``.
"""

from __future__ import annotations

import pytest

# Every environment variable the Settings model reads. Cleared before each test so
# that a value in the developer's real environment cannot change a unit-test result.
_SETTINGS_ENV_VARS = (
    "TEST_ENV",
    "BASE_URL",
    "API_BASE_URL",
    "HTTP_TIMEOUT_SECONDS",
    "UI_ACTION_TIMEOUT_MS",
    "UI_NAVIGATION_TIMEOUT_MS",
    "DB_ENABLED",
    "DB_HOST",
    "DB_PORT",
    "DB_NAME",
    "DB_USER",
    "DB_PASSWORD",
    "DB_CONNECT_TIMEOUT_SECONDS",
    "SEED_USER_PASSWORD",
    "HEADLESS",
    "LOG_LEVEL",
    "ARTIFACTS_DIR",
    "FAKER_SEED",
)


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove all framework configuration variables from the environment.

    Autouse, because forgetting it in a single test would make that test pass or
    fail depending on whose machine it runs on — the exact class of flakiness this
    framework is meant to demonstrate how to avoid.
    """
    for name in _SETTINGS_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
