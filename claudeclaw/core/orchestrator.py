import asyncio
import logging
from typing import Optional

from claudeclaw.core.event import Event, Response
from claudeclaw.core.router import Router
from claudeclaw.skills.registry import SkillRegistry
from claudeclaw.subagent.dispatch import SubagentDispatcher
from claudeclaw.auth.keyring import CredentialStore

logger = logging.getLogger(__name__)

FALLBACK_MESSAGE = (
    "I don't know how to help with that yet. "
    "No skill matched your request. "
    "You can teach me with: claudeclaw pop"
)


class Orchestrator:
    """
    Main daemon loop.
    Consumes events from an asyncio.Queue, routes to a skill, dispatches a subagent,
    and sends the response back via the event's channel_adapter.
    """

    def __init__(self, skill_registry: SkillRegistry, credential_store: CredentialStore):
        self.registry = skill_registry
        self.credential_store = credential_store

    async def run(self, event_queue: asyncio.Queue, stop_sentinel: bool = False):
        """Consume events from the queue until stopped."""
        logger.info("Orchestrator started.")
        while True:
            event: Event = await event_queue.get()
            if stop_sentinel and event is None:
                event_queue.task_done()
                break
            response = await self._process(event)
            if event.channel_adapter is not None:
                await event.channel_adapter.send(response)
            event_queue.task_done()

    async def _process(self, event: Event) -> Response:
        router = Router(self.registry.list_skills())
        skill = router.route(event)

        if skill is None:
            logger.info("No skill matched for: %r", event.text)
            return Response(text=FALLBACK_MESSAGE, channel=event.channel)

        logger.info("Dispatching skill '%s' for event: %r", skill.name, event.text)
        try:
            dispatcher = SubagentDispatcher()
            result = dispatcher.dispatch(skill, event)
            return Response(text=result.text, channel=event.channel)
        except Exception as e:
            logger.error("Dispatch failed: %s", e)
            return Response(
                text=f"Something went wrong running '{skill.name}'. Check logs.",
                channel=event.channel,
            )
