import pytest
from unittest.mock import patch, MagicMock
from claudeclaw.auth.oauth import AuthManager, AuthError, TOKEN_KEY


def test_is_logged_in_returns_false_when_no_token(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDECLAW_HOME", str(tmp_path))
    auth = AuthManager()
    assert not auth.is_logged_in()


def test_is_logged_in_returns_true_when_token_exists(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDECLAW_HOME", str(tmp_path))
    auth = AuthManager()
    with patch.object(auth._store, "get", return_value="fake-token"):
        assert auth.is_logged_in()


def test_get_token_raises_when_not_logged_in(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDECLAW_HOME", str(tmp_path))
    auth = AuthManager()
    with patch.object(auth, "is_logged_in", return_value=False):
        with pytest.raises(AuthError, match="not logged in"):
            auth.get_token()


def test_logout_clears_token(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDECLAW_HOME", str(tmp_path))
    mock_store = MagicMock()
    auth = AuthManager(store=mock_store)
    auth.logout()
    mock_store.delete.assert_called_once_with(TOKEN_KEY)


def test_get_token_returns_token_when_logged_in(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDECLAW_HOME", str(tmp_path))
    auth = AuthManager()
    with patch.object(auth, "is_logged_in", return_value=True):
        with patch.object(auth._store, "get", return_value="tok"):
            assert auth.get_token() == "tok"
