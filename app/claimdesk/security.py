"""Password hashing and JSON Web Token handling.

bcrypt is used directly rather than through passlib: passlib's bcrypt backend
breaks against modern bcrypt releases, and the direct API is four lines.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import bcrypt
import jwt

from claimdesk.config import get_app_settings

_ALGORITHM = "HS256"

# bcrypt truncates silently beyond 72 bytes, which would let a long password be
# accepted with only its prefix checked. The API rejects longer passwords instead.
MAX_PASSWORD_BYTES = 72


class TokenError(Exception):
    """Raised when a token is absent, malformed, expired or otherwise unusable."""


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt(rounds=10)).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def create_access_token(user_id: UUID, role: str) -> tuple[str, int]:
    """Return ``(token, expires_in_seconds)`` for the given user."""
    settings = get_app_settings()
    expires_in = settings.app_jwt_expiry_minutes * 60
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=expires_in)).timestamp()),
    }
    token = jwt.encode(payload, settings.app_jwt_secret.get_secret_value(), algorithm=_ALGORITHM)
    return token, expires_in


def decode_access_token(token: str) -> dict[str, Any]:
    """Decode and validate a token, raising :class:`TokenError` when unusable."""
    settings = get_app_settings()
    try:
        decoded: dict[str, Any] = jwt.decode(
            token,
            settings.app_jwt_secret.get_secret_value(),
            algorithms=[_ALGORITHM],
        )
    except jwt.ExpiredSignatureError as exc:
        raise TokenError("Token has expired") from exc
    except jwt.PyJWTError as exc:
        raise TokenError("Token is invalid") from exc
    return decoded
