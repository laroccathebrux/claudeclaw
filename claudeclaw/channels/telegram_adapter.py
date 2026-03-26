# claudeclaw/channels/telegram_adapter.py
import asyncio
import logging
from typing import AsyncGenerator, Optional

from telegram import Bot, Update
from telegram.ext import Application, MessageHandler, ContextTypes, filters

from claudeclaw.channels.base import ChannelAdapter
from claudeclaw.core.event import Event, Response

logger = logging.getLogger(__name__)


class TelegramAdapter(ChannelAdapter):
    """
    Channel adapter for Telegram using python-telegram-bot>=21.
    Bridges PTB callback-based message handling to the AsyncGenerator interface
    required by ChannelAdapter via an internal asyncio.Queue.

    Design notes:
    - receive() yields Event objects from _internal_queue (no PTB startup).
    - _on_message() is the PTB handler that puts messages onto _internal_queue.
    - In production, call start_application() before receive() to start PTB polling.
    - In tests, seed _internal_queue directly; PTB network is never touched.
    """

    def __init__(self, token: str):
        self._token = token
        self._internal_queue: asyncio.Queue = asyncio.Queue()
        self._bot: Optional[Bot] = None
        self._application: Optional[Application] = None

    async def _on_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """PTB handler: put incoming message onto the internal queue."""
        if update.message and update.message.text:
            await self._internal_queue.put(update.message)

    def receive(self) -> AsyncGenerator[Event, None]:
        """
        Return an async generator that yields Event objects as Telegram messages arrive.
        Consumes from the internal queue. PTB startup is a separate concern —
        call start_application() in production to wire PTB polling.
        In tests, seed _internal_queue directly.
        """
        return self._receive_impl()

    async def _receive_impl(self):
        """Consume messages from the internal queue and yield as Event objects."""
        while True:
            message = await self._internal_queue.get()
            if message is None:
                break
            yield Event(
                text=message.text,
                channel="telegram",
                channel_adapter=self,
                metadata={
                    "chat_id": message.chat_id,
                    "user_id": message.from_user.id if message.from_user else None,
                },
            )

    async def start_application(self) -> None:
        """
        Initialize and start PTB polling. Call this in production before receive().
        ChannelManager should call this method if present, or wrap receive() accordingly.
        """
        self._application = (
            Application.builder()
            .token(self._token)
            .build()
        )
        self._bot = self._application.bot
        self._application.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self._on_message)
        )
        await self._application.initialize()
        await self._application.start()
        await self._application.updater.start_polling(drop_pending_updates=True)
        logger.info("TelegramAdapter: PTB polling started")

    async def stop_application(self) -> None:
        """Stop PTB polling and clean up resources."""
        if self._application is not None:
            await self._application.updater.stop()
            await self._application.stop()
            await self._application.shutdown()
            logger.info("TelegramAdapter: PTB polling stopped")

    async def send(self, response: Response) -> None:
        """Send a text response back to the originating Telegram chat."""
        if self._bot is None:
            raise RuntimeError(
                "TelegramAdapter.send() called before bot is initialized. "
                "Call start_application() first, or set _bot directly (for tests)."
            )
        await self._bot.send_message(chat_id=response.chat_id, text=response.text)
