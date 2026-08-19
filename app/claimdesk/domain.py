"""Business rules for claims: roles, the status machine and the approval limit.

Pure logic with no database or web imports, so the application's own unit tests can
exercise it in milliseconds.

These rules are the specification the automation framework tests against. They are
deliberately not shared with the framework: the framework keeps its own copy, so a
change here that is not intended breaks a test instead of silently moving both sides
at once. See ``docs/adr/0002-black-box-boundary.md``.
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


#: An adjuster may approve claims up to and including this amount. Anything above
#: it requires an administrator. The boundary is inclusive, which is exactly the
#: kind of detail boundary tests exist to pin down.
ADJUSTER_APPROVAL_LIMIT: Final[Decimal] = Decimal("5000.00")

#: Statuses that accept no further change. Attempting to modify one is a conflict.
TERMINAL_STATUSES: Final[frozenset[ClaimStatus]] = frozenset(
    {ClaimStatus.PAID, ClaimStatus.REJECTED, ClaimStatus.WITHDRAWN}
)

#: Only a draft may be edited or withdrawn by its owner.
EDITABLE_STATUSES: Final[frozenset[ClaimStatus]] = frozenset({ClaimStatus.DRAFT})


class TransitionRule(NamedTuple):
    """One legal edge of the claim status machine."""

    source: ClaimStatus
    target: ClaimStatus
    roles: frozenset[Role]
    owner_only: bool = False
    amount_limited: bool = False
    """True when an adjuster's approval limit applies to this action."""


TRANSITIONS: Final[dict[ClaimAction, TransitionRule]] = {
    ClaimAction.SUBMIT: TransitionRule(
        source=ClaimStatus.DRAFT,
        target=ClaimStatus.SUBMITTED,
        roles=frozenset({Role.CUSTOMER, Role.ADMIN}),
        owner_only=True,
    ),
    ClaimAction.START_REVIEW: TransitionRule(
        source=ClaimStatus.SUBMITTED,
        target=ClaimStatus.UNDER_REVIEW,
        roles=frozenset({Role.ADJUSTER, Role.ADMIN}),
    ),
    ClaimAction.APPROVE: TransitionRule(
        source=ClaimStatus.UNDER_REVIEW,
        target=ClaimStatus.APPROVED,
        roles=frozenset({Role.ADJUSTER, Role.ADMIN}),
        amount_limited=True,
    ),
    ClaimAction.REJECT: TransitionRule(
        source=ClaimStatus.UNDER_REVIEW,
        target=ClaimStatus.REJECTED,
        roles=frozenset({Role.ADJUSTER, Role.ADMIN}),
    ),
    ClaimAction.PAY: TransitionRule(
        source=ClaimStatus.APPROVED,
        target=ClaimStatus.PAID,
        roles=frozenset({Role.ADJUSTER, Role.ADMIN}),
    ),
}


class DomainError(Exception):
    """Base class for rule violations, carrying the HTTP status the API should use."""

    status_code = 400

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class InvalidTransitionError(DomainError):
    """The requested action is not legal from the claim's current status."""

    status_code = 409


class InsufficientAuthorityError(DomainError):
    """The caller's role, ownership or approval limit does not permit the action."""

    status_code = 403


def resolve_transition(
    action: ClaimAction,
    *,
    current_status: ClaimStatus,
    actor_role: Role,
    is_owner: bool,
    amount: Decimal,
) -> ClaimStatus:
    """Validate a requested action and return the resulting status.

    Order of checks matters and is deliberate: the status is validated *before*
    authority. A customer trying to approve an already-paid claim gets ``409``,
    not ``403`` — the claim's state is a fact about the resource, while authority
    is a fact about the caller, and leaking "you could have done this if you had
    the right role" is more informative than it needs to be.

    Raises:
        InvalidTransitionError: the action is illegal from ``current_status``.
        InsufficientAuthorityError: the caller may not perform it.
    """
    rule = TRANSITIONS[action]

    if current_status is not rule.source:
        raise InvalidTransitionError(
            f"Cannot {action.value} a claim in status {current_status.value}; "
            f"it must be {rule.source.value}."
        )

    if actor_role not in rule.roles:
        raise InsufficientAuthorityError(f"Role {actor_role.value} may not {action.value} a claim.")

    if rule.owner_only and not is_owner:
        raise InsufficientAuthorityError(f"Only the claim owner may {action.value} it.")

    if rule.amount_limited and actor_role is Role.ADJUSTER and amount > ADJUSTER_APPROVAL_LIMIT:
        raise InsufficientAuthorityError(
            f"Amount {amount} exceeds the adjuster approval limit of "
            f"{ADJUSTER_APPROVAL_LIMIT}; an administrator must approve it."
        )

    return rule.target


def can_view_claim(*, actor_role: Role, is_owner: bool) -> bool:
    """Staff see every claim; a customer sees only their own."""
    if actor_role in (Role.ADJUSTER, Role.ADMIN):
        return True
    return is_owner


def validate_claim_amount(amount: Decimal, coverage_limit: Decimal) -> None:
    """Enforce ``0 < amount <= coverage_limit``.

    Raises:
        DomainError: with a 422 status, matching the framework's validation errors.
    """
    if amount <= Decimal("0"):
        error = DomainError("Claim amount must be greater than zero.")
        error.status_code = 422
        raise error
    if amount > coverage_limit:
        error = DomainError(
            f"Claim amount {amount} exceeds the policy coverage limit of {coverage_limit}."
        )
        error.status_code = 422
        raise error
