# tests/conftest.py
import pytest
from pathlib import Path


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


from unittest.mock import AsyncMock, MagicMock
from claudeclaw.skills.loader import SkillManifest
from claudeclaw.config.settings import get_settings


@pytest.fixture(autouse=True)
def clear_settings_cache():
    """Clear lru_cache on get_settings before/after each test."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def cron_skill():
    return SkillManifest(
        name="erp-invoices",
        description="Send monthly invoices",
        trigger="cron",
        schedule="0 0 28 * *",
        trigger_id=None,
        autonomy="autonomous",
        tools=[],
        shell_policy="none",
        body="Send invoices to all clients.",
    )


@pytest.fixture
def webhook_skill():
    return SkillManifest(
        name="crm-followup",
        description="Follow up on new CRM leads",
        trigger="webhook",
        schedule=None,
        trigger_id="new-crm-lead",
        autonomy="notify",
        tools=[],
        shell_policy="none",
        body="Process the new lead.",
    )


@pytest.fixture
def mock_sdk_client():
    client = MagicMock()
    client.beta = MagicMock()

    async def fake_cron_create(schedule: str, metadata: dict):
        return {"cron_id": f"cron_mock_{schedule.replace(' ', '_')}"}

    async def fake_cron_delete(cron_id: str):
        return {"deleted": True}

    async def fake_remote_trigger(trigger_id: str):
        return {"webhook_url": f"https://hooks.anthropic.com/rt/{trigger_id}"}

    client.beta.cron_create = AsyncMock(side_effect=fake_cron_create)
    client.beta.cron_delete = AsyncMock(side_effect=fake_cron_delete)
    client.beta.remote_trigger = AsyncMock(side_effect=fake_remote_trigger)
    return client
