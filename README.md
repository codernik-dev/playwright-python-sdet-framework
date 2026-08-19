# ClaimDesk QA — End-to-End SDET Automation Framework

> **Status: under construction.** This README is expanded in Phase 14.
> Live build progress: **[docs/progress.md](docs/progress.md)**.
> No performance, coverage or pass-rate numbers appear anywhere in this repository
> until they have been produced by a real run (Phase 15).

A production-style test automation framework in Python that exercises a containerised
insurance-claims application through **three independent layers**:

| Layer | Tooling | Proves |
|---|---|---|
| **UI** | Playwright + Page Objects | A human can actually complete the workflow in a browser |
| **API** | httpx + Service Objects | The business rules hold, fast and deterministically |
| **DB** | psycopg + read-only SQL | The persisted state, audit trail and money are correct |

## The application is a fixture. The framework is the deliverable.

`app/` contains **ClaimDesk**, a small FastAPI + PostgreSQL claims portal. It exists only to give the
framework something realistic to test — something with authentication, roles, a state machine,
monetary boundaries and an audit trail.

The framework **never imports application code**. It reaches the application only over HTTP and SQL,
exactly as an SDET would in a real job — and that boundary is **enforced by the linter**, not by good
intentions:

```toml
# pyproject.toml
[tool.ruff.lint.flake8-tidy-imports.banned-api]
"claimdesk".msg = "The test framework must NEVER import the application under test."
```

## Documentation

| Document | What it covers |
|---|---|
| [docs/progress.md](docs/progress.md) | **Build log — what is done, what is verified, what is not** |
| [docs/phase-1-design.md](docs/phase-1-design.md) | Full design: architecture, test strategy, 69-case test matrix, risks |
| [docs/adr/](docs/adr/) | Architecture Decision Records — why each choice was made |

## Quick start (local, Windows)

```powershell
# 1. Create the virtual environment and install everything
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev,app]"

# 2. Configure
Copy-Item .env.example .env

# 3. Start a disposable, project-local PostgreSQL cluster on port 55432.
#    It does not touch any PostgreSQL server you already run.
.\scripts\local_db.ps1 start

# 4. Start the application under test
python -m uvicorn claimdesk.main:app --app-dir app --port 8000

# 5. In a second terminal: prove it works
curl http://localhost:8000/health/ready     # {"status":"ready","database":"reachable"}
pytest -m framework -q                      # the framework's own unit tests
pytest app/tests -q                         # the application's own unit tests
```

Then open <http://localhost:8000/login> and sign in as `customer@example.com` /
`Passw0rd!seed`. Interactive API docs are at <http://localhost:8000/docs>.

Useful commands:

```powershell
.\scripts\local_db.ps1 reset   # destroy all local test data and rebuild
.\scripts\quality.ps1          # the exact CI gate: ruff + mypy + unit tests
```

Browsers, Docker, Jenkins and GitHub Actions are documented in
[docs/progress.md](docs/progress.md) as they are built.

## Technology

Python 3.11 · pytest · Playwright · httpx · pydantic · PostgreSQL 18 · psycopg 3 · Allure ·
pytest-xdist · Docker · Jenkins · GitHub Actions · Ruff · mypy

## Author

Techsapphire — QA / Test Automation Engineer moving toward SDET.
