# tests/conftest.py
import pytest
from pathlib import Path
import tempfile


@pytest.fixture
def tmp_skills_dir(tmp_path):
    """Temporary ~/.claudeclaw/skills/ replacement for tests."""
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    return skills_dir


@pytest.fixture
def sample_skill_md(tmp_skills_dir):
    """Write a minimal valid skill .md to the temp dir."""
    content = """---
name: test-skill
description: A test skill for unit tests
trigger: on-demand
autonomy: ask
tools: []
shell-policy: none
---
# Test Skill
Do nothing. This is a test.
"""
    skill_file = tmp_skills_dir / "test-skill.md"
    skill_file.write_text(content)
    return skill_file
