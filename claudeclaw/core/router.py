import logging
from typing import Optional
import anthropic

from claudeclaw.core.event import Event
from claudeclaw.skills.loader import SkillManifest

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
