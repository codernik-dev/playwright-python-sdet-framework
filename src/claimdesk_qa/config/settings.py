"""Typed, validated, environment-aware configuration for the test framework.

Why this module exists
----------------------
A test framework that reads ``os.environ["BASE_URL"]`` at the point of use fails in
the worst possible way: halfway through a run, on a CI agent, with a ``KeyError``
that says nothing about what was actually misconfigured. Worse, a typo silently
becomes ``None`` and the suite runs against the wrong environment.

This module makes configuration a first-class, validated object:

* every value is **typed** and **range-checked** at session start, not at point of use;
* a missing or malformed value fails **immediately** with an actionable message;
* secrets are :class:`~pydantic.SecretStr`, so they cannot be printed by accident;
* :meth:`Settings.masked` produces the exact block that goes into the test report,
  answering "which environment did this run actually target?" — the first question
  anyone asks about a failed CI run.

Precedence (highest wins): real environment variables > ``.env`` file > defaults.
That ordering is what lets the same code run locally from ``.env`` and in CI from
injected secrets with no branching.
"""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Any, Final
from urllib.parse import quote

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_VALID_LOG_LEVELS: Final[frozenset[str]] = frozenset(
    {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
)
_MASK: Final[str] = "***masked***"


class Environment(StrEnum):
    """Where the suite is pointed.

    The value selects sensible defaults and is recorded in every report, so a
    result can never be misattributed to the wrong environment.
    """

    LOCAL = "local"
    """Application and database on this machine; tests run on the host."""

    DOCKER = "docker"
    """Everything inside docker compose, including the test runner."""

    CI = "ci"
    """Ephemeral CI runner: headless, artefacts uploaded, no interactive niceties."""

    STAGING = "staging"
    """A real deployed URL — proves the framework is not hard-wired to Docker."""


class Settings(BaseSettings):
    """Validated runtime configuration for one test session.

    Instances are frozen: configuration is read once and cannot drift mid-run,
    which removes a whole class of "why did this test behave differently?" bugs.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        frozen=True,
    )

    # --- environment ---------------------------------------------------------
    env: Environment = Field(
        default=Environment.LOCAL,
        validation_alias="TEST_ENV",
        description="Which environment this run targets.",
    )

    # --- application under test ---------------------------------------------
    base_url: str = Field(
        default="http://localhost:8000",
        description="Browser entry point for the application under test.",
    )
    api_base_url: str | None = Field(
        default=None,
        description="REST API root. Derived from base_url when left empty.",
    )

    # --- timeouts ------------------------------------------------------------
    # Every network call has an explicit timeout. A missing timeout is how a
    # suite silently hangs a CI agent for the full job limit.
    http_timeout_seconds: float = Field(default=15.0, gt=0, le=300)
    ui_action_timeout_ms: int = Field(default=10_000, gt=0, le=300_000)
    ui_navigation_timeout_ms: int = Field(default=20_000, gt=0, le=300_000)

    # --- database validation (read-only) -------------------------------------
    db_enabled: bool = Field(
        default=False,
        description=(
            "Database validation is OPT-IN. It defaults to false so that a fresh clone "
            "loads with zero configuration, and because a capability that needs "
            "credentials should never be assumed. `.env.example` and every CI workflow "
            "turn it on explicitly. When it is off, db-marked tests SKIP with a reason "
            "instead of erroring, and the report header says so loudly so a green run "
            "can never be mistaken for one that validated the database."
        ),
    )
    db_host: str = "localhost"
    db_port: int = Field(default=5432, ge=1, le=65535)
    db_name: str = "claimdesk"
    db_user: str = "claimdesk_qa_ro"
    db_password: SecretStr = SecretStr("")
    db_connect_timeout_seconds: int = Field(default=10, gt=0, le=120)

    # --- seeded accounts -----------------------------------------------------
    seed_user_password: SecretStr = SecretStr("Passw0rd!seed")

    # --- execution / diagnostics ---------------------------------------------
    headless: bool = True
    log_level: str = "INFO"
    artifacts_dir: Path = Path("artifacts")
    faker_seed: int | None = Field(
        default=None,
        description="Fix to reproduce a data-dependent failure. Printed in every report.",
    )

    # ------------------------------------------------------------------ #
    # validators
    # ------------------------------------------------------------------ #

    @field_validator("base_url", "api_base_url")
    @classmethod
    def _normalise_url(cls, value: str | None) -> str | None:
        """Reject non-HTTP URLs early and strip the trailing slash.

        A trailing slash is the classic source of ``//api/v1`` double-slash bugs
        that only show up as a confusing 404 three layers down.
        """
        if value is None or value == "":
            return None
        if not value.startswith(("http://", "https://")):
            msg = f"URL must start with http:// or https://, got {value!r}"
            raise ValueError(msg)
        return value.rstrip("/")

    @field_validator("faker_seed", mode="before")
    @classmethod
    def _blank_means_unset(cls, value: object) -> object:
        """Treat an empty dotenv value as absent.

        ``.env`` files conventionally carry commented placeholders like
        ``FAKER_SEED=``. Without this, copying `.env.example` to `.env` would fail
        at startup with "unable to parse string as an integer" - a broken
        out-of-the-box experience, and exactly the bug a unit test caught here.
        """
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("log_level")
    @classmethod
    def _normalise_log_level(cls, value: str) -> str:
        level = value.upper().strip()
        if level not in _VALID_LOG_LEVELS:
            msg = f"LOG_LEVEL must be one of {sorted(_VALID_LOG_LEVELS)}, got {value!r}"
            raise ValueError(msg)
        return level

    @model_validator(mode="after")
    def _apply_environment_rules(self) -> Settings:
        """Cross-field rules that depend on the selected environment.

        Enforced here rather than in test code so that a misconfiguration fails at
        session start with a clear message, instead of as a mystery failure inside
        an unrelated test.
        """
        if self.db_enabled and not self.db_password.get_secret_value():
            msg = (
                "DB_ENABLED is true but DB_PASSWORD is empty. Either set DB_PASSWORD "
                "(see .env.example) or set DB_ENABLED=false to skip database tests."
            )
            raise ValueError(msg)

        # A headed browser on a CI agent waits forever for a display that will
        # never exist. Force headless rather than letting the job time out.
        if self.env is Environment.CI and not self.headless:
            object.__setattr__(self, "headless", True)

        return self

    # ------------------------------------------------------------------ #
    # derived values
    # ------------------------------------------------------------------ #

    @property
    def api_url(self) -> str:
        """REST API root, derived from :attr:`base_url` unless explicitly overridden.

        Deriving by default means a normal user sets one URL, not two that can
        disagree with each other.
        """
        return self.api_base_url or f"{self.base_url}/api/v1"

    @property
    def db_dsn(self) -> str:
        """PostgreSQL connection string. **Contains the password — never log this.**

        Use :attr:`db_dsn_safe` for anything human-visible.
        """
        password = quote(self.db_password.get_secret_value(), safe="")
        user = quote(self.db_user, safe="")
        return (
            f"postgresql://{user}:{password}@{self.db_host}:{self.db_port}/{self.db_name}"
            f"?connect_timeout={self.db_connect_timeout_seconds}"
        )

    @property
    def db_dsn_safe(self) -> str:
        """Connection string with the password masked, safe for logs and reports."""
        user = quote(self.db_user, safe="")
        return f"postgresql://{user}:{_MASK}@{self.db_host}:{self.db_port}/{self.db_name}"

    @property
    def is_ci(self) -> bool:
        return self.env is Environment.CI

    def masked(self) -> dict[str, Any]:
        """Report-safe view of the configuration.

        This is what gets attached to the Allure report and printed in the run
        header, so every result carries the environment that produced it.
        Secrets are replaced, never truncated — a truncated secret is still a leak.
        """
        return {
            "environment": self.env.value,
            "base_url": self.base_url,
            "api_url": self.api_url,
            "db_enabled": self.db_enabled,
            "database": self.db_dsn_safe if self.db_enabled else "disabled",
            "headless": self.headless,
            "http_timeout_seconds": self.http_timeout_seconds,
            "ui_action_timeout_ms": self.ui_action_timeout_ms,
            "ui_navigation_timeout_ms": self.ui_navigation_timeout_ms,
            "log_level": self.log_level,
            "faker_seed": self.faker_seed,
            "seed_user_password": _MASK,
        }


def load_settings(env_file: str | Path | None = ".env") -> Settings:
    """Build a :class:`Settings` instance.

    Args:
        env_file: Path to a dotenv file, or ``None`` to read only real environment
            variables. Tests pass ``None`` so a developer's local ``.env`` can never
            leak into — and silently change the outcome of — a unit test.
    """
    return Settings(_env_file=env_file)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide cached settings.

    Cached because configuration is read once per session; the cache also
    guarantees every fixture sees the identical object rather than re-reading
    ``.env`` at different moments.
    """
    return load_settings()
