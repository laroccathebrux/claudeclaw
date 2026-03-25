# ClaudeClaw — Plan 7: Additional Channels (WhatsApp, Slack, Web UI)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add three production-ready channel adapters — WhatsApp (Twilio), Slack (slack-bolt), and a local Web UI (FastAPI + WebSocket) — wired into the existing channel manager from Plan 2 and orchestrator from Plan 1.

**Architecture:** A shared FastAPI webhook server (`webhook_server.py`) hosts all HTTP-based adapters. `WhatsAppAdapter` handles Twilio inbound webhooks and REST outbound. `SlackAdapter` uses slack-bolt with Socket Mode for development. `WebAdapter` serves a minimal chat UI over WebSocket at `localhost:3000`. All three implement the `ChannelAdapter` ABC from Plan 2 and are managed as asyncio tasks by the channel manager.

**Tech Stack:** Python 3.11+, `twilio>=9.0`, `slack-bolt>=1.18`, `fastapi>=0.110`, `uvicorn>=0.29`, `websockets>=12.0`, `httpx>=0.27` (already present), `pytest`, `pytest-asyncio`, `pytest-mock`

**Spec reference:** `docs/superpowers/specs/2026-03-25-plan-7-channels-spec.md`

---

## File Map

```
claudeclaw/
├── claudeclaw/
│   └── channels/
│       ├── webhook_server.py           ← shared FastAPI app, route registration, uvicorn runner
│       ├── whatsapp_adapter.py         ← Twilio inbound webhook + REST outbound
│       ├── slack_adapter.py            ← slack-bolt Socket Mode + Events API
│       ├── web_adapter.py              ← WebSocket chat + static file serving
│       ├── channel_manager.py          ← UPDATED: register all three new adapters
│       └── static/
│           └── index.html              ← minimal single-file chat frontend
└── tests/
    ├── test_webhook_server.py
    ├── test_whatsapp_adapter.py
    ├── test_slack_adapter.py
    ├── test_web_adapter.py
    └── test_channel_manager_plan7.py
```

---

## Task 1: Shared Webhook Server

**Files:**
- Create: `claudeclaw/channels/webhook_server.py`
- Create: `tests/test_webhook_server.py`

- [ ] **Step 1: Add new dependencies to pyproject.toml**

Open `pyproject.toml` and add to the `dependencies` list:

```toml
"twilio>=9.0",
"slack-bolt>=1.18",
"fastapi>=0.110",
"uvicorn[standard]>=0.29",
"websockets>=12.0",
```

Then install:

```bash
pip install -e ".[dev]"
```

- [ ] **Step 2: Write the failing test**

```python
# tests/test_webhook_server.py
import pytest
from fastapi.testclient import TestClient
from claudeclaw.channels.webhook_server import app, register_route


def test_app_is_fastapi_instance():
    from fastapi import FastAPI
    assert isinstance(app, FastAPI)


def test_register_route_adds_endpoint():
    from fastapi import FastAPI
    import httpx

    async def dummy_handler():
        return {"ok": True}

    register_route("GET", "/test-register", dummy_handler)
    client = TestClient(app)
    resp = client.get("/test-register")
    assert resp.status_code == 200


def test_health_endpoint_returns_ok():
    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
```

- [ ] **Step 3: Run test to verify it fails**

```bash
pytest tests/test_webhook_server.py -v
```

Expected: `ImportError` — module does not exist yet.

- [ ] **Step 4: Implement the shared webhook server**

```python
# claudeclaw/channels/webhook_server.py
from __future__ import annotations

import asyncio
import logging
from typing import Callable

import uvicorn
from fastapi import FastAPI
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

app = FastAPI(title="ClaudeClaw Webhook Server")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


def register_route(method: str, path: str, handler: Callable, **kwargs) -> None:
    """Register a route on the shared FastAPI app at runtime."""
    app.add_api_route(path, handler, methods=[method.upper()], **kwargs)


def register_websocket_route(path: str, handler: Callable) -> None:
    """Register a WebSocket route on the shared FastAPI app."""
    app.add_websocket_route(path, handler)


_server_task: asyncio.Task | None = None


async def start_server(host: str = "0.0.0.0", port: int = 8080) -> None:
    """Start the uvicorn server. Call after all routes have been registered."""
    global _server_task
    config = uvicorn.Config(app, host=host, port=port, log_level="warning")
    server = uvicorn.Server(config)
    logger.info(f"Webhook server starting on {host}:{port}")
    await server.serve()


async def start_server_background(host: str = "0.0.0.0", port: int = 8080) -> asyncio.Task:
    """Launch the webhook server as a background asyncio task."""
    global _server_task
    _server_task = asyncio.create_task(start_server(host=host, port=port))
    return _server_task
```

- [ ] **Step 5: Run test to verify it passes**

```bash
pytest tests/test_webhook_server.py -v
```

Expected: 3 PASSED.

- [ ] **Step 6: Commit**

```bash
git add claudeclaw/channels/webhook_server.py tests/test_webhook_server.py pyproject.toml
git commit -m "feat: shared FastAPI webhook server with dynamic route registration"
```

---

## Task 2: WhatsApp Adapter

**Files:**
- Create: `claudeclaw/channels/whatsapp_adapter.py`
- Create: `tests/test_whatsapp_adapter.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_whatsapp_adapter.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from claudeclaw.channels.whatsapp_adapter import WhatsAppAdapter
from claudeclaw.core.event import Event, Response


@pytest.fixture
def mock_store():
    store = MagicMock()
    store.get.side_effect = lambda key: {
        "twilio-account-sid": "ACtest123",
        "twilio-auth-token": "authtoken456",
        "twilio-whatsapp-from": "+14155238886",
    }.get(key)
    return store


@pytest.fixture
def adapter(mock_store):
    return WhatsAppAdapter(credential_store=mock_store)


def test_adapter_channel_name(adapter):
    assert adapter.channel_name == "whatsapp"


@pytest.mark.asyncio
async def test_inbound_webhook_builds_event(adapter):
    """Simulate a Twilio inbound POST payload and verify Event construction."""
    form_data = {
        "From": "whatsapp:+15551234567",
        "To": "whatsapp:+14155238886",
        "Body": "Hello agent",
        "MessageSid": "SMxxx",
    }
    event = await adapter._parse_twilio_payload(form_data)
    assert event.channel == "whatsapp"
    assert event.user_id == "whatsapp:+15551234567"
    assert event.text == "Hello agent"
    assert event.raw["MessageSid"] == "SMxxx"


@pytest.mark.asyncio
async def test_invalid_signature_raises(adapter):
    """Requests with invalid Twilio signatures must be rejected."""
    with patch.object(adapter, "_validate_signature", return_value=False):
        with pytest.raises(PermissionError, match="Invalid Twilio signature"):
            await adapter.handle_inbound_raw(
                form_data={"From": "whatsapp:+15551234567", "Body": "hi"},
                signature="bad",
                url="https://example.com/whatsapp/inbound",
            )


@pytest.mark.asyncio
async def test_send_calls_twilio_api(adapter):
    """Outbound send must POST to Twilio Messages endpoint."""
    response = Response(
        channel="whatsapp",
        user_id="whatsapp:+15551234567",
        text="Hello back",
        event=MagicMock(),
    )
    with patch("claudeclaw.channels.whatsapp_adapter.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value.__aenter__.return_value = mock_client
        mock_client.post.return_value = MagicMock(status_code=201)
        await adapter.send(response)

    mock_client.post.assert_called_once()
    call_kwargs = mock_client.post.call_args
    assert "ACtest123" in call_kwargs[0][0]  # URL contains account SID
    assert call_kwargs[1]["data"]["To"] == "whatsapp:+15551234567"
    assert call_kwargs[1]["data"]["Body"] == "Hello back"


@pytest.mark.asyncio
async def test_send_uses_correct_from_number(adapter):
    response = Response(
        channel="whatsapp",
        user_id="whatsapp:+15551234567",
        text="Hi",
        event=MagicMock(),
    )
    with patch("claudeclaw.channels.whatsapp_adapter.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value.__aenter__.return_value = mock_client
        mock_client.post.return_value = MagicMock(status_code=201)
        await adapter.send(response)

    data = mock_client.post.call_args[1]["data"]
    assert data["From"] == "whatsapp:+14155238886"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_whatsapp_adapter.py -v
```

Expected: `ImportError` — module does not exist yet.

- [ ] **Step 3: Implement the WhatsApp adapter**

```python
# claudeclaw/channels/whatsapp_adapter.py
from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx
from fastapi import Request, Response as FastAPIResponse
from twilio.request_validator import RequestValidator

from claudeclaw.channels.base import ChannelAdapter
from claudeclaw.core.event import Event, Response

logger = logging.getLogger(__name__)

_TWILIO_MESSAGES_URL = (
    "https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Messages.json"
)


class WhatsAppAdapter(ChannelAdapter):
    """Channel adapter for WhatsApp via Twilio."""

    channel_name = "whatsapp"

    def __init__(self, credential_store, event_queue: asyncio.Queue | None = None):
        self._store = credential_store
        self._queue: asyncio.Queue[Event] = event_queue or asyncio.Queue()

    # ------------------------------------------------------------------
    # ChannelAdapter ABC
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """WhatsApp is inbound-only via webhook; nothing to start here."""
        logger.info("WhatsApp adapter ready (webhook-driven)")
        await asyncio.Event().wait()  # keep task alive

    async def send(self, response: Response) -> None:
        account_sid = self._store.get("twilio-account-sid")
        auth_token = self._store.get("twilio-auth-token")
        from_number = self._store.get("twilio-whatsapp-from")

        url = _TWILIO_MESSAGES_URL.format(account_sid=account_sid)
        payload = {
            "From": f"whatsapp:{from_number}",
            "To": response.user_id,
            "Body": response.text,
        }

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                url,
                data=payload,
                auth=(account_sid, auth_token),
            )
            if resp.status_code >= 400:
                logger.error(
                    "Twilio send failed: %s %s", resp.status_code, resp.text
                )

    # ------------------------------------------------------------------
    # Webhook handler (registered on shared server)
    # ------------------------------------------------------------------

    async def handle_inbound(self, request: Request) -> FastAPIResponse:
        """FastAPI endpoint for POST /whatsapp/inbound."""
        form_data = dict(await request.form())
        signature = request.headers.get("X-Twilio-Signature", "")
        url = str(request.url)

        if not self._validate_signature(signature, url, form_data):
            logger.warning("Invalid Twilio signature from %s", request.client)
            return FastAPIResponse(content="Forbidden", status_code=403)

        event = await self._parse_twilio_payload(form_data)
        await self._queue.put(event)
        # Return empty TwiML — response sent asynchronously
        return FastAPIResponse(
            content='<?xml version="1.0"?><Response></Response>',
            media_type="text/xml",
            status_code=200,
        )

    async def handle_inbound_raw(
        self,
        form_data: dict[str, str],
        signature: str,
        url: str,
    ) -> Event:
        """Testable version: validate + parse without HTTP request object."""
        if not self._validate_signature(signature, url, form_data):
            raise PermissionError("Invalid Twilio signature")
        return await self._parse_twilio_payload(form_data)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _validate_signature(self, signature: str, url: str, params: dict) -> bool:
        auth_token = self._store.get("twilio-auth-token")
        if not auth_token:
            return False
        validator = RequestValidator(auth_token)
        return validator.validate(url, params, signature)

    async def _parse_twilio_payload(self, form_data: dict[str, Any]) -> Event:
        return Event(
            channel=self.channel_name,
            user_id=form_data["From"],
            text=form_data.get("Body", ""),
            raw=form_data,
        )
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_whatsapp_adapter.py -v
```

Expected: 5 PASSED.

- [ ] **Step 5: Commit**

```bash
git add claudeclaw/channels/whatsapp_adapter.py tests/test_whatsapp_adapter.py
git commit -m "feat: WhatsApp channel adapter via Twilio with signature validation"
```

---

## Task 3: Slack Adapter

**Files:**
- Create: `claudeclaw/channels/slack_adapter.py`
- Create: `tests/test_slack_adapter.py`

- [ ] **Step 1: Write the failing tests**

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_slack_adapter.py -v
```

Expected: `ImportError` — module does not exist yet.

- [ ] **Step 3: Implement the Slack adapter**

```python
# claudeclaw/channels/slack_adapter.py
from __future__ import annotations

import asyncio
import logging
from typing import Any

from slack_bolt.async_app import AsyncApp
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler

from claudeclaw.channels.base import ChannelAdapter
from claudeclaw.core.event import Event, Response

logger = logging.getLogger(__name__)


class SlackAdapter(ChannelAdapter):
    """Channel adapter for Slack via slack-bolt (Socket Mode or Events API)."""

    channel_name = "slack"

    def __init__(
        self,
        credential_store,
        event_queue: asyncio.Queue | None = None,
        socket_mode: bool = True,
        app_token: str | None = None,
    ):
        self._store = credential_store
        self._queue: asyncio.Queue[Event] = event_queue or asyncio.Queue()
        self._socket_mode = socket_mode
        self._app_token = app_token
        self._slack_client = None
        self._app: AsyncApp | None = None

    # ------------------------------------------------------------------
    # ChannelAdapter ABC
    # ------------------------------------------------------------------

    async def start(self) -> None:
        bot_token = self._store.get("slack-bot-token")
        signing_secret = self._store.get("slack-signing-secret")

        self._app = AsyncApp(token=bot_token, signing_secret=signing_secret)
        self._slack_client = self._app.client

        @self._app.message("")
        async def on_message(event, body, say):  # noqa: F841
            if self._should_ignore(event):
                return
            normalized = self._build_event(event, body)
            await self._queue.put(normalized)

        if self._socket_mode:
            app_token = self._app_token or self._store.get("slack-app-token")
            handler = AsyncSocketModeHandler(self._app, app_token)
            logger.info("Slack adapter starting in Socket Mode")
            await handler.start_async()
        else:
            logger.info("Slack adapter ready (webhook mode — register /slack/events route)")
            await asyncio.Event().wait()

    async def send(self, response: Response) -> None:
        channel_id = response.event.raw["event"]["channel"]
        await self._slack_client.chat_postMessage(
            channel=channel_id,
            text=response.text,
        )

    # ------------------------------------------------------------------
    # Webhook handler (production Events API mode)
    # ------------------------------------------------------------------

    async def handle_events(self, request):
        """FastAPI endpoint for POST /slack/events (production webhook mode)."""
        from slack_bolt.adapter.fastapi.async_handler import AsyncSlackRequestHandler
        handler = AsyncSlackRequestHandler(self._app)
        return await handler.handle(request)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _build_event(self, slack_event: dict[str, Any], body: dict[str, Any]) -> Event:
        return Event(
            channel=self.channel_name,
            user_id=slack_event.get("user", "unknown"),
            text=slack_event.get("text", ""),
            raw=body,
        )

    def _should_ignore(self, slack_event: dict[str, Any]) -> bool:
        """Ignore messages from bots (including this bot's own messages)."""
        return "bot_id" in slack_event
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_slack_adapter.py -v
```

Expected: 5 PASSED.

- [ ] **Step 5: Commit**

```bash
git add claudeclaw/channels/slack_adapter.py tests/test_slack_adapter.py
git commit -m "feat: Slack channel adapter via slack-bolt with Socket Mode support"
```

---

## Task 4: Web UI Adapter

**Files:**
- Create: `claudeclaw/channels/web_adapter.py`
- Create: `claudeclaw/channels/static/index.html`
- Create: `tests/test_web_adapter.py`

- [ ] **Step 1: Write the failing tests**

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_web_adapter.py -v
```

Expected: `ImportError` — module does not exist yet.

- [ ] **Step 3: Implement the Web UI adapter**

```python
# claudeclaw/channels/web_adapter.py
from __future__ import annotations

import asyncio
import logging
import uuid
from pathlib import Path

from fastapi import WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from claudeclaw.channels.base import ChannelAdapter
from claudeclaw.core.event import Event, Response

logger = logging.getLogger(__name__)

_STATIC_DIR = Path(__file__).parent / "static"


class WebAdapter(ChannelAdapter):
    """Channel adapter for the local Web UI (FastAPI + WebSocket)."""

    channel_name = "web"

    def __init__(self, port: int = 3000, event_queue: asyncio.Queue | None = None):
        self._port = port
        self._queue: asyncio.Queue[Event] = event_queue or asyncio.Queue()
        self._connections: dict[str, WebSocket] = {}

    # ------------------------------------------------------------------
    # ChannelAdapter ABC
    # ------------------------------------------------------------------

    async def start(self) -> None:
        self.register_routes()
        logger.info("Web UI adapter ready at http://localhost:%d", self._port)
        await asyncio.Event().wait()  # routes registered; server managed externally

    async def send(self, response: Response) -> None:
        conn_id = response.event.raw.get("connection_id")
        ws = self._connections.get(conn_id)
        if ws is None:
            logger.warning("WebSocket connection %s not found for send", conn_id)
            return
        await ws.send_text(response.text)

    # ------------------------------------------------------------------
    # Route registration
    # ------------------------------------------------------------------

    def register_routes(self) -> None:
        from claudeclaw.channels.webhook_server import (
            register_route,
            register_websocket_route,
        )

        register_route("GET", "/", self._serve_index)
        register_websocket_route("/ws", self._websocket_endpoint)

    # ------------------------------------------------------------------
    # Handlers
    # ------------------------------------------------------------------

    async def _serve_index(self) -> HTMLResponse:
        index_path = _STATIC_DIR / "index.html"
        content = index_path.read_text(encoding="utf-8")
        return HTMLResponse(content=content)

    async def _websocket_endpoint(self, websocket: WebSocket) -> None:
        conn_id = str(uuid.uuid4())
        await websocket.accept()
        self._connections[conn_id] = websocket
        logger.info("WebSocket client connected: %s", conn_id)
        try:
            while True:
                data = await websocket.receive_text()
                await self._handle_text_message(data, conn_id)
        except WebSocketDisconnect:
            self._remove_connection(conn_id)
            logger.info("WebSocket client disconnected: %s", conn_id)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _handle_text_message(self, text: str, conn_id: str) -> None:
        event = Event(
            channel=self.channel_name,
            user_id="localhost",
            text=text,
            raw={"connection_id": conn_id},
        )
        await self._queue.put(event)

    def _remove_connection(self, conn_id: str) -> None:
        self._connections.pop(conn_id, None)
```

- [ ] **Step 4: Create the static HTML frontend**

```bash
mkdir -p claudeclaw/channels/static
```

Write `claudeclaw/channels/static/index.html`:

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>ClaudeClaw</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: system-ui, sans-serif; background: #f5f5f5; display: flex; flex-direction: column; height: 100vh; }
    #chat { flex: 1; overflow-y: auto; padding: 16px; display: flex; flex-direction: column; gap: 8px; }
    .msg { max-width: 70%; padding: 10px 14px; border-radius: 12px; line-height: 1.4; word-break: break-word; }
    .msg.user { background: #0070f3; color: white; align-self: flex-end; border-bottom-right-radius: 4px; }
    .msg.agent { background: white; color: #111; align-self: flex-start; border-bottom-left-radius: 4px; box-shadow: 0 1px 3px rgba(0,0,0,.1); }
    #form { display: flex; padding: 12px; gap: 8px; background: white; border-top: 1px solid #e0e0e0; }
    #input { flex: 1; padding: 10px 14px; border: 1px solid #ccc; border-radius: 8px; font-size: 14px; outline: none; }
    #input:focus { border-color: #0070f3; }
    #send { padding: 10px 20px; background: #0070f3; color: white; border: none; border-radius: 8px; cursor: pointer; font-size: 14px; }
    #send:hover { background: #005ad8; }
    #status { font-size: 11px; color: #888; padding: 4px 16px; background: white; }
  </style>
</head>
<body>
  <div id="chat"></div>
  <div id="status">Connecting...</div>
  <form id="form">
    <input id="input" type="text" placeholder="Message ClaudeClaw..." autocomplete="off" />
    <button id="send" type="submit">Send</button>
  </form>
  <script>
    const chat = document.getElementById('chat');
    const input = document.getElementById('input');
    const status = document.getElementById('status');
    let ws;

    function addMessage(text, role) {
      const div = document.createElement('div');
      div.className = 'msg ' + role;
      div.textContent = text;
      chat.appendChild(div);
      chat.scrollTop = chat.scrollHeight;
    }

    function connect() {
      ws = new WebSocket('ws://' + location.host + '/ws');
      ws.onopen = () => { status.textContent = 'Connected'; };
      ws.onmessage = (e) => { addMessage(e.data, 'agent'); };
      ws.onclose = () => {
        status.textContent = 'Disconnected — reconnecting...';
        setTimeout(connect, 2000);
      };
      ws.onerror = () => ws.close();
    }

    document.getElementById('form').addEventListener('submit', (e) => {
      e.preventDefault();
      const text = input.value.trim();
      if (!text || ws.readyState !== WebSocket.OPEN) return;
      addMessage(text, 'user');
      ws.send(text);
      input.value = '';
    });

    connect();
  </script>
</body>
</html>
```

- [ ] **Step 5: Run test to verify it passes**

```bash
pytest tests/test_web_adapter.py -v
```

Expected: 5 PASSED.

- [ ] **Step 6: Commit**

```bash
git add claudeclaw/channels/web_adapter.py claudeclaw/channels/static/index.html tests/test_web_adapter.py
git commit -m "feat: Web UI channel adapter with WebSocket and minimal chat frontend"
```

---

## Task 5: `channel add` CLI Commands

**Files:**
- Update: `claudeclaw/cli.py` (add `channel add whatsapp`, `channel add slack`, `channel add web`)
- Create: `tests/test_channel_cli_plan7.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_channel_cli_plan7.py
import pytest
from click.testing import CliRunner
from unittest.mock import patch, MagicMock
from claudeclaw.cli import main


@pytest.fixture
def runner():
    return CliRunner()


def test_channel_add_whatsapp_stores_credentials(runner, tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDECLAW_HOME", str(tmp_path))
    with patch("claudeclaw.cli.CredentialStore") as MockStore:
        mock_store = MagicMock()
        MockStore.return_value = mock_store
        result = runner.invoke(main, [
            "channel", "add", "whatsapp",
            "--account-sid", "ACtest",
            "--auth-token", "token123",
            "--from", "+14155238886",
        ])
    assert result.exit_code == 0
    calls = {c[0][0]: c[0][1] for c in mock_store.set.call_args_list}
    assert calls["twilio-account-sid"] == "ACtest"
    assert calls["twilio-auth-token"] == "token123"
    assert calls["twilio-whatsapp-from"] == "+14155238886"


def test_channel_add_slack_stores_credentials(runner, tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDECLAW_HOME", str(tmp_path))
    with patch("claudeclaw.cli.CredentialStore") as MockStore:
        mock_store = MagicMock()
        MockStore.return_value = mock_store
        result = runner.invoke(main, [
            "channel", "add", "slack",
            "--token", "xoxb-test",
            "--signing-secret", "secret123",
        ])
    assert result.exit_code == 0
    calls = {c[0][0]: c[0][1] for c in mock_store.set.call_args_list}
    assert calls["slack-bot-token"] == "xoxb-test"
    assert calls["slack-signing-secret"] == "secret123"


def test_channel_add_web_writes_config(runner, tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDECLAW_HOME", str(tmp_path))
    result = runner.invoke(main, ["channel", "add", "web", "--port", "3000"])
    assert result.exit_code == 0
    channels_yaml = tmp_path / "config" / "channels.yaml"
    assert channels_yaml.exists()
    import yaml
    data = yaml.safe_load(channels_yaml.read_text())
    assert data["channels"]["web"]["enabled"] is True
    assert data["channels"]["web"]["port"] == 3000


def test_channel_add_web_default_port(runner, tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDECLAW_HOME", str(tmp_path))
    result = runner.invoke(main, ["channel", "add", "web"])
    assert result.exit_code == 0
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_channel_cli_plan7.py -v
```

Expected: failures due to missing CLI subcommands.

- [ ] **Step 3: Add channel subcommands to cli.py**

In `claudeclaw/cli.py`, locate the `channel` Click group (created in Plan 2) and add three new subcommands:

```python
@channel.command("add")
@click.argument("channel_type", type=click.Choice(["telegram", "whatsapp", "slack", "web"]))
@click.option("--token", default=None, help="Bot token (Telegram/Slack)")
@click.option("--account-sid", default=None, help="Twilio Account SID (WhatsApp)")
@click.option("--auth-token", default=None, help="Twilio Auth Token (WhatsApp)")
@click.option("--from", "from_number", default=None, help="Twilio WhatsApp sender number")
@click.option("--signing-secret", default=None, help="Slack signing secret")
@click.option("--port", default=3000, type=int, help="Web UI port (default: 3000)")
def channel_add(channel_type, token, account_sid, auth_token, from_number, signing_secret, port):
    """Configure and enable a channel adapter."""
    from claudeclaw.auth.keyring import CredentialStore
    from claudeclaw.config.settings import Settings
    import yaml

    settings = Settings()
    store = CredentialStore()

    channels_file = settings.config_dir / "channels.yaml"
    config = {}
    if channels_file.exists():
        config = yaml.safe_load(channels_file.read_text()) or {}
    config.setdefault("channels", {})

    if channel_type == "whatsapp":
        if not all([account_sid, auth_token, from_number]):
            raise click.UsageError("--account-sid, --auth-token, and --from are required for WhatsApp")
        store.set("twilio-account-sid", account_sid)
        store.set("twilio-auth-token", auth_token)
        store.set("twilio-whatsapp-from", from_number)
        config["channels"]["whatsapp"] = {"enabled": True}
        click.echo("WhatsApp channel configured. Point Twilio webhook to POST /whatsapp/inbound")

    elif channel_type == "slack":
        if not all([token, signing_secret]):
            raise click.UsageError("--token and --signing-secret are required for Slack")
        store.set("slack-bot-token", token)
        store.set("slack-signing-secret", signing_secret)
        config["channels"]["slack"] = {"enabled": True, "socket_mode": True}
        click.echo("Slack channel configured.")

    elif channel_type == "web":
        config["channels"]["web"] = {"enabled": True, "port": port}
        click.echo(f"Web UI channel configured. Will serve at http://localhost:{port}")

    elif channel_type == "telegram":
        if not token:
            raise click.UsageError("--token is required for Telegram")
        store.set("telegram-bot-token", token)
        config["channels"]["telegram"] = {"enabled": True}
        click.echo("Telegram channel configured.")

    channels_file.write_text(yaml.dump(config))
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_channel_cli_plan7.py -v
```

Expected: 4 PASSED.

- [ ] **Step 5: Commit**

```bash
git add claudeclaw/cli.py tests/test_channel_cli_plan7.py
git commit -m "feat: channel add CLI commands for whatsapp, slack, and web"
```

---

## Task 6: Channel Manager Update

**Files:**
- Update: `claudeclaw/channels/channel_manager.py` (register WhatsApp, Slack, Web adapters)
- Create: `tests/test_channel_manager_plan7.py`

- [ ] **Step 1: Write the failing tests**

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_channel_manager_plan7.py -v
```

Expected: `ImportError` or `AttributeError` — new adapters not yet imported in channel_manager.

- [ ] **Step 3: Update channel_manager.py**

Open `claudeclaw/channels/channel_manager.py` and update imports and `start_channel` method:

```python
# Add to imports at top of channel_manager.py:
from claudeclaw.channels.whatsapp_adapter import WhatsAppAdapter
from claudeclaw.channels.slack_adapter import SlackAdapter
from claudeclaw.channels.web_adapter import WebAdapter
from claudeclaw.channels.webhook_server import (
    register_route as register_whatsapp,  # re-exported by adapter
    register_route as register_slack,
    start_server_background,
)
```

Add or update the `start_channel` and `is_enabled` methods in `ChannelManager`:

```python
def is_enabled(self, channel_name: str) -> bool:
    ch = self._config.get("channels", {}).get(channel_name, {})
    return ch.get("enabled", False)

async def start_channel(self, channel_name: str) -> None:
    """Start a single named channel adapter."""
    ch_config = self._config.get("channels", {}).get(channel_name, {})

    if channel_name == "whatsapp":
        adapter = WhatsAppAdapter(credential_store=self._store)
        register_whatsapp("POST", "/whatsapp/inbound", adapter.handle_inbound)
        asyncio.create_task(adapter.start())
        await start_server_background()

    elif channel_name == "slack":
        socket_mode = ch_config.get("socket_mode", True)
        adapter = SlackAdapter(credential_store=self._store, socket_mode=socket_mode)
        if not socket_mode:
            register_slack("POST", "/slack/events", adapter.handle_events)
            await start_server_background()
        asyncio.create_task(adapter.start())

    elif channel_name == "web":
        port = ch_config.get("port", 3000)
        adapter = WebAdapter(port=port)
        adapter.register_routes()
        asyncio.create_task(adapter.start())
        await start_server_background(port=port)

async def start_all(self) -> None:
    """Start all enabled channel adapters concurrently."""
    channels = self._config.get("channels", {})
    tasks = [
        self.start_channel(name)
        for name, cfg in channels.items()
        if cfg.get("enabled", False)
    ]
    await asyncio.gather(*tasks)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_channel_manager_plan7.py -v
```

Expected: 5 PASSED.

- [ ] **Step 5: Commit**

```bash
git add claudeclaw/channels/channel_manager.py tests/test_channel_manager_plan7.py
git commit -m "feat: channel manager wires WhatsApp, Slack, and Web adapters"
```

---

## Task 7: Integration Verification

**Goal:** Confirm all three channels produce valid `Event` objects that route correctly through the orchestrator.

- [ ] **Step 1: Run the full test suite**

```bash
pytest tests/ -v
```

Expected: all tests from Plan 7 pass. No regressions from Plan 1 or Plan 2 tests.

- [ ] **Step 2: Smoke-test WhatsApp event routing**

```python
# Run interactively or as a one-off script
import asyncio
from claudeclaw.channels.whatsapp_adapter import WhatsAppAdapter
from unittest.mock import MagicMock

store = MagicMock()
store.get.side_effect = lambda k: {"twilio-account-sid": "ACtest", "twilio-auth-token": "auth", "twilio-whatsapp-from": "+14155238886"}.get(k)
adapter = WhatsAppAdapter(credential_store=store)

async def run():
    event = await adapter._parse_twilio_payload({"From": "whatsapp:+15551234567", "Body": "hello"})
    print(event)
    assert event.channel == "whatsapp"
    print("WhatsApp smoke test PASSED")

asyncio.run(run())
```

- [ ] **Step 3: Smoke-test Slack event routing**

```python
from claudeclaw.channels.slack_adapter import SlackAdapter
from unittest.mock import MagicMock

store = MagicMock()
store.get.return_value = "fake"
adapter = SlackAdapter(credential_store=store)

body = {"event": {"user": "U01TEST", "text": "hello slack", "channel": "C01CH"}, "team_id": "T01"}
event = adapter._build_event(body["event"], body)
assert event.channel == "slack"
assert event.user_id == "U01TEST"
print("Slack smoke test PASSED")
```

- [ ] **Step 4: Smoke-test Web event routing**

```python
import asyncio
from claudeclaw.channels.web_adapter import WebAdapter

adapter = WebAdapter(port=3000)

async def run():
    await adapter._handle_text_message("hello web", "conn-001")
    event = adapter._queue.get_nowait()
    assert event.channel == "web"
    assert event.user_id == "localhost"
    assert event.text == "hello web"
    print("Web smoke test PASSED")

asyncio.run(run())
```

- [ ] **Step 5: Run full suite one final time and confirm 0 failures**

```bash
pytest tests/ -v --tb=short
```

Expected: all tests pass.

- [ ] **Step 6: Final commit**

```bash
git add .
git commit -m "test: Plan 7 integration verification — all three channels route to orchestrator"
```

---

## Dependency Summary

Add to `pyproject.toml` `[project] dependencies`:

```toml
"twilio>=9.0",
"slack-bolt>=1.18",
"fastapi>=0.110",
"uvicorn[standard]>=0.29",
"websockets>=12.0",
```

Install command:

```bash
pip install "twilio>=9.0" "slack-bolt>=1.18" "fastapi>=0.110" "uvicorn[standard]>=0.29" "websockets>=12.0"
```
