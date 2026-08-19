<!--
This template is short on purpose. A checklist nobody can complete honestly is a
checklist everybody ticks without reading.
-->

## What this changes

<!-- One or two sentences. The commit message carries the detail. -->

## Why

<!-- The problem, not the solution. If this fixes a defect, say how it was found:
     a failing test, a CI run, a code read. "Found by" is the most useful line in
     most pull requests. -->

## How it was verified

<!-- Paste the command and its OUTPUT. Not "tests pass" - the line that says so.

     pytest -q                    -> 351 passed in 29.84s
     ./scripts/quality.ps1        -> Quality gate passed.
-->

```
```

## Checks

- [ ] `.\scripts\quality.ps1` passes (ruff, ruff-format, mypy, framework tests)
- [ ] The full suite passes, or the failures are explained above
- [ ] New behaviour has a test **named after the failure it prevents**
- [ ] Nothing measured is claimed without the command that measured it
- [ ] No secret, token or password in the diff — including in test data and artefacts

## For a new or changed test

- [ ] It asserts only on data it created, or on an invariant that holds regardless
      of who else is writing (**never** an aggregate over a shared database)
- [ ] It has exactly one layer marker, from its directory
- [ ] A refusal test also asserts the resource **did not change**
- [ ] Passes at `-n 4` as well as serially
