from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional
import frontmatter


VALID_TRIGGERS = {"on-demand", "cron", "webhook"}
VALID_AUTONOMY = {"ask", "notify", "autonomous"}
VALID_SHELL_POLICIES = {"none", "read-only", "restricted", "full"}


class SkillLoadError(Exception):
    pass


@dataclass
class SkillManifest:
    name: str
    description: str
    trigger: str
    autonomy: str
    shell_policy: str
    body: str
    schedule: Optional[str] = None
    trigger_id: Optional[str] = None
    plugins: list[str] = field(default_factory=list)
    mcps: list[str] = field(default_factory=list)
    mcps_agent: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    credentials: list[str] = field(default_factory=list)
    source_path: Optional[Path] = None
    is_native: bool = False


def load_skill(path: Path) -> SkillManifest:
    try:
        post = frontmatter.load(str(path))
    except Exception as e:
        raise SkillLoadError(f"Failed to parse {path}: {e}") from e

    meta = post.metadata
    body = post.content

    def require(key: str):
        if key not in meta:
            raise SkillLoadError(f"Missing required frontmatter field '{key}' in {path.name}")
        return meta[key]

    name = require("name")
    description = require("description")
    trigger = require("trigger")
    autonomy = require("autonomy")
    shell_policy = meta.get("shell-policy", "none")

    if trigger not in VALID_TRIGGERS:
        raise SkillLoadError(f"Invalid trigger '{trigger}' in {path.name}. Must be one of {VALID_TRIGGERS}")

    if autonomy not in VALID_AUTONOMY:
        raise SkillLoadError(f"Invalid autonomy '{autonomy}' in {path.name}. Must be one of {VALID_AUTONOMY}")

    if shell_policy not in VALID_SHELL_POLICIES:
        raise SkillLoadError(f"Invalid shell-policy '{shell_policy}' in {path.name}")

    schedule = meta.get("schedule")
    if trigger == "cron" and not schedule:
        raise SkillLoadError(f"Skill '{name}' has trigger: cron but no schedule field")

    return SkillManifest(
        name=name,
        description=description,
        trigger=trigger,
        autonomy=autonomy,
        shell_policy=shell_policy,
        body=body,
        schedule=schedule,
        trigger_id=meta.get("trigger-id"),
        plugins=meta.get("plugins") or [],
        mcps=meta.get("mcps") or [],
        mcps_agent=meta.get("mcps_agent") or [],
        tools=meta.get("tools") or [],
        credentials=meta.get("credentials") or [],
        source_path=path,
    )
