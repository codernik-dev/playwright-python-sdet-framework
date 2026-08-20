"""API-CLM negative and boundary coverage.

Matrix: API-CLM-010 ... API-CLM-021.

Boundary tests here follow one rule: for every limit, assert the value **at** the
limit, **just inside** it and **just outside** it. Testing only "too big" proves
the rejection works but says nothing about whether the accepted range is right -
and off-by-one on a monetary limit is a real financial defect, not a rounding
detail.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from claimdesk_qa.api import ApiClient, ClaimsApi
from claimdesk_qa.api.models import ClaimModel, ErrorResponse, PolicyModel
from claimdesk_qa.data import ClaimFactory
from claimdesk_qa.domain import (
    DESCRIPTION_MAX_LENGTH,
    DESCRIPTION_MIN_LENGTH,
    MAX_PAGE_SIZE,
)

pytestmark = pytest.mark.negative

# Built from code points rather than pasted, so the source stays unambiguously
# readable: a reviewer can see WHICH characters are meant without trusting their
# font to distinguish a full-width digit from an ASCII one.
FULL_WIDTH_123 = "".join(chr(code) for code in (0xFF11, 0xFF12, 0xFF13))
ARABIC_INDIC_123 = "".join(chr(code) for code in (0x0661, 0x0662, 0x0663))


# --------------------------------------------------------------------------- #
# amount - value rules
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("amount", "reason"),
    [
        pytest.param("0", "zero is not a claim", id="zero"),
        pytest.param("0.00", "zero with decimals", id="zero-decimals"),
        pytest.param("-0.01", "negative by one cent", id="negative-one-cent"),
        pytest.param("-500.00", "clearly negative", id="negative"),
    ],
)
def test_non_positive_amounts_are_rejected(
    customer_claims: ClaimsApi, claim_factory: ClaimFactory, amount: str, reason: str
) -> None:
    """API-CLM-010 / 011."""
    response = customer_claims.create(claim_factory.payload(amount=amount))

    response.expect_status(422)
    assert "amount" in ErrorResponse.model_validate(response.json()).field_names(), reason


@pytest.mark.boundary
def test_the_smallest_payable_amount_is_accepted(
    customer_claims: ClaimsApi, claim_factory: ClaimFactory
) -> None:
    """API-CLM-014. One cent is the smallest legal value; it must not be rounded away."""
    claim = customer_claims.create(claim_factory.payload(amount="0.01")).expect_status(201)

    assert claim.model(ClaimModel).amount == Decimal("0.01")


@pytest.mark.boundary
@pytest.mark.parametrize(
    "amount",
    [
        pytest.param("1.234", id="three-decimals"),
        pytest.param("1.005", id="three-decimals-rounds-up"),
        pytest.param("0.001", id="sub-cent"),
    ],
)
def test_amounts_with_more_than_two_decimal_places_are_rejected_not_rounded(
    customer_claims: ClaimsApi, claim_factory: ClaimFactory, amount: str
) -> None:
    """API-CLM-015.

    Silently rounding money is the defect being guarded against. If the API
    accepted 1.005 and stored 1.01, the customer's records and the insurer's would
    disagree by a cent per claim - and nobody would notice until reconciliation.
    """
    customer_claims.create(claim_factory.payload(amount=amount)).expect_status(422)


@pytest.mark.parametrize(
    "amount",
    [
        pytest.param("not-a-number", id="text"),
        pytest.param("", id="empty"),
        pytest.param("1e5", id="scientific-notation"),
        pytest.param("  ", id="whitespace"),
        pytest.param("12,50", id="comma-decimal-separator"),
    ],
)
def test_non_numeric_amounts_are_rejected(
    customer_claims: ClaimsApi, claim_factory: ClaimFactory, amount: str
) -> None:
    customer_claims.create(claim_factory.payload(amount=amount)).expect_status(422)


@pytest.mark.parametrize(
    ("amount", "script"),
    [
        pytest.param(FULL_WIDTH_123, "full-width", id="full-width-digits"),
        pytest.param(ARABIC_INDIC_123, "Arabic-Indic", id="arabic-indic-digits"),
    ],
)
def test_non_ascii_digits_are_normalised_rather_than_rejected(
    customer_claims: ClaimsApi, claim_factory: ClaimFactory, amount: str, script: str
) -> None:
    """Characterisation test for a real finding, assessed as LOW severity.

    Python's ``Decimal`` accepts any character in the Unicode ``Nd`` category, so
    non-ASCII numerals are silently normalised: full-width and Arabic-Indic "123"
    both become ``123.00``.

    Why this is documented rather than "fixed":

    * the parsed value is **unambiguous and correct** - those characters really do
      mean one hundred and twenty-three;
    * no business rule is bypassed, because the normalised amount is still checked
      against the policy coverage limit;
    * rejecting them would invent a requirement and would refuse legitimate input
      from users whose keyboards produce those digits.

    What this test guards is the part that *would* matter: if the API accepts the
    input, the stored value must be exactly what the characters mean - never a
    truncation, and never a silently different number. A bug here would be a
    financial defect.
    """
    claim = customer_claims.create(claim_factory.payload(amount=amount)).expect_status(201)

    assert claim.model(ClaimModel).amount == Decimal("123.00"), (
        f"{script} digits must normalise to their exact value, not a different one"
    )


# --------------------------------------------------------------------------- #
# amount - the coverage limit boundary
# --------------------------------------------------------------------------- #


@pytest.mark.boundary
def test_an_amount_exactly_at_the_coverage_limit_is_accepted(
    customer_claims: ClaimsApi, low_coverage_policy: PolicyModel, claim_factory: ClaimFactory
) -> None:
    """API-CLM-012 - the limit is inclusive.

    Uses the 2 500.00 policy deliberately: it sits *below* the adjuster approval
    limit, so this test cannot accidentally be measuring the wrong boundary.
    """
    payload = claim_factory.payload(
        policy_id=str(low_coverage_policy.id),
        amount=str(low_coverage_policy.coverage_limit),
    )

    claim = customer_claims.create(payload).expect_status(201).model(ClaimModel)

    assert claim.amount == low_coverage_policy.coverage_limit


@pytest.mark.boundary
def test_one_cent_over_the_coverage_limit_is_rejected(
    customer_claims: ClaimsApi, low_coverage_policy: PolicyModel, claim_factory: ClaimFactory
) -> None:
    """API-CLM-013. The smallest possible step past the limit must fail."""
    payload = claim_factory.payload(
        policy_id=str(low_coverage_policy.id),
        amount=str(low_coverage_policy.coverage_limit + Decimal("0.01")),
    )

    response = customer_claims.create(payload)

    response.expect_status(422)
    assert "coverage limit" in response.detail().lower()


@pytest.mark.boundary
def test_one_cent_under_the_coverage_limit_is_accepted(
    customer_claims: ClaimsApi, low_coverage_policy: PolicyModel, claim_factory: ClaimFactory
) -> None:
    """The inside edge. Without it, an API that rejects everything would pass."""
    payload = claim_factory.payload(
        policy_id=str(low_coverage_policy.id),
        amount=str(low_coverage_policy.coverage_limit - Decimal("0.01")),
    )

    customer_claims.create(payload).expect_status(201)


# --------------------------------------------------------------------------- #
# description length
# --------------------------------------------------------------------------- #


@pytest.mark.boundary
@pytest.mark.parametrize(
    ("length", "expected"),
    [
        pytest.param(DESCRIPTION_MIN_LENGTH - 1, 422, id="one-below-minimum"),
        pytest.param(DESCRIPTION_MIN_LENGTH, 201, id="exactly-minimum"),
        pytest.param(DESCRIPTION_MAX_LENGTH, 201, id="exactly-maximum"),
        pytest.param(DESCRIPTION_MAX_LENGTH + 1, 422, id="one-above-maximum"),
    ],
)
def test_description_length_boundaries(
    customer_claims: ClaimsApi, claim_factory: ClaimFactory, length: int, expected: int
) -> None:
    """API-CLM-016 - all four edges of the accepted range."""
    payload = claim_factory.payload(description=claim_factory.description(length=length))

    customer_claims.create(payload).expect_status(expected)


# --------------------------------------------------------------------------- #
# identifiers and references
# --------------------------------------------------------------------------- #


def test_creating_a_claim_against_an_unknown_policy_is_rejected(
    customer_claims: ClaimsApi, claim_factory: ClaimFactory
) -> None:
    """API-CLM-017."""
    payload = claim_factory.payload(policy_id="00000000-0000-0000-0000-000000000000")

    customer_claims.create(payload).expect_status(404)


@pytest.mark.parametrize(
    "claim_id",
    [
        pytest.param("not-a-uuid", id="not-a-uuid"),
        pytest.param("12345", id="numeric"),
        pytest.param("00000000-0000-0000-0000-00000000000", id="uuid-one-char-short"),
    ],
)
def test_a_malformed_identifier_is_a_validation_error(
    customer_claims: ClaimsApi, claim_id: str
) -> None:
    """API-CLM-018. Malformed input is 422; well-formed-but-absent is 404."""
    customer_claims.get(claim_id).expect_status(422)


def test_a_well_formed_but_unknown_identifier_is_not_found(customer_claims: ClaimsApi) -> None:
    """API-CLM-019. The distinction from the previous test is the whole point."""
    customer_claims.get("00000000-0000-0000-0000-000000000000").expect_status(404)


# --------------------------------------------------------------------------- #
# dates
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "incident_date",
    [
        pytest.param("2099-01-01", id="far-future"),
        pytest.param("13/08/2026", id="wrong-format"),
        pytest.param("2026-02-30", id="impossible-day"),
        pytest.param("2026-13-01", id="impossible-month"),
        pytest.param("", id="empty"),
    ],
)
def test_invalid_incident_dates_are_rejected(
    customer_claims: ClaimsApi, claim_factory: ClaimFactory, incident_date: str
) -> None:
    """API-CLM-020. A claim cannot be made for an incident that has not happened."""
    customer_claims.create(claim_factory.payload(incident_date=incident_date)).expect_status(422)


def test_an_incident_dated_today_is_accepted(
    customer_claims: ClaimsApi, claim_factory: ClaimFactory
) -> None:
    """The inside edge of the future-date rule: today is not the future."""
    payload = claim_factory.payload(incident_date=claim_factory.recent_date(days_ago=0).isoformat())

    customer_claims.create(payload).expect_status(201)


# --------------------------------------------------------------------------- #
# payload shape
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "missing",
    ["policy_id", "amount", "description", "incident_date"],
)
def test_every_required_field_is_actually_required(
    customer_claims: ClaimsApi, claim_factory: ClaimFactory, missing: str
) -> None:
    """Removing each field in turn, so no field is 'required' only in the docs."""
    payload = claim_factory.payload()
    del payload[missing]

    response = customer_claims.create(payload)

    response.expect_status(422)
    assert missing in ErrorResponse.model_validate(response.json()).field_names()


def test_an_unknown_field_does_not_change_the_claim(
    customer_claims: ClaimsApi, claim_factory: ClaimFactory
) -> None:
    """API-CLM-021.

    The behaviour is asserted rather than assumed. Whether unknown fields are
    ignored or rejected is a real API decision; what matters is that a client
    cannot smuggle in a field the server silently honours - here, a status.
    """
    payload = claim_factory.payload(status="PAID", is_admin=True)

    response = customer_claims.create(payload)

    if response.status_code == 201:
        claim = response.model(ClaimModel)
        assert claim.status.value == "DRAFT", "an unknown field must not set the status"
    else:
        response.expect_status(422)


# --------------------------------------------------------------------------- #
# query parameter validation
# --------------------------------------------------------------------------- #


@pytest.mark.boundary
@pytest.mark.parametrize(
    ("size", "expected"),
    [
        pytest.param(0, 422, id="size-zero"),
        pytest.param(1, 200, id="size-minimum"),
        pytest.param(MAX_PAGE_SIZE, 200, id="size-maximum"),
        pytest.param(MAX_PAGE_SIZE + 1, 422, id="size-above-maximum"),
        pytest.param(-1, 422, id="size-negative"),
    ],
)
def test_page_size_boundaries(customer_claims: ClaimsApi, size: int, expected: int) -> None:
    """An unbounded page size is a denial-of-service vector, not a convenience."""
    customer_claims.list(size=size).expect_status(expected)


@pytest.mark.boundary
@pytest.mark.parametrize("page", [0, -1])
def test_page_numbers_below_one_are_rejected(customer_claims: ClaimsApi, page: int) -> None:
    customer_claims.list(page=page).expect_status(422)


def test_a_page_beyond_the_end_returns_an_empty_page(customer_claims: ClaimsApi) -> None:
    """Past the last page is empty, not an error - clients paginate blindly."""
    response = customer_claims.list(page=9999, size=10).expect_status(200)

    assert response.json()["items"] == []


@pytest.mark.parametrize(
    "sort",
    [
        pytest.param("password_hash", id="unlisted-column"),
        pytest.param("nonexistent", id="unknown-field"),
        pytest.param("amount; DROP TABLE claims", id="sql-injection-attempt"),
    ],
)
def test_sorting_by_an_unpermitted_field_is_rejected(customer_claims: ClaimsApi, sort: str) -> None:
    """Sort parameters are an allow-list, never a passthrough to a column name.

    A sort parameter interpolated into SQL is a classic injection point, and one
    that leaks data even without injection: sorting by a column you cannot see
    still reveals its ordering.
    """
    customer_claims.list(sort=sort).expect_status(422)


def test_an_oversized_search_term_is_rejected(customer_client: ApiClient) -> None:
    """Unbounded input is unbounded work for the database."""
    customer_client.get("/claims", params={"q": "x" * 5000}).expect_status(422)
