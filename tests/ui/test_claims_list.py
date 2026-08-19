"""UI-CLM — the claims table: filtering, searching and sorting.

Matrix: UI-CLM-001 … UI-CLM-006.

Every test here arranges its data **through the API** and then asserts on the
browser. That is a scoping decision, not a shortcut: a test about the table should
not be able to fail because the claim *form* broke. It is also about two orders of
magnitude faster than clicking through four screens to create a claim.
"""

from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

from claimdesk_qa.api import ClaimsApi
from claimdesk_qa.config import Settings
from claimdesk_qa.data import ClaimFactory
from claimdesk_qa.data.seeded import SEED_CLAIM_PREFIX
from claimdesk_qa.domain import ClaimStatus
from claimdesk_qa.ui import ClaimsListPage


@pytest.mark.smoke
def test_a_claim_created_through_the_api_appears_in_the_table(
    customer_page: Page,
    settings: Settings,
    customer_api: ClaimsApi,
    ui_claim_factory: ClaimFactory,
) -> None:
    """UI-CLM-001 — the read path, end to end.

    Searching for the claim's own reference rather than scanning the whole table:
    the table holds the seeded corpus plus whatever other workers are creating at
    this moment, so "it is somewhere on the page" is not a safe assertion under
    parallel execution.
    """
    claim = customer_api.create_claim(ui_claim_factory.payload(amount="432.10"))

    claims = ClaimsListPage(customer_page, settings).open().expect_loaded()
    claims.search_for(claim.reference)

    claims.expect_contains(claim.reference)
    expect(claims.row_for(claim.reference)).to_contain_text("432.10")


@pytest.mark.smoke
def test_searching_narrows_the_table_to_one_claim(
    customer_page: Page,
    settings: Settings,
    customer_api: ClaimsApi,
    ui_claim_factory: ClaimFactory,
) -> None:
    """UI-CLM-002 — asynchronous filtering, with no sleep anywhere.

    The page fetches a partial and swaps it in. The page object waits on
    ``aria-busy`` flipping back to ``false`` — a state the application publishes,
    not a duration someone guessed.
    """
    description = ui_claim_factory.description()
    marker = description.split()[1]
    claim = customer_api.create_claim(ui_claim_factory.payload(description=description))

    claims = ClaimsListPage(customer_page, settings).open().expect_loaded()
    claims.search_for(marker)

    claims.expect_result_count(1)
    claims.expect_contains(claim.reference)


def test_a_search_matching_nothing_shows_the_empty_state(
    customer_page: Page, settings: Settings
) -> None:
    """UI-CLM-003. An empty result must be *explained*, not just blank.

    A blank table is indistinguishable from a broken one. The empty state is what
    tells a user their filter matched nothing rather than the page having failed.
    """
    claims = ClaimsListPage(customer_page, settings).open().expect_loaded()

    claims.search_for("no-claim-will-ever-contain-this-string")

    expect(claims.empty_state).to_be_visible()
    claims.expect_result_count(0)


def test_filtering_by_status_shows_only_that_status(
    customer_page: Page, settings: Settings
) -> None:
    """UI-CLM-004 — every visible chip must match the selected filter."""
    claims = ClaimsListPage(customer_page, settings).open().expect_loaded()

    claims.filter_by_status(ClaimStatus.PAID.value)

    chips = claims.status_chips()
    assert chips, "the seeded corpus should contain paid claims"
    assert set(chips) == {ClaimStatus.PAID.value}


def test_a_new_claim_is_absent_from_a_non_matching_status_filter(
    customer_page: Page,
    settings: Settings,
    customer_api: ClaimsApi,
    ui_claim_factory: ClaimFactory,
) -> None:
    """The negative half of filtering, which most suites skip.

    Proving a filter *shows* matching rows says nothing about whether it *hides*
    the rest. This creates a DRAFT claim and asserts it does not appear under PAID.
    """
    claim = customer_api.create_claim(ui_claim_factory.payload())

    claims = ClaimsListPage(customer_page, settings).open().expect_loaded()
    claims.filter_by_status(ClaimStatus.PAID.value)

    claims.expect_does_not_contain(claim.reference)


def test_sorting_by_amount_orders_the_visible_rows(customer_page: Page, settings: Settings) -> None:
    """UI-CLM-005.

    The rendered values are read back and compared against their own sorted order,
    rather than spot-checking the first and last row — a spot check passes happily
    on a list that is wrong in the middle.
    """
    claims = ClaimsListPage(customer_page, settings).open().expect_loaded()

    claims.page.get_by_test_id("sort-amount").click()
    claims.expect_loaded()

    amounts = [float(value.replace(",", "")) for value in claims.amount_cells()]
    assert amounts == sorted(amounts)


def test_the_table_paginates(customer_page: Page, settings: Settings) -> None:
    """UI-CLM-006 — page two holds different claims from page one.

    **Scoped to the seeded corpus on purpose, and this test taught me why.**

    The first version paginated the unfiltered table, which is sorted newest-first.
    Under ``-n 4`` it failed roughly half the time: other workers create claims
    between the page-one and page-two requests, every row shifts down by one, and a
    claim seen at the bottom of page one reappears at the top of page two. The
    assertion was correct; the *premise* was wrong. You cannot paginate a data set
    that is being written to and expect stable page boundaries.

    Filtering to ``CLM-SEED`` fixes it properly rather than papering over it: the
    seeded corpus is 24 claims that no test mutates and no worker adds to, so the
    pages are deterministic no matter what else is running.
    """
    claims = ClaimsListPage(customer_page, settings).open().expect_loaded()
    claims.search_for(SEED_CLAIM_PREFIX)
    first_page = set(claims.page.get_by_test_id("claim-link").all_inner_texts())

    claims.page.get_by_test_id("next-page").click()
    claims.expect_loaded()

    second_page = set(claims.page.get_by_test_id("claim-link").all_inner_texts())

    assert first_page, "page one should not be empty"
    assert second_page, "page two should not be empty"
    assert not first_page & second_page, "the same claim appeared on both pages"


def test_opening_a_claim_from_the_table_navigates_to_its_detail_page(
    customer_page: Page,
    settings: Settings,
    customer_api: ClaimsApi,
    ui_claim_factory: ClaimFactory,
) -> None:
    """The link between two pages — the thing a UI test is uniquely able to prove."""
    claim = customer_api.create_claim(ui_claim_factory.payload())

    claims = ClaimsListPage(customer_page, settings).open().expect_loaded()
    claims.search_for(claim.reference)
    claims.open_claim(claim.reference)

    expect(customer_page).to_have_url(f"{settings.base_url}/claims/{claim.id}")
    expect(customer_page.get_by_test_id("page-title")).to_contain_text(claim.reference)
