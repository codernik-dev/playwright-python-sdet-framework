"""Response contracts.

Every model here is an assertion. Validating a response against one checks, in a
single line, that every documented field is present, correctly typed and correctly
named — the kind of regression that a hand-written
``assert response.json()["status"] == "DRAFT"`` sails straight past, because it
only looks at the one field the author happened to think about.

Two deliberate choices:

* ``extra="forbid"`` — an **undocumented extra field fails the test**. That sounds
  aggressive, and it is the point: a field appearing in a response is how personal
  data leaks into an API, and how a breaking change ships unnoticed. If a new
  field is intended, adding it here is a one-line, reviewable diff.
* ``Decimal`` for money, never ``float``. ``0.1 + 0.2 != 0.3`` is not a joke when
  the value is a payout, and a model that parses money as a float would quietly
  hide the very defect the database tests exist to catch.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict

from claimdesk_qa.domain import ClaimStatus, Role

T = TypeVar("T")


class StrictModel(BaseModel):
    """Base for every contract: unknown fields are a failure, not a shrug."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class TokenResponse(StrictModel):
    access_token: str
    token_type: str
    expires_in: int


class UserModel(StrictModel):
    id: uuid.UUID
    email: str
    full_name: str
    role: Role
    is_active: bool
    created_at: datetime


class PolicyModel(StrictModel):
    id: uuid.UUID
    policy_number: str
    holder_id: uuid.UUID
    coverage_limit: Decimal
    is_active: bool


class ClaimModel(StrictModel):
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


class ClaimEventModel(StrictModel):
    id: uuid.UUID
    claim_id: uuid.UUID
    actor_id: uuid.UUID
    from_status: ClaimStatus | None
    to_status: ClaimStatus
    note: str | None
    occurred_at: datetime


class PayoutModel(StrictModel):
    id: uuid.UUID
    claim_id: uuid.UUID
    amount: Decimal
    paid_by_id: uuid.UUID
    paid_at: datetime


class Page(StrictModel, Generic[T]):
    """A page of results.

    ``total`` is the count *before* pagination, which is what lets a test tell
    "the filter matched nothing" apart from "this page happens to be empty".
    """

    items: list[T]
    page: int
    size: int
    total: int


class ErrorResponse(BaseModel):
    """FastAPI's error shape.

    ``detail`` is a string for application errors and a list of field errors for
    validation failures, so it is typed loosely on purpose — this model exists to
    read an error, not to police one.
    """

    model_config = ConfigDict(extra="forbid")

    detail: str | list[dict[str, object]]

    def field_names(self) -> set[str]:
        """Fields named by a 422 validation response.

        Lets a test assert *which* field was rejected rather than merely that
        something was — the difference between "it 422'd" and "it 422'd for the
        reason I intended".
        """
        if isinstance(self.detail, str):
            return set()
        names: set[str] = set()
        for item in self.detail:
            location = item.get("loc")
            if isinstance(location, list) and location:
                names.add(str(location[-1]))
        return names

    def message(self) -> str:
        if isinstance(self.detail, str):
            return self.detail
        return "; ".join(str(item.get("msg", "")) for item in self.detail)
