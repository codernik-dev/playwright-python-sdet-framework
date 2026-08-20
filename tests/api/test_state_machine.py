"""API-STATE - the claim status machine.

Matrix: API-STATE-001 ... API-STATE-006.

The negative coverage here is **generated from the published transition table**
rather than hand-written. That is the whole design of this file: a hand-written
list of illegal combinations silently fails to cover a status added later, and
nobody notices because the suite still passes. Deriving them means a new status
brings its own negative cases with it.
"""

from __future__ import annotations

from itertools import pairwise

import pytest

from claimdesk_qa.api import ClaimsApi
from claimdesk_qa.api.models import ClaimEventModel, ClaimModel, PayoutModel
from claimdesk_qa.data import ClaimFactory
from claimdesk_qa.domain import (
    LEGAL_TRANSITIONS,
    ClaimAction,
    ClaimStatus,
    Transition,
    illegal_transitions,
)


@pytest.fixture
def staff(adjuster_claims: ClaimsApi) -> ClaimsApi:
    """The actor with authority for review, approval, rejection and payment."""
    return adjuster_claims


# --------------------------------------------------------------------------- #
# the happy path
# --------------------------------------------------------------------------- #


@pytest.mark.smoke
def test_a_claim_can_travel_the_full_lifecycle(
    customer_claims: ClaimsApi, staff: ClaimsApi, claim_factory: ClaimFactory
) -> None:
    """API-STATE-002 - DRAFT through to PAID, one step at a time."""
    claim = customer_claims.create_claim(claim_factory.payload(amount="750.00"))
    assert claim.status is ClaimStatus.DRAFT

    expected = [
        (ClaimAction.SUBMIT, ClaimStatus.SUBMITTED, customer_claims),
        (ClaimAction.START_REVIEW, ClaimStatus.UNDER_REVIEW, staff),
        (ClaimAction.APPROVE, ClaimStatus.APPROVED, staff),
        (ClaimAction.PAY, ClaimStatus.PAID, staff),
    ]
    for action, target, actor in expected:
        result = actor.transition(claim.id, action).expect_status(200).model(ClaimModel)
        assert result.status is target, f"{action} should have produced {target}"


@pytest.mark.parametrize(
    "transition",
    LEGAL_TRANSITIONS,
    ids=lambda t: f"{t.source.value}-{t.action.value}-{t.target.value}",
)
def test_every_published_transition_is_accepted(
    customer_claims: ClaimsApi,
    staff: ClaimsApi,
    claim_factory: ClaimFactory,
    transition: Transition,
) -> None:
    """API-STATE-001 - each documented edge, exercised in isolation.

    Driven from the same table that generates the negative matrix, so the positive
    and negative sets can never drift apart from each other.
    """
    claim = customer_claims.create_claim(claim_factory.payload(amount="100.00"))
    customer_claims.drive_to(claim.id, transition.source, staff=staff)

    actor = customer_claims if transition.action is ClaimAction.SUBMIT else staff
    result = actor.transition(claim.id, transition.action).expect_status(200).model(ClaimModel)

    assert result.status is transition.target


# --------------------------------------------------------------------------- #
# the generated negative matrix
# --------------------------------------------------------------------------- #

_REACHABLE = [
    (action, status)
    for action, status in illegal_transitions()
    # WITHDRAWN is reached by DELETE rather than by a transition, so it is covered
    # separately below; the rest are reachable through the workflow.
    if status is not ClaimStatus.WITHDRAWN
]


@pytest.mark.negative
@pytest.mark.parametrize(
    ("action", "status"),
    _REACHABLE,
    ids=[f"{status.value}-cannot-{action.value}" for action, status in _REACHABLE],
)
def test_illegal_transitions_are_refused(
    customer_claims: ClaimsApi,
    staff: ClaimsApi,
    claim_factory: ClaimFactory,
    action: ClaimAction,
    status: ClaimStatus,
) -> None:
    """API-STATE-005 - every combination that is not a published edge.

    Uses the administrator-capable actor so a refusal can only be about the
    claim's *state*, never about the caller's role. Role restrictions are proved
    separately in test_authorization.py; mixing the two would make a failure here
    ambiguous.
    """
    claim = customer_claims.create_claim(claim_factory.payload(amount="100.00"))
    customer_claims.drive_to(claim.id, status, staff=staff)

    response = staff.transition(claim.id, action)

    response.expect_status(409)
    assert staff.get(claim.id).model(ClaimModel).status is status, "a refusal must not change state"


@pytest.mark.negative
@pytest.mark.parametrize("action", list(ClaimAction))
def test_a_withdrawn_claim_accepts_no_transition(
    customer_claims: ClaimsApi, claim_factory: ClaimFactory, action: ClaimAction
) -> None:
    """WITHDRAWN is terminal - reached by DELETE, and a dead end thereafter."""
    claim = customer_claims.create_claim(claim_factory.payload())
    customer_claims.withdraw(claim.id).expect_status(204)

    customer_claims.transition(claim.id, action).expect_status(409)


@pytest.mark.negative
def test_an_unknown_action_is_rejected(
    customer_claims: ClaimsApi, claim_factory: ClaimFactory
) -> None:
    """The action field is an enum, not free text."""
    claim = customer_claims.create_claim(claim_factory.payload())

    customer_claims.transition(claim.id, "teleport").expect_status(422)


# --------------------------------------------------------------------------- #
# terminal states are immutable
# --------------------------------------------------------------------------- #


@pytest.mark.negative
def test_a_paid_claim_cannot_be_edited(
    customer_claims: ClaimsApi, staff: ClaimsApi, claim_factory: ClaimFactory
) -> None:
    """API-STATE-006. Editing a settled claim would desynchronise it from its payout."""
    claim = customer_claims.create_claim(claim_factory.payload(amount="300.00"))
    customer_claims.drive_to(claim.id, ClaimStatus.PAID, staff=staff)

    customer_claims.update(claim.id, {"description": "changed after payment"}).expect_status(409)
    customer_claims.update(claim.id, {"amount": "1.00"}).expect_status(409)

    unchanged = customer_claims.get(claim.id).expect_status(200).model(ClaimModel)
    assert unchanged.description == claim.description
    assert unchanged.amount == claim.amount


@pytest.mark.negative
def test_a_paid_claim_cannot_be_withdrawn(
    customer_claims: ClaimsApi, staff: ClaimsApi, claim_factory: ClaimFactory
) -> None:
    claim = customer_claims.create_claim(claim_factory.payload(amount="300.00"))
    customer_claims.drive_to(claim.id, ClaimStatus.PAID, staff=staff)

    customer_claims.withdraw(claim.id).expect_status(409)


@pytest.mark.negative
def test_paying_the_same_claim_twice_is_refused(
    customer_claims: ClaimsApi, staff: ClaimsApi, claim_factory: ClaimFactory
) -> None:
    """API-STATE-004 - the double-payout guard, the highest-value check here.

    Paying twice is the classic financial defect: money leaves the business
    twice for one claim. The storage layer also refuses it via a unique
    constraint; this proves the API surfaces that as a clean conflict rather than
    a 500, and DB-CLM-003 proves only one payout row exists.
    """
    claim = customer_claims.create_claim(claim_factory.payload(amount="300.00"))
    customer_claims.drive_to(claim.id, ClaimStatus.PAID, staff=staff)

    staff.transition(claim.id, ClaimAction.PAY).expect_status(409)

    payout = staff.payout(claim.id).expect_status(200).model(PayoutModel)
    assert payout.amount == claim.amount


# --------------------------------------------------------------------------- #
# the audit trail
# --------------------------------------------------------------------------- #


def test_every_transition_appends_exactly_one_audit_event(
    customer_claims: ClaimsApi, staff: ClaimsApi, claim_factory: ClaimFactory
) -> None:
    """API-STATE-002 / the audit half of the contract.

    Counted rather than merely checked for presence: a retry that writes two rows
    for one transition corrupts the trail just as badly as writing none, and only
    a count catches it.
    """
    claim = customer_claims.create_claim(claim_factory.payload(amount="300.00"))
    customer_claims.drive_to(claim.id, ClaimStatus.PAID, staff=staff)

    events = [
        ClaimEventModel.model_validate(event)
        for event in customer_claims.events(claim.id).expect_status(200).json()
    ]

    assert [event.to_status for event in events] == [
        ClaimStatus.DRAFT,
        ClaimStatus.SUBMITTED,
        ClaimStatus.UNDER_REVIEW,
        ClaimStatus.APPROVED,
        ClaimStatus.PAID,
    ]
    # Each row's from_status must equal the previous row's to_status: a chain with
    # a gap means a state change happened that nobody recorded.
    # pairwise, not zip(events, events[1:], strict=True) - offset slices always
    # differ in length by one, so strict=True raises every time. That mistake cost
    # a debugging round here.
    for previous, current in pairwise(events):
        assert current.from_status is previous.to_status


def test_a_refused_transition_writes_no_audit_event(
    customer_claims: ClaimsApi, staff: ClaimsApi, claim_factory: ClaimFactory
) -> None:
    """An attempt is not a transition. Recording one would falsify the history."""
    claim = customer_claims.create_claim(claim_factory.payload(amount="300.00"))
    customer_claims.drive_to(claim.id, ClaimStatus.SUBMITTED, staff=staff)
    before = len(customer_claims.events(claim.id).expect_status(200).json())

    staff.transition(claim.id, ClaimAction.PAY).expect_status(409)

    after = len(customer_claims.events(claim.id).expect_status(200).json())
    assert after == before


def test_the_approving_actor_is_recorded_on_the_claim(
    customer_claims: ClaimsApi, staff: ClaimsApi, claim_factory: ClaimFactory
) -> None:
    """Who decided is as auditable as what was decided."""
    claim = customer_claims.create_claim(claim_factory.payload(amount="300.00"))

    approved = customer_claims.drive_to(claim.id, ClaimStatus.APPROVED, staff=staff)

    assert approved.decided_by_id is not None
