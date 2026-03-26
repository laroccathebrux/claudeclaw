import json
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from claudeclaw.config.settings import get_settings

logger = logging.getLogger(__name__)

_CONVERSATIONS_SUBDIR = "conversations"


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _key_to_filename(channel: str, user_id: str) -> str:
    safe_channel = channel.replace("/", "-")
    safe_user = str(user_id).replace("/", "-")
    return f"{safe_channel}__{safe_user}.json"


@dataclass
class ConversationState:
    channel: str
    user_id: str
    skill_name: str
    step: int
    data: dict
    history: list
    created_at: str = field(default_factory=_utcnow_iso)
    updated_at: str = field(default_factory=_utcnow_iso)


class ConversationStore:
    """
    Persists multi-turn conversation state across subagent invocations.
    Files stored at: ~/.claudeclaw/config/conversations/<channel>__<user_id>.json
    """

    def __init__(self, base_dir: Optional[Path] = None):
        if base_dir is not None:
            self._dir = base_dir
        else:
            settings = get_settings()
            self._dir = settings.config_dir / _CONVERSATIONS_SUBDIR
        self._dir.mkdir(parents=True, exist_ok=True)

    def _path(self, channel: str, user_id: str) -> Path:
        return self._dir / _key_to_filename(channel, user_id)

    def get(self, channel: str, user_id: str) -> Optional[ConversationState]:
        p = self._path(channel, user_id)
        if not p.exists():
            return None
        try:
            data = json.loads(p.read_text())
            return ConversationState(**data)
        except Exception as e:
            logger.warning("Failed to load conversation %s: %s", p, e)
            return None

    def save(self, state: ConversationState, update_timestamp: bool = True) -> None:
        if update_timestamp:
            state.updated_at = _utcnow_iso()
        p = self._path(state.channel, state.user_id)
        p.write_text(json.dumps(asdict(state), indent=2))

    def clear(self, channel: str, user_id: str) -> None:
        p = self._path(channel, user_id)
        if p.exists():
            p.unlink()

    def has_active(self, channel: str, user_id: str) -> bool:
        return self._path(channel, user_id).exists()

    def list_active(self) -> list[ConversationState]:
        states = []
        for f in self._dir.glob("*.json"):
            try:
                data = json.loads(f.read_text())
                states.append(ConversationState(**data))
            except Exception as e:
                logger.warning("Skipping corrupt conversation file %s: %s", f, e)
        return states

    def clear_expired(self, max_idle_minutes: int = 30) -> int:
        removed = 0
        cutoff = max_idle_minutes * 60
        now = datetime.now(timezone.utc)
        for state in self.list_active():
            try:
                updated = datetime.fromisoformat(state.updated_at.rstrip("Z")).replace(
                    tzinfo=timezone.utc
                )
                idle_seconds = (now - updated).total_seconds()
                if idle_seconds > cutoff:
                    self.clear(state.channel, state.user_id)
                    removed += 1
            except Exception as e:
                logger.warning("Could not check expiry for conversation: %s", e)
        return removed
