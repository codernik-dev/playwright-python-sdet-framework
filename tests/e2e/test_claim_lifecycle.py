"""E2E — journeys that cross the browser, the API and the database.

Matrix: E2E-001 … E2E-004.

These are the fewest tests in the suite and the most expensive, which is exactly
right. An end-to-end test earns its cost only when the thing it proves cannot be
proved anywhere else: that the three layers **agree**.

A UI test can show a page said `PAID`. An API test can show the endpoint returned
`PAID`. Only a journey can show that what the user saw in the browser is what the
API reports and what the ledger actually recorded — and that is precisely where
real systems come apart.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from playwright.sync_api import Page, expect
from tests._fixtures.browser import ContextFactory

from claimdesk_qa.api import ClaimsApi, UsersApi
from claimdesk_qa.api.models import ClaimModel
from claimdesk_qa.config import Settings
from claimdesk_qa.data import ClaimFactory, UserFactory
from claimdesk_qa.data.seeded import SeededAccounts
from claimdesk_qa.db import ClaimEventQueries, ClaimQueries, PayoutQueries, UserQueries
from claimdesk_qa.domain import ClaimAction, ClaimStatus
from claimdesk_qa.ui import ClaimDetailPage, ClaimFormPage, ClaimsListPage


@pytest.mark.smoke
def test_a_claim_filed_in_the_browser_is_visible_to_the_api_and_the_database(
    customer_page: Page,
    settings: Settings,
    customer_claims: ClaimsApi,
    claim_factory: ClaimFactory,
    claims_db: ClaimQueries,
    events_db: ClaimEventQueries,
) -> None:
    """E2E-001 — one action, three independent confirmations.

    The browser is the *only* thing that acts here. The API and the database are
    then asked, independently, what happened. If any layer disagreed — a value
    displayed but not sent, sent but not stored, stored under a different
    reference — this is the test that would catch it.
    """
    description = claim_factory.description()

    form = ClaimFormPage(customer_page, settings).open().expect_loaded()
    form.fill_in(
        amount="3456.78",
        description=description,
        incident_date=claim_factory.recent_date().isoformat(),
    ).submit()

    detail = ClaimDetailPage(customer_page, settings)
    detail.expect_loaded().expect_status(ClaimStatus.DRAFT.value)
    reference = detail.page.get_by_test_id("page-title").inner_text().replace("Claim ", "").strip()

    # ... the API agrees
    page = customer_claims.list(q=reference).expect_status(200).json()
    assert page["total"] == 1, f"the API cannot find {reference}"
    from_api = ClaimModel.model_validate(page["items"][0])
    assert from_api.amount == Decimal("3456.78")
    assert from_api.description == description

    # ... and so does the database
    row = claims_db.by_reference(reference)
    assert row is not None, "the browser showed a claim the database does not have"
    assert row.id == from_api.id
    assert row.amount == Decimal("3456.78")
    assert events_db.statuses_for_claim(row.id) == [ClaimStatus.DRAFT.value]


def test_a_claim_approved_in_the_browser_is_paid_correctly_in_the_ledger(
    adjuster_page: Page,
    settings: Settings,
    customer_claims: ClaimsApi,
    adjuster_claims: ClaimsApi,
    claim_factory: ClaimFactory,
    claims_db: ClaimQueries,
    events_db: ClaimEventQueries,
    payouts_db: PayoutQueries,
    users_db: UserQueries,
) -> None:
    """E2E-002 — the money journey, from a click to the ledger.

    Arranged through the API, decided in the browser, verified in the database.
    That split is the point: the expensive browser interaction covers only the
    step this test is actually about.
    """
    claim = customer_claims.create_claim(claim_factory.payload(amount="1975.25"))
    customer_claims.drive_to(claim.id, ClaimStatus.UNDER_REVIEW, staff=adjuster_claims)

    detail = ClaimDetailPage(adjuster_page, settings, str(claim.id)).open().expect_loaded()
    detail.perform(ClaimAction.APPROVE.value)
    detail.expect_status(ClaimStatus.APPROVED.value)
    detail.perform(ClaimAction.PAY.value)
    detail.expect_status(ClaimStatus.PAID.value)

    adjuster = users_db.by_email(SeededAccounts.ADJUSTER)
    assert adjuster is not None

    row = claims_db.by_id(claim.id)
    assert row is not None
    assert row.status == ClaimStatus.PAID.value
    assert row.decided_by_id == adjuster.id

    assert events_db.statuses_for_claim(claim.id) == [
        ClaimStatus.DRAFT.value,
        ClaimStatus.SUBMITTED.value,
        ClaimStatus.UNDER_REVIEW.value,
        ClaimStatus.APPROVED.value,
        ClaimStatus.PAID.value,
    ]

    payout = payouts_db.for_claim(claim.id)
    assert payout is not None
    assert payout.amount == Decimal("1975.25"), "the ledger must match the approved amount"
    assert payouts_db.count_for_claim(claim.id) == 1
    assert payout.paid_by_id == adjuster.id


@pytest.mark.authz
def test_deactivating_a_user_immediately_ends_their_browser_session(
    settings: Settings,
    admin_users: UsersApi,
    users_db: UserQueries,
    context_factory: ContextFactory,
) -> None:
    """E2E-003 — an administrative action reaches into a live browser session.

    This is the journey that cannot be tested from one layer at all. An
    administrator deactivates an account through the **API**; a **browser** that
    was already signed in must stop working on its very next request; the
    **database** must show the account inactive.

    It also documents this application's real revocation story honestly. A bearer
    token cannot be withdrawn without server-side state, which ClaimDesk
    deliberately does not keep — so deactivating the user *is* the revocation
    path, and it must therefore work immediately rather than at token expiry.
    """
    from claimdesk_qa.api import ApiClient, AuthApi

    # A brand-new user, so no other test's session is affected.
    payload = UserFactory().payload(password="Passw0rd!e2e-session")
    created = admin_users.create(payload).expect_status(201).json()

    with ApiClient(
        base_url=settings.api_url, timeout_seconds=settings.http_timeout_seconds
    ) as client:
        token = AuthApi(client).token_for(payload["email"], "Passw0rd!e2e-session")

    # NOTE: an earlier version of this test wrote the storage state into
    # `artifacts/`, which CI archives and publishes - putting a live bearer token
    # into a downloadable build artefact. The cookie is now injected straight into
    # the browser context and never touches disk. Caught while reviewing this file,
    # not by a failing test, which is exactly why credential handling deserves a
    # deliberate second look rather than a green tick.
    context = context_factory(None)
    context.add_cookies(  # the session the user already has in their browser
        [
            {
                "name": "session",
                "value": token,
                "domain": "127.0.0.1",
                "path": "/",
                "httpOnly": True,
                "secure": False,
                "sameSite": "Lax",
            }
        ]
    )
    page = context.new_page()
    ClaimsListPage(page, settings).open().expect_loaded()  # signed in, working

    admin_users.set_active(created["id"], active=False).expect_status(200)

    # The very next navigation must be refused, not the one after the token expires.
    page.goto(f"{settings.base_url}/claims")
    expect(page).to_have_url(f"{settings.base_url}/login?next=/claims")

    row = users_db.by_email(payload["email"])
    assert row is not None
    assert row.is_active is False


def test_a_claim_withdrawn_in_the_browser_survives_in_the_database(
    customer_page: Page,
    settings: Settings,
    customer_claims: ClaimsApi,
    claim_factory: ClaimFactory,
    claims_db: ClaimQueries,
    events_db: ClaimEventQueries,
) -> None:
    """E2E-004 — a delete in the interface is a soft delete in storage.

    The browser and the API both stop offering the claim as actionable. Only the
    database can show the row is still there, with its history intact — which is
    what a regulator would ask for, and what a hard delete would have destroyed.
    """
    claim = customer_claims.create_claim(claim_factory.payload(amount="640.00"))

    claims = ClaimsListPage(customer_page, settings).open().expect_loaded()
    claims.search_for(claim.reference)
    claims.expect_contains(claim.reference)

    customer_claims.withdraw(claim.id).expect_status(204)

    detail = ClaimDetailPage(customer_page, settings, str(claim.id)).open().expect_loaded()
    detail.expect_status(ClaimStatus.WITHDRAWN.value)

    row = claims_db.by_id(claim.id)
    assert row is not None, "a withdrawal must not delete the row"
    assert row.withdrawn_at is not None
    assert events_db.statuses_for_claim(claim.id) == [
        ClaimStatus.DRAFT.value,
        ClaimStatus.WITHDRAWN.value,
    ]
