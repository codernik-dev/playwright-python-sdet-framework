# ADR 0002 — The framework never imports the application under test

**Status:** Accepted · **Date:** 2026-08-19 · **Phase:** 2

## Context

The application under test lives in the same repository as the framework. That is convenient for
reproducibility — one clone, one command — but it creates a real temptation: importing the
application's models, enums or business logic into the tests.

Doing so would be fatal to the project's credibility. A test that imports
`from claimdesk.domain import ClaimStatus` and asserts against it proves only that the code equals
itself. It cannot catch a serialisation bug, a mapping bug, a migration bug, or a broken contract —
the defects that actually reach production.

## Decision

The framework and its tests reach the application **only** over its public interfaces:

* HTTP through a real browser (UI layer),
* HTTP through an HTTP client (API layer),
* SQL through a read-only database role (DB layer).

This is enforced mechanically, not by convention:

```toml
[tool.ruff.lint.flake8-tidy-imports.banned-api]
"claimdesk".msg = "The test framework must NEVER import the application under test."
```

The rule runs in the pre-commit hook and in the CI quality gate, so a violation cannot be merged.

## Consequences

* Test data must be created through the API, not by inserting rows — which is more realistic anyway,
  because it exercises the application's own validation.
* Constants such as status names and the approval limit are duplicated in the test code. That
  duplication is **deliberate**: if the application changes `APPROVED` to `Approved`, a test must
  fail. A shared constant would hide exactly the regression we are paid to catch.
* When the API contract changes, tests break. That is the point.
