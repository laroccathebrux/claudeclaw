import pytest
from claudeclaw.core.event import Event


class _FakeAdapter:
    pass


def test_event_carries_channel_adapter():
    adapter = _FakeAdapter()
    event = Event(
        text="hello",
        channel="telegram",
        channel_adapter=adapter,
        metadata={"chat_id": 42},
    )
    assert event.channel_adapter is adapter
    assert event.metadata["chat_id"] == 42


def test_event_channel_adapter_defaults_to_none():
    event = Event(text="hello", channel="cli")
    assert event.channel_adapter is None
