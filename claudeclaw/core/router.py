import logging
from typing import Optional
import anthropic

from claudeclaw.core.event import Event
from claudeclaw.skills.loader import SkillManifest
from claudeclaw.skills.registry import SkillRegistry

logger = logging.getLogger(__name__)


class Router:
    """
    Maps an incoming event to the best matching skill.
    Uses Claude to match event intent against skill descriptions.
    Falls back to None if no skill matches well enough.
    """

    def __init__(self, skills: list[SkillManifest], client: Optional[anthropic.Anthropic] = None):
        self._skills = skills
        self._client = client or anthropic.Anthropic()

    def route(self, event: Event) -> Optional[SkillManifest]:
        if not self._skills:
            return None

        matched_name = self._match_with_claude(event.text)
        if matched_name is None:
            return None

        return next((s for s in self._skills if s.name.lower() == matched_name), None)

    def _match_with_claude(self, text: str) -> Optional[str]:
        skill_list = "\n".join(
            f"- {s.name}: {s.description}" for s in self._skills
        )
        prompt = f"""Given this user message: "{text}"

And these available skills:
{skill_list}

Which skill name best matches the user's intent?
Reply with ONLY the skill name, or "none" if no skill matches."""

        try:
            response = self._client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=64,
                messages=[{"role": "user", "content": prompt}],
            )
            result = response.content[0].text.strip().lower()
            return None if result == "none" else result
        except Exception as e:
            logger.error("Router Claude call failed: %s", e)
            return None


NATIVE_SKILL_INTENTS: dict[str, list[str]] = {
    "pop": [
        "teach", "ensina", "ensinar",
        "automate", "automatiza", "automatizar",
        "map", "mapeia", "mapear",
        "pop", "procedimento",
        "how to", "como fazer",
    ],
    "agent-creator": [
        "create an agent", "i need someone to",
        "crie um agente", "preciso de alguém",
    ],
}


def route(event: Event, registry: SkillRegistry) -> Optional[SkillManifest]:
    """
    Route an event to a skill.
    1. Check native skill intent keywords (priority).
    2. Fall through to general routing.
    """
    text_lower = event.text.lower()

    for skill_name, keywords in NATIVE_SKILL_INTENTS.items():
        if any(kw in text_lower for kw in keywords):
            skill = registry.find(skill_name)
            if skill is not None:
                return skill

    return _general_route(event, registry)


def _general_route(event: Event, registry: SkillRegistry) -> Optional[SkillManifest]:
    """
    General skill routing: find the best matching skill for the event.
    Plan 1 implementation: returns the first available on-demand skill.
    Plan 3 will replace this with Claude SDK semantic matching.
    """
    for skill in registry.all_skills():
        if skill.trigger == "on-demand":
            return skill
    return None
