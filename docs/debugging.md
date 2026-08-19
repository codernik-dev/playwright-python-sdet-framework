# Debugging runbook

> CI is red. You did not write the test, you did not write the application, and
> it is 03:00. This page is the order to do things in.

The whole framework is built so that **you should not need to reproduce the
failure to understand it.** If you find yourself re-running the suite to find out
what happened, that is a gap in the artefacts — file it as one.

---

## 0. Before anything: which environment was this?

Every report and every run answers this without being asked:

```
claimdesk-qa: env=ci  base_url=http://127.0.0.1:8000  api=http://127.0.0.1:8000/api/v1
claimdesk-qa: database=postgresql://claimdesk_qa_ro:***masked***@localhost:5432/claimdesk  headless=True  run_id=jenkins-9
claimdesk-qa: faker_seed=1683326883  (set FAKER_SEED to reproduce)
```

In Allure the same block is the **Environment** widget. Read it first. More red
builds are explained by "it ran against the wrong thing" than by any product
defect, and thirty seconds here saves an hour.

---

## 1. Let the report classify it before you form a theory

Open the Allure report and look at **Categories**, not at the failures.

| Category | What it means | Who owns it |
|---|---|---|
| **Environment problem** | `ServiceNotReadyError`, `DatabaseError`, `ConnectError`, `InsufficientPrivilege` | Infrastructure. The application or database was not reachable — there is no product bug here |
| **Wrong HTTP status** | The API returned something else | Product, probably |
| **Contract violation** | The response did not match its model | Product — a field changed shape |
| **Browser timeout** | An element never became actionable | Product or locator; go to the trace |
| **Product defect** | An assertion failed, none of the above | Read on |
| **Test defect** | The test itself raised | Ours |

Thirteen failures under *Environment problem* is a five-second triage. The same
thirteen under *Product defect* is a wasted morning — which is exactly why the
categories key on exception **types** the framework raises deliberately, not on
message wording.

---

## 2. Read the failure message. It was written to be read

Assertions here are built to answer the question, not to state the number:

```
Expected HTTP 201 but got 422
  POST http://127.0.0.1:8000/api/v1/claims
  X-Request-Id: qa-933749c975
  response: {"detail":[{"loc":["body","incident_date"],"msg":"Incident date cannot be in the future."}]}
```

Method, URL, correlation id, and the body. In most cases the diagnosis is here
and the remaining steps are confirmation.

---

## 3. Open the attachments, in this order

Each answers a different question. Going in order stops you reading a 30 MB trace
to learn something the log said in one line.

| Attachment | Answers |
|---|---|
| **test log** | What the framework did, in order, with the correlation id on every line |
| **HTTP exchanges** | What was actually sent and returned — every client the test used, in one timeline |
| **SQL executed** | What the database actually contained, and how many rows came back |
| **screenshot** | What the user would have seen |
| **page HTML** | Whether the element existed at all — this is what separates "wrong locator" from "page never rendered" |
| **playwright trace** | When it went wrong, step by step |

---

## 4. Open the trace for a browser failure

```powershell
playwright show-trace artifacts/<run-id>/<test>/trace.zip
```

The trace viewer is the best failure-debugging tool in browser automation and it
is worth learning properly:

- **Timeline with screenshots** — scrub to the moment it broke.
- **Action list** — every click and assertion, with the locator used and how long
  it waited.
- **DOM snapshot at each step** — inspect the page as it was, not as it is now.
- **Network tab** — the request the page made, which frequently explains
  everything.
- **Console** — a JavaScript error the test could not see.

The usual outcome: the element was there but covered, or it appeared 50 ms after
the assertion gave up, or the request behind it returned a 500.

---

## 5. Decide: product bug, test bug, or environment?

The question to ask in each case:

| Symptom | Ask | Usually |
|---|---|---|
| Fails everywhere, every time | Does the API do it too? Try `curl` | Product |
| Fails only in parallel | Does it assert on data another worker can change? | **Test** — see the rule below |
| Fails only in CI | Timezone, locale, cold start, missing browser dependency | Environment |
| Fails only in one browser | Is it in the trace's console? | Product, engine-specific |
| Passes on rerun | Reported as FLAKY, never green | Investigate now, while the artefacts exist |

**The rule this project learned twice, in two different layers:** a test may
assert an **invariant** globally — something true no matter who else is writing —
but never an **aggregate**. `count(*) WHERE status='DRAFT'` is a fact about a
shared database, not about your test.

---

## 6. Reproduce it locally, exactly

```powershell
# Same data as the failing run: the seed is printed in the header and the report.
$env:FAKER_SEED = "1683326883"

# The single test, with a visible browser and slowed down.
pytest "tests/ui/test_claim_form.py::test_a_future_incident_date_is_rejected" --headed --slowmo 300

# Or by correlation id, in the application's own log:
Select-String -Path app.log -Pattern "qa-933749c975"
```

That last one is the point of the correlation id: **one grep joins the test log,
the HTTP exchange and the application's server-side log.** It costs about twenty
lines of framework code and turns "the API returned 500" into the stack trace
that caused it.

---

## 7. When there are no artefacts at all

If the run produced nothing, the failure happened before the tests did:

| Symptom | Cause |
|---|---|
| `ServiceNotReadyError: ClaimDesk at ... did not become ready` | The application never started. Read `app.log`, not the test code |
| `DatabaseError: could not connect` | Database down or `DB_*` wrong. The message names the DSN with the password masked |
| Collection error naming a file | A test outside a layer directory under `tests/` |
| `*** DATABASE VALIDATION IS DISABLED ***` in the header | `DB_ENABLED=false`. The run was green **and never touched the database** |

That last line is shouted deliberately. A green run that skipped the database
must never be mistaken for one that validated it.

---

## 8. Where the evidence lives

```
artifacts/<run-id>/
  logs/worker-gw0.log          one file per xdist worker: the full narrative
  tests_ui_test_login__.../
    test.log                   this test only, correlation id on every line
    http.log                   every request and response it made
    sql.log                    every statement it ran, and the row counts
    screenshot-0.png           full page, at the moment of failure
    page-0.html                the DOM as rendered
    trace.zip                  playwright show-trace
```

**Only failures are here.** Passing tests are captured and then discarded, so this
directory is a list of problems rather than a haystack. If a directory exists,
something in it is worth reading.

In CI the same tree is the `failure-artefacts` upload, and `QA_RUN_ID` is set to
the build number so the folder links back to the pipeline run that produced it.
