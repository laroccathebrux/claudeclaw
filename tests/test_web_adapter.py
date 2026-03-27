# tests/test_web_adapter.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from fastapi.testclient import TestClient
from starlette.testclient import WebSocketTestSession
from claudeclaw.channels.web_adapter import WebAdapter
from claudeclaw.core.event import Event, Response


@pytest.fixture
def adapter():
    return WebAdapter(port=3000)


def test_adapter_channel_name(adapter):
    assert adapter.channel_name == "web"


def test_serve_index_returns_html(adapter):
    from claudeclaw.channels.webhook_server import app
    from claudeclaw.channels.webhook_server import register_route
    adapter.register_routes()
    client = TestClient(app)
    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]


@pytest.mark.asyncio
async def test_websocket_message_builds_event(adapter):
    """Message received over WebSocket must produce a correct Event."""
    queue = adapter._queue

    # Simulate WebSocket message delivery
    conn_id = "test-conn-001"
    await adapter._handle_text_message("Hello agent", conn_id)

    event = queue.get_nowait()
    assert event.channel == "web"
    assert event.user_id == "localhost"
    assert event.text == "Hello agent"
    assert event.raw["connection_id"] == conn_id


@pytest.mark.asyncio
async def test_send_pushes_to_correct_connection(adapter):
    """send() must write to the WebSocket identified by the originating event."""
    mock_ws = AsyncMock()
    conn_id = "conn-abc"
    adapter._connections[conn_id] = mock_ws

    fake_event = MagicMock()
    fake_event.raw = {"connection_id": conn_id}

    response = Response(
        channel="web",
        user_id="localhost",
        text="Here is your answer",
        event=fake_event,
    )
    await adapter.send(response)
    mock_ws.send_text.assert_called_once_with("Here is your answer")


@pytest.mark.asyncio
async def test_disconnected_client_cleaned_up(adapter):
    """Closed WebSocket connections must be removed from _connections."""
    conn_id = "conn-gone"
    adapter._connections[conn_id] = AsyncMock()
    adapter._remove_connection(conn_id)
    assert conn_id not in adapter._connections
