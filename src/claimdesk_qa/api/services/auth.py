"""Authentication endpoints."""

from __future__ import annotations

from claimdesk_qa.api.client import ApiClient, ApiResponse


class AuthApi:
    """Wraps /auth. Returns raw responses so negative tests use the same calls."""

    def __init__(self, client: ApiClient) -> None:
        self._client = client

    def login(self, email: str, password: str) -> ApiResponse:
        """Attempt a login. Does NOT assert success.

        Negative tests outnumber positive ones here, so the method that asserts is
        the separate `token_for` below. A helper that raised on failure would force
        every negative test to work around it.
        """
        return self._client.post(
            "/auth/login",
            json={"email": email, "password": password},
            authenticate=False,
        )

    def token_for(self, email: str, password: str) -> str:
        """Log in and return the bearer token, asserting the login worked.

        Used by fixtures rather than by tests: when a fixture's login fails, the
        test that depends on it should error immediately with a clear message
        rather than proceed and fail somewhere confusing.
        """
        response = self.login(email, password).expect_status(200)
        token: str = response.json()["access_token"]
        return token

    def me(self) -> ApiResponse:
        return self._client.get("/auth/me")

    def logout(self) -> ApiResponse:
        return self._client.post("/auth/logout")
