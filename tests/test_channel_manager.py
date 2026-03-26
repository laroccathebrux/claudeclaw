import asyncio
import pytest
from claudeclaw.core.event import Event, Response
from claudeclaw.core.orchestrator import Orchestrator

# NOTE: This test lives here because Task 2 (Plan 2) will add real ChannelManager
# tests to this file. The orchestrator integration test below will grow into a
# full channel manager test suite in Task 2.


@pytest.mark.asyncio
async def test_orchestrator_processes_event_from_queue(mocker):
    queue = asyncio.Queue()
    mock_adapter = mocker.AsyncMock()
    mock_adapter.send = mocker.AsyncMock()

    event = Event(text="hello", channel="cli", channel_adapter=mock_adapter)
    await queue.put(event)

    registry = mocker.MagicMock()
    credential_store = mocker.MagicMock()
    orchestrator = Orchestrator(skill_registry=registry, credential_store=credential_store)
    mocker.patch.object(orchestrator, "_process", return_value=Response(text="ok", channel="cli"))

    await queue.put(None)  # sentinel
    await orchestrator.run(queue, stop_sentinel=True)

    mock_adapter.send.assert_awaited_once()
