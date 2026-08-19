"""The sign-in page."""

from __future__ import annotations

from typing import Self

from playwright.sync_api import Locator, expect

from claimdesk_qa.ui.base_page import BasePage


class LoginPage(BasePage):
    path = "/login"
    ready_test_id = "submit-login"

    @property
    def email_field(self) -> Locator:
        return self._page.get_by_test_id("email")

    @property
    def password_field(self) -> Locator:
        return self._page.get_by_test_id("password")

    @property
    def submit_button(self) -> Locator:
        return self._page.get_by_test_id("submit-login")

    @property
    def error_message(self) -> Locator:
        return self._page.get_by_test_id("login-error")

    def sign_in(self, email: str, password: str) -> Self:
        """Fill the form and submit. Deliberately does NOT assert the outcome.

        Roughly half the tests using this expect it to fail. A method that
        asserted success would force every negative test to reach around it - and
        a page object people work around stops being maintained.
        """
        self.email_field.fill(email)
        self.password_field.fill(password)
        self.submit_button.click()
        return self

    def expect_error(self, text: str = "Invalid email or password") -> Self:
        """Assert the visible error.

        `expect` retries until the timeout, so this is correct even though the
        message arrives with the server's response rather than being present
        already. No sleep, no manual wait.
        """
        expect(self.error_message).to_be_visible()
        expect(self.error_message).to_have_text(text)
        return self
