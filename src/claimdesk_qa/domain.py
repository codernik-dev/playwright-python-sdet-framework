"""The framework's own copy of ClaimDesk's business vocabulary.

**This duplicates the application deliberately.** See
``docs/adr/0002-black-box-boundary.md``.

Importing ``claimdesk.domain`` would be shorter and would also make every contract
regression invisible: rename the serialised value ``APPROVED`` to ``Approved`` and
both sides move together, so the tests stay green while every real API consumer
breaks.

The copy here is the **specification** — what the framework asserts the API
promises. The application's copy is the **implementation**. When they disagree, a
test fails, which is the entire point of the exercise.
"""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import Final, NamedTuple


class Role(StrEnum):
    CUSTOMER = "CUSTOMER"
    ADJUSTER = "ADJUSTER"
    ADMIN = "ADMIN"


class ClaimStatus(StrEnum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    PAID = "PAID"
    WITHDRAWN = "WITHDRAWN"


class ClaimAction(StrEnum):
    SUBMIT = "submit"
    START_REVIEW = "start_review"
    APPROVE = "approve"
    REJECT = "reject"
    PAY = "pay"


#: The published approval limit for an adjuster. Inclusive: exactly this amount is
#: allowed, one cent more is not. Boundary tests exist to pin down which.
ADJUSTER_APPROVAL_LIMIT: Final[Decimal] = Decimal("5000.00")

#: Money has two decimal places. Anything else must be rejected, not rounded.
MONEY_DECIMAL_PLACES: Final[int] = 2

#: Field limits published by the API, asserted at and just past each edge.
DESCRIPTION_MIN_LENGTH: Final[int] = 5
DESCRIPTION_MAX_LENGTH: Final[int] = 500
MAX_PAGE_SIZE: Final[int] = 100
DEFAULT_PAGE_SIZE: Final[int] = 20


class Transition(NamedTuple):
    """One edge the API is expected to allow."""

    action: ClaimAction
    source: ClaimStatus
    target: ClaimStatus


#: Every legal edge of the published state machine. The negative matrix is derived
#: from this rather than hand-written, so a new status cannot be added without its
#: illegal combinations appearing automatically.
LEGAL_TRANSITIONS: Final[tuple[Transition, ...]] = (
    Transition(ClaimAction.SUBMIT, ClaimStatus.DRAFT, ClaimStatus.SUBMITTED),
    Transition(ClaimAction.START_REVIEW, ClaimStatus.SUBMITTED, ClaimStatus.UNDER_REVIEW),
    Transition(ClaimAction.APPROVE, ClaimStatus.UNDER_REVIEW, ClaimStatus.APPROVED),
    Transition(ClaimAction.REJECT, ClaimStatus.UNDER_REVIEW, ClaimStatus.REJECTED),
    Transition(ClaimAction.PAY, ClaimStatus.APPROVED, ClaimStatus.PAID),
)

_LEGAL_PAIRS: Final[frozenset[tuple[ClaimAction, ClaimStatus]]] = frozenset(
    (transition.action, transition.source) for transition in LEGAL_TRANSITIONS
)


def illegal_transitions() -> tuple[tuple[ClaimAction, ClaimStatus], ...]:
    """Every ``(action, status)`` pair the API must reject with ``409``.

    Generated, not listed. A hand-written list silently fails to cover a status
    added later — which is exactly how negative coverage rots without anyone
    noticing.
    """
    return tuple(
        (action, status)
        for action in ClaimAction
        for status in ClaimStatus
        if (action, status) not in _LEGAL_PAIRS
    )


def path_to(status: ClaimStatus) -> tuple[ClaimAction, ...]:
    """The actions needed to drive a fresh DRAFT claim to ``status``.

    Tests use this to reach a state through the real workflow rather than by
    writing rows — which is enforced anyway, since the framework's database role
    holds SELECT and nothing else.
    """
    routes: dict[ClaimStatus, tuple[ClaimAction, ...]] = {
        ClaimStatus.DRAFT: (),
        ClaimStatus.SUBMITTED: (ClaimAction.SUBMIT,),
        ClaimStatus.UNDER_REVIEW: (ClaimAction.SUBMIT, ClaimAction.START_REVIEW),
        ClaimStatus.APPROVED: (
            ClaimAction.SUBMIT,
            ClaimAction.START_REVIEW,
            ClaimAction.APPROVE,
        ),
        ClaimStatus.REJECTED: (
            ClaimAction.SUBMIT,
            ClaimAction.START_REVIEW,
            ClaimAction.REJECT,
        ),
        ClaimStatus.PAID: (
            ClaimAction.SUBMIT,
            ClaimAction.START_REVIEW,
            ClaimAction.APPROVE,
            ClaimAction.PAY,
        ),
    }
    if status not in routes:
        msg = f"No workflow route to {status}; it is not reachable by transitions."
        raise ValueError(msg)
    return routes[status]
