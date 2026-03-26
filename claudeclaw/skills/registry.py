import logging
from pathlib import Path
from typing import Optional

from claudeclaw.skills.loader import load_skill, SkillManifest, SkillLoadError
from claudeclaw.config.settings import get_settings

logger = logging.getLogger(__name__)

# Bundled native skills shipped with the package
_BUNDLED_NATIVE_DIR = Path(__file__).parent / "native"


class SkillRegistry:
    def __init__(
        self,
        user_skills_dir: Optional[Path] = None,
        native_skills_dir: Optional[Path] = None,
        # Backward-compat alias for user_skills_dir
        skills_dir: Optional[Path] = None,
    ):
        # skills_dir is the old name; user_skills_dir takes precedence if both given
        self._user_dir = user_skills_dir or skills_dir or get_settings().skills_dir
        # If native_skills_dir is not provided, default to the bundled native directory
        self._native_dir = native_skills_dir if native_skills_dir is not None else _BUNDLED_NATIVE_DIR

    def _load_from_dir(self, directory: Path, is_native: bool) -> dict[str, SkillManifest]:
        skills: dict[str, SkillManifest] = {}
        if not directory or not directory.exists():
            return skills
        for path in sorted(directory.glob("*.md")):
            try:
                skill = load_skill(path)
                skill.is_native = is_native
                skills[skill.name] = skill
            except SkillLoadError as exc:
                logger.warning("Skipping invalid skill %s: %s", path, exc)
        return skills

    def all_skills(self) -> list[SkillManifest]:
        """Return all skills: native first, user skills override by name."""
        merged: dict[str, SkillManifest] = {}
        if self._native_dir:
            merged.update(self._load_from_dir(self._native_dir, is_native=True))
        merged.update(self._load_from_dir(self._user_dir, is_native=False))
        return list(merged.values())

    def list_skills(self) -> list[SkillManifest]:
        """Backward-compatible alias for all_skills()."""
        return self.all_skills()

    def list_all(self) -> list[SkillManifest]:
        """Alias for all_skills() — returns all skills from native + user dirs."""
        return self.all_skills()

    def reload(self) -> list[SkillManifest]:
        """Force re-scan of skills directories. Returns all skills after rescan."""
        return self.all_skills()

    def find(self, name: str) -> Optional[SkillManifest]:
        for skill in self.all_skills():
            if skill.name == name:
                return skill
        return None
