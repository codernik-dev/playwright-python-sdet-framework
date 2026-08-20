"""Query objects: the database layer's equivalent of a page object.

A test says what it wants to know:

```python
events = claim_events.for_claim(claim.id)
```

not how to find out:

```python
cursor.execute("SELECT ... FROM claim_events WHERE claim_id = %s ORDER BY ...")
```

The payoff is the same as for page objects. SQL lives in one place, so a column
rename is one edit rather than forty. Tests stay readable, so a reviewer can see
what is being asserted without parsing SQL. And every statement is parameterised
by construction, because there is no path through this module that concatenates a
value into a string.

Every query here is a ``SELECT``. There is no write method, and there could not be
a working one: the role holds ``SELECT`` only and the connection is read-only.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from claimdesk_qa.db.connection import Database
from claimdesk_qa.db.rows import (
    ClaimEventRow,
    ClaimRow,
    ColumnTypeRow,
    ConstraintRow,
    CountRow,
    PayoutRow,
    PolicyRow,
    UserRow,
)

_CLAIM_COLUMNS = """
    id, reference, policy_id, claimant_id, amount, description, incident_date,
    status, created_at, updated_at, withdrawn_at, decided_by_id
"""


class ClaimQueries:
    def __init__(self, database: Database) -> None:
        self._db = database

    def by_id(self, claim_id: uuid.UUID | str) -> ClaimRow | None:
        return self._db.fetch_one(
            f"SELECT {_CLAIM_COLUMNS} FROM claims WHERE id = %s",
            (str(claim_id),),
            model=ClaimRow,
        )

    def by_reference(self, reference: str) -> ClaimRow | None:
        return self._db.fetch_one(
            f"SELECT {_CLAIM_COLUMNS} FROM claims WHERE reference = %s",
            (reference,),
            model=ClaimRow,
        )

    def exists(self, claim_id: uuid.UUID | str) -> bool:
        """Whether the row is physically present, regardless of its status.

        The distinction matters for withdrawal: the API stops offering the claim,
        but the row must survive. Only the database can tell those two apart.
        """
        return bool(self._db.scalar("SELECT count(*) FROM claims WHERE id = %s", (str(claim_id),)))

    def count_with_status(self, status: str) -> int:
        return int(self._db.scalar("SELECT count(*) FROM claims WHERE status = %s", (status,)) or 0)

    def count_with_description_containing(self, marker: str) -> int:
        """How many claims carry a marker in their description.

        The parallel-safe way to ask "did my write land?". A global
        ``count(*) WHERE status = 'DRAFT'`` answers a question about the whole
        database, which other workers are changing at the same moment; this
        answers a question about *this test's* data.

        ``%`` wildcards are supplied as part of the parameter value, never
        concatenated into the statement.
        """
        return int(
            self._db.scalar(
                "SELECT count(*) FROM claims WHERE description LIKE %s",
                (f"%{marker}%",),
            )
            or 0
        )

    def for_claimant(self, claimant_id: uuid.UUID | str) -> list[ClaimRow]:
        return self._db.fetch_all(
            f"SELECT {_CLAIM_COLUMNS} FROM claims WHERE claimant_id = %s ORDER BY created_at",
            (str(claimant_id),),
            model=ClaimRow,
        )


class ClaimEventQueries:
    def __init__(self, database: Database) -> None:
        self._db = database

    def for_claim(self, claim_id: uuid.UUID | str) -> list[ClaimEventRow]:
        """The audit trail in the order it happened.

        Ordered by ``occurred_at`` then ``id``: two events written inside the same
        transaction can share a timestamp, and without a tiebreaker the returned
        order would be arbitrary - making a chain assertion flaky for reasons that
        have nothing to do with the application.
        """
        return self._db.fetch_all(
            """
            SELECT id, claim_id, actor_id, from_status, to_status, note, occurred_at
            FROM claim_events
            WHERE claim_id = %s
            ORDER BY occurred_at, id
            """,
            (str(claim_id),),
            model=ClaimEventRow,
        )

    def count_for_claim(self, claim_id: uuid.UUID | str) -> int:
        return int(
            self._db.scalar(
                "SELECT count(*) FROM claim_events WHERE claim_id = %s", (str(claim_id),)
            )
            or 0
        )

    def statuses_for_claim(self, claim_id: uuid.UUID | str) -> list[str]:
        return [event.to_status for event in self.for_claim(claim_id)]


class PayoutQueries:
    def __init__(self, database: Database) -> None:
        self._db = database

    def for_claim(self, claim_id: uuid.UUID | str) -> PayoutRow | None:
        return self._db.fetch_one(
            """
            SELECT id, claim_id, amount, paid_by_id, paid_at
            FROM payouts
            WHERE claim_id = %s
            """,
            (str(claim_id),),
            model=PayoutRow,
        )

    def count_for_claim(self, claim_id: uuid.UUID | str) -> int:
        """How many payouts exist for a claim.

        Asserting this is ``1`` rather than merely "a payout exists" is the whole
        point: a duplicate payout means money left the business twice, and a
        presence check cannot see the difference.
        """
        return int(
            self._db.scalar("SELECT count(*) FROM payouts WHERE claim_id = %s", (str(claim_id),))
            or 0
        )

    def total_paid_for_claim(self, claim_id: uuid.UUID | str) -> Decimal:
        return Decimal(
            self._db.scalar(
                "SELECT coalesce(sum(amount), 0) FROM payouts WHERE claim_id = %s",
                (str(claim_id),),
            )
        )


class UserQueries:
    def __init__(self, database: Database) -> None:
        self._db = database

    def by_email(self, email: str) -> UserRow | None:
        return self._db.fetch_one(
            """
            SELECT id, email, full_name, role, password_hash, is_active, created_at
            FROM users WHERE email = %s
            """,
            (email,),
            model=UserRow,
        )


class PolicyQueries:
    def __init__(self, database: Database) -> None:
        self._db = database

    def by_number(self, policy_number: str) -> PolicyRow | None:
        return self._db.fetch_one(
            """
            SELECT id, policy_number, holder_id, coverage_limit, is_active
            FROM policies WHERE policy_number = %s
            """,
            (policy_number,),
            model=PolicyRow,
        )


class IntegrityQueries:
    """Whole-database invariants, and assertions about the schema itself.

    These are the checks that cannot be made from any other layer. The API can
    tell you a response looked right; only the database can tell you nothing was
    orphaned, no claim was paid twice, and money is stored in a type that can
    represent it exactly.
    """

    def __init__(self, database: Database) -> None:
        self._db = database

    def orphaned_event_count(self) -> int:
        """Audit rows pointing at a claim that no longer exists.

        A foreign key should make this impossible. The test asserts it anyway,
        because "there is a constraint" and "the constraint is enabled and valid"
        are different statements - and a migration that dropped it would otherwise
        go unnoticed until the data was already wrong.
        """
        return int(
            self._db.scalar(
                """
                SELECT count(*)
                FROM claim_events e
                LEFT JOIN claims c ON c.id = e.claim_id
                WHERE c.id IS NULL
                """
            )
            or 0
        )

    def orphaned_payout_count(self) -> int:
        return int(
            self._db.scalar(
                """
                SELECT count(*)
                FROM payouts p
                LEFT JOIN claims c ON c.id = p.claim_id
                WHERE c.id IS NULL
                """
            )
            or 0
        )

    def claims_paid_more_than_once(self) -> list[CountRow]:
        """Any claim with more than one payout. Must always be empty."""
        return self._db.fetch_all(
            """
            SELECT c.reference AS label, count(p.id) AS total
            FROM claims c
            JOIN payouts p ON p.claim_id = c.id
            GROUP BY c.reference
            HAVING count(p.id) > 1
            """,
            model=CountRow,
        )

    def paid_claims_without_a_payout(self) -> list[CountRow]:
        """Claims marked PAID with no payout row - money owed and never recorded."""
        return self._db.fetch_all(
            """
            SELECT c.reference AS label, 0 AS total
            FROM claims c
            LEFT JOIN payouts p ON p.claim_id = c.id
            WHERE c.status = 'PAID' AND p.id IS NULL
            """,
            model=CountRow,
        )

    def payouts_disagreeing_with_their_claim(self) -> list[CountRow]:
        """Payouts whose amount differs from the approved claim amount."""
        return self._db.fetch_all(
            """
            SELECT c.reference AS label, 1 AS total
            FROM payouts p
            JOIN claims c ON c.id = p.claim_id
            WHERE p.amount <> c.amount
            """,
            model=CountRow,
        )

    def claims_with_no_audit_trail(self) -> list[CountRow]:
        """Every claim must have at least the row recording its creation."""
        return self._db.fetch_all(
            """
            SELECT c.reference AS label, 0 AS total
            FROM claims c
            LEFT JOIN claim_events e ON e.claim_id = c.id
            WHERE e.id IS NULL
            """,
            model=CountRow,
        )

    def money_column_types(self) -> list[ColumnTypeRow]:
        """Declared storage types for every monetary column.

        Asserted against the schema rather than the data. A column holding correct
        values today but declared ``double precision`` is a defect waiting for the
        first value that cannot be represented exactly - and no amount of testing
        the *rows* will find it.
        """
        return self._db.fetch_all(
            """
            SELECT table_name, column_name, data_type, numeric_precision, numeric_scale
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND column_name IN ('amount', 'coverage_limit')
            ORDER BY table_name, column_name
            """,
            model=ColumnTypeRow,
        )

    def constraints_on(self, table_name: str) -> list[ConstraintRow]:
        """Constraints on a table, read from ``pg_catalog`` rather than ``information_schema``.

        This is not a style preference. ``information_schema.table_constraints``
        is **privilege-filtered**: PostgreSQL documents it as showing constraints
        on tables the current user owns or has *some privilege other than SELECT*
        on. Our QA role holds SELECT and nothing else, so it sees **zero**
        constraints there, while the owning role sees all sixteen.

        Measured on this database:

            read-only role, information_schema.table_constraints  ->  0
            read-only role, pg_catalog.pg_constraint              -> 16
            owning role,    information_schema.table_constraints  -> 16

        The trap is that the test would have passed against a superuser or the
        application's own role, and only failed once least privilege was applied
        properly. ``pg_catalog`` is not filtered this way.

        Note that ``information_schema.columns`` *is* visible to a SELECT-only
        role, which is why the money-type query can still use it.
        """
        return self._db.fetch_all(
            """
            SELECT
                con.conname AS constraint_name,
                CASE con.contype
                    WHEN 'p' THEN 'PRIMARY KEY'
                    WHEN 'u' THEN 'UNIQUE'
                    WHEN 'f' THEN 'FOREIGN KEY'
                    WHEN 'c' THEN 'CHECK'
                    ELSE con.contype::text
                END AS constraint_type,
                rel.relname AS table_name
            FROM pg_catalog.pg_constraint con
            JOIN pg_catalog.pg_class rel ON rel.oid = con.conrelid
            JOIN pg_catalog.pg_namespace nsp ON nsp.oid = rel.relnamespace
            WHERE nsp.nspname = 'public' AND rel.relname = %s
            ORDER BY 2, 1
            """,
            (table_name,),
            model=ConstraintRow,
        )

    def plaintext_password_count(self, password: str) -> int:
        """How many stored hashes equal the plaintext password.

        Must be zero. This is the check that catches hashing being disabled,
        misconfigured, or quietly replaced with a no-op - and it costs one query.
        """
        return int(
            self._db.scalar("SELECT count(*) FROM users WHERE password_hash = %s", (password,)) or 0
        )
