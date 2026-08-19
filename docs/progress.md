# Build progress log

The single place that answers **"what has actually been done, and what has actually been proved?"**

Verification vocabulary, used strictly:

| Marker | Meaning |
|---|---|
| ✅ **VERIFIED** | A command was executed in this repository and its output was observed |
| ⚠️ **NOT VERIFIED** | Written and reviewed, but not executed — the reason is always given |
| ⬜ **NOT STARTED** | Planned, no code yet |

No timing, coverage, pass-rate or "improvement" figure appears anywhere in this repository until it
comes from a real measured run (Phase 15).

---

## Machine this was built on

Recorded because "works on my machine" is only useful if the machine is written down.

| Item | Value | How it affected decisions |
|---|---|---|
| OS | Windows 11 Home Single Language 26200 | Scripts provided as `.ps1` **and** `.sh`; no Makefile |
| Python | 3.14.2 and **3.11.4** installed | Framework targets 3.11 — 3.14 is ahead of the plugin ecosystem |
| PostgreSQL | **18.1, running as a service on :5432** (scram-sha-256) | Local DB work possible immediately, before Docker |
| Java | OpenJDK 25.0.1 | Allure CLI can render reports locally |
| Node | 24.13.0 | Not required; an alternative route to the Allure CLI |
| Docker | **Engine 29.7.2 inside WSL2** (Compose v5.5.0, buildx v0.36.1) | Installed without elevation; see [ADR 0008](adr/0008-docker-engine-in-wsl2.md). Phases 10–12 unblocked |
| Free disk (C:) | ~32 GB (was 9.1 GB) | Still building a lean test image rather than pulling the 2.5 GB official Playwright one — faster CI pulls |

---

## Phase status

| Phase | Title | Status |
|---|---|---|
| 1 | Design & architecture | ✅ Complete — [phase-1-design.md](phase-1-design.md) |
| 2 | Repository structure + configuration | ✅ Complete — [phase-2-repository-and-configuration.md](phase-2-repository-and-configuration.md) |
| 3 | Application under test + database | ✅ Complete — [phase-3-application-under-test.md](phase-3-application-under-test.md) |
| 4 | pytest foundation (logging, artefacts, fixtures) | ✅ Complete — [phase-4-pytest-foundation.md](phase-4-pytest-foundation.md) |
| 5 | API automation layer | ✅ Complete — [phase-5-api-automation.md](phase-5-api-automation.md) |
| 6 | Playwright UI layer | ✅ Complete — [phase-6-playwright-ui.md](phase-6-playwright-ui.md) |
| 7 | Database validation + cross-layer journeys | ✅ Complete — [phase-7-database-validation.md](phase-7-database-validation.md) |
| 8 | Reporting + failure artefacts | ⬜ Next |
| 9 | Parallel execution + markers | ⬜ |
| 10 | Docker | ⬜ |
| 11 | Jenkins | ⬜ |
| 12 | GitHub Actions | ✅ Complete — [phase-12-github-actions.md](phase-12-github-actions.md) |
| 13 | Refactor + code quality pass | ⬜ |
| 14 | README + diagrams | ⬜ |
| 15 | Execution + measurement | ⬜ |
| 16 | GitHub presentation | ⬜ |
| 17 | LinkedIn presentation | ⬜ |
| 18 | Interview preparation | ⬜ |

---

## Phase 1 — Design & architecture ✅

**Delivered:** [docs/phase-1-design.md](phase-1-design.md) — project concept, domain and business
rules, black-box architecture, technology decisions with rejected alternatives, the test pyramid as
it applies to a black-box SDET, a **69-case test matrix** with IDs and priorities, CI/CD strategy,
reporting strategy, test-data strategy, parallelism strategy, flaky-test policy, failure-debugging
strategy, environment strategy, directory structure with justification, design patterns and their
boundaries, an 11-item risk register, and a senior-reviewer self-critique.

Nothing to verify — it is a design document.

---

## Phase 2 — Repository structure + configuration ✅

### What was built

| File | Purpose |
|---|---|
| `pyproject.toml` | Single source for dependencies, pytest, ruff and mypy configuration |
| `src/claimdesk_qa/config/settings.py` | Typed, validated, secret-safe configuration object |
| `src/claimdesk_qa/config/__init__.py` | Public surface of the config package |
| `tests/framework/test_settings.py` | 31 unit tests covering the configuration layer |
| `tests/framework/conftest.py` | Autouse fixture isolating tests from the local environment |
| `.env.example` | Documented template for every configuration value |
| `.gitignore` · `.gitattributes` · `.editorconfig` | Secret exclusion, line-ending control, editor consistency |
| `.pre-commit-config.yaml` | Formatting and private-key detection before commit |
| `scripts/bootstrap.ps1` | One-command setup for a fresh clone |
| `scripts/quality.ps1` · `scripts/quality.sh` | Local mirror of the CI quality gate |
| `docs/adr/0001`–`0006` | Architecture Decision Records |

### Verification — commands actually run, output actually observed

| Check | Command | Result |
|---|---|---|
| Package installs editable | `python -m pip install -e ".[dev]"` | ✅ **VERIFIED** — `Successfully installed claimdesk-qa-0.1.0` |
| Dependency resolution | (same) | ✅ **VERIFIED** — playwright 1.62.0, pytest 9.1.1, pydantic 2.13.4, psycopg 3.3.4, allure-pytest 2.16.0, xdist 3.8.0, rerunfailures 16.6, ruff 0.16.3, mypy 1.20.2 |
| Framework imports from tests | `pytest -m framework` | ✅ **VERIFIED** |
| Linting | `ruff check .` | ✅ **VERIFIED** — `All checks passed!` |
| Formatting | `ruff format --check .` | ✅ **VERIFIED** — `7 files already formatted` |
| Static typing (strict) | `mypy` | ✅ **VERIFIED** — `Success: no issues found in 5 source files` |
| Unit tests | `pytest -m framework -q` | ✅ **VERIFIED** — `31 passed in 0.35s` |
| Marker registration | `--strict-markers` in `addopts` | ✅ **VERIFIED** — an unregistered marker now fails the run |

⚠️ **NOT VERIFIED in Phase 2:** the ruff black-box import ban (`TID251`) has no code to catch yet —
it is exercised for real in Phase 3 when `app/claimdesk/` exists. The `pre-commit` hooks are
configured but `pre-commit install` has not been run (it requires a git repository, created at the
end of this phase).

### Problems found and fixed during the phase

Recorded because the fixes are more instructive than the final state.

1. **Editable install produced no import hook.** The first `pip install -e .` ran while
   `src/claimdesk_qa/` was still empty, so hatchling generated no `.pth` file and
   `import claimdesk_qa` failed. Fixed by reinstalling after the package existed. *Lesson: an
   editable install is a build, and a build of nothing produces nothing.*
2. **`README.md` was referenced by `pyproject.toml` before it existed**, which failed metadata
   generation with a message pointing at pip rather than at the real cause.
3. **The default configuration was invalid.** `DB_ENABLED` defaulted to `true`, so a fresh clone
   could not even load settings without a database password — 11 unit tests failed and were *right*
   to fail. The design was changed rather than the tests: database validation is now opt-in
   ([ADR 0006](adr/0006-opt-in-database-validation.md)). *Lesson: when your own tests reject your
   design, that is the framework working.*
4. **`PT004` is a removed ruff rule**, which produced a warning on every run. Removed.

---

## Phase 3 — Application under test + database ✅

### What was built

| Area | Detail |
|---|---|
| Disposable database | `scripts/local_db.ps1` — a project-local PostgreSQL cluster in `.pgdata/` on port 55432, with `start`/`stop`/`status`/`reset`/`psql` |
| Two database roles | `claimdesk_app` owns the schema; `claimdesk_qa_ro` holds `SELECT` and nothing else |
| Domain rules | Status machine, adjuster approval limit (5000.00, inclusive), ownership and coverage-limit validation |
| Schema | `users`, `policies`, `claims`, `claim_events` (append-only), `payouts` (unique per claim); money as `NUMERIC(12,2)` |
| REST API | 16 endpoints under `/api/v1` + `/health` and `/health/ready` |
| HTML interface | Login, dashboard, claims list with async filtering, claim form, claim detail with actions, admin users |
| Seed data | 4 users, 3 policies, 24 claims across all statuses with realistic audit trails |
| Application unit tests | 58 tests in `app/tests/test_domain.py` |

### Verification — commands run, output observed

| Check | Result |
|---|---|
| Database cluster starts | ✅ **VERIFIED** — listening on 127.0.0.1:55432 |
| Roles and database created | ✅ **VERIFIED** — `claimdesk_app`, `claimdesk_qa_ro`, database `claimdesk` |
| Application starts | ✅ **VERIFIED** — `Schema ensured and seed data applied`, `Application startup complete` |
| Liveness / readiness | ✅ **VERIFIED** — `{"status":"ok"}` / `{"status":"ready","database":"reachable"}` |
| **End-to-end behaviour** | ✅ **VERIFIED** — **54/54 checks passed** across auth, RBAC, CRUD, validation, boundaries, the state machine, the HTML interface and the database |
| Application unit tests | ✅ **VERIFIED** — `58 passed in 0.16s` |
| Framework unit tests | ✅ **VERIFIED** — `32 passed in 0.35s` |
| Linting | ✅ **VERIFIED** — `All checks passed!` (after fixing 8 real findings) |
| Formatting | ✅ **VERIFIED** — `37 files already formatted` |
| Static typing (strict) | ✅ **VERIFIED** — `Success: no issues found in 24 source files` |
| **Black-box import ban fires** | ✅ **VERIFIED** — a file importing `claimdesk` from `tests/` was rejected with `TID251`; the application importing itself still passes |
| **Read-only role cannot write** | ✅ **VERIFIED** — `INSERT` as `claimdesk_qa_ro` fails with `InsufficientPrivilege` |
| Audit trail correctness | ✅ **VERIFIED** — `['DRAFT','SUBMITTED','UNDER_REVIEW','APPROVED','PAID']` recorded for one claim |
| Exactly one payout per claim | ✅ **VERIFIED** — count is 1; a second `pay` returns 409 |
| Passwords stored hashed | ✅ **VERIFIED** — bcrypt hash, plaintext absent |

⚠️ **NOT VERIFIED in Phase 3:** nothing has been run in Docker, in Jenkins or in GitHub Actions; no
browser has been driven yet (Phase 6). The `.pgdata` cluster has only been exercised on this machine.

### Problems found and fixed

| # | Problem | Lesson |
|---|---|---|
| 1 | **A negative auth test passed for the wrong reason.** `GET /claims` with no `Authorization` header returned 200 — because `httpx.Client` had a `session` cookie from an earlier login. `curl` proved the application correctly returns 401. | The most dangerous test defect is the one that *passes*. Recorded as [ADR 0007](adr/0007-no-shared-cookie-jar.md): one client per identity, cookie persistence off |
| 2 | `pg_ctl start` never returned although the server was up and serving | On Windows the server inherits the parent's stdout handle and holds the pipe open. Fixed with `Start-Process -RedirectStandardOutput`. **Read the log before theorising** — it already said "ready to accept connections" |
| 3 | `.env.example` shipped `FAKER_SEED=` (empty) which fails `int` parsing | The documented first step produced a framework that could not start. Fixed, and a test now loads `.env.example` itself so the template can never silently break |
| 4 | Framework unit tests were not hermetic against the `.env` **file** | Clearing environment variables was only half the isolation; tests now `chdir` to a temp directory |
| 5 | Seed emails used `@claimdesk.test` | `email-validator` rejects the RFC 2606 `.test` TLD as special-use, so every login returned 422. Moved to `example.com` |
| 6 | Two `assert`s used for control flow | `python -O` strips them, turning a guard into a silent `None` dereference. Replaced with explicit raises |
| 7 | `next` used as a parameter name | Shadowed the builtin; renamed to `next_url` with `alias="next"` so the URL contract is unchanged |
| 8 | `get_policy` could return `None` where `Policy` was declared | Found by mypy, not by a human. Rewriting as two explicit guards fixed the type and made the non-enumeration rule readable |
| 9 | 53 `B008` warnings on FastAPI's `Depends()` idiom | Configured `extend-immutable-calls` rather than disabling the rule, so B008 still catches genuine mutable defaults elsewhere |

### Deviation from the Phase 1 design

The design named **HTMX** for asynchronous UI behaviour. The implementation uses about 25 lines of
plain JavaScript instead. Same outcome — a real asynchronous partial refresh for Playwright to wait
on, with `aria-busy` toggled around the request — with no vendored library, no CDN dependency and no
build step. Adding a dependency that a few lines of code replace would have contradicted the
project's own rule about unjustified technology.

---

## Phase 4 — pytest foundation ✅

### What was built

| File | Responsibility |
|---|---|
| `src/claimdesk_qa/core/artifacts.py` | Run/test artefact paths, worker-aware, Windows-path-safe |
| `src/claimdesk_qa/core/correlation.py` | Stable per-test `X-Request-Id`, held in a `ContextVar` |
| `src/claimdesk_qa/core/logging.py` | Console + per-worker + per-test logging |
| `src/claimdesk_qa/core/readiness.py` | Readiness polling with an injectable probe and clock |
| `src/claimdesk_qa/core/exceptions.py` | `FrameworkError` separated from `AssertionError` |
| `tests/conftest.py` | Session fixtures, marker enforcement, artefact retention policy |
| `tests/framework/test_artifacts.py` etc. | 38 new unit tests |

### Verification — commands run, output observed

| Check | Result |
|---|---|
| Framework unit tests | ✅ **VERIFIED** — `70 passed in 0.67s` |
| Application unit tests | ✅ **VERIFIED** — `58 passed in 0.16s` |
| Linting / formatting | ✅ **VERIFIED** — `All checks passed!`, `49 files already formatted` |
| Static typing (strict) | ✅ **VERIFIED** — `Success: no issues found in 34 source files` |
| **One run directory under `-n 4`** | ✅ **VERIFIED** — 1 directory, 4 worker logs (`worker-gw0..gw3.log`) |
| **Passing test's artefacts pruned** | ✅ **VERIFIED** |
| **Failing test's artefacts kept** | ✅ **VERIFIED** — `test.log` retained with correlation id `[qa-933749c975]` |
| Report header shows environment | ✅ **VERIFIED** — DB password rendered as `***masked***` |
| Test outside a layer directory | ✅ **VERIFIED** — collection error naming the offender |
| Database disabled | ✅ **VERIFIED** — skip with reason + shouted header line |
| Readiness against a dead port | ✅ **VERIFIED** — `ServiceNotReadyError` naming the service, attempts, OS error, and blaming the environment |

⚠️ **NOT VERIFIED in Phase 4:** nothing here has run in Docker or CI, and no browser has been driven.

### Problems found and fixed

Three silent failures — none of which made a test fail, all of which destroyed evidence.

| # | Problem | Lesson |
|---|---|---|
| 1 | **The correlation id never reached the log file.** Each handler had its own filter with its own default; filters mutate the *shared* `LogRecord`, so whichever handler ran first stamped its default and later filters left it alone. Logs showed `[-]` | Don't order the handlers — remove the ordering dependency. All filters now read one `ContextVar` |
| 2 | **Moving the filter to the logger deleted log lines entirely.** Logger filters apply only to records logged through that logger *directly*; records from a child logger reach the parent's handlers via `callHandlers`, skipping the parent's filters. `request_id` went missing, the formatter raised `KeyError`, and `logging` swallowed the line | The tidier-looking fix was worse. Filters belong on handlers, where they see every record |
| 3 | **Every per-test log file was empty.** The logger was set to `INFO`, so `DEBUG` records were dropped before any handler saw them | Filter late, at the destination — logger at DEBUG, console at the configured level, files at DEBUG |
| 4 | Artefact paths were relative, so a test that called `chdir` would scatter evidence | Anchored to `pytestconfig.rootpath` |
| 5 | A dead environment blocked for a hard-coded 60s | `READINESS_TIMEOUT_SECONDS` is now configurable — CI needs a cold-start minute, a developer wants three seconds |

All three silent failures now have regression tests named after the failure mode.

---

## Phase 5 — API automation layer ✅

### What was built

| Area | Detail |
|---|---|
| `domain.py` | The framework's own copy of statuses, roles, limits and the transition table (duplicated deliberately — ADR 0002) |
| `api/client.py` | `ApiClient`: one per identity, cookies discarded, mandatory timeouts, correlation header, rolling record of the last 25 exchanges |
| `api/models.py` | Strict contracts — `extra="forbid"`, `Decimal` money |
| `api/services/` | `AuthApi`, `ClaimsApi`, `UsersApi`, `PoliciesApi` |
| `data/` | `ClaimFactory`, `UserFactory`, seeded-account constants |
| `tests/api/` | **157 tests**: auth, CRUD, validation/boundary, authorisation, state machine |

### Verification — commands run, output observed

| Check | Result |
|---|---|
| Full suite, serial | ✅ **VERIFIED** — `229 passed in 11.42s` (72 framework + 157 API) |
| Full suite, `-n 4`, three consecutive runs | ✅ **VERIFIED** — `229 passed` in 6.89s / 6.84s / 7.18s, no flakes |
| Linting / formatting | ✅ **VERIFIED** — `All checks passed!`, `68 files already formatted` |
| Static typing (strict) | ✅ **VERIFIED** — `Success: no issues found in 52 source files` |
| Generated negative matrix | ✅ **VERIFIED** — 30 illegal `(action, status)` pairs, each returning 409 with no state change |
| Approval-limit boundary | ✅ **VERIFIED** — 4999.99 and 5000.00 approved by an adjuster; 5000.01 refused (403) and escalated to admin successfully |
| Cross-tenant access | ✅ **VERIFIED** — 404 (not 403), and the body does not leak the reference |

⚠️ **NOT VERIFIED in Phase 5:** no browser has been driven, and nothing has run in Docker or CI.

### Findings

| # | Finding | Outcome |
|---|---|---|
| 1 | **The suite was ~35× slower than necessary.** 21 auth tests took 48.17s; every request cost ~2.1s *uniformly*, which rules out the application. Measured: `localhost` 2034 ms vs `127.0.0.1` 10 ms — `localhost` resolves to `::1` first and the app binds IPv4 only | One configuration value changed. **48.17s → 1.36s, measured.** A framework problem that looked exactly like an application problem |
| 2 | **Spec/implementation mismatch on withdrawal.** The matrix said `GET` → 404 after DELETE; the app returns 200 with `status=WITHDRAWN` | The **specification** was wrong: `WITHDRAWN` is a published, filterable status, so a 404 on the detail endpoint contradicts the list endpoint. Matrix corrected, test asserts the coherent behaviour |
| 3 | Non-ASCII digits (full-width, Arabic-Indic) are accepted and normalised to the same value | Assessed **low severity** — unambiguous, no rule bypassed. Kept as a characterisation test proving the stored value is exactly right |
| 4 | `Authorization: "Bearer "` is untestable — httpx refuses to send a header with trailing whitespace (RFC 9110) | Case removed with the reason recorded |
| 5 | My own bug: `zip(a, a[1:], strict=True)` always raises — offset slices differ in length by one | Replaced with `itertools.pairwise`, which ruff had already suggested |
| 6 | **A race under `-n 4`**: all workers prune the same run directory, so one's `rmdir` hits a directory another already removed. Seen once, not reproduced in three further runs | Pruning is now concurrency-tolerant, with two regression tests. Cleanup must never fail a run |

---

## Phase 6 — Playwright UI layer ✅

### What was built

| Area | Detail |
|---|---|
| `ui/base_page.py` | Locators as properties (never stored elements), readiness assertions, no sleeps |
| `ui/session.py` | Browser session from an API login — `storage_state` injection, no login form |
| `ui/components/navigation.py` | The header, composed by six pages rather than inherited |
| `ui/pages/` | Login, dashboard, claims list, claim form, claim detail, admin users |
| `tests/ui/conftest.py` | Per-role browser contexts, tracing, failure artefacts |
| `tests/ui/` | **32 tests**: sign-in, table, form, workflow, authorisation |

### Verification — commands run, output observed

| Check | Result |
|---|---|
| Full suite, serial | ✅ **VERIFIED** — `261 passed in 21.04s` |
| Full suite, `-n 4`, five consecutive runs | ✅ **VERIFIED** — `261 passed` in 12.81 / 13.46 / 12.86 / 13.10 / 13.20 s |
| Linting / formatting | ✅ **VERIFIED** — `All checks passed!` |
| Static typing (strict) | ✅ **VERIFIED** — `Success: no issues found in 69 source files` |
| Chromium installed | ✅ **VERIFIED** — 114.5 MiB, Playwright 1.62.0 |
| **Failure artefacts** | ✅ **VERIFIED** — deliberate failure produced `trace.zip` (322,840 bytes, 24 entries incl. `trace.network` + 6 filmstrip frames), a valid PNG screenshot, page HTML and the per-test log |
| Artefact path truncation | ✅ **VERIFIED** — long node id truncated with hash suffix `_12a9d708`, as Phase 4 specified |
| Passing tests leave no trace | ✅ **VERIFIED** — traces stopped without a path are discarded |

⚠️ **NOT VERIFIED in Phase 6:** only Chromium is installed — Firefox and WebKit are Phase 9. Nothing has run in Docker or CI.

### Findings

| # | Finding | Outcome |
|---|---|---|
| 1 | **My own suite broke its own parallel-safety rule.** `test_the_table_paginates` failed ~50% of the time at `-n 4`, never serially. The table sorts newest-first, so claims created by other workers between the page-one and page-two requests shifted a row across the boundary | The assertion was correct; the **premise** was wrong — you cannot paginate a data set being written to. Scoped to the immutable seeded corpus; five consecutive `-n 4` runs then passed. The API pagination test was latently flaky for the same reason (random references can insert anywhere even in a sorted list) and was scoped the same way |
| 2 | The `anonymous_page` fixture used `yield` with no teardown | Converted to `return`; the context factory owns all teardown, so splitting cleanup would risk discarding a trace before the failure hook saved it |
| 3 | Port 8000 was still held by the previous session's server | Not a defect — noted because it is why the readiness probe exists rather than a `sleep` |

---

## Phase 7 — Database validation + cross-layer journeys ✅

### What was built

| Area | Detail |
|---|---|
| `db/connection.py` | Read-only connection (role grants **and** `read_only`), parameterised queries only, recorded SQL for failure attachment |
| `db/rows.py` | Typed row dataclasses; money as `Decimal` end to end |
| `db/queries.py` | Query objects — SQL in one place, tests read as intent |
| `tests/_fixtures/` | Shared fixtures extracted from three duplicated conftests; each layer conftest fell from ~120 lines to 15 |
| `tests/db/` | **28 tests**: persistence, audit trail, payouts, integrity, schema assertions |
| `tests/e2e/` | **4 journeys** crossing browser → API → database |

### Verification — commands run, output observed

| Check | Result |
|---|---|
| Full suite, serial | ✅ **VERIFIED** — `293 passed in 23.60s` |
| Full suite, `-n 4`, five consecutive runs | ✅ **VERIFIED** — `293 passed` in 15.14 / 16.86 / 14.83 / 14.88 / 15.04 s |
| Linting / formatting | ✅ **VERIFIED** — `All checks passed!` |
| Static typing (strict) | ✅ **VERIFIED** — `Success: no issues found in 83 source files` |
| **Read-only role cannot write** | ✅ **VERIFIED** — UPDATE, DELETE, INSERT and TRUNCATE all refused |
| Money stored as exact NUMERIC(scale 2) | ✅ **VERIFIED** — asserted against `information_schema.columns` |
| Payout uniqueness exists as a constraint | ✅ **VERIFIED** — read from `pg_catalog` |
| Passwords hashed, never plaintext | ✅ **VERIFIED** — bcrypt prefix, zero plaintext matches |

⚠️ **NOT VERIFIED in Phase 7:** nothing has run in Docker or CI; no Allure report has been generated yet.

### Findings

| # | Finding | Outcome |
|---|---|---|
| 1 | **`information_schema` is privilege-filtered.** The constraint query returned 0 rows for the read-only role. Measured: read-only via `information_schema` → **0**; via `pg_catalog` → **16**; owner via `information_schema` → **16** | Switched to `pg_catalog`. The trap is that the test **would have passed against a superuser** — least privilege is what exposed it |
| 2 | **The same concurrency bug, twice, in two layers.** `test_a_rejected_write_leaves_no_row` compared a global `count(*) WHERE status='DRAFT'` before and after; other workers create drafts in between. Failed 2 runs in 3 at `-n 4` | Scoped to the test's own marker. Stated as a **rule** rather than a second fix: *a test may assert an invariant globally, never an aggregate* — an invariant holds regardless of who else is writing; an aggregate is a fact about a shared database |
| 3 | **A live bearer token was written into `artifacts/`**, which CI archives and publishes | Caught by re-reading the file, not by a failing test. The cookie is now injected directly into the browser context and never touches disk |
| 4 | `customer_claims` existed in three conftests | Extracted to `tests/_fixtures/` as pytest plugins. The trigger was writing the fourth copy: three is a pattern, four is a problem |

---

## Phase 12 — GitHub Actions ✅ (brought forward)

Brought forward from its planned position because Docker was installed and CI was the deliverable
that makes the repository's state independently checkable rather than something I assert.

| Workflow | Purpose |
|---|---|
| `tests.yml` | PR gate — `quality` (lint, types, framework tests; ~45 s, no services) then `suite` (API, DB, UI, E2E against PostgreSQL 18) |
| `nightly.yml` | Full regression across Chromium, Firefox and WebKit, `fail-fast: false` |

### Verification — real runs, watched to completion

| Run | Result |
|---|---|
| Attempt 1 | ❌ **VERIFIED FAILURE** — `Permission denied` (exit 126); the executable bit was never in the commit |
| Attempt 2 | ✅ **VERIFIED** — `quality` 43 s; `suite` reported **`293 passed in 18.55s`** |
| Attempt 3 | ✅ **VERIFIED** — job total **752 s → 343 s** after splitting the browser install |

Artefacts published: `test-results` (1.5 MB — JUnit XML + Allure results), `junit-quality`. On
failure, `failure-artefacts` carries traces, screenshots, page HTML and logs.

**Nightly, dispatched manually and watched to completion — all three engines green:**

| Browser | Result |
|---|---|
| Chromium | ✅ **VERIFIED** — `293 passed in 17.98s` |
| Firefox | ✅ **VERIFIED** — `293 passed in 21.62s` |
| WebKit | ✅ **VERIFIED** — `293 passed in 26.60s` |

The suite is genuinely cross-browser: the same 293 tests pass on all three engines with no
browser-specific branching anywhere in the framework.

### CI measurements

| Step | Run 2 (cold) | Run 3 (split) | Run 4 (warm cache) |
|---|---|---|---|
| Browser install (combined) | **684 s** | — | — |
| apt system libraries | — | **249 s** | **13 s** |
| browser download | — | **11 s** | ~0 s |
| Test execution | 21 s | 19 s | 21 s |
| **Job total** | **752 s** | **343 s** | **78 s** |

⚠️ **Do not read that as a 10x win from caching.** The cache explains only the 11 s download. The
apt step fell from 249 s to 13 s with *identical* configuration — runner variance, not a change I
made. A single before/after pair in CI is not a measurement when the dominant cost varies
nineteen-fold between identical runs.

### Findings

| # | Finding | Outcome |
|---|---|---|
| 1 | **`chmod +x` locally changed nothing in the commit.** Git on Windows does not record the executable bit, so the runner checked out a non-executable script | `git update-index --chmod=+x`. A Windows-to-Linux crossing bug that local testing cannot surface — the script runs fine via `bash script.sh` |
| 2 | A failing diagnostic step added a second red X that obscured the real failure | `tail ... \|\| echo` — a step whose job is to explain a failure must never be able to cause one |
| 3 | **The cache I added costs more than it saves.** Browser download is 11 s; writing the cache is 28 s | Recorded rather than quietly deleted. I cached before measuring, which was the wrong order |
| 4 | **CI timings are noisy enough to fake a result.** The same apt step took 249 s and then 13 s with no configuration change | The honest claim is narrow: splitting the step revealed *where* the cost is. Attributing the drop to my cache would have been taking credit for the weather |

---

## Clean-clone verification ✅

The original brief asked whether the project is *"reproducible from a clean machine"*. Answered by
cloning the **published** repository into a fresh directory — not by re-running the working tree —
and building it from nothing.

| Step | Result |
|---|---|
| `git clone` the public repo | ✅ **VERIFIED** — 124 files, no `.env` present |
| `py -3.11 -m venv` + `pip install -e ".[dev,app]"` | ✅ **VERIFIED** |
| `cp .env.example .env`, set two passwords | ✅ **VERIFIED** — the documented first step works |
| `pytest -m framework` | ✅ **VERIFIED** — `72 passed`, no application required |
| `pytest -m "api or db or e2e"` | ✅ **VERIFIED** — `189 passed` |
| `pytest -m ui` | ✅ **VERIFIED** — `32 passed` |
| `pytest` (everything) | ✅ **VERIFIED** — **`293 passed in 26.21s`** |
| `ruff check` · `ruff format --check` · `mypy` | ✅ **VERIFIED** — clean, 103 files formatted, 83 typed |

### Two findings, and the first was serious

| # | Finding | Outcome |
|---|---|---|
| 1 | **The published repository could not run its own browser suite.** The Phase 7 refactor renamed three fixtures; the conftest changes were committed but `tests/ui/*.py` were never staged. My working tree passed 293 tests because it had the renames — the commit did not | Fixed and pushed. The lesson is procedural: **staging selectively across several commits means a green local run proves nothing about what was committed.** Verification now happens against a clean clone of the pushed commit, which is the only check that would have caught it |
| 2 | `pip install` failed with `Could not find a suitable TLS CA certificate bundle` | `CURL_CA_BUNDLE` was set to a PostgreSQL path that does not exist. An environment problem, not a project one — but it fails at the first documented step, so it is now in the README's troubleshooting section |

Also worth noting: my own verification script printed `install ok` after the install had **failed**,
because `set -e` does not trigger on a command whose output is piped to `tail`. The same shape of
mistake as an earlier `&&`-after-`head`. Exit codes are now checked explicitly.

---

## Open items carried forward

| # | Item | Blocks | Owner action |
|---|---|---|---|
| 1 | ~~Install Docker~~ | — | ✅ Done — Docker Engine 29.7.2 installed inside WSL2 with Compose and buildx, daemon enabled under systemd. `postgres:18-alpine` and `python:3.12-slim` pre-pulled and verified |
| 2 | ~~Create the local database + roles~~ | — | ✅ Done — `scripts/local_db.ps1` builds a disposable cluster; your existing PostgreSQL service was never touched and no superuser password was needed |
| 3 | ~~`playwright install chromium`~~ | — | ✅ Done — Chromium 114.5 MiB installed, Playwright 1.62.0 |
| 4 | ~~Free disk space on C:~~ | — | ✅ Resolved — ~32 GB free |
| 5 | ~~Add `app` to the mypy `files` list~~ | — | ✅ Done — mypy now checks `src`, `tests` and `app/claimdesk` |
