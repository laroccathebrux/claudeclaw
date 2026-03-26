# tests/test_oauth_refresh.py
import pytest
from unittest.mock import MagicMock, patch
from claudeclaw.auth.oauth import AuthManager


def test_is_token_expiring_returns_true_when_near_expiry():
    auth = AuthManager.__new__(AuthManager)
    auth._token_expiry = __import__("time").time() + 60  # 60 seconds from now
    assert auth.is_token_expiring(within_seconds=300) is True


def test_is_token_expiring_returns_false_when_not_near_expiry():
    auth = AuthManager.__new__(AuthManager)
    auth._token_expiry = __import__("time").time() + 3600  # 1 hour from now
    assert auth.is_token_expiring(within_seconds=300) is False


def test_is_token_expiring_returns_true_when_no_expiry_set():
    """If no expiry is known, treat as expiring to force refresh."""
    auth = AuthManager.__new__(AuthManager)
    auth._token_expiry = None
    assert auth.is_token_expiring(within_seconds=300) is True


def test_refresh_token_returns_false_stub():
    """Plan 6 stub: refresh_token always returns False (endpoint not implemented)."""
    auth = AuthManager.__new__(AuthManager)
    auth._token_expiry = None
    result = auth.refresh_token()
    assert result is False
