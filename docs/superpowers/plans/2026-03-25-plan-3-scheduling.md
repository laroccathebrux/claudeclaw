# ClaudeClaw — Plan 3: Scheduling (Claude Cron + Remote Triggers)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement autonomous scheduling for ClaudeClaw. Skills with `trigger: cron` are registered with the Claude SDK via `CronCreate` at startup; skills with `trigger: webhook` are registered via `RemoteTrigger`. When either fires, the SDK delivers a `tool_use` event that the orchestrator normalizes into an `Event` and dispatches as a skill run. Adds `claudeclaw schedule list` and `claudeclaw schedule run` CLI commands.

**Architecture:** A `ScheduleManager` class (`claudeclaw/scheduling/manager.py`) handles all SDK registration and inbound event normalization. The orchestrator's startup sequence is extended to call `ScheduleManager.register_crons()` and `register_webhooks()` before the channel loop starts. Registration state is persisted in `~/.claudeclaw/config/schedules.yaml` and `~/.claudeclaw/config/triggers.yaml` so re-registrations are idempotent across restarts.

**Tech Stack:** Python 3.11+, `anthropic` SDK (CronCreate / RemoteTrigger tool protocol), `pyyaml` (registry persistence), `click` (CLI), `pytest` + `pytest-asyncio` + `pytest-mock` (tests)

**Spec reference:** `docs/superpowers/specs/2026-03-25-plan-3-scheduling-spec.md`

---

## File Map

```
claudeclaw/
├── claudeclaw/
│   ├── scheduling/
│   │   ├── __init__.py                 ← new module
│   │   └── manager.py                  ← ScheduleManager: register + handle events
│   ├── core/
│   │   └── event.py                    ← extend: source="cron"|"webhook"|"manual", skill_name field
│   └── cli.py                          ← extend: add `schedule list` and `schedule run` commands
└── tests/
    ├── conftest.py                     ← extend: add mock_sdk_client, sample cron/webhook skill fixtures
    ├── test_schedule_manager.py        ← new: all ScheduleManager unit tests
    └── test_schedule_cli.py            ← new: CLI schedule subcommand tests
```

Config files (written at runtime, not committed):
```
~/.claudeclaw/config/schedules.yaml    ← cron registrations
~/.claudeclaw/config/triggers.yaml     ← webhook registrations
```

---

## Task 1: ScheduleManager — CronCreate Registration

**Files:**
- Create: `claudeclaw/scheduling/__init__.py`
- Create: `claudeclaw/scheduling/manager.py`
- Extend: `tests/conftest.py` (add cron skill fixture and mock SDK client)
- Create: `tests/test_schedule_manager.py`

- [ ] **Step 1: Add fixtures to `tests/conftest.py`**

Add the following fixtures to the existing `conftest.py`:

```python
# append to tests/conftest.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from claudeclaw.skills.loader import Skill


@pytest.fixture
def cron_skill():
    """A skill with trigger: cron."""
    return Skill(
        name="erp-invoices",
        description="Send monthly invoices",
        trigger="cron",
        schedule="0 0 28 * *",
        trigger_id=None,
        autonomy="autonomous",
        tools=[],
        shell_policy="none",
        body="Send invoices to all clients.",
    )


@pytest.fixture
def webhook_skill():
    """A skill with trigger: webhook."""
    return Skill(
        name="crm-followup",
        description="Follow up on new CRM leads",
        trigger="webhook",
        schedule=None,
        trigger_id="new-crm-lead",
        autonomy="notify",
        tools=[],
        shell_policy="none",
        body="Process the new lead.",
    )


@pytest.fixture
def mock_sdk_client():
    """Mock Anthropic SDK client that records CronCreate/RemoteTrigger tool calls."""
    client = MagicMock()
    client.beta = MagicMock()

    async def fake_cron_create(schedule: str, metadata: dict):
        return {"cron_id": f"cron_mock_{schedule.replace(' ', '_')}"}

    async def fake_cron_delete(cron_id: str):
        return {"deleted": True}

    async def fake_remote_trigger(trigger_id: str):
        return {"webhook_url": f"https://hooks.anthropic.com/rt/{trigger_id}"}

    client.beta.cron_create = AsyncMock(side_effect=fake_cron_create)
    client.beta.cron_delete = AsyncMock(side_effect=fake_cron_delete)
    client.beta.remote_trigger = AsyncMock(side_effect=fake_remote_trigger)
    return client
```

- [ ] **Step 2: Write the failing test for CronCreate registration**

```python
# tests/test_schedule_manager.py
import pytest
import yaml
from pathlib import Path
from claudeclaw.scheduling.manager import ScheduleManager


@pytest.mark.asyncio
async def test_register_cron_calls_sdk(tmp_path, monkeypatch, mock_sdk_client, cron_skill):
    monkeypatch.setenv("CLAUDECLAW_HOME", str(tmp_path))
    manager = ScheduleManager(sdk_client=mock_sdk_client)
    await manager.register_crons([cron_skill])
    mock_sdk_client.beta.cron_create.assert_awaited_once()
    call_kwargs = mock_sdk_client.beta.cron_create.call_args
    assert call_kwargs.kwargs["schedule"] == "0 0 28 * *"
    assert call_kwargs.kwargs["metadata"]["skill_name"] == "erp-invoices"


@pytest.mark.asyncio
async def test_register_cron_persists_to_yaml(tmp_path, monkeypatch, mock_sdk_client, cron_skill):
    monkeypatch.setenv("CLAUDECLAW_HOME", str(tmp_path))
    manager = ScheduleManager(sdk_client=mock_sdk_client)
    await manager.register_crons([cron_skill])
    schedules_file = tmp_path / "config" / "schedules.yaml"
    assert schedules_file.exists()
    data = yaml.safe_load(schedules_file.read_text())
    assert "erp-invoices" in data
    assert data["erp-invoices"]["schedule"] == "0 0 28 * *"
    assert data["erp-invoices"]["cron_id"].startswith("cron_")


@pytest.mark.asyncio
async def test_register_cron_is_idempotent(tmp_path, monkeypatch, mock_sdk_client, cron_skill):
    """Second call with same schedule should not call SDK again."""
    monkeypatch.setenv("CLAUDECLAW_HOME", str(tmp_path))
    manager = ScheduleManager(sdk_client=mock_sdk_client)
    await manager.register_crons([cron_skill])
    await manager.register_crons([cron_skill])
    assert mock_sdk_client.beta.cron_create.await_count == 1


@pytest.mark.asyncio
async def test_register_cron_rereg_on_schedule_change(tmp_path, monkeypatch, mock_sdk_client, cron_skill):
    """If schedule expression changes, old cron is deleted and new one created."""
    monkeypatch.setenv("CLAUDECLAW_HOME", str(tmp_path))
    manager = ScheduleManager(sdk_client=mock_sdk_client)
    await manager.register_crons([cron_skill])

    # Change schedule
    from dataclasses import replace
    updated_skill = replace(cron_skill, schedule="0 6 * * 1")
    manager2 = ScheduleManager(sdk_client=mock_sdk_client)
    await manager2.register_crons([updated_skill])

    mock_sdk_client.beta.cron_delete.assert_awaited_once()
    assert mock_sdk_client.beta.cron_create.await_count == 2


@pytest.mark.asyncio
async def test_on_demand_skills_are_skipped(tmp_path, monkeypatch, mock_sdk_client, sample_skill_md):
    """Skills with trigger: on-demand are not registered."""
    monkeypatch.setenv("CLAUDECLAW_HOME", str(tmp_path))
    from claudeclaw.skills.loader import SkillLoader
    loader = SkillLoader()
    skill = loader.load(sample_skill_md)
    manager = ScheduleManager(sdk_client=mock_sdk_client)
    await manager.register_crons([skill])
    mock_sdk_client.beta.cron_create.assert_not_awaited()
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
pytest tests/test_schedule_manager.py -v
```

Expected: `ImportError` — `claudeclaw.scheduling.manager` does not exist yet.

- [ ] **Step 4: Create `claudeclaw/scheduling/__init__.py`**

Empty file:

```python
# claudeclaw/scheduling/__init__.py
```

- [ ] **Step 5: Implement `claudeclaw/scheduling/manager.py` (CronCreate only)**

```python
# claudeclaw/scheduling/manager.py
from __future__ import annotations

import yaml
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from claudeclaw.config.settings import get_settings
from claudeclaw.core.event import Event


class ScheduleManager:
    """
    Manages CronCreate and RemoteTrigger SDK registrations.
    Persists state to schedules.yaml and triggers.yaml.
    """

    def __init__(self, sdk_client=None, settings=None):
        self._client = sdk_client
        self._settings = settings or get_settings()
        self._schedules_file = self._settings.config_dir / "schedules.yaml"
        self._triggers_file = self._settings.config_dir / "triggers.yaml"

    # ------------------------------------------------------------------ #
    #  Internal helpers                                                    #
    # ------------------------------------------------------------------ #

    def _load_schedules(self) -> dict:
        if not self._schedules_file.exists():
            return {}
        return yaml.safe_load(self._schedules_file.read_text()) or {}

    def _save_schedules(self, data: dict) -> None:
        self._schedules_file.write_text(yaml.dump(data, default_flow_style=False))

    def _load_triggers(self) -> dict:
        if not self._triggers_file.exists():
            return {}
        return yaml.safe_load(self._triggers_file.read_text()) or {}

    def _save_triggers(self, data: dict) -> None:
        self._triggers_file.write_text(yaml.dump(data, default_flow_style=False))

    def _now_iso(self) -> str:
        return datetime.now(tz=timezone.utc).isoformat()

    # ------------------------------------------------------------------ #
    #  CronCreate registration                                             #
    # ------------------------------------------------------------------ #

    async def register_crons(self, skills: list) -> None:
        """Register all cron skills with the SDK. Idempotent."""
        data = self._load_schedules()

        for skill in skills:
            if getattr(skill, "trigger", None) != "cron":
                continue
            schedule = skill.schedule
            existing = data.get(skill.name)

            if existing and existing.get("schedule") == schedule:
                # Already registered with same expression — skip.
                continue

            if existing:
                # Schedule changed — delete old registration.
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
        """Remove cron or webhook registration for a skill on uninstall."""
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
```

- [ ] **Step 6: Run CronCreate tests to verify they pass**

```bash
pytest tests/test_schedule_manager.py::test_register_cron_calls_sdk \
       tests/test_schedule_manager.py::test_register_cron_persists_to_yaml \
       tests/test_schedule_manager.py::test_register_cron_is_idempotent \
       tests/test_schedule_manager.py::test_register_cron_rereg_on_schedule_change \
       tests/test_schedule_manager.py::test_on_demand_skills_are_skipped \
       -v
```

Expected: 5 PASSED.

- [ ] **Step 7: Commit**

```bash
git add claudeclaw/scheduling/__init__.py claudeclaw/scheduling/manager.py \
        tests/conftest.py tests/test_schedule_manager.py
git commit -m "feat(scheduling): ScheduleManager with CronCreate registration and schedules.yaml persistence"
```

---

## Task 2: CronCreate Event Handling — SDK tool_use → Event → Dispatch

**Files:**
- Extend: `claudeclaw/scheduling/manager.py` (add `handle_tool_use_event`)
- Extend: `claudeclaw/core/event.py` (add `source`, `skill_name`, `payload` fields if not present)
- Extend: `tests/test_schedule_manager.py`

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/test_schedule_manager.py

@pytest.mark.asyncio
async def test_handle_cron_fired_returns_event(tmp_path, monkeypatch, mock_sdk_client, cron_skill):
    monkeypatch.setenv("CLAUDECLAW_HOME", str(tmp_path))
    manager = ScheduleManager(sdk_client=mock_sdk_client)
    await manager.register_crons([cron_skill])

    # Simulate SDK delivering a CronFired tool_use block
    cron_id = (yaml.safe_load((tmp_path / "config" / "schedules.yaml").read_text())
               ["erp-invoices"]["cron_id"])
    tool_use_block = {
        "type": "tool_use",
        "name": "CronFired",
        "input": {"cron_id": cron_id, "fired_at": "2026-03-28T00:00:00Z"},
    }
    event = await manager.handle_tool_use_event(tool_use_block)
    assert event is not None
    assert event.source == "cron"
    assert event.skill_name == "erp-invoices"
    assert event.payload["fired_at"] == "2026-03-28T00:00:00Z"
    assert event.channel_reply_fn is None


@pytest.mark.asyncio
async def test_handle_unknown_tool_use_returns_none(tmp_path, monkeypatch, mock_sdk_client):
    monkeypatch.setenv("CLAUDECLAW_HOME", str(tmp_path))
    manager = ScheduleManager(sdk_client=mock_sdk_client)
    tool_use_block = {
        "type": "tool_use",
        "name": "SomeOtherTool",
        "input": {"foo": "bar"},
    }
    event = await manager.handle_tool_use_event(tool_use_block)
    assert event is None


@pytest.mark.asyncio
async def test_handle_cron_fired_unknown_cron_id_returns_none(tmp_path, monkeypatch, mock_sdk_client):
    monkeypatch.setenv("CLAUDECLAW_HOME", str(tmp_path))
    manager = ScheduleManager(sdk_client=mock_sdk_client)
    tool_use_block = {
        "type": "tool_use",
        "name": "CronFired",
        "input": {"cron_id": "cron_does_not_exist", "fired_at": "2026-03-28T00:00:00Z"},
    }
    event = await manager.handle_tool_use_event(tool_use_block)
    assert event is None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_schedule_manager.py::test_handle_cron_fired_returns_event \
       tests/test_schedule_manager.py::test_handle_unknown_tool_use_returns_none \
       tests/test_schedule_manager.py::test_handle_cron_fired_unknown_cron_id_returns_none \
       -v
```

Expected: `AttributeError` or `ImportError` — `handle_tool_use_event` not implemented yet.

- [ ] **Step 3: Extend `claudeclaw/core/event.py` to support scheduling sources**

Ensure the `Event` dataclass has these fields (add them if Plan 1 did not include them):

```python
# claudeclaw/core/event.py  (extend existing file)
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Callable, Any


@dataclass
class Event:
    source: str                          # "cli" | "telegram" | "cron" | "webhook" | "manual"
    text: str | None = None              # human message text; None for scheduled events
    skill_name: str | None = None        # pre-resolved for cron/webhook/manual events
    payload: dict = field(default_factory=dict)
    channel_reply_fn: Callable | None = None   # None for headless scheduled events
```

If `event.py` already exists with a different shape, add `skill_name` and `payload` fields without removing existing fields.

- [ ] **Step 4: Implement `handle_tool_use_event` in `manager.py`**

Add this method to the `ScheduleManager` class:

```python
    async def handle_tool_use_event(self, block: dict) -> "Event | None":
        """
        Normalize an SDK tool_use block into an Event.
        Returns None if the block is not a scheduling trigger.
        """
        name = block.get("name")
        inp = block.get("input", {})

        if name == "CronFired":
            cron_id = inp.get("cron_id")
            schedules = self._load_schedules()
            skill_name = next(
                (sn for sn, meta in schedules.items() if meta["cron_id"] == cron_id),
                None,
            )
            if skill_name is None:
                return None
            return Event(
                source="cron",
                skill_name=skill_name,
                payload={"fired_at": inp.get("fired_at")},
                channel_reply_fn=None,
            )

        if name == "RemoteTriggerFired":
            trigger_id = inp.get("trigger_id")
            triggers = self._load_triggers()
            entry = triggers.get(trigger_id)
            if entry is None:
                return None
            return Event(
                source="webhook",
                skill_name=entry["skill_name"],
                payload=inp.get("payload", {}),
                channel_reply_fn=None,
            )

        return None
```

- [ ] **Step 5: Run all schedule manager tests**

```bash
pytest tests/test_schedule_manager.py -v
```

Expected: all tests PASSED.

- [ ] **Step 6: Commit**

```bash
git add claudeclaw/scheduling/manager.py claudeclaw/core/event.py \
        tests/test_schedule_manager.py
git commit -m "feat(scheduling): CronFired tool_use event → normalized Event dispatch"
```

---

## Task 3: RemoteTrigger Registration

**Files:**
- Extend: `claudeclaw/scheduling/manager.py` (add `register_webhooks`)
- Extend: `tests/test_schedule_manager.py`

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/test_schedule_manager.py

@pytest.mark.asyncio
async def test_register_webhook_calls_sdk(tmp_path, monkeypatch, mock_sdk_client, webhook_skill):
    monkeypatch.setenv("CLAUDECLAW_HOME", str(tmp_path))
    manager = ScheduleManager(sdk_client=mock_sdk_client)
    await manager.register_webhooks([webhook_skill])
    mock_sdk_client.beta.remote_trigger.assert_awaited_once()
    call_kwargs = mock_sdk_client.beta.remote_trigger.call_args
    assert call_kwargs.kwargs["trigger_id"] == "new-crm-lead"


@pytest.mark.asyncio
async def test_register_webhook_persists_to_yaml(tmp_path, monkeypatch, mock_sdk_client, webhook_skill):
    monkeypatch.setenv("CLAUDECLAW_HOME", str(tmp_path))
    manager = ScheduleManager(sdk_client=mock_sdk_client)
    await manager.register_webhooks([webhook_skill])
    triggers_file = tmp_path / "config" / "triggers.yaml"
    assert triggers_file.exists()
    data = yaml.safe_load(triggers_file.read_text())
    assert "new-crm-lead" in data
    assert data["new-crm-lead"]["skill_name"] == "crm-followup"
    assert "webhook_url" in data["new-crm-lead"]


@pytest.mark.asyncio
async def test_register_webhook_is_idempotent(tmp_path, monkeypatch, mock_sdk_client, webhook_skill):
    monkeypatch.setenv("CLAUDECLAW_HOME", str(tmp_path))
    manager = ScheduleManager(sdk_client=mock_sdk_client)
    await manager.register_webhooks([webhook_skill])
    await manager.register_webhooks([webhook_skill])
    assert mock_sdk_client.beta.remote_trigger.await_count == 1


@pytest.mark.asyncio
async def test_deregister_webhook_skill(tmp_path, monkeypatch, mock_sdk_client, webhook_skill):
    monkeypatch.setenv("CLAUDECLAW_HOME", str(tmp_path))
    manager = ScheduleManager(sdk_client=mock_sdk_client)
    await manager.register_webhooks([webhook_skill])
    await manager.deregister_skill("crm-followup")
    data = yaml.safe_load((tmp_path / "config" / "triggers.yaml").read_text()) or {}
    assert "new-crm-lead" not in data
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_schedule_manager.py::test_register_webhook_calls_sdk \
       tests/test_schedule_manager.py::test_register_webhook_persists_to_yaml \
       tests/test_schedule_manager.py::test_register_webhook_is_idempotent \
       tests/test_schedule_manager.py::test_deregister_webhook_skill \
       -v
```

Expected: `AttributeError` — `register_webhooks` not implemented yet.

- [ ] **Step 3: Implement `register_webhooks` in `manager.py`**

Add to `ScheduleManager`:

```python
    async def register_webhooks(self, skills: list) -> None:
        """Register all webhook skills with the SDK. Idempotent."""
        data = self._load_triggers()

        for skill in skills:
            if getattr(skill, "trigger", None) != "webhook":
                continue
            trigger_id = skill.trigger_id
            if not trigger_id:
                continue
            if trigger_id in data:
                # Already registered — skip.
                continue

            result = await self._client.beta.remote_trigger(trigger_id=trigger_id)
            data[trigger_id] = {
                "skill_name": skill.name,
                "webhook_url": result["webhook_url"],
                "registered_at": self._now_iso(),
            }

        self._save_triggers(data)
```

- [ ] **Step 4: Run all RemoteTrigger tests**

```bash
pytest tests/test_schedule_manager.py -v
```

Expected: all tests PASSED.

- [ ] **Step 5: Commit**

```bash
git add claudeclaw/scheduling/manager.py tests/test_schedule_manager.py
git commit -m "feat(scheduling): RemoteTrigger registration and triggers.yaml persistence"
```

---

## Task 4: RemoteTrigger Event Handling — Inbound Webhook → Normalized Event

**Files:**
- Extend: `claudeclaw/scheduling/manager.py` (`handle_tool_use_event` already handles `RemoteTriggerFired` — verify it works end-to-end)
- Extend: `tests/test_schedule_manager.py`

- [ ] **Step 1: Write the failing end-to-end webhook event test**

```python
# append to tests/test_schedule_manager.py

@pytest.mark.asyncio
async def test_handle_remote_trigger_fired_returns_event(
    tmp_path, monkeypatch, mock_sdk_client, webhook_skill
):
    monkeypatch.setenv("CLAUDECLAW_HOME", str(tmp_path))
    manager = ScheduleManager(sdk_client=mock_sdk_client)
    await manager.register_webhooks([webhook_skill])

    tool_use_block = {
        "type": "tool_use",
        "name": "RemoteTriggerFired",
        "input": {
            "trigger_id": "new-crm-lead",
            "payload": {"lead_name": "Acme Corp", "email": "contact@acme.com"},
        },
    }
    event = await manager.handle_tool_use_event(tool_use_block)
    assert event is not None
    assert event.source == "webhook"
    assert event.skill_name == "crm-followup"
    assert event.payload["lead_name"] == "Acme Corp"
    assert event.channel_reply_fn is None


@pytest.mark.asyncio
async def test_handle_remote_trigger_unknown_id_returns_none(
    tmp_path, monkeypatch, mock_sdk_client
):
    monkeypatch.setenv("CLAUDECLAW_HOME", str(tmp_path))
    manager = ScheduleManager(sdk_client=mock_sdk_client)
    tool_use_block = {
        "type": "tool_use",
        "name": "RemoteTriggerFired",
        "input": {"trigger_id": "nonexistent-trigger", "payload": {}},
    }
    event = await manager.handle_tool_use_event(tool_use_block)
    assert event is None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_schedule_manager.py::test_handle_remote_trigger_fired_returns_event \
       tests/test_schedule_manager.py::test_handle_remote_trigger_unknown_id_returns_none \
       -v
```

Expected: FAILED — `RemoteTriggerFired` branch in `handle_tool_use_event` depends on `triggers.yaml` which needs `register_webhooks` to have been called first (end-to-end wiring check).

- [ ] **Step 3: Verify the existing implementation covers these cases**

Review `handle_tool_use_event` in `manager.py`. The `RemoteTriggerFired` branch was written in Task 2. If any edge case is missing, fix it now. No new code should be required if Task 3 was implemented correctly.

- [ ] **Step 4: Run all schedule manager tests**

```bash
pytest tests/test_schedule_manager.py -v
```

Expected: all tests PASSED.

- [ ] **Step 5: Commit**

```bash
git add claudeclaw/scheduling/manager.py tests/test_schedule_manager.py
git commit -m "test(scheduling): end-to-end RemoteTriggerFired → Event normalization coverage"
```

---

## Task 5: Schedule Persistence — schedules.yaml + triggers.yaml Read/Write

**Files:**
- Extend: `tests/test_schedule_manager.py` (persistence edge cases)

- [ ] **Step 1: Write the failing persistence tests**

```python
# append to tests/test_schedule_manager.py

@pytest.mark.asyncio
async def test_schedules_yaml_survives_restart(tmp_path, monkeypatch, mock_sdk_client, cron_skill):
    """State persisted to YAML is correctly loaded by a new ScheduleManager instance."""
    monkeypatch.setenv("CLAUDECLAW_HOME", str(tmp_path))

    manager1 = ScheduleManager(sdk_client=mock_sdk_client)
    await manager1.register_crons([cron_skill])

    # Simulate restart — new ScheduleManager instance, same CLAUDECLAW_HOME
    manager2 = ScheduleManager(sdk_client=mock_sdk_client)
    await manager2.register_crons([cron_skill])

    # Should NOT have called cron_create a second time
    assert mock_sdk_client.beta.cron_create.await_count == 1


@pytest.mark.asyncio
async def test_triggers_yaml_survives_restart(tmp_path, monkeypatch, mock_sdk_client, webhook_skill):
    monkeypatch.setenv("CLAUDECLAW_HOME", str(tmp_path))

    manager1 = ScheduleManager(sdk_client=mock_sdk_client)
    await manager1.register_webhooks([webhook_skill])

    manager2 = ScheduleManager(sdk_client=mock_sdk_client)
    await manager2.register_webhooks([webhook_skill])

    assert mock_sdk_client.beta.remote_trigger.await_count == 1


@pytest.mark.asyncio
async def test_deregister_cron_skill(tmp_path, monkeypatch, mock_sdk_client, cron_skill):
    monkeypatch.setenv("CLAUDECLAW_HOME", str(tmp_path))
    manager = ScheduleManager(sdk_client=mock_sdk_client)
    await manager.register_crons([cron_skill])
    await manager.deregister_skill("erp-invoices")
    mock_sdk_client.beta.cron_delete.assert_awaited_once()
    data = yaml.safe_load((tmp_path / "config" / "schedules.yaml").read_text()) or {}
    assert "erp-invoices" not in data


@pytest.mark.asyncio
async def test_deregister_nonexistent_skill_is_noop(tmp_path, monkeypatch, mock_sdk_client):
    monkeypatch.setenv("CLAUDECLAW_HOME", str(tmp_path))
    manager = ScheduleManager(sdk_client=mock_sdk_client)
    # Should not raise
    await manager.deregister_skill("skill-that-was-never-registered")
    mock_sdk_client.beta.cron_delete.assert_not_awaited()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_schedule_manager.py::test_schedules_yaml_survives_restart \
       tests/test_schedule_manager.py::test_triggers_yaml_survives_restart \
       tests/test_schedule_manager.py::test_deregister_cron_skill \
       tests/test_schedule_manager.py::test_deregister_nonexistent_skill_is_noop \
       -v
```

Expected: some FAIL — persistence across instances and noop deregister may not be covered yet.

- [ ] **Step 3: Fix any gaps in `manager.py`**

Ensure `_load_schedules` returns `{}` when the file is missing or empty (not `None`). Ensure `deregister_skill` does not raise when the skill is not present in either registry. Patch as needed.

- [ ] **Step 4: Run all schedule manager tests**

```bash
pytest tests/test_schedule_manager.py -v
```

Expected: all tests PASSED.

- [ ] **Step 5: Commit**

```bash
git add claudeclaw/scheduling/manager.py tests/test_schedule_manager.py
git commit -m "test(scheduling): persistence edge cases — restart idempotency and safe deregister"
```

---

## Task 6: CLI — `schedule list` and `schedule run`

**Files:**
- Extend: `claudeclaw/cli.py` (add `schedule` group with `list` and `run` subcommands)
- Create: `tests/test_schedule_cli.py`

- [ ] **Step 1: Write the failing CLI tests**

```python
# tests/test_schedule_cli.py
import pytest
import yaml
from click.testing import CliRunner
from claudeclaw.cli import main


@pytest.fixture
def populated_config(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDECLAW_HOME", str(tmp_path))
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)

    schedules = {
        "erp-invoices": {
            "cron_id": "cron_abc123",
            "schedule": "0 0 28 * *",
            "registered_at": "2026-03-25T10:00:00Z",
        },
    }
    (config_dir / "schedules.yaml").write_text(yaml.dump(schedules))

    triggers = {
        "new-crm-lead": {
            "skill_name": "crm-followup",
            "webhook_url": "https://hooks.anthropic.com/rt/xyz789",
            "registered_at": "2026-03-25T10:00:01Z",
        },
    }
    (config_dir / "triggers.yaml").write_text(yaml.dump(triggers))
    return tmp_path


def test_schedule_list_shows_cron(populated_config):
    runner = CliRunner()
    result = runner.invoke(main, ["schedule", "list"])
    assert result.exit_code == 0
    assert "erp-invoices" in result.output
    assert "0 0 28 * *" in result.output


def test_schedule_list_shows_webhook(populated_config):
    runner = CliRunner()
    result = runner.invoke(main, ["schedule", "list"])
    assert result.exit_code == 0
    assert "new-crm-lead" in result.output
    assert "crm-followup" in result.output


def test_schedule_list_empty_shows_message(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDECLAW_HOME", str(tmp_path))
    (tmp_path / "config").mkdir(parents=True, exist_ok=True)
    runner = CliRunner()
    result = runner.invoke(main, ["schedule", "list"])
    assert result.exit_code == 0
    assert "No" in result.output or "empty" in result.output.lower()


def test_schedule_run_fires_skill(populated_config, monkeypatch):
    """schedule run should invoke the subagent for the named skill."""
    from unittest.mock import AsyncMock, patch

    runner = CliRunner()
    with patch("claudeclaw.cli.dispatch_skill", new_callable=AsyncMock) as mock_dispatch:
        mock_dispatch.return_value = "Done."
        result = runner.invoke(main, ["schedule", "run", "erp-invoices"])

    assert result.exit_code == 0
    assert "erp-invoices" in result.output


def test_schedule_run_unknown_skill_exits_nonzero(populated_config):
    runner = CliRunner()
    result = runner.invoke(main, ["schedule", "run", "skill-that-does-not-exist"])
    assert result.exit_code != 0
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_schedule_cli.py -v
```

Expected: `UsageError` or `NoSuchCommand` — `schedule` group not implemented yet.

- [ ] **Step 3: Add `schedule` CLI group to `claudeclaw/cli.py`**

Add the following to the existing `cli.py` (after existing command groups):

```python
# in claudeclaw/cli.py — add after existing groups

import asyncio
import yaml as _yaml
from claudeclaw.config.settings import get_settings as _get_settings


@main.group()
def schedule():
    """Manage scheduled skills (cron and webhook triggers)."""


@schedule.command("list")
def schedule_list():
    """List all registered cron schedules and webhook triggers."""
    settings = _get_settings()

    schedules_file = settings.config_dir / "schedules.yaml"
    triggers_file = settings.config_dir / "triggers.yaml"

    schedules = {}
    if schedules_file.exists():
        schedules = _yaml.safe_load(schedules_file.read_text()) or {}

    triggers = {}
    if triggers_file.exists():
        triggers = _yaml.safe_load(triggers_file.read_text()) or {}

    if not schedules and not triggers:
        click.echo("No schedules or webhook triggers registered.")
        return

    if schedules:
        click.echo("\nCRON SCHEDULES")
        for skill_name, meta in schedules.items():
            click.echo(f"  {skill_name:<25} {meta['schedule']:<20} {meta['cron_id']}")

    if triggers:
        click.echo("\nWEBHOOK TRIGGERS")
        for trigger_id, meta in triggers.items():
            click.echo(
                f"  {trigger_id:<25} skill: {meta['skill_name']:<20} {meta['webhook_url']}"
            )


@schedule.command("run")
@click.argument("skill_name")
def schedule_run(skill_name: str):
    """Manually fire a scheduled skill immediately."""
    from claudeclaw.skills.registry import SkillRegistry
    from claudeclaw.core.event import Event

    settings = _get_settings()
    registry = SkillRegistry(skills_dir=settings.skills_dir)
    skill = registry.find_by_name(skill_name)

    if skill is None:
        click.echo(f"Error: skill '{skill_name}' not found.", err=True)
        raise SystemExit(1)

    click.echo(f"Firing {skill_name} manually...")

    event = Event(
        source="manual",
        skill_name=skill_name,
        payload={},
        channel_reply_fn=None,
    )

    # Import here to avoid circular imports; dispatch_skill is the Plan 1 subagent dispatcher
    from claudeclaw.subagent.dispatch import dispatch_skill

    async def _run():
        return await dispatch_skill(skill=skill, event=event)

    result = asyncio.run(_run())
    click.echo(f"Done. Result: {result}")
```

- [ ] **Step 4: Run CLI tests**

```bash
pytest tests/test_schedule_cli.py -v
```

Expected: all tests PASSED (the `dispatch_skill` mock prevents actual SDK calls).

- [ ] **Step 5: Run full test suite to check for regressions**

```bash
pytest tests/ -v
```

Expected: all tests PASSED.

- [ ] **Step 6: Commit**

```bash
git add claudeclaw/cli.py tests/test_schedule_cli.py
git commit -m "feat(cli): schedule list and schedule run subcommands"
```

---

## Task 7: Integration Verification — Full Startup Sequence with a Cron Skill

**Files:**
- Create: `tests/test_scheduling_integration.py`
- Create: `tests/fixtures/cron-test-skill.md` (sample skill file for integration test)

- [ ] **Step 1: Create the sample cron skill fixture file**

```markdown
---
name: cron-test-skill
description: A scheduled skill for integration testing
trigger: cron
schedule: "*/5 * * * *"
autonomy: autonomous
tools: []
shell-policy: none
---
# Cron Test Skill
Run every 5 minutes. Log a heartbeat.
```

Write to: `tests/fixtures/cron-test-skill.md`

- [ ] **Step 2: Write the integration test**

```python
# tests/test_scheduling_integration.py
import pytest
import yaml
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.fixture
def integration_skills_dir(tmp_path):
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    fixture = Path(__file__).parent / "fixtures" / "cron-test-skill.md"
    (skills_dir / "cron-test-skill.md").write_text(fixture.read_text())
    return skills_dir


@pytest.mark.asyncio
async def test_full_startup_registers_cron_skill(tmp_path, monkeypatch, integration_skills_dir):
    """
    Simulates the orchestrator startup sequence:
    1. Load skills from directory
    2. register_crons() — should call CronCreate for the cron skill
    3. register_webhooks() — no webhook skills, should be a no-op
    4. Verify schedules.yaml is written correctly
    """
    monkeypatch.setenv("CLAUDECLAW_HOME", str(tmp_path))

    # Step 1: Load skills
    from claudeclaw.skills.loader import SkillLoader
    from claudeclaw.skills.registry import SkillRegistry

    registry = SkillRegistry(skills_dir=integration_skills_dir)
    all_skills = registry.list_all()
    assert len(all_skills) == 1
    assert all_skills[0].name == "cron-test-skill"
    assert all_skills[0].trigger == "cron"
    assert all_skills[0].schedule == "*/5 * * * *"

    # Step 2 & 3: Register via ScheduleManager
    from unittest.mock import AsyncMock
    mock_client = MagicMock()
    mock_client.beta.cron_create = AsyncMock(return_value={"cron_id": "cron_integration_001"})
    mock_client.beta.cron_delete = AsyncMock(return_value={"deleted": True})
    mock_client.beta.remote_trigger = AsyncMock(return_value={"webhook_url": "https://example.com"})

    from claudeclaw.scheduling.manager import ScheduleManager
    manager = ScheduleManager(sdk_client=mock_client)
    await manager.register_crons(all_skills)
    await manager.register_webhooks(all_skills)

    # Step 4: Verify
    mock_client.beta.cron_create.assert_awaited_once_with(
        schedule="*/5 * * * *",
        metadata={"skill_name": "cron-test-skill"},
    )
    mock_client.beta.remote_trigger.assert_not_awaited()

    schedules_file = tmp_path / "config" / "schedules.yaml"
    assert schedules_file.exists()
    data = yaml.safe_load(schedules_file.read_text())
    assert data["cron-test-skill"]["cron_id"] == "cron_integration_001"


@pytest.mark.asyncio
async def test_cron_fired_event_dispatched_correctly(tmp_path, monkeypatch, integration_skills_dir):
    """
    Simulates the full cycle: register → receive CronFired → get normalized Event
    with the correct skill_name.
    """
    monkeypatch.setenv("CLAUDECLAW_HOME", str(tmp_path))

    from claudeclaw.skills.registry import SkillRegistry
    from claudeclaw.scheduling.manager import ScheduleManager

    registry = SkillRegistry(skills_dir=integration_skills_dir)
    skills = registry.list_all()

    mock_client = MagicMock()
    mock_client.beta.cron_create = AsyncMock(return_value={"cron_id": "cron_int_fire_001"})
    mock_client.beta.cron_delete = AsyncMock(return_value={"deleted": True})
    mock_client.beta.remote_trigger = AsyncMock(return_value={"webhook_url": "https://example.com"})

    manager = ScheduleManager(sdk_client=mock_client)
    await manager.register_crons(skills)

    # Simulate the SDK delivering a CronFired event
    tool_use_block = {
        "type": "tool_use",
        "name": "CronFired",
        "input": {"cron_id": "cron_int_fire_001", "fired_at": "2026-03-25T10:05:00Z"},
    }
    event = await manager.handle_tool_use_event(tool_use_block)

    assert event is not None
    assert event.source == "cron"
    assert event.skill_name == "cron-test-skill"
    assert event.payload["fired_at"] == "2026-03-25T10:05:00Z"
    assert event.channel_reply_fn is None
```

- [ ] **Step 3: Run integration tests to verify they fail**

```bash
pytest tests/test_scheduling_integration.py -v
```

Expected: some failures due to `SkillRegistry.list_all()` or `Skill.trigger` attribute not yet wired up (depends on Plan 1 implementation details).

- [ ] **Step 4: Fix any wiring gaps**

If `SkillRegistry` does not have `list_all()`, add it:

```python
# in claudeclaw/skills/registry.py — add if missing
def list_all(self) -> list[Skill]:
    """Return all skills loaded from the skills directory."""
    return [self._loader.load(f) for f in sorted(self._skills_dir.glob("*.md"))]
```

If `Skill` does not expose `trigger_id` as an attribute, ensure the `SkillLoader` maps the `trigger-id` frontmatter key to `trigger_id` (underscore).

- [ ] **Step 5: Run the full integration test suite**

```bash
pytest tests/test_scheduling_integration.py -v
```

Expected: all integration tests PASSED.

- [ ] **Step 6: Run the complete test suite one final time**

```bash
pytest tests/ -v
```

Expected: all tests PASSED — no regressions from Plan 1.

- [ ] **Step 7: Commit**

```bash
git add tests/test_scheduling_integration.py tests/fixtures/cron-test-skill.md
git commit -m "test(scheduling): integration — full startup sequence and CronFired dispatch cycle"
```

---

## Plan 3 Complete

At this point the following is working:

- `ScheduleManager` registers cron skills via `CronCreate` at startup (idempotent, persists to `schedules.yaml`)
- `ScheduleManager` registers webhook skills via `RemoteTrigger` at startup (idempotent, persists to `triggers.yaml`)
- `handle_tool_use_event` normalizes `CronFired` and `RemoteTriggerFired` SDK events into `Event` objects with pre-resolved `skill_name`
- `deregister_skill` cleans up both registries on uninstall
- `claudeclaw schedule list` displays all registered schedules and webhook triggers
- `claudeclaw schedule run <skill>` manually fires a scheduled skill via the normal subagent dispatch path
- All behavior is covered by unit tests and one integration test

**Next plan:** Plan 4 — Channel Adapters (Telegram, Slack, Web UI)
