import asyncio
from typing import AsyncGenerator
from claudeclaw.channels.base import ChannelAdapter
from claudeclaw.core.event import Event, Response


class CliAdapter(ChannelAdapter):
    """stdin/stdout channel — reads lines from terminal, prints responses."""

    def __init__(self):
        self._ready = asyncio.Event()
        self._ready.set()  # allow first input immediately

    async def receive(self) -> AsyncGenerator[Event, None]:
        loop = asyncio.get_event_loop()
        while True:
            await self._ready.wait()
            self._ready.clear()
            try:
                text = await loop.run_in_executor(None, input, "\n> ")
            except (EOFError, KeyboardInterrupt):
                return
            if text.strip().lower() in ("/exit", "/quit"):
                return
            if not text.strip():
                self._ready.set()  # empty input — show prompt again
                continue
            yield Event(text=text.strip(), channel="cli", user_id="local")

    async def send(self, response: Response) -> None:
        print(f"\n{response.text}")
        self._ready.set()  # response delivered — show next prompt
