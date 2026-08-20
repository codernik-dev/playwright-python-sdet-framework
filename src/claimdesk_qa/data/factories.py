"""Factories: valid-by-default payloads with per-test overrides.

The problem they solve is duplication with a twist. Without a factory, every test
that creates a claim spells out four fields, so when the API adds a fifth required
field, forty tests break at once - and worse, forty tests each contain a slightly
different idea of what a "normal" claim looks like.

With a factory, tests state only what they care about:

    ClaimFactory(policy_id=policy.id).payload(amount="5000.01")

The reader sees immediately that this test is about the amount, and that
everything else is unremarkable. That readability is the real return: a test
should show its intent, not its plumbing.

Uniqueness is not left to chance. Faker makes values *look* real; the ``unique``
suffix makes them *safe to run in parallel*. Those are different problems and the
factory solves both explicitly.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from faker import Faker

from claimdesk_qa.core.clock import days_ago_utc
from claimdesk_qa.domain import DESCRIPTION_MIN_LENGTH


def unique_suffix() -> str:
    """A short value that cannot collide across processes, workers or runs."""
    return uuid.uuid4().hex[:8]


@dataclass
class ClaimFactory:
    """Builds claim payloads that the API accepts.

    Defaults are chosen to be *unremarkable*: an amount well inside every seeded
    policy's coverage limit and comfortably below the adjuster approval limit, and
    an incident date in the recent past. A test that wants to sit on a boundary
    says so explicitly, and the diff makes that obvious to a reviewer.
    """

    policy_id: uuid.UUID | str
    faker: Faker = field(default_factory=Faker)

    DEFAULT_AMOUNT = Decimal("250.00")

    def payload(self, **overrides: Any) -> dict[str, Any]:
        """A valid payload, with any field replaced by an override.

        Overrides are applied last and are not validated, so a test can pass
        deliberately invalid values - which is exactly what the negative and
        boundary tests need.
        """
        base: dict[str, Any] = {
            "policy_id": str(self.policy_id),
            "amount": str(self.DEFAULT_AMOUNT),
            "description": self.description(),
            "incident_date": self.recent_date().isoformat(),
        }
        base.update(overrides)
        return base

    def description(self, *, length: int | None = None) -> str:
        """A description carrying a unique marker, so a test can find its own rows.

        The marker is what makes the search and filter tests safe under parallel
        execution: they search for their own suffix rather than for a word that
        another worker's data might also contain.
        """
        text = f"QA {unique_suffix()} {self.faker.sentence(nb_words=6)}"
        if length is None:
            return text
        if length < DESCRIPTION_MIN_LENGTH:
            return "x" * length
        return (text * (length // len(text) + 1))[:length]

    def recent_date(self, *, days_ago: int = 7) -> date:
        """A date in the past. The API rejects future incident dates.

        UTC, not the runner's local date - see :mod:`claimdesk_qa.core.clock`.
        With ``days_ago=0`` this is the boundary value itself, and a local date
        would make that assertion depend on the timezone of whichever machine
        happened to run it.
        """
        return days_ago_utc(days_ago)


@dataclass
class UserFactory:
    """Builds user payloads for the administrator endpoints."""

    faker: Faker = field(default_factory=Faker)

    def payload(self, **overrides: Any) -> dict[str, Any]:
        base: dict[str, Any] = {
            # example.com is reserved for documentation by RFC 2606. The `.test`
            # TLD is reserved too, but email-validator rejects it as a special-use
            # name - so it cannot be used with an EmailStr field at all.
            "email": f"qa+{unique_suffix()}@example.com",
            "full_name": self.faker.name(),
            "role": "CUSTOMER",
            "password": "Passw0rd!generated",
        }
        base.update(overrides)
        return base
