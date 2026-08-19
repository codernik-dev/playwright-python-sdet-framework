"""User administration endpoints (administrators only)."""

from __future__ import annotations

import uuid
from typing import Any

from claimdesk_qa.api.client import ApiClient, ApiResponse


class UsersApi:
    def __init__(self, client: ApiClient) -> None:
        self._client = client

    def list(self, *, page: int | None = None, size: int | None = None) -> ApiResponse:
        return self._client.get("/users", params={"page": page, "size": size})

    def create(self, payload: dict[str, Any]) -> ApiResponse:
        return self._client.post("/users", json=payload)

    def get(self, user_id: uuid.UUID | str) -> ApiResponse:
        return self._client.get(f"/users/{user_id}")

    def update(self, user_id: uuid.UUID | str, payload: dict[str, Any]) -> ApiResponse:
        return self._client.patch(f"/users/{user_id}", json=payload)

    def set_active(self, user_id: uuid.UUID | str, *, active: bool) -> ApiResponse:
        return self.update(user_id, {"is_active": active})
