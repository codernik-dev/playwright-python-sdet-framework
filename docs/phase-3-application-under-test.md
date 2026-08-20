# Phase 3 - The application under test and its database

> Teaching document. The application is a **fixture**; the framework is the deliverable. This phase
> is therefore judged by one question: *does it give the automation something genuinely worth
> testing?*

---

## What was built

| Area | Files | What it provides the test suite |
|---|---|---|
| Domain rules | `app/claimdesk/domain.py` | A status machine, an approval limit, and ownership rules - the specification the framework tests from the outside |
| Persistence | `app/claimdesk/models.py` | `NUMERIC(12,2)` money, a unique payout per claim, an append-only audit trail |
| Services | `app/claimdesk/services.py` | Shared logic so the API and the browser cannot drift apart |
| REST API | `app/claimdesk/api/` | 16 endpoints under `/api/v1`, plus liveness and readiness probes |
| HTML interface | `app/claimdesk/web/` | Login, dashboard, claims table with async filtering, claim form, detail page with actions, admin users |
| Seed data | `app/claimdesk/seed.py` | 4 users, 3 policies, 24 claims across every status, with realistic audit trails |
| Environment | `scripts/local_db.ps1` | A disposable project-local PostgreSQL cluster |
| App tests | `app/tests/test_domain.py` | 58 unit tests proving the application is real, not a stub |

---

## Decision 1 - A disposable, project-local database

### The problem

The framework needs PostgreSQL. Three ways to get one:

| Option | Problem |
|---|---|
| Use the PostgreSQL service already on the machine | Needs the superuser password; risks colliding with existing databases; state carries over between runs |
| Docker | Not installed on this machine yet, and disk space is tight |
| A project-owned cluster | - |

### The decision

`scripts/local_db.ps1` builds a cluster in `.pgdata/` on port **55432** using the PostgreSQL binaries
already installed, and manages it with `start` / `stop` / `status` / `reset` / `psql`.

* No administrator rights, no superuser password from the machine's existing server.
* Cannot collide with anything on 5432.
* `reset` destroys and rebuilds it in seconds - which is what makes a run reproducible.
* It mirrors what Docker compose will do in Phase 10, so both paths behave the same way.

### The bug found while building it

`pg_ctl start` **never returned**, even though the server log said
`database system is ready to accept connections`. The command sat until it was killed.

Cause: on Windows the server process inherits the parent's stdout handle, so a piped
`& pg_ctl ... start | Out-Null` keeps the pipe open forever. The server is fine; the *launcher* hangs.

Fix: `Start-Process ... -RedirectStandardOutput` detaches the handles.

> This is worth remembering as a general shape: **"the thing hung" is often the wrapper, not the
> thing.** The log said the server was ready - reading it first would have saved ten minutes. Read
> the log before theorising.

### The two roles

```sql
CREATE ROLE claimdesk_app    LOGIN PASSWORD '...';   -- owns the schema, writes
CREATE ROLE claimdesk_qa_ro  LOGIN PASSWORD '...';   -- SELECT and nothing else
GRANT USAGE ON SCHEMA public TO claimdesk_qa_ro;
ALTER DEFAULT PRIVILEGES FOR ROLE claimdesk_app IN SCHEMA public
    GRANT SELECT ON TABLES TO claimdesk_qa_ro;
```

`ALTER DEFAULT PRIVILEGES` is the part people miss: at setup time the application has not created its
tables yet, so `GRANT SELECT ON ALL TABLES` grants nothing. Default privileges apply to tables the
application creates *later*.

**Verified:** an `INSERT` as `claimdesk_qa_ro` fails with `InsufficientPrivilege`. The framework
physically cannot mutate state through SQL. ([ADR 0003](adr/0003-read-only-db-role.md))

---

## Decision 2 - Business rules that are worth testing

A to-do application gives you `create` and `delete`. This one gives the framework real material:

| Rule | Test material it creates |
|---|---|
| `0 < amount <= policy.coverage_limit` | Boundary values: `0`, `0.01`, limit, limit + `0.01`, three decimal places |
| Adjuster limit `5000.00`, inclusive | Role **and** boundary in one rule: `4999.99`, `5000.00`, `5000.01` |
| `DRAFT → SUBMITTED → UNDER_REVIEW → APPROVED/REJECTED → PAID` | Every off-diagram edge is a `409`, generated as a parametrised matrix |
| One `claim_events` row per transition | Audit assertions only the database can make |
| One `payouts` row per claim, **unique constraint** | The double-payout defect, prevented at the storage layer |
| Another customer's claim → `404`, not `403` | Non-enumeration, asserted explicitly |

### The ordering decision inside `resolve_transition`

Status is checked **before** authority:

```python
if current_status is not rule.source:
    raise InvalidTransitionError  # 409
if actor_role not in rule.roles:
    raise InsufficientAuthorityError  # 403
```

A customer trying to approve an already-paid claim gets `409`, not `403`. The claim's state is a fact
about the resource; the caller's authority is a fact about the caller, and replying "you could have
done that with a different role" tells an unauthorised caller more than they need to know.

The application's own test `test_status_is_checked_before_authority` pins this, and the framework will
assert it from the outside too. It is the kind of detail that separates "the endpoint works" from "the
endpoint behaves correctly".

### The invalid-transition matrix is generated, not written

```python
def _illegal_pairs():
    return [
        (action, status)
        for action in ClaimAction
        for status in ClaimStatus
        if TRANSITIONS[action].source is not status
    ]
```

35 negative cases from four lines. More importantly, **adding a new status automatically adds its
negative cases** - a hand-written list would silently fail to cover the new value, which is how
coverage quietly rots.

---

## Decision 3 - Two transports, one token

The same JWT is accepted from an `Authorization: Bearer` header *and* from a `session` cookie.

This is not decoration. It is what lets Phase 6 authenticate **once through the API** and inject the
result into the browser via Playwright's `storage_state`, so UI tests do not repeatedly pay for a
login form they are not testing. It typically removes several seconds from every UI test.

It also produced the most valuable bug of the phase.

---

## The false pass - the most important thing in this phase

The verification script contained this check:

```python
r = client.get(f"{API}/claims")  # no Authorization header
check("no auth header -> 401", r.status_code == 401)
```

It reported **200**.

For a moment this looked like an authentication bypass in the application. It was not:

```
$ curl -o /dev/null -w "%{http_code}" http://127.0.0.1:8000/api/v1/claims
401
```

The application was correct. The *test* was wrong. `httpx.Client` persists cookies, the earlier login
had set a `session` cookie, and the "unauthenticated" request was quietly authenticated by it.

```
cookies before login : {}
cookies after  login : ['session']
no-auth-header call  : 200   <- cookie authenticated it
after clearing jar   : 401   <- correct
```

**Why this matters more than a normal bug:** the check did not fail. It passed, for the wrong reason,
and it would have kept passing even if authentication had been removed from the endpoint entirely. A
test that cannot fail is worse than no test, because it produces confidence instead of information.

The rule is now recorded in [ADR 0007](adr/0007-no-shared-cookie-jar.md): the API client disables
cookie persistence, each identity gets its own client, and unauthenticated tests use a client that has
never logged in.

> **Interview soundbite:** *"One of my negative tests passed for the wrong reason - a shared HTTP
> client's cookie jar was authenticating a request that was supposed to be anonymous. I proved the
> application was right with curl, fixed the framework, and wrote the isolation rule into an ADR.
> Now every authorisation test uses a per-identity client."*

---

## Bugs found by the quality gate

| # | Finding | Why it mattered |
|---|---|---|
| 1 | `.env.example` shipped `FAKER_SEED=` (empty), which fails `int` parsing | The documented first step - copy the template - produced a framework that could not start. Fixed with a `mode="before"` validator, and a test now loads `.env.example` itself so the template can never break again |
| 2 | Framework unit tests were not hermetic against the `.env` **file** | Clearing environment variables was only half the isolation. Tests now `chdir` to a temp directory, so a developer's real `.env` cannot change a unit-test result |
| 3 | Seed emails used `@claimdesk.test` | `email-validator` rejects the RFC 2606 `.test` TLD as a special-use name, so every login returned `422`. Moved to `example.com` |
| 4 | Two `assert` statements used for control flow | `python -O` strips `assert`, turning the guard into a silent `None` dereference. Replaced with explicit raises |
| 5 | `next` used as a parameter name | Shadowed the builtin. Renamed to `next_url` with `alias="next"`, so the URL contract is unchanged |
| 6 | `get_policy` mixed a `None` check into a boolean flag | mypy caught that it could return `None` where `Policy` was declared. Rewriting it as two explicit guards fixed the type **and** made the non-enumeration rule readable |

Item 6 is the argument for static typing in one line: the type checker found a latent `None` return
in code that looked perfectly reasonable.

---

## How to run it

```powershell
# 1. Start the disposable database (creates it on first run)
.\scripts\local_db.ps1 start

# 2. Start the application
.\.venv\Scripts\python.exe -m uvicorn claimdesk.main:app --app-dir app --port 8000

# 3. Check it is alive and ready
curl http://localhost:8000/health          # {"status":"ok","version":"1.0.0"}
curl http://localhost:8000/health/ready    # {"status":"ready","database":"reachable"}

# 4. Open http://localhost:8000/login and sign in
```

Seeded accounts - all with password `Passw0rd!seed`:

| Email | Role |
|---|---|
| `admin@example.com` | ADMIN |
| `adjuster@example.com` | ADJUSTER |
| `customer@example.com` | CUSTOMER (holds POL-1001 and POL-1002, owns the 24 seeded claims) |
| `other.customer@example.com` | CUSTOMER (holds POL-2001 - used for cross-tenant tests) |

Useful commands:

```powershell
.\scripts\local_db.ps1 status     # is it running?
.\scripts\local_db.ps1 reset      # destroy all data and rebuild
.\scripts\local_db.ps1 psql       # interactive SQL as the application role
.\.venv\Scripts\python.exe -m pytest app/tests -q   # the application's own tests
```

Interactive API documentation is at <http://localhost:8000/docs>, generated from the code - which is
also how you confirm the endpoint list without reading the routers.

---

## Interview questions this phase earns you

**Q: You wrote the application you are testing. Why should I trust the tests?**
Because the framework cannot see the application. It reaches it only over HTTP and read-only SQL, and
a ruff rule blocks the import - I proved the rule fires by adding a violating file and watching the
linter reject it. The database role the tests use holds `SELECT` and nothing else, so tests cannot
manufacture state that the application would never produce.

**Q: Why a separate read-only database role?**
So the tests physically cannot take shortcuts. The dangerous version of database testing writes rows
to reach a state quickly, and then asserts against data the application never created. With
`SELECT`-only, reaching `PAID` requires driving the real workflow - which also produces the audit rows
the test then verifies.

**Q: Why is `ALTER DEFAULT PRIVILEGES` needed?**
At setup time the application has not created its tables, so `GRANT SELECT ON ALL TABLES` grants
nothing. Default privileges apply to tables created later by the owning role.

**Q: How do you test a state machine without writing dozens of tests by hand?**
Generate the negative matrix from the transition table: every `(action, status)` pair that is not a
legal edge must return `409`. Four lines produce 35 cases, and adding a new status automatically adds
its negative cases - a hand-written list would silently miss them.

**Q: What is the hardest kind of test bug to find?**
The one that passes. In this phase a negative authentication check returned 200 because a shared HTTP
client had a session cookie from an earlier login. It did not fail - it passed for the wrong reason,
and would have kept passing with authentication removed entirely. The fix was a per-identity client
with cookie persistence disabled, recorded as ADR 0007.

**Q: Why does the UI still show the Approve button on an over-limit claim?**
Because hiding it would move authorisation into the template and make the rule untestable through the
interface. The button is offered based on status and role; the approval limit is enforced on submit.
That is what UI-CLM-011 asserts - the user sees an error and the status does not change.

**Q: Why does a customer get 404 rather than 403 for someone else's claim?**
`403` confirms the resource exists, which lets an attacker enumerate valid identifiers. `404` reveals
nothing. The same rule applies to policies.

---

## What Phase 4 builds on

* `/health/ready` → the readiness poll that replaces `sleep` before a run starts
* `X-Request-Id` echoing → correlation between test logs and application logs
* Seeded accounts and the `CLM-SEED` corpus → fixtures for list, filter, sort and pagination tests
* ADR 0007 → the shape of the `ApiClient` in Phase 5
