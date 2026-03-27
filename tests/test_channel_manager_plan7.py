# tests/test_channel_manager_plan7.py
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from claudeclaw.channels.channel_manager import ChannelManager


@pytest.fixture
def mock_store():
    store = MagicMock()
    store.get.return_value = "fake-value"
    return store


@pytest.fixture
def whatsapp_config():
    return {"channels": {"whatsapp": {"enabled": True}}}


@pytest.fixture
def slack_config():
    return {"channels": {"slack": {"enabled": True, "socket_mode": False}}}


@pytest.fixture
def web_config():
    return {"channels": {"web": {"enabled": True, "port": 3000}}}


@pytest.mark.asyncio
async def test_whatsapp_adapter_is_started(mock_store, whatsapp_config):
    manager = ChannelManager(config=whatsapp_config, credential_store=mock_store)
    with patch("claudeclaw.channels.channel_manager.WhatsAppAdapter") as MockAdapter:
        mock_instance = MagicMock()
        mock_instance.start = AsyncMock(return_value=None)
        MockAdapter.return_value = mock_instance
        with patch("claudeclaw.channels.channel_manager.start_server_background", new_callable=AsyncMock):
            with patch("claudeclaw.channels.channel_manager.register_whatsapp"):
                await manager.start_channel("whatsapp")
    MockAdapter.assert_called_once()


@pytest.mark.asyncio
async def test_slack_adapter_is_started(mock_store, slack_config):
    manager = ChannelManager(config=slack_config, credential_store=mock_store)
    with patch("claudeclaw.channels.channel_manager.SlackAdapter") as MockAdapter:
        mock_instance = MagicMock()
        mock_instance.start = AsyncMock(return_value=None)
        MockAdapter.return_value = mock_instance
        with patch("claudeclaw.channels.channel_manager.start_server_background", new_callable=AsyncMock):
            with patch("claudeclaw.channels.channel_manager.register_slack"):
                await manager.start_channel("slack")
    MockAdapter.assert_called_once()


@pytest.mark.asyncio
async def test_web_adapter_is_started(mock_store, web_config):
    manager = ChannelManager(config=web_config, credential_store=mock_store)
    with patch("claudeclaw.channels.channel_manager.WebAdapter") as MockAdapter:
        mock_instance = MagicMock()
        mock_instance.start = AsyncMock(return_value=None)
        mock_instance.register_routes = MagicMock()
        MockAdapter.return_value = mock_instance
        with patch("claudeclaw.channels.channel_manager.start_server_background", new_callable=AsyncMock):
            await manager.start_channel("web")
    MockAdapter.assert_called_once_with(port=3000)


def test_disabled_channel_not_started(mock_store):
    config = {"channels": {"whatsapp": {"enabled": False}}}
    manager = ChannelManager(config=config, credential_store=mock_store)
    assert not manager.is_enabled("whatsapp")


def test_missing_channel_not_started(mock_store):
    config = {"channels": {}}
    manager = ChannelManager(config=config, credential_store=mock_store)
    assert not manager.is_enabled("whatsapp")
    assert not manager.is_enabled("slack")
    assert not manager.is_enabled("web")
