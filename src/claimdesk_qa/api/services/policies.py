"""Policy endpoints."""

from __future__ import annotations

import uuid

from claimdesk_qa.api.client import ApiClient, ApiResponse
from claimdesk_qa.api.models import PolicyModel


class PoliciesApi:
    def __init__(self, client: ApiClient) -> None:
        self._client = client

    def list(self) -> ApiResponse:
        return self._client.get("/policies")

    def get(self, policy_id: uuid.UUID | str) -> ApiResponse:
        return self._client.get(f"/policies/{policy_id}")

    def by_number(self, policy_number: str) -> PolicyModel:
        """Find a seeded policy by its human-readable number.

        Fixtures use this so a test can say "the policy with a 2500 coverage
        limit" without hard-coding a UUID that changes on every database reset.
        """
        policies = [
            PolicyModel.model_validate(item) for item in self.list().expect_status(200).json()
        ]
        for policy in policies:
            if policy.policy_number == policy_number:
                return policy
        available = ", ".join(sorted(policy.policy_number for policy in policies)) or "none"
        msg = f"Policy {policy_number!r} is not visible to this user. Visible: {available}"
        raise AssertionError(msg)
