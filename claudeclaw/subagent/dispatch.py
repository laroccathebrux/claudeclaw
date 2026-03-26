import logging
from dataclasses import dataclass
from typing import Optional
import anthropic

from claudeclaw.skills.loader import SkillManifest
from claudeclaw.core.event import Event
from claudeclaw.core.conversation import ConversationState

logger = logging.getLogger(__name__)

MODEL = "claude-sonnet-4-6"


def credential_key_to_env_var(key: str) -> str:
    """Normalize a credential key name to an environment variable name."""
    return key.upper().replace("-", "_")


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

        # Build env dict from credentials — validate all declared keys are present
        env: dict[str, str] = {}
        for key in (skill.credentials or []):
            value = (credentials or {}).get(key)
            if value is None:
                raise ValueError(
                    f"Credential '{key}' declared in skill '{skill.name}' but not provided."
                )
            env[credential_key_to_env_var(key)] = value

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
        if env:
            kwargs["env"] = env

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
        return skill.body

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
