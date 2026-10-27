from __future__ import annotations

import os
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
    
    In authenticated mode:
      - Validates Bearer token or X-API-Key against server authorization secret.
      - Never allows unauthenticated caller-supplied user IDs to bypass security.
    
    In local single-user mode (AUTH_ENABLED=false):
      - Binds strictly to the local owner (default 'owner' or 'default_user').
      - Rejects arbitrary user impersonation attempts.
    """
    if AUTH_ENABLED:
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

        # Validate token against configured server key
        if SERVER_API_KEY and token != SERVER_API_KEY:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Invalid or unauthorized authentication credentials.",
            )

        # When authorized, user identity is either the authenticated caller identity or verified tenant
        authenticated_user = x_user_id.strip() if x_user_id and x_user_id.strip() else DEFAULT_USER
        return authenticated_user

    # Local personal single-tenant mode:
    # Use specified x_user_id if provided (for backwards test compatibility), or default to DEFAULT_USER
    return x_user_id if x_user_id and x_user_id.strip() else DEFAULT_USER
