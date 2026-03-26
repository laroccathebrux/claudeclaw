# claudeclaw/mcps/config.py
from __future__ import annotations

from pathlib import Path
from typing import Literal, Optional, TYPE_CHECKING

import yaml
from pydantic import BaseModel

from claudeclaw.config.settings import get_settings

if TYPE_CHECKING:
    from claudeclaw.skills.loader import SkillManifest


class MCPConfig(BaseModel):
    name: str
    command: str
    args: list[str] = []
    env: dict[str, str] = {}
    scope: Literal["global", "agent"] = "agent"


def _mcps_path() -> Path:
    return get_settings().config_dir / "mcps.yaml"


def load_mcps() -> list[MCPConfig]:
    path = _mcps_path()
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text()) or {}
    return [MCPConfig(**item) for item in data.get("mcps", [])]


def save_mcps(mcps: list[MCPConfig]) -> None:
    path = _mcps_path()
    path.write_text(yaml.dump({"mcps": [m.model_dump() for m in mcps]}, default_flow_style=False))


def add_mcp(config: MCPConfig) -> None:
    mcps = load_mcps()
    if any(m.name == config.name for m in mcps):
        raise ValueError(f"MCP '{config.name}' already exists. Use remove first.")
    mcps.append(config)
    save_mcps(mcps)


def remove_mcp(name: str) -> None:
    mcps = load_mcps()
    remaining = [m for m in mcps if m.name != name]
    if len(remaining) == len(mcps):
        raise KeyError(f"MCP '{name}' not found.")
    save_mcps(remaining)


def resolve_mcps(skill: "SkillManifest") -> list[MCPConfig]:
    """Return MCPs to inject for this skill: all globals + declared agent MCPs."""
    all_mcps = load_mcps()
    agent_names: set[str] = set((skill.mcps or []) + (skill.mcps_agent or []))
    resolved = []
    for m in all_mcps:
        if m.scope == "global":
            resolved.append(m)
        elif m.scope == "agent" and m.name in agent_names:
            resolved.append(m)
    return resolved
