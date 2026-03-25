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

    mock_channel = MagicMock()
    mock_channel.receive = AsyncMock(return_value=aiter([
        Event(text="echo hello", channel="cli")
    ]))
    mock_channel.send = AsyncMock()

    mock_registry = MagicMock()
    mock_registry.list_skills.return_value = [skill]

    mock_router = MagicMock()
    mock_router.route.return_value = skill

    mock_dispatcher = MagicMock()
    mock_dispatcher.dispatch.return_value = DispatchResult(
        text="hello", skill_name="echo-skill", stop_reason="end_turn"
    )

    orchestrator = Orchestrator(
        channel=mock_channel,
        registry=mock_registry,
        router=mock_router,
        dispatcher=mock_dispatcher,
    )

    await orchestrator.run_once()

    mock_dispatcher.dispatch.assert_called_once()
    mock_channel.send.assert_called_once()
    sent_response = mock_channel.send.call_args[0][0]
    assert "hello" in sent_response.text


@pytest.mark.asyncio
async def test_orchestrator_sends_fallback_on_no_skill_match():
    mock_channel = MagicMock()
    mock_channel.receive = AsyncMock(return_value=aiter([
        Event(text="something unknown", channel="cli")
    ]))
    mock_channel.send = AsyncMock()

    mock_registry = MagicMock()
    mock_registry.list_skills.return_value = []

    mock_router = MagicMock()
    mock_router.route.return_value = None

    mock_dispatcher = MagicMock()

    orchestrator = Orchestrator(
        channel=mock_channel,
        registry=mock_registry,
        router=mock_router,
        dispatcher=mock_dispatcher,
    )

    await orchestrator.run_once()

    mock_dispatcher.dispatch.assert_not_called()
    mock_channel.send.assert_called_once()
    sent = mock_channel.send.call_args[0][0]
    assert "no skill" in sent.text.lower() or "don't know" in sent.text.lower()


# Helper: async generator from list
async def aiter(items):
    for item in items:
        yield item
