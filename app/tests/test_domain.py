"""Unit tests for the ClaimDesk business rules.

These belong to the APPLICATION, not to the automation framework. They exist for
two reasons:

1. The application is a real application, with its own tests, rather than a stub
   shaped to make the automation look good.
2. They pin the specification that the framework's black-box tests then verify
   from the outside, through HTTP and SQL.

Pure logic, no database, no web server: the whole file runs in milliseconds.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from claimdesk.domain import (
    ADJUSTER_APPROVAL_LIMIT,
    TRANSITIONS,
    ClaimAction,
    ClaimStatus,
    DomainError,
    InsufficientAuthorityError,
    InvalidTransitionError,
    Role,
    can_view_claim,
    resolve_transition,
    validate_claim_amount,
)

SMALL = Decimal("100.00")


def _resolve(
    action: ClaimAction,
    *,
    status: ClaimStatus,
    role: Role,
    is_owner: bool = True,
    amount: Decimal = SMALL,
) -> ClaimStatus:
    return resolve_transition(
        action, current_status=status, actor_role=role, is_owner=is_owner, amount=amount
    )


# --------------------------------------------------------------------------- #
# the happy path through the state machine
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("action", "source", "role", "expected"),
    [
        (ClaimAction.SUBMIT, ClaimStatus.DRAFT, Role.CUSTOMER, ClaimStatus.SUBMITTED),
        (ClaimAction.START_REVIEW, ClaimStatus.SUBMITTED, Role.ADJUSTER, ClaimStatus.UNDER_REVIEW),
        (ClaimAction.APPROVE, ClaimStatus.UNDER_REVIEW, Role.ADJUSTER, ClaimStatus.APPROVED),
        (ClaimAction.REJECT, ClaimStatus.UNDER_REVIEW, Role.ADJUSTER, ClaimStatus.REJECTED),
        (ClaimAction.PAY, ClaimStatus.APPROVED, Role.ADJUSTER, ClaimStatus.PAID),
    ],
)
def test_legal_transitions_reach_the_expected_status(action, source, role, expected) -> None:
    assert _resolve(action, status=source, role=role) is expected


# --------------------------------------------------------------------------- #
# every illegal edge of the machine
# --------------------------------------------------------------------------- #


def _illegal_pairs() -> list[tuple[ClaimAction, ClaimStatus]]:
    """Every (action, status) combination that is not a legal edge.

    Generated rather than hand-listed, so a new status or action cannot be added
    without its negative cases appearing automatically.
    """
    return [
        (action, status)
        for action in ClaimAction
        for status in ClaimStatus
        if TRANSITIONS[action].source is not status
    ]


@pytest.mark.parametrize(("action", "status"), _illegal_pairs())
def test_illegal_transitions_are_rejected(action: ClaimAction, status: ClaimStatus) -> None:
    with pytest.raises(InvalidTransitionError) as exc:
        _resolve(action, status=status, role=Role.ADMIN)

    assert exc.value.status_code == 409


@pytest.mark.parametrize("status", [ClaimStatus.PAID, ClaimStatus.REJECTED, ClaimStatus.WITHDRAWN])
def test_terminal_statuses_accept_no_action(status: ClaimStatus) -> None:
    for action in ClaimAction:
        with pytest.raises(InvalidTransitionError):
            _resolve(action, status=status, role=Role.ADMIN)


# --------------------------------------------------------------------------- #
# authority: role, ownership and the approval limit
# --------------------------------------------------------------------------- #


def test_a_customer_cannot_approve() -> None:
    with pytest.raises(InsufficientAuthorityError) as exc:
        _resolve(ClaimAction.APPROVE, status=ClaimStatus.UNDER_REVIEW, role=Role.CUSTOMER)

    assert exc.value.status_code == 403


def test_only_the_owner_may_submit_their_draft() -> None:
    with pytest.raises(InsufficientAuthorityError):
        _resolve(ClaimAction.SUBMIT, status=ClaimStatus.DRAFT, role=Role.CUSTOMER, is_owner=False)


@pytest.mark.parametrize("amount", ["0.01", "4999.99", "5000.00"])
def test_adjuster_may_approve_up_to_and_including_the_limit(amount: str) -> None:
    result = _resolve(
        ClaimAction.APPROVE,
        status=ClaimStatus.UNDER_REVIEW,
        role=Role.ADJUSTER,
        amount=Decimal(amount),
    )

    assert result is ClaimStatus.APPROVED


@pytest.mark.parametrize("amount", ["5000.01", "9999.99"])
def test_adjuster_may_not_approve_above_the_limit(amount: str) -> None:
    with pytest.raises(InsufficientAuthorityError, match="exceeds the adjuster approval limit"):
        _resolve(
            ClaimAction.APPROVE,
            status=ClaimStatus.UNDER_REVIEW,
            role=Role.ADJUSTER,
            amount=Decimal(amount),
        )


def test_an_administrator_is_not_bound_by_the_adjuster_limit() -> None:
    result = _resolve(
        ClaimAction.APPROVE,
        status=ClaimStatus.UNDER_REVIEW,
        role=Role.ADMIN,
        amount=ADJUSTER_APPROVAL_LIMIT + Decimal("0.01"),
    )

    assert result is ClaimStatus.APPROVED


def test_status_is_checked_before_authority() -> None:
    """A wrong-state request is a 409 even when the caller also lacks the role.

    Reporting 403 first would tell an unauthorised caller that the action would
    otherwise have been possible, which is more than they need to know.
    """
    with pytest.raises(InvalidTransitionError):
        _resolve(ClaimAction.APPROVE, status=ClaimStatus.PAID, role=Role.CUSTOMER)


# --------------------------------------------------------------------------- #
# visibility
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("role", "is_owner", "expected"),
    [
        (Role.CUSTOMER, True, True),
        (Role.CUSTOMER, False, False),
        (Role.ADJUSTER, False, True),
        (Role.ADMIN, False, True),
    ],
)
def test_claim_visibility(role: Role, is_owner: bool, expected: bool) -> None:
    assert can_view_claim(actor_role=role, is_owner=is_owner) is expected


# --------------------------------------------------------------------------- #
# amount validation against the policy coverage limit
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("amount", ["0.01", "999.99", "1000.00"])
def test_amount_within_coverage_is_accepted(amount: str) -> None:
    validate_claim_amount(Decimal(amount), Decimal("1000.00"))


@pytest.mark.parametrize("amount", ["0.00", "-0.01", "-500.00"])
def test_non_positive_amounts_are_rejected(amount: str) -> None:
    with pytest.raises(DomainError) as exc:
        validate_claim_amount(Decimal(amount), Decimal("1000.00"))

    assert exc.value.status_code == 422


def test_amount_above_coverage_limit_is_rejected() -> None:
    with pytest.raises(DomainError, match="exceeds the policy coverage limit"):
        validate_claim_amount(Decimal("1000.01"), Decimal("1000.00"))
