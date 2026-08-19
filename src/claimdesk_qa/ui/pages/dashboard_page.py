"""The landing page after sign-in."""

from __future__ import annotations

from playwright.sync_api import Locator, expect

from claimdesk_qa.ui.base_page import BasePage
from claimdesk_qa.ui.components.navigation import Navigation


class DashboardPage(BasePage):
    path = "/dashboard"

    @property
    def navigation(self) -> Navigation:
        return Navigation(self._page)

    def status_count(self, status: str) -> Locator:
        """The tile showing how many claims are in a given status."""
        return self._page.get_by_test_id(f"stat-{status}").locator(".value")

    def expect_status_count(self, status: str, expected: int) -> None:
        expect(self.status_count(status)).to_have_text(str(expected))
