"""UI-WORKFLOW and UI-AUTHZ — acting on a claim, and who may act.

Matrix: UI-CLM-007 … UI-CLM-011, UI-AUTHZ-001 … UI-AUTHZ-003.

The most valuable test in this file is the last one: the interface **offers** an
adjuster the Approve button on a claim above their approval limit, and the server
refuses it. That is deliberate design, and testing it is the difference between
checking a screen and checking a system.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from playwright.sync_api import Page, expect

from claimdesk_qa.api import ClaimsApi
from claimdesk_qa.config import Settings
from claimdesk_qa.data import ClaimFactory
from claimdesk_qa.data.seeded import SeededAccounts
from claimdesk_qa.domain import ADJUSTER_APPROVAL_LIMIT, ClaimAction, ClaimStatus
from claimdesk_qa.ui import AdminUsersPage, ClaimDetailPage, ClaimsListPage

# --------------------------------------------------------------------------- #
# acting on a claim
# --------------------------------------------------------------------------- #


@pytest.mark.smoke
def test_a_customer_can_submit_their_draft(
    customer_page: Page,
    settings: Settings,
    customer_claims: ClaimsApi,
    claim_factory: ClaimFactory,
) -> None:
    """UI-CLM-007 — an action taken in the browser changes real state."""
    claim = customer_claims.create_claim(claim_factory.payload(amount="640.00"))

    detail = ClaimDetailPage(customer_page, settings, str(claim.id)).open().expect_loaded()
    detail.expect_status(ClaimStatus.DRAFT.value)
    detail.perform(ClaimAction.SUBMIT.value)

    detail.expect_status(ClaimStatus.SUBMITTED.value)
    expect(detail.success_toast).to_be_visible()


def test_an_adjuster_can_review_and_approve(
    adjuster_page: Page,
    settings: Settings,
    customer_claims: ClaimsApi,
    adjuster_claims: ClaimsApi,
    claim_factory: ClaimFactory,
) -> None:
    """UI-CLM-008 — the staff half of the workflow.

    Arranged to SUBMITTED through the API; the review and approval steps are the
    part under test and are done in the browser.
    """
    claim = customer_claims.create_claim(claim_factory.payload(amount="820.00"))
    customer_claims.drive_to(claim.id, ClaimStatus.SUBMITTED, staff=adjuster_claims)

    detail = ClaimDetailPage(adjuster_page, settings, str(claim.id)).open().expect_loaded()
    detail.perform(ClaimAction.START_REVIEW.value)
    detail.expect_status(ClaimStatus.UNDER_REVIEW.value)

    detail.perform(ClaimAction.APPROVE.value)
    detail.expect_status(ClaimStatus.APPROVED.value)


def test_the_audit_trail_is_visible_and_complete(
    adjuster_page: Page,
    settings: Settings,
    customer_claims: ClaimsApi,
    adjuster_claims: ClaimsApi,
    claim_factory: ClaimFactory,
) -> None:
    """UI-CLM-009 — the history a compliance reviewer would actually read."""
    claim = customer_claims.create_claim(claim_factory.payload(amount="410.00"))
    customer_claims.drive_to(claim.id, ClaimStatus.PAID, staff=adjuster_claims)

    detail = ClaimDetailPage(adjuster_page, settings, str(claim.id)).open().expect_loaded()

    assert detail.event_statuses() == [
        ClaimStatus.DRAFT.value,
        ClaimStatus.SUBMITTED.value,
        ClaimStatus.UNDER_REVIEW.value,
        ClaimStatus.APPROVED.value,
        ClaimStatus.PAID.value,
    ]


def test_a_settled_claim_offers_no_further_actions(
    adjuster_page: Page,
    settings: Settings,
    customer_claims: ClaimsApi,
    adjuster_claims: ClaimsApi,
    claim_factory: ClaimFactory,
) -> None:
    """UI-CLM-010 — a terminal state must look terminal.

    Offering a button that can only fail is a defect in its own right: the user
    tries it, gets an error, and loses confidence in everything else on the page.
    """
    claim = customer_claims.create_claim(claim_factory.payload(amount="410.00"))
    customer_claims.drive_to(claim.id, ClaimStatus.PAID, staff=adjuster_claims)

    detail = ClaimDetailPage(adjuster_page, settings, str(claim.id)).open().expect_loaded()

    for action in ClaimAction:
        detail.expect_action_unavailable(action.value)
    expect(detail.payout).to_be_visible()


@pytest.mark.boundary
@pytest.mark.authz
def test_the_approve_button_is_offered_but_the_server_refuses_over_the_limit(
    adjuster_page: Page,
    settings: Settings,
    customer_claims: ClaimsApi,
    adjuster_claims: ClaimsApi,
    claim_factory: ClaimFactory,
) -> None:
    """UI-CLM-011 — the most interesting test in the browser suite.

    The button is offered on purpose. Buttons are rendered from the claim's
    *status* and the caller's *role*; the approval limit is enforced when the
    action is taken. Hiding the button instead would move authorisation into a
    template — where it is unenforceable, untestable through the interface, and
    trivially bypassed by anyone who can issue an HTTP request.

    So the test asserts all three things that matter: the button is there, the
    attempt is refused with a message the user can act on, and **the claim did not
    move**. Only the third one catches a refusal that changed state anyway.
    """
    over_limit = ADJUSTER_APPROVAL_LIMIT + Decimal("0.01")
    claim = customer_claims.create_claim(claim_factory.payload(amount=str(over_limit)))
    customer_claims.drive_to(claim.id, ClaimStatus.UNDER_REVIEW, staff=adjuster_claims)

    detail = ClaimDetailPage(adjuster_page, settings, str(claim.id)).open().expect_loaded()
    detail.expect_action_available(ClaimAction.APPROVE.value)

    detail.perform(ClaimAction.APPROVE.value)

    expect(detail.error_toast).to_be_visible()
    expect(detail.error_toast).to_contain_text("approval limit")
    detail.expect_status(ClaimStatus.UNDER_REVIEW.value)


# --------------------------------------------------------------------------- #
# authorisation through the interface
# --------------------------------------------------------------------------- #


@pytest.mark.authz
def test_a_customer_never_sees_another_customers_claim(
    other_customer_page: Page,
    settings: Settings,
    customer_claims: ClaimsApi,
    claim_factory: ClaimFactory,
) -> None:
    """UI-AUTHZ-001 — checked in the table, where a scoping bug would show first."""
    claim = customer_claims.create_claim(claim_factory.payload())

    claims = ClaimsListPage(other_customer_page, settings).open().expect_loaded()
    claims.search_for(claim.reference)

    claims.expect_does_not_contain(claim.reference)
    expect(claims.empty_state).to_be_visible()


@pytest.mark.authz
def test_a_customer_cannot_reach_the_admin_area_by_typing_the_url(
    customer_page: Page, settings: Settings
) -> None:
    """UI-AUTHZ-002 — the check that matters.

    The admin link is hidden from customers, and the next test asserts that. But
    hiding a link is **presentation, not authorisation**: anyone can type a URL.
    This navigates straight to the route and requires the server to refuse it.
    """
    admin = AdminUsersPage(customer_page, settings).open()

    admin.expect_forbidden()
    expect(admin.rows).to_have_count(0)


@pytest.mark.authz
def test_the_admin_link_is_hidden_from_a_customer_and_shown_to_an_administrator(
    customer_page: Page, admin_page: Page, settings: Settings
) -> None:
    """UI-AUTHZ-003 — presentation, asserted in both directions.

    The negative alone would be satisfied by a navigation bar that renders no
    links at all, so the positive case is asserted in the same test.
    """
    customer_dashboard = ClaimsListPage(customer_page, settings).open().expect_loaded()
    expect(customer_dashboard.navigation.admin_link).to_have_count(0)

    admin_dashboard = ClaimsListPage(admin_page, settings).open().expect_loaded()
    expect(admin_dashboard.navigation.admin_link).to_be_visible()


@pytest.mark.authz
def test_an_administrator_can_see_the_user_list(admin_page: Page, settings: Settings) -> None:
    admin = AdminUsersPage(admin_page, settings).open().expect_loaded()

    admin.expect_lists_user(SeededAccounts.CUSTOMER)
    admin.expect_lists_user(SeededAccounts.ADJUSTER)
