# claudeclaw/plugins/manager.py
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel

from claudeclaw.config.settings import get_settings
from claudeclaw.mcps.config import MCPConfig


class PluginManifest(BaseModel):
    name: str
    version: str
    description: str
    mcps: list[MCPConfig] = []
    skills: list[str] = []
    auth_handler: Optional[str] = None


class PluginRecord(BaseModel):
    name: str
    version: str
    package: str
    installed_at: str  # ISO datetime string
    mcps: list[str] = []
    skills: list[str] = []


def parse_manifest(path: Path) -> PluginManifest:
    """Parse a claudeclaw_plugin.json file into a PluginManifest."""
    if not path.exists():
        raise FileNotFoundError(f"Plugin manifest not found: {path}")
    data = json.loads(path.read_text())
    return PluginManifest(**data)
