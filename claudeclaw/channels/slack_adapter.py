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

    async def receive(self):
        """Slack is webhook-driven; events arrive via handle_events, not receive()."""
        # Yield from the queue — allows use with receive()-based manager
        while True:
            event = await self._queue.get()
            yield event

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
