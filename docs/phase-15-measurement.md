# Phase 15 - Execution and measurement

> Teaching document. The phase where every number in this repository was allowed
> to be written down for the first time, and the phase whose main output is a
> caution about how easily these numbers lie.

---

## The rule this phase enforces

From Phase 1, written before any code existed:

> No percentage, timing, coverage figure or pass rate goes into the README, CV or
> LinkedIn until it comes from a real run recorded in Phase 15.

Until now the README carried counts and timings from the phase that produced
them. This phase re-measures everything on one machine, in one session, and
those are the numbers the project publishes.

---

## The machine

A measurement without a machine attached is not a measurement.

| Item | Value |
|---|---|
| CPU | AMD Ryzen 7 5800H, **16 logical cores** |
| OS | Windows 11 Home Single Language 26200 |
| Python | 3.12.10 |
| PostgreSQL | 17.6, project-local cluster on port 55432 |
| Playwright | 1.62.0, Chromium |
| Application | uvicorn on 127.0.0.1:8000, same machine as the tests |

---

## Test counts

Produced by `pytest -m <marker> --collect-only -q`.

| Layer | Tests | Share |
|---|---|---|
| Framework unit tests | **130** | 37% |
| API | **157** | 45% |
| Browser (UI) | **32** | 9% |
| Database | **28** | 8% |
| Cross-layer (E2E) | **4** | 1% |
| **Total** | **351** | |

Against the application only (excluding the framework's own unit tests): 221
tests, of which **71% are API**, 14% browser, 13% database and 2% end-to-end.

Phase 1 designed for roughly 60% API, 20% UI, 15% DB, 5% E2E. The API share came
out higher and the browser share lower than planned, and that is the correct
direction: every rule that could be asserted at the API was, and the browser
layer kept only what a browser alone can prove.

By intent, cutting across layers:

| Marker | Tests |
|---|---|
| `smoke` | 94 |
| `negative` | 136 |
| `boundary` | 28 |
| `authz` | 23 |
| `integrity` | 22 |
| `contract` | 5 |

**136 negative tests against 351 total.** That ratio is the point: a suite that
only proves the happy path also passes against an application that accepts
everything.

---

## Wall-clock: the worker sweep

Median of three runs per mode, after a discarded warm-up, all in one session,
back to back.

| Mode | Median | The three runs |
|---|---|---|
| serial (`-p no:xdist`) | **24.88 s** | 27.20 / 24.31 / 24.88 |
| `-n 2` | **18.75 s** | 18.42 / 18.75 / 19.00 |
| **`-n 4`** | **16.82 s** ← best | 16.96 / 16.82 / 16.75 |
| `-n 8` | **19.03 s** | 19.83 / 19.03 / 18.85 |
| `-n auto` (16 workers) | **23.81 s** | 23.81 / 24.14 / 23.50 |

**Best case: 24.88 s → 16.82 s, a 1.48× speed-up on 16 logical cores.**

And the result worth more than the speed-up: **the curve turns around.** Four workers
are the optimum; eight are slower than four, and sixteen are barely faster than running
serially at all.

```
serial   ████████████████████████  24.88s
-n 2     ██████████████████        18.75s
-n 4     ████████████████          16.82s   <- optimum
-n 8     ██████████████████        19.03s
-n auto  ███████████████████████   23.81s   <- 16 workers, almost no better than serial
```

`-n auto` is the default people reach for, and on this suite it throws away nearly the
entire benefit. That is the finding: **"use all your cores" is not a strategy, it is a
guess** - and it is measurable in ten minutes.

### Why more workers stop helping

Three costs do not divide, and they are worth naming because "just add workers"
is the most common wrong answer to a slow suite:

1. **Session fixtures are per worker, not per run.** Each worker performs its own
   four API logins to build browser storage states, its own four role logins, and
   starts its own browser process. Eight workers pay that eight times.
2. **The application is a single process.** Every worker queues behind one
   uvicorn and one PostgreSQL. Past a point they contend rather than parallelise.
3. **The suite is I/O-bound.** Parallelism helps least where the work is waiting
   rather than computing - and a test suite is almost entirely waiting.

---

## Flake rate

Ten consecutive full runs at `-n 4`, no code changes between them.

| Run | Result |
|---|---|
| 1-10 | `351 passed` - 14.99 / 15.34 / 15.43 / 16.09 / 17.63 / 18.15 / 18.43 / 18.88 / 18.73 / 18.86 s |
| **Failures** | **0 / 10** |

**Flake rate: 0 over 3,510 test executions.** Not "no known flakes" - ten consecutive
parallel runs with no code change between them, and every one of the 351 tests kept its
outcome.

Two honest caveats. Ten runs cannot distinguish a zero rate from a rate below roughly one
in three thousand; and this is one machine, with the application on the same host. The
claim is exactly what was measured and no more.

Also visible in that column: the runs got **steadily slower**, 14.99 s to 18.86 s across
ten identical runs. Nothing changed except the accumulated state - the seeded corpus grows
as each run creates claims, so later runs query more rows. Worth noticing rather than
averaging away: a suite that gets slower the more often you run it will eventually be a
suite people stop running.

Flake rate is defined here as *tests that changed outcome ÷ tests run*, which is
the only definition that survives contact with a suite people trust. A run that
"passed after a retry" is not a pass - and in this suite nothing has retried,
because the retry policy is CI-only and nothing has flaked in CI.

---

## The most important finding of this phase

**The same suite, on the same machine, measured 32.77 s serial in Phase 9 and 24.88 s
serial here.**

Nothing about the suite got faster between those two measurements in any way that
explains the difference. Different session, different background load, a
different application process with a differently-warmed database cache.

That is a **24% swing on the same hardware, from nothing at all** - larger than the
entire difference between two and four workers - and
it is exactly the trap this project already warned about in Phase 12, when a CI
step took 249 s and then 13 s with identical configuration:

> A single before/after pair is not a measurement when the dominant cost varies
> between identical runs.

So the numbers above are published **with their spread**, as medians, with the
machine attached - and the honest reading of the parallel speed-up is *"roughly
this much, on this hardware, in this session"*, not a headline.

The one performance claim this project makes without hedging is the TLS-context
fix (107 s → 30 s), and it survives that scepticism for a specific reason: the
cause was **measured directly**, not inferred from the difference between two
suite runs. 355 ms to build an SSL context versus 0.1 ms to reuse one, times one
client per identity per test, predicts the observed change. A mechanism that
explains the number is worth more than the number.

---

## Slowest tests

`pytest --durations=12`, serial:

| Duration | Phase | Test |
|---|---|---|
| 2.66 s | setup | `e2e/test_claim_lifecycle.py::test_a_claim_filed_in_the_browser_is_visible_to_the_api_and_the_database` |
| 0.93 s | setup | `api/test_authorization.py::test_an_administrator_may_approve_above_the_adjuster_limit` |
| 0.83 s | setup | `api/test_auth.py::test_login_with_valid_credentials_returns_a_bearer_token` |
| 0.77 s | setup | `ui/test_claim_workflow.py::test_the_audit_trail_is_visible_and_complete` |
| 0.71 s | call | `e2e/test_claim_lifecycle.py::test_deactivating_a_user_immediately_ends_their_browser_session` |

Every one of them is **setup**, and the first is the browser starting. There is no
slow *test* in this suite - there is fixture cost, which is why worker count stops
paying off before the core count does.

---

## What is measured, and what is deliberately not

| Measured | How |
|---|---|
| Test counts per layer and per intent | `pytest -m <marker> --collect-only -q` |
| Serial and parallel wall-clock | `scripts/benchmark.ps1` - warm-up discarded, medians, one session |
| Flake rate | Ten consecutive `-n 4` runs |
| Slowest tests | `pytest --durations=12` |
| Framework size | 2,914 lines excluding blanks and comments |

| **Not** measured, and why |
|---|
| **Application code coverage.** Black-box tests do not produce meaningful line coverage of the system under test, and quoting one would imply a relationship that does not exist. What is tracked instead is the matrix: which rule is asserted, at which layer |
| **Triage-time reduction.** The capability is real and described; the percentage would be invented, because nobody timed themselves debugging a seeded failure with and without artefacts |
| **Load or performance characteristics of the application.** Out of scope, stated as such, and no response-time claim appears anywhere beyond one smoke-level check |

---

## Interview questions this phase earns you

**"How much faster is it in parallel?"**
Roughly the ratio in the table, on 16 logical cores, median of three after a
warm-up. And it is well under the worker count for three reasons I can name.
Anyone quoting a clean multiple of their worker count has not measured it.

**"You said 107 s to 30 s. Why should I believe that one?"**
Because the cause was measured directly rather than inferred from two suite runs:
355 ms to build an SSL context, 0.1 ms to reuse one, one client per identity per
test. The mechanism predicts the number. A before/after pair with no mechanism is
an anecdote.

**"What is your flake rate?"**
Defined as tests that changed outcome divided by tests run, measured over ten
consecutive parallel runs. And the definition matters as much as the number: a
suite that counts "passed on retry" as passed has a flake rate of zero and no
idea what it is doing.
