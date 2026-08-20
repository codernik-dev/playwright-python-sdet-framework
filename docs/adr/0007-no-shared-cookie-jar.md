# ADR 0007 - The API client must never share a cookie jar between identities

**Status:** Accepted · **Date:** 2026-08-19 · **Phase:** 3 (applies to the Phase 5 API client)

## Context

ClaimDesk accepts the same JWT from two transports: an `Authorization: Bearer` header for API
clients, and a `session` cookie for the HTML interface. Logging in through the API therefore also
returns a `Set-Cookie` header.

`httpx.Client` persists cookies across requests by default. During Phase 3 verification this produced
a **false pass**:

```python
with httpx.Client() as client:
    login(client, "customer@example.com")  # server sets a session cookie
    r = client.get(f"{API}/claims")  # no Authorization header...
    assert r.status_code == 401  # ...but it returned 200
```

The check "an unauthenticated request is rejected" was silently exercising an *authenticated*
request. A direct `curl` confirmed the application was correct - it returns `401`, and `303` for the
anonymous HTML route. The framework was wrong, not the application.

This is the most dangerous category of test defect. It does not fail; it passes for the wrong reason,
and it would keep passing if authentication were removed from the endpoint entirely.

## Decision

1. The framework's `ApiClient` disables cookie persistence. Bearer-token authentication is explicit:
   every authenticated request carries a header the test can see.
2. Each authenticated identity gets its **own** client instance. No client is ever shared between two
   users, so a token or cookie cannot leak from one role's requests into another's.
3. Unauthenticated tests use a dedicated anonymous client that has never logged in.
4. Browser session state is carried deliberately through Playwright's `storage_state`, which is
   visible in the fixture, rather than accumulating invisibly in a client's cookie jar.

## Consequences

* Slightly more construction: one client per identity instead of one shared client.
* Authorisation tests become trustworthy - a `401`/`403` assertion cannot pass because of a stale
  cookie from a previous test.
* This is a strong interview answer to *"how do you know your negative tests are actually testing
  what they claim?"* - the honest answer is that one of mine was not, and here is the control that
  now prevents it.
