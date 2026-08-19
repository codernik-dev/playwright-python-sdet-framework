"""Shared FastAPI dependencies: authentication and role checks.

The application accepts the same JWT from two places:

* ``Authorization: Bearer <token>`` — used by API clients and by the framework's
  API layer;
* a ``session`` cookie — set by the HTML login form.

One token, two transports. That is what lets the UI tests authenticate once
through the API and inject the resulting cookie into the browser instead of
re-typing a login form they are not testing.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from claimdesk.db import get_session
from claimdesk.domain import Role
from claimdesk.models import User
from claimdesk.security import TokenError, decode_access_token

SESSION_COOKIE_NAME = "session"

_UNAUTHENTICATED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Not authenticated",
    headers={"WWW-Authenticate": "Bearer"},
)


def _extract_token(request: Request) -> str | None:
    header = request.headers.get("Authorization")
    if header:
        scheme, _, credentials = header.partition(" ")
        # A wrong scheme is treated as absent rather than as an error, so
        # "Basic ..." and a malformed header behave identically: 401.
        if scheme.lower() == "bearer" and credentials.strip():
            return credentials.strip()
        return None
    return request.cookies.get(SESSION_COOKIE_NAME)


def get_current_user(
    request: Request,
    session: Session = Depends(get_session),
) -> User:
    """Resolve the caller, or raise 401.

    A deactivated user is rejected here, which is what makes a token stop working
    the moment an administrator disables the account — the behaviour asserted by
    API-AUTH-008 and E2E-USR-001.
    """
    token = _extract_token(request)
    if not token:
        raise _UNAUTHENTICATED

    try:
        payload = decode_access_token(token)
    except TokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    try:
        user_id = uuid.UUID(str(payload.get("sub")))
    except (ValueError, TypeError) as exc:
        raise _UNAUTHENTICATED from exc

    user = session.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Account is inactive or no longer exists",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def require_roles(*allowed: Role) -> Callable[[User], User]:
    """Dependency factory enforcing that the caller holds one of ``allowed``.

    Returns 403, not 401: the caller *is* authenticated, they simply may not do
    this. Conflating the two is a common API bug and a favourite interview question.
    """

    def _check(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in {role.value for role in allowed}:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions for this operation",
            )
        return current_user

    return _check
