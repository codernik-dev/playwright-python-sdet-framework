"""ClaimDesk QA - an end-to-end SDET automation framework.

Layering (dependencies point downward only):

    tests/          intent only, no plumbing
      -> assertions/  domain assertion helpers
      -> api|db|ui/   service objects, query objects, page objects
      -> core/        settings, logging, correlation ids, artefacts

This package must NEVER import the application under test (``claimdesk``).
The boundary is enforced by ruff rule TID251; see
``docs/adr/0002-black-box-boundary.md``.
"""

__version__ = "0.1.0"
