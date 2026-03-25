# ClaudeClaw — Plan 4: Agent Creator Native Skill

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the Agent Creator native skill — a multi-turn wizard that guides users through creating a fully configured autonomous agent via any active channel (Telegram, Slack, CLI, etc.). After this plan, a user can type "create an agent that..." and ClaudeClaw will walk them through the entire setup, generate a skill `.md` file, register a schedule if needed, and confirm the agent is ready.

**Architecture:** A `ConversationStore` persists wizard state across turns. The orchestrator checks for active conversations before routing. A `SkillGenerator` converts wizard output into a valid `.md` skill file. The router's prompt is updated to always include `agent-creator` and `pop` as meta-skills. The `agent-creator.md` native skill is a pure `.md` file containing the wizard instructions for Claude.

**Tech Stack:** Python 3.11+, `anthropic` SDK, `python-frontmatter`, `pydantic`, `keyring` + `cryptography`, `pytest`, `pytest-asyncio`, `pytest-mock`

**Spec reference:** `docs/superpowers/specs/2026-03-25-plan-4-agent-creator-spec.md`

---

## File Map

```
claudeclaw/                               ← package root
├── claudeclaw/
│   ├── skills/
│   │   ├── native/
│   │   │   └── agent-creator.md          ← new: wizard instructions (pure .md)
│   │   ├── generator.py                  ← new: WizardOutput → writes .md skill file
│   │   └── registry.py                   ← updated: gains reload() method
│   ├── core/
│   │   ├── conversation.py               ← new: ConversationStore
│   │   ├── orchestrator.py               ← updated: checks ConversationStore before routing
│   │   └── router.py                     ← updated: always-available meta-skills
│   └── subagent/
│       └── dispatch.py                   ← updated: accepts optional conversation history
└── tests/
    ├── test_conversation.py              ← new
    ├── test_skill_generator.py           ← new
    ├── test_router_meta_skills.py        ← new
    └── test_agent_creator_integration.py ← new
```

---

## Task 1: ConversationStore

**Files:**
- Create: `claudeclaw/core/conversation.py`
- Create: `tests/test_conversation.py`

The `ConversationStore` persists multi-turn wizard state in JSON files under `~/.claudeclaw/config/conversations/`, keyed by `(channel, user_id)`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_conversation.py
import pytest
import time
from pathlib import Path
from claudeclaw.core.conversation import ConversationStore, ConversationState


@pytest.fixture
def conv_store(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDECLAW_HOME", str(tmp_path))
    return ConversationStore()


def test_no_active_conversation_initially(conv_store):
    assert not conv_store.has_active("telegram", "user123")


def test_save_and_get_conversation(conv_store):
    state = ConversationState(
        channel="telegram",
        user_id="user123",
        skill_name="agent-creator",
        step=2,
        data={"task_description": "issue invoices"},
        history=[
            {"role": "assistant", "content": "What do you need?"},
            {"role": "user", "content": "issue invoices"},
        ],
    )
    conv_store.save(state)
    loaded = conv_store.get("telegram", "user123")
    assert loaded is not None
    assert loaded.step == 2
    assert loaded.data["task_description"] == "issue invoices"
    assert len(loaded.history) == 2


def test_has_active_after_save(conv_store):
    state = ConversationState(
        channel="cli", user_id="local", skill_name="agent-creator",
        step=1, data={}, history=[],
    )
    conv_store.save(state)
    assert conv_store.has_active("cli", "local")


def test_clear_removes_conversation(conv_store):
    state = ConversationState(
        channel="cli", user_id="local", skill_name="agent-creator",
        step=1, data={}, history=[],
    )
    conv_store.save(state)
    conv_store.clear("cli", "local")
    assert not conv_store.has_active("cli", "local")
    assert conv_store.get("cli", "local") is None


def test_get_missing_returns_none(conv_store):
    assert conv_store.get("telegram", "nobody") is None


def test_list_active_returns_all_saved(conv_store):
    for i in range(3):
        state = ConversationState(
            channel="telegram", user_id=f"user{i}", skill_name="agent-creator",
            step=1, data={}, history=[],
        )
        conv_store.save(state)
    active = conv_store.list_active()
    assert len(active) == 3


def test_clear_expired_removes_idle_conversations(conv_store, monkeypatch):
    import datetime
    old_time = (datetime.datetime.utcnow() - datetime.timedelta(minutes=60)).isoformat() + "Z"
    state = ConversationState(
        channel="telegram", user_id="idle_user", skill_name="agent-creator",
        step=1, data={}, history=[],
    )
    conv_store.save(state)
    # Manually patch updated_at to be old
    loaded = conv_store.get("telegram", "idle_user")
    loaded.updated_at = old_time
    conv_store.save(loaded)

    removed = conv_store.clear_expired(max_idle_minutes=30)
    assert removed >= 1
    assert not conv_store.has_active("telegram", "idle_user")
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_conversation.py -v
```

Expected: `ImportError` — module does not exist yet.

- [ ] **Step 3: Implement ConversationStore**

```python
# claudeclaw/core/conversation.py
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
    # Replace path-unsafe chars; double underscore separates channel from user_id
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
        settings = get_settings()
        self._dir = base_dir or (settings.config_dir / _CONVERSATIONS_SUBDIR)
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

    def save(self, state: ConversationState) -> None:
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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_conversation.py -v
```

Expected: 8 PASSED.

- [ ] **Step 5: Commit**

```bash
git add claudeclaw/core/conversation.py tests/test_conversation.py
git commit -m "feat: ConversationStore — persist multi-turn wizard state as JSON"
```

---

## Task 2: Update Orchestrator to Pass Conversation History to Dispatcher

**Files:**
- Update: `claudeclaw/subagent/dispatch.py`
- Update: `claudeclaw/core/orchestrator.py`

The orchestrator checks `ConversationStore` before every routing decision. If an active conversation exists, it bypasses the router and re-dispatches the same skill with full conversation history. The dispatcher accepts an optional `conversation` argument and prepends history to the messages list.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_orchestrator_conversation.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from claudeclaw.core.orchestrator import Orchestrator
from claudeclaw.core.event import Event, Response
from claudeclaw.core.conversation import ConversationStore, ConversationState
from claudeclaw.skills.loader import SkillManifest
from claudeclaw.subagent.dispatch import DispatchResult


@pytest.fixture
def agent_creator_skill():
    return SkillManifest(
        name="agent-creator",
        description="Creates a new agent via a wizard",
        trigger="on-demand",
        autonomy="ask",
        shell_policy="none",
        body="# Agent Creator\nYou are running the agent creation wizard.",
    )


@pytest.mark.asyncio
async def test_orchestrator_resumes_active_conversation(agent_creator_skill, tmp_path, monkeypatch):
    """When an active conversation exists, orchestrator bypasses router and uses conversation skill."""
    monkeypatch.setenv("CLAUDECLAW_HOME", str(tmp_path))

    conv_store = ConversationStore()
    state = ConversationState(
        channel="cli", user_id="local", skill_name="agent-creator",
        step=2, data={"task_description": "issue invoices"},
        history=[{"role": "assistant", "content": "What do you need?"}],
    )
    conv_store.save(state)

    mock_channel = MagicMock()

    async def fake_receive():
        yield Event(text="ERP and Gmail", channel="cli", user_id="local")

    mock_channel.receive = fake_receive
    mock_channel.send = AsyncMock()

    mock_registry = MagicMock()
    mock_registry.find.return_value = agent_creator_skill
    mock_registry.list_skills.return_value = [agent_creator_skill]

    mock_router = MagicMock()
    mock_dispatcher = MagicMock()
    mock_dispatcher.dispatch.return_value = DispatchResult(
        text="Which systems?", skill_name="agent-creator", stop_reason="end_turn"
    )

    orchestrator = Orchestrator(
        channel=mock_channel,
        registry=mock_registry,
        router=mock_router,
        dispatcher=mock_dispatcher,
        conv_store=conv_store,
    )

    await orchestrator.run_once()

    # Router should NOT have been called — conversation was active
    mock_router.route.assert_not_called()
    # Dispatcher should have been called with the conversation
    mock_dispatcher.dispatch.assert_called_once()
    call_kwargs = mock_dispatcher.dispatch.call_args
    assert call_kwargs.kwargs.get("conversation") is not None or \
           (len(call_kwargs.args) >= 3 and call_kwargs.args[2] is not None)


@pytest.mark.asyncio
async def test_orchestrator_uses_router_when_no_active_conversation(agent_creator_skill, tmp_path, monkeypatch):
    """When no active conversation exists, orchestrator uses router as normal."""
    monkeypatch.setenv("CLAUDECLAW_HOME", str(tmp_path))

    conv_store = ConversationStore()

    mock_channel = MagicMock()

    async def fake_receive():
        yield Event(text="create an agent for invoices", channel="cli", user_id="local")

    mock_channel.receive = fake_receive
    mock_channel.send = AsyncMock()

    mock_registry = MagicMock()
    mock_registry.list_skills.return_value = [agent_creator_skill]

    mock_router = MagicMock()
    mock_router.route.return_value = agent_creator_skill

    mock_dispatcher = MagicMock()
    mock_dispatcher.dispatch.return_value = DispatchResult(
        text="What do you need?", skill_name="agent-creator", stop_reason="end_turn"
    )

    orchestrator = Orchestrator(
        channel=mock_channel,
        registry=mock_registry,
        router=mock_router,
        dispatcher=mock_dispatcher,
        conv_store=conv_store,
    )

    await orchestrator.run_once()

    mock_router.route.assert_called_once()


def test_dispatcher_prepends_conversation_history():
    """Dispatcher passes conversation history as prior messages to Claude."""
    from claudeclaw.subagent.dispatch import SubagentDispatcher
    from claudeclaw.core.conversation import ConversationState
    from claudeclaw.skills.loader import SkillManifest
    from claudeclaw.core.event import Event
    from unittest.mock import MagicMock, patch

    skill = SkillManifest(
        name="agent-creator",
        description="wizard",
        trigger="on-demand",
        autonomy="ask",
        shell_policy="none",
        body="# Agent Creator\nRun the wizard.",
    )
    event = Event(text="ERP and Gmail", channel="cli", user_id="local")
    history = [
        {"role": "assistant", "content": "What do you need?"},
        {"role": "user", "content": "issue invoices"},
    ]
    state = ConversationState(
        channel="cli", user_id="local", skill_name="agent-creator",
        step=2, data={}, history=history,
    )

    dispatcher = SubagentDispatcher()
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="Which systems?")]
    mock_response.stop_reason = "end_turn"

    with patch.object(dispatcher._client.messages, "create", return_value=mock_response) as mock_create:
        dispatcher.dispatch(skill, event, conversation=state)

    messages_arg = mock_create.call_args.kwargs["messages"]
    # History should appear before the current user message
    assert messages_arg[0]["role"] == "assistant"
    assert messages_arg[1]["role"] == "user"
    assert messages_arg[1]["content"] == "issue invoices"
    assert messages_arg[-1]["content"] == "ERP and Gmail"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_orchestrator_conversation.py -v
```

Expected: failures due to missing `conv_store` parameter on `Orchestrator` and missing `conversation` parameter on `SubagentDispatcher.dispatch`.

- [ ] **Step 3: Update SubagentDispatcher to accept conversation history**

```python
# claudeclaw/subagent/dispatch.py  — add conversation parameter to dispatch()
# Add import at top:
from typing import Optional
from claudeclaw.core.conversation import ConversationState  # new import

# Update dispatch() signature and messages building:
def dispatch(
    self,
    skill: SkillManifest,
    event: Event,
    conversation: Optional[ConversationState] = None,
) -> DispatchResult:
    system_prompt = self._build_system_prompt(skill)
    tools = self._resolve_tools(skill)

    # Build messages: prepend history if resuming a conversation
    messages = []
    if conversation and conversation.history:
        messages.extend(conversation.history)
    messages.append({"role": "user", "content": event.text})

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
```

- [ ] **Step 4: Update Orchestrator to check ConversationStore before routing**

```python
# claudeclaw/core/orchestrator.py  — add conv_store support
# Add imports:
from claudeclaw.core.conversation import ConversationStore

# Update __init__:
def __init__(
    self,
    channel: ChannelAdapter,
    registry: Optional[SkillRegistry] = None,
    router: Optional[Router] = None,
    dispatcher: Optional[SubagentDispatcher] = None,
    conv_store: Optional[ConversationStore] = None,
):
    self._channel = channel
    self._registry = registry or SkillRegistry()
    self._dispatcher = dispatcher or SubagentDispatcher()
    self._router = router
    self._conv_store = conv_store or ConversationStore()

# Update _handle():
async def _handle(self, event: Event, router: Router):
    conversation = None
    skill = None

    if self._conv_store.has_active(event.channel, event.user_id or ""):
        conversation = self._conv_store.get(event.channel, event.user_id or "")
        skill = self._registry.find(conversation.skill_name)
        logger.info(
            "Resuming conversation for skill '%s' (step %d)",
            conversation.skill_name, conversation.step,
        )

    if skill is None:
        skill = router.route(event)

    if skill is None:
        logger.info("No skill matched for: %r", event.text)
        await self._channel.send(Response(text=FALLBACK_MESSAGE, event=event))
        return

    logger.info("Dispatching skill '%s' for event: %r", skill.name, event.text)
    try:
        result = self._dispatcher.dispatch(skill, event, conversation=conversation)
        await self._channel.send(Response(text=result.text, event=event))
    except Exception as e:
        logger.error("Dispatch failed: %s", e)
        await self._channel.send(
            Response(
                text=f"Something went wrong running '{skill.name}'. Check logs.",
                event=event,
            )
        )
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
pytest tests/test_orchestrator_conversation.py -v
```

Expected: 3 PASSED.

- [ ] **Step 6: Run the existing test suite to verify no regressions**

```bash
pytest tests/ -v
```

Expected: All previously passing tests still pass.

- [ ] **Step 7: Commit**

```bash
git add claudeclaw/subagent/dispatch.py claudeclaw/core/orchestrator.py tests/test_orchestrator_conversation.py
git commit -m "feat: orchestrator resumes active conversations; dispatcher accepts history"
```

---

## Task 3: `agent-creator.md` Native Skill File

**Files:**
- Create: `claudeclaw/skills/native/agent-creator.md`
- Create: `claudeclaw/skills/native/__init__.py` (empty)

This is a pure `.md` file — the wizard instructions for Claude. No Python. Claude will read this as its system prompt when the agent-creator subagent is dispatched.

- [ ] **Step 1: Create the native skills directory and `__init__.py`**

```bash
mkdir -p claudeclaw/skills/native
touch claudeclaw/skills/native/__init__.py
```

- [ ] **Step 2: Write `agent-creator.md`**

```markdown
---
name: agent-creator
description: Creates a new autonomous agent via a guided multi-turn wizard. Always available regardless of installed skills.
trigger: on-demand
autonomy: ask
tools: []
credentials: []
shell-policy: none
---

# Agent Creator

You are the Agent Creator for ClaudeClaw. Your job is to guide the user through creating a new autonomous agent step by step, using a friendly conversational wizard.

## How You Work

You are a multi-turn wizard. Each invocation you receive: (1) the conversation history so far, and (2) the user's latest message. You continue from where you left off.

You have access to a special tool: `wizard_advance(step, data)` — call this after each completed step to save the wizard state. When the wizard is complete, call `wizard_complete(wizard_output)` with all collected data.

If the user says "cancel", "nevermind", "stop", or "abort" at any point, call `wizard_cancel()` and say goodbye warmly.

## Wizard Steps

### Step 1 — Task Description
Ask: "What do you need the agent to do? Describe the task in your own words — no need to be technical."

Wait for the user's answer. Save it as `task_description`.

### Step 2 — Systems
Ask: "Which systems does it need to access? For example: your ERP, CRM, Gmail, a website, Slack, a database... List as many as apply, or say 'none' if it only needs to think and respond."

Parse the answer into a list of system names. Save as `systems`.

### Step 3 — Credentials (repeat for each system)
For each system the user listed:
  - Ask: "What's the URL or API endpoint for [system name]?" → save as `<system>_url`
  - Ask: "Username for [system name]? (press Enter to skip if not needed)" → if provided, save securely with key `<agent-slug>-<system>-user`
  - Ask: "Password or API token for [system name]? This will be stored securely in your system keychain, never in any file." → save securely with key `<agent-slug>-<system>-token`

After each credential is provided, confirm: "Got it — stored securely."

Security note: remind the user on the password step that if they are in Telegram or another messaging channel, they should delete their message after sending to keep the credential private.

### Step 4 — Schedule
Ask: "How often should it run?"

Present clear options:
- "On demand only (I'll trigger it manually)"
- "Daily — at what time? (e.g., 9am, 11:30pm)"
- "Weekly — which day and time?"
- "Monthly — which day of the month and time?"
- "Trigger via webhook (I'll connect it to another system)"

Convert the user's choice into a cron expression or set trigger to "webhook". Save as `trigger` and `schedule`.

### Step 5 — Autonomy
Ask: "When it runs, should it:
- Ask before doing anything (safest — good for actions that can't be undone)
- Act and then notify you of what it did
- Run silently and only contact you if something goes wrong"

Map to: `ask` / `notify` / `autonomous`.

### Step 6 — Confirmation Before Generating
Summarize everything back to the user:
"Here's what I'm going to create:
- **Task:** [task_description]
- **Systems:** [systems]
- **Schedule:** [human-readable schedule]
- **Autonomy:** [autonomy level description]

Shall I create this agent? (yes / make changes)"

If the user wants changes, go back to the relevant step.

### Step 7 — Generate
Once confirmed, call `wizard_complete(wizard_output)` with all collected fields. The system will generate the skill file and register the schedule.

Then tell the user:
"Your agent '[agent name]' is ready.
[If scheduled: First run: [date/time].]
[If on-demand: Run it any time with: claudeclaw agents run [slug]]
You can also trigger it by messaging me: 'run [agent name]'"

## Tone Guidelines
- Be friendly, clear, and concise.
- Avoid technical jargon. The user may not be a developer.
- Validate inputs gently — if something doesn't make sense, ask for clarification rather than assuming.
- Keep each message short — one question at a time.
- Respond in the same language the user is writing in.
```

- [ ] **Step 3: Verify the skill file is valid frontmatter**

```bash
python -c "
import frontmatter
skill = frontmatter.load('claudeclaw/skills/native/agent-creator.md')
assert skill['name'] == 'agent-creator'
assert skill['trigger'] == 'on-demand'
print('agent-creator.md frontmatter OK')
"
```

Expected: `agent-creator.md frontmatter OK`

- [ ] **Step 4: Update SkillRegistry to load native skills**

Add a method to `SkillRegistry` that also discovers skills from the bundled `claudeclaw/skills/native/` directory. Native skills are always included in `list_skills()` and searchable via `find()`.

```python
# claudeclaw/skills/registry.py — add native skills support
import importlib.resources
from pathlib import Path

_NATIVE_SKILLS_PACKAGE = "claudeclaw.skills.native"


class SkillRegistry:
    def __init__(self, skills_dir: Optional[Path] = None):
        self._dir = skills_dir or get_settings().skills_dir
        self._native_dir: Optional[Path] = self._resolve_native_dir()

    @staticmethod
    def _resolve_native_dir() -> Optional[Path]:
        try:
            ref = importlib.resources.files(_NATIVE_SKILLS_PACKAGE)
            p = Path(str(ref))
            return p if p.is_dir() else None
        except Exception:
            return None

    def list_skills(self) -> list[SkillManifest]:
        skills = []
        # Load native skills first
        if self._native_dir:
            for md_file in sorted(self._native_dir.glob("*.md")):
                try:
                    skills.append(load_skill(md_file))
                except SkillLoadError as e:
                    logger.warning("Skipping invalid native skill %s: %s", md_file.name, e)
        # Load user skills
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

    def reload(self) -> list[SkillManifest]:
        """Force re-scan of skills directories. Call after writing a new skill file."""
        return self.list_skills()
```

- [ ] **Step 5: Write registry test for native skills**

```python
# tests/test_registry_native.py
from claudeclaw.skills.registry import SkillRegistry


def test_native_agent_creator_always_available(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDECLAW_HOME", str(tmp_path))
    (tmp_path / "skills").mkdir(parents=True, exist_ok=True)
    registry = SkillRegistry(skills_dir=tmp_path / "skills")
    skill = registry.find("agent-creator")
    assert skill is not None
    assert skill.name == "agent-creator"


def test_reload_picks_up_new_skills(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDECLAW_HOME", str(tmp_path))
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir(parents=True)
    registry = SkillRegistry(skills_dir=skills_dir)

    # No user skills yet
    user_skills = [s for s in registry.list_skills() if s.name != "agent-creator" and s.name != "pop"]
    assert len(user_skills) == 0

    # Write a new skill
    (skills_dir / "new-skill.md").write_text("""---
name: new-skill
description: A brand new skill
trigger: on-demand
autonomy: ask
tools: []
shell-policy: none
---
Do the new thing.
""")
    # After reload, new skill is present
    reloaded = registry.reload()
    names = [s.name for s in reloaded]
    assert "new-skill" in names
```

- [ ] **Step 6: Run tests**

```bash
pytest tests/test_registry_native.py -v
```

Expected: 2 PASSED.

- [ ] **Step 7: Commit**

```bash
git add claudeclaw/skills/native/ claudeclaw/skills/registry.py tests/test_registry_native.py
git commit -m "feat: agent-creator.md native skill + registry loads native skills + reload()"
```

---

## Task 4: Skill Generator

**Files:**
- Create: `claudeclaw/skills/generator.py`
- Create: `tests/test_skill_generator.py`

The `SkillGenerator` converts wizard output into a valid `.md` skill file written to `~/.claudeclaw/skills/`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_skill_generator.py
import pytest
from pathlib import Path
from claudeclaw.skills.generator import SkillGenerator, WizardOutput
from claudeclaw.skills.loader import load_skill


@pytest.fixture
def generator(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDECLAW_HOME", str(tmp_path))
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir(parents=True)
    return SkillGenerator(skills_dir=skills_dir)


@pytest.fixture
def basic_wizard_output():
    return WizardOutput(
        task_description="Issue monthly invoices from the ERP and email them to clients",
        systems=["erp", "gmail"],
        credentials=["erp-invoices-erp-user", "erp-invoices-erp-token", "erp-invoices-gmail-token"],
        trigger="cron",
        schedule="0 0 28 * *",
        autonomy="autonomous",
    )


def test_generates_valid_md_file(generator, basic_wizard_output):
    path = generator.generate(basic_wizard_output)
    assert path.exists()
    assert path.suffix == ".md"


def test_generated_skill_has_valid_frontmatter(generator, basic_wizard_output):
    path = generator.generate(basic_wizard_output)
    skill = load_skill(path)
    assert skill.trigger == "cron"
    assert skill.schedule == "0 0 28 * *"
    assert skill.autonomy == "autonomous"
    assert "erp-invoices-erp-user" in skill.credentials


def test_generated_skill_name_is_kebab_case(generator, basic_wizard_output):
    path = generator.generate(basic_wizard_output)
    skill = load_skill(path)
    assert " " not in skill.name
    assert skill.name == skill.name.lower()


def test_deduplicates_slug_if_file_exists(generator, basic_wizard_output, tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDECLAW_HOME", str(tmp_path))
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir(parents=True, exist_ok=True)
    gen = SkillGenerator(skills_dir=skills_dir)

    path1 = gen.generate(basic_wizard_output)
    path2 = gen.generate(basic_wizard_output)
    assert path1 != path2
    assert path1.exists()
    assert path2.exists()


def test_on_demand_skill_has_no_schedule(generator):
    output = WizardOutput(
        task_description="Answer customer questions",
        systems=[],
        credentials=[],
        trigger="on-demand",
        schedule=None,
        autonomy="ask",
    )
    path = generator.generate(output)
    skill = load_skill(path)
    assert skill.trigger == "on-demand"
    assert skill.schedule is None


def test_webhook_skill_has_trigger_id(generator):
    output = WizardOutput(
        task_description="Process new CRM lead",
        systems=["crm"],
        credentials=["crm-lead-crm-token"],
        trigger="webhook",
        schedule=None,
        autonomy="notify",
    )
    path = generator.generate(output)
    skill = load_skill(path)
    assert skill.trigger == "webhook"
    assert skill.trigger_id is not None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_skill_generator.py -v
```

Expected: `ImportError` — module does not exist yet.

- [ ] **Step 3: Implement SkillGenerator**

```python
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
        frontmatter: dict = {
            "name": path.stem,
            "description": _build_description(output.task_description),
            "trigger": output.trigger,
            "autonomy": output.autonomy,
            "tools": [],
            "credentials": output.credentials,
            "shell-policy": "none",
        }

        if output.trigger == "cron" and output.schedule:
            frontmatter["schedule"] = output.schedule

        if output.trigger == "webhook":
            trigger_id = output.trigger_id or f"{path.stem}-webhook"
            frontmatter["trigger-id"] = trigger_id

        body = _build_body(output)
        content = f"---\n{yaml.dump(frontmatter, default_flow_style=False)}---\n\n{body}\n"
        path.write_text(content)
        logger.info("Generated skill file: %s", path)
        return path
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_skill_generator.py -v
```

Expected: 6 PASSED.

- [ ] **Step 5: Commit**

```bash
git add claudeclaw/skills/generator.py tests/test_skill_generator.py
git commit -m "feat: SkillGenerator — converts wizard output to .md skill file"
```

---

## Task 5: Router Update — Always-Available Meta-Skills

**Files:**
- Update: `claudeclaw/core/router.py`
- Create: `tests/test_router_meta_skills.py`

The router prompt must always include `agent-creator` and `pop` as options, regardless of what user skills are installed.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_router_meta_skills.py
import pytest
from unittest.mock import patch
from claudeclaw.core.router import Router
from claudeclaw.core.event import Event
from claudeclaw.skills.loader import SkillManifest


@pytest.fixture
def no_skills_router():
    return Router([])


@pytest.fixture
def some_skills_router():
    return Router([
        SkillManifest(
            name="crm-followup",
            description="Send follow-up messages to hot CRM leads",
            trigger="on-demand",
            autonomy="notify",
            shell_policy="none",
            body="...",
        )
    ])


def test_router_returns_agent_creator_meta_skill(no_skills_router):
    event = Event(text="I want to create a new agent", channel="cli")
    with patch.object(no_skills_router, "_match_with_claude", return_value="agent-creator"):
        result = no_skills_router.route(event)
    assert result is not None
    assert result == "agent-creator"


def test_router_returns_pop_meta_skill(no_skills_router):
    event = Event(text="teach the system how to do this", channel="cli")
    with patch.object(no_skills_router, "_match_with_claude", return_value="pop"):
        result = no_skills_router.route(event)
    assert result == "pop"


def test_router_includes_meta_skills_in_prompt_even_with_empty_skills():
    router = Router([])
    prompt = router._build_routing_prompt("create an agent for me")
    assert "agent-creator" in prompt
    assert "pop" in prompt


def test_router_includes_meta_skills_alongside_installed_skills(some_skills_router):
    prompt = some_skills_router._build_routing_prompt("create an agent for me")
    assert "agent-creator" in prompt
    assert "crm-followup" in prompt


def test_router_returns_installed_skill_when_matched(some_skills_router):
    event = Event(text="follow up with my leads", channel="cli")
    with patch.object(some_skills_router, "_match_with_claude", return_value="crm-followup"):
        result = some_skills_router.route(event)
    assert result is not None
    assert hasattr(result, "name")
    assert result.name == "crm-followup"


def test_router_returns_none_on_no_match(some_skills_router):
    event = Event(text="what is the weather", channel="cli")
    with patch.object(some_skills_router, "_match_with_claude", return_value=None):
        result = some_skills_router.route(event)
    assert result is None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_router_meta_skills.py -v
```

Expected: failures — `_build_routing_prompt` does not exist yet, and router does not return string values for meta-skills.

- [ ] **Step 3: Update Router**

```python
# claudeclaw/core/router.py  — full updated implementation
import logging
from typing import Optional, Union
import anthropic

from claudeclaw.core.event import Event
from claudeclaw.skills.loader import SkillManifest

logger = logging.getLogger(__name__)

META_SKILLS = {
    "agent-creator": (
        "Creates a new autonomous agent via a guided wizard. Match when the user wants "
        "to create, build, set up, automate, or train a new agent or capability."
    ),
    "pop": (
        "Maps a single operation step-by-step and creates a skill. Match when the user "
        "wants to teach the system how to do one specific operation."
    ),
}


class Router:
    """
    Maps an incoming event to the best matching skill or meta-skill.
    Meta-skills (agent-creator, pop) are always available candidates.
    Returns a SkillManifest for installed skills, or a string name for meta-skills.
    Returns None if nothing matches.
    """

    def __init__(self, skills: list[SkillManifest], client: Optional[anthropic.Anthropic] = None):
        self._skills = skills
        self._client = client or anthropic.Anthropic()

    def route(self, event: Event) -> Optional[Union[SkillManifest, str]]:
        prompt = self._build_routing_prompt(event.text)
        matched_name = self._match_with_claude(event.text, prompt=prompt)
        if matched_name is None:
            return None
        # Check meta-skills first
        if matched_name in META_SKILLS:
            return matched_name
        # Then installed skills
        return next((s for s in self._skills if s.name == matched_name), None)

    def _build_routing_prompt(self, text: str) -> str:
        meta_lines = "\n".join(
            f"- {name}: {desc}" for name, desc in META_SKILLS.items()
        )
        installed_lines = "\n".join(
            f"- {s.name}: {s.description}" for s in self._skills
        ) if self._skills else "(none installed)"

        return (
            f'Given this user message: "{text}"\n\n'
            "Always-available skills (ALWAYS consider these regardless of installed skills):\n"
            f"{meta_lines}\n\n"
            "Installed skills:\n"
            f"{installed_lines}\n\n"
            "Which skill name best matches the user's intent?\n"
            "Reply with ONLY the skill name, or \"none\" if nothing matches."
        )

    def _match_with_claude(self, text: str, prompt: Optional[str] = None) -> Optional[str]:
        if prompt is None:
            prompt = self._build_routing_prompt(text)
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
pytest tests/test_router_meta_skills.py -v
```

Expected: 6 PASSED.

- [ ] **Step 5: Run the full router test suite to verify no regressions**

```bash
pytest tests/test_router.py tests/test_router_meta_skills.py -v
```

Expected: All pass.

- [ ] **Step 6: Commit**

```bash
git add claudeclaw/core/router.py tests/test_router_meta_skills.py
git commit -m "feat: router always includes agent-creator and pop as meta-skills"
```

---

## Task 6: Integration — Full Wizard Flow Test

**Files:**
- Create: `tests/test_agent_creator_integration.py`

Simulate a complete multi-turn Agent Creator wizard: mock Claude SDK responses for each wizard turn, verify skill file is generated with correct frontmatter, and verify ConversationStore is cleared on completion.

- [ ] **Step 1: Write the integration test**

```python
# tests/test_agent_creator_integration.py
"""
Integration test: simulates a full multi-turn Agent Creator wizard.
Uses mock Claude SDK responses — no real API calls.
"""
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch, AsyncMock
from claudeclaw.core.conversation import ConversationStore, ConversationState
from claudeclaw.skills.generator import SkillGenerator, WizardOutput
from claudeclaw.skills.registry import SkillRegistry
from claudeclaw.skills.loader import load_skill


@pytest.fixture
def skills_env(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDECLAW_HOME", str(tmp_path))
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir(parents=True)
    conv_dir = tmp_path / "config" / "conversations"
    conv_dir.mkdir(parents=True)
    return {
        "home": tmp_path,
        "skills_dir": skills_dir,
        "conv_dir": conv_dir,
    }


def test_wizard_output_produces_valid_loadable_skill(skills_env):
    """A WizardOutput fed to SkillGenerator produces a skill that passes load_skill()."""
    generator = SkillGenerator(skills_dir=skills_env["skills_dir"])
    output = WizardOutput(
        task_description="Issue monthly invoices from ERP and email clients",
        systems=["erp", "gmail"],
        credentials=["inv-erp-user", "inv-erp-token", "inv-gmail-token"],
        trigger="cron",
        schedule="0 0 28 * *",
        autonomy="autonomous",
    )
    path = generator.generate(output)
    skill = load_skill(path)
    assert skill.name is not None
    assert skill.trigger == "cron"
    assert skill.schedule == "0 0 28 * *"
    assert skill.autonomy == "autonomous"
    assert set(skill.credentials) == {"inv-erp-user", "inv-erp-token", "inv-gmail-token"}


def test_generated_skill_is_immediately_findable_via_registry(skills_env):
    """After generating a skill, SkillRegistry.find() returns it without restart."""
    generator = SkillGenerator(skills_dir=skills_env["skills_dir"])
    registry = SkillRegistry(skills_dir=skills_env["skills_dir"])

    output = WizardOutput(
        task_description="Send weekly CRM follow-up emails",
        systems=["crm"],
        credentials=["crm-followup-crm-token"],
        trigger="cron",
        schedule="0 9 * * 1",
        autonomy="notify",
    )
    path = generator.generate(output)

    # Reload and find
    registry.reload()
    skill = registry.find(path.stem)
    assert skill is not None
    assert skill.name == path.stem


def test_conversation_state_lifecycle(skills_env):
    """ConversationStore correctly saves, retrieves, and clears wizard state."""
    store = ConversationStore(base_dir=skills_env["conv_dir"])

    # Initially no active conversation
    assert not store.has_active("telegram", "user99")

    # Save step 1
    state = ConversationState(
        channel="telegram",
        user_id="user99",
        skill_name="agent-creator",
        step=1,
        data={},
        history=[{"role": "assistant", "content": "What do you need?"}],
    )
    store.save(state)
    assert store.has_active("telegram", "user99")

    # Advance to step 2
    loaded = store.get("telegram", "user99")
    loaded.step = 2
    loaded.data["task_description"] = "Issue invoices"
    loaded.history.append({"role": "user", "content": "Issue invoices"})
    store.save(loaded)

    reloaded = store.get("telegram", "user99")
    assert reloaded.step == 2
    assert reloaded.data["task_description"] == "Issue invoices"
    assert len(reloaded.history) == 2

    # Clear on completion
    store.clear("telegram", "user99")
    assert not store.has_active("telegram", "user99")


def test_full_wizard_to_skill_pipeline(skills_env):
    """
    Simulate the complete wizard pipeline end-to-end:
    ConversationState accumulates data across turns → SkillGenerator produces skill.
    """
    store = ConversationStore(base_dir=skills_env["conv_dir"])
    generator = SkillGenerator(skills_dir=skills_env["skills_dir"])
    registry = SkillRegistry(skills_dir=skills_env["skills_dir"])

    # Turn 1: wizard starts
    state = ConversationState(
        channel="cli", user_id="local", skill_name="agent-creator",
        step=1, data={}, history=[],
    )
    store.save(state)

    # Turn 2: user provides task description
    state = store.get("cli", "local")
    state.step = 2
    state.data["task_description"] = "Process new leads from CRM and send welcome email"
    state.history += [
        {"role": "assistant", "content": "What do you need the agent to do?"},
        {"role": "user", "content": "Process new leads from CRM and send welcome email"},
    ]
    store.save(state)

    # Turn 3: systems identified
    state = store.get("cli", "local")
    state.step = 3
    state.data["systems"] = ["crm", "gmail"]
    store.save(state)

    # Turn 4: credentials collected (simulated — real wizard stores to Keyring)
    state = store.get("cli", "local")
    state.step = 4
    state.data["credentials"] = ["crm-welcome-crm-token", "crm-welcome-gmail-token"]
    store.save(state)

    # Turn 5: schedule set
    state = store.get("cli", "local")
    state.step = 5
    state.data["trigger"] = "on-demand"
    state.data["schedule"] = None
    store.save(state)

    # Turn 6: autonomy set
    state = store.get("cli", "local")
    state.step = 6
    state.data["autonomy"] = "notify"
    store.save(state)

    # Wizard complete: generate skill
    final_state = store.get("cli", "local")
    output = WizardOutput(
        task_description=final_state.data["task_description"],
        systems=final_state.data["systems"],
        credentials=final_state.data["credentials"],
        trigger=final_state.data["trigger"],
        schedule=final_state.data["schedule"],
        autonomy=final_state.data["autonomy"],
    )
    path = generator.generate(output)
    assert path.exists()

    skill = load_skill(path)
    assert "crm-welcome-crm-token" in skill.credentials
    assert skill.trigger == "on-demand"
    assert skill.autonomy == "notify"

    # Clear conversation
    store.clear("cli", "local")
    assert not store.has_active("cli", "local")

    # Skill is findable in registry
    found = registry.find(skill.name)
    assert found is not None
```

- [ ] **Step 2: Run integration tests**

```bash
pytest tests/test_agent_creator_integration.py -v
```

Expected: 4 PASSED.

- [ ] **Step 3: Commit**

```bash
git add tests/test_agent_creator_integration.py
git commit -m "test: agent creator integration — wizard pipeline, conversation lifecycle, skill generation"
```

---

## Task 7: Integration Verification

- [ ] **Step 1: Run the full test suite**

```bash
pytest tests/ -v
```

Expected: All tests pass (previous suite + 20+ new tests). Zero failures.

- [ ] **Step 2: Verify agent-creator native skill is found by registry**

```bash
python -c "
from claudeclaw.skills.registry import SkillRegistry
r = SkillRegistry()
skill = r.find('agent-creator')
assert skill is not None, 'agent-creator not found!'
print(f'agent-creator found: trigger={skill.trigger}, autonomy={skill.autonomy}')
"
```

Expected: `agent-creator found: trigger=on-demand, autonomy=ask`

- [ ] **Step 3: Verify router always includes meta-skills in prompt**

```bash
python -c "
from claudeclaw.core.router import Router
r = Router([])
prompt = r._build_routing_prompt('create an agent')
assert 'agent-creator' in prompt
assert 'pop' in prompt
print('Router prompt includes meta-skills: OK')
"
```

Expected: `Router prompt includes meta-skills: OK`

- [ ] **Step 4: Smoke test skill generation end-to-end**

```bash
python -c "
import tempfile, os
from pathlib import Path
with tempfile.TemporaryDirectory() as tmp:
    os.environ['CLAUDECLAW_HOME'] = tmp
    (Path(tmp) / 'skills').mkdir(parents=True)
    from claudeclaw.skills.generator import SkillGenerator, WizardOutput
    from claudeclaw.skills.loader import load_skill
    gen = SkillGenerator()
    out = WizardOutput(
        task_description='Send weekly status report via email',
        systems=['gmail'],
        credentials=['status-report-gmail-token'],
        trigger='cron',
        schedule='0 9 * * 1',
        autonomy='autonomous',
    )
    path = gen.generate(out)
    skill = load_skill(path)
    print(f'Generated: {path.name}  trigger={skill.trigger}  schedule={skill.schedule}')
"
```

Expected: `Generated: send-weekly-status-report-via-e.md  trigger=cron  schedule=0 9 * * 1`

- [ ] **Step 5: Verify ConversationStore saves and clears cleanly**

```bash
python -c "
import tempfile, os
from pathlib import Path
with tempfile.TemporaryDirectory() as tmp:
    os.environ['CLAUDECLAW_HOME'] = tmp
    (Path(tmp) / 'config' / 'conversations').mkdir(parents=True)
    from claudeclaw.core.conversation import ConversationStore, ConversationState
    store = ConversationStore()
    state = ConversationState(
        channel='telegram', user_id='test123', skill_name='agent-creator',
        step=2, data={'task_description': 'test'}, history=[],
    )
    store.save(state)
    assert store.has_active('telegram', 'test123')
    store.clear('telegram', 'test123')
    assert not store.has_active('telegram', 'test123')
    print('ConversationStore: save/clear cycle OK')
"
```

Expected: `ConversationStore: save/clear cycle OK`

- [ ] **Step 6: Final commit**

```bash
git add .
git commit -m "feat: plan 4 complete — agent creator native skill, wizard pipeline end-to-end"
```

---

## Summary

After this plan, ClaudeClaw can:

1. Recognize agent-creation intent ("create an agent...", "quero criar um agente...") and route to the Agent Creator meta-skill
2. Conduct a multi-turn wizard conversation through any active channel, persisting state between turns via `ConversationStore`
3. Collect credentials securely during the wizard and store them in Keyring
4. Generate a valid `.md` skill file from wizard output and write it to `~/.claudeclaw/skills/`
5. Make the new skill immediately available via `SkillRegistry.reload()` — no restart required
6. Route to `agent-creator` or `pop` as always-available meta-skills regardless of what user skills are installed

**Next plan:** Plan 5 — Plugins + MCPs: full tool injection, plugin installation, per-agent MCP configuration
