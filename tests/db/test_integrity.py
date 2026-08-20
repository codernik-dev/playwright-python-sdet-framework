"""DB-INT - whole-database invariants and assertions about the schema itself.

Matrix: DB-INT-001 ... DB-INT-007.

Two kinds of check live here, and neither is possible from any other layer.

**Invariants** hold across the entire data set, not one record: no orphans, no
claim paid twice, no claim marked PAID without a payout. They are cheap, they run
against everything the suite has created, and they catch defects whose symptom is
a *relationship* rather than a value.

**Schema assertions** check the storage itself. A column holding correct values
today but declared `double precision` is a defect waiting for the first value that
cannot be represented exactly - and no amount of testing rows will ever find it.
"""

from __future__ import annotations

import pytest

from claimdesk_qa.db import Database, DatabaseError, IntegrityQueries
from claimdesk_qa.domain import MONEY_DECIMAL_PLACES

pytestmark = pytest.mark.integrity


# --------------------------------------------------------------------------- #
# referential invariants
# --------------------------------------------------------------------------- #


@pytest.mark.smoke
def test_no_audit_row_points_at_a_missing_claim(integrity_db: IntegrityQueries) -> None:
    """DB-INT-001.

    A foreign key should make this impossible - which is exactly why it is worth
    asserting. "There is a constraint" and "the constraint is valid and enforced"
    are different statements, and a migration that dropped one would go unnoticed
    until the data was already wrong.
    """
    assert integrity_db.orphaned_event_count() == 0


def test_no_payout_points_at_a_missing_claim(integrity_db: IntegrityQueries) -> None:
    """DB-INT-002 - an orphaned payout is money attached to nothing."""
    assert integrity_db.orphaned_payout_count() == 0


@pytest.mark.smoke
def test_no_claim_has_ever_been_paid_twice(integrity_db: IntegrityQueries) -> None:
    """DB-INT-003 - checked across every claim in the database.

    The per-claim test proves one claim was not double-paid. This proves *none*
    were, including every claim every other test in this run created. It costs one
    query and it is the check an auditor would ask for.
    """
    duplicates = integrity_db.claims_paid_more_than_once()

    assert duplicates == [], f"claims with more than one payout: {duplicates}"


def test_every_paid_claim_has_a_payout(integrity_db: IntegrityQueries) -> None:
    """DB-INT-004 - the opposite failure: money owed and never recorded.

    Paired with the previous test on purpose. Together they say the PAID status and
    the payout ledger agree in both directions, which neither says alone.
    """
    missing = integrity_db.paid_claims_without_a_payout()

    assert missing == [], f"claims marked PAID with no payout row: {missing}"


def test_no_payout_disagrees_with_its_claim(integrity_db: IntegrityQueries) -> None:
    """DB-INT-005 - the amount paid equals the amount approved.

    A payout that drifted from its claim is the shape a rounding bug takes once it
    reaches production.
    """
    mismatched = integrity_db.payouts_disagreeing_with_their_claim()

    assert mismatched == [], f"payouts whose amount differs from the claim: {mismatched}"


def test_every_claim_has_an_audit_trail(integrity_db: IntegrityQueries) -> None:
    """DB-INT-006 - a claim with no history cannot be explained to anyone."""
    silent = integrity_db.claims_with_no_audit_trail()

    assert silent == [], f"claims with no audit rows: {silent}"


# --------------------------------------------------------------------------- #
# the schema itself
# --------------------------------------------------------------------------- #


@pytest.mark.contract
def test_money_is_stored_as_exact_numeric_not_floating_point(
    integrity_db: IntegrityQueries,
) -> None:
    """DB-INT-007 - asserted against ``information_schema``, not against rows.

    This is the test that catches the defect *before* it produces a wrong value.
    A column declared ``double precision`` behaves correctly for most amounts and
    then, one day, cannot represent one - by which point the wrong number is
    already in the ledger.

    Scale is asserted too: ``NUMERIC`` without a scale would accept three decimal
    places and store them, quietly turning a validation rule into a suggestion.
    """
    columns = integrity_db.money_column_types()

    assert columns, "expected monetary columns to exist"
    for column in columns:
        location = f"{column.table_name}.{column.column_name}"
        assert column.data_type == "numeric", f"{location} is {column.data_type}, not numeric"
        assert column.numeric_scale == MONEY_DECIMAL_PLACES, (
            f"{location} has scale {column.numeric_scale}, expected {MONEY_DECIMAL_PLACES}"
        )


@pytest.mark.contract
def test_a_claim_can_only_be_paid_once_at_the_storage_layer(
    integrity_db: IntegrityQueries,
) -> None:
    """The double-payout guard exists as a constraint, not only as application code.

    Application logic can be bypassed by a second code path, a background job, or
    a manual fix applied at 2 a.m. during an incident. A unique constraint cannot.
    Asserting the constraint exists is asserting that the guarantee survives the
    application being wrong.
    """
    constraints = integrity_db.constraints_on("payouts")
    kinds = {c.constraint_type for c in constraints}

    assert "UNIQUE" in kinds or "PRIMARY KEY" in kinds
    unique_names = [c.constraint_name for c in constraints if c.constraint_type == "UNIQUE"]
    assert unique_names, f"payouts has no UNIQUE constraint; found: {sorted(kinds)}"


@pytest.mark.contract
def test_the_claims_table_constrains_status_and_amount(
    integrity_db: IntegrityQueries,
) -> None:
    """Check constraints, so invalid data is impossible rather than merely unlikely."""
    kinds = {c.constraint_type for c in integrity_db.constraints_on("claims")}

    assert "CHECK" in kinds, "claims should constrain status and a positive amount"
    assert "FOREIGN KEY" in kinds, "claims should reference its policy and claimant"


# --------------------------------------------------------------------------- #
# the safety control itself
# --------------------------------------------------------------------------- #


@pytest.mark.negative
@pytest.mark.parametrize(
    ("statement", "description"),
    [
        pytest.param("UPDATE claims SET amount = 1", "update", id="update"),
        pytest.param("DELETE FROM claim_events", "delete", id="delete"),
        pytest.param(
            "INSERT INTO payouts (id, claim_id, amount, paid_by_id) "
            "VALUES (gen_random_uuid(), gen_random_uuid(), 1, gen_random_uuid())",
            "insert",
            id="insert",
        ),
        pytest.param("TRUNCATE claims CASCADE", "truncate", id="truncate"),
    ],
)
def test_the_qa_role_cannot_modify_anything(
    database: Database, statement: str, description: str
) -> None:
    """The control from ADR 0003, tested rather than assumed.

    Every claim this framework makes about not writing to the database rests on
    this. An untested safety control is a belief, and beliefs about permissions
    are wrong surprisingly often - a well-meaning ``GRANT ALL`` during an incident
    is all it takes.

    The failure is raised as a ``DatabaseError``, not an ``AssertionError``,
    because being refused is the framework working correctly rather than the
    product misbehaving.
    """
    with pytest.raises(DatabaseError, match=r"not permitted|read-only|Query failed"):
        database.scalar(statement)
