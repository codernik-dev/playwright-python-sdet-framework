# Phase 7 - Database validation and cross-layer journeys

> Teaching document. 28 database tests, 4 end-to-end journeys, and the rule that
> two flaky tests in two different layers finally forced me to write down.

---

## What was built

| File | Responsibility |
|---|---|
| `src/claimdesk_qa/db/connection.py` | Read-only connection, parameterised queries, recorded SQL |
| `src/claimdesk_qa/db/rows.py` | Typed row dataclasses; money as `Decimal` |
| `src/claimdesk_qa/db/queries.py` | Query objects - the DB layer's page objects |
| `tests/_fixtures/` | Shared fixtures, extracted from three duplicated conftests |
| `tests/db/` | 28 tests: persistence, audit trail, payouts, integrity, schema |
| `tests/e2e/` | 4 journeys crossing browser → API → database |

---

## Decision 1 - Why validate the database at all

The API returned `200`. The page showed `PAID`. What else is there to check?

Quite a lot, and none of it visible from above:

| Question | Only the database can answer it |
|---|---|
| Was the value stored **exactly**? | A float column returns the right answer until the day it cannot represent one |
| Did the row **survive** the delete? | A soft delete and a hard delete look identical through the API |
| Was the claim paid **once**? | A duplicate payout returns a perfectly ordinary response |
| Is there an **audit trail**? | The API can show the events it chooses to show |
| Did a rejected write leave a **partial row**? | The API returns 422 either way |

That last one is the sharpest example. An application that inserts first and
validates second returns the correct error to every caller while quietly filling
the table with invalid rows. No API test can see it. One SQL query can.

---

## Decision 2 - Two independent controls, and the safety net is tested

The role holds `SELECT` and nothing else (ADR 0003). The connection *also* sets
`read_only`:

```python
connection.read_only = True
```

Belt and braces, because the dangerous version of database testing is a suite
that writes rows to reach a state faster - and then asserts against data the
application could never have produced.

And the control itself is tested, not assumed:

```python
@pytest.mark.parametrize("statement", ["UPDATE ...", "DELETE ...", "INSERT ...", "TRUNCATE ..."])
def test_the_qa_role_cannot_modify_anything(database, statement):
    with pytest.raises(DatabaseError, match=r"not permitted|read-only|Query failed"):
        database.scalar(statement)
```

An untested safety control is a belief, and beliefs about permissions are wrong
surprisingly often - a well-meaning `GRANT ALL` during an incident is all it
takes. Note also that the refusal raises `DatabaseError`, not `AssertionError`:
being refused is the *framework working*, not the product misbehaving.

---

## Decision 3 - Parameterised, always, and not only because of injection

```python
"SELECT count(*) FROM claims WHERE description LIKE %s", (f"%{marker}%",)
```

Injection is the famous reason, and it is real even in test code that runs against
a shared environment. But the quieter reason matters more here: **interpolation
mangles types.** A `Decimal` formatted into a SQL string becomes a float literal,
and the test that was supposed to prove money is exact starts comparing rounded
values - passing, while proving nothing.

The wildcards go in the *parameter*, never the statement.

---

## Decision 4 - Asserting the schema, not just the data

```python
def test_money_is_stored_as_exact_numeric_not_floating_point(integrity_db):
    for column in integrity_db.money_column_types():
        assert column.data_type == "numeric"
        assert column.numeric_scale == MONEY_DECIMAL_PLACES
```

This catches the defect *before* it produces a wrong value. A column declared
`double precision` behaves correctly for most amounts and then, one day, cannot
represent one - by which point the wrong number is already in the ledger. No
amount of testing rows will find it; one query against `information_schema` will.

Scale is asserted too. `NUMERIC` without a scale would happily store three decimal
places, quietly turning a validation rule into a suggestion.

The same reasoning drives asserting that the `payouts` unique constraint **exists**.
Application logic can be bypassed by a second code path, a background job, or a
manual fix applied at 2 a.m. during an incident. A unique constraint cannot.

---

## The finding: `information_schema` is privilege-filtered

`test_the_claims_table_constrains_status_and_amount` failed with an empty set.
Measured directly rather than guessed at:

```
read-only role, information_schema.table_constraints  ->  0
read-only role, pg_catalog.pg_constraint              -> 16
owning role,    information_schema.table_constraints  -> 16
```

PostgreSQL documents `information_schema.table_constraints` as showing constraints
on tables the current user owns **or has some privilege other than `SELECT` on**.
A `SELECT`-only role therefore sees none. `pg_catalog` is not filtered this way.

The trap is the shape of it: **the test would have passed against a superuser, or
against the application's own role.** It only failed once least privilege was
applied properly. Doing the secure thing exposed a bug in my query - which is an
argument for doing the secure thing early, while there is still time for it to
teach you something.

(`information_schema.columns` *is* visible to a `SELECT`-only role, which is why
the money-type query can still use it.)

---

## The finding that mattered more: the same mistake, twice, in two layers

`test_a_rejected_write_leaves_no_row` failed **two runs in three** under `-n 4`.
Its first version was:

```python
before = claims_db.count_with_status("DRAFT")
... two rejected writes ...
assert claims_db.count_with_status("DRAFT") == before
```

Other workers legitimately create draft claims in between, so the number moves for
reasons that have nothing to do with this test.

This is the **same error as the Phase 6 pagination flake**, made again in a
different layer, a day later, by someone who had already written the lesson down.
So it is now stated as a rule rather than as two fixed instances:

> **A test may assert on an *invariant* globally, because an invariant holds no
> matter who else is writing. It may never assert on an *aggregate* globally,
> because an aggregate is a fact about the whole database - and the whole database
> is shared.**

That distinction is what makes the integrity tests in this phase safe while the
count test was not:

| Assertion | Kind | Safe in parallel? |
|---|---|---|
| `orphaned_event_count() == 0` | invariant | ✅ true regardless of concurrent writes |
| `claims_paid_more_than_once() == []` | invariant | ✅ |
| `paid_claims_without_a_payout() == []` | invariant | ✅ status and payout commit together |
| `count_with_status("DRAFT") == before` | **aggregate** | ❌ every other worker changes it |

The fix scopes the question to this test's own data:

```python
marker = f"rejected-{unique_suffix()}"
... two rejected writes carrying that marker ...
assert claims_db.count_with_description_containing(marker) == 0
```

Five consecutive `-n 4` runs then passed.

> **Interview soundbite:** *"I wrote the same concurrency bug twice, in two
> different layers, after documenting it the first time. That told me the fix
> wasn't the fix - the rule was. Invariants can be asserted globally because they
> hold no matter who else is writing; aggregates can't, because the database is
> shared. Once it was a rule rather than a war story, the integrity tests I'd
> already written turned out to be safe for a reason I could state."*

---

## A credential leak I caught by reading, not by testing

The end-to-end session test originally wrote its storage state - containing a
**live bearer token** - to `artifacts/`, which CI archives and publishes as a
downloadable build artefact.

Nothing failed. Every test was green. It was caught while re-reading the file.

The cookie is now injected straight into the browser context and never touches
disk. Worth recording precisely because no test would ever have told me:
credential handling deserves a deliberate second look rather than a green tick.

---

## Decision 5 - Extracting shared fixtures, at the right moment

By the time the end-to-end suite needed them, `customer_claims` existed in three
separate conftest files. The rule I applied: **three copies is a pattern; a fourth
is a problem.** Writing the fourth was the trigger, not a tidiness impulse.

They moved to `tests/_fixtures/`, registered as plugins from the root conftest:

```python
pytest_plugins = [
    "tests._fixtures.identities",
    "tests._fixtures.database",
    "tests._fixtures.browser",
]
```

Each layer's conftest shrank from ~120 lines to 15 - holding only the thing that
is genuinely layer-specific: the autouse guard requiring a running application,
which the framework's own unit tests must not have.

---

## Decision 6 - What an end-to-end test is *for*

Four journeys, the fewest and most expensive tests in the suite. That ratio is
deliberate: an end-to-end test earns its cost only when it proves something no
single layer can - that the three layers **agree**.

`E2E-003` is the clearest case. An administrator deactivates an account through
the **API**; a **browser** that was already signed in must be refused on its very
next navigation; the **database** must show the account inactive. No single layer
can express that, and it documents this application's real revocation story: a
bearer token cannot be withdrawn without server-side state, so deactivating the
user *is* the revocation path - and it must work immediately, not at token expiry.

---

## Measurements

| Run | Result |
|---|---|
| Full suite, serial | **293 passed in 23.60 s** |
| Full suite, `-n 4` | **293 passed** in 15.14 / 16.86 / 14.83 / 14.88 / 15.04 s - five consecutive runs |

**293 total** - 72 framework · 157 API · 32 UI · 28 DB · 4 E2E. 94 carry `smoke`.

---

## How to run it

```powershell
pytest -m db -q                     # the database layer
pytest -m e2e -q                    # cross-layer journeys
pytest -m integrity -q              # invariants and schema assertions
pytest -m db -q --setup-show        # watch the read-only connection open per test

$env:DB_ENABLED="false"; pytest -m db -rs    # skips loudly, with reasons
```

---

## Interview questions this phase earns you

**Q: Why validate the database when the API already returned the right thing?**
Because the API can only tell you what a response said. It cannot tell you the
value was stored exactly rather than rounded, that a delete was soft rather than
hard, that a claim was paid once rather than twice, or that a rejected write left
no partial row. A handler that inserts before validating returns a correct 422 to
every caller while filling the table with invalid rows.

**Q: How do you stop database tests from cheating?**
The role holds `SELECT` and nothing else, and the connection sets `read_only` as a
second control. Reaching a state means driving the real workflow through the
application - which also produces the audit rows the test then asserts on. And the
control is tested: four write statements, each required to be refused.

**Q: Why parameterised queries in test code?**
Injection is the famous reason and it is real against a shared environment. The
quieter one is that interpolation mangles types - a `Decimal` formatted into a
string becomes a float literal, and a test meant to prove money is exact starts
comparing rounded values while still passing.

**Q: You hit a query returning nothing under a restricted role. What happened?**
`information_schema.table_constraints` is privilege-filtered: it shows constraints
only where you hold a privilege other than `SELECT`. Our QA role saw zero; the
owner saw sixteen. I measured both, switched to `pg_catalog`, and noted that the
test would have passed against a superuser - least privilege is what exposed it.

**Q: How do you make database assertions safe under parallel execution?**
By distinguishing invariants from aggregates. An invariant - no orphans, no claim
paid twice - holds no matter who else is writing, so it can be asserted globally
and covers everything the whole run created. An aggregate like "count of DRAFT
claims" is a fact about a shared database and moves under you. I learned that by
writing the same bug twice in two layers.

**Q: When is an end-to-end test worth its cost?**
When it proves the layers agree, and only then. Deactivating a user through the
API and requiring an already-open browser session to be refused on its next
request is not expressible in any single layer - and it documents the real
revocation path for a stateless token.

---

## What Phase 8 builds on

* `Database.render_queries()` → executed SQL attached to a failing test's report
* `ApiClient.render_exchanges()` → the HTTP conversation, attached alongside
* The artefact directory → already holds traces, screenshots and logs; Phase 8
  adds the Allure report that presents them together
