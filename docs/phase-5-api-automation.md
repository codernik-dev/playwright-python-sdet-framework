# Phase 5 — The API automation layer

> Teaching document. This is where the framework starts testing the application.
> 157 API tests, all passing, all safe to run in parallel.

---

## What was built

| File | Responsibility |
|---|---|
| `src/claimdesk_qa/domain.py` | The framework's **own copy** of the business vocabulary and transition table |
| `src/claimdesk_qa/api/client.py` | `ApiClient` (one per identity) and `ApiResponse` (assertions that explain themselves) |
| `src/claimdesk_qa/api/models.py` | Response contracts — strict, `Decimal` money, no extra fields |
| `src/claimdesk_qa/api/services/` | `AuthApi`, `ClaimsApi`, `UsersApi`, `PoliciesApi` |
| `src/claimdesk_qa/data/` | `ClaimFactory`, `UserFactory`, seeded-account constants |
| `tests/api/` | 157 tests across auth, CRUD, validation, authorisation and the state machine |

---

## Decision 1 — The client carries the ADR 0007 control

```python
response = self._client.request(...)
self._client.cookies.clear()   # discard Set-Cookie before it can authenticate later
```

ClaimDesk returns a `session` cookie on login and `httpx.Client` persists cookies.
In Phase 3 that combination made an unauthenticated check **pass while testing an
authenticated request**. Now:

* cookies are discarded after every response;
* each identity gets its own client (`customer_client`, `adjuster_client`, …);
* `anonymous_client` has never logged in at all.

`test_a_protected_endpoint_rejects_an_anonymous_request` is the same assertion
that once passed for the wrong reason. It now cannot.

The client also owns four things that would otherwise be repeated in every test:
the bearer header, a **mandatory** timeout, the `X-Request-Id` correlation header
read from the context variable, and a rolling record of the last 25 exchanges for
attaching to a failing test's report in Phase 8.

---

## Decision 2 — Assertion messages are a feature

A bare assertion tells you a number was wrong:

```
assert 403 == 201
```

The wrapper tells you the diagnosis:

```
Expected HTTP 201 but got 403
  POST http://127.0.0.1:8000/api/v1/claims
  X-Request-Id: qa-933749c975
  response: {"detail":"Amount 5000.01 exceeds the adjuster approval limit of 5000.00"}
```

Method, URL, correlation id, and the server's own explanation. In CI, where you
cannot re-run under a debugger, that difference is most of the triage.

`ApiResponse.model()` does the same for contract failures: a `ValidationError` is
re-raised as an `AssertionError`, because a response that does not match its
contract is a **product** failure, not a framework crash, and must be reported as
one.

---

## Decision 3 — Contracts forbid extra fields

```python
class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
```

An undocumented field in a response **fails the test**. That sounds aggressive
until you consider what it catches: a field appearing in an API response is how
personal data leaks, and how a breaking change ships unnoticed. If a new field is
intended, adding it here is a one-line reviewable diff.

Money is `Decimal`, never `float`. A model that parsed money as a float would
quietly hide the exact defect the database tests exist to catch.

One line of `response.model(ClaimModel)` checks every documented field's presence,
type and name — coverage a hand-written
`assert body["status"] == "DRAFT"` never approaches, because it only looks at the
field the author happened to think about.

---

## Decision 4 — Service objects return responses, not parsed models

```python
claims.transition(claim.id, ClaimAction.APPROVE).expect_status(403)
claims.create(payload).expect_status(201).model(ClaimModel)
```

A service that parsed and raised on error would force every negative test to reach
around it — and in a suite where negative tests outnumber positive ones, that is
most of the suite. **A framework people work around is a framework nobody trusts.**

The one exception is `create_claim`, which asserts, because it is used for
*arrangement*. When a test's setup fails it must fail loudly at the setup line,
not produce a baffling failure three steps later.

---

## Decision 5 — The negative matrix is generated

```python
def illegal_transitions():
    return tuple(
        (action, status)
        for action in ClaimAction for status in ClaimStatus
        if (action, status) not in _LEGAL_PAIRS
    )
```

30 negative cases from the published transition table. The positive tests are
driven from the *same* table, so the two sets cannot drift apart — and adding a
status automatically adds its negative cases. A hand-written list silently fails
to cover new values, which is how negative coverage rots without anyone noticing.

Two details that make these tests trustworthy:

* the illegal-transition tests use the **staff** actor, so a refusal can only be
  about the claim's state, never the caller's role. Role restrictions are proved
  separately; mixing them would make a failure ambiguous.
* each one asserts the claim **did not move**. A refusal that still changes state
  is worse than no refusal, and a status-code-only test misses it entirely.

---

## Decision 6 — Every refusal is paired with a permission

```python
def test_a_customer_cannot_list_users(...):   # 403
def test_an_administrator_can_list_users(...): # 200
```

A suite that only proves refusals also passes against an API that refuses
everything. Every `403`/`404` test in `test_authorization.py` has a positive twin.

Note also the deliberate difference between the two refusal codes:

| Case | Code | Why |
|---|---|---|
| Another customer's claim | **404** | 403 confirms the resource exists, turning identifier guessing into an enumeration oracle |
| A customer calling `/users` | **403** | The endpoint's existence is not a secret; the caller simply lacks the role |

---

## Findings

### 1. The suite was ~35× slower than it needed to be — and the application was innocent

The first full auth run took **48.17 s** for 21 tests. Every call took ~2.1 s,
uniformly — which immediately rules out the application, because a real
performance problem is never that evenly distributed.

Measured directly:

```
http://127.0.0.1:8000/health      123.7ms    10.4ms    21.4ms
http://localhost:8000/health     2034.5ms  2032.7ms  2059.1ms

localhost resolves to:
   AF_INET6 ('::1', 8000, 0, 0)
   AF_INET  ('127.0.0.1', 8000)
```

`localhost` resolves to `::1` first; the application binds IPv4 only; every
request stalled on the IPv6 attempt before falling back.

**Measured result of changing one configuration value: 48.17 s → 1.36 s.**

Worth noting for its own sake: a *test framework* problem that looked exactly like
an *application* problem. The instinct to profile before optimising — and to
suspect the harness before the product when the overhead is uniform — is the
transferable lesson.

### 2. A specification/implementation mismatch, and the specification lost

The Phase 1 matrix specified `DELETE /claims/{id}` → `204`, then `GET` → `404`.
The application returns `200` with `status=WITHDRAWN`. Rather than assume the
application was wrong, I checked what the rest of the API does:

* `WITHDRAWN` is a published value of the status enum;
* the list endpoint returns withdrawn claims and accepts `?status=WITHDRAWN`.

A detail endpoint returning 404 for a resource the list endpoint happily returns
is incoherent, and it would hide a claim from the customer who withdrew it.
**The specification was wrong.** It has been corrected in the matrix with a note,
and the test now asserts the coherent behaviour plus the audit event.

> **Interview soundbite:** *"A test failed against my own written spec. Before
> changing either side I checked whether the spec was internally consistent — it
> wasn't, because the same status was filterable on the list endpoint. I corrected
> the specification, not the application, and recorded why."*

### 3. Non-ASCII digits are accepted — assessed, documented, not 'fixed'

`Decimal` accepts any Unicode `Nd` character, so full-width `１２３` and
Arabic-Indic `١٢٣` both become `123.00`.

Assessed **low severity**: the value is unambiguous, no rule is bypassed (the
normalised amount is still checked against the coverage limit), and rejecting them
would invent a requirement and refuse legitimate input from some keyboards.

It is now a **characterisation test** that pins the part which would matter: if
the API accepts the input, the stored value must be exactly what the characters
mean — never a truncation, never a different number.

Not every finding is a bug. Knowing which is which, and writing down the
reasoning, is the actual skill.

### 4. A test case that was impossible to run

`Authorization: "Bearer "` (trailing space) could not be tested: httpx refuses to
send it, because trailing whitespace in a header value is illegal per RFC 9110. It
was removed with a comment explaining why — a deleted test with a reason is
honest; a quietly deleted test is not.

### 5. Two bugs in my own test code

* `zip(events, events[1:], strict=True)` — offset slices always differ in length
  by one, so `strict=True` raises every time. Replaced with `itertools.pairwise`,
  which ruff had already suggested.
* **A race under `-n 4`**: every xdist worker prunes the same shared run directory
  at session end, so two interleave — A lists a directory, B removes it, A's
  `rmdir` raises `FileNotFoundError`. It appeared once and did not reproduce in
  the next three runs. Pruning is now concurrency-tolerant, with two regression
  tests. **Cleanup must never be able to fail a run**: reporting a passing suite
  as broken because two processes tidied up at once is far worse than leaving an
  empty folder behind.

---

## Measurements

Recorded from real runs on this machine (Windows 11, Python 3.11.4). These are
observations, not claims — Phase 15 repeats them properly with medians.

| Run | Result |
|---|---|
| Full suite, serial | 229 passed in **11.42 s** |
| Full suite, `-n 4` | 229 passed in **6.89 s / 6.84 s / 7.18 s** (three consecutive runs) |
| Auth suite before the `localhost` fix | 21 passed in **48.17 s** |
| Auth suite after | 21 passed in **1.36 s** |

Test counts: **229 total — 72 framework, 157 API.**

Parallel safety is not asserted, it is demonstrated: the API suite creates every
record it asserts on, keys it with a `uuid4` fragment, and never asserts on a
global count. Three consecutive `-n 4` runs passed with no flakes.

---

## How to run it

```powershell
pytest -m api -q                       # the whole API layer
pytest -m "api and smoke" -q           # the PR gate subset
pytest -m "api and boundary" -q        # every boundary case
pytest -m "api and negative" -q        # every negative case
pytest -m "api and authz" -q           # role and ownership
pytest -q -n 4                         # everything, in parallel
pytest tests/api/test_state_machine.py -q --durations=5
```

---

## Interview questions this phase earns you

**Q: How do you know your negative tests are actually testing what they claim?**
Because one of mine wasn't. A shared HTTP client's session cookie authenticated a
request that was supposed to be anonymous, so "unauthenticated requests are
rejected" passed while testing an authenticated request. The control is one client
per identity with cookie persistence disabled, written up as ADR 0007.

**Q: How do you validate an API response properly?**
Against a typed contract, not field by field. One `model(ClaimModel)` call checks
every documented field's presence, type and name, and because the model forbids
extra fields it also fails when an undocumented field appears — which is how data
leaks and breaking changes usually ship.

**Q: Why should service objects return raw responses instead of parsed models?**
Because negative tests outnumber positive ones. A service that raises on error
forces every negative test to work around the framework, and a framework people
work around is one nobody trusts. Asserting variants exist only for arrangement.

**Q: How do you test a state machine thoroughly without writing dozens of tests?**
Generate the negative matrix from the published transition table — 30 cases from
one comprehension — and drive the positive tests from the same table so they
cannot drift apart. Use a privileged actor for the illegal-transition tests so a
refusal can only be about state, and always assert the resource did not move.

**Q: A test fails and you suspect the spec, not the code. What do you do?**
Check whether the spec is internally consistent first. Mine said a withdrawn claim
should 404 on GET, but the same status was filterable on the list endpoint — so
the spec contradicted itself, and I corrected the spec rather than the product,
with the reasoning recorded in the test's docstring.

**Q: Your suite is slow. Where do you start?**
Measure before changing anything. Mine took 48 seconds for 21 tests, but the cost
was *uniform* across every request — which rules out the application, because real
performance problems are lumpy. It was IPv6 fallback on `localhost`; one
configuration change took it to 1.36 seconds.

**Q: How do you make an API suite safe to run in parallel?**
Every test creates the data it asserts on, keys it with a uuid fragment, and never
asserts on a global count. Searches use the test's own marker rather than a word
another worker might also produce. That is why the suite runs clean at `-n 4`.

---

## What Phase 6 builds on

* `AuthApi.token_for` → the browser gets a session by injecting the token, instead
  of driving a login form it is not testing
* `ClaimsApi.drive_to` → UI tests arrange state through the API in milliseconds
  rather than by clicking through four screens
* `ClaimFactory` → the same valid-by-default payloads, reused by form tests
* `ApiClient` recording → attached alongside traces when a UI test fails
