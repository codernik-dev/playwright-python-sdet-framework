"""One claim: its values, the actions available, and its audit trail."""

from __future__ import annotations

from typing import Self

from playwright.sync_api import Locator, expect

from claimdesk_qa.ui.base_page import BasePage


class ClaimDetailPage(BasePage):
    """Constructed with a claim id, because this page has no fixed path."""

    def __init__(self, page, settings, claim_id: str | None = None) -> None:  # type: ignore[no-untyped-def]
        super().__init__(page, settings)
        self._claim_id = claim_id

    @property
    def path(self) -> str:  # type: ignore[override]
        if self._claim_id is None:
            msg = "ClaimDetailPage needs a claim id before it can be opened"
            raise ValueError(msg)
        return f"/claims/{self._claim_id}"

    # -- values ---------------------------------------------------------- #

    @property
    def status(self) -> Locator:
        return self._page.get_by_test_id("claim-status")

    @property
    def amount(self) -> Locator:
        return self._page.get_by_test_id("claim-amount")

    @property
    def description(self) -> Locator:
        return self._page.get_by_test_id("claim-description")

    @property
    def payout(self) -> Locator:
        return self._page.get_by_test_id("claim-payout")

    @property
    def success_toast(self) -> Locator:
        return self._page.get_by_test_id("toast-success")

    @property
    def error_toast(self) -> Locator:
        return self._page.get_by_test_id("toast-error")

    # -- actions --------------------------------------------------------- #

    def action_button(self, action: str) -> Locator:
        return self._page.get_by_test_id(f"action-{action}")

    def perform(self, action: str) -> Self:
        self.action_button(action).click()
        return self

    # -- audit trail ------------------------------------------------------ #

    @property
    def event_rows(self) -> Locator:
        return self._page.get_by_test_id("event-row")

    def event_statuses(self) -> list[str]:
        return self._page.get_by_test_id("event-to-status").all_inner_texts()

    # -- assertions ------------------------------------------------------- #

    def expect_status(self, expected: str) -> Self:
        expect(self.status).to_have_text(expected)
        return self

    def expect_action_available(self, action: str) -> Self:
        expect(self.action_button(action)).to_be_visible()
        return self

    def expect_action_unavailable(self, action: str) -> Self:
        """to_have_count(0) rather than a negated visibility check.

        A negated assertion is satisfied by a page that has not rendered yet, so
        it can pass for the wrong reason. to_have_count retries.
        """
        expect(self.action_button(action)).to_have_count(0)
        return self
