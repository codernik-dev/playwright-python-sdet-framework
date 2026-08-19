"""The claims table, with its asynchronous filter.

The most interesting page in the suite, because it is the only one that updates
without a navigation. That is exactly where hand-rolled waits normally appear —
and exactly where they are least necessary.
"""

from __future__ import annotations

from typing import Self

from playwright.sync_api import Locator, expect

from claimdesk_qa.ui.base_page import BasePage
from claimdesk_qa.ui.components.navigation import Navigation


class ClaimsListPage(BasePage):
    path = "/claims"

    @property
    def navigation(self) -> Navigation:
        return Navigation(self._page)

    # ------------------------------------------------------------------ #
    # filters
    # ------------------------------------------------------------------ #

    @property
    def status_filter(self) -> Locator:
        return self._page.get_by_test_id("filter-status")

    @property
    def search_field(self) -> Locator:
        return self._page.get_by_test_id("filter-search")

    @property
    def apply_button(self) -> Locator:
        return self._page.get_by_test_id("apply-filters")

    @property
    def container(self) -> Locator:
        return self._page.get_by_test_id("claims-container")

    # ------------------------------------------------------------------ #
    # results
    # ------------------------------------------------------------------ #

    @property
    def rows(self) -> Locator:
        return self._page.get_by_test_id("claim-row")

    @property
    def result_count(self) -> Locator:
        return self._page.get_by_test_id("result-count")

    @property
    def empty_state(self) -> Locator:
        return self._page.get_by_test_id("empty-state")

    def row_for(self, reference: str) -> Locator:
        """The row for one claim, found by its reference.

        Keyed by data rather than by index. ``rows.nth(0)`` is the classic flaky
        locator: it silently means "whatever happens to be first", which changes
        with sort order, paging, and any row another parallel worker created.
        """
        return self._page.locator(f'[data-testid="claim-row"][data-reference="{reference}"]')

    def amount_cells(self) -> list[str]:
        return self._page.get_by_test_id("claim-amount").all_inner_texts()

    def status_chips(self) -> list[str]:
        return self._page.get_by_test_id("claim-status").all_inner_texts()

    # ------------------------------------------------------------------ #
    # actions
    # ------------------------------------------------------------------ #

    def search_for(self, term: str) -> Self:
        """Type a search term and apply it, waiting for the refresh to finish.

        The wait is on ``aria-busy``, which the page sets around its fetch. That
        is a **state**, not a duration — the difference between a test that is
        correct on a loaded CI agent and one that merely usually passes.

        Waiting on ``aria-busy`` rather than a private class name is deliberate
        twice over: it is the same signal assistive technology uses, so it cannot
        be renamed as an internal implementation detail without breaking
        accessibility too.
        """
        self.search_field.fill(term)
        self.apply_button.click()
        return self.wait_for_refresh()

    def filter_by_status(self, status: str) -> Self:
        """Select a status. The page refreshes on change, with no Apply click."""
        self.status_filter.select_option(status)
        return self.wait_for_refresh()

    def wait_for_refresh(self) -> Self:
        expect(self.container).to_have_attribute("aria-busy", "false")
        return self

    def open_claim(self, reference: str) -> None:
        self.row_for(reference).get_by_test_id("claim-link").click()

    # ------------------------------------------------------------------ #
    # assertions
    # ------------------------------------------------------------------ #

    def expect_result_count(self, expected: int) -> Self:
        expect(self.result_count).to_have_text(str(expected))
        return self

    def expect_contains(self, reference: str) -> Self:
        expect(self.row_for(reference)).to_be_visible()
        return self

    def expect_does_not_contain(self, reference: str) -> Self:
        """Assert a claim is absent.

        ``to_have_count(0)`` rather than ``not to_be_visible()``: the negative form
        passes instantly on a page that has not finished rendering, which makes it
        pass for the wrong reason. ``to_have_count`` retries until the timeout,
        so a row that appears late still fails the test.
        """
        expect(self.row_for(reference)).to_have_count(0)
        return self
