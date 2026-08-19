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
| Docker | **not installed** | Phases 10–12 blocked until installed; WSL2 + Ubuntu already present, so installation is straightforward |
| Free disk (C:) | ~9.1 GB | Rules out the 2.5 GB official Playwright image; we build a lean image instead |

---

## Phase status

| Phase | Title | Status |
|---|---|---|
| 1 | Design & architecture | ✅ Complete — [phase-1-design.md](phase-1-design.md) |
| 2 | Repository structure + configuration | ✅ Complete — [phase-2-repository-and-configuration.md](phase-2-repository-and-configuration.md) |
| 3 | Application under test + database | ⬜ Next |
| 4 | pytest foundation (logging, artefacts, fixtures) | ⬜ |
| 5 | API automation layer | ⬜ |
| 6 | Playwright UI layer | ⬜ |
| 7 | Database validation layer | ⬜ |
| 8 | Reporting + failure artefacts | ⬜ |
| 9 | Parallel execution + markers | ⬜ |
| 10 | Docker | ⬜ |
| 11 | Jenkins | ⬜ |
| 12 | GitHub Actions | ⬜ |
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

## Open items carried forward

| # | Item | Blocks | Owner action |
|---|---|---|---|
| 1 | Install Docker Desktop (WSL2 backend is already present) | Phases 10–12 | Yours |
| 2 | Create the local database + roles | Phase 3 verification | `scripts/setup_local_db.ps1` (Phase 3) — needs your PostgreSQL superuser password, entered by you, never stored |
| 3 | `playwright install chromium` (~200 MB) | Phase 6 | Runs during Phase 6 |
| 4 | Free disk space on C: (~9 GB left) | Phase 10 image builds | Monitor |
| 5 | Add `app` to the mypy `files` list | Phase 3 | Done as part of Phase 3 |
