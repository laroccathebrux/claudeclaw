from __future__ import annotations

import yaml
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from claudeclaw.config.settings import get_settings


class ScheduleManager:
    def __init__(self, sdk_client=None, settings=None):
        self._client = sdk_client
        self._settings = settings or get_settings()
        self._schedules_file = self._settings.config_dir / "schedules.yaml"
        self._triggers_file = self._settings.config_dir / "triggers.yaml"

    def _load_schedules(self) -> dict:
        if not self._schedules_file.exists():
            return {}
        return yaml.safe_load(self._schedules_file.read_text()) or {}

    def _save_schedules(self, data: dict) -> None:
        self._schedules_file.parent.mkdir(parents=True, exist_ok=True)
        self._schedules_file.write_text(yaml.dump(data, default_flow_style=False))

    def _load_triggers(self) -> dict:
        if not self._triggers_file.exists():
            return {}
        return yaml.safe_load(self._triggers_file.read_text()) or {}

    def _save_triggers(self, data: dict) -> None:
        self._triggers_file.parent.mkdir(parents=True, exist_ok=True)
        self._triggers_file.write_text(yaml.dump(data, default_flow_style=False))

    def _now_iso(self) -> str:
        return datetime.now(tz=timezone.utc).isoformat()

    async def register_crons(self, skills: list) -> None:
        data = self._load_schedules()

        for skill in skills:
            if getattr(skill, "trigger", None) != "cron":
                continue
            schedule = skill.schedule
            existing = data.get(skill.name)

            if existing and existing.get("schedule") == schedule:
                continue

            if existing:
                await self._client.beta.cron_delete(cron_id=existing["cron_id"])

            result = await self._client.beta.cron_create(
                schedule=schedule,
                metadata={"skill_name": skill.name},
            )
            data[skill.name] = {
                "cron_id": result["cron_id"],
                "schedule": schedule,
                "registered_at": self._now_iso(),
            }

        self._save_schedules(data)

    async def deregister_skill(self, skill_name: str) -> None:
        schedules = self._load_schedules()
        if skill_name in schedules:
            await self._client.beta.cron_delete(cron_id=schedules[skill_name]["cron_id"])
            del schedules[skill_name]
            self._save_schedules(schedules)

        triggers = self._load_triggers()
        triggers_to_remove = [
            tid for tid, meta in triggers.items()
            if meta.get("skill_name") == skill_name
        ]
        for tid in triggers_to_remove:
            del triggers[tid]
        if triggers_to_remove:
            self._save_triggers(triggers)
