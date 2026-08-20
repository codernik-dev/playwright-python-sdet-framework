# Phase 13 - Refactor and code-quality pass

> Teaching document. The pass that reads the whole repository as one artefact.
> It found a latent timezone flake with a five-and-a-half-hour daily window, two
> gates that contradicted each other, and a `.gitignore` pattern that had never
> matched the file it was written for.

---

## What this phase is for

Everything before it built something. This one asks a different question: *if a
senior engineer read the whole repository today, what would they object to?*

The tools were already configured. The finding is that **configuring a tool is
not the same as running it** - `pre-commit` had been set up in Phase 2 and never
executed once, and it had real things to say.

---

## Finding 1 - A timezone flake, found before it ever failed

The sharpest finding of the phase, and nothing was red.

ClaimDesk refuses a claim whose incident date is in the future. The suite asserts
both sides of that boundary:

| Test | Sends |
|---|---|
| `test_an_incident_dated_today_is_accepted` | today |
| `test_a_future_incident_date_is_rejected` | tomorrow |

Both the application and the framework answered "what is today?" with
`date.today()` - **the local date of whichever machine asked**. On a developer's
laptop that is one machine, so they always agreed.

They stop agreeing the moment those are two machines, which is exactly what
Phase 10 built. A container runs UTC; this project is developed in IST
(UTC+05:30). Between **00:00 and 05:30 IST the runner's date is one day ahead of
the container's**:

- `..._today_is_accepted` sends a date the server considers *tomorrow* → `422` →
  **fails**;
- `..._future_..._is_rejected` sends the day after, still in the server's future
  → passes, hiding half the problem.

A test that fails for five and a half hours a day, only in the containerised
environment, and only one of a matched pair. It would have presented as
flakiness, been blamed on the browser or the database, and survived for months.

**The fix is not an offset calculation.** Both sides now answer the same question
the same way - UTC, explicitly - so they agree by construction whatever timezone
either machine has:

```python
def today_utc() -> date:
    return datetime.now(UTC).date()
```

The application was changed too, in `schemas.py` (the API) **and**
`web/routes.py` (the browser form, which had its own copy of the check). Not to
make a test pass - the tests passed. A claims system that decides "is this in the
future" from whichever timezone its server happens to be configured with is
wrong on its own terms, and it is the kind of wrong that only appears once the
system is deployed somewhere other than where it was written.

`DTZ` is now in the ruff selection, so the whole class cannot come back. The one
place a naive local `now()` is correct - the test that proves UTC and local can
genuinely differ - carries a `# noqa: DTZ005` with its reason, rather than the
rule being weakened for everyone.

---

## Finding 2 - Two gates that disagreed with each other

`pre-commit run --all-files`, executed for the first time.

### 2a. Two versions of the same linter

`.pre-commit-config.yaml` pinned `ruff` at **v0.9.6**. `pyproject.toml` installs
**0.16.3**. Two versions of one linter is two gates with two verdicts, and they
duly disagreed: the older one reported `A005 module shadows a standard-library
module` for `claimdesk_qa/core/logging.py`, which the project's own gate does not.

The hook is now pinned to the version the project installs. One fact, one place
to update.

*(The finding itself was assessed and declined: `claimdesk_qa.core.logging` is
namespaced, Python 3 imports are absolute, and the module imports the real
`logging` successfully. Renaming it would touch every module for no defect.
Knowing which findings to act on is the skill; a linter is an opinion, not an
authority.)*

### 2b. A hook fighting `.gitattributes`

`mixed-line-ending --fix=lf` rewrote **every** file to LF - including the `.ps1`
scripts that `.gitattributes` explicitly requires to be CRLF:

```gitattributes
*.ps1   text eol=crlf
```

The hook and the attributes file contradicted each other outright. On every
commit the hook would "fix" the scripts and git would convert them back.

A hook that fights the developer is worse than no hook, because it is how people
learn to use `--no-verify` - and `--no-verify` is how the private-key detection
in the same file gets bypassed on the one day it would have mattered. The hook
now excludes the extensions `.gitattributes` owns.

---

## Finding 3 - A `.gitignore` pattern that never matched anything

`junit.xml` was **tracked in the repository**: a generated test-result file,
committed by accident in Phase 8 by a `git add -A`.

The interesting part is why it slipped through. The ignore file already had a
pattern for it:

```gitignore
*.junit.xml
```

That requires a dot before the word. It matches `results.junit.xml`. It has never
matched `junit.xml` - which is precisely what `--junitxml=junit.xml` produces.

**A near-miss glob is worse than no glob, because it looks handled.** Anyone
reviewing `.gitignore` would tick it off. It is now `junit*.xml`, the original
pattern is kept alongside it, and the file is untracked.

---

## Measurements

The Phase 1 self-critique set a hard constraint: *"If framework code grows past
roughly 3,000 lines it stops being reviewable and becomes a liability."*

| Measure | Lines |
|---|---|
| `src/claimdesk_qa/` total | 3,946 |
| `src/claimdesk_qa/` **excluding blank lines and comments** | **2,914** |
| `tests/` | 5,451 |
| `app/` (the fixture) | 2,533 |

Under the cap on the measure that matters, and the gap between the two numbers is
the point: roughly a quarter of the framework is docstrings explaining *why*. That
is deliberate, and it is the part a reviewer reads first.

| Check | Result |
|---|---|
| TODO / FIXME / XXX / HACK anywhere | ✅ **none** |
| Commented-out code (`ERA`) | ✅ none |
| Stray `print()` (`T20`) | ✅ none |
| Full suite | ✅ **`351 passed in 29.84s`** |
| Application's own tests | ✅ `58 passed in 0.31s` |
| ruff · ruff-format · mypy `--strict` | ✅ clean, 94 files |
| `pre-commit run --all-files` | ✅ **all hooks pass** - for the first time |

---

## What was deliberately not changed

A quality pass is also a set of decisions *not* to act, and those are worth
recording because "the linter said so" is not a reason:

| Suggestion | Verdict |
|---|---|
| `S101` - 348 uses of `assert` | Declined. It is a test suite; `assert` is the product |
| `D1xx` - 245 missing docstrings | Declined wholesale. Docstrings are on every module and every non-obvious function; requiring one on `def test_login_works()` produces noise that dilutes the ones worth reading |
| `TC001/TC003` - move 112 imports into `TYPE_CHECKING` | Declined. A real but tiny import-time saving, paid for with 112 diffs and a permanently more awkward import block |
| `ANN401` - `Any` in 11 signatures | Declined. Each is a genuine boundary with untyped JSON or an untyped library |
| `A005` - rename `core/logging.py` | Declined; see Finding 2a |
| `S608` - f-string SQL in `db/queries.py` | Declined. The interpolated value is a module-level **column list**, never input. The project's rule is that *values* are parameterised, and they all are |

---

## Interview questions this phase earns you

**"How do you find bugs that have not failed yet?"**
By asking what a test depends on that nobody declared. A date boundary depends on
a timezone; the timezone was implicit; the two machines that had to agree only
became two machines in Phase 10. Then look for the window: five and a half hours
a day, one of a matched pair, container only.

**"Your linter and your pre-commit hook disagreed. Why does that matter?"**
Because a gate that fights the developer teaches `--no-verify`, and the same
config contains the private-key detection. Tooling that is wrong on style gets
bypassed on security.

**"What did you decide not to fix?"**
Six things, each with a reason. Requiring a docstring on `test_login_works` makes
the docstrings that matter harder to find. A linter is an opinion, and taking
every opinion is not rigour - it is an absence of judgement.
