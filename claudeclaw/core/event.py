# claudeclaw/core/event.py
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from claudeclaw.channels.base import ChannelAdapter


@dataclass
class Event:
    """Normalized input event from any channel or trigger."""
    text: str                          # raw message text from user or trigger payload
    channel: str                       # "cli", "telegram", "cron", "webhook", etc.
    channel_adapter: Optional["ChannelAdapter"] = field(default=None, repr=False)
    user_id: Optional[str] = None      # channel-specific user identifier
    conversation_id: Optional[str] = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict = field(default_factory=dict)
    source: str = "cli"                # "cli" | "telegram" | "cron" | "webhook" | "manual"
    skill_name: Optional[str] = None   # pre-resolved for cron/webhook/manual events
    payload: dict = field(default_factory=dict)
    raw: dict = field(default_factory=dict)  # original webhook payload from adapter
    channel_reply_fn: Optional[Any] = None  # None for headless scheduled events


@dataclass
class Response:
    """Outbound response to send back via the originating channel."""
    text: str
    channel: str = ""
    user_id: Optional[str] = None
    chat_id: Optional[Any] = None
    metadata: dict[str, Any] = field(default_factory=dict)
    event: Optional["Event"] = None  # TODO(Plan 3): remove — kept for Plan 1 backward compatibility
