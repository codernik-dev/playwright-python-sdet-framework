"""Fixtures for the framework's own unit tests.

These tests must be hermetic: they exercise framework code only and must never
depend on a running application, a database, or the developer's local ``.env``.
"""

from __future__ import annotations

from pathlib import Path

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
def isolated_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Isolate these tests from BOTH sources of configuration.

    Clearing the environment variables is only half the job: ``Settings`` also
    reads a ``.env`` file from the working directory. Running the suite from the
    repository root, where a developer's real ``.env`` lives, would otherwise feed
    real values into unit tests — which is precisely how a suite starts passing or
    failing depending on whose machine it runs on.

    Autouse, because a rule that has to be remembered will eventually be forgotten.
    """
    for name in _SETTINGS_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)
