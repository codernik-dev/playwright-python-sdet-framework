# ADR 0009 - Retries are diagnostics, not a cure

**Status:** Accepted (Phase 9)

## Context

`pytest-rerunfailures` is a dependency of this project, and it is the single
easiest way to destroy the value of a test suite.

`--reruns 3` makes a red build green. Everyone involved is briefly happier and
permanently worse off: the defect is still there, the suite takes up to three
times as long to fail, and the most valuable signal a suite can produce - *this
result is not deterministic* - has been deliberately deleted.

The pressure to do it is real and recurring. A flaky test blocks a release, it is
5pm, and raising a number in a config file is a fifteen-second fix that appears
to work.

## Decision

Retries exist, and are constrained so tightly they cannot be used as a cure.

1. **UI and end-to-end tests only.** A browser genuinely shares a machine with a
   compositor, a renderer and a network stack, so a retry there answers a real
   question: does this reproduce? An **API or database test that fails
   intermittently is not flaky, it is wrong** - a race, a shared-state
   assumption, or a genuine product defect - and retrying it deletes the
   evidence.
2. **CI only.** Locally a flake should be reproduced, not papered over; the
   developer is right there and the trace is on disk.
3. **One retry.** If one cannot decide whether a failure reproduces, two will not
   either.
4. **A test that passes on retry is reported as FLAKY, never as green.** The run
   prints a `FLAKY` block naming every test that needed a retry, plus the seed to
   reproduce it. Allure records the retry alongside the result.
5. **The policy is applied in one place** - `pytest_collection_modifyitems`,
   reading `claimdesk_qa.core.flakiness.reruns_for` - not by decorating
   individual tests. A decorator is a decision made once by whoever was annoyed
   that day; a policy is a decision the whole suite obeys and a reviewer can read
   in one sitting.
6. **The budget is not configurable.** A retry count that can be raised will be
   raised. `MAX_RERUNS = 1` is pinned by a unit test that explains why.

## Consequences

- A genuinely flaky browser test does not block a pipeline, and is still
  reported, so it can be fixed rather than forgotten.
- An intermittent API failure fails the build, loudly, on the first occurrence.
  This is the intended cost: it is the only way that class of defect gets found.
- "The build is green" keeps meaning something, which is the entire point.
- Quarantine (`@pytest.mark.quarantine`) remains the escape hatch for a known
  flake, and it is deliberately more expensive than a retry: the test is excluded
  from the gate, tracked as a bug against the test, and carries a deadline.
  Making the honest route the *visible* one is what stops the dishonest route
  being taken.

## Alternatives considered

| Alternative | Why not |
|---|---|
| `--reruns 2` globally | Hides real defects in the layers where intermittency is always a bug |
| No retries at all | Defensible, and nearly right. Rejected because a real browser flake then blocks unrelated work with no diagnostic value - the retry is what tells you it is *not* reproducible |
| Retry only on specific exception types | More precise in theory; in practice the exception is usually a generic timeout, so it would approximate the layer rule with more code |
| Let each author decorate their own tests | Guarantees drift. The one test that most needs the discipline is the one whose author is most tempted to relax it |
