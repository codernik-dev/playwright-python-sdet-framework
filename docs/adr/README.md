# Architecture Decision Records

One short file per significant decision: the context, the choice, the alternatives that were
rejected, and the consequences we accepted.

They exist for two reasons:

1. **Interview defensibility.** Every question of the form *"why did you use X?"* has a written,
   considered answer rather than a rationalisation invented on the spot.
2. **Reviewability.** A senior engineer reading this repository can see the reasoning, not just the
   result — and can disagree with the reasoning specifically.

| ADR | Decision |
|---|---|
| [0001](0001-python-pytest-playwright.md) | Python + pytest + Playwright as the core stack |
| [0002](0002-black-box-boundary.md) | The framework never imports the application under test |
| [0003](0003-read-only-db-role.md) | Database validation runs as a read-only PostgreSQL role |
| [0004](0004-src-layout-installable-package.md) | The framework is an installable package using a src layout |
| [0005](0005-allure-plus-junit.md) | Allure for humans, JUnit XML for machines |
| [0006](0006-opt-in-database-validation.md) | Database validation is opt-in and skips loudly |
