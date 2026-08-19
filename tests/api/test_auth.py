"""API-AUTH — authentication and session handling.

Matrix: API-AUTH-001 … API-AUTH-009 in docs/phase-1-design.md §8.4.
"""

from __future__ import annotations

import pytest

from claimdesk_qa.api import ApiClient, AuthApi, ClaimsApi
from claimdesk_qa.api.models import TokenResponse, UserModel
from claimdesk_qa.config import Settings
from claimdesk_qa.data.seeded import SeededAccounts
from claimdesk_qa.domain import Role


@pytest.fixture
def password(settings: Settings) -> str:
    return settings.seed_user_password.get_secret_value()


# --------------------------------------------------------------------------- #
# API-AUTH-001 / 009 — the happy path
# --------------------------------------------------------------------------- #


@pytest.mark.smoke
def test_login_with_valid_credentials_returns_a_bearer_token(
    anonymous_auth: AuthApi, password: str
) -> None:
    """API-AUTH-001."""
    response = anonymous_auth.login(SeededAccounts.CUSTOMER, password).expect_status(200)

    token = response.model(TokenResponse)

    assert token.token_type == "bearer"
    assert token.access_token
    assert token.expires_in > 0


@pytest.mark.smoke
def test_me_returns_the_caller_identity(customer_client: ApiClient) -> None:
    """API-AUTH-009. Also validates the full user contract in one line."""
    user = AuthApi(customer_client).me().expect_status(200).model(UserModel)

    assert user.email == SeededAccounts.CUSTOMER
    assert user.role is Role.CUSTOMER
    assert user.is_active is True


def test_the_login_response_does_not_leak_the_password_hash(
    anonymous_auth: AuthApi, password: str
) -> None:
    """A token response has no business carrying credential material."""
    body = anonymous_auth.login(SeededAccounts.CUSTOMER, password).expect_status(200).raw.text

    assert password not in body
    assert "password" not in body.lower()
    assert "$2b$" not in body  # a bcrypt hash prefix


# --------------------------------------------------------------------------- #
# API-AUTH-002 / 003 — failures must be indistinguishable
# --------------------------------------------------------------------------- #


@pytest.mark.negative
def test_login_with_the_wrong_password_is_rejected(
    anonymous_auth: AuthApi,
) -> None:
    """API-AUTH-002."""
    anonymous_auth.login(SeededAccounts.CUSTOMER, "definitely-not-the-password").expect_status(401)


@pytest.mark.negative
def test_unknown_user_and_wrong_password_are_indistinguishable(
    anonymous_auth: AuthApi, password: str
) -> None:
    """API-AUTH-003 — a user-enumeration check.

    If "no such account" and "wrong password" produce different responses, anyone
    can discover which email addresses are registered by watching the difference.
    Status code, message and timing-independent body must all match.
    """
    wrong_password = anonymous_auth.login(SeededAccounts.CUSTOMER, "wrong-password")
    unknown_user = anonymous_auth.login("definitely-not-registered@example.com", password)

    assert wrong_password.status_code == unknown_user.status_code == 401
    assert wrong_password.detail() == unknown_user.detail()


@pytest.mark.negative
@pytest.mark.parametrize(
    ("payload", "expected_field"),
    [
        pytest.param({"password": "x"}, "email", id="email-missing"),
        pytest.param({"email": SeededAccounts.CUSTOMER}, "password", id="password-missing"),
        pytest.param({"email": "not-an-email", "password": "x"}, "email", id="email-malformed"),
        pytest.param({"email": "", "password": "x"}, "email", id="email-empty"),
        pytest.param({"email": SeededAccounts.CUSTOMER, "password": ""}, "password", id="pw-empty"),
    ],
)
def test_malformed_login_payloads_are_rejected_by_field(
    anonymous_client: ApiClient, payload: dict[str, str], expected_field: str
) -> None:
    """API-AUTH-004.

    Asserting *which* field was rejected, not merely that something was. A test
    that only checks for 422 passes even when the API rejects the wrong field.
    """
    response = anonymous_client.post("/auth/login", json=payload, authenticate=False)

    response.expect_status(422)
    assert expected_field in response.raw.text


# --------------------------------------------------------------------------- #
# API-AUTH-005 / 006 — missing and malformed credentials
# --------------------------------------------------------------------------- #


@pytest.mark.negative
@pytest.mark.smoke
def test_a_protected_endpoint_rejects_an_anonymous_request(anonymous_client: ApiClient) -> None:
    """API-AUTH-005.

    The client here has never logged in. That is the whole point: in Phase 3 this
    exact check passed against a *shared* client because a leftover session cookie
    authenticated it. See ADR 0007.
    """
    ClaimsApi(anonymous_client).list().expect_status(401)


@pytest.mark.negative
@pytest.mark.parametrize(
    "header",
    [
        pytest.param("", id="empty"),
        pytest.param("Bearer", id="scheme-only"),
        # Note: "Bearer " with a trailing space is deliberately absent. httpx
        # refuses to send it - a trailing space is illegal in a header value per
        # RFC 9110 - so it is untestable over HTTP rather than a server behaviour.
        pytest.param("Bearer  double-space", id="double-space"),
        pytest.param("Bearer not-a-jwt", id="not-a-jwt"),
        pytest.param("Bearer a.b.c", id="three-segments-but-garbage"),
        pytest.param("Basic dXNlcjpwYXNz", id="wrong-scheme"),
        pytest.param("bearer lowercase-scheme", id="lowercase-scheme-garbage-token"),
    ],
)
def test_malformed_authorization_headers_are_rejected(
    anonymous_client: ApiClient, header: str
) -> None:
    """API-AUTH-006. Every malformed shape must land on 401, never 500."""
    response = anonymous_client.get("/claims", headers={"Authorization": header})

    response.expect_status(401)


@pytest.mark.negative
def test_a_token_signed_with_the_wrong_key_is_rejected(anonymous_client: ApiClient) -> None:
    """A structurally valid JWT with a bad signature must not be accepted.

    This is the check that would catch signature verification being disabled — a
    real and catastrophic misconfiguration that a "malformed string" test misses
    entirely, because a malformed string fails parsing long before verification.
    """
    forged = (
        "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
        "eyJzdWIiOiIwMDAwMDAwMC0wMDAwLTAwMDAtMDAwMC0wMDAwMDAwMDAwMDAiLCJyb2xlIjoiQURNSU4ifQ."
        "ZmFrZS1zaWduYXR1cmUtdGhhdC1kb2VzLW5vdC12ZXJpZnk"
    )

    anonymous_client.get("/claims", headers={"Authorization": f"Bearer {forged}"}).expect_status(
        401
    )


# --------------------------------------------------------------------------- #
# contract details
# --------------------------------------------------------------------------- #


@pytest.mark.contract
def test_a_rejected_request_advertises_the_expected_scheme(anonymous_client: ApiClient) -> None:
    """RFC 7235: a 401 carries WWW-Authenticate telling the client what to send."""
    response = ClaimsApi(anonymous_client).list()

    response.expect_status(401)
    assert response.headers.get("WWW-Authenticate") == "Bearer"


@pytest.mark.contract
def test_the_correlation_id_is_echoed_back(customer_client: ApiClient, request_id: str) -> None:
    """Proves the correlation chain works end to end.

    The framework sends X-Request-Id derived from this test's node id; the
    application echoes it and writes it to its own log. That is what lets a CI
    failure be traced to exact server-side requests with one grep.
    """
    response = AuthApi(customer_client).me().expect_status(200)

    assert response.headers.get("X-Request-Id") == request_id
    assert request_id.startswith("qa-")
