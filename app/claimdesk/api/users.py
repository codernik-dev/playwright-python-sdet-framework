"""User administration. Administrators only."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from claimdesk.db import get_session
from claimdesk.deps import require_roles
from claimdesk.domain import Role
from claimdesk.models import User
from claimdesk.schemas import (
    MAX_PAGE_SIZE,
    Page,
    UserCreateRequest,
    UserResponse,
    UserUpdateRequest,
)
from claimdesk.security import hash_password

router = APIRouter(prefix="/users", tags=["users"])

#: Applied to every route in this module, so a new endpoint cannot be added
#: without the permission check - "secure by default, insecure by exception".
_admin_only = Depends(require_roles(Role.ADMIN))


@router.get("", response_model=Page[UserResponse])
def list_users(
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=MAX_PAGE_SIZE),
    _: User = _admin_only,
    session: Session = Depends(get_session),
) -> Page[UserResponse]:
    total = session.scalar(select(func.count()).select_from(User)) or 0
    query = select(User).order_by(User.created_at).offset((page - 1) * size).limit(size)
    return Page[UserResponse](
        items=[UserResponse.model_validate(user) for user in session.scalars(query).all()],
        page=page,
        size=size,
        total=total,
    )


@router.post("", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: UserCreateRequest,
    _: User = _admin_only,
    session: Session = Depends(get_session),
) -> User:
    email = payload.email.lower()
    if session.scalar(select(User).where(User.email == email)) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="A user with that email already exists"
        )

    user = User(
        email=email,
        full_name=payload.full_name,
        role=payload.role.value,
        password_hash=hash_password(payload.password),
        is_active=True,
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


@router.get("/{user_id}", response_model=UserResponse)
def get_user(
    user_id: uuid.UUID,
    _: User = _admin_only,
    session: Session = Depends(get_session),
) -> User:
    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user


@router.patch("/{user_id}", response_model=UserResponse)
def update_user(
    user_id: uuid.UUID,
    payload: UserUpdateRequest,
    current_user: User = _admin_only,
    session: Session = Depends(get_session),
) -> User:
    """Update a user. Deactivating one immediately invalidates their token."""
    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    if payload.is_active is False and user.id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An administrator cannot deactivate their own account",
        )

    if payload.full_name is not None:
        user.full_name = payload.full_name
    if payload.is_active is not None:
        user.is_active = payload.is_active

    session.commit()
    session.refresh(user)
    return user
