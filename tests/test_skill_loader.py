import pytest
from pathlib import Path
from claudeclaw.skills.loader import load_skill, SkillManifest, SkillLoadError


def test_load_valid_skill(sample_skill_md):
    skill = load_skill(sample_skill_md)
    assert skill.name == "test-skill"
    assert skill.trigger == "on-demand"
    assert skill.autonomy == "ask"
    assert skill.shell_policy == "none"
    assert "Do nothing" in skill.body


def test_missing_required_field_raises(tmp_path):
    bad = tmp_path / "bad.md"
    bad.write_text("---\nname: no-description\n---\nBody")
    with pytest.raises(SkillLoadError, match="description"):
        load_skill(bad)


def test_invalid_autonomy_value_raises(tmp_path):
    bad = tmp_path / "bad2.md"
    bad.write_text("""---
name: bad
description: test
trigger: on-demand
autonomy: maybe
tools: []
shell-policy: none
---
Body""")
    with pytest.raises(SkillLoadError, match="autonomy"):
        load_skill(bad)


def test_cron_skill_requires_schedule(tmp_path):
    bad = tmp_path / "bad3.md"
    bad.write_text("""---
name: no-schedule
description: test
trigger: cron
autonomy: autonomous
tools: []
shell-policy: none
---
Body""")
    with pytest.raises(SkillLoadError, match="schedule"):
        load_skill(bad)


def test_optional_fields_have_defaults(sample_skill_md):
    skill = load_skill(sample_skill_md)
    assert skill.plugins == []
    assert skill.mcps == []
    assert skill.credentials == []
