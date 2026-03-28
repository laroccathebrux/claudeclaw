"""Agent registry — stores and retrieves agent metadata separately from skill files."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
import yaml


@dataclass
class AgentRecord:
    name: str
    description: str
    skill_name: str
    schedule: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat()[:10])


class AgentRegistry:
    """
    Persists agent metadata in ~/.claudeclaw/agents/agents.yaml.
    One agent = one record, linked to a skill by skill_name.
    """

    def __init__(self, agents_dir: Optional[Path] = None):
        if agents_dir is None:
            from claudeclaw.config.settings import get_settings
            agents_dir = get_settings().agents_dir
        self._dir = Path(agents_dir)
        self._file = self._dir / "agents.yaml"

    def _load(self) -> list[dict]:
        if not self._file.exists():
            return []
        return yaml.safe_load(self._file.read_text()) or []

    def _save(self, agents: list[dict]) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        self._file.write_text(yaml.dump(agents, default_flow_style=False, allow_unicode=True))

    def list_agents(self) -> list[AgentRecord]:
        return [
            AgentRecord(
                name=a["name"],
                description=a.get("description", ""),
                skill_name=a.get("skill_name", a["name"]),
                schedule=a.get("schedule"),
                created_at=a.get("created_at", ""),
            )
            for a in self._load()
        ]

    def add(self, record: AgentRecord) -> None:
        agents = self._load()
        agents = [a for a in agents if a["name"] != record.name]  # upsert
        agents.append({
            "name": record.name,
            "description": record.description,
            "skill_name": record.skill_name,
            "schedule": record.schedule,
            "created_at": record.created_at,
        })
        self._save(agents)

    def remove(self, name: str) -> None:
        agents = self._load()
        new = [a for a in agents if a["name"] != name]
        if len(new) == len(agents):
            raise KeyError(f"Agent '{name}' not found.")
        self._save(new)

    def find(self, name: str) -> Optional[AgentRecord]:
        for a in self.list_agents():
            if a.name == name:
                return a
        return None
