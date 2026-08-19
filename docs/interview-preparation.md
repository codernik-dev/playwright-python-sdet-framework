# Interview preparation

> Every answer here is defensible because it happened. Where a number appears it
> was measured; where something is unverified it says so. **The fastest way to
> fail an interview with this project is to claim more than it does** — an
> interviewer's first follow-up is always "how did you measure that?"

---

## The 90-second version

> ClaimDesk QA is a test automation framework in Python that exercises an
> insurance-claims application through three independent layers — browser, REST
> API, and PostgreSQL — as an installable package with its own unit tests, strict
> typing, and a lint rule that makes it impossible to import the application
> under test. 351 tests: 130 framework, 157 API, 32 browser, 28 database, 4
> cross-layer journeys. It runs on GitHub Actions as a PR gate and a nightly
> cross-browser matrix, in Docker Compose, and on Jenkins. The application is a
> fixture; the framework is the deliverable.

Then stop. The next question tells you which thread they care about.

---

## The questions that decide the interview

### "You wrote the app you're testing — doesn't that invalidate it?"

It would, if the framework could see inside it. It cannot:

- The framework never imports application code, and that is **enforced by a lint
  rule in CI**, not by discipline:
  ```
  TID251 `claimdesk` is banned: The test framework must NEVER import the
  application under test.
  ```
- The database role holds `SELECT` and nothing else, so a test physically cannot
  manufacture state the application would never produce. An `INSERT` fails with
  `InsufficientPrivilege`.
- The Docker workflow asserts `import claimdesk` **fails inside the test image**,
  because the application is not installed there at all.
- The application has its own 58 unit tests and was deliberately left with real
  rough edges rather than shaped to make testing easy.

And then be honest: a purpose-built application is a real limitation. What it
buys is a database to validate against and a status machine worth testing —
neither of which any public demo site offers.

### "How do you decide what to test at which layer?"

One rule, and I will defend the trade-off:

| Question | Layer |
|---|---|
| Does the business rule work? | API |
| Is the persisted state correct and auditable? | Database |
| Can a human actually do it in a browser? | UI |
| Does the whole chain hold across roles? | E2E |
| Does the framework itself work? | `tests/framework/` |

The anti-pattern I avoided explicitly: testing the same rule at all four layers.
The over-limit approval rule is tested exhaustively at the API — every boundary
value — and **once** in the UI, that a user sees the error and the status does not
change. That single decision is the difference between a suite that finishes in
half a minute and one that takes an hour.

### "Show me a bug you found."

Pick by what they seem to care about.

**A test that passed for the wrong reason.** `GET /claims` with no
`Authorization` header returned `200`. It looked like an auth bypass; `curl`
proved the application was correct. `httpx` persists cookies, so a leftover
session cookie from an earlier login had authenticated the "anonymous" request.
**That check would have kept passing with authentication removed entirely.** Now
every identity gets its own cookie-less client — ADR 0007.

**A bug that had not failed yet.** The application refuses future incident dates
and the suite asserts both sides of that boundary. Both used `date.today()` — the
*local* date of whichever machine asked. Same machine, so they always agreed.
Then Docker made them two machines: a UTC container and an IST runner. Between
00:00 and 05:30 the runner is a day ahead, so "an incident dated today is
accepted" would fail for five and a half hours a day — while its matched pair
still passed, hiding half the problem. Both sides now answer in UTC explicitly,
so they agree by construction.

**A bug that only exists in containers.** Moving the suite into Docker Compose made
*every* browser test fail with `net::ERR_SSL_PROTOCOL_ERROR at http://app:8000` while
*every* API test passed. The compose service was named `app`, a service name becomes a
hostname, and **`.app` is a real gTLD whose entire namespace is HSTS-preloaded** — so
Chromium force-upgraded the URL to HTTPS and spoke TLS to a plain HTTP server. The
diagnostic was the pattern rather than the message: httpx does not implement HSTS,
browsers do, so when one client reaches a service and another cannot over the same URL,
the difference is in the client.

**A finding I decided was not a bug.** Non-ASCII digits (`１２３`, `١٢٣`) are
accepted and normalised. Unambiguous value, no rule bypassed, so it is a
characterisation test with the reasoning recorded rather than a "fix". Knowing
which findings are bugs is the actual skill.

### "How do you handle flaky tests?"

Written down before it was needed — ADR 0009:

- Retries are **diagnostics**, not a cure. One retry, UI and E2E only, CI only.
- API and database tests are **never** retried. A test that fails intermittently
  there is *wrong*, not flaky, and a retry deletes the evidence.
- A test that passes on retry is printed in a `FLAKY` block with the seed to
  reproduce it. It is not green.
- `MAX_RERUNS = 1` is not configurable, and a unit test pins it — because a retry
  budget that can be raised will be raised, at 5pm, by whoever is shipping.

And a real one: a pagination test failed ~50% at `-n 4` and never serially. Other
workers inserted rows between the two page requests. The assertion was right and
the **premise** was wrong — you cannot paginate a data set that is being written
to. The rule I took from it, after making the same mistake again in the database
layer: *a test may assert an invariant globally, never an aggregate.*

### "How fast is it, and how do you know?"

Measured on an AMD Ryzen 7 5800H, 16 logical cores, median of three runs after a
discarded warm-up, both modes back to back:

| Mode | Median |
|---|---|
| serial | **24.88 s** |
| `-n 2` | 18.75 s |
| **`-n 4`** | **16.82 s** ← optimum |
| `-n 8` | 19.03 s |
| `-n auto` (16) | 23.81 s |

The headline is not the 1.48×. It is that **the curve turns around**: eight workers
are slower than four, and sixteen are barely faster than serial. `-n auto` — the
default everyone reaches for — throws away nearly the whole benefit on this suite,
because session fixtures are per worker, the application is a single process, and
the suite is I/O-bound. "Use all your cores" is a guess, and it is measurable in
ten minutes.

The measurement script itself is built to resist flattering me: warm-up
discarded, medians not bests, both modes in one session, the machine printed
alongside, and it **aborts if a run fails** — a timing from a failing suite may
be a suite that exited early.

### "The biggest speed-up you made?"

Not a clever optimisation. Every API test spent ~0.4 s in *setup* while its
assertions ran in 0.02 s, and the application answered in 2.8 ms. **Uniform
overhead rules out the product** — real performance problems are lumpy. Measured:
`httpx.Client()` builds a fresh SSL context per instance, 355 ms, and the
framework builds a client per identity per test. One shared context: **107 s →
30 s**.

Two regression tests pin it — one that the context is reused, one that it still
*verifies certificates* — so the tempting wrong fix (`verify=False`, invisible
today because every URL is `http://`) fails the suite instead of passing it.

### "Walk me through what happens when CI goes red at 3am."

`docs/debugging.md`, in order: which environment (the report says so), then the
**category** — environment / product / test — before forming any theory, then the
assertion message, which carries method, URL, correlation id and body. Then the
attachments: log, HTTP exchanges, SQL, screenshot, page HTML, trace.

The correlation id is the piece I would defend hardest: every request carries an
`X-Request-Id` derived from the test's node id, and the application logs it. One
grep joins the test log, the HTTP exchange and the server-side stack trace. About
twenty lines of framework code.

### "What is in your report, and why?"

A report earns its existence by answering four questions before anyone asks:
against what did this run, whose problem is it, which CI run produced it, and
what actually happened. Environment block, failure categories, executor, and
attachments — nothing else, because decoration makes a report slower to read at
exactly the moment reading speed matters.

The categories are the part that changes behaviour: they key on **exception
types the framework raises deliberately** — `FrameworkError` means the
environment, `AssertionError` means the product. Proved by pointing the database
at a dead port: 13 failures, all filed as *Environment problem*, none as product
defects.

### "What went wrong when you built the reporting?"

Three things, and two were invisible until I generated a real report from real
failures:

1. Every category regex matched **nothing**. Allure requires a full match and `.`
   does not cross newlines, so no stack trace could ever match — and a category
   that matches nothing looks identical to a category with nothing to match. My
   unit test had passed because I fed it a one-line trace.
2. I keyed the browser category on `playwright._impl`, a module path that does
   not appear in what Allure records. Fixed by reading the actual recorded trace
   instead of guessing a third time.
3. I wrote a marker-to-tag mapping that allure-pytest already provides. The
   report showed every tag twice. Deleted rather than kept.

### "Jenkins or GitHub Actions?"

Both, for different reasons. GitHub Actions is the CI that genuinely runs this
repository — PR gate plus a nightly Chromium/Firefox/WebKit matrix, all three
green. Jenkins is what most enterprise QA organisations actually run, and the
Jenkinsfile was **executed**: ten builds on a real controller, six of them red
first. The final build ran **351 tests green** through the quality gate, the two-pass
runner, report generation, JUnit publishing, archiving and workspace cleanup.

The difference worth stating: a Jenkins agent is **persistent**. A GitHub runner
is destroyed after every job, so a leaked process is somebody else's problem; on
Jenkins it is inherited by the next build. That is why `post { cleanup }` — which
runs even when a build is aborted — tears down compose and the workspace.

### "What would you do next?"

In order:

1. **Contract testing against the OpenAPI schema itself**, so a response shape
   change is caught by generation rather than by hand-written models.
2. **Accessibility smoke checks** (axe) on the main pages — currently out of
   scope and stated as such.
3. **A real staging target**, to prove the framework is not hard-wired to Docker.
4. **Mutation testing on the framework's own code**, because "our tests pass" is
   a weak claim for a test framework specifically.

Not on the list: Kubernetes, a BDD layer, a keyword-driven DSL. Each is rejected
in the README with a reason, and I would defend those rejections as judgement
rather than as gaps.

---

## Questions I would struggle with, and the honest answer

Prepared deliberately. Being caught without an answer is worse than the gap.

| Question | Honest answer |
|---|---|
| "How does this scale to 5,000 tests?" | It has not been tried. At that size the session fixtures being per-worker would dominate, and I would move to a shared auth token cache and sharding by timing rather than by file. |
| "Have you used a real device cloud / Selenium Grid?" | No. Playwright's browser contexts removed the need here, and I would not claim experience I do not have. |
| "What is your test coverage?" | Of the application, unknown and deliberately unmeasured — black-box tests do not have meaningful line coverage, and reporting one would be misleading. What is measured is the matrix: which rules are asserted and at which layer. |
| "Load testing?" | Explicitly out of scope. There is one soft response-time check labelled smoke-level, and no performance claims anywhere. |
| "Did Docker actually run?" | Yes — 351 tests green inside the container. I first assessed it as impossible here (no admin) and that was wrong: WSL2 was already installed and only a distribution was missing, which is a per-user install. The GitHub workflow still exists as independent confirmation on a clean runner, and that part has not been dispatched. |

---

## The one-sentence summary of the whole project

**Every number in this repository came from a command that was run, and
everything that was not run says so.**
