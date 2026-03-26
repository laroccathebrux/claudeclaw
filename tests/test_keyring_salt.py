# tests/test_keyring_salt.py
import pytest
from pathlib import Path
from claudeclaw.auth.keyring import _load_or_create_salt, CredentialStore, CredentialMigrationError


def test_creates_salt_file_on_first_run(tmp_path):
    salt_path = tmp_path / "keystore-salt"
    assert not salt_path.exists()
    salt = _load_or_create_salt(tmp_path)
    assert salt_path.exists()
    assert len(salt) == 32


def test_loads_existing_salt_file(tmp_path):
    salt_path = tmp_path / "keystore-salt"
    original = b"\xde\xad" * 16  # 32 bytes
    salt_path.write_text(original.hex())
    loaded = _load_or_create_salt(tmp_path)
    assert loaded == original


def test_salt_is_random_across_two_installations(tmp_path):
    dir_a = tmp_path / "a"
    dir_b = tmp_path / "b"
    dir_a.mkdir()
    dir_b.mkdir()
    salt_a = _load_or_create_salt(dir_a)
    salt_b = _load_or_create_salt(dir_b)
    assert salt_a != salt_b


def test_credential_store_file_backend_uses_per_installation_salt(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDECLAW_HOME", str(tmp_path))
    store = CredentialStore(backend="file", master_password="test-secret")
    store.set("my-key", "my-value")
    salt_path = tmp_path / "config" / "keystore-salt"
    assert salt_path.exists()


def test_migration_re_encrypts_with_new_salt(tmp_path, monkeypatch):
    """
    Simulate a Plan 1 credential store (fixed salt, no keystore-salt file).
    After loading with Plan 6 CredentialStore, the store must be re-encrypted
    and a keystore-salt file must exist.
    """
    import json, base64
    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    from cryptography.hazmat.primitives import hashes

    monkeypatch.setenv("CLAUDECLAW_HOME", str(tmp_path))
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True)

    # Create old-style credentials.enc with fixed salt
    OLD_SALT = b"claudeclaw-salt-v1"
    master_pw = "migrate-me"
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=OLD_SALT, iterations=480_000)
    old_key = base64.urlsafe_b64encode(kdf.derive(master_pw.encode()))
    old_fernet = Fernet(old_key)
    old_data = {"secret-key": "secret-value"}
    (config_dir / "credentials.enc").write_bytes(
        old_fernet.encrypt(json.dumps(old_data).encode())
    )

    # No keystore-salt exists yet
    assert not (config_dir / "keystore-salt").exists()

    # Load with Plan 6 CredentialStore — should auto-migrate
    store = CredentialStore(backend="file", master_password=master_pw)

    # Migration must have written keystore-salt
    assert (config_dir / "keystore-salt").exists()

    # The value must still be retrievable
    assert store.get("secret-key") == "secret-value"


def test_migration_fails_gracefully_on_wrong_password(tmp_path, monkeypatch):
    import json, base64
    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    from cryptography.hazmat.primitives import hashes

    monkeypatch.setenv("CLAUDECLAW_HOME", str(tmp_path))
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True)

    OLD_SALT = b"claudeclaw-salt-v1"
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=OLD_SALT, iterations=480_000)
    old_key = base64.urlsafe_b64encode(kdf.derive(b"correct-password"))
    old_fernet = Fernet(old_key)
    (config_dir / "credentials.enc").write_bytes(
        old_fernet.encrypt(b'{"k": "v"}')
    )

    with pytest.raises(CredentialMigrationError):
        CredentialStore(backend="file", master_password="wrong-password")
