"""The header, present on every authenticated page.

A component, not a page. The distinction matters: the header appears on six
different pages, so modelling it as part of any one of them would either duplicate
it six times or force five pages to inherit from an unrelated sixth.

Page objects compose components; they do not inherit them.
"""

from __future__ import annotations

from playwright.sync_api import Locator, Page, expect


class Navigation:
    """Links and the sign-out control in the application header."""

    def __init__(self, page: Page) -> None:
        self._page = page

    @property
    def dashboard_link(self) -> Locator:
        return self._page.get_by_test_id("nav-dashboard")

    @property
    def claims_link(self) -> Locator:
        return self._page.get_by_test_id("nav-claims")

    @property
    def new_claim_link(self) -> Locator:
        return self._page.get_by_test_id("nav-new-claim")

    @property
    def admin_link(self) -> Locator:
        """Only rendered for administrators.

        Its ABSENCE is asserted for other roles - but never as the only check.
        Hiding a link is presentation, not authorisation: the server must refuse
        the route as well, which UI-AUTHZ-002 proves by navigating directly.
        """
        return self._page.get_by_test_id("nav-admin")

    @property
    def current_user(self) -> Locator:
        return self._page.get_by_test_id("current-user")

    @property
    def logout_button(self) -> Locator:
        return self._page.get_by_test_id("logout")

    def log_out(self) -> None:
        self.logout_button.click()

    def expect_signed_in_as(self, full_name: str) -> None:
        expect(self.current_user).to_contain_text(full_name)
