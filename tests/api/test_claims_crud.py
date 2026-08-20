"""API-CLM - claim creation, retrieval, update, withdrawal, search and paging.

Matrix: API-CLM-001 ... API-CLM-009 in docs/phase-1-design.md §8.4.

Every test creates the data it asserts on and identifies it by a unique key, which
is what makes the whole file safe to run in parallel against one shared database.
No test asserts on a global count, and none touches the seeded corpus except to
read it.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from claimdesk_qa.api import ClaimsApi
from claimdesk_qa.api.models import ClaimEventModel, ClaimModel, Page
from claimdesk_qa.data import ClaimFactory
from claimdesk_qa.data.seeded import SEED_CLAIM_PREFIX
from claimdesk_qa.domain import DEFAULT_PAGE_SIZE, ClaimStatus

# --------------------------------------------------------------------------- #
# create and read
# --------------------------------------------------------------------------- #


@pytest.mark.smoke
def test_creating_a_claim_returns_the_full_contract(
    customer_claims: ClaimsApi, claim_factory: ClaimFactory
) -> None:
    """API-CLM-001.

    Validating against ClaimModel checks every documented field's presence, type
    and name in one line - and, because the model forbids extras, fails if an
    undocumented field appears.
    """
    payload = claim_factory.payload(amount="1250.50")

    claim = customer_claims.create(payload).expect_status(201).model(ClaimModel)

    assert claim.status is ClaimStatus.DRAFT
    assert claim.amount == Decimal("1250.50")
    assert claim.description == payload["description"]
    assert claim.reference.startswith("CLM-")
    assert claim.withdrawn_at is None
    assert claim.decided_by_id is None


@pytest.mark.smoke
def test_a_created_claim_can_be_read_back_unchanged(
    customer_claims: ClaimsApi, claim_factory: ClaimFactory
) -> None:
    """API-CLM-002. A write that cannot be read back is not a write."""
    created = customer_claims.create_claim(claim_factory.payload(amount="99.99"))

    fetched = customer_claims.get(created.id).expect_status(200).model(ClaimModel)

    assert fetched == created


def test_each_claim_receives_a_distinct_reference(
    customer_claims: ClaimsApi, claim_factory: ClaimFactory
) -> None:
    """References are user-facing identifiers; a collision is a real incident."""
    references = {customer_claims.create_claim(claim_factory.payload()).reference for _ in range(5)}

    assert len(references) == 5


# --------------------------------------------------------------------------- #
# update and withdraw
# --------------------------------------------------------------------------- #


def test_updating_a_draft_changes_only_the_field_sent(
    customer_claims: ClaimsApi, claim_factory: ClaimFactory
) -> None:
    """API-CLM-008. A PATCH that quietly resets other fields is a classic defect."""
    claim = customer_claims.create_claim(claim_factory.payload(amount="410.00"))

    updated = (
        customer_claims.update(claim.id, {"description": "Updated description for the claim"})
        .expect_status(200)
        .model(ClaimModel)
    )

    assert updated.description == "Updated description for the claim"
    assert updated.amount == claim.amount
    assert updated.status is claim.status
    assert updated.reference == claim.reference


def test_withdrawing_a_draft_moves_it_to_withdrawn_and_keeps_it_visible(
    customer_claims: ClaimsApi, claim_factory: ClaimFactory
) -> None:
    """API-CLM-009 - **specification corrected by this test.**

    The Phase 1 matrix originally specified ``DELETE -> 204, then GET -> 404``.
    The application returns ``200`` with ``status=WITHDRAWN``, and on
    investigation the *specification* was wrong:

    * ``WITHDRAWN`` is a published value of the status enum;
    * the list endpoint returns withdrawn claims and accepts ``?status=WITHDRAWN``.

    A detail endpoint returning 404 for a resource the list endpoint happily
    returns is incoherent, and it would also hide a claim from the customer who
    withdrew it. Withdrawal is a state transition, not a deletion - so the row
    stays, the audit trail records it, and the resource stays readable.

    The soft delete itself is proven by DB-CLM-004, because only the database can
    show that the row survived rather than being removed.
    """
    claim = customer_claims.create_claim(claim_factory.payload())

    customer_claims.withdraw(claim.id).expect_status(204)

    withdrawn = customer_claims.get(claim.id).expect_status(200).model(ClaimModel)
    assert withdrawn.status is ClaimStatus.WITHDRAWN
    assert withdrawn.withdrawn_at is not None
    assert withdrawn.reference == claim.reference


def test_withdrawal_is_recorded_in_the_audit_trail(
    customer_claims: ClaimsApi, claim_factory: ClaimFactory
) -> None:
    """A state change that leaves no audit row is invisible to compliance."""
    claim = customer_claims.create_claim(claim_factory.payload())

    customer_claims.withdraw(claim.id).expect_status(204)

    events = [
        ClaimEventModel.model_validate(event)
        for event in customer_claims.events(claim.id).expect_status(200).json()
    ]
    assert [event.to_status for event in events] == [
        ClaimStatus.DRAFT,
        ClaimStatus.WITHDRAWN,
    ]
    assert events[-1].from_status is ClaimStatus.DRAFT


# --------------------------------------------------------------------------- #
# audit trail
# --------------------------------------------------------------------------- #


def test_creating_a_claim_records_its_first_audit_event(
    customer_claims: ClaimsApi, claim_factory: ClaimFactory
) -> None:
    claim = customer_claims.create_claim(claim_factory.payload())

    events = customer_claims.events(claim.id).expect_status(200).json()
    parsed = [ClaimEventModel.model_validate(event) for event in events]

    assert len(parsed) == 1
    assert parsed[0].from_status is None
    assert parsed[0].to_status is ClaimStatus.DRAFT
    assert parsed[0].claim_id == claim.id


# --------------------------------------------------------------------------- #
# listing, filtering, sorting, paging
# --------------------------------------------------------------------------- #


@pytest.mark.smoke
def test_listing_claims_returns_a_page_with_metadata(customer_claims: ClaimsApi) -> None:
    """API-CLM-003."""
    page = customer_claims.list(size=5).expect_status(200).model(Page[ClaimModel])

    assert len(page.items) == 5
    assert page.size == 5
    assert page.page == 1
    assert page.total >= 5


def test_the_default_page_size_matches_the_published_contract(
    customer_claims: ClaimsApi,
) -> None:
    page = customer_claims.list().expect_status(200).model(Page[ClaimModel])

    assert page.size == DEFAULT_PAGE_SIZE
    assert len(page.items) <= DEFAULT_PAGE_SIZE


def test_paging_returns_different_claims_on_each_page(customer_claims: ClaimsApi) -> None:
    """API-CLM-003.

    Scoped to the seeded corpus, which no test mutates and no worker adds to.

    Sorting by a stable key is necessary but **not sufficient**: references are
    random, so a claim another worker creates can insert anywhere in the ordering
    and shift the page boundary. Only an isolated data set makes page contents
    deterministic under parallel execution. The browser version of this test
    failed ~50% of the time at `-n 4` before this was understood.
    """
    first = customer_claims.list(
        size=5, page=1, sort="reference", q=SEED_CLAIM_PREFIX
    ).expect_status(200)
    second = customer_claims.list(
        size=5, page=2, sort="reference", q=SEED_CLAIM_PREFIX
    ).expect_status(200)

    first_ids = {item["id"] for item in first.json()["items"]}
    second_ids = {item["id"] for item in second.json()["items"]}

    assert first_ids, "page 1 should not be empty"
    assert second_ids, "page 2 should not be empty"
    assert not first_ids & second_ids, "the same claim appeared on both pages"


@pytest.mark.parametrize("status", list(ClaimStatus))
def test_filtering_by_status_returns_only_that_status(
    customer_claims: ClaimsApi, status: ClaimStatus
) -> None:
    """API-CLM-004, across every status the enum defines.

    Parametrised over the enum rather than a hand-picked list, so a new status
    cannot be added without being covered here.
    """
    page = customer_claims.list(status=status, size=50).expect_status(200).model(Page[ClaimModel])

    assert all(item.status is status for item in page.items)


def test_filtering_by_amount_range_excludes_values_outside_it(
    customer_claims: ClaimsApi,
) -> None:
    """API-CLM-006."""
    page = (
        customer_claims.list(min_amount="1000.00", max_amount="3000.00", size=50)
        .expect_status(200)
        .model(Page[ClaimModel])
    )

    assert page.items, "the seeded corpus should contain claims in this range"
    out_of_range = [
        item.reference
        for item in page.items
        if not Decimal("1000.00") <= item.amount <= Decimal("3000.00")
    ]
    assert out_of_range == []


def test_searching_finds_a_claim_the_test_created_itself(
    customer_claims: ClaimsApi, claim_factory: ClaimFactory
) -> None:
    """API-CLM-005 - and a demonstration of parallel-safe searching.

    The search term is the unique marker embedded in this test's own description,
    so the assertion "exactly one result" holds no matter what other workers are
    creating at the same moment.
    """
    description = claim_factory.description()
    marker = description.split()[1]
    claim = customer_claims.create_claim(claim_factory.payload(description=description))

    page = customer_claims.list(q=marker).expect_status(200).model(Page[ClaimModel])

    assert page.total == 1
    assert page.items[0].id == claim.id


def test_searching_by_reference_finds_exactly_that_claim(
    customer_claims: ClaimsApi, claim_factory: ClaimFactory
) -> None:
    claim = customer_claims.create_claim(claim_factory.payload())

    page = customer_claims.list(q=claim.reference).expect_status(200).model(Page[ClaimModel])

    assert [item.id for item in page.items] == [claim.id]


def test_a_search_matching_nothing_returns_an_empty_page_not_an_error(
    customer_claims: ClaimsApi,
) -> None:
    """An empty result is a valid answer; 404 here would be wrong."""
    page = customer_claims.list(q="no-claim-will-ever-contain-this-string").expect_status(200)

    parsed = page.model(Page[ClaimModel])

    assert parsed.items == []
    assert parsed.total == 0


@pytest.mark.parametrize(
    ("sort", "descending"),
    [
        pytest.param("amount", False, id="amount-ascending"),
        pytest.param("-amount", True, id="amount-descending"),
        pytest.param("incident_date", False, id="incident-date-ascending"),
        pytest.param("-incident_date", True, id="incident-date-descending"),
    ],
)
def test_sorting_orders_the_results(
    customer_claims: ClaimsApi, sort: str, descending: bool
) -> None:
    """API-CLM-007.

    The order is recomputed in Python and compared, rather than spot-checking the
    first and last rows - a spot check passes on a list that is wrong in the
    middle.
    """
    page = customer_claims.list(sort=sort, size=50).expect_status(200).model(Page[ClaimModel])

    field = "amount" if "amount" in sort else "incident_date"
    values = [getattr(item, field) for item in page.items]

    assert values == sorted(values, reverse=descending)


def test_the_seeded_corpus_is_present_for_the_list_tests(customer_claims: ClaimsApi) -> None:
    """Guards the assumption every filter and sort test above depends on.

    If the seed changes, this one obvious test fails instead of a dozen confusing
    ones.
    """
    page = customer_claims.list(q=SEED_CLAIM_PREFIX, size=1).expect_status(200)

    assert page.model(Page[ClaimModel]).total >= 24
