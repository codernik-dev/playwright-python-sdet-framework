"""Fixtures for the API suite.

The shape of this file is dictated by ADR 0007: **one client per identity, never a
shared one**. Every role gets its own ``ApiClient`` carrying its own token, and the
anonymous client has never logged in at all.

That is not tidiness. In Phase 3 a shared client's leftover session cookie made an
"unauthenticated request is rejected" check pass while testing an *authenticated*
request. Separate clients make that impossible rather than merely unlikely.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from claimdesk_qa.api import ApiClient, AuthApi, ClaimsApi, PoliciesApi, UsersApi
from claimdesk_qa.api.models import PolicyModel
from claimdesk_qa.config import Settings
from claimdesk_qa.data import ClaimFactory
from claimdesk_qa.data.seeded import SeededAccounts, SeededPolicies


@pytest.fixture(autouse=True)
def _require_application(app_ready: float) -> None:
    """Every API test needs the application; the framework's unit tests do not.

    Autouse *here* rather than in the root conftest, so ``pytest -m framework``
    still runs with nothing else alive. Requesting it once, in one place, means a
    dead environment produces a single clear error instead of one per test.
    """


def _client(settings: Settings, token: str | None = None) -> ApiClient:
    return ApiClient(
        base_url=settings.api_url,
        timeout_seconds=settings.http_timeout_seconds,
        token=token,
    )


@pytest.fixture
def anonymous_client(settings: Settings) -> Iterator[ApiClient]:
    """A client that has never authenticated. Used by every 401 test."""
    with _client(settings) as client:
        yield client


@pytest.fixture(scope="session")
def _tokens(settings: Settings, app_ready: float) -> dict[str, str]:
    """Log each seeded role in once per session.

    Session-scoped because a bcrypt verification costs real time and the tokens
    are immutable — but the *clients* built from them are function-scoped, so no
    HTTP state is ever shared between tests.
    """
    password = settings.seed_user_password.get_secret_value()
    with _client(settings) as client:
        auth = AuthApi(client)
        return {
            name: auth.token_for(email, password)
            for name, email in (
                ("admin", SeededAccounts.ADMIN),
                ("adjuster", SeededAccounts.ADJUSTER),
                ("customer", SeededAccounts.CUSTOMER),
                ("other_customer", SeededAccounts.OTHER_CUSTOMER),
            )
        }


@pytest.fixture
def customer_client(settings: Settings, _tokens: dict[str, str]) -> Iterator[ApiClient]:
    with _client(settings, _tokens["customer"]) as client:
        yield client


@pytest.fixture
def other_customer_client(settings: Settings, _tokens: dict[str, str]) -> Iterator[ApiClient]:
    """A second customer — the only way to prove cross-tenant access is refused."""
    with _client(settings, _tokens["other_customer"]) as client:
        yield client


@pytest.fixture
def adjuster_client(settings: Settings, _tokens: dict[str, str]) -> Iterator[ApiClient]:
    with _client(settings, _tokens["adjuster"]) as client:
        yield client


@pytest.fixture
def admin_client(settings: Settings, _tokens: dict[str, str]) -> Iterator[ApiClient]:
    with _client(settings, _tokens["admin"]) as client:
        yield client


# --------------------------------------------------------------------------- #
# service objects
# --------------------------------------------------------------------------- #


@pytest.fixture
def customer_claims(customer_client: ApiClient) -> ClaimsApi:
    return ClaimsApi(customer_client)


@pytest.fixture
def other_customer_claims(other_customer_client: ApiClient) -> ClaimsApi:
    return ClaimsApi(other_customer_client)


@pytest.fixture
def adjuster_claims(adjuster_client: ApiClient) -> ClaimsApi:
    return ClaimsApi(adjuster_client)


@pytest.fixture
def admin_claims(admin_client: ApiClient) -> ClaimsApi:
    return ClaimsApi(admin_client)


@pytest.fixture
def customer_policies(customer_client: ApiClient) -> PoliciesApi:
    return PoliciesApi(customer_client)


@pytest.fixture
def admin_users(admin_client: ApiClient) -> UsersApi:
    return UsersApi(admin_client)


@pytest.fixture
def customer_users(customer_client: ApiClient) -> UsersApi:
    return UsersApi(customer_client)


@pytest.fixture
def anonymous_auth(anonymous_client: ApiClient) -> AuthApi:
    return AuthApi(anonymous_client)


# --------------------------------------------------------------------------- #
# data
# --------------------------------------------------------------------------- #


@pytest.fixture
def high_coverage_policy(customer_policies: PoliciesApi) -> PolicyModel:
    """The customer's 10 000.00 policy — room to exceed the approval limit."""
    return customer_policies.by_number(SeededPolicies.CUSTOMER_HIGH_COVERAGE)


@pytest.fixture
def low_coverage_policy(customer_policies: PoliciesApi) -> PolicyModel:
    """The customer's 2 500.00 policy.

    Below the adjuster approval limit on purpose, so a coverage-limit boundary
    test cannot accidentally be measuring the approval limit instead.
    """
    return customer_policies.by_number(SeededPolicies.CUSTOMER_LOW_COVERAGE)


@pytest.fixture
def claim_factory(high_coverage_policy: PolicyModel, faker_seed: int) -> ClaimFactory:
    """Valid-by-default claim payloads against the high-coverage policy.

    Depends on ``faker_seed`` so the Faker plugin seeds this test's generator
    before the factory uses it — reproducible data without collisions between
    tests.
    """
    from faker import Faker

    generator = Faker()
    generator.seed_instance(faker_seed)
    return ClaimFactory(policy_id=high_coverage_policy.id, faker=generator)
