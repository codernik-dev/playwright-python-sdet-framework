"""Page objects: one per screen, composing shared components."""

from claimdesk_qa.ui.pages.admin_users_page import AdminUsersPage
from claimdesk_qa.ui.pages.claim_detail_page import ClaimDetailPage
from claimdesk_qa.ui.pages.claim_form_page import ClaimFormPage
from claimdesk_qa.ui.pages.claims_list_page import ClaimsListPage
from claimdesk_qa.ui.pages.dashboard_page import DashboardPage
from claimdesk_qa.ui.pages.login_page import LoginPage

__all__ = [
    "AdminUsersPage",
    "ClaimDetailPage",
    "ClaimFormPage",
    "ClaimsListPage",
    "DashboardPage",
    "LoginPage",
]
