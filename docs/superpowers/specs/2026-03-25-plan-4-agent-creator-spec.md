# ClaudeClaw — Plan 4 Spec: Agent Creator Native Skill

**Date:** 2026-03-25
**Status:** Draft
**Author:** Alessandro Silveira
**Plan:** 4 of N
**Spec reference:** `docs/superpowers/specs/2026-03-24-claudeclaw-design.md`

---

## Overview

Plan 4 implements the Agent Creator — the most strategically important native skill in ClaudeClaw. It allows any user, regardless of technical skill, to create a fully configured autonomous agent through a guided multi-turn conversation in whatever channel they are already using (Telegram, Slack, CLI, etc.).

The Agent Creator is a **meta-skill**: it is always available to the router regardless of what other skills are installed, and it is capable of producing new skills that are immediately active after the conversation ends.

---

## 1. Native Skill: `agent-creator.md`

### Location

```
claudeclaw/skills/native/agent-creator.md
```

This file ships inside the ClaudeClaw Python package. On startup, the orchestrator loads native skills from this bundled directory in addition to `~/.claudeclaw/skills/`. Native skills are always available; they cannot be uninstalled.

### Trigger

The orchestrator's router must recognize Agent Creator intent and dispatch this skill instead of — or in addition to — routing to installed user skills.

**Recognition patterns (non-exhaustive):**
- English: "I need someone to...", "create an agent that...", "automate...", "build me an agent...", "I want to set up..."
- Portuguese: "quero criar um agente para...", "preciso de alguém que...", "automatizar..."
- Any message expressing a desire to create, build, train, or configure a new automated capability

### Wizard Flow

The Agent Creator skill conducts a structured multi-turn conversation. Each step produces a question to the user; the user's answer advances the wizard to the next step.

```
Step 1 — Task Description
  Question: "What do you need the agent to do? Describe the task in natural language."
  Captures: task_description (free text)

Step 2 — Systems
  Question: "Which systems does it need to access? (e.g., ERP, CRM, Gmail, Slack, a website...)"
  Captures: systems[] (list of system names, may be empty)

Step 3 — Credentials (per system, loop)
  For each system in systems:
    Question: "What's the URL or API endpoint for [system]?"
    Captures: system_url
    Question: "Username for [system]? (or press Enter to skip)"
    Captures: username → stored in Keyring as "<agent-slug>-<system>-user"
    Question: "Password or API token for [system]? (will be stored securely)"
    Captures: password/token → stored in Keyring as "<agent-slug>-<system>-token"

Step 4 — Schedule
  Question: "How often should it run?"
  Options: on-demand / daily at [time] / weekly on [day] / monthly on [date] / webhook
  Captures: trigger type + schedule expression

Step 5 — Autonomy
  Question: "Should it ask before acting, run and then notify you, or run silently?"
  Options: ask / notify / autonomous
  Captures: autonomy level

Step 6 — Skill Generation (internal, no question)
  Wizard generates a complete .md skill file from collected data.
  Writes to: ~/.claudeclaw/skills/<agent-slug>.md
  Reloads SkillRegistry.

Step 7 — Schedule Registration (internal, no question)
  If trigger is cron: calls CronCreate via SDK with the computed expression.
  If trigger is webhook: calls RemoteTrigger via SDK to register webhook endpoint.

Step 8 — Confirmation
  Message: "Your agent '[name]' is ready.
            First run: [date/time if scheduled, 'on demand' otherwise].
            Run manually: claudeclaw agents run [agent-slug]"
```

### Conversation State

The Agent Creator is a **multi-turn conversation**. Unlike regular skills that execute in one shot, the subagent dispatched for Agent Creator must persist its wizard state between user messages.

State transitions:
- Orchestrator detects Agent Creator intent → creates a new conversation entry
- Each subsequent message from that user on that channel is checked: if an active Agent Creator conversation exists for `(channel, user_id)`, the message is routed to Agent Creator (not through the regular router)
- Conversation is cleared when: wizard completes (step 8), user sends "cancel" or "nevermind", or conversation is idle for more than 30 minutes

---

## 2. Conversation State Management

### Module

```
claudeclaw/core/conversation.py
```

### Class: `ConversationStore`

Persists multi-turn conversation state across subagent invocations. Each conversation is keyed by `(channel, user_id)` and stored as a JSON file.

**Storage path:**
```
~/.claudeclaw/config/conversations/<channel>__<user_id>.json
```

**JSON schema:**
```json
{
  "channel": "telegram",
  "user_id": "12345678",
  "skill_name": "agent-creator",
  "created_at": "2026-03-25T10:00:00Z",
  "updated_at": "2026-03-25T10:02:30Z",
  "step": 3,
  "data": {
    "task_description": "...",
    "systems": ["erp", "gmail"],
    "credentials_collected": ["erp-user", "erp-token"],
    "current_system_index": 1
  },
  "history": [
    {"role": "assistant", "content": "What do you need the agent to do?"},
    {"role": "user", "content": "Issue monthly invoices from our ERP"},
    ...
  ]
}
```

**API:**
```python
class ConversationStore:
    def get(self, channel: str, user_id: str) -> Optional[ConversationState]
    def save(self, state: ConversationState) -> None
    def clear(self, channel: str, user_id: str) -> None
    def has_active(self, channel: str, user_id: str) -> bool
    def list_active(self) -> list[ConversationState]
    def clear_expired(self, max_idle_minutes: int = 30) -> int
```

### Orchestrator Integration

The orchestrator checks `ConversationStore` before routing every event:

```python
# In orchestrator._handle(event, router):
active = self._conv_store.has_active(event.channel, event.user_id)
if active:
    state = self._conv_store.get(event.channel, event.user_id)
    skill = self._registry.find(state.skill_name)  # always "agent-creator"
else:
    skill = router.route(event)
```

The full conversation history is passed to the subagent dispatcher so the subagent resumes from where it left off:

```python
result = self._dispatcher.dispatch(skill, event, conversation=state)
```

`SubagentDispatcher.dispatch()` gains an optional `conversation: Optional[ConversationState]` parameter. When present, the conversation history is prepended to the messages list and the current wizard step is included in the system prompt context.

---

## 3. Skill Generator

### Module

```
claudeclaw/skills/generator.py
```

### Class: `SkillGenerator`

Takes the wizard's collected data and produces a valid `.md` skill file.

**Input:** `WizardOutput` dataclass containing all fields from the wizard conversation.

**Output:** writes `~/.claudeclaw/skills/<slug>.md` and returns the `Path`.

**Generated frontmatter fields:**
```yaml
---
name: <slug>                          # kebab-case from task description
description: <one-line summary>       # synthesized by Claude from task_description
trigger: <on-demand|cron|webhook>
schedule: "<cron expression>"         # only if trigger: cron
trigger-id: <slug>-webhook            # only if trigger: webhook
autonomy: <ask|notify|autonomous>
tools: []
credentials: [<list of keyring keys>]
shell-policy: none
---
```

**Generated body:** The wizard output's `task_description` plus system/credential context, structured as Claude instructions.

**Slug generation:** kebab-case from the first meaningful words of `task_description`, deduplicated if a file already exists (appends `-2`, `-3`, etc.).

**Registry reload:** After writing, calls `SkillRegistry.reload()` so the skill is immediately available without restarting the orchestrator.

---

## 4. Router Update: Meta-Skills

### Always-Available Skills

Agent Creator and POP are **meta-skills** — they are always candidates for routing regardless of what user skills are installed. The router prompt must always include them.

**Updated router prompt structure:**
```
Always-available skills (these are ALWAYS options regardless of installed skills):
- agent-creator: Creates a new autonomous agent via a guided wizard. Match when the user
  wants to create, build, set up, automate, or train a new agent or capability.
- pop: Maps a single operation step-by-step and creates a skill. Match when the user
  wants to teach the system how to do one specific thing.

Installed skills:
<...existing skill list...>
```

**Router return contract update:** The router returns either a `SkillManifest` (from registry) or a string `"agent-creator"` / `"pop"` for meta-skills. The orchestrator resolves meta-skill names to the native skill `.md` from the bundled path.

---

## 5. Dependencies

| Dependency | From Plan |
|---|---|
| `SubagentDispatcher` | Plan 1 |
| `Router` | Plan 1 |
| `SkillRegistry` | Plan 1 |
| `CredentialStore` | Plan 1 |
| `Event` / `Response` | Plan 1 |
| Native skills loading | Plan 2 |
| POP wizard pattern (multi-turn conversation) | Plan 2 |
| `CronCreate` / `RemoteTrigger` SDK calls | Plan 3 |

---

## 6. Out of Scope for Plan 4

- GUI or web-based wizard (wizard runs through active channel only)
- Editing or updating an existing agent (update flow is a separate meta-skill)
- Skill templates from a marketplace (skills are generated from scratch)
- Multi-user / per-user skill isolation
- Agent Creator invoked via cron or webhook (only via channel messages)

---

## 7. File Map

```
claudeclaw/
├── skills/
│   ├── native/
│   │   └── agent-creator.md          ← wizard instructions for Claude (pure .md)
│   ├── generator.py                  ← WizardOutput → writes .md skill file
│   └── registry.py                   ← gains reload() method
├── core/
│   ├── conversation.py               ← ConversationStore: persist wizard state
│   ├── orchestrator.py               ← updated: checks ConversationStore before routing
│   └── router.py                     ← updated: always-available meta-skills in prompt
└── subagent/
    └── dispatch.py                   ← updated: accepts optional conversation history

tests/
├── test_conversation.py
├── test_skill_generator.py
├── test_router_meta_skills.py
└── test_agent_creator_integration.py
```

---

## 8. Security Considerations

- Credentials collected during the wizard (Step 3) are stored in Keyring immediately as the user types them, using the same `CredentialStore` abstraction from Plan 1.
- The password/token step must use masked input on interactive channels (terminal: use `getpass`; Telegram: remind user to delete their message after sending, as Telegram has no masked input).
- The generated skill file must not contain credential values — only the Keyring key names are written to the frontmatter `credentials:` list.
- Conversation JSON files must not contain credential values — collected credentials are stored in Keyring at collection time and only referenced by key name in the conversation state.

---

## 9. End-to-End Example

User sends via Telegram: "quero criar um agente para emitir notas fiscais no nosso ERP todo mês"

```
Orchestrator: router detects agent-creation intent → dispatches agent-creator.md
Agent Creator → "O que você precisa que o agente faça? Descreva a tarefa."
User → "Emitir notas fiscais no ERP e enviar por email todo dia 28"
[state saved: step=2, task_description="..."]

Agent Creator → "Quais sistemas ele precisa acessar?"
User → "ERP e Gmail"
[state saved: step=3, systems=["erp", "gmail"], current_system_index=0]

Agent Creator → "Qual é a URL do ERP?"
User → "https://erp.empresa.com"
Agent Creator → "Usuário do ERP?"
User → "financeiro@empresa.com"
[stored in Keyring: "erp-invoices-erp-user" = "financeiro@empresa.com"]
Agent Creator → "Senha ou token do ERP?"
User → "supersecret"
[stored in Keyring: "erp-invoices-erp-token" = "supersecret"]
[state saved: step=3, current_system_index=1]

... (same for gmail) ...

Agent Creator → "Com que frequência deve rodar?"
User → "Todo dia 28"
[state saved: step=4, trigger="cron", schedule="0 0 28 * *"]

Agent Creator → "Deve perguntar antes de agir, avisar depois, ou rodar silenciosamente?"
User → "Rodar silenciosamente"
[state saved: step=5, autonomy="autonomous"]

[internal: generate erp-invoices.md → write to ~/.claudeclaw/skills/]
[internal: register CronCreate "0 0 28 * *"]
[conversation cleared]

Agent Creator → "Seu agente 'erp-invoices' está pronto.
                 Próxima execução: 28 de abril.
                 Para rodar manualmente: claudeclaw agents run erp-invoices"
```
