import logging
from dataclasses import dataclass
from typing import Optional
import anthropic

from claudeclaw.skills.loader import SkillManifest
from claudeclaw.core.event import Event
from claudeclaw.auth.keyring import CredentialStore
from claudeclaw.core.conversation import ConversationState

logger = logging.getLogger(__name__)

MODEL = "claude-sonnet-4-6"


@dataclass
class DispatchResult:
    text: str
    skill_name: str
    stop_reason: str


class SubagentDispatcher:
    """
    Dispatches a Claude SDK subagent for a given skill + event.
    Enforces permissions: only tools declared in the skill are passed to the API.
    Injects credentials from Keyring into the system prompt context.
    """

    def __init__(self, client: Optional[anthropic.Anthropic] = None):
        self._client = client or anthropic.Anthropic()

    def dispatch(
        self,
        skill: SkillManifest,
        event: Optional[Event] = None,
        conversation: Optional[ConversationState] = None,
        *,
        user_message: Optional[str] = None,
        credentials: Optional[dict] = None,
    ) -> DispatchResult:
        system_prompt = self._build_system_prompt(skill)
        tools = self._resolve_tools(skill)

        # Resolve message text: prefer event.text, fall back to user_message
        text = event.text if event is not None else (user_message or "")

        # Build MCP servers list
        from claudeclaw.mcps.config import resolve_mcps
        mcp_configs = resolve_mcps(skill)
        mcp_servers = [
            {
                "type": "stdio",
                "command": m.command,
                "args": m.args,
                "env": m.env,
            }
            for m in mcp_configs
        ]

        # Build messages: prepend history if resuming a conversation
        messages = []
        if conversation and conversation.history:
            messages.extend(conversation.history)
        messages.append({"role": "user", "content": text})

        kwargs = dict(
            model=MODEL,
            max_tokens=4096,
            system=system_prompt,
            messages=messages,
        )
        if tools:
            kwargs["tools"] = tools
        if mcp_servers:
            kwargs["mcp_servers"] = mcp_servers

        try:
            response = self._client.messages.create(**kwargs)
            text = response.content[0].text if response.content else ""
            return DispatchResult(
                text=text,
                skill_name=skill.name,
                stop_reason=response.stop_reason,
            )
        except Exception as e:
            logger.error("Subagent dispatch failed for skill '%s': %s", skill.name, e)
            raise

    def _build_system_prompt(self, skill: SkillManifest) -> str:
        # PLAN 1 SIMPLIFICATION: credentials are injected as plaintext into the system prompt.
        # The spec calls for env-var injection — that is deferred to Plan 5 (Plugins + MCPs)
        # when the full subagent sandboxing model is wired up. Do NOT change this now.
        parts = [skill.body]

        if skill.credentials:
            store = CredentialStore()
            cred_lines = []
            for key in skill.credentials:
                value = store.get(key)
                if value:
                    cred_lines.append(f"{key}: {value}")
            if cred_lines:
                parts.append("\n## Credentials\n" + "\n".join(cred_lines))

        return "\n\n".join(parts)

    def _resolve_tools(self, skill: SkillManifest) -> list:
        # Plan 1: tools list is empty or contains string names.
        # MCPs and plugins are resolved in later plans.
        # Return empty list — no tool schemas wired yet.
        return []


async def dispatch_skill(skill: SkillManifest, event: Event):
    """Async wrapper around SubagentDispatcher for use in async CLI contexts.

    NOTE: SubagentDispatcher.dispatch is currently synchronous (uses anthropic.Anthropic,
    not AsyncAnthropic). This wrapper is intentionally kept async so callers can await it
    uniformly. When the dispatcher is migrated to async streaming (planned for a later plan),
    this wrapper will not need to change.
    """
    dispatcher = SubagentDispatcher()
    return dispatcher.dispatch(skill, event)
