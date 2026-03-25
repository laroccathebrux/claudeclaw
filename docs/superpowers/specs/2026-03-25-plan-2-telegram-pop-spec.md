# ClaudeClaw — Plan 2 Sub-Spec: Telegram Channel Adapter + POP Native Skill

**Date:** 2026-03-25
**Status:** Draft
**Author:** Alessandro Silveira
**Plan reference:** `docs/superpowers/plans/2026-03-25-plan-2-telegram-pop.md`
**Spec reference:** `docs/superpowers/specs/2026-03-24-claudeclaw-design.md`

---

## Scope

This sub-spec defines the implementation details for Plan 2. It covers:

1. A channel manager that concurrently runs multiple channel adapters feeding events to the orchestrator via a shared `asyncio.Queue`
2. The Telegram channel adapter using `python-telegram-bot`
3. The `channel add telegram` CLI command and `channels.yaml` config
4. The native skills directory and updated `SkillRegistry` that loads from both user and native skill locations
5. The `pop.md` native skill file

**Dependencies on Plan 1:** `ChannelAdapter` ABC (`claudeclaw/channels/base.py`), `CredentialStore` (`claudeclaw/auth/keyring.py`), `SkillRegistry` (`claudeclaw/skills/registry.py`), `Orchestrator` (`claudeclaw/core/orchestrator.py`), `Event` / `Response` (`claudeclaw/core/event.py`), `Settings` (`claudeclaw/config/settings.py`), `cli.py` (Click group).

**Out of scope for Plan 2:** Multiple simultaneous users per channel, media or file messages, inline keyboards, WhatsApp adapter, Slack adapter, web UI, marketplace, cron/webhook triggers.

---

## 1. Channel Manager

### Purpose

The channel manager (`claudeclaw/channels/manager.py`) is the glue between the orchestrator and all active channel adapters. It:

- Reads `~/.claudeclaw/config/channels.yaml` to discover which channels are enabled
- Instantiates the correct adapter for each enabled channel
- Starts each adapter as an independent `asyncio.Task`
- Feeds all incoming events into a single shared `asyncio.Queue[Event]`

The orchestrator pulls from this queue instead of calling `receive()` on a single adapter directly.

### Orchestrator Queue Refactor

In Plan 1, the orchestrator calls `receive()` on a single `ChannelAdapter` in a loop. Plan 2 replaces this with a `asyncio.Queue`-based design:

```python
# claudeclaw/core/orchestrator.py  (updated)
async def run(self, event_queue: asyncio.Queue):
    while True:
        event: Event = await event_queue.get()
        response = await self._process(event)
        await event.channel_adapter.send(response)
```

The `Event` dataclass gains a `channel_adapter` field (reference to the adapter that received the event) so the orchestrator can route responses back to the correct channel without a separate lookup.

### channels.yaml Schema

```yaml
# ~/.claudeclaw/config/channels.yaml
channels:
  - type: telegram
    enabled: true
  - type: cli
    enabled: true
```

Token storage: channel tokens are **never** stored in `channels.yaml`. They are stored in `CredentialStore` under a well-known key (`telegram-bot-token`). The adapter reads from `CredentialStore` at startup.

### ChannelManager API

```python
class ChannelManager:
    def __init__(self, config_path: Path, credential_store: CredentialStore): ...

    def load_channels(self) -> list[ChannelAdapter]:
        """Read channels.yaml and instantiate enabled adapters."""

    async def start_all(self, event_queue: asyncio.Queue) -> list[asyncio.Task]:
        """Start each adapter as an asyncio.Task that pushes to event_queue."""
```

Each adapter task runs a loop like:

```python
async for event in adapter.receive():
    await event_queue.put(event)
```

If an adapter raises an exception, the task logs the error and restarts after a configurable back-off (default: 5 seconds). This prevents one broken adapter from killing the entire daemon.

---

## 2. Telegram Channel Adapter

### File

`claudeclaw/channels/telegram_adapter.py`

### Dependencies

`python-telegram-bot>=21.0` — async-native library. The adapter uses the Application builder pattern.

### Implements

`ChannelAdapter` ABC defined in `claudeclaw/channels/base.py` (Plan 1):

```python
class ChannelAdapter(ABC):
    @abstractmethod
    async def receive(self) -> AsyncGenerator[Event, None]: ...

    @abstractmethod
    async def send(self, response: Response) -> None: ...
```

### TelegramAdapter Design

```python
class TelegramAdapter(ChannelAdapter):
    def __init__(self, token: str): ...

    async def receive(self) -> AsyncGenerator[Event, None]:
        """
        Uses python-telegram-bot's Application with a message handler.
        Yields Event objects for each incoming text message.
        Blocks internally; uses an asyncio.Queue to bridge PTB callbacks → generator.
        """

    async def send(self, response: Response) -> None:
        """
        Calls bot.send_message(chat_id=response.chat_id, text=response.text).
        chat_id is stored on the Event and carried through to the Response.
        """
```

#### Event Construction

For each incoming Telegram message, the adapter constructs:

```python
Event(
    text=message.text,
    channel="telegram",
    channel_adapter=self,           # reference for routing responses
    metadata={"chat_id": message.chat_id, "user_id": message.from_user.id},
)
```

#### Internal Queue Bridge

`python-telegram-bot` uses handler callbacks, not an async generator. The adapter bridges PTB callbacks to the `receive()` generator via an internal `asyncio.Queue`:

```python
async def _on_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
    await self._internal_queue.put(update.message)

async def receive(self):
    # starts the PTB Application in the background
    # loops over self._internal_queue.get()
    # yields Event objects
```

### Configuration Flow

```bash
claudeclaw channel add telegram --token <BOT_TOKEN>
```

This CLI command:

1. Calls `CredentialStore.set("telegram-bot-token", token)`
2. Reads `~/.claudeclaw/config/channels.yaml` (creates it if absent)
3. Upserts an entry `{type: telegram, enabled: true}` into the `channels` list
4. Writes the updated YAML back

The token is never written to `channels.yaml`.

### Token Retrieval at Runtime

```python
token = credential_store.get("telegram-bot-token")
if not token:
    raise RuntimeError("Telegram bot token not configured. Run: claudeclaw channel add telegram --token <TOKEN>")
adapter = TelegramAdapter(token=token)
```

---

## 3. Native Skills Directory

### Location

Native skills (bundled with the package) live at:

```
claudeclaw/skills/native/
├── pop.md
└── agent-creator.md
```

This directory is inside the installed Python package. Its absolute path is resolved at runtime via `importlib.resources` or `Path(__file__).parent`:

```python
NATIVE_SKILLS_DIR = Path(__file__).parent / "native"
```

### SkillRegistry Update

`claudeclaw/skills/registry.py` (Plan 1) currently loads only from `~/.claudeclaw/skills/`. Plan 2 updates it to load from **both** locations:

```python
class SkillRegistry:
    def __init__(self, user_skills_dir: Path, native_skills_dir: Path): ...

    def all_skills(self) -> list[SkillManifest]:
        """Returns native skills + user skills. User skills with the same name shadow native ones."""

    def find(self, name: str) -> Optional[SkillManifest]:
        """Looks up by skill name. User skills take precedence over native skills."""
```

**Rules:**
- Native skills are always available and cannot be deleted via the CLI
- If a user creates a skill with the same `name` as a native skill, the user skill takes precedence
- `claudeclaw skills list` shows both, with a `[native]` annotation for bundled skills

---

## 4. POP Native Skill (`pop.md`)

### Purpose

POP (Procedimento Operacional Padrão — Standard Operating Procedure) is a native skill that guides the user through mapping one specific function they want to automate and generates a skill `.md` file for it.

It is lighter and more focused than `agent-creator.md`: POP maps a single operation, step-by-step, and produces a ready-to-run skill file.

### Trigger Intent Keywords

The orchestrator routes to `pop.md` when the user's message contains any of these intent signals (case-insensitive):

- `"teach"`, `"ensina"`, `"ensinar"`
- `"automate"`, `"automatiza"`, `"automatizar"`
- `"map"`, `"mapeia"`, `"mapear"`
- `"pop"`, `"procedimento"`
- `"how to"`, `"como fazer"`

These keywords are checked by the orchestrator's intent router **before** dispatching to the general skill selection logic.

### Wizard Flow

The POP skill conducts a seven-step wizard conversation via whichever channel the user initiated from (Telegram, CLI, etc.):

| Step | Orchestrator message | What it collects |
|------|----------------------|-----------------|
| 1 | "What do you want to automate? Describe the task in a few words." | Task description → used as the skill `description` |
| 2 | "Step by step, what do you do manually? List each step, one per message, then say 'done'." | Ordered list of steps → becomes the skill body |
| 3 | "Which systems or tools do you use for this? (e.g. ERP, spreadsheet, email)" | Systems list → mapped to `plugins` / `mcps` |
| 4 | "Do any of these require credentials? If yes, I'll store them securely. Name each one and provide the value." | Credential key-value pairs → stored in `CredentialStore` |
| 5 | "How often should this run? Options: on-demand / daily / weekly / monthly / a specific cron expression" | Trigger + schedule |
| 6 | "Should it ask you before acting, notify you after, or run silently?" | Autonomy level (`ask` / `notify` / `autonomous`) |
| 7 | POP generates the `.md` file and saves it to `~/.claudeclaw/skills/<skill-name>.md` | — |
| — | "Skill '<name>' created. Run it with: `claudeclaw agents run <name>`" | — |

### Generated Skill File Format

POP generates a standard skill `.md` following the schema defined in the design spec:

```markdown
---
name: <slugified-task-name>
description: <task description from step 1>
trigger: <on-demand | cron | webhook>
schedule: "<cron expression>"    # only if trigger: cron
autonomy: <ask | notify | autonomous>
plugins: [<list from step 3>]
credentials: [<list from step 4>]
shell-policy: none
---

# <Task Name>

## Steps

1. <step 1>
2. <step 2>
...

## Systems Used

- <system 1>
- <system 2>
```

### Skill Naming

The skill name is derived from the task description (step 1) by:
1. Lowercasing
2. Replacing spaces and special characters with `-`
3. Truncating to 50 characters

Example: "Generate monthly invoice report" → `generate-monthly-invoice-report`

### Credential Handling During Wizard

When the user provides credentials in step 4:
- The orchestrator calls `CredentialStore.set(key, value)` immediately
- The wizard **does not echo** credential values back to the user
- The generated skill's frontmatter lists only the key names under `credentials:`

---

## 5. Intent Routing for POP

The orchestrator's intent router (`claudeclaw/core/router.py`, Plan 1) is extended with a priority check for native skill intents:

```python
NATIVE_SKILL_INTENTS = {
    "pop": ["teach", "ensina", "ensinar", "automate", "automatiza", "automatizar",
            "map", "mapeia", "mapear", "pop", "procedimento", "how to", "como fazer"],
    "agent-creator": ["create an agent", "i need someone to", "crie um agente",
                      "preciso de alguém"],
}

def route(event: Event, registry: SkillRegistry) -> SkillManifest:
    text_lower = event.text.lower()
    for skill_name, keywords in NATIVE_SKILL_INTENTS.items():
        if any(kw in text_lower for kw in keywords):
            skill = registry.find(skill_name)
            if skill:
                return skill
    # ... fall through to general semantic routing via Claude SDK
```

---

## 6. Updated `claudeclaw start` Flow

When `claudeclaw start` is run:

1. `Settings` is initialized
2. `CredentialStore` is initialized
3. `SkillRegistry` is initialized with both `native_skills_dir` and `user_skills_dir`
4. `ChannelManager` loads `channels.yaml` and instantiates enabled adapters
5. An `asyncio.Queue` is created
6. `ChannelManager.start_all(event_queue)` starts each adapter as an asyncio task
7. `Orchestrator.run(event_queue)` enters its processing loop

```
claudeclaw start
  └─ ChannelManager.start_all(queue)
       ├─ asyncio.Task: TelegramAdapter → pushes events to queue
       └─ asyncio.Task: CLIAdapter     → pushes events to queue
  └─ Orchestrator.run(queue)
       └─ event = await queue.get()
       └─ route → dispatch subagent → send response via event.channel_adapter
```

---

## 7. File Changes Summary

| File | Status | Notes |
|------|--------|-------|
| `claudeclaw/channels/manager.py` | **New** | ChannelManager |
| `claudeclaw/channels/telegram_adapter.py` | **New** | TelegramAdapter |
| `claudeclaw/skills/native/pop.md` | **New** | POP skill instructions |
| `claudeclaw/skills/native/agent-creator.md` | **New** (stub) | Placeholder for Plan 3 |
| `claudeclaw/skills/native/__init__.py` | **New** | Empty |
| `claudeclaw/skills/registry.py` | **Updated** | Load from both native + user dirs |
| `claudeclaw/core/event.py` | **Updated** | Add `channel_adapter` field to `Event` |
| `claudeclaw/core/orchestrator.py` | **Updated** | Use `asyncio.Queue` instead of single adapter |
| `claudeclaw/core/router.py` | **Updated** | Add native skill intent priority check |
| `claudeclaw/cli.py` | **Updated** | Add `channel add` command group |
| `pyproject.toml` | **Updated** | Add `python-telegram-bot>=21.0` |
| `tests/test_channel_manager.py` | **New** | Manager unit tests |
| `tests/test_telegram_adapter.py` | **New** | Adapter tests with mocked PTB |
| `tests/test_channel_cli.py` | **New** | `channel add` CLI tests |
| `tests/test_skill_registry_native.py` | **New** | Registry loads native skills |
| `tests/test_router_native_intents.py` | **New** | POP/agent-creator routing tests |

---

## 8. Key Design Decisions

**Why asyncio.Queue instead of a single adapter generator?**
Multiple channels run concurrently. A single generator can only yield from one source at a time. A shared queue is the standard asyncio pattern for fan-in from multiple producers to one consumer.

**Why store the adapter reference on the Event?**
The response must be routed back to the exact channel and chat that sent the message. Storing the adapter reference on the Event eliminates the need for a separate routing table and keeps the orchestrator stateless with respect to channel topology.

**Why bridge PTB callbacks to an async generator?**
`python-telegram-bot>=21` uses a callback-based handler model. Wrapping it in a generator makes the `ChannelAdapter` interface consistent across all adapters (CLI, Telegram, future Slack). The manager loop is the same regardless of the adapter's internal mechanics.

**Why is the POP skill a `.md` file and not Python code?**
All ClaudeClaw skills are `.md` files — this is a core design principle. The wizard logic in POP is expressed as natural language instructions for the Claude SDK subagent, not as procedural Python code. The orchestrator dispatches POP as a subagent the same way it dispatches any other skill.
