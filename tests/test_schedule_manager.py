import pytest
import yaml
from pathlib import Path
from claudeclaw.scheduling.manager import ScheduleManager


@pytest.mark.asyncio
async def test_register_cron_calls_sdk(tmp_path, monkeypatch, mock_sdk_client, cron_skill):
    monkeypatch.setenv("CLAUDECLAW_HOME", str(tmp_path))
    manager = ScheduleManager(sdk_client=mock_sdk_client)
    await manager.register_crons([cron_skill])
    mock_sdk_client.beta.cron_create.assert_awaited_once()
    call_kwargs = mock_sdk_client.beta.cron_create.call_args
    assert call_kwargs.kwargs["schedule"] == "0 0 28 * *"
    assert call_kwargs.kwargs["metadata"]["skill_name"] == "erp-invoices"


@pytest.mark.asyncio
async def test_register_cron_persists_to_yaml(tmp_path, monkeypatch, mock_sdk_client, cron_skill):
    monkeypatch.setenv("CLAUDECLAW_HOME", str(tmp_path))
    manager = ScheduleManager(sdk_client=mock_sdk_client)
    await manager.register_crons([cron_skill])
    schedules_file = tmp_path / "config" / "schedules.yaml"
    assert schedules_file.exists()
    data = yaml.safe_load(schedules_file.read_text())
    assert "erp-invoices" in data
    assert data["erp-invoices"]["schedule"] == "0 0 28 * *"
    assert data["erp-invoices"]["cron_id"].startswith("cron_")


@pytest.mark.asyncio
async def test_register_cron_is_idempotent(tmp_path, monkeypatch, mock_sdk_client, cron_skill):
    monkeypatch.setenv("CLAUDECLAW_HOME", str(tmp_path))
    manager = ScheduleManager(sdk_client=mock_sdk_client)
    await manager.register_crons([cron_skill])
    await manager.register_crons([cron_skill])
    assert mock_sdk_client.beta.cron_create.await_count == 1


@pytest.mark.asyncio
async def test_register_cron_rereg_on_schedule_change(tmp_path, monkeypatch, mock_sdk_client, cron_skill):
    monkeypatch.setenv("CLAUDECLAW_HOME", str(tmp_path))
    manager = ScheduleManager(sdk_client=mock_sdk_client)
    await manager.register_crons([cron_skill])

    from dataclasses import replace
    updated_skill = replace(cron_skill, schedule="0 6 * * 1")
    manager2 = ScheduleManager(sdk_client=mock_sdk_client)
    await manager2.register_crons([updated_skill])

    mock_sdk_client.beta.cron_delete.assert_awaited_once()
    assert mock_sdk_client.beta.cron_create.await_count == 2


@pytest.mark.asyncio
async def test_on_demand_skills_are_skipped(tmp_path, monkeypatch, mock_sdk_client, sample_skill_md):
    monkeypatch.setenv("CLAUDECLAW_HOME", str(tmp_path))
    from claudeclaw.skills.loader import load_skill
    skill = load_skill(sample_skill_md)
    manager = ScheduleManager(sdk_client=mock_sdk_client)
    await manager.register_crons([skill])
    mock_sdk_client.beta.cron_create.assert_not_awaited()


@pytest.mark.asyncio
async def test_handle_cron_fired_returns_event(tmp_path, monkeypatch, mock_sdk_client, cron_skill):
    monkeypatch.setenv("CLAUDECLAW_HOME", str(tmp_path))
    manager = ScheduleManager(sdk_client=mock_sdk_client)
    await manager.register_crons([cron_skill])

    cron_id = (yaml.safe_load((tmp_path / "config" / "schedules.yaml").read_text())
               ["erp-invoices"]["cron_id"])
    tool_use_block = {
        "type": "tool_use",
        "name": "CronFired",
        "input": {"cron_id": cron_id, "fired_at": "2026-03-28T00:00:00Z"},
    }
    event = await manager.handle_tool_use_event(tool_use_block)
    assert event is not None
    assert event.source == "cron"
    assert event.skill_name == "erp-invoices"
    assert event.payload["fired_at"] == "2026-03-28T00:00:00Z"
    assert event.channel_reply_fn is None


@pytest.mark.asyncio
async def test_handle_unknown_tool_use_returns_none(tmp_path, monkeypatch, mock_sdk_client):
    monkeypatch.setenv("CLAUDECLAW_HOME", str(tmp_path))
    manager = ScheduleManager(sdk_client=mock_sdk_client)
    tool_use_block = {
        "type": "tool_use",
        "name": "SomeOtherTool",
        "input": {"foo": "bar"},
    }
    event = await manager.handle_tool_use_event(tool_use_block)
    assert event is None


@pytest.mark.asyncio
async def test_handle_cron_fired_unknown_cron_id_returns_none(tmp_path, monkeypatch, mock_sdk_client):
    monkeypatch.setenv("CLAUDECLAW_HOME", str(tmp_path))
    manager = ScheduleManager(sdk_client=mock_sdk_client)
    tool_use_block = {
        "type": "tool_use",
        "name": "CronFired",
        "input": {"cron_id": "cron_does_not_exist", "fired_at": "2026-03-28T00:00:00Z"},
    }
    event = await manager.handle_tool_use_event(tool_use_block)
    assert event is None


@pytest.mark.asyncio
async def test_register_webhook_calls_sdk(tmp_path, monkeypatch, mock_sdk_client, webhook_skill):
    monkeypatch.setenv("CLAUDECLAW_HOME", str(tmp_path))
    manager = ScheduleManager(sdk_client=mock_sdk_client)
    await manager.register_webhooks([webhook_skill])
    mock_sdk_client.beta.remote_trigger.assert_awaited_once()
    call_kwargs = mock_sdk_client.beta.remote_trigger.call_args
    assert call_kwargs.kwargs["trigger_id"] == "new-crm-lead"


@pytest.mark.asyncio
async def test_register_webhook_persists_to_yaml(tmp_path, monkeypatch, mock_sdk_client, webhook_skill):
    monkeypatch.setenv("CLAUDECLAW_HOME", str(tmp_path))
    manager = ScheduleManager(sdk_client=mock_sdk_client)
    await manager.register_webhooks([webhook_skill])
    triggers_file = tmp_path / "config" / "triggers.yaml"
    assert triggers_file.exists()
    data = yaml.safe_load(triggers_file.read_text())
    assert "new-crm-lead" in data
    assert data["new-crm-lead"]["skill_name"] == "crm-followup"
    assert "webhook_url" in data["new-crm-lead"]


@pytest.mark.asyncio
async def test_register_webhook_is_idempotent(tmp_path, monkeypatch, mock_sdk_client, webhook_skill):
    monkeypatch.setenv("CLAUDECLAW_HOME", str(tmp_path))
    manager = ScheduleManager(sdk_client=mock_sdk_client)
    await manager.register_webhooks([webhook_skill])
    await manager.register_webhooks([webhook_skill])
    assert mock_sdk_client.beta.remote_trigger.await_count == 1


@pytest.mark.asyncio
async def test_deregister_webhook_skill(tmp_path, monkeypatch, mock_sdk_client, webhook_skill):
    monkeypatch.setenv("CLAUDECLAW_HOME", str(tmp_path))
    manager = ScheduleManager(sdk_client=mock_sdk_client)
    await manager.register_webhooks([webhook_skill])
    await manager.deregister_skill("crm-followup")
    data = yaml.safe_load((tmp_path / "config" / "triggers.yaml").read_text()) or {}
    assert "new-crm-lead" not in data
