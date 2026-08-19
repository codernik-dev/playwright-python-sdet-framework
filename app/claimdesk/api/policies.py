"""Policy endpoints.

Read-only: policies are reference data created by the seed, which keeps the
application small while still giving claims something real to hang off.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from claimdesk.db import get_session
from claimdesk.deps import get_current_user
from claimdesk.domain import Role
from claimdesk.models import Policy, User
from claimdesk.schemas import PolicyResponse

router = APIRouter(prefix="/policies", tags=["policies"])


@router.get("", response_model=list[PolicyResponse])
def list_policies(
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> list[Policy]:
    """Staff see every policy; a customer sees only their own."""
    query = select(Policy).order_by(Policy.policy_number)
    if current_user.role == Role.CUSTOMER.value:
        query = query.where(Policy.holder_id == current_user.id)
    return list(session.scalars(query).all())


@router.get("/{policy_id}", response_model=PolicyResponse)
def get_policy(
    policy_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> Policy:
    policy = session.get(Policy, policy_id)
    if policy is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Policy not found")
    # Somebody else's policy is 404, not 403 - the same non-enumeration rule the
    # claim endpoints follow.
    if current_user.role == Role.CUSTOMER.value and policy.holder_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Policy not found")
    return policy
