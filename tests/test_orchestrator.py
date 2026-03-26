import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from claudeclaw.core.orchestrator import Orchestrator
from claudeclaw.core.event import Event, Response
from claudeclaw.skills.loader import SkillManifest


@pytest.fixture
def skill():
    return SkillManifest(
        name="echo-skill",
        description="Echoes input back",
        trigger="on-demand",
        autonomy="autonomous",
        shell_policy="none",
        body="Echo the user's message.",
    )


@pytest.mark.asyncio
async def test_orchestrator_routes_and_dispatches(skill):
    from claudeclaw.subagent.dispatch import DispatchResult

    mock_adapter = AsyncMock()
    mock_adapter.send = AsyncMock()

    mock_registry = MagicMock()
    mock_registry.list_skills.return_value = [skill]

    mock_router = MagicMock()
    mock_router.route.return_value = skill

    mock_dispatcher = MagicMock()
    mock_dispatcher.dispatch.return_value = DispatchResult(
        text="hello", skill_name="echo-skill", stop_reason="end_turn"
    )

    event = Event(text="echo hello", channel="cli", channel_adapter=mock_adapter)

    with patch("claudeclaw.core.orchestrator.Router", return_value=mock_router), \
         patch("claudeclaw.core.orchestrator.SubagentDispatcher", return_value=mock_dispatcher):
        orchestrator = Orchestrator(skill_registry=mock_registry, credential_store=MagicMock())
        queue = asyncio.Queue()
        await queue.put(event)
        await queue.put(None)  # sentinel
        await orchestrator.run(queue, stop_sentinel=True)

    mock_dispatcher.dispatch.assert_called_once()
    mock_adapter.send.assert_awaited_once()
    sent_response = mock_adapter.send.call_args[0][0]
    assert "hello" in sent_response.text


@pytest.mark.asyncio
async def test_orchestrator_sends_fallback_on_no_skill_match():
    mock_adapter = AsyncMock()
    mock_adapter.send = AsyncMock()

    mock_registry = MagicMock()
    mock_registry.list_skills.return_value = []

    mock_router = MagicMock()
    mock_router.route.return_value = None

    mock_dispatcher = MagicMock()

    event = Event(text="something unknown", channel="cli", channel_adapter=mock_adapter)

    with patch("claudeclaw.core.orchestrator.Router", return_value=mock_router), \
         patch("claudeclaw.core.orchestrator.SubagentDispatcher", return_value=mock_dispatcher):
        orchestrator = Orchestrator(skill_registry=mock_registry, credential_store=MagicMock())
        queue = asyncio.Queue()
        await queue.put(event)
        await queue.put(None)  # sentinel
        await orchestrator.run(queue, stop_sentinel=True)

    mock_dispatcher.dispatch.assert_not_called()
    mock_adapter.send.assert_awaited_once()
    sent = mock_adapter.send.call_args[0][0]
    assert "no skill" in sent.text.lower() or "don't know" in sent.text.lower()
