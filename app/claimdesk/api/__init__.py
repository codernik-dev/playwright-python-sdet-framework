"""REST API, versioned under /api/v1."""

from fastapi import APIRouter

from claimdesk.api import auth, claims, policies, users

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(claims.router)
api_router.include_router(policies.router)
api_router.include_router(users.router)

__all__ = ["api_router"]
