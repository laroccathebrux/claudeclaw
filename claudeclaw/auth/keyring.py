import json
import base64
import os
from pathlib import Path
from typing import Optional

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes

from claudeclaw.config.settings import Settings


SERVICE_NAME = "claudeclaw"
SALT_FILE_NAME = "keystore-salt"
_OLD_FIXED_SALT = b"claudeclaw-salt-v1"  # Plan 1 legacy — used for migration only


class CredentialMigrationError(Exception):
    """Raised when auto-migration from Plan 1's fixed salt fails."""


def _load_or_create_salt(config_dir: Path) -> bytes:
    """Load the per-installation salt from disk, or generate and save a new one."""
    salt_path = config_dir / SALT_FILE_NAME
    if salt_path.exists():
        return bytes.fromhex(salt_path.read_text().strip())
    salt = os.urandom(32)
    salt_path.write_text(salt.hex())
    return salt


def _derive_key(master_password: str, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=480_000)
    return base64.urlsafe_b64encode(kdf.derive(master_password.encode()))


class _FileBackend:
    """Encrypted JSON file for headless/VPS environments."""

    def __init__(self, path: Path, master_password: str):
        self._path = path
        config_dir = path.parent
        self._migrate_if_needed(config_dir, master_password)
        salt = _load_or_create_salt(config_dir)
        self._fernet = Fernet(_derive_key(master_password, salt))

    def _migrate_if_needed(self, config_dir: Path, master_password: str) -> None:
        """Auto-migrate from Plan 1's fixed salt to per-installation salt."""
        cred_file = config_dir / "credentials.enc"
        salt_file = config_dir / SALT_FILE_NAME
        if not (cred_file.exists() and not salt_file.exists()):
            return  # nothing to migrate

        try:
            old_key = base64.urlsafe_b64encode(
                PBKDF2HMAC(
                    algorithm=hashes.SHA256(), length=32,
                    salt=_OLD_FIXED_SALT, iterations=480_000
                ).derive(master_password.encode())
            )
            old_fernet = Fernet(old_key)
            data = json.loads(old_fernet.decrypt(cred_file.read_bytes()))
        except Exception as e:
            raise CredentialMigrationError(
                f"Found credentials.enc without keystore-salt. "
                f"Migration from fixed salt failed — check your master password. ({e})"
            ) from e

        new_salt = os.urandom(32)
        salt_file.write_text(new_salt.hex())
        new_key = _derive_key(master_password, new_salt)
        new_fernet = Fernet(new_key)
        cred_file.write_bytes(new_fernet.encrypt(json.dumps(data).encode()))

    def _load(self) -> dict:
        if not self._path.exists():
            return {}
        return json.loads(self._fernet.decrypt(self._path.read_bytes()))

    def _save(self, data: dict):
        self._path.write_bytes(self._fernet.encrypt(json.dumps(data).encode()))

    def get(self, key: str) -> Optional[str]:
        return self._load().get(key)

    def set(self, key: str, value: str):
        data = self._load()
        data[key] = value
        self._save(data)

    def delete(self, key: str):
        data = self._load()
        data.pop(key, None)
        self._save(data)

    def list_keys(self) -> list[str]:
        return list(self._load().keys())


class _KeyringBackend:
    """OS-native keyring (macOS Keychain, Windows Credential Manager, libsecret)."""

    def __init__(self):
        import keyring as _kr
        self._kr = _kr

    def get(self, key: str) -> Optional[str]:
        return self._kr.get_password(SERVICE_NAME, key)

    def set(self, key: str, value: str):
        self._kr.set_password(SERVICE_NAME, key, value)
        keys = self.list_keys()
        if key not in keys:
            keys.append(key)
            self._kr.set_password(SERVICE_NAME, "__index__", json.dumps(keys))

    def delete(self, key: str):
        try:
            self._kr.delete_password(SERVICE_NAME, key)
        except Exception:
            pass
        keys = self.list_keys()
        if key in keys:
            keys.remove(key)
            self._kr.set_password(SERVICE_NAME, "__index__", json.dumps(keys))

    def list_keys(self) -> list[str]:
        raw = self._kr.get_password(SERVICE_NAME, "__index__")
        return json.loads(raw) if raw else []


class CredentialStore:
    """
    Unified credential store. Backend selection:
      - backend="auto"  → tries OS keyring, falls back to file if unavailable
      - backend="keyring" → OS keyring only
      - backend="file"  → encrypted file (requires master_password)
    """

    def __init__(self, backend: str = "auto", master_password: Optional[str] = None):
        settings = Settings()
        cred_file = settings.config_dir / "credentials.enc"

        if backend == "file" or (backend == "auto" and not self._keyring_available()):
            if master_password is None:
                raise ValueError("master_password required for file backend")
            self._backend = _FileBackend(cred_file, master_password)
        else:
            self._backend = _KeyringBackend()

    @staticmethod
    def _keyring_available() -> bool:
        try:
            import keyring
            keyring.get_password("__test__", "__test__")
            return True
        except Exception:
            return False

    def get(self, key: str) -> Optional[str]:
        return self._backend.get(key)

    def set(self, key: str, value: str):
        self._backend.set(key, value)

    def delete(self, key: str):
        self._backend.delete(key)

    def list_keys(self) -> list[str]:
        return self._backend.list_keys()
