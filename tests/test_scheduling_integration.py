import pytest
import yaml
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock


@pytest.fixture
def integration_skills_dir(tmp_path):
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    fixture = Path(__file__).parent / "fixtures" / "cron-test-skill.md"
    (skills_dir / "cron-test-skill.md").write_text(fixture.read_text())
    return skills_dir


@pytest.mark.asyncio
async def test_full_startup_registers_cron_skill(tmp_path, monkeypatch, integration_skills_dir):
    monkeypatch.setenv("CLAUDECLAW_HOME", str(tmp_path))

    from claudeclaw.skills.registry import SkillRegistry
    from claudeclaw.scheduling.manager import ScheduleManager

    registry = SkillRegistry(skills_dir=integration_skills_dir)
    all_skills = registry.list_all()
    cron_skill = next((s for s in all_skills if s.name == "cron-test-skill"), None)
    assert cron_skill is not None
    assert cron_skill.trigger == "cron"
    assert cron_skill.schedule == "*/5 * * * *"

    mock_client = MagicMock()
    mock_client.beta.cron_create = AsyncMock(return_value={"cron_id": "cron_integration_001"})
    mock_client.beta.cron_delete = AsyncMock(return_value={"deleted": True})
    mock_client.beta.remote_trigger = AsyncMock(return_value={"webhook_url": "https://example.com"})

    manager = ScheduleManager(sdk_client=mock_client)
    await manager.register_crons(all_skills)
    await manager.register_webhooks(all_skills)

    mock_client.beta.cron_create.assert_awaited_once_with(
        schedule="*/5 * * * *",
        metadata={"skill_name": "cron-test-skill"},
    )
    mock_client.beta.remote_trigger.assert_not_awaited()

    schedules_file = tmp_path / "config" / "schedules.yaml"
    assert schedules_file.exists()
    data = yaml.safe_load(schedules_file.read_text())
    assert data["cron-test-skill"]["cron_id"] == "cron_integration_001"


@pytest.mark.asyncio
async def test_cron_fired_event_dispatched_correctly(tmp_path, monkeypatch, integration_skills_dir):
    monkeypatch.setenv("CLAUDECLAW_HOME", str(tmp_path))

    from claudeclaw.skills.registry import SkillRegistry
    from claudeclaw.scheduling.manager import ScheduleManager

    registry = SkillRegistry(skills_dir=integration_skills_dir)
    skills = registry.list_all()

    mock_client = MagicMock()
    mock_client.beta.cron_create = AsyncMock(return_value={"cron_id": "cron_int_fire_001"})
    mock_client.beta.cron_delete = AsyncMock(return_value={"deleted": True})
    mock_client.beta.remote_trigger = AsyncMock(return_value={"webhook_url": "https://example.com"})

    manager = ScheduleManager(sdk_client=mock_client)
    await manager.register_crons(skills)

    tool_use_block = {
        "type": "tool_use",
        "name": "CronFired",
        "input": {"cron_id": "cron_int_fire_001", "fired_at": "2026-03-25T10:05:00Z"},
    }
    event = await manager.handle_tool_use_event(tool_use_block)

    assert event is not None
    assert event.source == "cron"
    assert event.skill_name == "cron-test-skill"
    assert event.payload["fired_at"] == "2026-03-25T10:05:00Z"
    assert event.channel_reply_fn is None
