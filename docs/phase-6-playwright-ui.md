# Phase 6 - The Playwright UI layer

> Teaching document. 32 browser tests, no `sleep` anywhere, failure artefacts that
> actually let you debug a CI failure without reproducing it.

---

## What was built

| File | Responsibility |
|---|---|
| `src/claimdesk_qa/ui/base_page.py` | Navigation, readiness, and the two rules every page object follows |
| `src/claimdesk_qa/ui/session.py` | A browser session obtained from an API login - no login form |
| `src/claimdesk_qa/ui/components/navigation.py` | The header, shared by six pages |
| `src/claimdesk_qa/ui/pages/` | Login, dashboard, claims list, claim form, claim detail, admin users |
| `tests/ui/conftest.py` | Per-role browser contexts, tracing, failure artefacts |
| `tests/ui/` | 32 tests: sign-in, table, form, workflow, authorisation |

---

## Decision 1 - Authenticate through the API, not the login form

Almost every UI test needs to be signed in. Almost none are *about* signing in.

```python
token = AuthApi(client).token_for(email, password)  # one API call
write_storage_state(token, base_url, path)  # a cookie in a JSON file
browser.new_context(storage_state=str(path))  # already signed in
```

ClaimDesk accepts the same JWT from an `Authorization` header **and** from a
`session` cookie, which is what makes this possible. The framework logs in four
times per session - once per role - instead of once per test.

Two benefits, and the second matters more:

1. **Speed.** No page load, form fill, POST, redirect and bcrypt verification per
   test.
2. **Blast radius.** When login breaks, the *login tests* fail. Not fifty
   unrelated tests with the real cause buried among them.

The trade: nothing else exercises the login form, so `test_login.py` does it
explicitly and is the only file that does. That is the correct split - sign-in is
covered once, deliberately, by tests that are about sign-in.

This is also why the API layer was built first. It is not only a test target; it
is the fastest way to arrange state for every other layer.

> **The bug this design invites:** the cookie's domain must match how the browser
> addresses the app. A cookie scoped to `localhost` is simply never sent to
> `127.0.0.1` - browsers treat them as different hosts - and the symptom is a
> silent redirect to the login page that looks like a broken session. The domain
> is derived from `base_url` rather than hard-coded.

---

## Decision 2 - Locators are properties, never stored elements

```python
@property
def submit_button(self) -> Locator:  # correct
    return self._page.get_by_test_id("submit-login")


self.submit_button = page.query_selector("#submit")  # wrong
```

A `Locator` is a *description* of how to find an element, resolved every time it is
used - which is when Playwright's auto-waiting applies. A stored element handle is
a snapshot: the moment the page re-renders it is stale, and the test fails with a
detached-node error that looks like a product bug.

This is enforced by the base class's shape rather than by review comments.

---

## Decision 3 - Wait for state, never for time

There is no `sleep` in this layer. The claims table refreshes asynchronously, and
the page object waits on the signal the application publishes:

```python
def wait_for_refresh(self) -> Self:
    expect(self.container).to_have_attribute("aria-busy", "false")
    return self
```

`aria-busy` rather than a private CSS class, deliberately twice over: it is a real
state rather than a guessed duration, **and** it is the same signal assistive
technology uses - so it cannot be renamed as an internal detail without breaking
accessibility too. Coupling the test to the accessibility contract makes it a
better test *and* a better citizen.

### The negative-assertion trap

```python
expect(self.row_for(reference)).to_have_count(0)  # correct
expect(self.row_for(reference)).not_to_be_visible()  # passes for the wrong reason
```

A negated visibility assertion is satisfied by a page that has not finished
rendering - so it passes instantly, before the row it is meant to reject has even
had a chance to appear. `to_have_count(0)` retries until the timeout, so a row that
appears late still fails the test. Every "must not be present" assertion in this
layer uses the counting form.

---

## Decision 4 - One browser, many contexts

```python
context = browser.new_context(storage_state=..., viewport=...)
```

A context is an isolated browser session - its own cookies, storage and cache -
inside an already-running browser process. Launching a *browser* per test costs
hundreds of milliseconds each; a context costs almost nothing. That difference is
what makes a parallel browser suite affordable at all.

It also mirrors the API layer's rule: **one session per identity, never shared.**
`customer_page`, `adjuster_page`, `admin_page` and `other_customer_page` cannot
leak state into one another, which is what makes the authorisation tests
trustworthy.

---

## Decision 5 - Capture everything, keep only failures

```python
context.tracing.start(screenshots=True, snapshots=True, sources=True)
...
if failed:
    context.tracing.stop(path=directory / "trace.zip")
    page.screenshot(path=directory / "screenshot-0.png", full_page=True)
    (directory / "page-0.html").write_text(page.content())
else:
    context.tracing.stop()  # no path = discarded
```

You cannot know in advance which test will fail, so tracing runs for all of them
and the output is thrown away for the ones that passed.

**Verified** by deliberately failing a test:

```
artifacts/<run>/tests_ui_..._12a9d708/
  trace.zip          322,840 bytes - 24 entries, incl. trace.network + 6 filmstrip frames
  screenshot-0.png    26,708 bytes - valid PNG
  page-0.html          6,370 bytes
  test.log               866 bytes - with the correlation id
```

And the failure log tells you what to do next:

```
Saved failure artefacts to ...\tests_ui_..._12a9d708
  - inspect with: playwright show-trace ...\trace.zip
```

That command opens a time-travel viewer: DOM snapshot at every step, the network
log, console output, and the source line of each action. **This is the answer to
"how would you debug a CI failure you cannot reproduce locally?"** - you do not
reproduce it, you replay it.

Note the directory name ends in `_12a9d708`: the node id exceeded the slug limit
and was truncated with a hash, exactly as the Phase 4 tests specified.

---

## Decision 6 - The button that is offered and then refused

`UI-CLM-011` is the most interesting test in the suite. An adjuster looking at a
claim **above** their approval limit still sees the Approve button - and pressing
it is refused.

That is deliberate. Buttons are rendered from the claim's *status* and the caller's
*role*; the approval limit is enforced when the action is taken. Hiding the button
instead would move authorisation into a template, where it is unenforceable,
untestable through the interface, and bypassed by anyone who can issue an HTTP
request.

The test asserts all three things that matter:

```python
detail.expect_action_available(ClaimAction.APPROVE.value)  # offered
detail.perform(ClaimAction.APPROVE.value)
expect(detail.error_toast).to_contain_text("approval limit")  # refused, legibly
detail.expect_status(ClaimStatus.UNDER_REVIEW.value)  # and did not move
```

Only the third catches a refusal that changed state anyway.

The same principle drives `UI-AUTHZ-002`: the admin link is hidden from customers,
and one test asserts that - but a *separate* test navigates directly to
`/admin/users` and requires the server to refuse it. **Hiding a link is
presentation, not authorisation.**

---

## The finding: my own suite broke its own parallel-safety rule

`test_the_table_paginates` failed **roughly half the time** under `-n 4`, and
passed every time serially. Reproduced deliberately rather than re-run until green:

```
attempt 1: 261 passed
attempt 2: FAILED tests/ui/test_claims_list.py::test_the_table_paginates[chromium]
attempt 3: 261 passed
attempt 4: FAILED ... test_the_table_paginates[chromium]
```

The cause: the table sorts newest-first, and other workers create claims *between*
the page-one and page-two requests. Every row shifts down by one, and a claim seen
at the bottom of page one reappears at the top of page two.

**The assertion was correct. The premise was wrong.** You cannot paginate a data
set that is being written to and expect stable page boundaries.

The fix is to scope the test to the seeded corpus - 24 claims that no test mutates
and no worker adds to - so the pages are deterministic regardless of what else is
running. Five consecutive `-n 4` runs then passed.

Two things make this worth writing down:

* I had already applied this discipline in the *API* pagination test, and still
  wrote the UI one without it. A rule you apply where you remember is not a rule.
* Sorting by a stable key is necessary but **not sufficient**. References are
  random, so a concurrently created claim can insert anywhere in a
  reference-sorted list and shift the boundary too. The API test was latently
  flaky for the same reason and has been scoped the same way.

> **Interview soundbite:** *"A browser test failed about half the time in parallel
> and never serially. I reproduced it deliberately rather than re-running until
> green: other workers were inserting rows between my two page requests, so a claim
> moved from page one to page two. The assertion was right and the premise was
> wrong - you can't paginate a data set that's being written to. I scoped it to the
> immutable seeded corpus and confirmed five clean runs. Retrying it would have
> hidden a real lesson."*

---

## Measurements

| Run | Result |
|---|---|
| Full suite, serial | **261 passed in 21.04 s** |
| Full suite, `-n 4` | **261 passed** in 12.81 / 13.46 / 12.86 / 13.10 / 13.20 s - five consecutive runs |
| Browser tests only | 32 |

Counts: **261 total - 72 framework, 157 API, 32 UI.** 87 carry the `smoke` marker.

---

## How to run it

```powershell
pytest -m ui -q                          # the browser layer
pytest -m ui --headed                    # watch it drive
pytest -m ui --slowmo 500 --headed       # slowly enough to follow
pytest -m "ui and authz" -q              # role and ownership through the interface
pytest -q -n 4                           # everything, in parallel

playwright show-trace artifacts\<run>\<test>\trace.zip   # replay a failure
```

---

## Interview questions this phase earns you

**Q: How do you stop every UI test failing when login breaks?**
Authenticate once through the API and inject the session as a Playwright
`storage_state`. Only the login tests drive the login form, so a sign-in defect
produces a handful of pointed failures instead of fifty vague ones - and every
other test skips the cost of a form post and a bcrypt verification.

**Q: How do you handle waiting without `sleep`?**
Wait for state, never for duration. Playwright's auto-waiting covers actionability;
for the asynchronous table I wait on `aria-busy`, which is the signal the
application already publishes for assistive technology. A sleep is either redundant
or hiding a race that will surface on a slower agent.

**Q: What's wrong with `expect(x).not_to_be_visible()`?**
It is satisfied by a page that has not rendered yet, so it passes before the thing
it rejects could have appeared. `to_have_count(0)` retries until the timeout. Every
"must not be present" assertion in my suite uses the counting form.

**Q: How would you debug a CI failure you cannot reproduce locally?**
I would not reproduce it - I would replay it. Every failing browser test writes a
Playwright trace, a full-page screenshot and the rendered HTML into that test's
artefact directory, and the log line prints the `playwright show-trace` command.
The trace carries a DOM snapshot per step, the network log and the source line of
each action.

**Q: Why not hide the button the user is not allowed to press?**
Because hiding a control is presentation, not authorisation. Rendering decisions
based on the limit would put an access rule in a template - unenforceable and
bypassed by anyone who can send an HTTP request. The button is offered, the server
refuses, and the test asserts the refusal *and* that the claim did not move.

**Q: Tell me about a flaky test you fixed.**
A pagination test failed about half the time at `-n 4` and never serially. Other
workers were inserting rows between the two page requests, shifting a claim from
page one to page two. The assertion was correct; the premise was wrong. I scoped it
to the immutable seeded corpus and verified five consecutive clean runs. I had
already applied that discipline in the API layer and still wrote the UI test
without it - a rule you apply only where you remember is not a rule.

---

## What Phase 7 builds on

* Claims driven to real states through the UI and API → the database layer asserts
  what was actually persisted
* The artefact directory → where SQL query results are attached on failure
* `ClaimsApi.drive_to` → arranging the exact state a DB assertion needs
