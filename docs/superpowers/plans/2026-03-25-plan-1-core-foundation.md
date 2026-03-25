# ClaudeClaw — Plan 1: Core Foundation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the working core of ClaudeClaw: authenticate with a Claude account, load skills from `.md` files, dispatch Claude SDK subagents with enforced permissions, and run the full loop via CLI.

**Architecture:** A Python daemon (`orchestrator.py`) receives normalized events from channel adapters, routes them to matching skills via the router, and dispatches isolated Claude SDK subagent invocations. Skills are `.md` files with YAML frontmatter. Credentials are stored in the OS keyring (with an encrypted-file fallback for headless Linux). The CLI channel adapter provides stdin/stdout interaction for this first plan.

**Tech Stack:** Python 3.11+, `anthropic` SDK, `click` (CLI), `python-frontmatter` (`.md` parsing), `keyring` + `cryptography` (credential storage), `pydantic` (data validation), `pytest` (tests)

**Spec reference:** `docs/superpowers/specs/2026-03-24-claudeclaw-design.md`

---

## File Map

```
claudeclaw/                         ← package root
├── pyproject.toml                  ← deps, entry points, pytest config
├── claudeclaw/
│   ├── __init__.py
│   ├── cli.py                      ← Click CLI: login, start, skills, agents
│   ├── auth/
│   │   ├── __init__.py
│   │   ├── oauth.py                ← Claude OAuth flow (browser-based)
│   │   └── keyring.py              ← Keyring abstraction + headless fallback
│   ├── core/
│   │   ├── __init__.py
│   │   ├── event.py                ← Normalized event dataclass
│   │   ├── router.py               ← Maps intent to matching skill
│   │   └── orchestrator.py         ← Daemon loop: receive → route → dispatch → respond
│   ├── skills/
│   │   ├── __init__.py
│   │   ├── loader.py               ← Parse .md files + validate frontmatter schema
│   │   └── registry.py             ← List/find skills from ~/.claudeclaw/skills/
│   ├── subagent/
│   │   ├── __init__.py
│   │   └── dispatch.py             ← Claude SDK subagent invocation + permission enforcement
│   ├── channels/
│   │   ├── __init__.py
│   │   ├── base.py                 ← Abstract ChannelAdapter interface
│   │   └── cli_adapter.py          ← stdin/stdout channel for Plan 1
│   └── config/
│       ├── __init__.py
│       └── settings.py             ← Load/save ~/.claudeclaw/config/settings.yaml
└── tests/
    ├── conftest.py                 ← shared fixtures (tmp skill dir, mock claude client)
    ├── test_keyring.py
    ├── test_skill_loader.py
    ├── test_router.py
    ├── test_dispatch.py
    └── test_cli.py
```

---

## Task 1: Project Scaffold

**Files:**
- Create: `pyproject.toml`
- Create: `claudeclaw/__init__.py`
- Create: `claudeclaw/auth/__init__.py`
- Create: `claudeclaw/core/__init__.py`
- Create: `claudeclaw/skills/__init__.py`
- Create: `claudeclaw/subagent/__init__.py`
- Create: `claudeclaw/channels/__init__.py`
- Create: `claudeclaw/config/__init__.py`
- Create: `tests/conftest.py`

- [ ] **Step 1: Create pyproject.toml**

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "claudeclaw"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "anthropic>=0.40.0",
    "click>=8.1",
    "python-frontmatter>=1.1",
    "pydantic>=2.0",
    "keyring>=25.0",
    "cryptography>=42.0",
    "pyyaml>=6.0",
    "httpx>=0.27",
]

[project.scripts]
claudeclaw = "claudeclaw.cli:main"

[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"

[tool.hatch.envs.default]
dependencies = ["pytest", "pytest-asyncio", "pytest-mock"]
```

- [ ] **Step 2: Create all `__init__.py` files and tests/conftest.py**

All `__init__.py` files should be empty for now. `conftest.py`:

```python
# tests/conftest.py
import pytest
from pathlib import Path
import tempfile


@pytest.fixture
def tmp_skills_dir(tmp_path):
    """Temporary ~/.claudeclaw/skills/ replacement for tests."""
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    return skills_dir


@pytest.fixture
def sample_skill_md(tmp_skills_dir):
    """Write a minimal valid skill .md to the temp dir."""
    content = """---
name: test-skill
description: A test skill for unit tests
trigger: on-demand
autonomy: ask
tools: []
shell-policy: none
---
# Test Skill
Do nothing. This is a test.
"""
    skill_file = tmp_skills_dir / "test-skill.md"
    skill_file.write_text(content)
    return skill_file
```

- [ ] **Step 3: Install dependencies**

```bash
pip install -e ".[dev]" 2>/dev/null || pip install -e .
pip install pytest pytest-asyncio pytest-mock
```

- [ ] **Step 4: Verify pytest discovers tests**

```bash
pytest tests/ --collect-only
```

Expected: `no tests ran` (empty test files don't exist yet — this just confirms pytest runs without error).

- [ ] **Step 5: Commit**

```bash
git init
git add pyproject.toml claudeclaw/ tests/
git commit -m "chore: project scaffold — package structure and dependencies"
```

---

## Task 2: Config + Settings

**Files:**
- Create: `claudeclaw/config/settings.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_config.py
from pathlib import Path
from claudeclaw.config.settings import Settings, get_settings


def test_default_skills_dir_is_under_home():
    s = Settings()
    assert s.skills_dir.parts[-1] == "skills"
    assert ".claudeclaw" in str(s.skills_dir)


def test_settings_creates_dirs_on_init(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDECLAW_HOME", str(tmp_path))
    s = Settings()
    assert s.skills_dir.exists()
    assert s.config_dir.exists()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_config.py -v
```

Expected: `ImportError` — module does not exist yet.

- [ ] **Step 3: Implement settings**

```python
# claudeclaw/config/settings.py
import os
from pathlib import Path
from functools import lru_cache
import yaml


def _claudeclaw_home() -> Path:
    env = os.environ.get("CLAUDECLAW_HOME")
    if env:
        return Path(env)
    return Path.home() / ".claudeclaw"


class Settings:
    def __init__(self):
        self.home = _claudeclaw_home()
        self.config_dir = self.home / "config"
        self.skills_dir = self.home / "skills"
        self.plugins_dir = self.home / "plugins"
        self.config_file = self.config_dir / "settings.yaml"
        self._ensure_dirs()

    def _ensure_dirs(self):
        for d in [self.config_dir, self.skills_dir, self.plugins_dir]:
            d.mkdir(parents=True, exist_ok=True)

    def get(self, key: str, default=None):
        if not self.config_file.exists():
            return default
        data = yaml.safe_load(self.config_file.read_text()) or {}
        return data.get(key, default)

    def set(self, key: str, value) -> None:
        data = {}
        if self.config_file.exists():
            data = yaml.safe_load(self.config_file.read_text()) or {}
        data[key] = value
        self.config_file.write_text(yaml.dump(data))


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_config.py -v
```

Expected: 2 PASSED.

- [ ] **Step 5: Commit**

```bash
git add claudeclaw/config/settings.py tests/test_config.py
git commit -m "feat: config settings with auto-dir creation"
```

---

## Task 3: Keyring Abstraction

**Files:**
- Create: `claudeclaw/auth/keyring.py`
- Create: `tests/test_keyring.py`

The keyring module must work on macOS (Keychain), Windows (Credential Manager), Linux with GUI (libsecret), and headless Linux VPS (encrypted file with master password).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_keyring.py
import pytest
from claudeclaw.auth.keyring import CredentialStore


def test_set_and_get_credential(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDECLAW_HOME", str(tmp_path))
    store = CredentialStore(backend="file", master_password="test-secret")
    store.set("erp-user", "alice")
    assert store.get("erp-user") == "alice"


def test_get_missing_returns_none(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDECLAW_HOME", str(tmp_path))
    store = CredentialStore(backend="file", master_password="test-secret")
    assert store.get("does-not-exist") is None


def test_delete_credential(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDECLAW_HOME", str(tmp_path))
    store = CredentialStore(backend="file", master_password="test-secret")
    store.set("token", "abc123")
    store.delete("token")
    assert store.get("token") is None


def test_list_keys(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDECLAW_HOME", str(tmp_path))
    store = CredentialStore(backend="file", master_password="test-secret")
    store.set("key-a", "val-a")
    store.set("key-b", "val-b")
    keys = store.list_keys()
    assert "key-a" in keys
    assert "key-b" in keys
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_keyring.py -v
```

Expected: `ImportError`.

- [ ] **Step 3: Implement CredentialStore**

```python
# claudeclaw/auth/keyring.py
import json
import base64
from pathlib import Path
from typing import Optional

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes

from claudeclaw.config.settings import get_settings


SERVICE_NAME = "claudeclaw"
SALT = b"claudeclaw-salt-v1"  # fixed salt; credential file is already protected by master pw


def _derive_key(master_password: str) -> bytes:
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=SALT, iterations=480_000)
    return base64.urlsafe_b64encode(kdf.derive(master_password.encode()))


class _FileBackend:
    """Encrypted JSON file for headless/VPS environments."""

    def __init__(self, path: Path, master_password: str):
        self._path = path
        self._fernet = Fernet(_derive_key(master_password))

    def _load(self) -> dict:
        if not self._path.exists():
            return {}
        return json.loads(self._fernet.decrypt(self._path.read_bytes()))

    def _save(self, data: dict):
        self._path.write_bytes(self._fernet.encrypt(json.dumps(data).encode()))

    def get(self, key: str) -> Optional[str]:
        return self._load().get(key)

    def set(self, key: str, value: str):
        data = self._load()
        data[key] = value
        self._save(data)

    def delete(self, key: str):
        data = self._load()
        data.pop(key, None)
        self._save(data)

    def list_keys(self) -> list[str]:
        return list(self._load().keys())


class _KeyringBackend:
    """OS-native keyring (macOS Keychain, Windows Credential Manager, libsecret)."""

    def __init__(self):
        import keyring as _kr
        self._kr = _kr

    def get(self, key: str) -> Optional[str]:
        return self._kr.get_password(SERVICE_NAME, key)

    def set(self, key: str, value: str):
        # Store value AND maintain an index so list_keys() works
        # (keyring has no native list API)
        self._kr.set_password(SERVICE_NAME, key, value)
        keys = self.list_keys()
        if key not in keys:
            keys.append(key)
            self._kr.set_password(SERVICE_NAME, "__index__", json.dumps(keys))

    def delete(self, key: str):
        try:
            self._kr.delete_password(SERVICE_NAME, key)
        except Exception:
            pass

    def list_keys(self) -> list[str]:
        # keyring has no standard list API; we maintain an index key
        raw = self._kr.get_password(SERVICE_NAME, "__index__")
        return json.loads(raw) if raw else []




class CredentialStore:
    """
    Unified credential store. Backend selection:
      - backend="auto"  → tries OS keyring, falls back to file if unavailable
      - backend="keyring" → OS keyring only
      - backend="file"  → encrypted file (requires master_password)
    """

    def __init__(self, backend: str = "auto", master_password: Optional[str] = None):
        settings = get_settings()
        cred_file = settings.config_dir / "credentials.enc"

        if backend == "file" or (backend == "auto" and not self._keyring_available()):
            if master_password is None:
                raise ValueError("master_password required for file backend")
            self._backend = _FileBackend(cred_file, master_password)
        else:
            self._backend = _KeyringBackend()

    @staticmethod
    def _keyring_available() -> bool:
        try:
            import keyring
            keyring.get_password("__test__", "__test__")
            return True
        except Exception:
            return False

    def get(self, key: str) -> Optional[str]:
        return self._backend.get(key)

    def set(self, key: str, value: str):
        self._backend.set(key, value)

    def delete(self, key: str):
        self._backend.delete(key)

    def list_keys(self) -> list[str]:
        return self._backend.list_keys()
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_keyring.py -v
```

Expected: 4 PASSED.

- [ ] **Step 5: Commit**

```bash
git add claudeclaw/auth/keyring.py tests/test_keyring.py
git commit -m "feat: credential store with OS keyring + encrypted file fallback"
```

---

## Task 4: Skill Loader

**Files:**
- Create: `claudeclaw/skills/loader.py`
- Create: `tests/test_skill_loader.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_skill_loader.py
import pytest
from claudeclaw.skills.loader import load_skill, SkillManifest, SkillLoadError


def test_load_valid_skill(sample_skill_md):
    skill = load_skill(sample_skill_md)
    assert skill.name == "test-skill"
    assert skill.trigger == "on-demand"
    assert skill.autonomy == "ask"
    assert skill.shell_policy == "none"
    assert "Do nothing" in skill.body


def test_missing_required_field_raises(tmp_path):
    bad = tmp_path / "bad.md"
    bad.write_text("---\nname: no-description\n---\nBody")
    with pytest.raises(SkillLoadError, match="description"):
        load_skill(bad)


def test_invalid_autonomy_value_raises(tmp_path):
    bad = tmp_path / "bad2.md"
    bad.write_text("""---
name: bad
description: test
trigger: on-demand
autonomy: maybe
tools: []
shell-policy: none
---
Body""")
    with pytest.raises(SkillLoadError, match="autonomy"):
        load_skill(bad)


def test_cron_skill_requires_schedule(tmp_path):
    bad = tmp_path / "bad3.md"
    bad.write_text("""---
name: no-schedule
description: test
trigger: cron
autonomy: autonomous
tools: []
shell-policy: none
---
Body""")
    with pytest.raises(SkillLoadError, match="schedule"):
        load_skill(bad)


def test_optional_fields_have_defaults(sample_skill_md):
    skill = load_skill(sample_skill_md)
    assert skill.plugins == []
    assert skill.mcps == []
    assert skill.credentials == []
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_skill_loader.py -v
```

Expected: `ImportError`.

- [ ] **Step 3: Implement skill loader**

```python
# claudeclaw/skills/loader.py
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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_skill_loader.py -v
```

Expected: 5 PASSED.

- [ ] **Step 5: Commit**

```bash
git add claudeclaw/skills/loader.py tests/test_skill_loader.py
git commit -m "feat: skill loader — parse and validate .md frontmatter"
```

---

## Task 5: Skill Registry

**Files:**
- Create: `claudeclaw/skills/registry.py`
- Create: `tests/test_registry.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_registry.py
import pytest
from claudeclaw.skills.registry import SkillRegistry


def test_list_returns_loaded_skills(tmp_skills_dir, sample_skill_md, monkeypatch):
    monkeypatch.setenv("CLAUDECLAW_HOME", str(tmp_skills_dir.parent))
    registry = SkillRegistry(skills_dir=tmp_skills_dir)
    skills = registry.list_skills()
    assert len(skills) == 1
    assert skills[0].name == "test-skill"


def test_find_by_name(tmp_skills_dir, sample_skill_md, monkeypatch):
    registry = SkillRegistry(skills_dir=tmp_skills_dir)
    skill = registry.find("test-skill")
    assert skill is not None
    assert skill.name == "test-skill"


def test_find_missing_returns_none(tmp_skills_dir):
    registry = SkillRegistry(skills_dir=tmp_skills_dir)
    assert registry.find("does-not-exist") is None


def test_skips_invalid_skills(tmp_skills_dir, caplog):
    bad = tmp_skills_dir / "bad.md"
    bad.write_text("---\nno-name: true\n---\nbody")
    registry = SkillRegistry(skills_dir=tmp_skills_dir)
    skills = registry.list_skills()
    # bad.md is skipped, no crash
    assert all(s.name != "bad" for s in skills)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_registry.py -v
```

Expected: `ImportError`.

- [ ] **Step 3: Implement registry**

```python
# claudeclaw/skills/registry.py
import logging
from pathlib import Path
from typing import Optional

from claudeclaw.skills.loader import load_skill, SkillManifest, SkillLoadError
from claudeclaw.config.settings import get_settings

logger = logging.getLogger(__name__)


class SkillRegistry:
    def __init__(self, skills_dir: Optional[Path] = None):
        self._dir = skills_dir or get_settings().skills_dir

    def list_skills(self) -> list[SkillManifest]:
        skills = []
        for md_file in sorted(self._dir.glob("*.md")):
            try:
                skills.append(load_skill(md_file))
            except SkillLoadError as e:
                logger.warning("Skipping invalid skill %s: %s", md_file.name, e)
        return skills

    def find(self, name: str) -> Optional[SkillManifest]:
        for skill in self.list_skills():
            if skill.name == name:
                return skill
        return None
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_registry.py -v
```

Expected: 4 PASSED.

- [ ] **Step 5: Commit**

```bash
git add claudeclaw/skills/registry.py tests/test_registry.py
git commit -m "feat: skill registry — list and find skills from ~/.claudeclaw/skills/"
```

---

## Task 6: Normalized Event + Channel Base

**Files:**
- Create: `claudeclaw/core/event.py`
- Create: `claudeclaw/channels/base.py`

- [ ] **Step 1: Implement event dataclass (no test needed — pure data)**

```python
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
```

- [ ] **Step 2: Implement abstract channel adapter**

```python
# claudeclaw/channels/base.py
from abc import ABC, abstractmethod
from typing import AsyncIterator
from claudeclaw.core.event import Event, Response


class ChannelAdapter(ABC):
    """
    Each channel adapter normalizes incoming messages into Event objects
    and delivers Response objects back to the user.
    """

    @abstractmethod
    async def receive(self) -> AsyncIterator[Event]:
        """Yield events as they arrive."""
        ...

    @abstractmethod
    async def send(self, response: Response) -> None:
        """Deliver a response back to the user."""
        ...
```

- [ ] **Step 3: Commit**

```bash
git add claudeclaw/core/event.py claudeclaw/channels/base.py
git commit -m "feat: normalized event + abstract channel adapter"
```

---

## Task 7: CLI Channel Adapter

**Files:**
- Create: `claudeclaw/channels/cli_adapter.py`
- Create: `tests/test_cli_adapter.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cli_adapter.py
import asyncio
import pytest
from unittest.mock import patch
from claudeclaw.channels.cli_adapter import CliAdapter
from claudeclaw.core.event import Response, Event


@pytest.mark.asyncio
async def test_receive_yields_event_from_stdin():
    adapter = CliAdapter()
    inputs = iter(["hello world", ""])

    with patch("builtins.input", side_effect=inputs):
        events = []
        async for event in adapter.receive():
            events.append(event)
            break  # take just one

    assert len(events) == 1
    assert events[0].text == "hello world"
    assert events[0].channel == "cli"


@pytest.mark.asyncio
async def test_send_prints_response(capsys):
    adapter = CliAdapter()
    event = Event(text="hi", channel="cli")
    response = Response(text="Hello back!", event=event)
    await adapter.send(response)
    captured = capsys.readouterr()
    assert "Hello back!" in captured.out
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_cli_adapter.py -v
```

Expected: `ImportError`.

- [ ] **Step 3: Implement CLI adapter**

```python
# claudeclaw/channels/cli_adapter.py
import asyncio
from typing import AsyncIterator
from claudeclaw.channels.base import ChannelAdapter
from claudeclaw.core.event import Event, Response


class CliAdapter(ChannelAdapter):
    """stdin/stdout channel — reads lines from terminal, prints responses."""

    async def receive(self) -> AsyncIterator[Event]:
        loop = asyncio.get_event_loop()
        while True:
            try:
                text = await loop.run_in_executor(None, input, "\n> ")
            except (EOFError, KeyboardInterrupt):
                return
            if text.strip():
                yield Event(text=text.strip(), channel="cli", user_id="local")

    async def send(self, response: Response) -> None:
        print(f"\n{response.text}\n")
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_cli_adapter.py -v
```

Expected: 2 PASSED.

- [ ] **Step 5: Commit**

```bash
git add claudeclaw/channels/cli_adapter.py tests/test_cli_adapter.py
git commit -m "feat: CLI channel adapter — stdin/stdout"
```

---

## Task 8: Intent Router

**Files:**
- Create: `claudeclaw/core/router.py`
- Create: `tests/test_router.py`

The router maps an event's text to a skill. In Plan 1 it uses simple keyword/description matching via the Claude SDK. This is the first Claude SDK call in the system.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_router.py
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from claudeclaw.core.router import Router
from claudeclaw.core.event import Event
from claudeclaw.skills.loader import SkillManifest


@pytest.fixture
def skills():
    return [
        SkillManifest(
            name="invoice-agent",
            description="Emits invoices and sends them by email at month end",
            trigger="cron",
            schedule="0 0 28 * *",
            autonomy="autonomous",
            shell_policy="none",
            body="...",
        ),
        SkillManifest(
            name="crm-followup",
            description="Sends follow-up messages to hot CRM leads",
            trigger="on-demand",
            autonomy="notify",
            shell_policy="none",
            body="...",
        ),
    ]


def test_router_returns_best_matching_skill(skills):
    router = Router(skills)
    event = Event(text="I need to follow up with my leads", channel="cli")

    # Mock the Claude SDK call that does intent matching
    with patch.object(router, "_match_with_claude", return_value="crm-followup"):
        result = router.route(event)

    assert result is not None
    assert result.name == "crm-followup"


def test_router_returns_none_when_no_match(skills):
    router = Router(skills)
    event = Event(text="what is the weather today", channel="cli")

    with patch.object(router, "_match_with_claude", return_value=None):
        result = router.route(event)

    assert result is None


def test_router_returns_none_on_empty_skill_list():
    router = Router([])
    event = Event(text="do something", channel="cli")
    result = router.route(event)
    assert result is None
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_router.py -v
```

Expected: `ImportError`.

- [ ] **Step 3: Implement router**

```python
# claudeclaw/core/router.py
import logging
from typing import Optional
import anthropic

from claudeclaw.core.event import Event
from claudeclaw.skills.loader import SkillManifest

logger = logging.getLogger(__name__)


class Router:
    """
    Maps an incoming event to the best matching skill.
    Uses Claude to match event intent against skill descriptions.
    Falls back to None if no skill matches well enough.
    """

    def __init__(self, skills: list[SkillManifest], client: Optional[anthropic.Anthropic] = None):
        self._skills = skills
        self._client = client or anthropic.Anthropic()

    def route(self, event: Event) -> Optional[SkillManifest]:
        if not self._skills:
            return None

        matched_name = self._match_with_claude(event.text)
        if matched_name is None:
            return None

        return next((s for s in self._skills if s.name == matched_name), None)

    def _match_with_claude(self, text: str) -> Optional[str]:
        skill_list = "\n".join(
            f"- {s.name}: {s.description}" for s in self._skills
        )
        prompt = f"""Given this user message: "{text}"

And these available skills:
{skill_list}

Which skill name best matches the user's intent?
Reply with ONLY the skill name, or "none" if no skill matches."""

        try:
            response = self._client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=64,
                messages=[{"role": "user", "content": prompt}],
            )
            result = response.content[0].text.strip().lower()
            return None if result == "none" else result
        except Exception as e:
            logger.error("Router Claude call failed: %s", e)
            return None
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_router.py -v
```

Expected: 3 PASSED (all patched, no real API calls).

- [ ] **Step 5: Commit**

```bash
git add claudeclaw/core/router.py tests/test_router.py
git commit -m "feat: intent router — maps events to skills via Claude SDK"
```

---

## Task 9: Subagent Dispatch

**Files:**
- Create: `claudeclaw/subagent/dispatch.py`
- Create: `tests/test_dispatch.py`

The dispatcher calls the Claude SDK with the skill's `.md` body as the system prompt, injects only the declared tools, and returns the result text.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_dispatch.py
import pytest
from unittest.mock import MagicMock, patch
from claudeclaw.subagent.dispatch import SubagentDispatcher, DispatchResult
from claudeclaw.skills.loader import SkillManifest
from claudeclaw.core.event import Event


@pytest.fixture
def skill():
    return SkillManifest(
        name="test-skill",
        description="Test skill",
        trigger="on-demand",
        autonomy="ask",
        shell_policy="none",
        body="# Test\nYou are a helpful test agent. Echo back what the user says.",
        tools=[],
        credentials=[],
    )


@pytest.fixture
def event():
    return Event(text="hello", channel="cli", user_id="local")


def test_dispatch_returns_result_text(skill, event):
    dispatcher = SubagentDispatcher()
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="Echo: hello")]
    mock_response.stop_reason = "end_turn"

    with patch.object(dispatcher._client.messages, "create", return_value=mock_response):
        result = dispatcher.dispatch(skill, event)

    assert isinstance(result, DispatchResult)
    assert result.text == "Echo: hello"
    assert result.skill_name == "test-skill"


def test_dispatch_uses_skill_body_as_system_prompt(skill, event):
    dispatcher = SubagentDispatcher()
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="ok")]
    mock_response.stop_reason = "end_turn"

    with patch.object(dispatcher._client.messages, "create", return_value=mock_response) as mock_create:
        dispatcher.dispatch(skill, event)

    call_kwargs = mock_create.call_args.kwargs
    assert skill.body in call_kwargs["system"]


def test_dispatch_enforces_tool_permission(skill, event):
    """A skill with no tools declared should receive an empty tools list."""
    dispatcher = SubagentDispatcher()
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="ok")]
    mock_response.stop_reason = "end_turn"

    with patch.object(dispatcher._client.messages, "create", return_value=mock_response) as mock_create:
        dispatcher.dispatch(skill, event)

    call_kwargs = mock_create.call_args.kwargs
    # No tools declared in skill → tools list not passed (or empty)
    assert call_kwargs.get("tools", []) == []


def test_dispatch_injects_credentials_as_context(skill, event, tmp_path, monkeypatch):
    """Credentials should be injected into system prompt context."""
    monkeypatch.setenv("CLAUDECLAW_HOME", str(tmp_path))
    skill.credentials = ["erp-user"]

    from claudeclaw.auth.keyring import CredentialStore
    store = CredentialStore(backend="file", master_password="test")
    store.set("erp-user", "alice")

    dispatcher = SubagentDispatcher()
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="ok")]
    mock_response.stop_reason = "end_turn"

    with patch.object(dispatcher._client.messages, "create", return_value=mock_response) as mock_create:
        with patch("claudeclaw.subagent.dispatch.CredentialStore", return_value=store):
            dispatcher.dispatch(skill, event)

    system_prompt = mock_create.call_args.kwargs["system"]
    assert "alice" in system_prompt
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_dispatch.py -v
```

Expected: `ImportError`.

- [ ] **Step 3: Implement dispatcher**

```python
# claudeclaw/subagent/dispatch.py
import logging
from dataclasses import dataclass
from typing import Optional
import anthropic

from claudeclaw.skills.loader import SkillManifest
from claudeclaw.core.event import Event
from claudeclaw.auth.keyring import CredentialStore

logger = logging.getLogger(__name__)

MODEL = "claude-sonnet-4-6"


@dataclass
class DispatchResult:
    text: str
    skill_name: str
    stop_reason: str


class SubagentDispatcher:
    """
    Dispatches a Claude SDK subagent for a given skill + event.
    Enforces permissions: only tools declared in the skill are passed to the API.
    Injects credentials from Keyring into the system prompt context.
    """

    def __init__(self, client: Optional[anthropic.Anthropic] = None):
        self._client = client or anthropic.Anthropic()

    def dispatch(self, skill: SkillManifest, event: Event) -> DispatchResult:
        system_prompt = self._build_system_prompt(skill)
        tools = self._resolve_tools(skill)
        messages = [{"role": "user", "content": event.text}]

        kwargs = dict(
            model=MODEL,
            max_tokens=4096,
            system=system_prompt,
            messages=messages,
        )
        if tools:
            kwargs["tools"] = tools

        try:
            response = self._client.messages.create(**kwargs)
            text = response.content[0].text if response.content else ""
            return DispatchResult(
                text=text,
                skill_name=skill.name,
                stop_reason=response.stop_reason,
            )
        except Exception as e:
            logger.error("Subagent dispatch failed for skill '%s': %s", skill.name, e)
            raise

    def _build_system_prompt(self, skill: SkillManifest) -> str:
        # PLAN 1 SIMPLIFICATION: credentials are injected as plaintext into the system prompt.
        # The spec calls for env-var injection — that is deferred to Plan 5 (Plugins + MCPs)
        # when the full subagent sandboxing model is wired up. Do NOT change this now.
        parts = [skill.body]

        if skill.credentials:
            store = CredentialStore()
            cred_lines = []
            for key in skill.credentials:
                value = store.get(key)
                if value:
                    cred_lines.append(f"{key}: {value}")
            if cred_lines:
                parts.append("\n## Credentials\n" + "\n".join(cred_lines))

        return "\n\n".join(parts)

    def _resolve_tools(self, skill: SkillManifest) -> list:
        # Plan 1: tools list is empty or contains string names.
        # MCPs and plugins are resolved in later plans.
        # Return empty list — no tool schemas wired yet.
        return []
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_dispatch.py -v
```

Expected: 4 PASSED.

- [ ] **Step 5: Commit**

```bash
git add claudeclaw/subagent/dispatch.py tests/test_dispatch.py
git commit -m "feat: subagent dispatcher — enforces permissions, injects credentials"
```

---

## Task 10: Orchestrator Daemon

**Files:**
- Create: `claudeclaw/core/orchestrator.py`
- Create: `tests/test_orchestrator.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_orchestrator.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from claudeclaw.core.orchestrator import Orchestrator
from claudeclaw.core.event import Event, Response
from claudeclaw.skills.loader import SkillManifest


@pytest.fixture
def skill():
    return SkillManifest(
        name="echo-skill",
        description="Echoes input back",
        trigger="on-demand",
        autonomy="autonomous",
        shell_policy="none",
        body="Echo the user's message.",
    )


@pytest.mark.asyncio
async def test_orchestrator_routes_and_dispatches(skill):
    from claudeclaw.subagent.dispatch import DispatchResult

    mock_channel = MagicMock()
    mock_channel.receive = AsyncMock(return_value=aiter([
        Event(text="echo hello", channel="cli")
    ]))
    mock_channel.send = AsyncMock()

    mock_registry = MagicMock()
    mock_registry.list_skills.return_value = [skill]

    mock_router = MagicMock()
    mock_router.route.return_value = skill

    mock_dispatcher = MagicMock()
    mock_dispatcher.dispatch.return_value = DispatchResult(
        text="hello", skill_name="echo-skill", stop_reason="end_turn"
    )

    orchestrator = Orchestrator(
        channel=mock_channel,
        registry=mock_registry,
        router=mock_router,
        dispatcher=mock_dispatcher,
    )

    await orchestrator.run_once()

    mock_dispatcher.dispatch.assert_called_once()
    mock_channel.send.assert_called_once()
    sent_response = mock_channel.send.call_args[0][0]
    assert "hello" in sent_response.text


@pytest.mark.asyncio
async def test_orchestrator_sends_fallback_on_no_skill_match():
    mock_channel = MagicMock()
    mock_channel.receive = AsyncMock(return_value=aiter([
        Event(text="something unknown", channel="cli")
    ]))
    mock_channel.send = AsyncMock()

    mock_registry = MagicMock()
    mock_registry.list_skills.return_value = []

    mock_router = MagicMock()
    mock_router.route.return_value = None

    mock_dispatcher = MagicMock()

    orchestrator = Orchestrator(
        channel=mock_channel,
        registry=mock_registry,
        router=mock_router,
        dispatcher=mock_dispatcher,
    )

    await orchestrator.run_once()

    mock_dispatcher.dispatch.assert_not_called()
    mock_channel.send.assert_called_once()
    sent = mock_channel.send.call_args[0][0]
    assert "no skill" in sent.text.lower() or "don't know" in sent.text.lower()


# Helper: async generator from list
async def aiter(items):
    for item in items:
        yield item
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_orchestrator.py -v
```

Expected: `ImportError`.

- [ ] **Step 3: Implement orchestrator**

```python
# claudeclaw/core/orchestrator.py
import asyncio
import logging
from typing import Optional

from claudeclaw.core.event import Event, Response
from claudeclaw.core.router import Router
from claudeclaw.skills.registry import SkillRegistry
from claudeclaw.subagent.dispatch import SubagentDispatcher
from claudeclaw.channels.base import ChannelAdapter

logger = logging.getLogger(__name__)

FALLBACK_MESSAGE = (
    "I don't know how to help with that yet. "
    "No skill matched your request. "
    "You can teach me with: claudeclaw pop"
)


class Orchestrator:
    """
    Main daemon loop.
    Receives events from a channel, routes to a skill, dispatches a subagent,
    and sends the response back.
    """

    def __init__(
        self,
        channel: ChannelAdapter,
        registry: Optional[SkillRegistry] = None,
        router: Optional[Router] = None,
        dispatcher: Optional[SubagentDispatcher] = None,
    ):
        self._channel = channel
        self._registry = registry or SkillRegistry()
        self._dispatcher = dispatcher or SubagentDispatcher()
        # Router is created lazily after registry loads skills
        self._router = router

    def _get_router(self) -> Router:
        if self._router is None:
            skills = self._registry.list_skills()
            self._router = Router(skills)
        return self._router

    async def run_once(self):
        """Process exactly one event. Used in tests and single-shot runs."""
        router = self._get_router()
        async for event in self._channel.receive():
            await self._handle(event, router)
            return

    async def run(self):
        """Continuous daemon loop."""
        logger.info("Orchestrator started.")
        router = self._get_router()
        try:
            async for event in self._channel.receive():
                await self._handle(event, router)
        except (KeyboardInterrupt, asyncio.CancelledError):
            logger.info("Orchestrator stopped.")

    async def _handle(self, event: Event, router: Router):
        skill = router.route(event)
        if skill is None:
            logger.info("No skill matched for: %r", event.text)
            await self._channel.send(Response(text=FALLBACK_MESSAGE, event=event))
            return

        logger.info("Dispatching skill '%s' for event: %r", skill.name, event.text)
        try:
            result = self._dispatcher.dispatch(skill, event)
            await self._channel.send(Response(text=result.text, event=event))
        except Exception as e:
            logger.error("Dispatch failed: %s", e)
            await self._channel.send(
                Response(text=f"Something went wrong running '{skill.name}'. Check logs.", event=event)
            )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_orchestrator.py -v
```

Expected: 2 PASSED.

- [ ] **Step 5: Commit**

```bash
git add claudeclaw/core/orchestrator.py tests/test_orchestrator.py
git commit -m "feat: orchestrator daemon — receive, route, dispatch, respond"
```

---

## Task 11: Claude OAuth Authentication

**Files:**
- Create: `claudeclaw/auth/oauth.py`
- Create: `tests/test_oauth.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_oauth.py
import pytest
from unittest.mock import patch, MagicMock
from claudeclaw.auth.oauth import AuthManager, AuthError


def test_is_logged_in_returns_false_when_no_token(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDECLAW_HOME", str(tmp_path))
    auth = AuthManager()
    assert not auth.is_logged_in()


def test_is_logged_in_returns_true_when_token_exists(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDECLAW_HOME", str(tmp_path))
    from claudeclaw.auth.keyring import CredentialStore
    store = CredentialStore(backend="file", master_password="test")
    store.set("claude-oauth-token", "fake-token")

    auth = AuthManager()
    with patch.object(auth._store, "get", return_value="fake-token"):
        assert auth.is_logged_in()


def test_get_token_raises_when_not_logged_in(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDECLAW_HOME", str(tmp_path))
    auth = AuthManager()
    with patch.object(auth, "is_logged_in", return_value=False):
        with pytest.raises(AuthError, match="not logged in"):
            auth.get_token()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_oauth.py -v
```

Expected: `ImportError`.

- [ ] **Step 3: Implement auth manager**

```python
# claudeclaw/auth/oauth.py
"""
Claude OAuth authentication.
Uses the same OAuth mechanism as Claude Code:
- Opens browser to https://claude.ai/oauth/authorize
- Receives token via local redirect
- Stores token in Keyring
"""
import webbrowser
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import logging
from typing import Optional

from claudeclaw.auth.keyring import CredentialStore

logger = logging.getLogger(__name__)

TOKEN_KEY = "claude-oauth-token"
OAUTH_URL = "https://claude.ai/oauth/authorize"
REDIRECT_PORT = 54321
REDIRECT_URI = f"http://localhost:{REDIRECT_PORT}/callback"
# IMPORTANT: The exact OAuth client_id, scopes, and token exchange endpoint must be
# obtained from Anthropic's official documentation or by inspecting how Claude Code
# performs its own `claude auth login` flow (check the claude binary's network traffic).
# The values below are stubs. The login() method implements the authorization code flow
# correctly (code → token exchange), but _exchange_code() is a stub that must be filled
# in with the real Anthropic token endpoint before this command will work.
CLIENT_ID = "claudeclaw"   # STUB — replace with real Anthropic OAuth client_id
SCOPE = "claude:messages"  # STUB — replace with real required scopes


class AuthError(Exception):
    pass


class _CallbackHandler(BaseHTTPRequestHandler):
    token: Optional[str] = None

    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        token = params.get("token", [None])[0] or params.get("code", [None])[0]
        _CallbackHandler.token = token
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"<html><body><h2>ClaudeClaw authenticated. You can close this tab.</h2></body></html>")

    def log_message(self, *args):
        pass  # suppress request logs


class AuthManager:
    def __init__(self, store: Optional[CredentialStore] = None):
        self._store = store or CredentialStore()

    def is_logged_in(self) -> bool:
        return self._store.get(TOKEN_KEY) is not None

    def get_token(self) -> str:
        token = self._store.get(TOKEN_KEY)
        if not token:
            raise AuthError("Not logged in. Run: claudeclaw login")
        return token

    def login(self) -> None:
        """Open browser for OAuth and wait for redirect with authorization code, then exchange for token."""
        _CallbackHandler.token = None
        server = HTTPServer(("localhost", REDIRECT_PORT), _CallbackHandler)
        thread = threading.Thread(target=server.handle_request)
        thread.start()

        auth_url = (
            f"{OAUTH_URL}?client_id={CLIENT_ID}"
            f"&redirect_uri={REDIRECT_URI}&scope={SCOPE}&response_type=code"
        )
        print("Opening browser for Claude authentication...")
        webbrowser.open(auth_url)
        thread.join(timeout=120)
        server.server_close()

        code = _CallbackHandler.token
        if not code:
            raise AuthError("Authentication timed out or was cancelled.")

        # Exchange authorization code for access token
        token = self._exchange_code(code)
        self._store.set(TOKEN_KEY, token)
        print("Logged in successfully.")

    def _exchange_code(self, code: str) -> str:
        """
        Exchange OAuth authorization code for an access token.
        STUB: Fill in the real Anthropic token endpoint and parameters.
        Until this is implemented, store the code directly for local testing only.
        """
        import httpx
        # TODO: Replace with real Anthropic token endpoint discovered from Claude Code OAuth flow
        # response = httpx.post("https://claude.ai/oauth/token", data={
        #     "grant_type": "authorization_code",
        #     "code": code,
        #     "redirect_uri": REDIRECT_URI,
        #     "client_id": CLIENT_ID,
        # })
        # response.raise_for_status()
        # return response.json()["access_token"]
        logger.warning("OAuth token exchange not implemented — storing code as token (dev only)")
        return code

    def logout(self) -> None:
        self._store.delete(TOKEN_KEY)
        print("Logged out.")
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_oauth.py -v
```

Expected: 3 PASSED.

- [ ] **Step 5: Commit**

```bash
git add claudeclaw/auth/oauth.py tests/test_oauth.py
git commit -m "feat: Claude OAuth authentication — login/logout/token storage"
```

---

## Task 12: CLI Entry Point

**Files:**
- Create: `claudeclaw/cli.py`
- Create: `tests/test_cli.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_cli.py
from click.testing import CliRunner
from claudeclaw.cli import main
from unittest.mock import patch, MagicMock


def test_login_command_calls_auth_manager():
    runner = CliRunner()
    with patch("claudeclaw.cli.AuthManager") as MockAuth:
        mock_instance = MagicMock()
        MockAuth.return_value = mock_instance
        result = runner.invoke(main, ["login"])
    mock_instance.login.assert_called_once()
    assert result.exit_code == 0


def test_skills_list_command_prints_skills(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDECLAW_HOME", str(tmp_path))
    # Create a fake skill
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir(parents=True)
    (skills_dir / "my-skill.md").write_text("""---
name: my-skill
description: Does something useful
trigger: on-demand
autonomy: ask
tools: []
shell-policy: none
---
Body""")
    runner = CliRunner()
    result = runner.invoke(main, ["skills", "list"])
    assert "my-skill" in result.output
    assert result.exit_code == 0


def test_start_command_exists():
    runner = CliRunner()
    result = runner.invoke(main, ["--help"])
    assert "start" in result.output


def test_agents_run_command_exists():
    runner = CliRunner()
    result = runner.invoke(main, ["agents", "--help"])
    assert "run" in result.output
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_cli.py -v
```

Expected: `ImportError`.

- [ ] **Step 3: Implement CLI**

```python
# claudeclaw/cli.py
import asyncio
import click
from claudeclaw.auth.oauth import AuthManager
from claudeclaw.skills.registry import SkillRegistry
from claudeclaw.subagent.dispatch import SubagentDispatcher
from claudeclaw.core.router import Router
from claudeclaw.core.orchestrator import Orchestrator
from claudeclaw.channels.cli_adapter import CliAdapter


@click.group()
def main():
    """ClaudeClaw — autonomous agent system powered by Claude."""
    pass


@main.command()
def login():
    """Authenticate with your Claude account."""
    auth = AuthManager()
    auth.login()


@main.command()
def logout():
    """Log out of your Claude account."""
    auth = AuthManager()
    auth.logout()


@main.command()
@click.option("--daemon", is_flag=True, help="Run as background daemon")
def start(daemon):
    """Start the ClaudeClaw orchestrator."""
    click.echo("Starting ClaudeClaw...")
    channel = CliAdapter()
    orchestrator = Orchestrator(channel=channel)
    try:
        asyncio.run(orchestrator.run())
    except KeyboardInterrupt:
        click.echo("\nStopped.")


@main.group()
def skills():
    """Manage skills."""
    pass


@skills.command("list")
def skills_list():
    """List all installed skills."""
    registry = SkillRegistry()
    all_skills = registry.list_skills()
    if not all_skills:
        click.echo("No skills installed. Install from marketplace: claudeclaw install <skill>")
        return
    for skill in all_skills:
        trigger_info = f"[{skill.trigger}]"
        if skill.schedule:
            trigger_info = f"[cron: {skill.schedule}]"
        click.echo(f"  {skill.name:<30} {trigger_info:<25} {skill.description}")


@main.group()
def agents():
    """Manage agents."""
    pass


@agents.command("run")
@click.argument("skill_name")
@click.argument("message", default="run")
def agents_run(skill_name, message):
    """Manually trigger a skill by name."""
    registry = SkillRegistry()
    skill = registry.find(skill_name)
    if skill is None:
        click.echo(f"Skill '{skill_name}' not found. Run 'claudeclaw skills list' to see available skills.")
        raise SystemExit(1)

    from claudeclaw.core.event import Event
    event = Event(text=message, channel="cli", user_id="local")
    dispatcher = SubagentDispatcher()

    click.echo(f"Running skill '{skill_name}'...")
    result = dispatcher.dispatch(skill, event)
    click.echo(result.text)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_cli.py -v
```

Expected: 4 PASSED.

- [ ] **Step 5: Commit**

```bash
git add claudeclaw/cli.py tests/test_cli.py
git commit -m "feat: CLI entry point — login, start, skills list, agents run"
```

---

## Task 13: Full Test Suite + Integration Verification

- [ ] **Step 1: Run the full test suite**

```bash
pytest tests/ -v
```

Expected: All tests pass. Count should be 20+.

- [ ] **Step 2: Verify the CLI is importable and help works**

```bash
claudeclaw --help
claudeclaw skills --help
claudeclaw agents --help
```

Expected: Help text displayed for all commands, no import errors.

- [ ] **Step 3: Smoke test skill loading end-to-end**

Create a test skill manually:

```bash
mkdir -p ~/.claudeclaw/skills
cat > ~/.claudeclaw/skills/hello.md << 'EOF'
---
name: hello
description: Greet the user warmly
trigger: on-demand
autonomy: autonomous
tools: []
shell-policy: none
---
# Hello Skill
Greet the user warmly. Say hello and ask how you can help them today.
EOF

claudeclaw skills list
```

Expected output includes `hello` in the list.

- [ ] **Step 4: Smoke test agents run (requires Claude auth)**

If logged in (`claudeclaw login` completed):

```bash
claudeclaw agents run hello "hello there"
```

Expected: Claude response text printed to stdout.

- [ ] **Step 5: Final commit**

```bash
git add .
git commit -m "feat: plan 1 complete — core foundation working end-to-end"
```

---

## Summary

After this plan, ClaudeClaw can:

1. `claudeclaw login` — authenticate with Claude account, token in Keyring
2. `claudeclaw skills list` — list `.md` skills from `~/.claudeclaw/skills/`
3. `claudeclaw agents run <skill> "<message>"` — dispatch a Claude subagent with a skill
4. `claudeclaw start` — run the orchestrator daemon, accepting CLI input, routing to skills

**Next plan:** Plan 2 — Telegram channel adapter + POP native skill
