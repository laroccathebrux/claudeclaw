import logging
from dataclasses import dataclass
from typing import Optional
import anthropic

from claudeclaw.skills.loader import SkillManifest
from claudeclaw.security.openshell import OpenShellTool
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
        if client is not None:
            self._client = client
        else:
            from claudeclaw.auth.oauth import AuthManager, AuthError
            try:
                token = AuthManager().get_token()
                self._client = anthropic.Anthropic(auth_token=token)
            except AuthError:
                # Fall back to SDK default (ANTHROPIC_API_KEY env var)
                self._client = anthropic.Anthropic()

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
        tools = self._build_tools(skill)

        # Check and attempt token refresh if needed
        if hasattr(self, "_auth") and self._auth is not None:
            if self._auth.is_token_expiring():
                refreshed = self._auth.refresh_token()
                if not refreshed:
                    logger.warning(
                        "OAuth token is expiring and refresh is not yet implemented. "
                        "Run 'claudeclaw login' if authentication fails."
                    )

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

    def _build_tools(self, skill) -> list:
        """Build the tool list for a subagent invocation based on skill frontmatter."""
        tools = []
        policy = getattr(skill, "shell_policy", "none")
        if policy and policy != "none":
            tools.append(OpenShellTool(policy=policy))
        return tools


async def dispatch_skill(skill: SkillManifest, event: Event):
    """Async wrapper around SubagentDispatcher for use in async CLI contexts.

    NOTE: SubagentDispatcher.dispatch is currently synchronous (uses anthropic.Anthropic,
    not AsyncAnthropic). This wrapper is intentionally kept async so callers can await it
    uniformly. When the dispatcher is migrated to async streaming (planned for a later plan),
    this wrapper will not need to change.
    """
    dispatcher = SubagentDispatcher()
    return dispatcher.dispatch(skill, event)
