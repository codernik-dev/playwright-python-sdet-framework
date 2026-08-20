# ADR 0006 - Database validation is opt-in and skips loudly

**Status:** Accepted · **Date:** 2026-08-19 · **Phase:** 2

## Context

The first version of the configuration defaulted `DB_ENABLED` to `true`. That made a fresh clone
**fail to load at all** - settings validation rejected the empty password before a single test ran.
A framework whose default configuration is invalid is a broken framework.

There is also a real-world constraint: in many organisations an SDET has database access in one
environment and none in another. A suite that hard-requires a database cannot run at all in the
second case, which is worse than running with reduced coverage.

## Decision

`DB_ENABLED` defaults to `false`.

* A fresh clone loads and runs the framework unit tests with zero configuration.
* `.env.example` and every CI workflow set it to `true` explicitly.
* When it is off, `db`-marked tests **skip with an explicit reason**, they do not error.

## The risk this creates, and the mitigation

The obvious danger: a CI run could pass while database validation silently never happened, and
nobody would notice. Mitigations:

1. The environment block attached to every report states `database: disabled` - the first thing a
   reader sees.
2. The session header prints a prominent warning when database validation is off (Phase 4).
3. CI workflows set `DB_ENABLED=true` explicitly, so a disabled database in CI is a visible diff in
   the workflow file, not an invisible default.

A skip that is impossible to miss is safe. A skip that looks like a pass is not - and that
distinction is the whole decision.
