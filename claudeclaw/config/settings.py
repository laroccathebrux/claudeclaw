import os
from pathlib import Path
from functools import lru_cache
import yaml


def _claudeclaw_home() -> Path:
    env = os.environ.get("CLAUDECLAW_HOME")
    if env:
        return Path(env)
    return Path.home() / ".claudeclaw"


class Settings:
    def __init__(self):
        self.home = _claudeclaw_home()
        self.config_dir = self.home / "config"
        self.skills_dir = self.home / "skills"
        self.plugins_dir = self.home / "plugins"
        self.config_file = self.config_dir / "settings.yaml"
        self._ensure_dirs()

    def _ensure_dirs(self):
        for d in [self.config_dir, self.skills_dir, self.plugins_dir]:
            d.mkdir(parents=True, exist_ok=True)

    def get(self, key: str, default=None):
        if not self.config_file.exists():
            return default
        data = yaml.safe_load(self.config_file.read_text()) or {}
        return data.get(key, default)

    def set(self, key: str, value) -> None:
        data = {}
        if self.config_file.exists():
            data = yaml.safe_load(self.config_file.read_text()) or {}
        data[key] = value
        self.config_file.write_text(yaml.dump(data))


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
