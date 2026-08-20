# Phase 12 - GitHub Actions

> Teaching document. Two workflows, verified against real runs - not YAML that
> was written, pushed, and assumed to work.

---

## What was built

| File | Responsibility |
|---|---|
| `.github/workflows/tests.yml` | The pull-request gate: `quality` then `suite` |
| `.github/workflows/nightly.yml` | Full regression across Chromium, Firefox and WebKit |
| `scripts/setup_ci_db.sh` | Creates the database and its two roles in a CI PostgreSQL service |

---

## Decision 1 - Two jobs, so failures arrive in the right order

```
quality  →  suite
```

`quality` runs lint, types and the framework's own unit tests with **no services,
no browser, no database**. It finishes in about 45 seconds. If the framework
itself is unsound there is no point starting a database and a browser to test
against it - and the person waiting gets their answer in under a minute instead
of twelve.

`suite` then runs the API, database, browser and end-to-end tests against a real
PostgreSQL 18 service and a real running application.

The split is not cosmetic: it is the difference between "your lint failed" arriving
at 45 seconds and arriving at 13 minutes.

---

## Decision 2 - Credentials are generated, not stored

```yaml
- name: Generate ephemeral credentials
  run: |
    echo "DB_PASSWORD=$(openssl rand -hex 24)" >> "$GITHUB_ENV"
    echo "APP_DB_PASSWORD=$(openssl rand -hex 24)" >> "$GITHUB_ENV"
    echo "APP_JWT_SECRET=$(openssl rand -hex 32)" >> "$GITHUB_ENV"
```

Deliberately **not** GitHub secrets. The database exists for a few minutes inside
one runner and is destroyed with it, so a stored secret would be a long-lived
credential protecting something that does not outlive the job - and a value nobody
can read is safer than a value somebody must remember to rotate.

Real environments get real secrets. Disposable ones get disposable credentials.
Knowing which is which is the point; reaching for the secret store reflexively is
not security, it is habit.

The same two-role split as everywhere else (ADR 0003): the application owns the
schema, the QA role holds `SELECT` and nothing else. CI is where that separation
matters most, because it is the environment nobody is watching.

**Verified before pushing** by running `setup_ci_db.sh` against the local cluster:
the read-only role could `SELECT` from a table and was refused an `INSERT` with
`ERROR: permission denied for table t`.

---

## Decision 3 - No `sleep` before the tests

```yaml
- name: Start ClaimDesk
  run: nohup python -m uvicorn claimdesk.main:app --app-dir app ... &

- name: Run the suite
  run: pytest -q -n 2 --junitxml=junit-suite.xml
```

Nothing waits between them. The `app_ready` fixture polls `/health/ready`, which is
faster than a sleep when the application is already up and *correct* when the
runner is slow. A sleep is wrong in both directions, and the fix is never a bigger
number.

---

## The two failures, and what they taught

### Failure 1 - `Permission denied`, exit code 126

The first run failed instantly on `./scripts/setup_ci_db.sh`.

I had run `chmod +x` locally. That changed the filesystem and **nothing in the
commit**: Git on Windows does not record the executable bit, so the runner checked
out a file it could not execute.

```bash
git update-index --chmod=+x scripts/setup_ci_db.sh
```

A pure Windows-to-Linux crossing bug, and one that no amount of local testing
would ever surface - the script runs fine locally through `bash script.sh`.

### Failure 2 - a red X that was not the real failure

When the database step failed, the application never started, so the
`Application log` step failed too on a missing file. Two red X's, one real
problem, and the eye goes to the last one.

```yaml
run: tail -n 200 app.log || echo "(the application never started)"
```

Diagnostic steps must never be able to fail. Their job is to explain a failure,
not to add one.

---

## Measuring CI, then acting on the measurement

The first green run took **752 seconds**, of which the tests were **21**.

```
684s  Install Chromium          ← 91% of the job
 21s  Run the suite
 17s  Install the framework
 13s  Initialize containers
```

Optimising from there would have been guesswork, because `playwright install
--with-deps chromium` does two unrelated things: it downloads a browser (~120 MB,
identical every run, cacheable) and it apt-installs system libraries into the
runner image (not cacheable - the image is discarded).

Splitting them into separate steps made each cost visible:

```
249s  Install browser system libraries   ← apt
 11s  Install Chromium                   ← the download
```

**Job total: 752s → 343s.** And the more useful result is the shape of the answer:
the download was never the problem. It is 11 seconds. The 249 seconds is `apt`,
and `apt` cannot be cached because the runner image does not persist.

### The cache question, answered - and a caution about CI measurement

A fourth run, with a warm cache, came in at **78 s** against the previous **343 s**.

It would be easy - and wrong - to report "752 s to 78 s, a 10x CI speedup from
caching". The step timings do not support that:

| Step | Run 2 (cold) | Run 3 (split) | Run 4 (warm cache) |
|---|---|---|---|
| Browser install (combined) | 684 s | - | - |
| apt system libraries | - | **249 s** | **13 s** |
| browser download | - | 11 s | ~0 s (cache hit) |
| Test execution | 21 s | 19 s | 21 s |
| **Job total** | **752 s** | **343 s** | **78 s** |

The cache can only explain the **11 s** download. The apt step fell from 249 s to
13 s **with identical YAML** - that is variance in the runner's package mirrors,
not something I changed.

Two conclusions, and the second matters more:

1. **The cache saves ~11 s and costs 28 s to write.** Marginal at best. Kept for
   now because it is already written and harmless, but it is not the reason the
   job got faster, and claiming otherwise would be inventing a result.
2. **A single before/after comparison in CI is not a measurement.** The dominant
   cost varied nineteen-fold between two runs of the same configuration. Anyone
   reporting a speedup from one pair of runs is at serious risk of taking credit
   for the weather.

The defensible claim from this exercise is narrow and useful: **splitting the step
revealed that the browser download is 11 s and the system libraries are the real
cost** - which is what tells you where to look next.

The real remaining lever is the 249-second `apt` step, which would need either the
official Playwright container image (removing apt entirely, at the cost of
coupling the image tag to the pip-installed Playwright version) or an empirical
check of whether the runner image already carries what Chromium needs. Both are
worth measuring; neither is worth assuming.

---

## Verified runs

Not "the YAML looks right" - actual runs, watched to completion.

| Run | Outcome |
|---|---|
| First attempt | ❌ `Permission denied` (exit 126) - executable bit not in the commit |
| Second attempt | ✅ `quality` 43 s, `suite` 12 m 32 s - **`293 passed in 18.55s`** |
| Third attempt | ✅ **343 s** job after splitting the browser install |
| Fourth attempt | ✅ **78 s** job - but see the variance caveat above |
| Nightly (dispatched) | ✅ **all three engines green**: Chromium `293 passed in 17.98s`, Firefox `293 passed in 21.62s`, WebKit `293 passed in 26.60s` |

Artefacts published by the green run: `test-results` (1.5 MB - JUnit XML plus
Allure results) and `junit-quality`. On failure, `failure-artefacts` carries the
Playwright traces, screenshots, page HTML and per-test logs - so a CI failure can
be replayed with `playwright show-trace` instead of reproduced.

---

## Decision 4 - Nightly is a matrix that does not fail fast

```yaml
strategy:
  fail-fast: false
  matrix:
    browser: [chromium, firefox, webkit]
```

`fail-fast: false` is the whole point. Knowing that a change breaks **WebKit only**
is far more useful than knowing it broke "a browser" - and with fail-fast enabled
the other two engines are cancelled the moment one fails, destroying exactly the
information you need.

A PR gate answers *"did I break something?"* and must stay fast enough that nobody
routes around it. A nightly run answers *"does it work everywhere?"* and can afford
to be thorough, because nobody is waiting on it.

---

## Interview questions this phase earns you

**Q: What runs on a pull request versus nightly, and why?**
On a PR: lint, types and framework unit tests first - under a minute, no services -
then the full suite on Chromium only. Nightly: the same suite across Chromium,
Firefox and WebKit with `fail-fast: false`. A gate people wait twelve minutes for
is a gate they learn to bypass; a nightly run can be thorough because nobody is
blocked on it.

**Q: How do you handle secrets in CI?**
By first asking whether the thing needs a secret at all. My CI database lives for
minutes inside one runner, so its credentials are generated per run with
`openssl rand` and never stored - a value nobody can read beats a value somebody
must remember to rotate. A real environment gets a real secret store; reaching for
one reflexively is habit, not security.

**Q: Your CI is slow. What do you do?**
Measure before changing anything. Mine was 752 seconds with 21 seconds of testing,
and one step was 91% of it - but that step did two unrelated things. Splitting it
showed the browser download was 11 seconds and apt was 249. I had already added a
cache for the download, which turned out to cost 28 seconds to write to save 11.
The measurement told me to consider removing my own optimisation.

**Q: What broke first when you set up CI?**
`Permission denied`, exit 126. `chmod +x` locally changes the filesystem, not the
commit - Git on Windows does not record the executable bit, so the runner checked
out a non-executable script. Fixed with `git update-index --chmod=+x`. It is a
Windows-to-Linux crossing bug that local testing cannot surface.

**Q: How would you debug a CI failure you cannot reproduce?**
Replay it rather than reproduce it. Failing runs upload the Playwright trace,
screenshot, page HTML and per-test log; `playwright show-trace trace.zip` gives a
DOM snapshot per step, the network log and the source line of each action. The
application's own log is uploaded alongside, and every request carries a
correlation id that joins the two.
