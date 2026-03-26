# claudeclaw/skills/generator.py
import re
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml

from claudeclaw.config.settings import get_settings

logger = logging.getLogger(__name__)


@dataclass
class WizardOutput:
    task_description: str
    systems: list[str]
    credentials: list[str]
    trigger: str                          # "on-demand" | "cron" | "webhook"
    schedule: Optional[str]              # cron expression, only for trigger: cron
    autonomy: str                         # "ask" | "notify" | "autonomous"
    trigger_id: Optional[str] = None     # set automatically for webhook trigger


def _to_slug(text: str) -> str:
    """Convert free text to a kebab-case slug (max 40 chars)."""
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s-]", "", text)
    text = re.sub(r"\s+", "-", text.strip())
    text = re.sub(r"-+", "-", text)
    return text[:40].rstrip("-")


def _deduplicate_path(base: Path, slug: str) -> Path:
    candidate = base / f"{slug}.md"
    if not candidate.exists():
        return candidate
    counter = 2
    while True:
        candidate = base / f"{slug}-{counter}.md"
        if not candidate.exists():
            return candidate
        counter += 1


def _build_description(task_description: str) -> str:
    """One-line description: truncate task description to 100 chars."""
    desc = task_description.strip().split("\n")[0]
    return desc[:100]


def _build_body(output: WizardOutput) -> str:
    lines = [
        f"# {_build_description(output.task_description)}",
        "",
        "## Task",
        output.task_description,
        "",
    ]
    if output.systems:
        lines += [
            "## Systems",
            "This agent has access to the following systems:",
        ]
        for system in output.systems:
            lines.append(f"- {system}")
        lines.append("")
    lines += [
        "## Instructions",
        "Perform the task described above. Use the credentials provided in your context.",
        "Follow the autonomy level set in your configuration: if 'ask', always confirm",
        "before taking irreversible actions. If 'notify', act and report results.",
        "If 'autonomous', act silently and only contact the user on errors.",
    ]
    return "\n".join(lines)


class SkillGenerator:
    """
    Converts wizard output into a valid .md skill file.
    Writes to ~/.claudeclaw/skills/<slug>.md.
    """

    def __init__(self, skills_dir: Optional[Path] = None):
        self._dir = skills_dir or get_settings().skills_dir

    def generate(self, output: WizardOutput) -> Path:
        slug = _to_slug(output.task_description)
        if not slug:
            slug = "new-agent"

        path = _deduplicate_path(self._dir, slug)

        # Build frontmatter
        fm: dict = {
            "name": path.stem,
            "description": _build_description(output.task_description),
            "trigger": output.trigger,
            "autonomy": output.autonomy,
            "tools": [],
            "credentials": output.credentials,
            "shell-policy": "none",
        }

        if output.trigger == "cron" and output.schedule:
            fm["schedule"] = output.schedule

        if output.trigger == "webhook":
            trigger_id = output.trigger_id or f"{path.stem}-webhook"
            fm["trigger-id"] = trigger_id

        body = _build_body(output)
        content = f"---\n{yaml.dump(fm, default_flow_style=False)}---\n\n{body}\n"
        path.write_text(content)
        logger.info("Generated skill file: %s", path)
        return path
