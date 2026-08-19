"""The new-claim form."""

from __future__ import annotations

from typing import Self

from playwright.sync_api import Locator, expect

from claimdesk_qa.ui.base_page import BasePage


class ClaimFormPage(BasePage):
    path = "/claims/new"

    @property
    def policy_select(self) -> Locator:
        return self._page.get_by_test_id("policy")

    @property
    def amount_field(self) -> Locator:
        return self._page.get_by_test_id("amount")

    @property
    def incident_date_field(self) -> Locator:
        return self._page.get_by_test_id("incident-date")

    @property
    def description_field(self) -> Locator:
        return self._page.get_by_test_id("description")

    @property
    def submit_button(self) -> Locator:
        return self._page.get_by_test_id("submit-claim")

    @property
    def error_message(self) -> Locator:
        return self._page.get_by_test_id("form-error")

    def fill_in(
        self,
        *,
        amount: str,
        description: str,
        incident_date: str,
        policy_number: str | None = None,
    ) -> Self:
        """Populate the form without submitting it.

        Separating fill from submit lets a test assert on client-side state before
        submission - and keeps the negative tests readable, since they differ only
        in the one value they are about.
        """
        if policy_number is not None:
            self.policy_select.select_option(label=policy_number)
        self.amount_field.fill(amount)
        self.incident_date_field.fill(incident_date)
        self.description_field.fill(description)
        return self

    def submit(self) -> Self:
        self.submit_button.click()
        return self

    def expect_error_containing(self, fragment: str) -> Self:
        expect(self.error_message).to_be_visible()
        expect(self.error_message).to_contain_text(fragment)
        return self

    def expect_still_on_form(self) -> Self:
        """A rejected submission must not navigate away and lose the input."""
        expect(self.submit_button).to_be_visible()
        return self
