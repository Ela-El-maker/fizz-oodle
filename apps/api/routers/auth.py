from __future__ import annotations

import hmac
from typing import Callable

from fastapi import Header, HTTPException, Request

from apps.core.config import get_settings
from apps.core.session_auth import verify_session_token

settings = get_settings()

# Role hierarchy: admin > operator > viewer
ROLE_HIERARCHY = {"admin": 3, "operator": 2, "viewer": 1}


def get_session_user(request: Request) -> str | None:
    if not settings.SESSION_AUTH_ENABLED:
        return None
    token = request.cookies.get(settings.SESSION_COOKIE_NAME)
    if not token:
        return None
    payload = verify_session_token(token, secret=settings.SESSION_SECRET)
    if not payload:
        return None
    sub = payload.get("sub")
    if isinstance(sub, str) and sub:
        return sub
    return None


def get_session_role(request: Request) -> str | None:
    """Extract the role from the session token, if present."""
    if not settings.SESSION_AUTH_ENABLED:
        return None
    token = request.cookies.get(settings.SESSION_COOKIE_NAME)
    if not token:
        return None
    payload = verify_session_token(token, secret=settings.SESSION_SECRET)
    if not payload:
        return None
    return str(payload.get("role") or "viewer")


def require_api_key(
    request: Request,
    x_api_key: str | None = Header(default=None),
) -> None:
    if not settings.API_KEY:
        return
    if x_api_key and hmac.compare_digest(x_api_key, settings.API_KEY):
        return
    if get_session_user(request):
        return
    raise HTTPException(status_code=401, detail="Invalid API key")


def require_role(minimum_role: str) -> Callable:
    """FastAPI dependency factory that enforces a minimum role.

    API-key auth (programmatic) is treated as admin level.
    Session auth checks the role claim in the JWT.

    Usage:
        @app.post("/admin/...", dependencies=[Depends(require_role("admin"))])
    """
    min_level = ROLE_HIERARCHY.get(minimum_role, 1)

    def _guard(
        request: Request,
        x_api_key: str | None = Header(default=None),
    ) -> None:
        # API key holders get full admin access
        if settings.API_KEY and x_api_key and hmac.compare_digest(x_api_key, settings.API_KEY):
            return

        # Session-based: check role claim
        role = get_session_role(request)
        if role is None:
            raise HTTPException(status_code=401, detail="Authentication required")
        level = ROLE_HIERARCHY.get(role, 0)
        if level < min_level:
            raise HTTPException(status_code=403, detail=f"Requires {minimum_role} role")

    return _guard
