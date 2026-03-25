import json
import base64
from pathlib import Path
from typing import Optional

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes

from claudeclaw.config.settings import Settings


SERVICE_NAME = "claudeclaw"
SALT = b"claudeclaw-salt-v1"  # fixed salt; credential file is already protected by master pw


def _derive_key(master_password: str) -> bytes:
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=SALT, iterations=480_000)
    return base64.urlsafe_b64encode(kdf.derive(master_password.encode()))


class _FileBackend:
    """Encrypted JSON file for headless/VPS environments."""

    def __init__(self, path: Path, master_password: str):
        self._path = path
        self._fernet = Fernet(_derive_key(master_password))

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
        # Store value AND maintain an index so list_keys() works
        # (keyring has no native list API)
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
        # Update the index to remove the deleted key
        keys = self.list_keys()
        if key in keys:
            keys.remove(key)
            self._kr.set_password(SERVICE_NAME, "__index__", json.dumps(keys))

    def list_keys(self) -> list[str]:
        # keyring has no standard list API; we maintain an index key
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
