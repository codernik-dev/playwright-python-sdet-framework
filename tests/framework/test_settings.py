"""Unit tests for the configuration layer.

"Who tests the tests?" - this file. The framework is shared code that every other
test depends on; a silent bug here (a URL built wrong, a secret leaked into a
report, a value read from the wrong variable) corrupts every result in the suite.

These tests need no application, no database and no browser: they run in
milliseconds and form the base of the pyramid described in
``docs/phase-1-design.md`` §8.1.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from claimdesk_qa.config import Environment, Settings, get_settings, load_settings

pytestmark = [pytest.mark.framework, pytest.mark.smoke]


# --------------------------------------------------------------------------- #
# defaults and overrides
# --------------------------------------------------------------------------- #


def test_defaults_are_usable_without_any_environment_variables() -> None:
    settings = load_settings(env_file=None)

    assert settings.env is Environment.LOCAL
    assert settings.base_url == "http://localhost:8000"
    assert settings.headless is True
    assert settings.log_level == "INFO"
    assert settings.artifacts_dir == Path("artifacts")
    assert settings.faker_seed is None
    # Database validation is opt-in: a fresh clone must load with no configuration.
    assert settings.db_enabled is False


def test_environment_is_read_from_the_test_env_alias(monkeypatch: pytest.MonkeyPatch) -> None:
    """The variable is TEST_ENV, not ENV - ENV is far too generic to claim."""
    monkeypatch.setenv("TEST_ENV", "staging")

    assert load_settings(env_file=None).env is Environment.STAGING


def test_unknown_environment_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEST_ENV", "production-ish")

    with pytest.raises(ValidationError):
        load_settings(env_file=None)


def test_environment_variables_override_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BASE_URL", "https://claims.example.test")
    monkeypatch.setenv("HTTP_TIMEOUT_SECONDS", "42")
    monkeypatch.setenv("HEADLESS", "false")

    settings = load_settings(env_file=None)

    assert settings.base_url == "https://claims.example.test"
    assert settings.http_timeout_seconds == 42.0
    assert settings.headless is False


def test_dotenv_file_is_read_when_provided(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("BASE_URL=http://from-dotenv:9000\nDB_ENABLED=false\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    settings = load_settings(env_file=env_file)

    assert settings.base_url == "http://from-dotenv:9000"
    assert settings.db_enabled is False


def test_real_environment_beats_the_dotenv_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CI injects real variables; they must win over a file left on disk."""
    env_file = tmp_path / ".env"
    env_file.write_text("BASE_URL=http://from-dotenv:9000\nDB_ENABLED=false\n", encoding="utf-8")
    monkeypatch.setenv("BASE_URL", "http://from-real-env:8080")

    settings = load_settings(env_file=env_file)

    assert settings.base_url == "http://from-real-env:8080"


# --------------------------------------------------------------------------- #
# URL handling
# --------------------------------------------------------------------------- #


def test_trailing_slash_is_stripped_from_urls(monkeypatch: pytest.MonkeyPatch) -> None:
    """Prevents the classic ``//api/v1`` double-slash 404 that looks like a real bug."""
    monkeypatch.setenv("BASE_URL", "http://localhost:8000/")

    assert load_settings(env_file=None).base_url == "http://localhost:8000"


@pytest.mark.negative
@pytest.mark.parametrize("bad_url", ["localhost:8000", "ftp://localhost", "://nope", "  "])
def test_non_http_urls_are_rejected(monkeypatch: pytest.MonkeyPatch, bad_url: str) -> None:
    monkeypatch.setenv("BASE_URL", bad_url)

    with pytest.raises(ValidationError, match="http"):
        load_settings(env_file=None)


def test_api_url_is_derived_from_base_url() -> None:
    """One URL to configure, so two values can never disagree."""
    assert load_settings(env_file=None).api_url == "http://localhost:8000/api/v1"


def test_api_url_can_be_overridden_independently(monkeypatch: pytest.MonkeyPatch) -> None:
    """Needed when the API is served from a different host than the UI."""
    monkeypatch.setenv("API_BASE_URL", "https://api.claims.example.test/v2/")

    assert load_settings(env_file=None).api_url == "https://api.claims.example.test/v2"


# --------------------------------------------------------------------------- #
# validation of ranges and enumerations
# --------------------------------------------------------------------------- #


@pytest.mark.negative
@pytest.mark.parametrize(
    ("variable", "value"),
    [
        ("DB_PORT", "0"),
        ("DB_PORT", "70000"),
        ("HTTP_TIMEOUT_SECONDS", "0"),
        ("HTTP_TIMEOUT_SECONDS", "-1"),
        ("UI_ACTION_TIMEOUT_MS", "0"),
        ("LOG_LEVEL", "chatty"),
    ],
)
def test_out_of_range_values_fail_fast(
    monkeypatch: pytest.MonkeyPatch, variable: str, value: str
) -> None:
    """Fail at session start with a clear message, not mid-run as a mystery."""
    monkeypatch.setenv(variable, value)

    with pytest.raises(ValidationError):
        load_settings(env_file=None)


def test_log_level_is_normalised_to_upper_case(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOG_LEVEL", "debug")

    assert load_settings(env_file=None).log_level == "DEBUG"


# --------------------------------------------------------------------------- #
# database configuration
# --------------------------------------------------------------------------- #


@pytest.mark.negative
def test_enabling_the_database_without_a_password_is_an_actionable_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DB_ENABLED", "true")
    monkeypatch.setenv("DB_PASSWORD", "")

    with pytest.raises(ValidationError, match="DB_ENABLED=false"):
        load_settings(env_file=None)


def test_database_may_be_disabled_entirely(monkeypatch: pytest.MonkeyPatch) -> None:
    """Real environments exist where an SDET has no database access at all.

    The suite must still be runnable there - db-marked tests skip with a reason.
    """
    monkeypatch.setenv("DB_ENABLED", "false")
    monkeypatch.setenv("DB_PASSWORD", "")

    settings = load_settings(env_file=None)

    assert settings.db_enabled is False
    assert settings.masked()["database"] == "disabled"


def test_dsn_is_built_correctly_and_url_encodes_the_password(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A password containing @ or / would otherwise corrupt the connection URL."""
    monkeypatch.setenv("DB_PASSWORD", "p@ss/word:1")
    monkeypatch.setenv("DB_HOST", "db")
    monkeypatch.setenv("DB_NAME", "claimdesk")
    monkeypatch.setenv("DB_USER", "claimdesk_qa_ro")

    dsn = load_settings(env_file=None).db_dsn

    assert dsn.startswith("postgresql://claimdesk_qa_ro:p%40ss%2Fword%3A1@db:5432/claimdesk")
    assert "connect_timeout=10" in dsn


# --------------------------------------------------------------------------- #
# secret handling - a leak here would put credentials in a public CI log
# --------------------------------------------------------------------------- #


def test_masked_report_block_contains_no_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DB_PASSWORD", "super-secret-value")
    monkeypatch.setenv("SEED_USER_PASSWORD", "another-secret-value")

    rendered = repr(load_settings(env_file=None).masked())

    assert "super-secret-value" not in rendered
    assert "another-secret-value" not in rendered
    assert "***masked***" in rendered


def test_repr_of_settings_does_not_leak_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    """pytest prints locals on failure (--showlocals); a plain str would leak."""
    monkeypatch.setenv("DB_PASSWORD", "super-secret-value")

    assert "super-secret-value" not in repr(load_settings(env_file=None))


def test_safe_dsn_masks_the_password(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DB_PASSWORD", "super-secret-value")

    safe = load_settings(env_file=None).db_dsn_safe

    assert "super-secret-value" not in safe
    assert "***masked***" in safe


# --------------------------------------------------------------------------- #
# environment-specific rules and immutability
# --------------------------------------------------------------------------- #


def test_ci_forces_headless_even_if_asked_otherwise(monkeypatch: pytest.MonkeyPatch) -> None:
    """A headed browser on a CI agent waits forever for a display that never exists."""
    monkeypatch.setenv("TEST_ENV", "ci")
    monkeypatch.setenv("HEADLESS", "false")

    settings = load_settings(env_file=None)

    assert settings.is_ci is True
    assert settings.headless is True


def test_settings_are_immutable() -> None:
    """Configuration cannot drift mid-run, so a result always matches its report."""
    settings = load_settings(env_file=None)

    with pytest.raises(ValidationError):
        settings.base_url = "http://somewhere-else"  # type: ignore[misc]


def test_get_settings_is_cached() -> None:
    """Every fixture must see the same object, not a fresh read of the environment."""
    get_settings.cache_clear()
    try:
        assert get_settings() is get_settings()
    finally:
        get_settings.cache_clear()


def test_masked_block_answers_which_environment_this_run_targeted() -> None:
    """This dict is attached to every report; these keys are what people look for."""
    block = load_settings(env_file=None).masked()

    assert {"environment", "base_url", "api_url", "database", "headless"} <= block.keys()


def test_the_shipped_env_example_actually_loads() -> None:
    """The file we tell people to copy must produce a valid configuration.

    Added after `.env.example` shipped `FAKER_SEED=` with an empty value, which
    failed integer parsing - so the documented first step, `cp .env.example .env`,
    produced a framework that could not start.
    """
    example = Path(__file__).resolve().parents[2] / ".env.example"

    settings = load_settings(env_file=example)

    assert settings.base_url.startswith("http")
    assert settings.faker_seed is None


def test_settings_can_be_constructed_directly_for_tests() -> None:
    """Fixtures build purpose-made Settings objects without touching the environment."""
    settings = Settings(base_url="http://direct:1234", db_enabled=False)

    assert settings.api_url == "http://direct:1234/api/v1"
