"""Claim operations shared by the REST API and the HTML interface.

Both entry points call the same functions, so the browser and the API cannot drift
apart. That matters for the framework: an end-to-end test that submits a claim in
the UI and approves it through the API is only meaningful if both paths enforce the
identical rules.
"""

from __future__ import annotations

import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from claimdesk.domain import (
    EDITABLE_STATUSES,
    ClaimAction,
    ClaimStatus,
    DomainError,
    Role,
    can_view_claim,
    resolve_transition,
    validate_claim_amount,
)
from claimdesk.models import Claim, ClaimEvent, Payout, Policy, User

MAX_PAGE_SIZE = 100

SORTABLE_FIELDS = frozenset({"created_at", "amount", "incident_date", "reference"})


def generate_reference() -> str:
    """Human-readable, collision-resistant claim reference.

    Random rather than sequential so that parallel test workers never contend for
    the same value, and so no test can accidentally depend on ordering.
    """
    return f"CLM-{secrets.token_hex(4).upper()}"


def as_domain_error(exc: DomainError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.message)


@dataclass(frozen=True, slots=True)
class ClaimFilters:
    """Query parameters for the claim list, already validated by FastAPI."""

    status: ClaimStatus | None = None
    min_amount: Decimal | None = None
    max_amount: Decimal | None = None
    date_from: date | None = None
    date_to: date | None = None
    q: str | None = None
    sort: str = "-created_at"
    page: int = 1
    size: int = 20


def _record_event(
    session: Session,
    *,
    claim: Claim,
    actor: User,
    from_status: ClaimStatus | None,
    to_status: ClaimStatus,
    note: str | None = None,
) -> None:
    """Append one audit row. Never updated, never deleted."""
    session.add(
        ClaimEvent(
            claim_id=claim.id,
            actor_id=actor.id,
            from_status=from_status.value if from_status else None,
            to_status=to_status.value,
            note=note,
        )
    )


def create_claim(
    session: Session,
    *,
    actor: User,
    policy_id: uuid.UUID,
    amount: Decimal,
    description: str,
    incident_date: date,
) -> Claim:
    policy = session.get(Policy, policy_id)
    if policy is None or not policy.is_active:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Policy not found")

    # A customer may only claim against a policy they hold. Staff may file on
    # behalf of a holder, which is why this is not a blanket ownership check.
    if actor.role == Role.CUSTOMER.value and policy.holder_id != actor.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Policy not found")

    try:
        validate_claim_amount(amount, policy.coverage_limit)
    except DomainError as exc:
        raise as_domain_error(exc) from exc

    claim = Claim(
        reference=generate_reference(),
        policy_id=policy.id,
        claimant_id=policy.holder_id,
        amount=amount,
        description=description,
        incident_date=incident_date,
        status=ClaimStatus.DRAFT.value,
    )
    session.add(claim)
    session.flush()
    _record_event(session, claim=claim, actor=actor, from_status=None, to_status=ClaimStatus.DRAFT)
    session.commit()
    session.refresh(claim)
    return claim


def get_visible_claim(session: Session, *, actor: User, claim_id: uuid.UUID) -> Claim:
    """Fetch a claim the caller is allowed to see.

    A claim belonging to somebody else returns **404, not 403**. Returning 403
    would confirm the resource exists, letting an attacker enumerate identifiers.
    """
    claim = session.get(Claim, claim_id)
    if claim is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Claim not found")

    if not can_view_claim(actor_role=Role(actor.role), is_owner=claim.claimant_id == actor.id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Claim not found")
    return claim


def _visible_claims_query(actor: User) -> Select[tuple[Claim]]:
    query = select(Claim)
    if actor.role == Role.CUSTOMER.value:
        query = query.where(Claim.claimant_id == actor.id)
    return query


def list_claims(session: Session, *, actor: User, filters: ClaimFilters) -> tuple[list[Claim], int]:
    """Return one page of claims plus the total count before pagination."""
    query = _visible_claims_query(actor)

    if filters.status is not None:
        query = query.where(Claim.status == filters.status.value)
    if filters.min_amount is not None:
        query = query.where(Claim.amount >= filters.min_amount)
    if filters.max_amount is not None:
        query = query.where(Claim.amount <= filters.max_amount)
    if filters.date_from is not None:
        query = query.where(Claim.incident_date >= filters.date_from)
    if filters.date_to is not None:
        query = query.where(Claim.incident_date <= filters.date_to)
    if filters.q:
        pattern = f"%{filters.q.strip()}%"
        query = query.where(Claim.reference.ilike(pattern) | Claim.description.ilike(pattern))

    total = session.scalar(select(func.count()).select_from(query.subquery())) or 0

    descending = filters.sort.startswith("-")
    field_name = filters.sort.lstrip("-")
    if field_name not in SORTABLE_FIELDS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Cannot sort by {field_name!r}; allowed: {sorted(SORTABLE_FIELDS)}",
        )
    column = getattr(Claim, field_name)
    # A secondary key on the primary key keeps ordering stable when the sort
    # column has ties - otherwise pagination can repeat or drop rows.
    query = query.order_by(column.desc() if descending else column.asc(), Claim.id.asc())
    query = query.offset((filters.page - 1) * filters.size).limit(filters.size)

    return list(session.scalars(query).all()), total


def update_claim(
    session: Session,
    *,
    claim: Claim,
    actor: User,
    amount: Decimal | None,
    description: str | None,
) -> Claim:
    if ClaimStatus(claim.status) not in EDITABLE_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A claim in status {claim.status} can no longer be edited.",
        )
    if claim.claimant_id != actor.id and actor.role == Role.CUSTOMER.value:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Claim not found")

    if amount is not None:
        policy = session.get(Policy, claim.policy_id)
        if policy is None:  # pragma: no cover - guaranteed by a NOT NULL foreign key
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Policy not found")
        try:
            validate_claim_amount(amount, policy.coverage_limit)
        except DomainError as exc:
            raise as_domain_error(exc) from exc
        claim.amount = amount

    if description is not None:
        claim.description = description

    session.commit()
    session.refresh(claim)
    return claim


def withdraw_claim(session: Session, *, claim: Claim, actor: User) -> None:
    """Soft delete: the row survives, and the audit trail records the withdrawal."""
    if ClaimStatus(claim.status) not in EDITABLE_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Only a DRAFT claim can be withdrawn; this one is {claim.status}.",
        )
    if claim.claimant_id != actor.id and actor.role == Role.CUSTOMER.value:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Claim not found")

    previous = ClaimStatus(claim.status)
    claim.status = ClaimStatus.WITHDRAWN.value
    claim.withdrawn_at = datetime.now(UTC)
    _record_event(
        session,
        claim=claim,
        actor=actor,
        from_status=previous,
        to_status=ClaimStatus.WITHDRAWN,
    )
    session.commit()


def apply_transition(
    session: Session,
    *,
    claim: Claim,
    actor: User,
    action: ClaimAction,
    note: str | None = None,
) -> Claim:
    """Move a claim along the status machine, writing the audit trail and payout."""
    current = ClaimStatus(claim.status)
    try:
        target = resolve_transition(
            action,
            current_status=current,
            actor_role=Role(actor.role),
            is_owner=claim.claimant_id == actor.id,
            amount=claim.amount,
        )
    except DomainError as exc:
        raise as_domain_error(exc) from exc

    claim.status = target.value
    if target in (ClaimStatus.APPROVED, ClaimStatus.REJECTED):
        claim.decided_by_id = actor.id

    if target is ClaimStatus.PAID:
        # The unique constraint on payouts.claim_id makes a duplicate impossible
        # at the storage layer; this check turns it into a clean 409 instead.
        existing = session.scalar(select(Payout).where(Payout.claim_id == claim.id))
        if existing is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This claim has already been paid.",
            )
        session.add(Payout(claim_id=claim.id, amount=claim.amount, paid_by_id=actor.id))

    _record_event(
        session, claim=claim, actor=actor, from_status=current, to_status=target, note=note
    )
    session.commit()
    session.refresh(claim)
    return claim
