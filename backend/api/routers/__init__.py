"""
backend/api/routers package
"""
from backend.api.routers.auth import router as auth_router
from backend.api.routers.health import router as health_router
from backend.api.routers.profile import router as profile_router
from backend.api.routers.accounts import router as accounts_router
from backend.api.routers.transactions import router as transactions_router
from backend.api.routers.imports import router as imports_router
from backend.api.routers.purchases import router as purchases_router
from backend.api.routers.decisions import router as decisions_router

__all__ = [
    "auth_router",
    "health_router",
    "profile_router",
    "accounts_router",
    "transactions_router",
    "imports_router",
    "purchases_router",
    "decisions_router",
]
