"""API-AUTHZ — role and ownership based access control.

Matrix: API-AUTHZ-001 … API-AUTHZ-007.

Authorisation tests are the ones most likely to pass for the wrong reason, so two
rules apply throughout:

* every identity uses **its own client** — a shared client's leftover session
  cookie once made an unauthenticated check pass (ADR 0007);
* every "must be refused" test is paired with a "must be allowed" test. A test
  suite that only proves refusals also passes against an API that refuses
  everything.
"""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal

import pytest

from claimdesk_qa.api import ApiClient, ClaimsApi, UsersApi
from claimdesk_qa.api.models import ClaimModel, PolicyModel
from claimdesk_qa.data import ClaimFactory, UserFactory
from claimdesk_qa.domain import ADJUSTER_APPROVAL_LIMIT, ClaimAction, ClaimStatus

pytestmark = pytest.mark.authz

#: Builds a claim parked in UNDER_REVIEW at a given amount. Named rather than
#: inlined so the four tests that use it read cleanly and type-check.
ClaimUnderReviewFactory = Callable[[str], "ClaimModel"]


# --------------------------------------------------------------------------- #
# ownership — a customer sees only their own claims
# --------------------------------------------------------------------------- #


@pytest.mark.smoke
def test_a_customer_cannot_read_another_customers_claim(
    customer_claims: ClaimsApi,
    other_customer_claims: ClaimsApi,
    claim_factory: ClaimFactory,
) -> None:
    """API-AUTHZ-001 — and it must be 404, not 403.

    403 confirms the resource exists. Repeated against a range of identifiers that
    turns into an enumeration oracle: an attacker learns which claims are real
    without ever reading one. 404 reveals nothing.
    """
    claim = customer_claims.create_claim(claim_factory.payload())

    response = other_customer_claims.get(claim.id)

    response.expect_status(404)
    assert claim.reference not in response.raw.text, "the 404 body must not leak the resource"


def test_the_owner_can_read_their_own_claim(
    customer_claims: ClaimsApi, claim_factory: ClaimFactory
) -> None:
    """The paired positive case. Without it, an API refusing everyone would pass."""
    claim = customer_claims.create_claim(claim_factory.payload())

    customer_claims.get(claim.id).expect_status(200)


def test_a_customer_cannot_modify_another_customers_claim(
    customer_claims: ClaimsApi,
    other_customer_claims: ClaimsApi,
    claim_factory: ClaimFactory,
) -> None:
    """Reading is not the only thing that must be scoped to the owner."""
    claim = customer_claims.create_claim(claim_factory.payload())

    other_customer_claims.update(
        claim.id, {"description": "hijacked by another user"}
    ).expect_status(404)
    other_customer_claims.withdraw(claim.id).expect_status(404)

    unchanged = customer_claims.get(claim.id).expect_status(200).model(ClaimModel)
    assert unchanged.description == claim.description
    assert unchanged.status is ClaimStatus.DRAFT


def test_a_customers_list_never_includes_another_customers_claims(
    customer_claims: ClaimsApi,
    other_customer_claims: ClaimsApi,
    claim_factory: ClaimFactory,
) -> None:
    """Scoping the detail endpoint but not the list endpoint is a common oversight."""
    claim = customer_claims.create_claim(claim_factory.payload())

    page = other_customer_claims.list(q=claim.reference).expect_status(200)

    assert page.json()["items"] == []


def test_staff_can_read_any_customers_claim(
    customer_claims: ClaimsApi, adjuster_claims: ClaimsApi, claim_factory: ClaimFactory
) -> None:
    """Ownership restricts customers, not staff — adjusters must see every claim."""
    claim = customer_claims.create_claim(claim_factory.payload())

    adjuster_claims.get(claim.id).expect_status(200)


# --------------------------------------------------------------------------- #
# role — administrator-only endpoints
# --------------------------------------------------------------------------- #


@pytest.mark.smoke
def test_a_customer_cannot_list_users(customer_users: UsersApi) -> None:
    """API-AUTHZ-003 — 403 here, not 404.

    The distinction from the ownership case is deliberate: the endpoint's
    existence is not a secret, the caller simply lacks the role. Returning 404
    would tell an administrator debugging a permissions problem that the route
    does not exist.
    """
    customer_users.list().expect_status(403)


def test_an_administrator_can_list_users(admin_users: UsersApi) -> None:
    admin_users.list().expect_status(200)


def test_an_adjuster_cannot_administer_users(adjuster_client: ApiClient) -> None:
    """Being staff is not the same as being an administrator."""
    users = UsersApi(adjuster_client)

    users.list().expect_status(403)
    users.create(UserFactory().payload()).expect_status(403)


def test_a_customer_cannot_create_a_user(customer_users: UsersApi) -> None:
    """Self-registration is not an anonymous or customer capability here."""
    customer_users.create(UserFactory().payload(role="ADMIN")).expect_status(403)


def test_an_administrator_can_create_a_user(admin_users: UsersApi) -> None:
    payload = UserFactory().payload()

    created = admin_users.create(payload).expect_status(201)

    assert created.json()["email"] == payload["email"]


# --------------------------------------------------------------------------- #
# the adjuster approval limit — role and boundary in one rule
# --------------------------------------------------------------------------- #


@pytest.fixture
def claim_under_review(
    customer_claims: ClaimsApi,
    adjuster_claims: ClaimsApi,
    claim_factory: ClaimFactory,
    high_coverage_policy: PolicyModel,
) -> ClaimUnderReviewFactory:
    """A factory for claims parked in UNDER_REVIEW at a chosen amount.

    Driven through the real workflow rather than written into the database — the
    framework's database role holds SELECT only, and the transitions produce the
    audit rows the DB tests later assert on.
    """

    def _make(amount: str) -> ClaimModel:
        claim = customer_claims.create_claim(
            claim_factory.payload(policy_id=str(high_coverage_policy.id), amount=amount)
        )
        return customer_claims.drive_to(claim.id, ClaimStatus.UNDER_REVIEW, staff=adjuster_claims)

    return _make


@pytest.mark.boundary
@pytest.mark.parametrize(
    "amount",
    [
        pytest.param("0.01", id="far-below-limit"),
        pytest.param(str(ADJUSTER_APPROVAL_LIMIT - Decimal("0.01")), id="one-cent-below-limit"),
        pytest.param(str(ADJUSTER_APPROVAL_LIMIT), id="exactly-at-limit"),
    ],
)
def test_an_adjuster_may_approve_up_to_and_including_the_limit(
    adjuster_claims: ClaimsApi, claim_under_review: ClaimUnderReviewFactory, amount: str
) -> None:
    """API-AUTHZ-004 — the limit is inclusive."""
    claim = claim_under_review(amount)

    approved = (
        adjuster_claims.transition(claim.id, ClaimAction.APPROVE)
        .expect_status(200)
        .model(ClaimModel)
    )

    assert approved.status is ClaimStatus.APPROVED


@pytest.mark.boundary
@pytest.mark.parametrize(
    "amount",
    [
        pytest.param(str(ADJUSTER_APPROVAL_LIMIT + Decimal("0.01")), id="one-cent-above-limit"),
        pytest.param("9999.99", id="far-above-limit"),
    ],
)
def test_an_adjuster_may_not_approve_above_the_limit(
    adjuster_claims: ClaimsApi, claim_under_review: ClaimUnderReviewFactory, amount: str
) -> None:
    """API-AUTHZ-005.

    Also asserts the claim did **not** move. A refusal that still changes state is
    worse than no refusal at all, and a test that only checks the status code
    would miss it entirely.
    """
    claim = claim_under_review(amount)

    response = adjuster_claims.transition(claim.id, ClaimAction.APPROVE)

    response.expect_status(403)
    assert "approval limit" in response.detail().lower()

    unchanged = adjuster_claims.get(claim.id).expect_status(200).model(ClaimModel)
    assert unchanged.status is ClaimStatus.UNDER_REVIEW
    assert unchanged.decided_by_id is None


@pytest.mark.boundary
def test_an_administrator_may_approve_above_the_adjuster_limit(
    admin_claims: ClaimsApi, claim_under_review: ClaimUnderReviewFactory
) -> None:
    """API-AUTHZ-006 — the escalation path exists and works.

    Without this, the previous test would be satisfied by an API that refuses
    large approvals to everybody, which is a different product entirely.
    """
    claim = claim_under_review(str(ADJUSTER_APPROVAL_LIMIT + Decimal("0.01")))

    approved = (
        admin_claims.transition(claim.id, ClaimAction.APPROVE).expect_status(200).model(ClaimModel)
    )

    assert approved.status is ClaimStatus.APPROVED


def test_a_customer_cannot_approve_their_own_claim(
    customer_claims: ClaimsApi, claim_under_review: ClaimUnderReviewFactory
) -> None:
    """API-AUTHZ-002 — self-approval would be the most obvious fraud path there is."""
    claim = claim_under_review("100.00")

    response = customer_claims.transition(claim.id, ClaimAction.APPROVE)

    response.expect_status(403)
    assert customer_claims.get(claim.id).model(ClaimModel).status is ClaimStatus.UNDER_REVIEW
