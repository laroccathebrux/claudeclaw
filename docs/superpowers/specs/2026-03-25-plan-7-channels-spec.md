# ClaudeClaw — Plan 7 Sub-Spec: Additional Channels (WhatsApp, Slack, Web UI)

**Date:** 2026-03-25
**Status:** Draft
**Spec reference:** `docs/superpowers/specs/2026-03-24-claudeclaw-design.md`
**Depends on:** Plan 1 (CredentialStore, Event/Response, Orchestrator), Plan 2 (ChannelAdapter ABC, Channel manager, channels.yaml)

---

## Overview

Plan 7 adds three production-ready channel adapters: WhatsApp (via Twilio), Slack (via slack-bolt), and a local Web UI (via FastAPI + WebSocket). All three integrate with the existing channel manager from Plan 2 and require no changes to the orchestrator or skill system.

---

## 1. WhatsApp Channel Adapter

**File:** `claudeclaw/channels/whatsapp_adapter.py`

### Summary

Receives inbound WhatsApp messages from Twilio's webhook and sends outbound messages via the Twilio REST API. Implements the `ChannelAdapter` ABC from Plan 2.

### Inbound Flow

1. Twilio delivers a POST request to `POST /whatsapp/inbound` on the shared webhook server.
2. `WhatsAppAdapter.handle_inbound(request)` parses the form-encoded Twilio payload.
3. Constructs and enqueues an `Event`:
   - `Event.channel = "whatsapp"`
   - `Event.user_id = request.form["From"]` (sender's WhatsApp number, e.g. `whatsapp:+15551234567`)
   - `Event.text = request.form["Body"]`
   - `Event.raw = dict(request.form)`
4. Returns a `200 OK` with an empty TwiML body (response sent asynchronously).

### Outbound Flow

1. Orchestrator calls `adapter.send(response: Response)`.
2. Adapter fetches credentials from Keyring: `twilio-account-sid`, `twilio-auth-token`, `twilio-whatsapp-from`.
3. Makes a POST to `https://api.twilio.com/2010-04-01/Accounts/{SID}/Messages.json` using `httpx` (async).
4. Payload: `From=whatsapp:<from_number>`, `To=<user_id>`, `Body=<response.text>`.

### Configuration

```bash
claudeclaw channel add whatsapp \
  --account-sid <SID> \
  --auth-token <TOKEN> \
  --from <NUMBER>
```

- Stores `twilio-account-sid` → Keyring
- Stores `twilio-auth-token` → Keyring
- Stores `twilio-whatsapp-from` → Keyring
- Writes `{ channel: whatsapp, enabled: true }` to `~/.claudeclaw/config/channels.yaml`

### Keyring Keys

| Key | Value |
|---|---|
| `twilio-account-sid` | Twilio Account SID |
| `twilio-auth-token` | Twilio Auth Token |
| `twilio-whatsapp-from` | Sender's WhatsApp number (e.g. `+14155238886`) |

### Event Shape

```python
Event(
    channel="whatsapp",
    user_id="whatsapp:+15551234567",   # sender's number
    text="Hello agent",
    raw={"From": "whatsapp:+15551234567", "Body": "Hello agent", ...}
)
```

### Signature Validation

The adapter validates every inbound Twilio request using `twilio.request_validator.RequestValidator` before processing. Requests that fail validation return `403 Forbidden`.

### Dependencies

```
twilio>=9.0
httpx>=0.27        (already in Plan 1)
```

---

## 2. Slack Channel Adapter

**File:** `claudeclaw/channels/slack_adapter.py`

### Summary

Listens for Slack messages using `slack-bolt`. In development mode uses Socket Mode (no public URL required). In production uses Slack Events API HTTP webhooks. Implements the `ChannelAdapter` ABC from Plan 2.

### Inbound Flow

**Socket Mode (development):**
1. `SlackAdapter.start()` initialises a `slack_bolt.App` with `bot_token` and `signing_secret`.
2. Wraps the app in `slack_bolt.adapter.socket_mode.async_handler.AsyncSocketModeHandler`.
3. On `@app.message("")`, converts the Slack event to an `Event` and enqueues it.

**Webhook Mode (production):**
1. Registers `POST /slack/events` on the shared webhook server.
2. Slack-bolt's `AsyncSlackRequestHandler` handles request verification and event parsing.
3. On `message` events, constructs and enqueues an `Event`.

### Event Shape

```python
Event(
    channel="slack",
    user_id="U01ABCDE123",             # Slack user ID from event["user"]
    text="Hello agent",
    raw={"event": {...}, "team_id": "T01XYZ"}
)
```

### Outbound Flow

1. Orchestrator calls `adapter.send(response: Response)`.
2. Adapter resolves the originating Slack channel ID from `response.event.raw["event"]["channel"]`.
3. Calls `app.client.chat_postMessage(channel=channel_id, text=response.text)` asynchronously.

### Configuration

```bash
claudeclaw channel add slack \
  --token <BOT_TOKEN> \
  --signing-secret <SECRET> \
  [--socket-mode]          # default: True for local, False in production
```

- Stores `slack-bot-token` → Keyring
- Stores `slack-signing-secret` → Keyring
- Writes `{ channel: slack, enabled: true, socket_mode: true }` to `channels.yaml`

### Keyring Keys

| Key | Value |
|---|---|
| `slack-bot-token` | Slack Bot User OAuth Token (`xoxb-...`) |
| `slack-signing-secret` | Slack Signing Secret for request verification |

### Dependencies

```
slack-bolt>=1.18
```

---

## 3. Web UI Channel Adapter

**File:** `claudeclaw/channels/web_adapter.py`
**Static assets:** `claudeclaw/channels/static/index.html`

### Summary

Serves a minimal single-page chat UI at `http://localhost:3000`. Uses a WebSocket connection for real-time bidirectional messaging. Runs on the shared webhook server. No authentication — localhost only.

### Architecture

```
Browser ←→ WebSocket /ws ←→ WebAdapter ←→ Orchestrator event queue
          HTTP GET /      ←→ static index.html
```

### Inbound Flow

1. Browser connects to `ws://localhost:3000/ws`.
2. On each WebSocket message received, `WebAdapter` constructs an `Event`:
   - `Event.channel = "web"`
   - `Event.user_id = "localhost"`
   - `Event.text = message.data`
3. Enqueues the event for the orchestrator.

### Outbound Flow

1. Orchestrator calls `adapter.send(response: Response)`.
2. Adapter pushes `response.text` as a WebSocket text frame to the browser.
3. Multiple concurrent browser connections are supported; messages route to the connection that sent the originating event.

### Static Frontend

**File:** `claudeclaw/channels/static/index.html`

Minimal single-file HTML+JS chat interface:
- Text input + send button
- Chat bubble display area
- WebSocket client auto-reconnects on disconnect
- No external dependencies (vanilla JS, inline CSS)
- Loads at `GET /` served by the shared webhook server

### Configuration

```bash
claudeclaw channel add web [--port 3000]
```

- Writes `{ channel: web, enabled: true, port: 3000 }` to `channels.yaml`
- No credentials required (localhost only)

### Event Shape

```python
Event(
    channel="web",
    user_id="localhost",
    text="Hello agent",
    raw={"connection_id": "abc123"}
)
```

### Dependencies

```
fastapi>=0.110
uvicorn>=0.29
websockets>=12.0
```

---

## 4. Shared Webhook Server

**File:** `claudeclaw/channels/webhook_server.py`

### Summary

A single FastAPI application instance shared by all HTTP-based adapters. Started once when any HTTP-based channel is enabled. WhatsApp (Twilio) and Web UI both register their routes into this shared app.

### Route Table

| Method | Path | Handler |
|---|---|---|
| `POST` | `/whatsapp/inbound` | `WhatsAppAdapter.handle_inbound` |
| `POST` | `/slack/events` | `SlackAdapter.handle_events` (production webhook mode) |
| `GET` | `/` | Serve `static/index.html` |
| `WebSocket` | `/ws` | `WebAdapter.handle_websocket` |

### Lifecycle

```python
# webhook_server.py

app = FastAPI()

def register_whatsapp(adapter: WhatsAppAdapter) -> None:
    app.add_api_route("/whatsapp/inbound", adapter.handle_inbound, methods=["POST"])

def register_slack(adapter: SlackAdapter) -> None:
    app.add_api_route("/slack/events", adapter.handle_events, methods=["POST"])

def register_web(adapter: WebAdapter) -> None:
    app.add_api_route("/", adapter.serve_index)
    app.add_websocket_route("/ws", adapter.handle_websocket)

async def start_server(host: str = "0.0.0.0", port: int = 8080) -> None:
    config = uvicorn.Config(app, host=host, port=port)
    server = uvicorn.Server(config)
    await server.serve()
```

### Port Configuration

- Default webhook port: `8080` (Twilio inbound, Slack Events API)
- Default Web UI port: `3000` (served separately or on the same server with path routing)
- Port is configurable via `claudeclaw channel add web --port <PORT>`

---

## 5. Channel Manager Update

The channel manager from Plan 2 manages concurrent adapter tasks via asyncio. Plan 7 registers the three new adapters using the same pattern.

```python
# In channel_manager.py (Plan 2 file, updated in Plan 7)

from claudeclaw.channels.whatsapp_adapter import WhatsAppAdapter
from claudeclaw.channels.slack_adapter import SlackAdapter
from claudeclaw.channels.web_adapter import WebAdapter
from claudeclaw.channels.webhook_server import register_whatsapp, register_slack, register_web, start_server

async def start_all_channels(config: ChannelsConfig, credential_store: CredentialStore) -> None:
    tasks = []

    if config.whatsapp.enabled:
        adapter = WhatsAppAdapter(credential_store)
        register_whatsapp(adapter)
        tasks.append(asyncio.create_task(adapter.start()))

    if config.slack.enabled:
        adapter = SlackAdapter(credential_store)
        if config.slack.socket_mode:
            tasks.append(asyncio.create_task(adapter.start()))
        else:
            register_slack(adapter)

    if config.web.enabled:
        adapter = WebAdapter(port=config.web.port)
        register_web(adapter)
        tasks.append(asyncio.create_task(adapter.start()))

    if any([config.whatsapp.enabled, config.web.enabled, not config.slack.socket_mode]):
        tasks.append(asyncio.create_task(start_server()))

    await asyncio.gather(*tasks)
```

All three adapters are optional — they are started only if their channel config entry exists and `enabled: true`.

---

## 6. channels.yaml Format Extension

The `channels.yaml` format from Plan 2 is extended with three new channel entries:

```yaml
# ~/.claudeclaw/config/channels.yaml

channels:
  telegram:
    enabled: true
    # credentials in keyring: telegram-bot-token

  whatsapp:
    enabled: true
    webhook_port: 8080
    # credentials in keyring: twilio-account-sid, twilio-auth-token, twilio-whatsapp-from

  slack:
    enabled: true
    socket_mode: true
    # credentials in keyring: slack-bot-token, slack-signing-secret

  web:
    enabled: true
    port: 3000
```

---

## 7. Out of Scope for Plan 7

- WhatsApp Business API direct integration (Plan 7 uses Twilio as the intermediary)
- Slack slash commands (only `message` events are handled)
- Web UI user authentication (localhost only, no auth)
- Mobile-responsive or styled Web UI (minimal functional HTML only)
- Multi-user Web UI sessions (single-user localhost assumption)
- Slack interactive components (buttons, modals)
- Twilio media messages (images, audio) — text only in v1

---

## 8. Test Coverage Requirements

Each adapter must have:

1. **Unit tests** — mock all external APIs (Twilio, Slack, WebSocket), verify `Event` construction from raw payloads
2. **Outbound tests** — verify correct API calls are made with expected parameters
3. **Config tests** — verify `channel add` CLI stores credentials to Keyring and writes `channels.yaml`
4. **Webhook server tests** — verify routes are registered correctly, 403 on invalid Twilio signature

Test files:
- `tests/test_whatsapp_adapter.py`
- `tests/test_slack_adapter.py`
- `tests/test_web_adapter.py`
- `tests/test_webhook_server.py`
- `tests/test_channel_manager_plan7.py`
