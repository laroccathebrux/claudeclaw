# ClaudeClaw — Plan 2: Telegram Channel Adapter + POP Native Skill

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Telegram as a live messaging channel, refactor the orchestrator to consume events from a shared `asyncio.Queue` (enabling multiple concurrent channels), add the native skills directory, and author the POP skill — so a user can connect Telegram, say "teach me to automate X", and receive a generated skill file.

**Architecture:** A `ChannelManager` reads `channels.yaml`, instantiates adapters, and starts each as an asyncio task feeding a shared `asyncio.Queue[Event]`. The `Orchestrator` consumes from this queue. `TelegramAdapter` bridges `python-telegram-bot` callbacks to the shared queue. `SkillRegistry` is extended to load native skills bundled inside the package. The `pop.md` skill file encodes the full wizard flow as natural language instructions for the Claude SDK subagent.

**Tech Stack:** Python 3.11+, `anthropic` SDK, `click`, `python-frontmatter`, `keyring`, `cryptography`, `pydantic`, `pyyaml`, `pytest`, `pytest-asyncio`, `pytest-mock`, **`python-telegram-bot>=21.0`** (new)

**Spec reference:** `docs/superpowers/specs/2026-03-25-plan-2-telegram-pop-spec.md`

---

## File Map

```
claudeclaw/
├── pyproject.toml                          ← add python-telegram-bot>=21.0
├── claudeclaw/
│   ├── channels/
│   │   ├── base.py                         ← (Plan 1) ChannelAdapter ABC — update Event import
│   │   ├── cli_adapter.py                  ← (Plan 1) update to push to queue
│   │   ├── manager.py                      ← NEW: load channels.yaml, start adapters
│   │   └── telegram_adapter.py             ← NEW: TelegramAdapter
│   ├── core/
│   │   ├── event.py                        ← UPDATE: add channel_adapter field
│   │   ├── orchestrator.py                 ← UPDATE: asyncio.Queue-based loop
│   │   └── router.py                       ← UPDATE: native skill intent priority
│   ├── skills/
│   │   ├── registry.py                     ← UPDATE: load from native + user dirs
│   │   └── native/
│   │       ├── __init__.py                 ← NEW: empty
│   │       ├── pop.md                      ← NEW: POP skill instructions
│   │       └── agent-creator.md            ← NEW: stub placeholder for Plan 3
│   └── cli.py                              ← UPDATE: add `channel` command group
└── tests/
    ├── test_event_channel_adapter.py       ← NEW
    ├── test_channel_manager.py             ← NEW
    ├── test_telegram_adapter.py            ← NEW
    ├── test_channel_cli.py                 ← NEW
    ├── test_skill_registry_native.py       ← NEW
    └── test_router_native_intents.py       ← NEW
```

---

## Task 1: Event + Orchestrator Queue Refactor

**Files:**
- Update: `claudeclaw/core/event.py`
- Update: `claudeclaw/core/orchestrator.py`

### Step 1.1 — Write failing test for updated Event

- [ ] Create `tests/test_event_channel_adapter.py`:

```python
# tests/test_event_channel_adapter.py
import pytest
from claudeclaw.core.event import Event


class _FakeAdapter:
    pass


def test_event_carries_channel_adapter():
    adapter = _FakeAdapter()
    event = Event(
        text="hello",
        channel="telegram",
        channel_adapter=adapter,
        metadata={"chat_id": 42},
    )
    assert event.channel_adapter is adapter
    assert event.metadata["chat_id"] == 42


def test_event_channel_adapter_defaults_to_none():
    event = Event(text="hello", channel="cli")
    assert event.channel_adapter is None
```

### Step 1.2 — Run to verify failure

- [ ] Run:

```bash
pytest tests/test_event_channel_adapter.py -v
```

Expected: `ImportError` or `TypeError` — `channel_adapter` field does not exist yet.

### Step 1.3 — Update Event dataclass

- [ ] Edit `claudeclaw/core/event.py` to add `channel_adapter` and `metadata` fields:

```python
# claudeclaw/core/event.py
from __future__ import annotations
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from claudeclaw.channels.base import ChannelAdapter


@dataclass
class Event:
    text: str
    channel: str
    channel_adapter: Optional["ChannelAdapter"] = field(default=None, repr=False)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Response:
    text: str
    channel: str
    chat_id: Optional[Any] = None
    metadata: dict[str, Any] = field(default_factory=dict)
```

### Step 1.4 — Run to verify pass

- [ ] Run:

```bash
pytest tests/test_event_channel_adapter.py -v
```

Expected: 2 PASSED.

### Step 1.5 — Write failing test for queue-based orchestrator

- [ ] Add to `tests/test_channel_manager.py` (create file):

```python
# tests/test_channel_manager.py
import asyncio
import pytest
from claudeclaw.core.event import Event, Response


async def test_orchestrator_processes_event_from_queue(mocker):
    """Orchestrator should consume from a queue and call process."""
    from claudeclaw.core.orchestrator import Orchestrator

    queue = asyncio.Queue()
    mock_adapter = mocker.AsyncMock()
    mock_adapter.send = mocker.AsyncMock()

    event = Event(text="hello", channel="cli", channel_adapter=mock_adapter)
    await queue.put(event)

    orchestrator = Orchestrator(skill_registry=mocker.MagicMock(), credential_store=mocker.MagicMock())
    mocker.patch.object(orchestrator, "_process", return_value=Response(text="ok", channel="cli"))

    # run with a sentinel to stop after one event
    await queue.put(None)  # sentinel
    await orchestrator.run(queue, stop_sentinel=True)

    mock_adapter.send.assert_awaited_once()
```

### Step 1.6 — Run to verify failure

- [ ] Run:

```bash
pytest tests/test_channel_manager.py::test_orchestrator_processes_event_from_queue -v
```

Expected: `ImportError` or `TypeError`.

### Step 1.7 — Update Orchestrator to use asyncio.Queue

- [ ] Edit `claudeclaw/core/orchestrator.py`. Replace the single-adapter loop with:

```python
# claudeclaw/core/orchestrator.py  (updated run method)
import asyncio
from claudeclaw.core.event import Event, Response
from claudeclaw.skills.registry import SkillRegistry
from claudeclaw.auth.keyring import CredentialStore


class Orchestrator:
    def __init__(self, skill_registry: SkillRegistry, credential_store: CredentialStore):
        self.registry = skill_registry
        self.credential_store = credential_store

    async def run(self, event_queue: asyncio.Queue, stop_sentinel: bool = False):
        """
        Consume events from queue. If stop_sentinel=True, stop when None is dequeued
        (used in tests). In production, runs forever.
        """
        while True:
            event: Event = await event_queue.get()
            if stop_sentinel and event is None:
                break
            response = await self._process(event)
            if event.channel_adapter is not None:
                await event.channel_adapter.send(response)
            event_queue.task_done()

    async def _process(self, event: Event) -> Response:
        """Route event to skill, dispatch subagent, return response."""
        from claudeclaw.core.router import route
        from claudeclaw.subagent.dispatch import dispatch

        skill = route(event, self.registry)
        result = await dispatch(skill, event, self.credential_store)
        return Response(
            text=result,
            channel=event.channel,
            chat_id=event.metadata.get("chat_id"),
        )
```

### Step 1.8 — Run to verify pass

- [ ] Run:

```bash
pytest tests/test_channel_manager.py::test_orchestrator_processes_event_from_queue -v
```

Expected: 1 PASSED.

### Step 1.9 — Commit

- [ ] Run:

```bash
git add claudeclaw/core/event.py claudeclaw/core/orchestrator.py \
      tests/test_event_channel_adapter.py tests/test_channel_manager.py
git commit -m "feat: refactor orchestrator to asyncio.Queue; add channel_adapter to Event"
```

---

## Task 2: Channel Manager

**Files:**
- Create: `claudeclaw/channels/manager.py`

### Step 2.1 — Write failing tests

- [ ] Add to `tests/test_channel_manager.py`:

```python
# append to tests/test_channel_manager.py
import asyncio
import pytest
from pathlib import Path
import yaml


def _write_channels_yaml(path: Path, channels: list[dict]):
    config = {"channels": channels}
    path.write_text(yaml.dump(config))


async def test_manager_load_channels_reads_yaml(tmp_path, mocker):
    from claudeclaw.channels.manager import ChannelManager

    channels_file = tmp_path / "channels.yaml"
    _write_channels_yaml(channels_file, [{"type": "cli", "enabled": True}])

    store = mocker.MagicMock()
    manager = ChannelManager(config_path=channels_file, credential_store=store)
    adapters = manager.load_channels()
    assert len(adapters) == 1


async def test_manager_skips_disabled_channels(tmp_path, mocker):
    from claudeclaw.channels.manager import ChannelManager

    channels_file = tmp_path / "channels.yaml"
    _write_channels_yaml(channels_file, [
        {"type": "cli", "enabled": True},
        {"type": "telegram", "enabled": False},
    ])

    store = mocker.MagicMock()
    manager = ChannelManager(config_path=channels_file, credential_store=store)
    adapters = manager.load_channels()
    assert len(adapters) == 1


async def test_manager_start_all_feeds_queue(tmp_path, mocker):
    from claudeclaw.channels.manager import ChannelManager

    channels_file = tmp_path / "channels.yaml"
    _write_channels_yaml(channels_file, [{"type": "cli", "enabled": True}])

    fake_event = mocker.MagicMock()
    mock_adapter = mocker.AsyncMock()

    async def fake_receive():
        yield fake_event

    mock_adapter.receive = fake_receive
    mocker.patch("claudeclaw.channels.manager.ChannelManager.load_channels",
                 return_value=[mock_adapter])

    store = mocker.MagicMock()
    manager = ChannelManager(config_path=channels_file, credential_store=store)
    queue = asyncio.Queue()

    tasks = await manager.start_all(queue)
    await asyncio.sleep(0.05)
    for t in tasks:
        t.cancel()

    assert not queue.empty()
    assert await queue.get() is fake_event
```

### Step 2.2 — Run to verify failure

- [ ] Run:

```bash
pytest tests/test_channel_manager.py -v -k "test_manager"
```

Expected: `ImportError` — `claudeclaw.channels.manager` does not exist.

### Step 2.3 — Implement ChannelManager

- [ ] Create `claudeclaw/channels/manager.py`:

```python
# claudeclaw/channels/manager.py
import asyncio
import logging
from pathlib import Path
from typing import Optional

import yaml

from claudeclaw.channels.base import ChannelAdapter
from claudeclaw.auth.keyring import CredentialStore

logger = logging.getLogger(__name__)

RESTART_DELAY_SECONDS = 5


class ChannelManager:
    def __init__(self, config_path: Path, credential_store: CredentialStore):
        self._config_path = config_path
        self._credential_store = credential_store

    def load_channels(self) -> list[ChannelAdapter]:
        """Read channels.yaml and return instantiated, enabled adapters."""
        if not self._config_path.exists():
            return []

        data = yaml.safe_load(self._config_path.read_text()) or {}
        channel_configs = data.get("channels", [])
        adapters: list[ChannelAdapter] = []

        for cfg in channel_configs:
            if not cfg.get("enabled", False):
                continue
            adapter = self._build_adapter(cfg["type"])
            if adapter is not None:
                adapters.append(adapter)

        return adapters

    def _build_adapter(self, channel_type: str) -> Optional[ChannelAdapter]:
        if channel_type == "cli":
            from claudeclaw.channels.cli_adapter import CLIAdapter
            return CLIAdapter()
        if channel_type == "telegram":
            from claudeclaw.channels.telegram_adapter import TelegramAdapter
            token = self._credential_store.get("telegram-bot-token")
            if not token:
                logger.error(
                    "Telegram token not found in credential store. "
                    "Run: claudeclaw channel add telegram --token <TOKEN>"
                )
                return None
            return TelegramAdapter(token=token)
        logger.warning("Unknown channel type: %s", channel_type)
        return None

    async def start_all(self, event_queue: asyncio.Queue) -> list[asyncio.Task]:
        """Start each adapter as an asyncio.Task feeding events to event_queue."""
        adapters = self.load_channels()
        tasks = []
        for adapter in adapters:
            task = asyncio.create_task(
                self._run_adapter(adapter, event_queue),
                name=f"channel-{adapter.__class__.__name__}",
            )
            tasks.append(task)
        return tasks

    async def _run_adapter(self, adapter: ChannelAdapter, queue: asyncio.Queue):
        """Run an adapter forever, restarting on error with back-off."""
        while True:
            try:
                async for event in adapter.receive():
                    await queue.put(event)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.exception("Adapter %s crashed: %s. Restarting in %ds.",
                                 adapter.__class__.__name__, exc, RESTART_DELAY_SECONDS)
                await asyncio.sleep(RESTART_DELAY_SECONDS)
```

### Step 2.4 — Run to verify pass

- [ ] Run:

```bash
pytest tests/test_channel_manager.py -v -k "test_manager"
```

Expected: 3 PASSED.

### Step 2.5 — Commit

- [ ] Run:

```bash
git add claudeclaw/channels/manager.py tests/test_channel_manager.py
git commit -m "feat: ChannelManager loads channels.yaml and fans events into asyncio.Queue"
```

---

## Task 3: Telegram Adapter

**Files:**
- Create: `claudeclaw/channels/telegram_adapter.py`
- Create: `tests/test_telegram_adapter.py`

### Step 3.1 — Add dependency

- [ ] Edit `pyproject.toml` — add `"python-telegram-bot>=21.0"` to `dependencies`:

```toml
dependencies = [
    "anthropic>=0.40.0",
    "click>=8.1",
    "python-frontmatter>=1.1",
    "pydantic>=2.0",
    "keyring>=25.0",
    "cryptography>=42.0",
    "pyyaml>=6.0",
    "httpx>=0.27",
    "python-telegram-bot>=21.0",
]
```

- [ ] Run:

```bash
pip install "python-telegram-bot>=21.0"
```

### Step 3.2 — Write failing tests

- [ ] Create `tests/test_telegram_adapter.py`:

```python
# tests/test_telegram_adapter.py
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from claudeclaw.channels.telegram_adapter import TelegramAdapter
from claudeclaw.core.event import Event, Response


@pytest.fixture
def adapter():
    return TelegramAdapter(token="fake-token-123")


def test_adapter_instantiates_with_token(adapter):
    assert adapter._token == "fake-token-123"


async def test_receive_yields_event_from_message(adapter, mocker):
    """Simulate PTB calling the message handler; verify Event is yielded."""
    fake_message = MagicMock()
    fake_message.text = "hello bot"
    fake_message.chat_id = 99
    fake_message.from_user.id = 7

    # Seed the internal queue directly (bypasses PTB network layer)
    await adapter._internal_queue.put(fake_message)
    await adapter._internal_queue.put(None)  # sentinel to stop

    events = []
    async for event in adapter.receive():
        events.append(event)
        break  # take only the first one

    assert len(events) == 1
    assert events[0].text == "hello bot"
    assert events[0].channel == "telegram"
    assert events[0].metadata["chat_id"] == 99


async def test_send_calls_bot_send_message(adapter, mocker):
    mock_bot = AsyncMock()
    adapter._bot = mock_bot

    response = Response(text="reply text", channel="telegram", chat_id=99)
    await adapter.send(response)

    mock_bot.send_message.assert_awaited_once_with(chat_id=99, text="reply text")


async def test_on_message_puts_to_internal_queue(adapter):
    """Verify the PTB handler callback puts the message onto the internal queue."""
    fake_update = MagicMock()
    fake_update.message.text = "test"
    fake_update.message.chat_id = 1
    fake_update.message.from_user.id = 2

    await adapter._on_message(fake_update, context=MagicMock())
    assert not adapter._internal_queue.empty()
    msg = await adapter._internal_queue.get()
    assert msg is fake_update.message
```

### Step 3.3 — Run to verify failure

- [ ] Run:

```bash
pytest tests/test_telegram_adapter.py -v
```

Expected: `ImportError` — module does not exist yet.

### Step 3.4 — Implement TelegramAdapter

- [ ] Create `claudeclaw/channels/telegram_adapter.py`:

```python
# claudeclaw/channels/telegram_adapter.py
import asyncio
import logging
from typing import AsyncGenerator, Optional

from telegram import Bot, Update
from telegram.ext import Application, MessageHandler, ContextTypes, filters

from claudeclaw.channels.base import ChannelAdapter
from claudeclaw.core.event import Event, Response

logger = logging.getLogger(__name__)


class TelegramAdapter(ChannelAdapter):
    """
    Channel adapter for Telegram using python-telegram-bot>=21.
    Bridges PTB callback-based message handling to the AsyncGenerator interface
    required by ChannelAdapter via an internal asyncio.Queue.
    """

    def __init__(self, token: str):
        self._token = token
        self._internal_queue: asyncio.Queue = asyncio.Queue()
        self._bot: Optional[Bot] = None
        self._application: Optional[Application] = None

    async def _on_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """PTB handler: put incoming message onto the internal queue."""
        if update.message and update.message.text:
            await self._internal_queue.put(update.message)

    async def receive(self) -> AsyncGenerator[Event, None]:
        """
        Start the PTB application, then yield Event objects as messages arrive.
        Runs until the task is cancelled.
        """
        self._application = (
            Application.builder()
            .token(self._token)
            .build()
        )
        self._bot = self._application.bot
        self._application.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self._on_message)
        )

        await self._application.initialize()
        await self._application.start()
        await self._application.updater.start_polling(drop_pending_updates=True)

        try:
            while True:
                message = await self._internal_queue.get()
                if message is None:
                    break
                yield Event(
                    text=message.text,
                    channel="telegram",
                    channel_adapter=self,
                    metadata={
                        "chat_id": message.chat_id,
                        "user_id": message.from_user.id if message.from_user else None,
                    },
                )
        finally:
            await self._application.updater.stop()
            await self._application.stop()
            await self._application.shutdown()

    async def send(self, response: Response) -> None:
        """Send a text response back to the originating Telegram chat."""
        if self._bot is None:
            raise RuntimeError("TelegramAdapter.send() called before receive() was started")
        await self._bot.send_message(chat_id=response.chat_id, text=response.text)
```

### Step 3.5 — Run to verify pass

- [ ] Run:

```bash
pytest tests/test_telegram_adapter.py -v
```

Expected: 4 PASSED.

### Step 3.6 — Commit

- [ ] Run:

```bash
git add claudeclaw/channels/telegram_adapter.py tests/test_telegram_adapter.py pyproject.toml
git commit -m "feat: TelegramAdapter using python-telegram-bot>=21 with internal queue bridge"
```

---

## Task 4: `channel add` CLI Command + channels.yaml

**Files:**
- Update: `claudeclaw/cli.py`
- Create: `tests/test_channel_cli.py`

### Step 4.1 — Write failing tests

- [ ] Create `tests/test_channel_cli.py`:

```python
# tests/test_channel_cli.py
import pytest
import yaml
from pathlib import Path
from click.testing import CliRunner
from claudeclaw.cli import main


@pytest.fixture
def runner():
    return CliRunner()


def test_channel_add_telegram_stores_token(runner, tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDECLAW_HOME", str(tmp_path))
    (tmp_path / "config").mkdir(parents=True, exist_ok=True)

    from claudeclaw.auth.keyring import CredentialStore
    store = CredentialStore(backend="file", master_password="test")

    with runner.isolated_filesystem():
        result = runner.invoke(main, [
            "channel", "add", "telegram", "--token", "my-secret-token"
        ], catch_exceptions=False)

    # Token written to credential store
    assert result.exit_code == 0
    # channels.yaml created
    channels_yaml = tmp_path / "config" / "channels.yaml"
    assert channels_yaml.exists()
    data = yaml.safe_load(channels_yaml.read_text())
    types = [c["type"] for c in data["channels"]]
    assert "telegram" in types


def test_channel_add_telegram_idempotent(runner, tmp_path, monkeypatch):
    """Running channel add twice should not duplicate the entry."""
    monkeypatch.setenv("CLAUDECLAW_HOME", str(tmp_path))
    (tmp_path / "config").mkdir(parents=True, exist_ok=True)

    runner.invoke(main, ["channel", "add", "telegram", "--token", "tok1"])
    runner.invoke(main, ["channel", "add", "telegram", "--token", "tok2"])

    channels_yaml = tmp_path / "config" / "channels.yaml"
    data = yaml.safe_load(channels_yaml.read_text())
    telegram_entries = [c for c in data["channels"] if c["type"] == "telegram"]
    assert len(telegram_entries) == 1


def test_channel_add_requires_token(runner, tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDECLAW_HOME", str(tmp_path))
    result = runner.invoke(main, ["channel", "add", "telegram"])
    assert result.exit_code != 0
```

### Step 4.2 — Run to verify failure

- [ ] Run:

```bash
pytest tests/test_channel_cli.py -v
```

Expected: `UsageError` or `No such command 'channel'`.

### Step 4.3 — Add `channel` command group to CLI

- [ ] Edit `claudeclaw/cli.py` — add after existing commands:

```python
# claudeclaw/cli.py  (additions — append to existing file)
import yaml as _yaml


@main.group()
def channel():
    """Manage channel adapters (Telegram, Slack, etc.)."""


@channel.command("add")
@click.argument("channel_type")
@click.option("--token", required=True, help="Bot or API token for the channel.")
def channel_add(channel_type: str, token: str):
    """Add and configure a channel adapter."""
    from claudeclaw.config.settings import get_settings
    from claudeclaw.auth.keyring import CredentialStore

    settings = get_settings()
    store = CredentialStore()

    # Store token in credential store
    token_key = f"{channel_type}-bot-token"
    store.set(token_key, token)

    # Upsert entry in channels.yaml
    channels_file = settings.config_dir / "channels.yaml"
    if channels_file.exists():
        data = _yaml.safe_load(channels_file.read_text()) or {}
    else:
        data = {}

    channels = data.get("channels", [])
    # Remove existing entry for this channel type (idempotent)
    channels = [c for c in channels if c.get("type") != channel_type]
    channels.append({"type": channel_type, "enabled": True})
    data["channels"] = channels
    channels_file.write_text(_yaml.dump(data, default_flow_style=False))

    click.echo(f"Channel '{channel_type}' configured. Token stored securely.")
```

### Step 4.4 — Run to verify pass

- [ ] Run:

```bash
pytest tests/test_channel_cli.py -v
```

Expected: 3 PASSED.

### Step 4.5 — Commit

- [ ] Run:

```bash
git add claudeclaw/cli.py tests/test_channel_cli.py
git commit -m "feat: channel add CLI command writes channels.yaml and stores token in keyring"
```

---

## Task 5: Native Skills Directory + Updated SkillRegistry

**Files:**
- Create: `claudeclaw/skills/native/__init__.py`
- Create: `claudeclaw/skills/native/agent-creator.md` (stub)
- Update: `claudeclaw/skills/registry.py`
- Create: `tests/test_skill_registry_native.py`

### Step 5.1 — Write failing tests

- [ ] Create `tests/test_skill_registry_native.py`:

```python
# tests/test_skill_registry_native.py
import pytest
from pathlib import Path
from claudeclaw.skills.registry import SkillRegistry
from claudeclaw.skills.loader import SkillManifest


NATIVE_SKILLS_DIR = Path(__file__).parent.parent / "claudeclaw" / "skills" / "native"


def test_registry_loads_native_skills(tmp_path):
    registry = SkillRegistry(
        user_skills_dir=tmp_path,
        native_skills_dir=NATIVE_SKILLS_DIR,
    )
    skills = registry.all_skills()
    names = [s.name for s in skills]
    assert "pop" in names


def test_native_skills_annotated(tmp_path):
    registry = SkillRegistry(
        user_skills_dir=tmp_path,
        native_skills_dir=NATIVE_SKILLS_DIR,
    )
    pop_skill = registry.find("pop")
    assert pop_skill is not None
    assert pop_skill.is_native is True


def test_user_skill_shadows_native(tmp_path):
    """A user skill with the same name should take precedence over native."""
    user_pop = tmp_path / "pop.md"
    user_pop.write_text("""---
name: pop
description: User override of pop
trigger: on-demand
autonomy: ask
tools: []
shell-policy: none
---
User override body.
""")
    registry = SkillRegistry(
        user_skills_dir=tmp_path,
        native_skills_dir=NATIVE_SKILLS_DIR,
    )
    pop_skill = registry.find("pop")
    assert pop_skill.description == "User override of pop"
    assert pop_skill.is_native is False


def test_registry_find_returns_none_for_unknown(tmp_path):
    registry = SkillRegistry(
        user_skills_dir=tmp_path,
        native_skills_dir=NATIVE_SKILLS_DIR,
    )
    assert registry.find("does-not-exist") is None
```

### Step 5.2 — Run to verify failure

- [ ] Run:

```bash
pytest tests/test_skill_registry_native.py -v
```

Expected: `ImportError` or `TypeError` — registry does not accept `native_skills_dir` yet.

### Step 5.3 — Create native skills directory and stub agent-creator

- [ ] Create `claudeclaw/skills/native/__init__.py` (empty file)

- [ ] Create `claudeclaw/skills/native/agent-creator.md`:

```markdown
---
name: agent-creator
description: Wizard that creates a new agent end-to-end from a natural language description
trigger: on-demand
autonomy: ask
tools: []
shell-policy: none
---

# Agent Creator

> **Stub — full implementation in Plan 3.**

This native skill will guide the user through a wizard to create a fully configured
ClaudeClaw agent. For now, acknowledge the intent and inform the user this feature
is coming soon.

Respond: "The Agent Creator wizard is coming in a future update. In the meantime,
you can use the POP skill to map a single operation: just say 'teach me to automate X'."
```

### Step 5.4 — Update SkillManifest to include is_native flag

- [ ] Edit `claudeclaw/skills/loader.py` — add `is_native: bool = False` to `SkillManifest`:

```python
@dataclass
class SkillManifest:
    name: str
    description: str
    trigger: str
    autonomy: str
    shell_policy: str
    body: str
    plugins: list[str] = field(default_factory=list)
    mcps: list[str] = field(default_factory=list)
    credentials: list[str] = field(default_factory=list)
    schedule: Optional[str] = None
    trigger_id: Optional[str] = None
    is_native: bool = False
```

### Step 5.5 — Update SkillRegistry

- [ ] Edit `claudeclaw/skills/registry.py` to accept and load from `native_skills_dir`:

```python
# claudeclaw/skills/registry.py
from pathlib import Path
from typing import Optional
from claudeclaw.skills.loader import load_skill, SkillManifest, SkillLoadError
import logging

logger = logging.getLogger(__name__)


class SkillRegistry:
    def __init__(self, user_skills_dir: Path, native_skills_dir: Optional[Path] = None):
        self._user_dir = user_skills_dir
        self._native_dir = native_skills_dir

    def _load_from_dir(self, directory: Path, is_native: bool) -> dict[str, SkillManifest]:
        skills: dict[str, SkillManifest] = {}
        if not directory or not directory.exists():
            return skills
        for path in directory.glob("*.md"):
            try:
                skill = load_skill(path)
                skill.is_native = is_native
                skills[skill.name] = skill
            except SkillLoadError as exc:
                logger.warning("Skipping invalid skill %s: %s", path, exc)
        return skills

    def all_skills(self) -> list[SkillManifest]:
        """Native skills first; user skills override by name."""
        merged: dict[str, SkillManifest] = {}
        if self._native_dir:
            merged.update(self._load_from_dir(self._native_dir, is_native=True))
        merged.update(self._load_from_dir(self._user_dir, is_native=False))
        return list(merged.values())

    def find(self, name: str) -> Optional[SkillManifest]:
        for skill in self.all_skills():
            if skill.name == name:
                return skill
        return None
```

### Step 5.6 — Run to verify pass

- [ ] Run:

```bash
pytest tests/test_skill_registry_native.py -v
```

Expected: 4 PASSED.

### Step 5.7 — Commit

- [ ] Run:

```bash
git add claudeclaw/skills/native/ claudeclaw/skills/registry.py \
      claudeclaw/skills/loader.py tests/test_skill_registry_native.py
git commit -m "feat: native skills directory; SkillRegistry loads from both native and user dirs"
```

---

## Task 6: POP Skill `.md` File

**Files:**
- Create: `claudeclaw/skills/native/pop.md`

No code tests for this task — the POP skill is a natural language instruction file for the Claude SDK subagent. Verification is done by checking that it loads without error via the skill loader.

### Step 6.1 — Verify the skill loader will accept pop.md

- [ ] Add a quick smoke test to `tests/test_skill_registry_native.py`:

```python
# append to tests/test_skill_registry_native.py
from claudeclaw.skills.loader import load_skill

def test_pop_md_loads_without_error():
    pop_path = NATIVE_SKILLS_DIR / "pop.md"
    assert pop_path.exists(), "pop.md must exist before this test"
    skill = load_skill(pop_path)
    assert skill.name == "pop"
    assert skill.trigger == "on-demand"
```

### Step 6.2 — Run to verify failure (file does not exist yet)

- [ ] Run:

```bash
pytest tests/test_skill_registry_native.py::test_pop_md_loads_without_error -v
```

Expected: `AssertionError: pop.md must exist`.

### Step 6.3 — Write pop.md

- [ ] Create `claudeclaw/skills/native/pop.md`:

```markdown
---
name: pop
description: Maps a single function the user wants to automate and generates a skill file (Procedimento Operacional Padrão)
trigger: on-demand
autonomy: ask
tools: []
shell-policy: none
---

# POP — Procedimento Operacional Padrão

You are the POP wizard. Your job is to guide the user through mapping ONE specific
function they want to automate, and then generate a ClaudeClaw skill `.md` file for it.

Be conversational, patient, and concise. Ask one question at a time. Do not rush.

---

## Wizard Flow

Work through these steps in order. After the user answers each step, confirm briefly
("Got it.") and move to the next step.

### Step 1 — Task Description

Ask: "What do you want to automate? Describe the task in a few words."

Save the answer as `task_description`. This will become the skill's `description` field.
Derive a `skill_name` by lowercasing, replacing spaces and special characters with `-`,
and truncating to 50 characters.

### Step 2 — Manual Steps

Ask: "Step by step, what do you do manually? Send each step as a separate message,
then say 'done' when you have listed all steps."

Collect each message as an ordered step. Stop collecting when the user sends "done"
(case-insensitive). Save the ordered list as `manual_steps`.

### Step 3 — Systems and Tools

Ask: "Which systems or tools do you use for this? For example: ERP, spreadsheet,
email, browser, API. List them."

Save the answer as `systems_list`.

### Step 4 — Credentials

Ask: "Do any of these systems require a username, password, or API key?
If yes, tell me the name for each credential and I'll store it securely.
Say 'none' if no credentials are needed."

If the user provides credentials:
- For each credential, ask: "What is the value for [credential name]?"
- Store each credential immediately using the CredentialStore tool (key = credential name, value = the provided value).
- Do NOT echo credential values back to the user.
- Confirm: "Stored securely. Moving on."

Save the list of credential key names (not values) as `credential_keys`.

### Step 5 — Schedule

Ask: "How often should this run? Choose one:
1. On-demand (I will trigger it manually)
2. Daily
3. Weekly
4. Monthly
5. Custom cron expression"

Map the answer to frontmatter:
- On-demand → `trigger: on-demand`
- Daily → `trigger: cron`, `schedule: "0 9 * * *"`
- Weekly → `trigger: cron`, `schedule: "0 9 * * 1"`
- Monthly → `trigger: cron`, `schedule: "0 9 1 * *"`
- Custom → `trigger: cron`, `schedule: <user's expression>`

Save as `trigger_config`.

### Step 6 — Autonomy Level

Ask: "When this runs, should it:
1. Ask you before taking each action (ask)
2. Act and then notify you (notify)
3. Run silently and only contact you on error (autonomous)"

Map the answer to `autonomy: ask | notify | autonomous`.
Save as `autonomy_level`.

---

## Skill Generation

After all six steps are complete, generate the skill file using this template:

```
---
name: {skill_name}
description: {task_description}
{trigger_config}
autonomy: {autonomy_level}
plugins: []
credentials: [{credential_keys joined by ", "}]
shell-policy: none
---

# {Title Case of skill_name}

## Steps

{numbered list of manual_steps}

## Systems Used

{bulleted list of systems_list}
```

Save the generated content to `~/.claudeclaw/skills/{skill_name}.md`.

---

## Confirmation

After saving the file, respond:

"Skill '{skill_name}' created and saved.

Run it with: `claudeclaw agents run {skill_name}`

To edit it: `~/.claudeclaw/skills/{skill_name}.md`"

---

## Error Handling

- If the user seems confused or goes off-topic, gently redirect: "Let's focus on mapping this one task. [repeat current question]"
- If the user says "cancel" or "stop" at any point, respond: "POP session cancelled. No skill was created." and stop.
- If saving the file fails, report the error and suggest the user check disk space and permissions.
```

### Step 6.4 — Run to verify pass

- [ ] Run:

```bash
pytest tests/test_skill_registry_native.py -v
```

Expected: all tests PASSED including `test_pop_md_loads_without_error`.

### Step 6.5 — Commit

- [ ] Run:

```bash
git add claudeclaw/skills/native/pop.md tests/test_skill_registry_native.py
git commit -m "feat: POP native skill — wizard that maps a function and generates a skill file"
```

---

## Task 7: Router — Native Skill Intent Priority

**Files:**
- Update: `claudeclaw/core/router.py`
- Create: `tests/test_router_native_intents.py`

### Step 7.1 — Write failing tests

- [ ] Create `tests/test_router_native_intents.py`:

```python
# tests/test_router_native_intents.py
import pytest
from unittest.mock import MagicMock
from claudeclaw.core.event import Event
from claudeclaw.core.router import route


def _make_registry(skill_names: list[str]):
    """Build a mock registry that returns a mock skill for known names."""
    registry = MagicMock()

    def fake_find(name):
        if name in skill_names:
            skill = MagicMock()
            skill.name = name
            return skill
        return None

    registry.find.side_effect = fake_find
    return registry


@pytest.mark.parametrize("text", [
    "teach me to automate invoices",
    "I want to automate my report",
    "map this process",
    "pop",
    "procedimento",
    "how to send emails",
    "ensina como fazer relatório",
])
def test_pop_keywords_route_to_pop(text):
    registry = _make_registry(["pop"])
    event = Event(text=text, channel="telegram")
    skill = route(event, registry)
    assert skill.name == "pop"


@pytest.mark.parametrize("text", [
    "create an agent for invoicing",
    "i need someone to handle my emails",
    "crie um agente para meu ERP",
])
def test_agent_creator_keywords_route_to_agent_creator(text):
    registry = _make_registry(["agent-creator"])
    event = Event(text=text, channel="telegram")
    skill = route(event, registry)
    assert skill.name == "agent-creator"


def test_generic_text_does_not_match_native_intents(mocker):
    """Text with no known intent keywords falls through to general routing."""
    registry = _make_registry(["pop", "agent-creator"])
    event = Event(text="hello, what time is it?", channel="cli")
    # Mock general routing to return a dummy skill
    mocker.patch("claudeclaw.core.router._general_route", return_value=MagicMock(name="time-skill"))
    skill = route(event, registry)
    assert skill is not None  # general route was called
```

### Step 7.2 — Run to verify failure

- [ ] Run:

```bash
pytest tests/test_router_native_intents.py -v
```

Expected: import or assertion errors.

### Step 7.3 — Update router with native intent priority

- [ ] Edit `claudeclaw/core/router.py` — add native intent dispatch at the top of `route()`:

```python
# claudeclaw/core/router.py
from claudeclaw.core.event import Event
from claudeclaw.skills.registry import SkillRegistry
from claudeclaw.skills.loader import SkillManifest
from typing import Optional

NATIVE_SKILL_INTENTS: dict[str, list[str]] = {
    "pop": [
        "teach", "ensina", "ensinar",
        "automate", "automatiza", "automatizar",
        "map", "mapeia", "mapear",
        "pop", "procedimento",
        "how to", "como fazer",
    ],
    "agent-creator": [
        "create an agent", "i need someone to",
        "crie um agente", "preciso de alguém",
    ],
}


def route(event: Event, registry: SkillRegistry) -> Optional[SkillManifest]:
    """
    Route an event to a skill.
    1. Check native skill intent keywords (priority).
    2. Fall through to general semantic routing.
    """
    text_lower = event.text.lower()

    for skill_name, keywords in NATIVE_SKILL_INTENTS.items():
        if any(kw in text_lower for kw in keywords):
            skill = registry.find(skill_name)
            if skill is not None:
                return skill

    return _general_route(event, registry)


def _general_route(event: Event, registry: SkillRegistry) -> Optional[SkillManifest]:
    """
    General skill routing: find the best matching skill for the event.
    Plan 1 implementation: returns the first available on-demand skill.
    Plan 3 will replace this with Claude SDK semantic matching.
    """
    for skill in registry.all_skills():
        if skill.trigger == "on-demand":
            return skill
    return None
```

### Step 7.4 — Run to verify pass

- [ ] Run:

```bash
pytest tests/test_router_native_intents.py -v
```

Expected: all tests PASSED.

### Step 7.5 — Commit

- [ ] Run:

```bash
git add claudeclaw/core/router.py tests/test_router_native_intents.py
git commit -m "feat: router checks native skill intent keywords before general routing"
```

---

## Task 8: Integration — Orchestrator Loads Telegram + Routes to POP

**Files:**
- No new files — integration test using existing components

### Step 8.1 — Write integration test

- [ ] Add `tests/test_integration_telegram_pop.py`:

```python
# tests/test_integration_telegram_pop.py
"""
Integration test: simulates a Telegram message with a POP intent arriving
at the orchestrator via the channel manager queue.
"""
import asyncio
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from claudeclaw.core.event import Event, Response
from claudeclaw.core.orchestrator import Orchestrator
from claudeclaw.skills.registry import SkillRegistry

NATIVE_SKILLS_DIR = Path(__file__).parent.parent / "claudeclaw" / "skills" / "native"


async def test_telegram_pop_intent_dispatches_pop_skill(tmp_path, mocker):
    """
    Simulate: Telegram user sends 'teach me to automate my report'
    Expect: Orchestrator routes to pop skill and calls send() on the adapter.
    """
    registry = SkillRegistry(user_skills_dir=tmp_path, native_skills_dir=NATIVE_SKILLS_DIR)

    credential_store = mocker.MagicMock()
    orchestrator = Orchestrator(skill_registry=registry, credential_store=credential_store)

    # Mock _process to avoid real Claude SDK call, but verify routing happened
    dispatched_skills = []

    async def fake_process(event: Event) -> Response:
        from claudeclaw.core.router import route
        skill = route(event, registry)
        dispatched_skills.append(skill.name if skill else None)
        return Response(text="POP started", channel="telegram", chat_id=42)

    mocker.patch.object(orchestrator, "_process", side_effect=fake_process)

    mock_adapter = AsyncMock()
    event = Event(
        text="teach me to automate my monthly report",
        channel="telegram",
        channel_adapter=mock_adapter,
        metadata={"chat_id": 42},
    )

    queue = asyncio.Queue()
    await queue.put(event)
    await queue.put(None)  # sentinel

    await orchestrator.run(queue, stop_sentinel=True)

    assert dispatched_skills == ["pop"]
    mock_adapter.send.assert_awaited_once()
    call_args = mock_adapter.send.call_args[0][0]
    assert call_args.text == "POP started"


async def test_channel_manager_creates_telegram_adapter(tmp_path, mocker):
    """ChannelManager with telegram in channels.yaml instantiates TelegramAdapter."""
    import yaml
    from claudeclaw.channels.manager import ChannelManager

    channels_file = tmp_path / "channels.yaml"
    channels_file.write_text(yaml.dump({
        "channels": [{"type": "telegram", "enabled": True}]
    }))

    credential_store = mocker.MagicMock()
    credential_store.get.return_value = "fake-token"

    manager = ChannelManager(config_path=channels_file, credential_store=credential_store)
    adapters = manager.load_channels()

    assert len(adapters) == 1
    from claudeclaw.channels.telegram_adapter import TelegramAdapter
    assert isinstance(adapters[0], TelegramAdapter)
```

### Step 8.2 — Run to verify pass

- [ ] Run:

```bash
pytest tests/test_integration_telegram_pop.py -v
```

Expected: 2 PASSED.

### Step 8.3 — Run full test suite

- [ ] Run:

```bash
pytest tests/ -v
```

Expected: all tests PASSED, no regressions from Plan 1 tests.

### Step 8.4 — Commit

- [ ] Run:

```bash
git add tests/test_integration_telegram_pop.py
git commit -m "test: integration — Telegram message with POP intent routes to pop skill via orchestrator queue"
```

---

## Task 9: Final Verification

### Step 9.1 — Full test suite clean run

- [ ] Run:

```bash
pytest tests/ -v --tb=short
```

Expected: all tests PASSED.

### Step 9.2 — Verify CLI help reflects new commands

- [ ] Run:

```bash
python -m claudeclaw.cli --help
python -m claudeclaw.cli channel --help
python -m claudeclaw.cli channel add --help
```

Expected: `channel` group appears, `add` subcommand shows `--token` option.

### Step 9.3 — Verify native skills are listed

- [ ] Run:

```bash
python -c "
from pathlib import Path
from claudeclaw.skills.registry import SkillRegistry

native_dir = Path('claudeclaw/skills/native')
registry = SkillRegistry(user_skills_dir=Path('/tmp'), native_skills_dir=native_dir)
for s in registry.all_skills():
    tag = '[native]' if s.is_native else '[user]'
    print(f'{tag} {s.name}: {s.description}')
"
```

Expected: `[native] pop: Maps a single function...` and `[native] agent-creator: ...` printed.

### Step 9.4 — Final commit

- [ ] Run:

```bash
git add -u
git status
```

Confirm nothing untracked is left. Then:

```bash
git commit -m "chore: Plan 2 complete — Telegram adapter, channel manager, POP skill, native registry"
```

---

## Summary of Deliverables

| Deliverable | Location | Status after Plan 2 |
|-------------|----------|---------------------|
| asyncio.Queue orchestrator loop | `claudeclaw/core/orchestrator.py` | Done |
| `channel_adapter` field on Event | `claudeclaw/core/event.py` | Done |
| ChannelManager | `claudeclaw/channels/manager.py` | Done |
| TelegramAdapter | `claudeclaw/channels/telegram_adapter.py` | Done |
| `channel add` CLI command | `claudeclaw/cli.py` | Done |
| `channels.yaml` config | `~/.claudeclaw/config/channels.yaml` | Done |
| Native skills directory | `claudeclaw/skills/native/` | Done |
| Updated SkillRegistry | `claudeclaw/skills/registry.py` | Done |
| `pop.md` skill file | `claudeclaw/skills/native/pop.md` | Done |
| Native intent router | `claudeclaw/core/router.py` | Done |
| `agent-creator.md` stub | `claudeclaw/skills/native/agent-creator.md` | Stub (Plan 3) |
