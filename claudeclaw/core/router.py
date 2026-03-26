import logging
from typing import Optional, Union
import anthropic

from claudeclaw.core.event import Event
from claudeclaw.skills.loader import SkillManifest
from claudeclaw.skills.registry import SkillRegistry

logger = logging.getLogger(__name__)

META_SKILLS = {
    "agent-creator": (
        "Creates a new autonomous agent via a guided wizard. Match when the user wants "
        "to create, build, set up, automate, or train a new agent or capability."
    ),
    "pop": (
        "Maps a single operation step-by-step and creates a skill. Match when the user "
        "wants to teach the system how to do one specific operation."
    ),
}


class Router:
    """
    Maps an incoming event to the best matching skill or meta-skill.
    Meta-skills (agent-creator, pop) are always available candidates.
    Returns a SkillManifest for installed skills, or a string name for meta-skills.
    Returns None if nothing matches.
    """

    def __init__(self, skills: list[SkillManifest], client: Optional[anthropic.Anthropic] = None):
        self._skills = skills
        self._client = client or anthropic.Anthropic()

    def route(self, event: Event) -> Optional[Union[SkillManifest, str]]:
        prompt = self._build_routing_prompt(event.text)
        matched_name = self._match_with_claude(event.text, prompt=prompt)
        if matched_name is None:
            return None
        # Meta-skills returned as string name
        if matched_name in META_SKILLS:
            return matched_name
        # Installed skills returned as SkillManifest
        return next((s for s in self._skills if s.name.lower() == matched_name), None)

    def _build_routing_prompt(self, text: str) -> str:
        meta_lines = "\n".join(
            f"- {name}: {desc}" for name, desc in META_SKILLS.items()
        )
        installed_lines = "\n".join(
            f"- {s.name}: {s.description}" for s in self._skills
        ) if self._skills else "(none installed)"

        return (
            f'Given this user message: "{text}"\n\n'
            "Always-available skills (ALWAYS consider these regardless of installed skills):\n"
            f"{meta_lines}\n\n"
            "Installed skills:\n"
            f"{installed_lines}\n\n"
            "Which skill name best matches the user's intent?\n"
            'Reply with ONLY the skill name, or "none" if nothing matches.'
        )

    def _match_with_claude(self, text: str, prompt: Optional[str] = None) -> Optional[str]:
        if prompt is None:
            prompt = self._build_routing_prompt(text)
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
