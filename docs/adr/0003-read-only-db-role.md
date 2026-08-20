# ADR 0003 - Database validation runs as a read-only PostgreSQL role

**Status:** Accepted · **Date:** 2026-08-19 · **Phase:** 2

## Context

The framework asserts on database state: that a claim was persisted with the right owner and amount,
that the audit trail recorded the transition, that exactly one payout row exists. To do this it needs
database credentials - and credentials in a test framework are a liability.

The dangerous version of database testing is a suite that also *writes* to the database: seeding a
row directly, patching a status to reach a state quickly, deleting rows to clean up. Every one of
those shortcuts creates state the application never produced, and tests then pass against data that
could not exist in production.

## Decision

The framework connects with a dedicated role, `claimdesk_qa_ro`, holding `SELECT` and nothing else.
The application connects with a separate role, `claimdesk_app`, which owns the schema.

A test therefore *cannot* mutate state via SQL even if someone tries. Every write goes through the
application, exactly as in production.

## Consequences

* Reaching a specific state (`PAID`, say) requires driving the real workflow through the API. Slower
  than an `UPDATE`, and correct - the transitions produce the audit rows we then assert on.
* Cleanup cannot be done with `DELETE`. Tests instead use uniquely-keyed disposable data, and CI
  destroys the whole database between runs.
* An accidental `INSERT` in a query object fails with a permission error at development time, not
  silently corrupting a shared environment.
* Two roles must be created during environment setup. `scripts/setup_local_db.ps1` does this.
