# Phase 8 - Reporting and failure artefacts

> Teaching document. What a report has to answer before it earns the right to
> exist, and three defects I shipped into my own reporting code - two of which
> were invisible until I generated a real report from real failures.

---

## What was built

| File | Responsibility |
|---|---|
| `src/claimdesk_qa/core/recording.py` | One evidence recorder per test: every HTTP exchange and every SQL statement, in one timeline |
| `src/claimdesk_qa/reporting/allure_support.py` | Environment block, failure categories, CI executor, severity mapping |
| `tests/conftest.py` | Writes report metadata; attaches logs, HTTP and SQL on failure only |
| `tests/_fixtures/browser.py` | Attaches screenshot, page HTML and the Playwright trace on failure |
| `scripts/report.ps1` · `scripts/report.sh` | Generate and serve the report, carrying history forward |
| `tests/framework/test_recording.py` · `test_allure_support.py` | 37 unit tests for the above |

---

## Decision 1 - What a report must answer without being asked

A test report is not a list of outcomes. It is the thing an engineer opens at
03:00 with no context, and it has to answer four questions before they can even
begin:

| Question | Where the answer comes from |
|---|---|
| Against **what** did this run? | `environment.properties` - env, URLs, database, browser, workers, seed, commit |
| **Whose** problem is this? | `categories.json` - product defect vs environment vs test defect |
| **Which** CI run produced it? | `executor.json` - a link straight back to the build |
| What actually **happened**? | Attachments: log, HTTP exchanges, SQL, screenshot, page HTML, trace |

Anything that does not serve one of those four is decoration, and decoration in a
report is worse than nothing: it makes the report slower to read at exactly the
moment reading speed matters.

---

## Decision 2 - Capture for everyone, keep for the failures

The policy is deliberately asymmetric:

| Artefact | On pass | On failure |
|---|---|---|
| Per-test log | captured, deleted | kept **and attached** |
| HTTP exchanges | recorded in memory | written and attached |
| Executed SQL | recorded in memory | written and attached |
| Screenshot / page HTML | not taken | taken and attached |
| Playwright trace | recorded, discarded | saved and attached |

You cannot decide up front to record only failures, because a test is not known
to have failed until after it has run. So everything is gathered and most of it
is thrown away. The alternative - recording nothing and asking people to
reproduce - is how a flaky failure survives for six weeks.

Attaching, rather than only writing to `artifacts/`, is the part that changes
behaviour. A file on a CI runner is useful to whoever knows the archive exists
and knows how to download it. The same bytes inside the report are one click
from the failure that produced them.

---

## Decision 3 - One timeline, not four fragments

`ApiClient` already kept its last 25 exchanges and `Database` its last 25
queries. That is not enough, because a single test routinely uses **three
clients and a database connection** - a customer, an adjuster, an admin, and a
read-only session. Four separate histories mean the reader interleaves them by
hand, from timestamps, while trying to understand a failure.

So there is one recorder per test, and the objects push into whichever recorder
is currently active:

```python
def record_http(exchange: Renderable) -> None:
    recording = _active.get()
    if recording is not None:
        recording.http.add(exchange)
```

Three properties, each of which is a test in `test_recording.py`:

- **It never fails a test.** With no recorder active every call is a no-op, so a
  client built in a script - or by the readiness probe, which runs before any
  test - behaves exactly as before.
- **It never leaks between tests.** The token is reset in a `finally`, so a test
  that raises cannot leave its recorder attached and start collecting the *next*
  test's traffic. That failure mode is worse than collecting nothing: the
  evidence would look completely genuine while describing the wrong test.
- **It is bounded, and says what it dropped.** A parametrised test making a
  thousand requests keeps the most recent hundred and states how many were
  discarded. Truncating silently would let a reader draw conclusions from a
  timeline that quietly began in the middle.

`core` may not import `api` or `db` - the dependency arrows in this framework
point one way - so the recorder accepts anything that satisfies a `Renderable`
Protocol. The layers hand over their own value objects without either side
importing the other.

---

## Decision 4 - Categories are an exception taxonomy, not a wording match

This is the one that changes what people *do*, rather than what they see.

The framework already draws the distinction in code: `FrameworkError` and its
subclasses mean the environment could not support the test, `AssertionError`
means the product misbehaved. The report's categories are that same taxonomy:

| Category | Keyed on |
|---|---|
| Environment problem | `ServiceNotReadyError`, `DatabaseError`, `ConnectError`, `InsufficientPrivilege` |
| Contract violation | "did not match the ... contract" |
| Wrong HTTP status | "Expected HTTP ... but got" |
| Browser timeout | Playwright's `Call log:` block |
| Skipped by configuration | `DB_ENABLED=false` |
| Product defect | everything else that failed an assertion |
| Test defect | everything else that errored |

Order matters: Allure applies the **first** match, so the catch-alls come last.
A test asserts that, because if "Product defect" ever moved up the list, every
environment outage would be reported as a product bug - silently.

**Proof it works**, from a real report generated in this phase. The database was
pointed at a dead port and thirteen tests failed:

```
Product defect:                                    2
Browser timeout (element never became actionable):  1
Environment problem (not a product defect):        13
```

Thirteen environment problems, not thirteen product defects. That is the whole
point: a database outage must not summon a developer to debug their own code.

---

## The three defects I shipped into my own reporting

### 1. Every category regex matched nothing

Allure matches with Java's `Pattern.matches`, which requires the **entire** value
to match, and `.` does not cross a newline. A message is usually one line and
gets away with it. **A stack trace never is.**

So every `traceRegex` silently matched nothing, everything fell through to the
catch-all, and the report looked perfectly healthy while triage had quietly
stopped working. There is no error for this - a category that matches nothing is
indistinguishable from a category with nothing to match.

Caught by generating a real report from three deliberate failures and noticing a
Playwright timeout filed as a product defect.

The fix is `(?s)`. The lesson is in the *test*, which had passed:

```python
# before - passed, and proved nothing
("claimdesk_qa.core.exceptions.ServiceNotReadyError: ...", True)


# after - a realistic multi-line traceback
def _as_traceback(exception_line: str) -> str: ...
```

A test that feeds a regex simpler input than reality does is not a test, it is a
rehearsal. There is now a second test asserting `re.DOTALL` on **every** pattern
- compiled, not by looking for a `(?s)` prefix, because checking the text proves
only that somebody typed it.

### 2. The pattern I wrote from imagination, twice

Having fixed the flag, the browser category still matched nothing. I had keyed it
on `playwright._impl` - a module path that appears in a Python traceback and
**not** in what Allure records, which is pytest's formatted failure repr: source
lines and `E ` markers.

I then read the actual recorded trace instead of guessing a third time, and keyed
the category on `Call log:` - a block Playwright emits for every locator and
expect timeout, and for nothing else.

Two wrong patterns, both written from a plausible mental model of a data
structure I had never looked at. Reading it took thirty seconds.

### 3. A feature the library already had

I mapped pytest markers onto Allure tags. The report then showed every tag
twice, because allure-pytest already does exactly that.

Verified rather than assumed - the same test run with and without the loop:

```
WITH our fixture:    [('tag', 'framework'), ('tag', 'framework')]
WITHOUT our fixture: [('tag', 'framework')]
```

The mapping function, its export and its unit test were **deleted**. Severity was
kept, because that part genuinely is missing: without it every test in the report
is "normal", and a smoke failure sorts alongside a quarantined one.

Writing code a dependency already provides is not a small waste. It is a second
implementation that can disagree with the first, and here it did - visibly, in
the deliverable.

---

## A fourth defect, in the tooling rather than the framework

My throwaway inspection script crashed with `KeyError: 'type'` on the trace
attachment (a zip has no MIME type) and aborted its loop early. I read that as
"browser attachments are not being written" and started debugging the framework.
They had been written correctly all along.

Worth recording because the instinct it corrects is general: when a tool reports
that the system is broken, the tool is also a suspect. Mine had a stack trace in
plain sight and I read past it.

---

## Decision 5 - Severity means triage order

Three values, because a scale nobody applies consistently is worse than a coarse
one everybody can:

- `critical` - smoke. If these fail, nothing further is worth reading.
- `minor` - quarantined. Known-flaky, excluded from the gate, and it must never
  compete for attention with a real failure.
- `normal` - everything else.

---

## Decision 6 - History, or the report answers only half the question

`scripts/report.ps1` copies the previous report's history **into the results
directory** before generating. That direction is the whole trick, and it is
routinely done backwards: Allure reads history from the results, and produces it
into the report. Copy it the other way and you get an empty trend with no error
to explain why.

Without history a report can say "this test failed". With it, the report says
"this test has failed four times this week" or "this test broke today" - and
those are different problems with different owners.

---

## Verification - commands run, output observed

| Check | Result |
|---|---|
| Full suite with reporting | ✅ `330 passed in 26.56s` (`--alluredir` + `--junitxml`) |
| Framework unit tests | ✅ `109 passed` |
| Quality gate | ✅ ruff clean · ruff-format clean · mypy strict clean, 90 files |
| Environment block written | ✅ 19 entries; database password rendered `***masked***` |
| Report generated by the Allure CLI | ✅ `Report successfully generated to allure-report` |
| Categories applied to real failures | ✅ 2 product · 1 browser timeout · 13 environment |
| Attachments on an API failure | ✅ `test log`, `HTTP exchanges` |
| Attachments on a DB failure | ✅ `test log`, `SQL executed` |
| Attachments on a browser failure | ✅ `test log`, `screenshot-0` (PNG), `page-0.html`, `playwright trace` (zip) |
| Passing tests attach nothing | ✅ artefact directories pruned, no attachments recorded |

⚠️ **NOT VERIFIED in Phase 8:** the nightly workflow's Allure publication to
GitHub Pages. It is written, but it needs a push and Pages enabled on the
repository, and nothing in this phase was run on a GitHub runner.

---

## How to run it

```powershell
pytest -q --alluredir=allure-results     # run the suite, write raw results
.\scripts\report.ps1                     # generate, carry history forward, serve
.\scripts\report.ps1 -NoOpen             # generate only (what CI does)
.\scripts\report.ps1 -Clean              # discard the accumulated trend
```

The Allure CLI needs a JVM. `npm install -g allure-commandline` is the shortest
route if Node is present; the script falls back to `npx` and, failing that, tells
you exactly what to install rather than dying on a missing command.

---

## Interview questions this phase earns you

**"How do you decide what to capture on failure?"**
Capture everything for every test, keep it only for failures - you cannot know in
advance which test will fail. Then judge each artefact by whether it answers a
question the report cannot already answer: screenshot for "what did the user
see", page HTML for "was the element there at all", trace for "when did it go
wrong", HTTP and SQL for "what did the system actually do".

**"Your CI went red. How does the report help?"**
It classifies first. Thirteen failures under "Environment problem" is a
five-second triage; thirteen failures under "Product defect" is a wasted morning.
The categories key on exception types the framework raises deliberately, not on
message wording that drifts.

**"What went wrong when you built it?"**
Every category regex matched nothing, because Allure requires a full match and
`.` does not cross newlines - and a category that matches nothing looks
identical to a category with nothing to match. My unit test had passed because I
fed it a one-line trace. I also wrote a marker-to-tag mapping that allure-pytest
already provided, and the report showed every tag twice.

**"How do you know the report is right?"**
By breaking things on purpose. Three deliberate failures across three layers, one
forced database outage, and then reading the generated report's own widget JSON
to confirm what a reader would see.

---

## What Phase 9 builds on

Reporting is now the place where flakiness becomes visible: a rerun that passes
must be **reported as flaky**, not silently green. Phase 9 finalises the marker
taxonomy, the serial pass, and the rerun policy that decides what a retry is
allowed to hide - which is nothing.
