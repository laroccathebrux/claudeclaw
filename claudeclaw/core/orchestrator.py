# claudeclaw/core/orchestrator.py
import asyncio
import logging
from typing import Optional

from claudeclaw.core.event import Event, Response
from claudeclaw.core.router import route as route_event
from claudeclaw.skills.registry import SkillRegistry
from claudeclaw.subagent.dispatch import SubagentDispatcher
from claudeclaw.auth.keyring import CredentialStore
from claudeclaw.core.conversation import ConversationStore

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

    def __init__(
        self,
        skill_registry: SkillRegistry,
        credential_store: CredentialStore,
        conv_store: Optional[ConversationStore] = None,
    ):
        self.registry = skill_registry
        self.credential_store = credential_store
        self._dispatcher = SubagentDispatcher()
        self._conv_store = conv_store or ConversationStore()

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
        conversation = None
        skill = None

        user_id = event.user_id or ""
        if self._conv_store.has_active(event.channel, user_id):
            conversation = self._conv_store.get(event.channel, user_id)
            if conversation is not None:
                skill = self.registry.find(conversation.skill_name)
                logger.info(
                    "Resuming conversation for skill '%s' (step %d)",
                    conversation.skill_name, conversation.step,
                )

        if skill is None:
            skill = route_event(event, self.registry)

        if skill is None:
            logger.info("No skill matched for: %r", event.text)
            return Response(text=FALLBACK_MESSAGE, channel=event.channel)

        logger.info("Dispatching skill '%s' for event: %r", skill.name, event.text)
        try:
            result = self._dispatcher.dispatch(skill, event, conversation=conversation)

            # Persist session_id so next message resumes the same Claude CLI session
            if result.session_id:
                from claudeclaw.core.conversation import ConversationState
                if conversation is None:
                    conversation = ConversationState(
                        channel=event.channel,
                        user_id=user_id,
                        skill_name=skill.name,
                        step=1,
                        data={},
                        history=[],
                    )
                conversation.data["claude_session_id"] = result.session_id
                conversation.step += 1
                self._conv_store.save(conversation)

            return Response(text=result.text, channel=event.channel)
        except Exception as e:
            logger.error("Dispatch failed: %s", e)
            return Response(
                text=f"Something went wrong running '{skill.name}'. Check logs.",
                channel=event.channel,
            )
