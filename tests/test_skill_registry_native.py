# tests/test_skill_registry_native.py
import pytest
from pathlib import Path
from claudeclaw.skills.registry import SkillRegistry
from claudeclaw.skills.loader import SkillManifest


NATIVE_SKILLS_DIR = Path(__file__).parent.parent / "claudeclaw" / "skills" / "native"


def test_registry_loads_native_skills(tmp_path):
    registry = SkillRegistry(
        user_skills_dir=tmp_path,
        native_skills_dir=NATIVE_SKILLS_DIR,
    )
    skills = registry.all_skills()
    names = [s.name for s in skills]
    assert "pop" in names


def test_native_skills_annotated(tmp_path):
    registry = SkillRegistry(
        user_skills_dir=tmp_path,
        native_skills_dir=NATIVE_SKILLS_DIR,
    )
    pop_skill = registry.find("pop")
    assert pop_skill is not None
    assert pop_skill.is_native is True


def test_user_skill_shadows_native(tmp_path):
    """A user skill with the same name should take precedence over native."""
    user_pop = tmp_path / "pop.md"
    user_pop.write_text("""---
name: pop
description: User override of pop
trigger: on-demand
autonomy: ask
tools: []
shell-policy: none
---
User override body.
""")
    registry = SkillRegistry(
        user_skills_dir=tmp_path,
        native_skills_dir=NATIVE_SKILLS_DIR,
    )
    pop_skill = registry.find("pop")
    assert pop_skill.description == "User override of pop"
    assert pop_skill.is_native is False


def test_registry_find_returns_none_for_unknown(tmp_path):
    registry = SkillRegistry(
        user_skills_dir=tmp_path,
        native_skills_dir=NATIVE_SKILLS_DIR,
    )
    assert registry.find("does-not-exist") is None
