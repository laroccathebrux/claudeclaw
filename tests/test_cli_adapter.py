import asyncio
import pytest
from unittest.mock import patch
from claudeclaw.channels.cli_adapter import CliAdapter
from claudeclaw.core.event import Response, Event


@pytest.mark.asyncio
async def test_receive_yields_event_from_stdin():
    adapter = CliAdapter()
    inputs = iter(["hello world", ""])

    with patch("builtins.input", side_effect=inputs):
        events = []
        async for event in adapter.receive():
            events.append(event)
            break  # take just one

    assert len(events) == 1
    assert events[0].text == "hello world"
    assert events[0].channel == "cli"


@pytest.mark.asyncio
async def test_send_prints_response(capsys):
    adapter = CliAdapter()
    event = Event(text="hi", channel="cli")
    response = Response(text="Hello back!", event=event)
    await adapter.send(response)
    captured = capsys.readouterr()
    assert "Hello back!" in captured.out
