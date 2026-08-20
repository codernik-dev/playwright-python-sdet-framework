"""Read-only access to the application's database.

Why a dedicated layer instead of `psycopg.connect` in each test
---------------------------------------------------------------
Three things must be true of every query this framework runs, and none of them
survive being left to the author of each individual test:

1. **It must be read-only.** The database role holds ``SELECT`` and nothing else
   (ADR 0003), and this layer sets ``read_only`` on the connection as well. Two
   independent controls, because the dangerous version of database testing is a
   suite that quietly writes rows to reach a state faster - and then asserts
   against data the application could never have produced.
2. **It must be parameterised.** Never string interpolation. Not only because of
   injection - that is a real risk even in test code that runs against a shared
   environment - but because interpolation silently mangles types. A ``Decimal``
   formatted into SQL becomes a float literal, and the test that was supposed to
   prove money is exact starts comparing rounded values.
3. **It must be recordable.** When an assertion about database state fails, the
   question is always "what did the query actually return?". Every statement and
   its result are kept so the failure hook can attach them.

Connections are opened per test rather than pooled. A pool would be faster, and it
would also let one test's open transaction hold a snapshot that hides another
test's committed writes - which is exactly the confusion this layer exists to
avoid.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from types import TracebackType
from typing import Any, Self, TypeVar

import psycopg
from psycopg.rows import class_row, dict_row

from claimdesk_qa.core.exceptions import FrameworkError
from claimdesk_qa.core.logging import get_logger
from claimdesk_qa.core.recording import record_sql

logger = get_logger(__name__)

RowT = TypeVar("RowT")

#: Enough to explain a failure without attaching an essay to the report.
MAX_RECORDED_QUERIES = 25


class DatabaseError(FrameworkError):
    """The database could not be reached or the query could not run.

    A ``FrameworkError``, not an ``AssertionError``: an unreachable database is an
    environment problem. Reporting it as a product defect sends people hunting for
    a bug that does not exist.
    """


@dataclass(frozen=True, slots=True)
class ExecutedQuery:
    """One statement and what it returned, kept for failure diagnosis."""

    sql: str
    params: tuple[Any, ...] | None
    row_count: int

    def render(self) -> str:
        compact = " ".join(self.sql.split())
        lines = [f"SQL: {compact}"]
        if self.params:
            lines.append(f"  params: {self.params!r}")
        lines.append(f"  rows: {self.row_count}")
        return "\n".join(lines)


@dataclass
class Database:
    """A read-only connection to the application's database."""

    dsn: str
    dsn_safe: str
    _connection: psycopg.Connection[Any] | None = field(default=None, init=False, repr=False)
    _queries: deque[ExecutedQuery] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._queries = deque(maxlen=MAX_RECORDED_QUERIES)

    # ------------------------------------------------------------------ #
    # lifecycle
    # ------------------------------------------------------------------ #

    def connect(self) -> Self:
        try:
            connection = psycopg.connect(self.dsn, autocommit=True)
        except psycopg.Error as exc:
            msg = (
                f"Could not connect to the database at {self.dsn_safe}: {exc}\n"
                "This is an environment problem, not a product defect. Check that the "
                "database is running and that DB_* settings are correct, or set "
                "DB_ENABLED=false to skip database tests."
            )
            raise DatabaseError(msg) from exc

        # Belt and braces on top of the role's grants: even a bug in this layer
        # cannot issue a write, because the server refuses it for the session.
        connection.read_only = True
        self._connection = connection
        logger.debug("Connected read-only to %s", self.dsn_safe)
        return self

    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def __enter__(self) -> Self:
        return self.connect()

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    @property
    def connection(self) -> psycopg.Connection[Any]:
        if self._connection is None:
            msg = "Database.connect() was never called"
            raise DatabaseError(msg)
        return self._connection

    # ------------------------------------------------------------------ #
    # querying
    # ------------------------------------------------------------------ #

    @property
    def executed_queries(self) -> list[ExecutedQuery]:
        return list(self._queries)

    def render_queries(self) -> str:
        """The recorded statements, for attaching to a failing test's report."""
        if not self._queries:
            return "(no SQL executed)"
        return "\n\n".join(query.render() for query in self._queries)

    @contextmanager
    def _cursor(self, row_factory: Any) -> Iterator[psycopg.Cursor[Any]]:
        try:
            with self.connection.cursor(row_factory=row_factory) as cursor:
                yield cursor
        except psycopg.errors.InsufficientPrivilege as exc:
            msg = (
                f"The QA database role is not permitted to run that statement: {exc}\n"
                "The role holds SELECT only, by design. If a test needs to change "
                "state, it must do so through the application. See ADR 0003."
            )
            raise DatabaseError(msg) from exc
        except psycopg.Error as exc:
            msg = f"Query failed against {self.dsn_safe}: {exc}"
            raise DatabaseError(msg) from exc

    def _record(self, sql: str, params: Sequence[Any] | None, row_count: int) -> None:
        query = ExecutedQuery(
            sql=sql,
            params=tuple(params) if params else None,
            row_count=row_count,
        )
        self._queries.append(query)
        # Into the current test's recorder as well, so the report can answer the
        # question a database assertion always raises: what did the query return?
        record_sql(query)
        logger.debug("%s", query.render())

    def fetch_all(
        self, sql: str, params: Sequence[Any] | None = None, *, model: type[RowT]
    ) -> list[RowT]:
        """Run a query and map every row onto ``model``."""
        with self._cursor(class_row(model)) as cursor:
            cursor.execute(sql, params)
            rows: list[RowT] = cursor.fetchall()
        self._record(sql, params, len(rows))
        return rows

    def fetch_one(
        self, sql: str, params: Sequence[Any] | None = None, *, model: type[RowT]
    ) -> RowT | None:
        """Run a query expected to match at most one row.

        Returns ``None`` when nothing matched, rather than raising. "The row is
        absent" is a legitimate and frequently asserted outcome - a deleted claim,
        a payout that should not exist - and forcing every caller to catch an
        exception for the normal case makes those tests unreadable.
        """
        rows = self.fetch_all(sql, params, model=model)
        if len(rows) > 1:
            msg = f"Expected at most one row but got {len(rows)} from: {' '.join(sql.split())}"
            raise DatabaseError(msg)
        return rows[0] if rows else None

    def scalar(self, sql: str, params: Sequence[Any] | None = None) -> Any:
        """Run a query returning a single value, such as a ``count(*)``."""
        with self._cursor(dict_row) as cursor:
            cursor.execute(sql, params)
            row = cursor.fetchone()
        self._record(sql, params, 1 if row else 0)
        if row is None:
            return None
        return next(iter(row.values()))
