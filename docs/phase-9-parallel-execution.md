# Phase 9 — Parallel execution, markers, and the retry policy

> Teaching document. The two-pass execution model, a retry policy narrow enough
> that it cannot be abused, a marker I deleted, and a measured speed-up that is
> smaller than the marketing version — with the reason.

---

## What was built

| File | Responsibility |
|---|---|
| `src/claimdesk_qa/core/flakiness.py` | The retry policy and the reproducibility seed, as testable functions |
| `tests/conftest.py` | Applies the policy in one place; prints a `FLAKY` block; prints the effective seed |
| `scripts/run_suite.ps1` · `.sh` | The two-pass runner: parallel, then serial |
| `scripts/benchmark.ps1` | Serial-versus-parallel measurement, built to resist flattering itself |
| `docs/adr/0009-retries-are-diagnostics.md` | The retry decision, written down |
| `tests/framework/test_flakiness.py` | 12 unit tests |

---

## Decision 1 — Two passes, and why the second one is empty

```
pass 1   pytest -m "not serial" -n auto
pass 2   pytest -m serial        -p no:xdist
```

A `serial` test mutates something the whole suite shares — an application-wide
setting, or a seeded account other tests sign in as. Running it beside anything
else produces failures in *other* tests, which is the worst kind of flake to
diagnose, because the test that fails is not the test that is wrong.

**No test in this suite carries the marker.** That is the intended outcome, not
an omission. Every test creates uniquely-keyed data through the API and asserts
only on data it created; even the nastiest candidate — "deactivate a user and
prove their live browser session dies" — creates a throwaway user rather than
touching a seeded one.

The pass exists anyway. The moment somebody genuinely needs the marker is the
moment they must not *also* have to invent the mechanism, because that is when it
gets skipped and the test goes in unmarked.

### The bug that made the empty pass worth writing

`pytest -m serial` collects nothing and exits **5**, which means "no tests
collected". The first version of the runner reported a fully passing suite as a
failure, and CI would have failed the build while the console said `Suite
passed`. Exit code 5 is now treated as success **for that pass only**.

Then the script did it again from the other direction: it printed
`Suite passed (both passes)` and exited 5 anyway, because PowerShell returns the
last command's exit status unless told otherwise. Both scripts now `exit 0`
explicitly.

Two bugs, same shape: **a wrapper that reports its own success incorrectly is
worse than no wrapper**, because everything downstream believes it.

---

## Decision 2 — Retries, constrained so they cannot become a cure

The full reasoning is in [ADR 0009](adr/0009-retries-are-diagnostics.md). The
short version:

| Rule | Why |
|---|---|
| UI and E2E only | A browser shares a machine with a compositor and a renderer. An API or DB test that fails intermittently is **wrong**, not flaky |
| CI only | Locally, reproduce it — the developer is right there with the trace |
| One retry | If one cannot decide whether it reproduces, two cannot either |
| Passing on retry is reported as **FLAKY** | Without this the policy is a lie |
| Applied in one hook, not per test | A decorator is a decision made once by whoever was annoyed that day |
| `MAX_RERUNS` is not configurable | A retry budget that can be raised will be raised, at 5pm, by whoever is shipping |

The last one is pinned by a test that says so in its docstring. That is not
decoration: the test is the thing that argues back when the number is convenient
to change.

---

## Decision 3 — Print the seed that was used, not the seed that was configured

The run header used to report `faker_seed=None` whenever nothing was configured.
Technically true, practically useless: a seed *was* used — derived from the run
id — and a reader trying to reproduce a data-dependent failure needs the number,
not the news that they did not choose it.

```
claimdesk-qa: faker_seed=1683326883  (set FAKER_SEED to reproduce)
```

The derivation moved into `core.flakiness.effective_seed` because three places
need it: the header, the `session_seed` fixture, and the Allure environment
block. Three copies of a derivation is three chances for the report to print a
number that reproduces nothing.

`effective_seed(0, ...)` returning `0` has its own test. `if configured:` would
have silently ignored a seed of zero, and the failure would have been invisible —
the run works, just not with the seed that was asked for.

---

## Decision 4 — A marker I deleted

`regression` was registered in Phase 2 and never applied to a single test,
because to be honest it would have to mean *every* test.

A marker that selects everything is not a filter, it is a second name for the
suite. The nightly job runs the whole suite; that **is** the regression run.
Deleted.

The three unused markers that stayed — `serial`, `quarantine`, `slow` — are
different in kind: each names a decision somebody will need to make, and each has
machinery behind it (the serial pass, the quarantine exclusion, the severity
mapping). An unused marker with a mechanism is a policy. An unused marker without
one is clutter.

---

## Decision 5 — A benchmark built to resist flattering itself

Every property of `scripts/benchmark.ps1` exists to stop it producing a nicer
number than the truth:

- **A discarded warm-up run.** The first run of anything is slower — cold caches,
  a browser binary read from disk for the first time. Comparing a cold "before"
  against a warm "after" reliably overstates the gain.
- **Repetitions and the median.** One before/after pair is an anecdote.
- **Both modes in the same session, on the same machine, back to back.**
- **The machine is printed with the result.** A parallel speed-up is a statement
  about a core count; without it the number means nothing.
- **A failing run aborts the benchmark.** A timing taken from a suite that
  failed may be a suite that exited early, and that number is not slower or
  faster — it is meaningless.
- **No "% improvement" headline.** The ratio is printed next to the spread, and
  what it is worth is the reader's judgement.

---

## Measurements

Machine: **AMD Ryzen 7 5800H, 16 logical cores**, Windows 11, Python 3.12.10.
342 tests. Three measured runs per mode after a discarded warm-up.

| Mode | Median | Min | Max |
|---|---|---|---|
| serial (`-p no:xdist`) | **32.77 s** | 31.58 s | 33.29 s |
| parallel (`-n 4`) | **23.53 s** | 22.75 s | 27.12 s |
| **ratio** | **1.39×** | | |

### Why the ratio is not 4×, and why that is the honest number

Four workers do not make a suite four times faster, and a project claiming they
do has not measured it. Three costs do not divide:

1. **Session fixtures are per worker, not per run.** Each worker performs its own
   four API logins to build storage states, its own four role logins, and starts
   its own browser. With four workers that setup is paid four times.
2. **The application is one process.** Four workers share one uvicorn and one
   PostgreSQL; past a point they queue behind each other rather than the CPU.
3. **The suite is I/O-bound, not CPU-bound.** Parallelism helps least exactly
   where the work is waiting rather than computing.

The gain is real and it is worth having on a gate. It is simply not the number
that makes a good headline, and the difference between those two is the whole
subject of Phase 15.

---

## Verification — commands run, output observed

| Check | Result |
|---|---|
| Full suite, serial | ✅ `342 passed` |
| Two-pass runner | ✅ `Suite passed (both passes).`, script exit code **0** |
| Serial pass with nothing to run | ✅ `(no tests matched - nothing to run in this pass)`, not a failure |
| Five consecutive `-n 4` runs | ✅ `342 passed` in 21.46 / 22.79 / 21.64 / 22.47 / 23.39 s — no flakes |
| Effective seed in the run header | ✅ `faker_seed=1683326883  (set FAKER_SEED to reproduce)` |
| Framework unit tests | ✅ `121 passed` |
| Quality gate | ✅ ruff · ruff-format · mypy strict, clean |

⚠️ **NOT VERIFIED in Phase 9:** the retry path itself has never fired, because it
is CI-only and nothing has flaked in CI. `reruns_for` is unit-tested in both
directions, and the `FLAKY` summary block is exercised by no real rerun yet — it
is written and reviewed, not observed. Said plainly rather than quietly implied.

---

## Interview questions this phase earns you

**"How do you make a suite safe to run in parallel?"**
Not with a `serial` marker — with data ownership. Every test creates its own
uniquely-keyed data through the API and asserts only on data it created. The
marker is the escape hatch for the cases that genuinely cannot, and in this suite
there are none. The rule underneath it, learned twice the hard way in Phase 7: a
test may assert an **invariant** globally, never an **aggregate**.

**"Do you use retries?"**
One, on browser tests, in CI only, and a test that passes on retry is reported as
flaky rather than green. Retries answer "does this reproduce" — that is the whole
value. Anything more and the build is green because it was asked twice.

**"You said parallel execution made it faster. By how much?"**
Median of three runs after a warm-up, both modes back to back on the same
16-core machine — and the ratio is well under the worker count, because session
fixtures are per worker, the application is a single process, and the suite is
I/O-bound. That is the measurement; the four-times number would be a guess.

---

## What Phase 10 builds on

The two-pass runner and the marker taxonomy are what the containerised runner and
the Jenkins pipeline invoke. Neither of those should re-express the execution
model in YAML or Groovy — they call the same script a developer calls, so the two
cannot drift apart.
