from __future__ import annotations

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from app.core import auth


def test_auth_disabled_default_user_blocks_arbitrary_header():
    orig_auth = auth.AUTH_ENABLED
    orig_allow = auth.ALLOW_TEST_USER_HEADER
    try:
        auth.AUTH_ENABLED = False
        auth.ALLOW_TEST_USER_HEADER = False
        assert auth.get_current_user(credentials=None, x_user_id=None, x_api_key=None) == "owner"

        # Arbitrary X-User-ID spoofing is ignored in production/default single-user mode
        assert auth.get_current_user(credentials=None, x_user_id="attacker", x_api_key=None) == "owner"

        # Explicit test harness flag permits header override in isolated unit tests
        auth.ALLOW_TEST_USER_HEADER = True
        assert auth.get_current_user(credentials=None, x_user_id="custom_user", x_api_key=None) == "custom_user"
    finally:
        auth.AUTH_ENABLED = orig_auth
        auth.ALLOW_TEST_USER_HEADER = orig_allow


def test_auth_enabled_rejects_unauthenticated_and_cross_user():
    orig = auth.AUTH_ENABLED
    orig_key = auth.SERVER_API_KEY
    try:
        auth.AUTH_ENABLED = True
        auth.SERVER_API_KEY = "super_secret_test_key"

        with pytest.raises(HTTPException) as exc:
            auth.get_current_user(credentials=None, x_user_id=None, x_api_key=None)
        assert exc.value.status_code == 401

        with pytest.raises(HTTPException) as exc:
            auth.get_current_user(
                credentials=HTTPAuthorizationCredentials(scheme="Bearer", credentials="wrong_token"),
                x_user_id="owner",
                x_api_key=None,
            )
        assert exc.value.status_code == 403

        valid_user = auth.get_current_user(
            credentials=HTTPAuthorizationCredentials(scheme="Bearer", credentials="super_secret_test_key"),
            x_user_id="owner",
            x_api_key=None,
        )
        assert valid_user == "owner"

        valid_user2 = auth.get_current_user(
            credentials=None,
            x_user_id=None,
            x_api_key="super_secret_test_key",
        )
        assert valid_user2 == "owner"

        with pytest.raises(HTTPException) as exc_spoof:
            auth.get_current_user(
                credentials=HTTPAuthorizationCredentials(scheme="Bearer", credentials="super_secret_test_key"),
                x_user_id="victim_user",
                x_api_key=None,
            )
        assert exc_spoof.value.status_code == 403
        assert "Cross-user isolation enforced" in exc_spoof.value.detail

        auth.SERVER_API_KEY = ""
        with pytest.raises(HTTPException) as exc_misconfig:
            auth.get_current_user(
                credentials=HTTPAuthorizationCredentials(scheme="Bearer", credentials="some_token"),
                x_user_id="owner",
                x_api_key=None,
            )
        assert exc_misconfig.value.status_code == 500
    finally:
        auth.AUTH_ENABLED = orig
        auth.SERVER_API_KEY = orig_key
