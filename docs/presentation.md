# Presenting this project - CV, GitHub, LinkedIn

> Every claim below is traceable to a command that was run. Anything that has not
> been measured is absent rather than estimated. If a recruiter or an interviewer
> asks "how do you know?", the answer is a file in this repository.

---

## CV bullets

Written to survive the follow-up question, which is always *"how did you measure
that?"*

1. Designed and built an end-to-end test automation framework in **Python
   (pytest, Playwright, httpx, psycopg/PostgreSQL)** covering UI, REST API,
   database-state and cross-layer integration testing, structured as an
   installable package with strict typing, its own unit tests, and a lint rule
   that makes importing the application under test impossible.

2. Implemented a layered architecture - Page Objects and Component Objects for
   the browser, Service Objects for the API, parameterised Query Objects on a
   **read-only** database role - delivering **351 automated tests: 157 API, 32
   browser, 28 database, 4 cross-layer journeys and 130 framework unit tests.**

3. Integrated the suite into **three** independent pipelines: GitHub Actions (PR
   gate plus a nightly Chromium/Firefox/WebKit matrix, all three green), Docker
   Compose, and a parameterised **Jenkins** declarative pipeline with credential
   binding, JUnit and Allure publishing and workspace cleanup - verified by real
   builds, not by configuration alone.

4. Diagnosed a **3.5× suite-wide slowdown** to a shared TLS-context defect by
   observing that per-test overhead was *uniform* - which rules out the
   application - reducing full-suite wall-clock from **107 s to 30 s** measured,
   and pinning the fix with a regression test that fails if certificate
   verification is ever disabled to reclaim the time.

5. Cut failure triage to a single artefact set by capturing Playwright traces,
   screenshots, page HTML, correlated request/response logs and executed SQL **on
   failure only**, published through Allure with failure categories derived from
   the framework's own exception taxonomy - proved by pointing the database at a
   dead port and watching 13 failures file as *environment problems* rather than
   as product defects.

**Deliberately absent:** any coverage percentage (black-box tests have no
meaningful line coverage of the application), any load-testing claim, and any
"reduced triage time by X%" figure that was never timed.

---

## GitHub repository presentation

**Description**

> Production-style SDET framework: Python · pytest · Playwright · httpx ·
> PostgreSQL. UI, API and read-only database validation against a containerised
> claims application, with Allure reporting, GitHub Actions, Docker and Jenkins.

**Topics**

`python` · `pytest` · `playwright` · `test-automation` · `sdet` · `qa-automation`
· `api-testing` · `database-testing` · `postgresql` · `allure-report` ·
`github-actions` · `jenkins` · `docker` · `page-object-model` · `httpx`

**What a reviewer sees in the first thirty seconds** - and what each is there to
answer:

| They see | It answers |
|---|---|
| Badges: tests, nightly | Does it actually run? |
| "The application is a fixture. The framework is the deliverable." | Is this a toy? |
| The banned-import lint rule, quoted | Is the black-box boundary real? |
| Measured numbers with the machine beside them | Are the claims checkable? |
| `docs/progress.md` separating ✅ VERIFIED from ⚠️ NOT VERIFIED | Is this person honest about what they did not do? |

That last row does more work than any of the others.

---

## LinkedIn

### Featured project entry

**ClaimDesk QA - End-to-End SDET Automation Framework**

> A production-style test automation framework in Python that tests an insurance
> claims application through three independent layers: the browser (Playwright),
> the REST API (httpx) and the PostgreSQL database (read-only SQL). 351 tests
> across API, UI, database and cross-layer journeys, running on GitHub Actions,
> Docker and Jenkins.
>
> Built as a real codebase rather than a demo: an installable package, strict
> typing, architecture decision records, and a lint rule that makes importing the
> application under test impossible. The build log records what was verified and
> what was not, including the parts that could not be run on the machine it was
> built on.

### Announcement post

> I have spent the last few weeks building a test automation framework the way I
> would build one on the job, and publishing the mistakes along with it.
>
> ClaimDesk QA tests an insurance-claims application through three independent
> layers - browser, REST API, and a read-only PostgreSQL role - with 351 tests,
> Allure reporting, and pipelines on GitHub Actions, Docker and Jenkins.
>
> The parts I would actually talk about in an interview are the failures:
>
> • A negative auth test that **passed for the wrong reason** - a leftover session
>   cookie authenticated the "anonymous" request. It would have kept passing with
>   authentication removed entirely.
>
> • A **3.5× slowdown that was not the application's fault**. Every test spent
>   0.4 s in setup while the app answered in 2.8 ms. Uniform overhead rules out
>   the product. It was an SSL context being rebuilt for every HTTP client.
>
> • A **timezone bug that had never failed**. The app and the tests both asked
>   "what is today?" using the local clock. Fine on one machine - until Docker
>   made them two, and a boundary test would have failed for five and a half
>   hours a day, in one environment, as "flakiness".
>
> • Reporting code where **every failure-category regex silently matched
>   nothing**, so triage had quietly stopped working while the report looked
>   perfectly healthy.
>
> Everything measured in the repository came from a command that was run, and
> everything that was not run is labelled NOT VERIFIED with the reason. That
> discipline is the part I am proudest of - it is much easier to write "10×
> faster" than to write "1.39× on 16 cores, and here is why it is not 4×".
>
> Repository, build log and architecture decision records in the comments.
>
> #SDET #TestAutomation #Python #Playwright #pytest #QA #CICD

### What not to post

- No screenshot of a green test run as the headline image. Everyone has one, and
  it says nothing that the badge does not.
- No "10x faster" or invented percentages. The first competent reply will ask how
  it was measured, in public.
- Nothing about Docker "working" until the workflow has run green.

---

## The interview version of the same content

`docs/interview-preparation.md` - the questions that decide it, the answers, and
the five questions I would struggle with along with what I would honestly say.
