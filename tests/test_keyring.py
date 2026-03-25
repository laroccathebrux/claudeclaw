import pytest
from claudeclaw.auth.keyring import CredentialStore


def test_set_and_get_credential(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDECLAW_HOME", str(tmp_path))
    store = CredentialStore(backend="file", master_password="test-secret")
    store.set("erp-user", "alice")
    assert store.get("erp-user") == "alice"


def test_get_missing_returns_none(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDECLAW_HOME", str(tmp_path))
    store = CredentialStore(backend="file", master_password="test-secret")
    assert store.get("does-not-exist") is None


def test_delete_credential(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDECLAW_HOME", str(tmp_path))
    store = CredentialStore(backend="file", master_password="test-secret")
    store.set("token", "abc123")
    store.delete("token")
    assert store.get("token") is None


def test_list_keys(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDECLAW_HOME", str(tmp_path))
    store = CredentialStore(backend="file", master_password="test-secret")
    store.set("key-a", "val-a")
    store.set("key-b", "val-b")
    keys = store.list_keys()
    assert "key-a" in keys
    assert "key-b" in keys
