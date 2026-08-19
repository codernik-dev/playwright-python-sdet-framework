"""Authentication endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from claimdesk.db import get_session
from claimdesk.deps import SESSION_COOKIE_NAME, get_current_user
from claimdesk.models import User
from claimdesk.schemas import LoginRequest, TokenResponse, UserResponse
from claimdesk.security import create_access_token, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])

#: One message for every failure mode. A distinct "unknown user" reply would let
#: anyone enumerate valid email addresses, so wrong-password and unknown-user are
#: deliberately indistinguishable. API-AUTH-002 and API-AUTH-003 assert exactly this.
_INVALID_CREDENTIALS = "Invalid email or password"


@router.post("/login", response_model=TokenResponse)
def login(
    payload: LoginRequest, response: Response, session: Session = Depends(get_session)
) -> TokenResponse:
    user = session.scalar(select(User).where(User.email == payload.email.lower()))

    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=_INVALID_CREDENTIALS,
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Account is deactivated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token, expires_in = create_access_token(user.id, user.role)

    # The same token is also set as a cookie so the HTML interface is logged in.
    # httponly keeps it away from JavaScript; samesite=lax is enough for a
    # form-based application and keeps the browser tests simple.
    response.set_cookie(
        SESSION_COOKIE_NAME,
        token,
        httponly=True,
        samesite="lax",
        max_age=expires_in,
        path="/",
    )
    return TokenResponse(access_token=token, expires_in=expires_in)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(response: Response) -> None:
    """Clear the browser session.

    A bearer token cannot be revoked without server-side state, which this
    application deliberately does not have. The limitation is documented rather
    than hidden: deactivating the user is the real revocation path.
    """
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")


@router.get("/me", response_model=UserResponse)
def me(current_user: User = Depends(get_current_user)) -> User:
    return current_user
