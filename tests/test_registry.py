import pytest
from claudeclaw.skills.registry import SkillRegistry


def test_list_returns_loaded_skills(tmp_skills_dir, sample_skill_md, monkeypatch):
    monkeypatch.setenv("CLAUDECLAW_HOME", str(tmp_skills_dir.parent))
    registry = SkillRegistry(skills_dir=tmp_skills_dir)
    skills = registry.list_skills()
    assert len(skills) == 1
    assert skills[0].name == "test-skill"


def test_find_by_name(tmp_skills_dir, sample_skill_md, monkeypatch):
    registry = SkillRegistry(skills_dir=tmp_skills_dir)
    skill = registry.find("test-skill")
    assert skill is not None
    assert skill.name == "test-skill"


def test_find_missing_returns_none(tmp_skills_dir):
    registry = SkillRegistry(skills_dir=tmp_skills_dir)
    assert registry.find("does-not-exist") is None


def test_skips_invalid_skills(tmp_skills_dir, caplog):
    bad = tmp_skills_dir / "bad.md"
    bad.write_text("---\nno-name: true\n---\nbody")
    registry = SkillRegistry(skills_dir=tmp_skills_dir)
    skills = registry.list_skills()
    # bad.md is skipped, no crash
    assert all(s.name != "bad" for s in skills)
