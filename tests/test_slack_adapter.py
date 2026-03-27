# tests/test_slack_adapter.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from claudeclaw.channels.slack_adapter import SlackAdapter
from claudeclaw.core.event import Event, Response


@pytest.fixture
def mock_store():
    store = MagicMock()
    store.get.side_effect = lambda key: {
        "slack-bot-token": "xoxb-test-token",
        "slack-signing-secret": "test-signing-secret",
    }.get(key)
    return store


@pytest.fixture
def adapter(mock_store):
    return SlackAdapter(credential_store=mock_store)


def test_adapter_channel_name(adapter):
    assert adapter.channel_name == "slack"


def test_build_event_from_slack_payload(adapter):
    """Slack message event payload must produce correct Event."""
    slack_event = {
        "type": "message",
        "user": "U01ABCDE123",
        "text": "Hello agent",
        "channel": "C01CHANNEL",
        "ts": "1712345678.000100",
    }
    body = {"event": slack_event, "team_id": "T01XYZ"}
    event = adapter._build_event(slack_event, body)
    assert event.channel == "slack"
    assert event.user_id == "U01ABCDE123"
    assert event.text == "Hello agent"
    assert event.raw["event"]["channel"] == "C01CHANNEL"


@pytest.mark.asyncio
async def test_send_calls_chat_post_message(adapter):
    """Outbound send must call slack client chat_postMessage."""
    fake_event = MagicMock()
    fake_event.raw = {
        "event": {"channel": "C01CHANNEL"},
        "team_id": "T01XYZ",
    }
    response = Response(
        channel="slack",
        user_id="U01ABCDE123",
        text="Here is your answer",
        event=fake_event,
    )

    mock_client = AsyncMock()
    adapter._slack_client = mock_client
    await adapter.send(response)

    mock_client.chat_postMessage.assert_called_once_with(
        channel="C01CHANNEL",
        text="Here is your answer",
    )


def test_message_from_bot_is_ignored(adapter):
    """Messages sent by the bot itself (bot_id present) must be dropped."""
    slack_event = {
        "type": "message",
        "user": "U01ABCDE123",
        "bot_id": "B01BOTID",
        "text": "I am the bot",
        "channel": "C01CHANNEL",
    }
    assert adapter._should_ignore(slack_event) is True


def test_regular_user_message_not_ignored(adapter):
    slack_event = {
        "type": "message",
        "user": "U01ABCDE123",
        "text": "Hello",
        "channel": "C01CHANNEL",
    }
    assert adapter._should_ignore(slack_event) is False
