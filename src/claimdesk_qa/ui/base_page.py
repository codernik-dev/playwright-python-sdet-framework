"""The base every page object extends.

Two rules are enforced here rather than left to discipline, because both are easy
to get wrong and expensive when you do.

**Locators are properties, never stored elements.**

```python
@property
def submit_button(self) -> Locator:      # correct - resolved at use time
    return self._page.get_by_test_id("submit-login")

self.submit_button = page.query_selector("#submit")   # WRONG - resolved now
```

A ``Locator`` is a *description* of how to find an element; it is resolved every
time it is used, and Playwright's auto-waiting applies at that moment. A stored
element handle is a snapshot: the moment the page re-renders, it is stale, and the
test fails with a detached-node error that looks like a product bug.

**No page object ever calls ``sleep``.**

Playwright already waits for an element to be attached, visible, stable, enabled
and able to receive events before acting on it. A sleep is either redundant (the
common case) or hiding a real race that will surface on a slower CI agent. If
something genuinely needs waiting for, wait for *that thing* — a URL, a state, a
count — never for a duration.
"""

from __future__ import annotations

from typing import Self

from playwright.sync_api import Locator, Page, expect

from claimdesk_qa.config import Settings
from claimdesk_qa.core.logging import get_logger

logger = get_logger(__name__)


class BasePage:
    """Shared navigation, waiting and assertion helpers.

    Deliberately small. A base class that accumulates every convenience becomes
    the god-object that page objects exist to avoid — the temptation is to put
    "just one more" claim-specific helper here, and three of those later every
    page depends on claim logic it never uses.
    """

    #: Path relative to the base URL, e.g. ``/claims``. Overridden by each page.
    path: str = "/"

    #: An element that is present only when this page has finished rendering.
    #: Used by :meth:`expect_loaded`, so "did the page load?" is one clear
    #: assertion instead of a guess about timing.
    ready_test_id: str = "page-title"

    def __init__(self, page: Page, settings: Settings) -> None:
        self._page = page
        self._settings = settings

    # ------------------------------------------------------------------ #
    # navigation
    # ------------------------------------------------------------------ #

    @property
    def page(self) -> Page:
        """The underlying Playwright page.

        Exposed so a test can do something genuinely one-off without a new page
        object method — but reaching for it repeatedly is a signal that the page
        object is missing a method.
        """
        return self._page

    def url_for(self, path: str | None = None) -> str:
        return f"{self._settings.base_url}{path or self.path}"

    def open(self) -> Self:
        """Navigate to this page directly.

        Deep-linking rather than clicking through the interface. A test about the
        claims table should not be able to fail because the *dashboard* link
        broke — that is a different test's job, and coupling them turns one defect
        into a dozen red tests.
        """
        logger.info("Opening %s", self.url_for())
        self._page.goto(self.url_for(), wait_until="domcontentloaded")
        return self

    def expect_loaded(self) -> Self:
        """Assert the page has rendered. Auto-retries until the timeout."""
        expect(self.ready_marker).to_be_visible()
        return self

    # ------------------------------------------------------------------ #
    # shared locators
    # ------------------------------------------------------------------ #

    @property
    def ready_marker(self) -> Locator:
        return self._page.get_by_test_id(self.ready_test_id)

    @property
    def current_user_label(self) -> Locator:
        return self._page.get_by_test_id("current-user")

    # ------------------------------------------------------------------ #
    # helpers
    # ------------------------------------------------------------------ #

    def expect_path(self, path: str) -> Self:
        """Assert the browser ended up where it should have.

        ``expect(page).to_have_url`` retries, so it tolerates a redirect that is
        still in flight — unlike reading ``page.url`` directly, which is the
        classic source of a redirect race.
        """
        expect(self._page).to_have_url(self.url_for(path))
        return self

    def screenshot_bytes(self) -> bytes:
        """Full-page screenshot, used by the failure hook rather than by tests."""
        return self._page.screenshot(full_page=True)
