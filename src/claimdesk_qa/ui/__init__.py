"""The browser automation layer: page objects, components and session helpers."""

from claimdesk_qa.ui.base_page import BasePage
from claimdesk_qa.ui.components import Navigation
from claimdesk_qa.ui.pages import (
    AdminUsersPage,
    ClaimDetailPage,
    ClaimFormPage,
    ClaimsListPage,
    DashboardPage,
    LoginPage,
)
from claimdesk_qa.ui.session import storage_state_for_token

__all__ = [
    "AdminUsersPage",
    "BasePage",
    "ClaimDetailPage",
    "ClaimFormPage",
    "ClaimsListPage",
    "DashboardPage",
    "LoginPage",
    "Navigation",
    "storage_state_for_token",
]
