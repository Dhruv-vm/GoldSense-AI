from __future__ import annotations

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from app.core import auth


def test_auth_disabled_default_user():
    orig = auth.AUTH_ENABLED
    try:
        auth.AUTH_ENABLED = False
        user = auth.get_current_user(credentials=None, x_user_id=None, x_api_key=None)
        assert user == "owner"

        # Explicit header passes through in dev mode
        user2 = auth.get_current_user(credentials=None, x_user_id="custom_user", x_api_key=None)
        assert user2 == "custom_user"
    finally:
        auth.AUTH_ENABLED = orig


def test_auth_enabled_rejects_unauthenticated():
    orig = auth.AUTH_ENABLED
    orig_key = auth.SERVER_API_KEY
    try:
        auth.AUTH_ENABLED = True
        auth.SERVER_API_KEY = "super_secret_test_key"

        # Missing token raises 401
        with pytest.raises(HTTPException) as exc:
            auth.get_current_user(credentials=None, x_user_id=None, x_api_key=None)
        assert exc.value.status_code == 401

        # Invalid token raises 403
        with pytest.raises(HTTPException) as exc:
            auth.get_current_user(
                credentials=HTTPAuthorizationCredentials(scheme="Bearer", credentials="wrong_token"),
                x_user_id="attacker",
                x_api_key=None,
            )
        assert exc.value.status_code == 403

        # Valid token via Bearer authorizes successfully
        valid_user = auth.get_current_user(
            credentials=HTTPAuthorizationCredentials(scheme="Bearer", credentials="super_secret_test_key"),
            x_user_id="verified_user",
            x_api_key=None,
        )
        assert valid_user == "verified_user"

        # Valid token via X-API-Key authorizes successfully
        valid_user2 = auth.get_current_user(
            credentials=None,
            x_user_id=None,
            x_api_key="super_secret_test_key",
        )
        assert valid_user2 == "owner"
    finally:
        auth.AUTH_ENABLED = orig
        auth.SERVER_API_KEY = orig_key
