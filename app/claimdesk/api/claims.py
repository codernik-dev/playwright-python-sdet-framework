"""Claim endpoints — the core of the application under test."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from claimdesk.db import get_session
from claimdesk.deps import get_current_user
from claimdesk.domain import ClaimStatus
from claimdesk.models import Claim, ClaimEvent, Payout, User
from claimdesk.schemas import (
    MAX_PAGE_SIZE,
    ClaimCreateRequest,
    ClaimEventResponse,
    ClaimResponse,
    ClaimUpdateRequest,
    Page,
    PayoutResponse,
    TransitionRequest,
)
from claimdesk.services import (
    ClaimFilters,
    apply_transition,
    create_claim,
    get_visible_claim,
    list_claims,
    update_claim,
    withdraw_claim,
)

router = APIRouter(prefix="/claims", tags=["claims"])


@router.get("", response_model=Page[ClaimResponse])
def list_claims_endpoint(
    status_filter: ClaimStatus | None = Query(default=None, alias="status"),
    min_amount: Decimal | None = Query(default=None, ge=0),
    max_amount: Decimal | None = Query(default=None, ge=0),
    date_from: date | None = None,
    date_to: date | None = None,
    q: str | None = Query(default=None, max_length=100),
    sort: str = Query(default="-created_at"),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=MAX_PAGE_SIZE),
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> Page[ClaimResponse]:
    """List claims visible to the caller.

    ``total`` is the count before pagination, so a client can tell the difference
    between "the filter matched nothing" and "this page happens to be empty".
    """
    filters = ClaimFilters(
        status=status_filter,
        min_amount=min_amount,
        max_amount=max_amount,
        date_from=date_from,
        date_to=date_to,
        q=q,
        sort=sort,
        page=page,
        size=size,
    )
    items, total = list_claims(session, actor=current_user, filters=filters)
    return Page[ClaimResponse](
        items=[ClaimResponse.model_validate(item) for item in items],
        page=page,
        size=size,
        total=total,
    )


@router.post("", response_model=ClaimResponse, status_code=status.HTTP_201_CREATED)
def create_claim_endpoint(
    payload: ClaimCreateRequest,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> Claim:
    return create_claim(
        session,
        actor=current_user,
        policy_id=payload.policy_id,
        amount=payload.amount,
        description=payload.description,
        incident_date=payload.incident_date,
    )


@router.get("/{claim_id}", response_model=ClaimResponse)
def get_claim_endpoint(
    claim_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> Claim:
    return get_visible_claim(session, actor=current_user, claim_id=claim_id)


@router.patch("/{claim_id}", response_model=ClaimResponse)
def update_claim_endpoint(
    claim_id: uuid.UUID,
    payload: ClaimUpdateRequest,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> Claim:
    claim = get_visible_claim(session, actor=current_user, claim_id=claim_id)
    return update_claim(
        session,
        claim=claim,
        actor=current_user,
        amount=payload.amount,
        description=payload.description,
    )


@router.delete("/{claim_id}", status_code=status.HTTP_204_NO_CONTENT)
def withdraw_claim_endpoint(
    claim_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> None:
    claim = get_visible_claim(session, actor=current_user, claim_id=claim_id)
    withdraw_claim(session, claim=claim, actor=current_user)


@router.post("/{claim_id}/transitions", response_model=ClaimResponse)
def transition_claim_endpoint(
    claim_id: uuid.UUID,
    payload: TransitionRequest,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> Claim:
    """Advance a claim along the status machine.

    One endpoint for every action rather than ``/approve``, ``/reject`` and so on.
    That keeps the state machine in a single place and gives the framework a single,
    fully parametrisable surface for the invalid-transition matrix (API-STATE-005).
    """
    claim = get_visible_claim(session, actor=current_user, claim_id=claim_id)
    return apply_transition(
        session, claim=claim, actor=current_user, action=payload.action, note=payload.note
    )


@router.get("/{claim_id}/events", response_model=list[ClaimEventResponse])
def list_claim_events_endpoint(
    claim_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> list[ClaimEvent]:
    claim = get_visible_claim(session, actor=current_user, claim_id=claim_id)
    query = (
        select(ClaimEvent).where(ClaimEvent.claim_id == claim.id).order_by(ClaimEvent.occurred_at)
    )
    return list(session.scalars(query).all())


@router.get("/{claim_id}/payout", response_model=PayoutResponse)
def get_payout_endpoint(
    claim_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> Payout:
    claim: Claim = get_visible_claim(session, actor=current_user, claim_id=claim_id)
    payout = session.scalar(select(Payout).where(Payout.claim_id == claim.id))
    if payout is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="This claim has no payout"
        )
    return payout
