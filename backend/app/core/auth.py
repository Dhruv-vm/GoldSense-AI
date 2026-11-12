from __future__ import annotations

import os
import secrets
from typing import Annotated
from fastapi import Header, HTTPException, Security, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

security = HTTPBearer(auto_error=False)

AUTH_ENABLED = os.environ.get("AUTH_ENABLED", "false").lower() in ("true", "1", "yes")
ALLOW_TEST_USER_HEADER = os.environ.get("ALLOW_TEST_USER_HEADER", "false").lower() in ("true", "1", "yes")
SERVER_API_KEY = os.environ.get("GOLDSENSE_API_KEY", "")
DEFAULT_USER = "owner"


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Security(security)] = None,
    x_user_id: str | None = Header(default=None, alias="X-User-ID"),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> str:
    """
    Server-side authorization dependency.

    In authenticated mode (AUTH_ENABLED=true):
      - Validates Bearer token or X-API-Key against server secret using constant-time comparison.
      - Fails closed (500) if GOLDSENSE_API_KEY is unset or weak (<8 chars).
      - Rejects caller impersonation of another user_id via X-User-ID with HTTP 403 Forbidden.
      - Supports explicit single-owner personal vault until full per-user JWT identity is introduced.

    In single-user local mode (AUTH_ENABLED=false):
      - Always resolves strictly to DEFAULT_USER ('owner') so arbitrary caller-supplied
        X-User-ID headers cannot hijack or spoof user identity unless explicitly running
        isolated tests with ALLOW_TEST_USER_HEADER=true.
    """
    if AUTH_ENABLED:
        if not SERVER_API_KEY or len(SERVER_API_KEY.strip()) < 8:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Server authentication misconfigured: GOLDSENSE_API_KEY must be set to at least 8 characters.",
            )

        token = None
        if credentials and credentials.credentials:
            token = credentials.credentials
        elif x_api_key:
            token = x_api_key

        if not token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required. Provide a valid Bearer token or X-API-Key.",
                headers={"WWW-Authenticate": "Bearer"},
            )

        if not secrets.compare_digest(token.encode("utf-8"), SERVER_API_KEY.encode("utf-8")):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Invalid or unauthorized authentication credentials.",
            )

        authenticated_identity = DEFAULT_USER
        if x_user_id and x_user_id.strip() and x_user_id.strip() != authenticated_identity:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Cross-user isolation enforced: credentials authorize '{authenticated_identity}', cannot impersonate '{x_user_id}'.",
            )

        return authenticated_identity

    # In non-authenticated mode, strictly bind to DEFAULT_USER unless explicit test harness isolation flag is set
    if ALLOW_TEST_USER_HEADER and x_user_id and x_user_id.strip():
        return x_user_id.strip()
    return DEFAULT_USER
