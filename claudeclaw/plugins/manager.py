# claudeclaw/plugins/manager.py
from __future__ import annotations

import importlib.metadata
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
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


def _plugins_registry_path() -> Path:
    return get_settings().config_dir / "plugins.yaml"


def _load_registry() -> list[PluginRecord]:
    path = _plugins_registry_path()
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text()) or {}
    return [PluginRecord(**item) for item in data.get("plugins", [])]


def _save_registry(records: list[PluginRecord]) -> None:
    path = _plugins_registry_path()
    path.write_text(
        yaml.dump(
            {"plugins": [r.model_dump() for r in records]},
            default_flow_style=False,
        )
    )


def _verify_signature(name: str, package_path: Path) -> bool:
    """Stub: signature verification deferred to Plan 6 (Security)."""
    import warnings
    warnings.warn(
        f"Plugin '{name}' signature not verified (Plan 6). Install at your own risk.",
        stacklevel=3,
    )
    return True


def install(name: str) -> None:
    """Install a ClaudeClaw plugin from PyPI."""
    package_name = f"claudeclaw-plugin-{name}"

    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", package_name],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"pip install {package_name} failed:\n{result.stderr}")

    dist = importlib.metadata.distribution(package_name)
    package_path = Path(dist.locate_file("."))
    manifest_path = package_path / "claudeclaw_plugin.json"
    manifest = parse_manifest(manifest_path)

    _verify_signature(name, package_path)

    from claudeclaw.mcps.config import add_mcp, load_mcps
    existing_names = {m.name for m in load_mcps()}
    for mcp_cfg in manifest.mcps:
        if mcp_cfg.name not in existing_names:
            add_mcp(mcp_cfg)

    skills_dir = get_settings().skills_dir
    copied_skills: list[str] = []
    for skill_rel in manifest.skills:
        src = package_path / skill_rel
        dest = skills_dir / Path(skill_rel).name
        if src.exists():
            shutil.copy2(src, dest)
            copied_skills.append(Path(skill_rel).stem)

    records = _load_registry()
    records.append(PluginRecord(
        name=manifest.name,
        version=manifest.version,
        package=package_name,
        installed_at=datetime.now(tz=timezone.utc).isoformat(),
        mcps=[m.name for m in manifest.mcps],
        skills=copied_skills,
    ))
    _save_registry(records)

    print(f"Plugin '{name}' installed (v{manifest.version}). "
          f"MCPs: {len(manifest.mcps)}, Skills: {len(copied_skills)}.")


def list_plugins() -> list[PluginRecord]:
    """Return all installed plugins."""
    return _load_registry()


def uninstall(name: str) -> None:
    """Uninstall a ClaudeClaw plugin."""
    records = _load_registry()
    record = next((r for r in records if r.name == name), None)
    if record is None:
        raise KeyError(f"Plugin '{name}' is not installed.")

    from claudeclaw.mcps.config import remove_mcp
    for mcp_name in record.mcps:
        try:
            remove_mcp(mcp_name)
        except KeyError:
            pass

    skills_dir = get_settings().skills_dir
    for skill_stem in record.skills:
        skill_file = skills_dir / f"{skill_stem}.md"
        if skill_file.exists():
            skill_file.unlink()

    _save_registry([r for r in records if r.name != name])

    subprocess.run(
        [sys.executable, "-m", "pip", "uninstall", record.package, "-y"],
        capture_output=True,
    )

    print(f"Plugin '{name}' uninstalled.")
