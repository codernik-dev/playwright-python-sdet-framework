# ADR 0001 — Python + pytest + Playwright as the core stack

**Status:** Accepted · **Date:** 2026-08-19 · **Phase:** 2

## Context

The framework must cover UI, API and database testing in one codebase, be maintainable by a small
team, and run identically on a Windows workstation and a Linux CI runner.

## Decision

Python 3.11 (local) / 3.12 (container), pytest as the runner, Playwright for the browser layer.

## Why pytest rather than unittest or Robot Framework

* **Fixtures are real dependency injection** — scoped, composable, and finalised even when a test
  fails. This removes the need for `setUp`/`tearDown` inheritance hierarchies entirely.
* **Parametrisation is first-class**, which is what makes boundary and negative testing cheap.
* **Markers** give free-form suite selection (`-m "smoke and not ui"`) with no extra tooling.
* **The plugin ecosystem** (xdist, rerunfailures, allure) is where the industry actually is.

Robot Framework buys readability for non-programmers, at the cost of debuggability and refactoring.
There is no non-programmer consumer of these tests, so the trade is a loss.

## Why Playwright rather than Selenium

* **Auto-waiting actionability checks.** Playwright waits for an element to be attached, visible,
  stable, enabled and able to receive events before acting. Most Selenium flakiness is a missing
  explicit wait; Playwright removes the category rather than the individual bugs.
* **Browser contexts** are isolated sessions inside one browser process — far cheaper than a browser
  per test, which is what makes parallel UI runs affordable.
* **`storage_state`** lets us authenticate once via the API and inject the session, so UI tests do
  not pay for a login they are not testing.
* **The trace viewer** gives a time-travel DOM snapshot, network log and console for a failed CI run.
  Nothing in the Selenium ecosystem is equivalent out of the box.
* **One dependency, three engines** (Chromium, Firefox, WebKit) with no driver-binary management.

## When Selenium would still be the right answer

* A large existing Selenium estate — rewriting working tests is rarely a good use of budget.
* Real device clouds / Selenium Grid infrastructure already paid for.
* Browsers or versions Playwright does not support (legacy Internet Explorer, some embedded engines).
* A team whose entire skill set is Selenium, where the migration cost exceeds the flakiness cost.

This is a judgement about *this* project, not a claim that Selenium is obsolete.

## Consequences

* Playwright's Python API is sync-wrapped; async gives no benefit here and costs readability.
* Browser binaries (~a few hundred MB) must be installed with `playwright install`.
* The team must learn Playwright locators rather than reusing Selenium habits (`By.XPATH` everywhere).
