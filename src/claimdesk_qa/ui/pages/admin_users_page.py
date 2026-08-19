"""User administration - reachable only by an administrator."""

from __future__ import annotations

from playwright.sync_api import Locator, expect

from claimdesk_qa.ui.base_page import BasePage


class AdminUsersPage(BasePage):
    path = "/admin/users"

    @property
    def rows(self) -> Locator:
        return self._page.get_by_test_id("user-row")

    @property
    def forbidden_message(self) -> Locator:
        """Shown instead of the table when a non-administrator navigates here."""
        return self._page.get_by_test_id("forbidden-message")

    def row_for(self, email: str) -> Locator:
        return self._page.locator(f'[data-testid="user-row"][data-email="{email}"]')

    def expect_forbidden(self) -> None:
        expect(self.forbidden_message).to_be_visible()

    def expect_lists_user(self, email: str) -> None:
        expect(self.row_for(email)).to_be_visible()
