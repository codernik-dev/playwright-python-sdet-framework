"""Claim endpoints - the service object the majority of tests use."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Any

from claimdesk_qa.api.client import ApiClient, ApiResponse
from claimdesk_qa.api.models import ClaimModel
from claimdesk_qa.domain import ClaimAction, ClaimStatus, path_to


class ClaimsApi:
    """Wraps /claims.

    Methods return :class:`ApiResponse` rather than parsed models, so a positive
    and a negative test call exactly the same method. A service that parsed and
    raised would force every negative test to reach around it - and a framework
    people work around is a framework nobody trusts.
    """

    def __init__(self, client: ApiClient) -> None:
        self._client = client

    # -- reads -------------------------------------------------------------- #

    def list(
        self,
        *,
        status: ClaimStatus | str | None = None,
        min_amount: Decimal | str | None = None,
        max_amount: Decimal | str | None = None,
        date_from: date | str | None = None,
        date_to: date | str | None = None,
        q: str | None = None,
        sort: str | None = None,
        page: int | None = None,
        size: int | None = None,
    ) -> ApiResponse:
        return self._client.get(
            "/claims",
            params={
                "status": str(status) if status is not None else None,
                "min_amount": str(min_amount) if min_amount is not None else None,
                "max_amount": str(max_amount) if max_amount is not None else None,
                "date_from": str(date_from) if date_from is not None else None,
                "date_to": str(date_to) if date_to is not None else None,
                "q": q,
                "sort": sort,
                "page": page,
                "size": size,
            },
        )

    def get(self, claim_id: uuid.UUID | str) -> ApiResponse:
        return self._client.get(f"/claims/{claim_id}")

    def events(self, claim_id: uuid.UUID | str) -> ApiResponse:
        return self._client.get(f"/claims/{claim_id}/events")

    def payout(self, claim_id: uuid.UUID | str) -> ApiResponse:
        return self._client.get(f"/claims/{claim_id}/payout")

    # -- writes ------------------------------------------------------------- #

    def create(self, payload: dict[str, Any]) -> ApiResponse:
        return self._client.post("/claims", json=payload)

    def update(self, claim_id: uuid.UUID | str, payload: dict[str, Any]) -> ApiResponse:
        return self._client.patch(f"/claims/{claim_id}", json=payload)

    def withdraw(self, claim_id: uuid.UUID | str) -> ApiResponse:
        return self._client.delete(f"/claims/{claim_id}")

    def transition(
        self,
        claim_id: uuid.UUID | str,
        action: ClaimAction | str,
        *,
        note: str | None = None,
    ) -> ApiResponse:
        return self._client.post(
            f"/claims/{claim_id}/transitions",
            json={"action": str(action), "note": note},
        )

    # -- workflow helpers --------------------------------------------------- #

    def create_claim(self, payload: dict[str, Any]) -> ClaimModel:
        """Create a claim, asserting success, and return it typed.

        The asserting variant exists for *arrangement*: when a test's setup fails
        it must fail loudly at the setup line, not produce a confusing failure
        three steps later. Tests that are *about* creation call ``create`` instead
        and assert for themselves.
        """
        return self.create(payload).expect_status(201).model(ClaimModel)

    def drive_to(
        self,
        claim_id: uuid.UUID | str,
        target: ClaimStatus,
        *,
        staff: ClaimsApi | None = None,
    ) -> ClaimModel:
        """Move a fresh DRAFT claim to ``target`` through the real workflow.

        Reaching a state by writing rows would be faster and would also be a lie:
        it skips the audit trail and the payout side effects that the database
        tests then assert on. The framework's database role holds SELECT only, so
        this is the only route available - by design.

        Args:
            staff: the adjuster's or administrator's service object. Review,
                approval, rejection and payment are not available to the customer
                who owns the claim, so the caller must supply the actor with the
                authority to perform them.
        """
        customer_actions = {ClaimAction.SUBMIT}
        current: ClaimModel | None = None

        for action in path_to(target):
            actor = self if action in customer_actions else (staff or self)
            current = actor.transition(claim_id, action).expect_status(200).model(ClaimModel)

        if current is None:  # target was DRAFT: nothing to do
            return self.get(claim_id).expect_status(200).model(ClaimModel)

        if current.status is not target:
            msg = f"Expected the claim to reach {target} but it is {current.status}"
            raise AssertionError(msg)
        return current
