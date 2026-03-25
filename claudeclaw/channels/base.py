# claudeclaw/channels/base.py
from abc import ABC, abstractmethod
from typing import AsyncIterator
from claudeclaw.core.event import Event, Response


class ChannelAdapter(ABC):
    """
    Each channel adapter normalizes incoming messages into Event objects
    and delivers Response objects back to the user.
    """

    @abstractmethod
    async def receive(self) -> AsyncIterator[Event]:
        """Yield events as they arrive."""
        ...

    @abstractmethod
    async def send(self, response: Response) -> None:
        """Deliver a response back to the user."""
        ...
