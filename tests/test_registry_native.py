# tests/test_registry_native.py
import pytest
from claudeclaw.skills.registry import SkillRegistry


def test_native_agent_creator_always_available(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDECLAW_HOME", str(tmp_path))
    from claudeclaw.config.settings import get_settings
    get_settings.cache_clear()
    (tmp_path / "skills").mkdir(parents=True, exist_ok=True)
    registry = SkillRegistry(skills_dir=tmp_path / "skills")
    skill = registry.find("agent-creator")
    assert skill is not None
    assert skill.name == "agent-creator"


def test_native_pop_always_available(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDECLAW_HOME", str(tmp_path))
    from claudeclaw.config.settings import get_settings
    get_settings.cache_clear()
    (tmp_path / "skills").mkdir(parents=True, exist_ok=True)
    registry = SkillRegistry(skills_dir=tmp_path / "skills")
    skill = registry.find("pop")
    assert skill is not None
    assert skill.name == "pop"


def test_reload_picks_up_new_skills(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDECLAW_HOME", str(tmp_path))
    from claudeclaw.config.settings import get_settings
    get_settings.cache_clear()
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir(parents=True)
    registry = SkillRegistry(skills_dir=skills_dir)

    # Only native skills at first
    user_skills = [s for s in registry.list_skills() if s.name not in ("agent-creator", "pop")]
    assert len(user_skills) == 0

    # Write a new user skill
    (skills_dir / "new-skill.md").write_text("""---
name: new-skill
description: A brand new skill
trigger: on-demand
autonomy: ask
tools: []
shell-policy: none
---
Do the new thing.
""")
    # After reload, new skill is present
    reloaded = registry.reload()
    names = [s.name for s in reloaded]
    assert "new-skill" in names
