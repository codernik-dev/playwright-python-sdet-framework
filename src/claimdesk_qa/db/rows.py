"""Typed rows returned by the query layer.

Plain dataclasses rather than dicts, for the same reason the API layer uses
pydantic models rather than raw JSON: ``row.amount`` fails loudly when the column
is renamed, whereas ``row["amount"]`` fails with a ``KeyError`` somewhere further
down, and ``row.get("amount")`` silently returns ``None`` and turns a schema
change into a passing test.

Money is ``Decimal``. PostgreSQL ``NUMERIC`` maps to ``Decimal`` in psycopg, and
keeping it that way through the whole stack is what allows an exact-equality
assertion on a monetary value. The moment anything converts to ``float``, the
strongest assertion available becomes "close enough" - which is precisely the
defect these tests exist to catch.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class UserRow:
    id: uuid.UUID
    email: str
    full_name: str
    role: str
    password_hash: str
    is_active: bool
    created_at: datetime


@dataclass(frozen=True, slots=True)
class PolicyRow:
    id: uuid.UUID
    policy_number: str
    holder_id: uuid.UUID
    coverage_limit: Decimal
    is_active: bool


@dataclass(frozen=True, slots=True)
class ClaimRow:
    id: uuid.UUID
    reference: str
    policy_id: uuid.UUID
    claimant_id: uuid.UUID
    amount: Decimal
    description: str
    incident_date: date
    status: str
    created_at: datetime
    updated_at: datetime
    withdrawn_at: datetime | None
    decided_by_id: uuid.UUID | None


@dataclass(frozen=True, slots=True)
class ClaimEventRow:
    id: uuid.UUID
    claim_id: uuid.UUID
    actor_id: uuid.UUID
    from_status: str | None
    to_status: str
    note: str | None
    occurred_at: datetime


@dataclass(frozen=True, slots=True)
class PayoutRow:
    id: uuid.UUID
    claim_id: uuid.UUID
    amount: Decimal
    paid_by_id: uuid.UUID
    paid_at: datetime


@dataclass(frozen=True, slots=True)
class ColumnTypeRow:
    """A column's declared storage type, read from ``information_schema``.

    Used to assert the *schema* itself, not just the data in it. A column that
    holds correct values today but is declared ``double precision`` is a defect
    waiting for the row that cannot be represented exactly.
    """

    table_name: str
    column_name: str
    data_type: str
    numeric_precision: int | None
    numeric_scale: int | None


@dataclass(frozen=True, slots=True)
class ConstraintRow:
    """A constraint's name and type, read from the catalogue."""

    constraint_name: str
    constraint_type: str
    table_name: str


@dataclass(frozen=True, slots=True)
class CountRow:
    """A single labelled count, for group-by integrity queries."""

    label: str
    total: int
