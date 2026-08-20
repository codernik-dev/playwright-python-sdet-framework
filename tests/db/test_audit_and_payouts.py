"""DB-AUDIT and DB-PAY - the audit trail and the money.

Matrix: DB-AUDIT-001 ... DB-AUDIT-004, DB-PAY-001 ... DB-PAY-004.

These are the highest-value tests in the repository. An insurer that pays a claim
twice has lost money; an insurer that cannot show who approved what has a
regulatory problem. Neither defect is visible from the API - a duplicate payout
returns a perfectly ordinary response.
"""

from __future__ import annotations

from decimal import Decimal
from itertools import pairwise

import pytest

from claimdesk_qa.api import ClaimsApi
from claimdesk_qa.data import ClaimFactory
from claimdesk_qa.data.seeded import SeededAccounts
from claimdesk_qa.db import ClaimEventQueries, ClaimQueries, PayoutQueries, UserQueries
from claimdesk_qa.domain import ClaimAction, ClaimStatus

pytestmark = pytest.mark.integrity


# --------------------------------------------------------------------------- #
# the audit trail
# --------------------------------------------------------------------------- #


@pytest.mark.smoke
def test_every_transition_writes_exactly_one_audit_row(
    customer_claims: ClaimsApi,
    adjuster_claims: ClaimsApi,
    claim_factory: ClaimFactory,
    events_db: ClaimEventQueries,
) -> None:
    """DB-AUDIT-001.

    Counted, not merely checked for presence. A retry that writes two rows for one
    transition corrupts the history exactly as badly as writing none, and only a
    count can tell the difference.
    """
    claim = customer_claims.create_claim(claim_factory.payload(amount="700.00"))

    customer_claims.drive_to(claim.id, ClaimStatus.PAID, staff=adjuster_claims)

    assert events_db.statuses_for_claim(claim.id) == [
        ClaimStatus.DRAFT.value,
        ClaimStatus.SUBMITTED.value,
        ClaimStatus.UNDER_REVIEW.value,
        ClaimStatus.APPROVED.value,
        ClaimStatus.PAID.value,
    ]
    assert events_db.count_for_claim(claim.id) == 5


def test_the_audit_chain_has_no_gaps(
    customer_claims: ClaimsApi,
    adjuster_claims: ClaimsApi,
    claim_factory: ClaimFactory,
    events_db: ClaimEventQueries,
) -> None:
    """DB-AUDIT-002 - each row's ``from_status`` matches the previous ``to_status``.

    A gap means a state change happened that nobody recorded. Asserting the list
    of statuses alone would not catch it: the endpoints could be right while a
    step in between went unlogged.
    """
    claim = customer_claims.create_claim(claim_factory.payload(amount="700.00"))
    customer_claims.drive_to(claim.id, ClaimStatus.PAID, staff=adjuster_claims)

    events = events_db.for_claim(claim.id)

    assert events[0].from_status is None, "the first event is a creation, from nothing"
    for previous, current in pairwise(events):
        assert current.from_status == previous.to_status, (
            f"gap in the audit chain: {previous.to_status} -> {current.from_status}"
        )


def test_each_audit_row_names_the_actor_who_caused_it(
    customer_claims: ClaimsApi,
    adjuster_claims: ClaimsApi,
    claim_factory: ClaimFactory,
    events_db: ClaimEventQueries,
    users_db: UserQueries,
) -> None:
    """DB-AUDIT-003 - attribution, resolved to real users.

    The customer submits; the adjuster reviews and approves. Recording the wrong
    actor would be worse than recording none - it implicates somebody who did not
    act.
    """
    customer = users_db.by_email(SeededAccounts.CUSTOMER)
    adjuster = users_db.by_email(SeededAccounts.ADJUSTER)
    assert customer is not None
    assert adjuster is not None

    claim = customer_claims.create_claim(claim_factory.payload(amount="700.00"))
    customer_claims.drive_to(claim.id, ClaimStatus.APPROVED, staff=adjuster_claims)

    actors = {event.to_status: event.actor_id for event in events_db.for_claim(claim.id)}

    assert actors[ClaimStatus.DRAFT.value] == customer.id
    assert actors[ClaimStatus.SUBMITTED.value] == customer.id
    assert actors[ClaimStatus.UNDER_REVIEW.value] == adjuster.id
    assert actors[ClaimStatus.APPROVED.value] == adjuster.id


@pytest.mark.negative
def test_a_refused_transition_writes_no_audit_row(
    customer_claims: ClaimsApi,
    adjuster_claims: ClaimsApi,
    claim_factory: ClaimFactory,
    events_db: ClaimEventQueries,
) -> None:
    """DB-AUDIT-004 - an attempt is not a transition.

    Recording refused attempts in the same table would falsify the history: a
    reader could no longer tell what happened from what was merely tried.
    """
    claim = customer_claims.create_claim(claim_factory.payload(amount="700.00"))
    customer_claims.drive_to(claim.id, ClaimStatus.SUBMITTED, staff=adjuster_claims)
    before = events_db.count_for_claim(claim.id)

    adjuster_claims.transition(claim.id, ClaimAction.PAY).expect_status(409)
    customer_claims.transition(claim.id, ClaimAction.APPROVE).expect_status(409)

    assert events_db.count_for_claim(claim.id) == before


# --------------------------------------------------------------------------- #
# payouts
# --------------------------------------------------------------------------- #


@pytest.mark.smoke
def test_paying_a_claim_writes_exactly_one_payout_for_the_right_amount(
    customer_claims: ClaimsApi,
    adjuster_claims: ClaimsApi,
    claim_factory: ClaimFactory,
    payouts_db: PayoutQueries,
    users_db: UserQueries,
) -> None:
    """DB-PAY-001."""
    claim = customer_claims.create_claim(claim_factory.payload(amount="2345.67"))

    customer_claims.drive_to(claim.id, ClaimStatus.PAID, staff=adjuster_claims)

    payout = payouts_db.for_claim(claim.id)
    adjuster = users_db.by_email(SeededAccounts.ADJUSTER)
    assert payout is not None
    assert adjuster is not None
    assert payout.amount == Decimal("2345.67")
    assert payout.paid_by_id == adjuster.id
    assert payouts_db.count_for_claim(claim.id) == 1


@pytest.mark.negative
def test_a_second_payment_attempt_creates_no_second_payout(
    customer_claims: ClaimsApi,
    adjuster_claims: ClaimsApi,
    claim_factory: ClaimFactory,
    payouts_db: PayoutQueries,
) -> None:
    """DB-PAY-002 - the double-payout guard, checked where the money lives.

    The API test proves the second attempt returns ``409``. That is not the same
    statement as "no second row was written": a handler could insert and then fail
    on a later step, returning an error while the money had already been recorded
    twice. Only counting rows settles it.
    """
    claim = customer_claims.create_claim(claim_factory.payload(amount="800.00"))
    customer_claims.drive_to(claim.id, ClaimStatus.PAID, staff=adjuster_claims)

    adjuster_claims.transition(claim.id, ClaimAction.PAY).expect_status(409)
    adjuster_claims.transition(claim.id, ClaimAction.PAY).expect_status(409)

    assert payouts_db.count_for_claim(claim.id) == 1
    assert payouts_db.total_paid_for_claim(claim.id) == Decimal("800.00")


@pytest.mark.negative
def test_an_unpaid_claim_has_no_payout(
    customer_claims: ClaimsApi,
    adjuster_claims: ClaimsApi,
    claim_factory: ClaimFactory,
    payouts_db: PayoutQueries,
) -> None:
    """DB-PAY-003 - approval is not payment.

    A payout row created at approval time would mean money recorded as leaving
    before anyone authorised it to.
    """
    claim = customer_claims.create_claim(claim_factory.payload(amount="800.00"))

    customer_claims.drive_to(claim.id, ClaimStatus.APPROVED, staff=adjuster_claims)

    assert payouts_db.for_claim(claim.id) is None
    assert payouts_db.count_for_claim(claim.id) == 0


@pytest.mark.negative
def test_a_rejected_claim_is_never_paid(
    customer_claims: ClaimsApi,
    adjuster_claims: ClaimsApi,
    claim_factory: ClaimFactory,
    payouts_db: PayoutQueries,
    claims_db: ClaimQueries,
) -> None:
    """DB-PAY-004 - the most expensive defect this suite could catch."""
    claim = customer_claims.create_claim(claim_factory.payload(amount="800.00"))

    customer_claims.drive_to(claim.id, ClaimStatus.REJECTED, staff=adjuster_claims)

    row = claims_db.by_id(claim.id)
    assert row is not None
    assert row.status == ClaimStatus.REJECTED.value
    assert payouts_db.count_for_claim(claim.id) == 0
    assert payouts_db.total_paid_for_claim(claim.id) == Decimal("0")
