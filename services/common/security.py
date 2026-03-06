from __future__ import annotations

import hmac

from fastapi import Header, HTTPException, status

from apps.core.config import get_settings


def require_internal_api_key(
    x_internal_api_key: str | None = Header(default=None),
) -> None:
    settings = get_settings()
    if not x_internal_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing internal API key",
        )
    if not hmac.compare_digest(x_internal_api_key, settings.INTERNAL_API_KEY):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid internal API key",
        )

