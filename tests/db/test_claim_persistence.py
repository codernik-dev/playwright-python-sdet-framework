"""DB-CLM — what the application actually stored.

Matrix: DB-CLM-001 … DB-CLM-006.

The pattern is always the same: **act through the application, then assert on
storage.** A database test that only reads would be testing the seed script.

What these tests add over the API tests is not duplication. The API can only tell
you what a response said. Only the database can tell you whether the value was
persisted exactly, whether the row survived a delete, and whether the money is
stored in a type that can represent it.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from claimdesk_qa.api import ClaimsApi
from claimdesk_qa.config import Settings
from claimdesk_qa.data import ClaimFactory
from claimdesk_qa.data.factories import unique_suffix
from claimdesk_qa.data.seeded import SeededAccounts
from claimdesk_qa.db import ClaimQueries, IntegrityQueries, UserQueries
from claimdesk_qa.domain import ClaimStatus


@pytest.mark.smoke
def test_a_claim_created_through_the_api_is_persisted(
    customer_claims: ClaimsApi, claim_factory: ClaimFactory, claims_db: ClaimQueries
) -> None:
    """DB-CLM-001 — the write reached storage, with every field intact.

    A `201` proves the API accepted the request. It does not prove a row exists,
    and it certainly does not prove the row holds what was sent — an application
    that returned the payload it was given while silently failing to commit would
    satisfy every API test in this repository.
    """
    payload = claim_factory.payload(amount="1234.56")

    claim = customer_claims.create_claim(payload)

    row = claims_db.by_id(claim.id)
    assert row is not None, "the API returned 201 but no row exists"
    assert row.reference == claim.reference
    assert row.amount == Decimal("1234.56")
    assert row.description == payload["description"]
    assert row.status == ClaimStatus.DRAFT.value
    assert row.withdrawn_at is None
    assert row.decided_by_id is None


@pytest.mark.smoke
def test_money_is_stored_exactly(
    customer_claims: ClaimsApi, claim_factory: ClaimFactory, claims_db: ClaimQueries
) -> None:
    """DB-CLM-002 — exact equality on a Decimal, all the way to storage.

    ``0.1 + 0.2 != 0.3`` stops being a curiosity when the value is a payout. This
    asserts equality rather than closeness, which is only possible because the
    column is NUMERIC and psycopg returns Decimal. The moment anything in the
    chain becomes a float, the strongest available assertion drops to "close
    enough" — and a cent-per-claim discrepancy becomes invisible.
    """
    awkward = "1234.57"  # not representable exactly in binary floating point

    claim = customer_claims.create_claim(claim_factory.payload(amount=awkward))

    row = claims_db.by_id(claim.id)
    assert row is not None
    assert row.amount == Decimal(awkward)
    assert isinstance(row.amount, Decimal), "money must not arrive as a float"
    assert str(row.amount) == awkward, "stored scale must be preserved, not normalised away"


def test_updating_a_draft_is_persisted(
    customer_claims: ClaimsApi, claim_factory: ClaimFactory, claims_db: ClaimQueries
) -> None:
    """DB-CLM-003 — and the update timestamp moves."""
    claim = customer_claims.create_claim(claim_factory.payload(amount="500.00"))
    before = claims_db.by_id(claim.id)
    assert before is not None

    customer_claims.update(claim.id, {"description": "Updated through the API"}).expect_status(200)

    after = claims_db.by_id(claim.id)
    assert after is not None
    assert after.description == "Updated through the API"
    assert after.amount == before.amount, "an unrelated column must not change"
    assert after.updated_at > before.updated_at, "updated_at should advance on a write"
    assert after.created_at == before.created_at, "created_at must never move"


def test_withdrawing_a_claim_is_a_soft_delete(
    customer_claims: ClaimsApi, claim_factory: ClaimFactory, claims_db: ClaimQueries
) -> None:
    """DB-CLM-004 — the assertion only the database can make.

    The API test proves a withdrawn claim reports ``WITHDRAWN``. It cannot prove
    the row was not physically deleted and re-created, nor that a hard delete did
    not take the audit trail with it. This can.
    """
    claim = customer_claims.create_claim(claim_factory.payload())

    customer_claims.withdraw(claim.id).expect_status(204)

    assert claims_db.exists(claim.id), "the row must survive a withdrawal"
    row = claims_db.by_id(claim.id)
    assert row is not None
    assert row.status == ClaimStatus.WITHDRAWN.value
    assert row.withdrawn_at is not None, "withdrawn_at records when, not just that"
    assert row.reference == claim.reference, "the identity of the row is unchanged"


def test_the_approving_actor_is_recorded_against_the_claim(
    customer_claims: ClaimsApi,
    adjuster_claims: ClaimsApi,
    claim_factory: ClaimFactory,
    claims_db: ClaimQueries,
    users_db: UserQueries,
) -> None:
    """DB-CLM-005 — the decision is attributable to a real person.

    ``decided_by_id`` is resolved back to a user row rather than merely checked
    for non-null: a foreign key that pointed at a deleted or wrong user would pass
    a null check and fail an audit.
    """
    claim = customer_claims.create_claim(claim_factory.payload(amount="900.00"))
    customer_claims.drive_to(claim.id, ClaimStatus.APPROVED, staff=adjuster_claims)

    row = claims_db.by_id(claim.id)
    adjuster = users_db.by_email(SeededAccounts.ADJUSTER)
    assert row is not None
    assert adjuster is not None
    assert row.decided_by_id == adjuster.id
    assert adjuster.role == "ADJUSTER"


def test_a_rejected_write_leaves_no_row(
    customer_claims: ClaimsApi, claim_factory: ClaimFactory, claims_db: ClaimQueries
) -> None:
    """DB-CLM-006 — a 422 must not leave a partial record behind.

    The failure mode being guarded against is a handler that inserts first and
    validates second. The API would still return an error, so no API test could
    detect it, while the database quietly accumulated invalid rows.

    **Scoped to this test's own marker, and the first version was not.** It
    compared a global ``count(*) WHERE status = 'DRAFT'`` before and after, which
    failed two runs in three under ``-n 4``: other workers legitimately create
    draft claims in between, so the number moves for reasons that have nothing to
    do with this test.

    That is the same error as the Phase 6 pagination flake, made again in a new
    layer — which is the argument for stating the rule as a rule rather than
    fixing instances of it. **A test may assert on an invariant globally, because
    an invariant holds no matter who else is writing. It may never assert on an
    aggregate globally, because an aggregate is a fact about the whole database
    and the whole database is shared.**
    """
    marker = f"rejected-{unique_suffix()}"
    description = f"{marker} this claim must never be stored"

    customer_claims.create(
        claim_factory.payload(amount="-1.00", description=description)
    ).expect_status(422)
    customer_claims.create(
        claim_factory.payload(amount="1.234", description=description)
    ).expect_status(422)

    assert claims_db.count_with_description_containing(marker) == 0


@pytest.mark.integrity
def test_passwords_are_never_stored_in_plaintext(
    users_db: UserQueries, integrity_db: IntegrityQueries, settings: Settings
) -> None:
    """DB-SEC-001 — one query, and it catches hashing being disabled entirely.

    Checked two ways: the seeded password appears in no ``password_hash``, and the
    stored value carries a bcrypt prefix. The first catches a no-op hash; the
    second catches a hash that is present but not the algorithm intended.
    """
    plaintext = settings.seed_user_password.get_secret_value()

    assert integrity_db.plaintext_password_count(plaintext) == 0

    user = users_db.by_email(SeededAccounts.CUSTOMER)
    assert user is not None
    assert user.password_hash.startswith("$2"), "expected a bcrypt hash"
    assert plaintext not in user.password_hash
