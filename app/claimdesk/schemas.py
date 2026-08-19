"""Request and response models.

Every constraint declared here becomes a boundary or negative test in the
framework's matrix. FastAPI turns a violated constraint into a ``422`` with a
field-level error body, which is what the API tests assert against.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from claimdesk.domain import ClaimAction, ClaimStatus, Role
from claimdesk.security import MAX_PASSWORD_BYTES

# Money: at most 12 digits with exactly 2 decimal places, strictly positive.
# Three decimal places are rejected rather than silently rounded.
Money = Annotated[Decimal, Field(gt=0, max_digits=12, decimal_places=2)]

DESCRIPTION_MIN_LENGTH = 5
DESCRIPTION_MAX_LENGTH = 500
PASSWORD_MIN_LENGTH = 8
MAX_PAGE_SIZE = 100

T = TypeVar("T")


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --------------------------------------------------------------------------- #
# authentication
# --------------------------------------------------------------------------- #


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


# --------------------------------------------------------------------------- #
# users
# --------------------------------------------------------------------------- #


class UserResponse(ORMModel):
    id: uuid.UUID
    email: EmailStr
    full_name: str
    role: Role
    is_active: bool
    created_at: datetime


class UserCreateRequest(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=2, max_length=120)
    role: Role
    password: str = Field(min_length=PASSWORD_MIN_LENGTH)

    @field_validator("password")
    @classmethod
    def _password_within_bcrypt_limit(cls, value: str) -> str:
        """Reject rather than silently truncate.

        bcrypt ignores everything beyond 72 bytes, so a longer password would be
        accepted with only its prefix ever checked — a real authentication bypass.
        """
        if len(value.encode("utf-8")) > MAX_PASSWORD_BYTES:
            msg = f"Password must be at most {MAX_PASSWORD_BYTES} bytes."
            raise ValueError(msg)
        return value


class UserUpdateRequest(BaseModel):
    full_name: str | None = Field(default=None, min_length=2, max_length=120)
    is_active: bool | None = None


# --------------------------------------------------------------------------- #
# policies
# --------------------------------------------------------------------------- #


class PolicyResponse(ORMModel):
    id: uuid.UUID
    policy_number: str
    holder_id: uuid.UUID
    coverage_limit: Decimal
    is_active: bool


# --------------------------------------------------------------------------- #
# claims
# --------------------------------------------------------------------------- #


class ClaimCreateRequest(BaseModel):
    policy_id: uuid.UUID
    amount: Money
    description: str = Field(min_length=DESCRIPTION_MIN_LENGTH, max_length=DESCRIPTION_MAX_LENGTH)
    incident_date: date

    @field_validator("incident_date")
    @classmethod
    def _not_in_the_future(cls, value: date) -> date:
        if value > date.today():
            msg = "Incident date cannot be in the future."
            raise ValueError(msg)
        return value


class ClaimUpdateRequest(BaseModel):
    """Partial update. Only a DRAFT claim may be changed at all."""

    amount: Money | None = None
    description: str | None = Field(
        default=None, min_length=DESCRIPTION_MIN_LENGTH, max_length=DESCRIPTION_MAX_LENGTH
    )


class ClaimResponse(ORMModel):
    id: uuid.UUID
    reference: str
    policy_id: uuid.UUID
    claimant_id: uuid.UUID
    amount: Decimal
    description: str
    incident_date: date
    status: ClaimStatus
    created_at: datetime
    updated_at: datetime
    withdrawn_at: datetime | None
    decided_by_id: uuid.UUID | None


class ClaimEventResponse(ORMModel):
    id: uuid.UUID
    claim_id: uuid.UUID
    actor_id: uuid.UUID
    from_status: ClaimStatus | None
    to_status: ClaimStatus
    note: str | None
    occurred_at: datetime


class TransitionRequest(BaseModel):
    action: ClaimAction
    note: str | None = Field(default=None, max_length=500)


class PayoutResponse(ORMModel):
    id: uuid.UUID
    claim_id: uuid.UUID
    amount: Decimal
    paid_by_id: uuid.UUID
    paid_at: datetime


# --------------------------------------------------------------------------- #
# pagination
# --------------------------------------------------------------------------- #


class Page(BaseModel, Generic[T]):
    """A page of results plus the metadata a client needs to navigate.

    ``total`` is the count *before* pagination, so a test can assert that
    filtering changed the result set rather than just the current page.
    """

    items: list[T]
    page: int
    size: int
    total: int
