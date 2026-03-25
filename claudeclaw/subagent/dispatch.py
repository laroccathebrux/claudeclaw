import logging
from dataclasses import dataclass
from typing import Optional
import anthropic

from claudeclaw.skills.loader import SkillManifest
from claudeclaw.core.event import Event
from claudeclaw.auth.keyring import CredentialStore

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

    def dispatch(self, skill: SkillManifest, event: Event) -> DispatchResult:
        system_prompt = self._build_system_prompt(skill)
        tools = self._resolve_tools(skill)
        messages = [{"role": "user", "content": event.text}]

        kwargs = dict(
            model=MODEL,
            max_tokens=4096,
            system=system_prompt,
            messages=messages,
        )
        if tools:
            kwargs["tools"] = tools

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
