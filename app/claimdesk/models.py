"""SQLAlchemy models - the single source of truth for the ClaimDesk schema.

Design notes that the database tests depend on:

* Money is ``NUMERIC(12, 2)``. Never a float. A float would drift and the
  ``DB-CLM-005`` integrity test exists to prove it does not.
* ``payouts.claim_id`` is **unique**, so a double payout is impossible at the
  storage layer rather than only in application code.
* ``claim_events`` is an append-only audit trail. Every status change writes
  exactly one row, which is what makes the audit assertions meaningful.
* Statuses and roles are constrained with ``CHECK`` rather than PostgreSQL enums,
  so adding a value later does not require a migration dance.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from claimdesk.db import Base
from claimdesk.domain import ClaimStatus, Role

_ROLE_VALUES = ", ".join(f"'{r.value}'" for r in Role)
_STATUS_VALUES = ", ".join(f"'{s.value}'" for s in ClaimStatus)


def _uuid_column() -> Mapped[uuid.UUID]:
    return mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


class User(Base):
    __tablename__ = "users"
    __table_args__ = (CheckConstraint(f"role IN ({_ROLE_VALUES})", name="ck_users_role"),)

    id: Mapped[uuid.UUID] = _uuid_column()
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String(120), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    policies: Mapped[list[Policy]] = relationship(back_populates="holder")


class Policy(Base):
    __tablename__ = "policies"
    __table_args__ = (CheckConstraint("coverage_limit > 0", name="ck_policies_coverage_positive"),)

    id: Mapped[uuid.UUID] = _uuid_column()
    policy_number: Mapped[str] = mapped_column(String(32), unique=True, index=True, nullable=False)
    holder_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    coverage_limit: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    holder: Mapped[User] = relationship(back_populates="policies")


class Claim(Base):
    __tablename__ = "claims"
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_claims_amount_positive"),
        CheckConstraint(f"status IN ({_STATUS_VALUES})", name="ck_claims_status"),
    )

    id: Mapped[uuid.UUID] = _uuid_column()
    reference: Mapped[str] = mapped_column(String(32), unique=True, index=True, nullable=False)
    policy_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("policies.id", ondelete="RESTRICT"), nullable=False
    )
    claimant_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    incident_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    #: Set instead of deleting the row: withdrawal is a soft delete, and the
    #: DB-CLM-004 test proves the row survives.
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decided_by_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    policy: Mapped[Policy] = relationship()
    claimant: Mapped[User] = relationship(foreign_keys=[claimant_id])
    events: Mapped[list[ClaimEvent]] = relationship(
        back_populates="claim", order_by="ClaimEvent.occurred_at"
    )


class ClaimEvent(Base):
    """Append-only audit trail. One row per status change, no updates, no deletes."""

    __tablename__ = "claim_events"

    id: Mapped[uuid.UUID] = _uuid_column()
    claim_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("claims.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    actor_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    from_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    to_status: Mapped[str] = mapped_column(String(20), nullable=False)
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    claim: Mapped[Claim] = relationship(back_populates="events")


class Payout(Base):
    """One payout per claim, enforced by a unique constraint on ``claim_id``.

    The constraint is the point: a double payout is the classic financial defect,
    and the storage layer refuses it rather than trusting application code to.
    """

    __tablename__ = "payouts"
    __table_args__ = (CheckConstraint("amount > 0", name="ck_payouts_amount_positive"),)

    id: Mapped[uuid.UUID] = _uuid_column()
    claim_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("claims.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    paid_by_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    paid_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    claim: Mapped[Claim] = relationship()
