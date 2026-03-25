from pathlib import Path
from claudeclaw.config.settings import Settings, get_settings


def test_default_skills_dir_is_under_home():
    s = Settings()
    assert s.skills_dir.parts[-1] == "skills"
    assert ".claudeclaw" in str(s.skills_dir)


def test_settings_creates_dirs_on_init(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDECLAW_HOME", str(tmp_path))
    s = Settings()
    assert s.skills_dir.exists()
    assert s.config_dir.exists()
