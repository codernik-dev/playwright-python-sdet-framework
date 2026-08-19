# Phase 4 — The pytest foundation

> Teaching document. This is the layer every test sits on: artefacts, correlation,
> logging, readiness, and the fixtures and hooks that tie them together.
> It contains no test of the application — and that is the point. Get this wrong
> and every later phase inherits the damage.

---

## What was built

| File | Responsibility |
|---|---|
| `src/claimdesk_qa/core/artifacts.py` | Where failure evidence goes and how it is named |
| `src/claimdesk_qa/core/correlation.py` | Identifiers that join a test to the application's logs |
| `src/claimdesk_qa/core/logging.py` | Console, per-worker and per-test logging |
| `src/claimdesk_qa/core/readiness.py` | Waiting for a dependency — the replacement for `sleep` |
| `src/claimdesk_qa/core/exceptions.py` | "The test could not run" versus "the product is wrong" |
| `tests/conftest.py` | Session fixtures, marker enforcement, artefact policy |
| `tests/framework/test_*.py` | 38 new unit tests for all of the above |

---

## Decision 1 — `FrameworkError` is not `AssertionError`

```python
class FrameworkError(Exception):
    """The test could not be executed correctly. Not a product defect."""
```

An `AssertionError` means the application behaved incorrectly. A `FrameworkError`
means the test never got the chance to find out — the environment was wrong, a
service never came up, configuration was missing.

Conflating them is expensive in a specific way: an infrastructure outage arrives
as forty red tests, someone spends an hour "investigating the regressions", and
after the third time it happens people stop believing the suite. Separating them
means a database that is down reads as *a database that is down*.

---

## Decision 2 — Artefacts: capture always, keep selectively

```
artifacts/
  20260819-061521-a2af/
    logs/worker-gw0.log ... worker-gw3.log
    tests_api_test_claims.py__test_approve_above_limit/
      test.log
```

**One run directory, shared by every worker.** The controller fixes a run id in
`pytest_configure` *before* xdist spawns workers, so they inherit it:

```python
if not hasattr(config, "workerinput"):  # controller, or no xdist
    os.environ.setdefault(RUN_ID_ENV_VAR, new_run_id())
```

Without this, a four-worker run produces four run directories and nobody can find
the failure. **Verified:** `pytest -m framework -n 4` produced exactly one run
directory containing four worker logs.

`QA_RUN_ID` can also be set by CI to the build number, so the artefact directory
links back to the pipeline run that produced it.

**One log file per worker.** Four processes appending to one file interleave and
lose lines. Separate files cost nothing and are always complete.

**Capture always, keep selectively.** Every test writes `test.log`; on teardown,
a test that passed has its directory deleted:

```python
if not test_failed(request.node):
    shutil.rmtree(log_path.parent, ignore_errors=True)
```

You cannot decide up front to log only failures, because you do not know a test
will fail until it already has. So evidence is gathered for everyone and thrown
away for the tests that did not need it. `artifacts/` stays a list of problems
rather than a haystack. **Verified:** a run with one passing and one failing test
left exactly one directory behind.

### Windows path limits, handled deliberately

A parametrised node id easily exceeds Windows' 260-character path limit. The
failure this produces is genuinely horrible: it happens inside a library, during
teardown, while trying to save the evidence for a *different* failure. So slugs
are truncated — and truncation appends a hash of the **full** node id:

```python
if len(slug) > max_length:
    digest = hashlib.sha256(node_id.encode()).hexdigest()[:8]
    slug = f"{slug[: max_length - len(digest) - 1]}_{digest}"
```

Truncating alone would let two long ids sharing a prefix collapse onto one
directory and overwrite each other's evidence. There is a test for exactly that.

---

## Decision 3 — Correlation identifiers, and two real bugs

Every HTTP request the framework makes will carry `X-Request-Id`. ClaimDesk echoes
it and writes it to its own log, so one `grep` shows exactly the requests a failing
test made — instead of guessing from timestamps.

The id is `sha256(node_id)[:10]`, which makes it **stable** (the same test yields
the same id in every run, so you can compare today's failure with last week's),
**short** enough to sit in a log line, and **safe** as a header value.

The current id lives in a `ContextVar` rather than being threaded through every
call. Two unrelated things need it — the log formatter and the HTTP client — and
passing it as an argument would force every helper in between to know about
correlation.

### Bug 1 — the correlation id never reached the log file

The first implementation gave each handler its own filter holding its own default:

```python
console.addFilter(RequestIdFilter("-"))
per_test_handler.addFilter(RequestIdFilter(request_id))
```

Filters mutate the **shared** `LogRecord`. Whichever handler ran first stamped its
default onto the record; every later filter found the attribute already present
and left it alone. The per-test log showed `[-]` and correlation was silently
useless.

The fix is not "order the handlers correctly" — it is to remove the ordering
dependency. All filters now read one `ContextVar`, so it no longer matters which
runs first: they all compute the same answer.

### Bug 2 — moving the filter to the logger silently deleted every log line

The obvious next move was to attach the filter once, to the logger:

```python
logger.addFilter(RequestIdFilter())  # looks tidier. It is wrong.
```

A logger's filters are applied **only to records logged through that logger
directly**. A record from a child logger — `claimdesk_qa.api` — reaches the
parent's handlers through `callHandlers`, which skips the parent's filters
entirely. So `request_id` was missing, the formatter raised `KeyError`, and
`logging` swallowed it.

Nothing failed. The log file was simply empty.

The filter belongs on the handlers, where it applies to every record regardless
of origin. Both bugs now have named regression tests.

> **Interview soundbite:** *"Two logging bugs, both silent. One made correlation
> ids vanish because handler filters mutate a shared record, so ordering decided
> the value. The other deleted log lines entirely because logger-level filters do
> not apply to records from child loggers. Neither failed loudly — the evidence
> was just missing when I needed it. Both have regression tests now."*

---

## Decision 4 — Log levels are per destination

```python
logger.setLevel(logging.DEBUG)  # nothing is dropped before the handlers
console.setLevel(settings.log_level)  # a local run stays readable
file_handler.setLevel(logging.DEBUG)  # files exist for the moment it failed
```

Getting this backwards is the third silent failure of the phase, and I hit it:
with the **logger** at INFO, debug records are discarded before any handler sees
them, so every per-test log file is empty. Discovered — as always — while
triaging a real failure.

The rule: filter late, at the destination, not early at the source.

---

## Decision 5 — Readiness, not `sleep`

```python
subprocess.run(["docker", "compose", "up", "-d"])
time.sleep(10)  # "should be enough"
```

Wrong in both directions: ten wasted seconds on every fast run, and not enough on
a loaded CI agent — where it fails with a connection error that looks like a
product defect. The fix is never a bigger number.

```python
wait_until_ready(
    http_probe(f"{settings.base_url}/health/ready"),
    description=f"ClaimDesk at {settings.base_url}",
    timeout_seconds=settings.readiness_timeout_seconds,
)
```

The failure message is engineered, not incidental:

```
ServiceNotReadyError: ClaimDesk at http://localhost:9999 did not become ready
within 3s (1 attempt(s), last result: ConnectError: [WinError 10061] No connection
could be made because the target machine actively refused it).
This is an environment problem, not a product defect.
```

It names what was waited for, how hard it tried, the actual OS-level cause, and —
explicitly — who is at fault. Someone reading a CI log at 03:00 needs all four.

The probe, the clock and `sleep` are all **injected**, which is why the unit tests
can prove that a 60-second timeout times out without spending 60 seconds. A suite
that is slow to test its own slowness stops being run.

---

## Decision 6 — Layer markers are applied by location

```python
_LAYER_BY_DIRECTORY = {"api": "api", "ui": "ui", "db": "db", "e2e": "e2e", "framework": "framework"}
```

This is the only piece of magic in the framework, and it is deliberate. The
alternative — asking every author to remember `@pytest.mark.api` — fails
**silently**: the test still runs, it simply drops out of the suite it was meant
to belong to, and nobody notices until a release. Location is a fact that cannot
be forgotten.

A test that ends up outside a layer directory is a collection error, not a
warning:

```
ERROR: Every test must sit in exactly one layer directory under tests/
(api, db, e2e, framework, ui). Offenders:
  tests/test_stray.py::test_stray (layer markers: none)
```

**Verified** by creating exactly that file and watching collection refuse it.

---

## Decision 7 — Database tests skip loudly, never quietly

```python
if "db" in present and not settings.db_enabled:
    item.add_marker(pytest.mark.skip(reason="DB_ENABLED=false - database validation is disabled"))
```

Combined with the header:

```
claimdesk-qa: *** DATABASE VALIDATION IS DISABLED - db-marked tests will SKIP ***
```

and `-ra` in `addopts`, which prints every skip **with its reason**. A green run
that never touched the database cannot be mistaken for one that validated it.
That was the risk [ADR 0006](adr/0006-opt-in-database-validation.md) accepted, and
this is the control that pays for it.

---

## Decision 8 — Artefact paths are absolute

`ARTIFACTS_DIR` is conventionally relative (`artifacts`). A relative path resolves
against the *current* working directory — so any test that calls `chdir` (the
framework's own tests do, to isolate themselves from `.env`) would scatter
evidence into unrelated folders. Anchoring to `pytestconfig.rootpath` removes the
class of problem rather than the instance.

---

## Decision 9 — Faker is seeded per test, not per session

```python
node_digest = int(hashlib.sha256(request.node.nodeid.encode()).hexdigest()[:8], 16)
return session_seed ^ node_digest
```

Seeding every test from one session seed would make two tests generate the *same*
"random" email and collide. Seeding per node id keeps each test's data distinct
while staying fully reproducible: same run seed plus same test equals the same
data.

**Reproducibility is not uniqueness.** For values that must never collide across
parallel workers, use `unique_id` (a `uuid4` fragment). Faker makes data look
real; `unique_id` makes it safe to run in parallel.

---

## How to run and prove it

```powershell
pytest -m framework -q              # 70 unit tests, no application needed
pytest -m framework -n 4 -q         # then check artifacts/ holds ONE run directory
pytest --markers                    # the full marker taxonomy
pytest tests/db -rs                 # see a skip WITH its reason
```

Prove the artefact policy yourself:

```powershell
# add a failing test under tests/api/, run it, then:
Get-ChildItem artifacts -Recurse    # only the failing test kept a directory
```

Prove the readiness gate:

```powershell
$env:BASE_URL="http://localhost:9999"; $env:READINESS_TIMEOUT_SECONDS="3"
pytest tests/api -q                 # ServiceNotReadyError, blaming the environment
```

---

## Verification — commands run, output observed

| Check | Result |
|---|---|
| Framework unit tests | ✅ `70 passed` |
| Application unit tests | ✅ `58 passed` |
| ruff / ruff format / mypy strict | ✅ clean, 34 source files |
| One run directory under `-n 4` | ✅ one directory, four worker logs |
| Passing test's artefacts pruned | ✅ pruned |
| Failing test's artefacts kept | ✅ `test.log` retained, with the correlation id in it |
| Correlation id in the log | ✅ `[qa-933749c975]` |
| Header shows environment + masked DSN | ✅ password rendered as `***masked***` |
| Test outside a layer directory | ✅ collection error naming the offender |
| DB disabled | ✅ skip with reason + shouted header line |
| Readiness against a dead port | ✅ `ServiceNotReadyError` blaming the environment |

---

## Interview questions this phase earns you

**Q: How do you make a parallel test run debuggable?**
One run directory shared by every worker — the controller fixes the run id before
workers spawn, so they inherit it. One log file per worker, because concurrent
appends to a single file interleave and lose lines. One directory per test, named
from a sanitised node id with a hash suffix so long parametrised names cannot
collide.

**Q: How do you keep artefacts useful instead of enormous?**
Capture always, keep selectively. You cannot know in advance which test will fail,
so every test writes its evidence and passing tests have theirs deleted at
teardown. The result is that `artifacts/` contains only problems.

**Q: How do you correlate a test failure with server-side logs?**
Every request carries `X-Request-Id`, derived by hashing the pytest node id, which
the application echoes and logs. It is stable across runs, so you can compare the
same test's requests over time. The current value lives in a `ContextVar` so both
the log formatter and the HTTP client can read it without threading a parameter
through every layer.

**Q: Why not just `sleep` after starting the environment?**
Because it is wrong in both directions — wasteful when the service is up, and
insufficient when the agent is slow. Poll the readiness endpoint and fail with a
message naming the service, the elapsed budget, the attempt count, the underlying
error, and the fact that it is an environment problem.

**Q: How do you test code that waits?**
Inject the clock and the sleep. The tests prove a 60-second timeout times out
without taking 60 seconds. If testing your own slowness is slow, people stop
running the tests.

**Q: How do you stop someone forgetting a marker?**
Do not rely on memory. Markers are applied from the test's directory, and a test
outside a known layer directory is a collection error. A forgotten marker is a
silent failure — the test passes while quietly leaving the suite it belonged to.

**Q: Tell me about a bug you found in your own framework.**
Two, both silent. Handler-level log filters mutate a shared record, so whichever
handler ran first decided the correlation id and the rest was `[-]`. Fixing it by
moving the filter onto the logger made it worse — logger filters do not apply to
records from child loggers, so `request_id` went missing entirely, the formatter
raised `KeyError`, and log lines simply disappeared. Both have regression tests
named after the failure mode.

---

## What Phase 5 builds on

* `request_id_context` / `get_request_id` → the `ApiClient` reads the current id
  and sets the `X-Request-Id` header with no plumbing
* `app_ready` → requested by the API suite so a dead environment fails once, clearly
* `unique_id` → the key every created record carries, which is what makes the
  suite parallel-safe
* `test_failed` + the artefact directory → where request/response recordings are
  attached in Phase 8
