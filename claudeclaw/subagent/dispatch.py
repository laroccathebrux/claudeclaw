import json
import logging
import os
import subprocess
from dataclasses import dataclass, field
from typing import Optional

from claudeclaw.skills.loader import SkillManifest
from claudeclaw.core.event import Event
from claudeclaw.core.conversation import ConversationState

logger = logging.getLogger(__name__)

CLAUDE_CLI = "claude"


def credential_key_to_env_var(key: str) -> str:
    """Normalize a credential key name to an environment variable name."""
    return key.upper().replace("-", "_")


@dataclass
class DispatchResult:
    text: str
    skill_name: str
    stop_reason: str
    session_id: Optional[str] = field(default=None)


class SubagentDispatcher:
    """
    Dispatches a subagent via the Claude Code CLI (`claude -p`).
    Uses the user's existing Claude subscription — no API key needed.
    Maintains conversation history via Claude CLI session resumption.
    Credentials are injected as environment variables.
    MCPs are passed via --mcp-config.
    """

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
        text = event.text if event is not None else (user_message or "")

        # Resume existing session if we have one, otherwise start a new one
        session_id = (conversation.data or {}).get("claude_session_id") if conversation else None

        cmd = [CLAUDE_CLI, "-p", "--output-format", "json"]

        if session_id:
            cmd += ["--resume", session_id]
        else:
            cmd += ["--append-system-prompt", system_prompt]

        # Inject MCPs via --mcp-config
        from claudeclaw.mcps.config import resolve_mcps
        mcp_configs = resolve_mcps(skill)
        if mcp_configs:
            mcp_json = json.dumps([
                {"type": "stdio", "command": m.command, "args": m.args, "env": m.env}
                for m in mcp_configs
            ])
            cmd += ["--mcp-config", mcp_json]

        cmd.append(text)

        # Inject credentials as subprocess environment variables
        env = os.environ.copy()
        for key in (skill.credentials or []):
            value = (credentials or {}).get(key)
            if value is None:
                raise ValueError(
                    f"Credential '{key}' declared in skill '{skill.name}' but not provided."
                )
            env[credential_key_to_env_var(key)] = value

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120,
                env=env,
            )
            if result.returncode != 0:
                err = result.stderr.strip() or result.stdout.strip()
                logger.error("Subagent dispatch failed for skill '%s': %s", skill.name, err)
                raise RuntimeError(err)

            data = json.loads(result.stdout)
            response_text = data.get("result", "")
            stop_reason = data.get("stop_reason", "end_turn")
            new_session_id = data.get("session_id")
            return DispatchResult(
                text=response_text,
                skill_name=skill.name,
                stop_reason=stop_reason,
                session_id=new_session_id,
            )
        except subprocess.TimeoutExpired:
            logger.error("Subagent dispatch timed out for skill '%s'", skill.name)
            raise RuntimeError(f"Dispatch timed out for skill '{skill.name}'")
        except Exception as e:
            logger.error("Subagent dispatch failed for skill '%s': %s", skill.name, e)
            raise

    def _build_system_prompt(self, skill: SkillManifest) -> str:
        return skill.body

    def _build_tools(self, skill) -> list:
        """Kept for API compatibility. Claude CLI handles tool use internally."""
        return []


async def dispatch_skill(skill: SkillManifest, event: Event):
    """Async wrapper around SubagentDispatcher for use in async contexts."""
    dispatcher = SubagentDispatcher()
    return dispatcher.dispatch(skill, event)
