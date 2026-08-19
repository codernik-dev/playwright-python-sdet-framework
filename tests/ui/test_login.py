"""UI-AUTH — signing in and out through the browser.

Matrix: UI-AUTH-001 … UI-AUTH-005.

**These are the only tests that drive the login form.** Every other browser test
starts from an injected session, because it is not testing sign-in and should not
fail when sign-in breaks. Concentrating that coverage here means one defect
produces a handful of pointed failures instead of fifty vague ones.
"""

from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

from claimdesk_qa.config import Settings
from claimdesk_qa.data.seeded import SeededAccounts
from claimdesk_qa.ui import DashboardPage, LoginPage


@pytest.fixture
def password(settings: Settings) -> str:
    return settings.seed_user_password.get_secret_value()


@pytest.mark.smoke
def test_a_customer_can_sign_in(anonymous_page: Page, settings: Settings, password: str) -> None:
    """UI-AUTH-001 — the canonical happy path."""
    login = LoginPage(anonymous_page, settings).open().expect_loaded()

    login.sign_in(SeededAccounts.CUSTOMER, password)

    dashboard = DashboardPage(anonymous_page, settings)
    dashboard.expect_loaded().expect_path("/dashboard")
    dashboard.navigation.expect_signed_in_as("Casey Customer")


@pytest.mark.negative
@pytest.mark.smoke
def test_signing_in_with_a_wrong_password_shows_an_error(
    anonymous_page: Page, settings: Settings
) -> None:
    """UI-AUTH-002.

    Asserts the user stays on the login page as well as seeing the error. An
    application that showed an error *and* signed you in anyway would satisfy a
    message-only assertion.
    """
    login = LoginPage(anonymous_page, settings).open()

    login.sign_in(SeededAccounts.CUSTOMER, "definitely-not-the-password")

    login.expect_error()
    expect(anonymous_page).to_have_url(login.url_for("/login"))


@pytest.mark.negative
def test_an_unknown_account_gives_the_same_message_as_a_wrong_password(
    anonymous_page: Page, settings: Settings, password: str
) -> None:
    """UI-AUTH-003 — user enumeration, checked at the interface as well as the API.

    The API test proves the response bodies match. This proves the *rendered*
    message matches too — a UI that helpfully said "no account with that email"
    would leak exactly what the API was careful not to.
    """
    login = LoginPage(anonymous_page, settings).open()

    login.sign_in("definitely-not-registered@example.com", password)

    login.expect_error("Invalid email or password")


@pytest.mark.negative
def test_the_password_field_masks_input(anonymous_page: Page, settings: Settings) -> None:
    """A password rendered as plain text is a real finding in a shared office."""
    login = LoginPage(anonymous_page, settings).open()

    expect(login.password_field).to_have_attribute("type", "password")


def test_signing_out_ends_the_session(customer_page: Page, settings: Settings) -> None:
    """UI-AUTH-004.

    Sign-out must actually invalidate the browser session, not merely redirect.
    So after signing out the test navigates *back* to a protected page: if the
    session survived, the dashboard would render and this would fail.
    """
    dashboard = DashboardPage(customer_page, settings).open().expect_loaded()

    dashboard.navigation.log_out()

    expect(customer_page).to_have_url(dashboard.url_for("/login"))
    customer_page.goto(dashboard.url_for("/dashboard"))
    expect(customer_page).to_have_url(dashboard.url_for("/login?next=/dashboard"))


@pytest.mark.negative
def test_an_anonymous_visitor_is_redirected_to_sign_in(
    anonymous_page: Page, settings: Settings
) -> None:
    """UI-AUTH-005 — the browser redirects where the API would return 401.

    Same rule, two presentations: an API client gets a status code it can act on,
    a person gets a page they can use. Asserting the ``next`` parameter matters
    too — losing it sends the user to the dashboard after signing in instead of
    back to the page they actually wanted.
    """
    anonymous_page.goto(f"{settings.base_url}/claims")

    expect(anonymous_page).to_have_url(f"{settings.base_url}/login?next=/claims")
