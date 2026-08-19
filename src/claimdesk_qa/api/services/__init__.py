"""Service objects: one per API resource.

A service object is the API layer's equivalent of a page object. It hides the URL,
the verb and the payload shape so a test reads as intent:

    claims.transition(claim.id, ClaimAction.APPROVE).expect_status(403)

rather than as plumbing. When an endpoint moves, one file changes.
"""

from claimdesk_qa.api.services.auth import AuthApi
from claimdesk_qa.api.services.claims import ClaimsApi
from claimdesk_qa.api.services.policies import PoliciesApi
from claimdesk_qa.api.services.users import UsersApi

__all__ = ["AuthApi", "ClaimsApi", "PoliciesApi", "UsersApi"]
