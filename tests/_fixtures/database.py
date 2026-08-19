"""Read-only database access and the query objects built on it."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from claimdesk_qa.config import Settings
from claimdesk_qa.db import (
    ClaimEventQueries,
    ClaimQueries,
    Database,
    IntegrityQueries,
    PayoutQueries,
    PolicyQueries,
    UserQueries,
)


@pytest.fixture
def database(settings: Settings) -> Iterator[Database]:
    """A read-only connection, opened per test.

    Per test rather than pooled, on purpose. A long-lived connection can hold a
    transaction snapshot that hides another test's committed writes - which would
    surface as an assertion failing against data that is demonstrably present.
    """
    with Database(dsn=settings.db_dsn, dsn_safe=settings.db_dsn_safe) as db:
        yield db


@pytest.fixture
def claims_db(database: Database) -> ClaimQueries:
    return ClaimQueries(database)


@pytest.fixture
def events_db(database: Database) -> ClaimEventQueries:
    return ClaimEventQueries(database)


@pytest.fixture
def payouts_db(database: Database) -> PayoutQueries:
    return PayoutQueries(database)


@pytest.fixture
def users_db(database: Database) -> UserQueries:
    return UserQueries(database)


@pytest.fixture
def policies_db(database: Database) -> PolicyQueries:
    return PolicyQueries(database)


@pytest.fixture
def integrity_db(database: Database) -> IntegrityQueries:
    return IntegrityQueries(database)
