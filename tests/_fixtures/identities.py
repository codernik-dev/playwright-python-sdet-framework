"""Authenticated API access, one client per identity.

Every role gets its own :class:`ApiClient`. That is the control from ADR 0007: a
shared client's leftover session cookie once made an unauthenticated assertion
pass while testing an authenticated request.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator

import pytest

from claimdesk_qa.api import ApiClient, AuthApi, ClaimsApi, PoliciesApi, UsersApi
from claimdesk_qa.api.models import PolicyModel
from claimdesk_qa.config import Settings
from claimdesk_qa.data import ClaimFactory
from claimdesk_qa.data.seeded import SeededAccounts, SeededPolicies

ROLE_EMAILS: dict[str, str] = {
    "admin": SeededAccounts.ADMIN,
    "adjuster": SeededAccounts.ADJUSTER,
    "customer": SeededAccounts.CUSTOMER,
    "other_customer": SeededAccounts.OTHER_CUSTOMER,
}


@pytest.fixture(scope="session")
def role_tokens(settings: Settings, app_ready: float) -> dict[str, str]:
    """One login per role for the whole session.

    Session-scoped because a bcrypt verification costs real time and a token is
    immutable. The *clients* built from these are function-scoped, so no HTTP
    state is ever shared between tests.
    """
    password = settings.seed_user_password.get_secret_value()
    with ApiClient(
        base_url=settings.api_url, timeout_seconds=settings.http_timeout_seconds
    ) as client:
        auth = AuthApi(client)
        return {role: auth.token_for(email, password) for role, email in ROLE_EMAILS.items()}


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


def _client_fixture(role: str) -> Callable[[Settings, dict[str, str]], Iterator[ApiClient]]:
    """Build a fixture yielding a client authenticated as ``role``.

    Generated rather than written out four times: the bodies would be identical
    apart from one string, and four copies is four chances for one to drift.
    """

    def fixture(settings: Settings, role_tokens: dict[str, str]) -> Iterator[ApiClient]:
        with _client(settings, role_tokens[role]) as client:
            yield client

    return fixture


customer_client = pytest.fixture(name="customer_client")(_client_fixture("customer"))
adjuster_client = pytest.fixture(name="adjuster_client")(_client_fixture("adjuster"))
admin_client = pytest.fixture(name="admin_client")(_client_fixture("admin"))
other_customer_client = pytest.fixture(name="other_customer_client")(
    _client_fixture("other_customer")
)


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
    """The customer's 10 000.00 policy - room to exceed the approval limit."""
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

    Depends on ``faker_seed`` so this test's generator is seeded before use -
    reproducible data without collisions between tests.
    """
    from faker import Faker

    generator = Faker()
    generator.seed_instance(faker_seed)
    return ClaimFactory(policy_id=high_coverage_policy.id, faker=generator)
