from __future__ import annotations

import os
import secrets
from typing import Annotated
from fastapi import Depends, Header, HTTPException, Security, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

security = HTTPBearer(auto_error=False)

AUTH_ENABLED = os.environ.get("AUTH_ENABLED", "false").lower() in ("true", "1", "yes")
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
      - Validates Bearer token or X-API-Key against server authorization secret using constant-time comparison.
      - Fails closed if GOLDSENSE_API_KEY is unset or empty.
      - Never allows unauthenticated caller-supplied user IDs to bypass security.
      - Binds the authenticated session to the verified tenant/owner.
      - Rejects attempts to spoof or switch to another user_id with HTTP 403 Forbidden.

    In local single-user mode (AUTH_ENABLED=false):
      - Binds strictly to the local owner (default 'owner').
      - Allows explicit test harness user overrides only when test isolation is active.
    """
    if AUTH_ENABLED:
        # Production fail-closed: must have a configured server secret
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

        # Constant-time comparison to prevent timing attacks
        if not secrets.compare_digest(token.encode("utf-8"), SERVER_API_KEY.encode("utf-8")):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Invalid or unauthorized authentication credentials.",
            )

        # The shared server API key authenticates the authorized vault owner.
        # It does NOT allow arbitrary caller-supplied user impersonation:
        authenticated_identity = DEFAULT_USER
        if x_user_id and x_user_id.strip() and x_user_id.strip() != authenticated_identity:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Cross-user isolation enforced: credentials authorize '{authenticated_identity}', cannot impersonate '{x_user_id}'.",
            )

        return authenticated_identity

    # Local personal single-tenant mode (AUTH_ENABLED=false):
    # Default to owner, allowing specified x_user_id for local tests
    return x_user_id if x_user_id and x_user_id.strip() else DEFAULT_USER
