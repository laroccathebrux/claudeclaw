import logging
from pathlib import Path
from typing import Optional

from claudeclaw.skills.loader import load_skill, SkillManifest, SkillLoadError
from claudeclaw.config.settings import get_settings

logger = logging.getLogger(__name__)


class SkillRegistry:
    def __init__(self, skills_dir: Optional[Path] = None):
        self._dir = skills_dir or get_settings().skills_dir

    def list_skills(self) -> list[SkillManifest]:
        skills = []
        for md_file in sorted(self._dir.glob("*.md")):
            try:
                skills.append(load_skill(md_file))
            except SkillLoadError as e:
                logger.warning("Skipping invalid skill %s: %s", md_file.name, e)
        return skills

    def find(self, name: str) -> Optional[SkillManifest]:
        for skill in self.list_skills():
            if skill.name == name:
                return skill
        return None
