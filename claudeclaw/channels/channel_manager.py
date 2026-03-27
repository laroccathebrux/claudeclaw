# claudeclaw/channels/channel_manager.py
from __future__ import annotations

import asyncio
import logging
from typing import Any

from claudeclaw.channels.whatsapp_adapter import WhatsAppAdapter
from claudeclaw.channels.slack_adapter import SlackAdapter
from claudeclaw.channels.web_adapter import WebAdapter
from claudeclaw.channels.webhook_server import (
    register_route as register_whatsapp,
    register_route as register_slack,
    start_server_background,
)

logger = logging.getLogger(__name__)


class ChannelManager:
    """Manages channel adapters using an in-memory config dict."""

    def __init__(self, config: dict[str, Any], credential_store):
        self._config = config
        self._store = credential_store

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
