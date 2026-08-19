# ADR 0005 — Allure for humans, JUnit XML for machines

**Status:** Accepted · **Date:** 2026-08-19 · **Phase:** 2 (implemented in Phase 8)

## Context

A test report has two distinct audiences, and no single format serves both well:

* **A human** debugging a red build needs the assertion, the screenshot, the trace, the request and
  response, the environment, and the history of whether this test has been failing for a week.
* **A CI system** needs a machine-readable result file so it can annotate the build, show per-test
  history, and fail the job.

## Decision

Emit both.

* **Allure** is the human-facing report: steps, attachments, categories, severity, an environment
  block, and trend history across runs. Jenkins has a first-class Allure plugin; GitHub Actions
  publishes the nightly report to GitHub Pages so it is viewable without cloning anything.
* **JUnit XML** (`--junitxml`) is the machine-facing result: consumed by the Jenkins `junit` step and
  by GitHub Actions reporters.

## Rejected alternatives

* **Playwright's HTML report** — does not exist for Python. It is a feature of the JavaScript
  Playwright *test runner*. In Python, Playwright provides artefacts (trace, video, screenshot); the
  report layer is pytest's job. Assuming otherwise is a common and revealing mistake.
* **pytest-html only** — a single self-contained file with no Java requirement, but no attachments
  model, no history, and no trends. Kept as an optional `[html]` extra for machines without a JVM.
* **Allure only** — leaves the CI system unable to tabulate results natively.

## Consequences

* Rendering an Allure report requires Java and the Allure CLI. Documented, and installed in CI.
* Two reporting configurations to maintain; both are a handful of lines.
* `artifacts/allure-results/` must be cleaned between runs or results accumulate across runs.
