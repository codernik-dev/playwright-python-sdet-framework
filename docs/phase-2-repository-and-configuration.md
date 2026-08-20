# Phase 2 - Repository structure and configuration

> Teaching document. For each component: the problem it solves, the design decision, what the code
> does, how to run it, how to prove it works, and the interview questions it earns you.

---

## Component 1 - `pyproject.toml`: one file instead of five

### The problem it solves

A typical automation repository accumulates `requirements.txt`, `requirements-dev.txt`, `pytest.ini`,
`setup.cfg`, `.flake8`, `.isort.cfg` and `mypy.ini`. Seven files, three formats, and no mechanism
stopping them from disagreeing. When the CI pipeline lints with one config and the developer's IDE
lints with another, the pipeline becomes something people fight rather than trust.

### The decision

Everything in `pyproject.toml`: dependencies, packaging, pytest, ruff and mypy.

### The parts that matter

**Dependencies are grouped by intent, and the application is deliberately quarantined:**

```toml
dependencies = [ ... the framework needs these ... ]

[project.optional-dependencies]
dev = ["ruff", "mypy", "pre-commit", "types-PyYAML"]
app = ["fastapi", "uvicorn[standard]", "sqlalchemy", "jinja2", "pyjwt", "bcrypt"]
```

The application under test is an **optional extra**. CI installs the framework without it. That
makes the black-box boundary visible in the dependency manifest itself, not just in a policy
document - a reviewer sees it in the first file they open.

**Version ranges, not exact pins:**

```toml
"pytest>=8.3,<10"
```

Lower bound = the oldest version whose features we use. Upper bound = the next major, because that is
where breaking changes are allowed to live. Exact pins in `pyproject.toml` make a library
uninstallable next to anything else; reproducibility belongs in a lock file generated from a real
resolution, which Phase 12 adds for CI.

**pytest configuration where a typo cannot hide:**

```toml
addopts = ["-ra", "--strict-markers", "--strict-config", "--import-mode=importlib", "--showlocals"]
```

| Flag | Why it is there |
|---|---|
| `--strict-markers` | `@pytest.mark.smoek` currently does nothing at all - the test silently drops out of the smoke suite. With this flag it is a hard error. This one flag prevents an entire class of "we thought it was covered". |
| `--strict-config` | The same protection for typos in `pyproject.toml` itself |
| `--import-mode=importlib` | Modern import semantics that work with the `src` layout and behave identically in an IDE, a terminal and CI |
| `-ra` | A summary of every non-passing outcome, including the *reason* for each skip - so a skipped database suite is visible, not invisible |
| `--showlocals` | Local variables in the traceback. This is why secrets must be `SecretStr` |

**Warnings are errors:**

```toml
filterwarnings = ["error", "ignore::DeprecationWarning:allure_commons.*", ...]
```

A `DeprecationWarning` from a dependency is advance notice that a future upgrade will break the
suite. Treating warnings as errors converts that notice into a task with a date, rather than a line
of noise nobody reads. Known-noisy third-party warnings are silenced *by module*, never globally.

**Markers are a taxonomy, not a pile of labels.** Every test carries exactly one *layer* marker
(`api`, `ui`, `db`, `e2e`, `framework`), at least one *suite* marker (`smoke`, `regression`), and any
number of *intent* markers (`negative`, `boundary`, `authz`, `contract`, `integrity`). That structure
is what makes `-m "api and boundary and not slow"` a genuinely useful command instead of a party
trick.

### How to run it

```powershell
pip install -e ".[dev]"     # install framework + tooling
pytest --markers            # list every registered marker with its description
pytest --collect-only -q    # what would run, without running it
```

---

## Component 2 - The black-box boundary, enforced by the linter

### The problem it solves

The application under test lives in this repository. Sooner or later somebody writes:

```python
from claimdesk.domain import ClaimStatus  # tempting, and fatal

assert response.json()["status"] == ClaimStatus.APPROVED
```

That assertion cannot fail for the reason you care about. If a developer renames the serialised value
from `APPROVED` to `Approved`, the constant changes too, both sides move together, and the test stays
green while every API consumer in production breaks. The test now proves only that the code equals
itself.

### The decision

Ban the import mechanically:

```toml
[tool.ruff.lint.flake8-tidy-imports.banned-api]
"claimdesk".msg = "The test framework must NEVER import the application under test."
```

Runs in pre-commit and in the CI gate. A violation cannot be merged.

### The consequence people argue with

Status names and the approval limit are now duplicated between the application and the tests. That
duplication is **the point**. The test's copy is the *specification*; the application's copy is the
*implementation*. When they diverge, a test fails - which is the entire purpose of the exercise.

> **Interview soundbite:** *"Sharing constants between the tests and the application converts every
> contract regression into a silent pass. I duplicate deliberately and let the linter enforce it."*

---

## Component 3 - `src/` layout and an installable package

### The problem it solves

Root-level `pages/` and `utils/` folders rely on pytest putting the repository root on `sys.path`.
That breaks in four predictable ways: name collisions with the application's packages, `sys.path`
hacks creeping into `conftest.py`, code that is unimportable outside pytest, and imports resolving
differently in an IDE than in CI.

### The decision

`src/claimdesk_qa/`, installed with `pip install -e .`. Tests import it exactly like any third-party
library. Full reasoning in [ADR 0004](adr/0004-src-layout-installable-package.md).

### What went wrong while building it (and what it teaches)

The first `pip install -e .` ran while `src/claimdesk_qa/` was still an empty directory. It reported
success, but hatchling had nothing to map, so no import hook was written and `import claimdesk_qa`
failed at test collection. **An editable install is a build; a build of nothing produces nothing.**
Reinstalling after the package had content fixed it.

Then the install failed a second time with `metadata-generation-failed` - because `pyproject.toml`
declared `readme = "README.md"` and that file did not exist yet. The error pointed at pip. The cause
was five lines up in my own manifest. That gap between *where an error is reported* and *where it is
caused* is the single most useful thing to internalise about debugging build tooling.

---

## Component 4 - `Settings`: configuration as a validated object

### The problem it solves

The naive approach:

```python
base_url = os.environ["BASE_URL"]  # KeyError, 20 minutes into a CI run
timeout = int(os.getenv("TIMEOUT", 15))  # ValueError if someone writes "15s"
url = os.getenv("BASE_UR1")  # typo -> None -> "None/api/v1" -> confusing 404
```

Three separate failure modes, all discovered late, none of them saying what is actually wrong. The
third is the worst: it does not crash, it produces a *wrong* result that looks like an application
bug and costs an afternoon.

### The decision

One frozen, validated `Settings` object built at session start. Precedence: **real environment
variables > `.env` file > defaults** - which is precisely what lets the identical code run locally
from a file and in CI from injected secrets, with no branching.

### The five design decisions worth defending

**1. Validate at session start, not at point of use.**

```python
http_timeout_seconds: float = Field(default=15.0, gt=0, le=300)
db_port: int = Field(default=5432, ge=1, le=65535)
```

A misconfiguration now fails before the first test, with a message naming the variable and the
constraint. It never surfaces as a mysterious failure inside an unrelated test 20 minutes later.

**2. Secrets are `SecretStr`, and masking is a first-class operation.**

`--showlocals` prints local variables into the failure traceback, and CI logs are frequently public.
A plain `str` password would eventually end up in one. `SecretStr` renders as `**********`
everywhere, and `masked()` produces the report block:

```python
{"environment": "local", "base_url": "...", "database": "postgresql://claimdesk_qa_ro:***masked***@localhost:5432/claimdesk", ...}
```

Note that secrets are **replaced, not truncated** - a truncated secret is still a leak.

**3. Derive rather than duplicate.** `api_url` defaults to `{base_url}/api/v1`. One value to
configure means two values can never disagree. Override it only when the API genuinely lives
elsewhere.

**4. Normalise inputs at the boundary.** `http://host:8000/` becomes `http://host:8000`, so the
framework can never build `http://host:8000//api/v1`. That double slash produces a 404 that looks
exactly like a routing bug and wastes an hour.

**5. Environment-specific rules live in the model.**

```python
if self.env is Environment.CI and not self.headless:
    object.__setattr__(self, "headless", True)
```

A headed browser on a CI agent waits forever for a display that will never exist. The job does not
fail - it *hangs* until the pipeline timeout, which is a far worse outcome than a clear error.

**6. Frozen.** Configuration cannot drift mid-run, so the environment block in the report is
guaranteed to describe the run that actually happened.

### The design flaw the tests caught

`DB_ENABLED` originally defaulted to `true`. Eleven unit tests failed instantly, because a fresh
clone with no `.env` could not even *load* the configuration - validation rejected the empty
password before a single test ran.

The tests were right and the design was wrong. Database validation is now opt-in
([ADR 0006](adr/0006-opt-in-database-validation.md)), with the skip made deliberately loud so a green
run can never be mistaken for one that validated the database.

> **Interview soundbite:** *"My own framework unit tests rejected my first configuration design. I
> changed the design, not the tests - and wrote down why in an ADR."*

### How to run and prove it

```powershell
pytest -m framework -q                    # 31 tests, no application required
python -c "from claimdesk_qa.config import get_settings; print(get_settings().masked())"
```

Deliberately break it to see the failure quality:

```powershell
$env:DB_ENABLED="true"; $env:DB_PASSWORD=""
python -c "from claimdesk_qa.config import load_settings; load_settings(None)"
# ValidationError: DB_ENABLED is true but DB_PASSWORD is empty. Either set DB_PASSWORD
# (see .env.example) or set DB_ENABLED=false to skip database tests.
```

An error message that tells you both causes *and* both fixes is not a nicety. It is the difference
between a five-second fix and a Slack thread.

---

## Component 5 - Tests for the test framework

`tests/framework/` contains unit tests for framework code. They need no application, no database and
no browser, and run in well under a second.

### Why this exists at all

Framework code is shared by every test in the suite. A silent bug in it - a URL built wrong, a secret
leaked into a report, a value read from the wrong variable - corrupts every result the suite
produces. Everything else in the pyramid rests on this layer being correct.

It is also the cleanest possible answer to *"who tests the tests?"* - a question good interviewers
ask and most candidates have never considered.

### The isolation fixture, and why it is autouse

```python
@pytest.fixture(autouse=True)
def isolated_env(monkeypatch):
    for name in _SETTINGS_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
```

Without it, a developer with `BASE_URL` set in their shell gets different results from CI. That is
exactly the environment-dependent flakiness this framework exists to demonstrate how to avoid - so it
would be indefensible to allow it in the framework's own tests. `autouse` because remembering to
request it is a rule that will eventually be forgotten.

### What the 31 tests actually cover

| Area | Examples |
|---|---|
| Defaults | A fresh clone loads with no configuration at all |
| Precedence | Real environment variables beat the `.env` file |
| Normalisation | Trailing slashes stripped; log level upper-cased |
| Negative | Non-HTTP URLs, unknown environment names, bad log levels |
| Boundary | `DB_PORT` at 0 and 70000; timeouts at 0 and negative |
| Security | `masked()` and `repr()` contain no secret; DSN URL-encodes `@` and `/` in passwords |
| Behaviour | CI forces headless; settings are immutable; `get_settings` is cached |

Note the shape: the framework's own tests use the same *negative* and *boundary* discipline demanded
of the application tests. Consistency between what you preach and what you practise is visible in a
repository, and reviewers notice.

---

## Component 6 - Secret hygiene

| Control | Mechanism |
|---|---|
| `.env` never committed | `.gitignore` uses `.env.*` with `!.env.example` |
| Private keys never committed | `detect-private-key` pre-commit hook |
| Secrets never printed | `SecretStr` + `masked()` + `db_dsn_safe` |
| Large binaries never committed | `check-added-large-files` (512 KB) |
| CI secrets | Injected as environment variables from GitHub secrets / Jenkins credentials |

The seeded local password (`Passw0rd!seed`) is committed **on purpose** and documented as a throwaway
value for a disposable local database. Pretending it is a secret would be security theatre; treating
real credentials the same way would be negligence. Knowing which is which is the actual skill.

---

## Component 7 - Scripts instead of a Makefile

`make` is not present on a default Windows install. Since the development machine is Windows and CI
is Linux, the repository ships:

* `scripts/bootstrap.ps1` - one-command setup for a fresh clone, idempotent by design
* `scripts/quality.ps1` / `scripts/quality.sh` - the **exact** CI gate, runnable locally

The second matters more than it looks: any divergence between the local script and the CI workflow is
a bug in one of them. A developer must never learn about a lint failure from a pipeline.

---

## Interview questions this phase earns you

**Q: Why `src/` layout instead of packages at the repository root?**
Imports resolve identically in an IDE, a terminal, CI and Docker; no `sys.path` manipulation; no
collision between the framework's `api/` and the application's `api/`; and the framework can be
packaged and reused by another repository. The cost is one `pip install -e .`, which you need anyway
for dependencies.

**Q: How do you stop tests from importing application code, and why does it matter?**
A ruff `banned-api` rule (TID251) in pre-commit and CI. It matters because shared constants make
contract regressions invisible: rename a serialised enum value and both sides move together, so the
test passes while every real consumer breaks.

**Q: What does `--strict-markers` buy you?**
A typo'd marker silently removes a test from the suite it was supposed to belong to. `--strict-markers`
turns that into a hard error. It is one line and it prevents a whole class of false coverage.

**Q: How does your framework handle configuration across environments?**
One frozen, validated pydantic-settings object. Precedence is real environment variables, then
`.env`, then defaults - which is why the same code runs locally from a file and in CI from injected
secrets with no branching. Everything is range-checked at session start, so misconfiguration fails
immediately with an actionable message instead of as a mystery failure mid-run.

**Q: How do you keep secrets out of reports and logs?**
`SecretStr` for every credential, an explicit `masked()` view for the report, and a `db_dsn_safe`
property for logs. Secrets are replaced rather than truncated, because a truncated secret is still a
leak. `.env` is gitignored, and a pre-commit hook rejects private keys.

**Q: Why treat warnings as errors?**
A `DeprecationWarning` is advance notice that an upgrade will break the suite. As an error it becomes
a dated task; as a warning it becomes a line nobody reads. Known-noisy third-party warnings are
silenced by module, never globally.

**Q: Why is database validation opt-in? Isn't that hiding coverage?**
It would be, if the skip were quiet. A fresh clone must load with zero configuration, and in real
organisations an SDET often has database access in one environment and not another - the suite must
still run there. The safeguards are that the skip carries a reason, the report's environment block
says `database: disabled`, and every CI workflow enables it explicitly, so a disabled database in CI
is a visible diff rather than an invisible default.

**Q: What did you get wrong in this phase?**
Three things, all recorded in `docs/progress.md`: an editable install built before the package
existed, a manifest referencing a README that did not exist, and a default configuration that was
invalid - caught by my own unit tests. I changed the design rather than the tests and wrote an ADR
explaining why.

---

## What Phase 3 depends on from here

* `Settings.db_*` fields → the roles created by `scripts/setup_local_db.ps1`
* `DB_ENABLED` → whether `db`-marked tests run or skip
* `[app]` optional dependency group → installing the application under test
* The `claimdesk` import ban → gets its first real code to police
