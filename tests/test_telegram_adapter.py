# tests/test_telegram_adapter.py
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock
from claudeclaw.channels.telegram_adapter import TelegramAdapter
from claudeclaw.core.event import Event, Response


@pytest.fixture
def adapter():
    return TelegramAdapter(token="fake-token-123")


def test_adapter_instantiates_with_token(adapter):
    assert adapter._token == "fake-token-123"


async def test_receive_yields_event_from_message(adapter):
    """Simulate PTB calling the message handler; verify Event is yielded."""
    fake_message = MagicMock()
    fake_message.text = "hello bot"
    fake_message.chat_id = 99
    fake_message.from_user.id = 7

    # Seed the internal queue directly (bypasses PTB network layer)
    await adapter._internal_queue.put(fake_message)

    events = []
    async for event in adapter.receive():
        events.append(event)
        break  # take only the first one

    assert len(events) == 1
    assert events[0].text == "hello bot"
    assert events[0].channel == "telegram"
    assert events[0].metadata["chat_id"] == 99


async def test_send_calls_bot_send_message(adapter):
    mock_bot = AsyncMock()
    adapter._bot = mock_bot

    response = Response(text="reply text", channel="telegram", user_id="99")
    await adapter.send(response)

    mock_bot.send_message.assert_awaited_once_with(chat_id="99", text="reply text")


async def test_on_message_puts_to_internal_queue(adapter):
    """Verify the PTB handler callback puts the message onto the internal queue."""
    fake_update = MagicMock()
    fake_update.message.text = "test"
    fake_update.message.chat_id = 1
    fake_update.message.from_user.id = 2

    await adapter._on_message(fake_update, context=MagicMock())
    assert not adapter._internal_queue.empty()
    msg = await adapter._internal_queue.get()
    assert msg is fake_update.message
