"""UI-FORM — the new-claim form.

Matrix: UI-FORM-001 … UI-FORM-006.

The form is rendered with ``novalidate``, so the **server's** validation stays
reachable from the browser. That is deliberate: browser-native validation is a
convenience for the user, not a security control, and a suite that only exercises
it would pass against a server that accepted anything at all.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
from playwright.sync_api import Page, expect

from claimdesk_qa.config import Settings
from claimdesk_qa.data import ClaimFactory
from claimdesk_qa.data.seeded import SeededPolicies
from claimdesk_qa.domain import DESCRIPTION_MIN_LENGTH, ClaimStatus
from claimdesk_qa.ui import ClaimDetailPage, ClaimFormPage


@pytest.fixture
def form(customer_page: Page, settings: Settings) -> ClaimFormPage:
    return ClaimFormPage(customer_page, settings).open().expect_loaded()


@pytest.mark.smoke
def test_submitting_a_valid_claim_creates_it(
    form: ClaimFormPage, customer_page: Page, settings: Settings, ui_claim_factory: ClaimFactory
) -> None:
    """UI-FORM-001 — the full create journey through the interface.

    This is one of the few tests that genuinely *needs* a browser: it proves a
    person can complete the workflow, which no API test can tell you.
    """
    description = ui_claim_factory.description()

    form.fill_in(
        amount="1234.56",
        description=description,
        incident_date=ui_claim_factory.recent_date().isoformat(),
    ).submit()

    detail = ClaimDetailPage(customer_page, settings)
    detail.expect_loaded()
    detail.expect_status(ClaimStatus.DRAFT.value)
    expect(detail.amount).to_have_text("1234.56")
    expect(detail.description).to_have_text(description)


@pytest.mark.negative
@pytest.mark.parametrize(
    ("amount", "fragment"),
    [
        pytest.param("0", "greater than zero", id="zero"),
        pytest.param("-10", "greater than zero", id="negative"),
        pytest.param("abc", "must be a number", id="not-a-number"),
    ],
)
def test_invalid_amounts_are_rejected_with_a_visible_message(
    form: ClaimFormPage, ui_claim_factory: ClaimFactory, amount: str, fragment: str
) -> None:
    """UI-FORM-002.

    Asserts the message is *visible*, not merely present in the DOM. An error
    rendered inside a collapsed container is invisible to the user and therefore
    does not exist as far as the product is concerned.
    """
    form.fill_in(
        amount=amount,
        description=ui_claim_factory.description(),
        incident_date=ui_claim_factory.recent_date().isoformat(),
    ).submit()

    form.expect_error_containing(fragment)
    form.expect_still_on_form()


@pytest.mark.negative
@pytest.mark.boundary
def test_a_description_below_the_minimum_length_is_rejected(
    form: ClaimFormPage, ui_claim_factory: ClaimFactory
) -> None:
    """UI-FORM-003 — the outside edge of the length rule."""
    form.fill_in(
        amount="100.00",
        description="x" * (DESCRIPTION_MIN_LENGTH - 1),
        incident_date=ui_claim_factory.recent_date().isoformat(),
    ).submit()

    form.expect_error_containing("Description must be between")


@pytest.mark.negative
def test_a_future_incident_date_is_rejected(
    form: ClaimFormPage, ui_claim_factory: ClaimFactory
) -> None:
    """UI-FORM-004. A claim cannot be filed for an incident that has not happened."""
    tomorrow = (date.today() + timedelta(days=1)).isoformat()

    form.fill_in(
        amount="100.00",
        description=ui_claim_factory.description(),
        incident_date=tomorrow,
    ).submit()

    form.expect_error_containing("cannot be in the future")


@pytest.mark.negative
@pytest.mark.boundary
def test_an_amount_over_the_policy_coverage_limit_is_rejected(
    form: ClaimFormPage, ui_claim_factory: ClaimFactory
) -> None:
    """UI-FORM-005 — a business rule surfaced in the interface.

    Uses the 2 500.00 policy and exceeds it by one cent, so the failure can only
    be the coverage limit and not the adjuster approval limit, which sits higher.
    """
    over_limit = Decimal("2500.00") + Decimal("0.01")

    form.fill_in(
        amount=str(over_limit),
        description=ui_claim_factory.description(),
        incident_date=ui_claim_factory.recent_date().isoformat(),
        policy_number=None,
    )
    form.policy_select.select_option(index=1)  # POL-1002, the low-coverage policy
    form.submit()

    form.expect_error_containing("exceeds the policy coverage limit")


def test_a_rejected_submission_keeps_what_the_user_typed(
    form: ClaimFormPage, ui_claim_factory: ClaimFactory
) -> None:
    """UI-FORM-006 — small, and the difference between usable and infuriating.

    Losing a 400-character description because the amount had a typo is the kind
    of defect users complain about loudly and test suites rarely check.
    """
    description = ui_claim_factory.description()

    form.fill_in(
        amount="not-a-number",
        description=description,
        incident_date=ui_claim_factory.recent_date().isoformat(),
    ).submit()

    form.expect_error_containing("must be a number")
    expect(form.description_field).to_have_value(description)


def test_the_form_only_offers_policies_the_customer_holds(
    form: ClaimFormPage,
) -> None:
    """Authorisation expressed as an interface constraint.

    The customer holds POL-1001 and POL-1002; POL-2001 belongs to somebody else
    and must not be selectable. The server enforces this too — the browser check
    proves a user cannot even be led into the mistake.
    """
    options = form.policy_select.locator("option").all_inner_texts()

    assert any(SeededPolicies.CUSTOMER_HIGH_COVERAGE in option for option in options)
    assert any(SeededPolicies.CUSTOMER_LOW_COVERAGE in option for option in options)
    assert not any(SeededPolicies.OTHER_CUSTOMER in option for option in options)
