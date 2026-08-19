"""The deterministic data the application seeds on startup.

Named constants rather than string literals scattered through tests: when the seed
changes, one file changes. More importantly, a typo becomes an ImportError at
collection instead of a 401 that looks like an authentication bug.

Everything here is READ-ONLY by convention. No test mutates a seeded account or a
seeded claim - tests that need to change something create their own. That single
rule is most of what makes the suite safe to run in parallel.
"""

from __future__ import annotations

from typing import Final


class SeededAccounts:
    """Accounts created by the application's seed. All share SEED_USER_PASSWORD."""

    ADMIN: Final[str] = "admin@example.com"
    ADJUSTER: Final[str] = "adjuster@example.com"
    CUSTOMER: Final[str] = "customer@example.com"
    OTHER_CUSTOMER: Final[str] = "other.customer@example.com"
    """A second customer, used to prove cross-tenant access is refused."""


class SeededPolicies:
    """Policies created by the seed."""

    CUSTOMER_HIGH_COVERAGE: Final[str] = "POL-1001"
    """Coverage 10000.00 - large enough to exercise the adjuster approval limit."""

    CUSTOMER_LOW_COVERAGE: Final[str] = "POL-1002"
    """Coverage 2500.00 - BELOW the approval limit, so the coverage boundary and
    the approval boundary can be tested independently of one another."""

    OTHER_CUSTOMER: Final[str] = "POL-2001"


#: Prefix on every seeded claim reference. Tests filter it out when they need to
#: assert on "only the claims I created".
SEED_CLAIM_PREFIX: Final[str] = "CLM-SEED"

#: How many claims the seed creates. Asserted in one place so a change to the seed
#: fails a single obvious test rather than a dozen mysterious ones.
SEED_CLAIM_COUNT: Final[int] = 24
