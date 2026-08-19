"""Deterministic seed data.

Two rules make this data safe for a parallel test suite:

1. **It is deterministic.** The same users, policies, references and amounts every
   time, so a test can rely on them without creating them first.
2. **It is read-only by convention.** Seeded claims all carry the ``CLM-SEED``
   prefix and exist to support list, filter, sort and pagination tests. No test
   mutates them; tests that need to change a claim create their own.

Seeding is idempotent: running it twice changes nothing.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from claimdesk.config import get_app_settings
from claimdesk.domain import ClaimStatus, Role
from claimdesk.models import Claim, ClaimEvent, Payout, Policy, User
from claimdesk.security import hash_password

# example.com is reserved for documentation by RFC 2606 and is therefore the correct
# domain for test data. Note that RFC 2606 also reserves the `.test` TLD, but
# email-validator rejects it as a special-use name - so `.test` addresses cannot be
# used with EmailStr at all. Discovered the hard way; see docs/progress.md.
ADMIN_EMAIL = "admin@example.com"
ADJUSTER_EMAIL = "adjuster@example.com"
CUSTOMER_EMAIL = "customer@example.com"
OTHER_CUSTOMER_EMAIL = "other.customer@example.com"

SEED_REFERENCE_PREFIX = "CLM-SEED"

#: Policy numbers and their coverage limits. The 2 500.00 policy sits *below* the
#: adjuster approval limit of 5 000.00, so coverage-limit and approval-limit
#: boundaries can be tested independently of one another.
POLICIES: tuple[tuple[str, str, Decimal], ...] = (
    ("POL-1001", CUSTOMER_EMAIL, Decimal("10000.00")),
    ("POL-1002", CUSTOMER_EMAIL, Decimal("2500.00")),
    ("POL-2001", OTHER_CUSTOMER_EMAIL, Decimal("10000.00")),
)

#: (index, status, amount) for the seeded claim corpus. Amounts are spread either
#: side of the 5 000.00 approval limit and the set is large enough that a default
#: page size of 20 leaves a second page to test.
_CORPUS: tuple[tuple[ClaimStatus, str], ...] = (
    (ClaimStatus.DRAFT, "120.00"),
    (ClaimStatus.DRAFT, "349.50"),
    (ClaimStatus.DRAFT, "1500.00"),
    (ClaimStatus.DRAFT, "75.25"),
    (ClaimStatus.SUBMITTED, "900.00"),
    (ClaimStatus.SUBMITTED, "4999.99"),
    (ClaimStatus.SUBMITTED, "5000.00"),
    (ClaimStatus.SUBMITTED, "5000.01"),
    (ClaimStatus.SUBMITTED, "250.00"),
    (ClaimStatus.UNDER_REVIEW, "610.00"),
    (ClaimStatus.UNDER_REVIEW, "3200.00"),
    (ClaimStatus.UNDER_REVIEW, "7400.00"),
    (ClaimStatus.UNDER_REVIEW, "88.00"),
    (ClaimStatus.APPROVED, "1450.00"),
    (ClaimStatus.APPROVED, "2600.00"),
    (ClaimStatus.APPROVED, "9999.99"),
    (ClaimStatus.REJECTED, "430.00"),
    (ClaimStatus.REJECTED, "6100.00"),
    (ClaimStatus.PAID, "775.00"),
    (ClaimStatus.PAID, "3050.00"),
    (ClaimStatus.PAID, "150.00"),
    (ClaimStatus.DRAFT, "980.00"),
    (ClaimStatus.SUBMITTED, "1320.00"),
    (ClaimStatus.UNDER_REVIEW, "2480.00"),
)

#: The order a claim passes through to reach a given status, used to build a
#: realistic audit trail for seeded claims rather than a single synthetic row.
_PATHS: dict[ClaimStatus, tuple[ClaimStatus, ...]] = {
    ClaimStatus.DRAFT: (ClaimStatus.DRAFT,),
    ClaimStatus.SUBMITTED: (ClaimStatus.DRAFT, ClaimStatus.SUBMITTED),
    ClaimStatus.UNDER_REVIEW: (
        ClaimStatus.DRAFT,
        ClaimStatus.SUBMITTED,
        ClaimStatus.UNDER_REVIEW,
    ),
    ClaimStatus.APPROVED: (
        ClaimStatus.DRAFT,
        ClaimStatus.SUBMITTED,
        ClaimStatus.UNDER_REVIEW,
        ClaimStatus.APPROVED,
    ),
    ClaimStatus.REJECTED: (
        ClaimStatus.DRAFT,
        ClaimStatus.SUBMITTED,
        ClaimStatus.UNDER_REVIEW,
        ClaimStatus.REJECTED,
    ),
    ClaimStatus.PAID: (
        ClaimStatus.DRAFT,
        ClaimStatus.SUBMITTED,
        ClaimStatus.UNDER_REVIEW,
        ClaimStatus.APPROVED,
        ClaimStatus.PAID,
    ),
}


def _ensure_user(
    session: Session, *, email: str, full_name: str, role: Role, password: str
) -> User:
    user = session.scalar(select(User).where(User.email == email))
    if user is not None:
        return user
    user = User(
        email=email,
        full_name=full_name,
        role=role.value,
        password_hash=hash_password(password),
        is_active=True,
    )
    session.add(user)
    session.flush()
    return user


def seed(session: Session) -> None:
    """Create the baseline data set if it is not already present."""
    settings = get_app_settings()
    password = settings.seed_user_password.get_secret_value()

    _ensure_user(
        session, email=ADMIN_EMAIL, full_name="Ada Admin", role=Role.ADMIN, password=password
    )
    adjuster = _ensure_user(
        session,
        email=ADJUSTER_EMAIL,
        full_name="Alex Adjuster",
        role=Role.ADJUSTER,
        password=password,
    )
    customer = _ensure_user(
        session,
        email=CUSTOMER_EMAIL,
        full_name="Casey Customer",
        role=Role.CUSTOMER,
        password=password,
    )
    other = _ensure_user(
        session,
        email=OTHER_CUSTOMER_EMAIL,
        full_name="Robin Rival",
        role=Role.CUSTOMER,
        password=password,
    )
    holders = {CUSTOMER_EMAIL: customer, OTHER_CUSTOMER_EMAIL: other}

    for number, holder_email, coverage in POLICIES:
        if session.scalar(select(Policy).where(Policy.policy_number == number)) is None:
            session.add(
                Policy(
                    policy_number=number,
                    holder_id=holders[holder_email].id,
                    coverage_limit=coverage,
                    is_active=True,
                )
            )
    session.flush()

    already_seeded = session.scalar(
        select(func.count())
        .select_from(Claim)
        .where(Claim.reference.like(f"{SEED_REFERENCE_PREFIX}%"))
    )
    if already_seeded:
        session.commit()
        return

    policy = session.scalar(select(Policy).where(Policy.policy_number == "POL-1001"))
    if policy is None:  # pragma: no cover - created immediately above
        msg = "Seed policy POL-1001 is missing; the seed cannot continue."
        raise RuntimeError(msg)

    # UTC so the seeded corpus is identical wherever it is loaded. Seed data
    # that shifts by a day depending on the server's timezone would make a
    # date-range filter test pass in one environment and fail in another.
    today = datetime.now(UTC).date()
    for index, (final_status, amount) in enumerate(_CORPUS, start=1):
        claim = Claim(
            reference=f"{SEED_REFERENCE_PREFIX}{index:04d}",
            policy_id=policy.id,
            claimant_id=customer.id,
            amount=Decimal(amount),
            description=f"Seeded claim {index} for list, filter and sort coverage",
            # Spread incident dates so date-range filters have something to bite on.
            incident_date=today - timedelta(days=index * 3),
            status=final_status.value,
        )
        if final_status in (ClaimStatus.APPROVED, ClaimStatus.PAID, ClaimStatus.REJECTED):
            claim.decided_by_id = adjuster.id
        session.add(claim)
        session.flush()

        path = _PATHS[final_status]
        previous: ClaimStatus | None = None
        for step in path:
            actor = customer if step in (ClaimStatus.DRAFT, ClaimStatus.SUBMITTED) else adjuster
            session.add(
                ClaimEvent(
                    claim_id=claim.id,
                    actor_id=actor.id,
                    from_status=previous.value if previous else None,
                    to_status=step.value,
                    note="seed",
                )
            )
            previous = step

        if final_status is ClaimStatus.PAID:
            session.add(Payout(claim_id=claim.id, amount=claim.amount, paid_by_id=adjuster.id))

    session.commit()
