import asyncio
import logging
from typing import Optional

from claudeclaw.core.event import Event, Response
from claudeclaw.core.router import Router
from claudeclaw.skills.registry import SkillRegistry
from claudeclaw.subagent.dispatch import SubagentDispatcher
from claudeclaw.channels.base import ChannelAdapter

logger = logging.getLogger(__name__)

FALLBACK_MESSAGE = (
    "I don't know how to help with that yet. "
    "No skill matched your request. "
    "You can teach me with: claudeclaw pop"
)


class Orchestrator:
    """
    Main daemon loop.
    Receives events from a channel, routes to a skill, dispatches a subagent,
    and sends the response back.
    """

    def __init__(
        self,
        channel: ChannelAdapter,
        registry: Optional[SkillRegistry] = None,
        router: Optional[Router] = None,
        dispatcher: Optional[SubagentDispatcher] = None,
    ):
        self._channel = channel
        self._registry = registry or SkillRegistry()
        self._dispatcher = dispatcher or SubagentDispatcher()
        # Router is created lazily after registry loads skills
        self._router = router

    def _get_router(self) -> Router:
        if self._router is None:
            skills = self._registry.list_skills()
            self._router = Router(skills)
        return self._router

    async def run_once(self):
        """Process exactly one event. Used in tests and single-shot runs."""
        router = self._get_router()
        stream = self._channel.receive()
        # Support both plain async generators and coroutines that return async generators
        if asyncio.iscoroutine(stream):
            stream = await stream
        async for event in stream:
            await self._handle(event, router)
            return

    async def run(self):
        """Continuous daemon loop."""
        logger.info("Orchestrator started.")
        router = self._get_router()
        try:
            stream = self._channel.receive()
            if asyncio.iscoroutine(stream):
                stream = await stream
            async for event in stream:
                await self._handle(event, router)
        except (KeyboardInterrupt, asyncio.CancelledError):
            logger.info("Orchestrator stopped.")

    async def _handle(self, event: Event, router: Router):
        skill = router.route(event)
        if skill is None:
            logger.info("No skill matched for: %r", event.text)
            await self._channel.send(Response(text=FALLBACK_MESSAGE, event=event))
            return

        logger.info("Dispatching skill '%s' for event: %r", skill.name, event.text)
        try:
            result = self._dispatcher.dispatch(skill, event)
            await self._channel.send(Response(text=result.text, event=event))
        except Exception as e:
            logger.error("Dispatch failed: %s", e)
            await self._channel.send(
                Response(text=f"Something went wrong running '{skill.name}'. Check logs.", event=event)
            )
