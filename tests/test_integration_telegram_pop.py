# tests/test_integration_telegram_pop.py
"""
Integration test: simulates a Telegram message with a POP intent arriving
at the orchestrator via the channel manager queue.
"""
import asyncio
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from claudeclaw.core.event import Event, Response
from claudeclaw.core.orchestrator import Orchestrator
from claudeclaw.skills.registry import SkillRegistry

NATIVE_SKILLS_DIR = Path(__file__).parent.parent / "claudeclaw" / "skills" / "native"


@pytest.mark.asyncio
async def test_telegram_pop_intent_dispatches_pop_skill(tmp_path, mocker):
    """
    Simulate: Telegram user sends 'teach me to automate my monthly report'
    Expect: Orchestrator routes to pop skill and calls send() on the adapter.
    """
    registry = SkillRegistry(user_skills_dir=tmp_path, native_skills_dir=NATIVE_SKILLS_DIR)

    credential_store = mocker.MagicMock()
    orchestrator = Orchestrator(skill_registry=registry, credential_store=credential_store)

    # Track which skills were routed to, without making a real Claude SDK call
    dispatched_skills = []

    async def fake_process(event: Event) -> Response:
        from claudeclaw.core.router import route
        skill = route(event, registry)
        dispatched_skills.append(skill.name if skill else None)
        return Response(text="POP started", channel="telegram", chat_id=42)

    mocker.patch.object(orchestrator, "_process", side_effect=fake_process)

    mock_adapter = AsyncMock()
    event = Event(
        text="teach me to automate my monthly report",
        channel="telegram",
        channel_adapter=mock_adapter,
        metadata={"chat_id": 42},
    )

    queue = asyncio.Queue()
    await queue.put(event)
    await queue.put(None)  # sentinel

    await orchestrator.run(queue, stop_sentinel=True)

    assert dispatched_skills == ["pop"]
    mock_adapter.send.assert_awaited_once()
    call_args = mock_adapter.send.call_args[0][0]
    assert call_args.text == "POP started"


@pytest.mark.asyncio
async def test_channel_manager_creates_telegram_adapter(tmp_path, mocker):
    """ChannelManager with telegram in channels.yaml instantiates TelegramAdapter."""
    import yaml
    from claudeclaw.channels.manager import ChannelManager

    channels_file = tmp_path / "channels.yaml"
    channels_file.write_text(yaml.dump({
        "channels": [{"type": "telegram", "enabled": True}]
    }))

    credential_store = mocker.MagicMock()
    credential_store.get.return_value = "fake-token"

    manager = ChannelManager(config_path=channels_file, credential_store=credential_store)
    adapters = manager.load_channels()

    assert len(adapters) == 1
    from claudeclaw.channels.telegram_adapter import TelegramAdapter
    assert isinstance(adapters[0], TelegramAdapter)
