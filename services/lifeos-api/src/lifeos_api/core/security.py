from __future__ import annotations

import hmac
import os

from fastapi import Header, HTTPException, Request, status


async def require_api_key(
    request: Request,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    authorization: str | None = Header(default=None, alias="Authorization"),
    x_shortcut_token: str | None = Header(default=None, alias="X-Shortcut-Token"),
) -> None:
    if request.url.path.startswith("/integrations/shortcuts/"):
        require_shortcut_token(authorization=authorization, x_shortcut_token=x_shortcut_token)
        return

    expected = os.getenv("LIFEOS_API_KEY")
    allow_anonymous = os.getenv("LIFEOS_ALLOW_ANONYMOUS", "").lower() in {"1", "true", "yes"}
    if not expected and not allow_anonymous:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="api key is not configured")
    if expected and not hmac.compare_digest(x_api_key or "", expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid API key")


def require_shortcut_token(*, authorization: str | None, x_shortcut_token: str | None) -> None:
    expected = os.getenv("LIFEOS_SHORTCUT_TOKEN")
    if not expected:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="shortcut token is not configured")

    supplied = x_shortcut_token or bearer_token(authorization)
    if not supplied or not hmac.compare_digest(supplied, expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid shortcut token")


def bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, separator, token = authorization.partition(" ")
    if separator and scheme.lower() == "bearer" and token.strip():
        return token.strip()
    return None
