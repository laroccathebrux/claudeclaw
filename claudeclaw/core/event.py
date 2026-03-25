# claudeclaw/core/event.py
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class Event:
    """Normalized input event from any channel or trigger."""
    text: str                          # raw message text from user or trigger payload
    channel: str                       # "cli", "telegram", "cron", "webhook", etc.
    user_id: Optional[str] = None      # channel-specific user identifier
    conversation_id: Optional[str] = None
    timestamp: datetime = field(default_factory=datetime.utcnow)
    metadata: dict = field(default_factory=dict)


@dataclass
class Response:
    """Outbound response to send back via the originating channel."""
    text: str
    event: Event                       # the original event this responds to
