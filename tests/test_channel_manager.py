import asyncio
import pytest
import yaml
from pathlib import Path
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


from claudeclaw.channels.manager import ChannelManager


def _write_channels_yaml(path: Path, channels: list[dict]):
    config = {"channels": channels}
    path.write_text(yaml.dump(config))


@pytest.mark.asyncio
async def test_manager_load_channels_reads_yaml(tmp_path, mocker):
    channels_file = tmp_path / "channels.yaml"
    _write_channels_yaml(channels_file, [{"type": "cli", "enabled": True}])
    store = mocker.MagicMock()
    manager = ChannelManager(config_path=channels_file, credential_store=store)
    adapters = manager.load_channels()
    assert len(adapters) == 1


@pytest.mark.asyncio
async def test_manager_skips_disabled_channels(tmp_path, mocker):
    channels_file = tmp_path / "channels.yaml"
    _write_channels_yaml(channels_file, [
        {"type": "cli", "enabled": True},
        {"type": "telegram", "enabled": False},
    ])
    store = mocker.MagicMock()
    manager = ChannelManager(config_path=channels_file, credential_store=store)
    adapters = manager.load_channels()
    assert len(adapters) == 1


@pytest.mark.asyncio
async def test_manager_start_all_feeds_queue(tmp_path, mocker):
    channels_file = tmp_path / "channels.yaml"
    _write_channels_yaml(channels_file, [{"type": "cli", "enabled": True}])

    fake_event = mocker.MagicMock()
    mock_adapter = mocker.AsyncMock()

    async def fake_receive():
        yield fake_event

    mock_adapter.receive = fake_receive
    mocker.patch("claudeclaw.channels.manager.ChannelManager.load_channels",
                 return_value=[mock_adapter])

    store = mocker.MagicMock()
    manager = ChannelManager(config_path=channels_file, credential_store=store)
    queue = asyncio.Queue()

    tasks = await manager.start_all(queue)
    await asyncio.sleep(0.05)
    for t in tasks:
        t.cancel()

    assert not queue.empty()
    assert await queue.get() is fake_event
