"""Give the browser a session without driving the login form.

The problem
-----------
Almost every UI test needs to be signed in, and almost none of them are *about*
signing in. Driving the login form in each one means every test pays for a page
load, two field fills, a form post, a redirect and a bcrypt verification - and,
worse, every one of those tests now fails when login breaks. One defect, fifty red
tests, and the actual cause buried among them.

The solution
------------
ClaimDesk accepts the same JWT from an ``Authorization`` header *and* from a
``session`` cookie (see ``docs/phase-3-application-under-test.md``). So the
framework authenticates **once, through the API**, and hands Playwright the
resulting cookie as a ``storage_state``. The browser starts already signed in.

What this trades away, and why it is acceptable
-----------------------------------------------
Nothing then exercises the login form - so the login tests do it explicitly, and
they are the only tests that do. That is the correct split: sign-in is covered
once, deliberately, by tests that are about sign-in, and everything else starts
from the state it actually wants to test.

This is also why the API layer is built first. It is not only a test target; it is
the fastest way to arrange state for every other layer.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

SESSION_COOKIE_NAME = "session"


def storage_state_for_token(token: str, base_url: str) -> dict[str, Any]:
    """Build a Playwright storage state carrying an authenticated session cookie.

    Args:
        token: a JWT obtained from the API.
        base_url: the application's base URL, used to derive the cookie domain.

    The domain must match how the browser will address the application. A cookie
    scoped to ``localhost`` is simply not sent to ``127.0.0.1`` - the browser
    treats them as different hosts - and the symptom is a silent redirect back to
    the login page that looks like a broken session rather than a wrong domain.
    """
    host = urlparse(base_url).hostname or "127.0.0.1"
    return {
        "cookies": [
            {
                "name": SESSION_COOKIE_NAME,
                "value": token,
                "domain": host,
                "path": "/",
                # -1 means a session cookie: it lives as long as the browser
                # context, which is exactly one test.
                "expires": -1,
                "httpOnly": True,
                "secure": False,
                "sameSite": "Lax",
            }
        ],
        "origins": [],
    }


def write_storage_state(token: str, base_url: str, destination: Path) -> Path:
    """Write a storage state to disk for ``browser.new_context(storage_state=...)``."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(storage_state_for_token(token, base_url), indent=2),
        encoding="utf-8",
    )
    return destination
