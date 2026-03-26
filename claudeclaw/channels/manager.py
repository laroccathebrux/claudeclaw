# claudeclaw/channels/manager.py
import asyncio
import logging
from pathlib import Path
from typing import Optional

import yaml

from claudeclaw.channels.base import ChannelAdapter
from claudeclaw.auth.keyring import CredentialStore

logger = logging.getLogger(__name__)

RESTART_DELAY_SECONDS = 5


class ChannelManager:
    def __init__(self, config_path: Path, credential_store: CredentialStore):
        self._config_path = config_path
        self._credential_store = credential_store

    def load_channels(self) -> list[ChannelAdapter]:
        if not self._config_path.exists():
            return []
        data = yaml.safe_load(self._config_path.read_text()) or {}
        channel_configs = data.get("channels", [])
        adapters: list[ChannelAdapter] = []
        for cfg in channel_configs:
            if not cfg.get("enabled", False):
                continue
            adapter = self._build_adapter(cfg["type"])
            if adapter is not None:
                adapters.append(adapter)
        return adapters

    def _build_adapter(self, channel_type: str) -> Optional[ChannelAdapter]:
        if channel_type == "cli":
            from claudeclaw.channels.cli_adapter import CliAdapter
            return CliAdapter()
        if channel_type == "telegram":
            from claudeclaw.channels.telegram_adapter import TelegramAdapter
            token = self._credential_store.get("telegram-bot-token")
            if not token:
                logger.error(
                    "Telegram token not found. Run: claudeclaw channel add telegram --token <TOKEN>"
                )
                return None
            return TelegramAdapter(token=token)
        logger.warning("Unknown channel type: %s", channel_type)
        return None

    async def start_all(self, event_queue: asyncio.Queue) -> list[asyncio.Task]:
        adapters = self.load_channels()
        tasks = []
        for adapter in adapters:
            task = asyncio.create_task(
                self._run_adapter(adapter, event_queue),
                name=f"channel-{adapter.__class__.__name__}",
            )
            tasks.append(task)
        return tasks

    async def _run_adapter(self, adapter: ChannelAdapter, queue: asyncio.Queue):
        while True:
            try:
                async for event in adapter.receive():
                    await queue.put(event)
                # Yield to event loop before restarting (avoids starving the loop
                # when adapter.receive() returns quickly, e.g. in tests)
                await asyncio.sleep(0)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.exception("Adapter %s crashed: %s. Restarting in %ds.",
                                 adapter.__class__.__name__, exc, RESTART_DELAY_SECONDS)
                await asyncio.sleep(RESTART_DELAY_SECONDS)
