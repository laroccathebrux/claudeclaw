# ClaudeClaw — Plan 3 Spec: Scheduling (Claude Cron + Remote Triggers)

**Date:** 2026-03-25
**Status:** Draft
**Spec reference:** `docs/superpowers/specs/2026-03-24-claudeclaw-design.md`
**Plan reference:** `docs/superpowers/plans/2026-03-25-plan-3-scheduling.md`

---

## Overview

Plan 3 implements autonomous scheduling for ClaudeClaw. Skills can declare a cron trigger or a webhook trigger in their frontmatter. The orchestrator registers these triggers at startup using the `CronCreate` and `RemoteTrigger` tools from the Claude SDK tool protocol, receives their fire events as SDK `tool_use` messages, normalizes them into `Event` objects, and dispatches the appropriate skill — exactly as it would for a message arriving from a channel adapter.

---

## Critical Clarification: SDK-Level Tools, Not CLI

ClaudeClaw implements scheduling by calling `CronCreate` and `RemoteTrigger` as **programmatic SDK tool calls**, not by shelling out to the Claude Code CLI. ClaudeClaw is the only runtime. The orchestrator calls these tools directly via the Anthropic Python SDK's tool protocol. The SDK responds with a `tool_use` block when a cron fires or a webhook is received, and the orchestrator processes that block just like any other tool event.

There is no dependency on the `claude` CLI binary. Skills do not execute shell commands to schedule themselves. All scheduling is managed internally by the `ScheduleManager`.

---

## Skill Frontmatter Fields (Scheduling)

These fields are already parsed by `SkillLoader` (Plan 1). Plan 3 consumes them:

```yaml
# Cron skill
trigger: cron
schedule: "0 0 28 * *"    # standard 5-field cron expression

# Webhook skill
trigger: webhook
trigger-id: new-crm-lead  # arbitrary unique string; becomes the webhook identifier

# On-demand (default — not scheduled)
trigger: on-demand
```

- `trigger` — one of `cron | webhook | on-demand`. Skills with `trigger: on-demand` (or no trigger field) are ignored by the scheduler.
- `schedule` — required when `trigger: cron`. Standard POSIX 5-field cron expression (`* * * * *`). Timezones are out of scope for Plan 3 (UTC assumed).
- `trigger-id` — required when `trigger: webhook`. Must be unique across all installed skills. Serves as the identifier passed to `RemoteTrigger`.

---

## CronCreate Integration

### Registration flow

At orchestrator startup, after skills are loaded:

1. `ScheduleManager.register_crons()` iterates over all skills where `trigger == "cron"`.
2. For each skill, check `schedules.yaml` — if the skill is already registered and the schedule expression has not changed, skip.
3. If new or changed, call `CronCreate` via the Claude SDK with the skill's `schedule` expression and a `metadata` payload containing the skill name.
4. The SDK returns a `cron_id`. Store the mapping `skill_name → cron_id` in `schedules.yaml`.
5. If the previous registration exists (schedule changed), call `CronDelete` with the old `cron_id` before creating the new one.

### Firing flow

When a cron fires, the Claude SDK delivers a `tool_use` event to the orchestrator's event loop:

```json
{
  "type": "tool_use",
  "name": "CronFired",
  "input": {
    "cron_id": "cron_abc123",
    "fired_at": "2026-03-28T00:00:00Z"
  }
}
```

The orchestrator:
1. Looks up `cron_id` in `schedules.yaml` to find the skill name.
2. Constructs a normalized `Event` with `source="cron"`, `skill_name=<skill>`, `payload={"fired_at": ...}`.
3. Bypasses intent routing (skill is already known) and dispatches the subagent directly.

### Skill uninstall / update

- On skill uninstall: call `CronDelete(cron_id)` and remove the entry from `schedules.yaml`.
- On skill update (schedule expression changed): call `CronDelete` on the old id, then `CronCreate` with the new expression.

---

## RemoteTrigger Integration

### Registration flow

At orchestrator startup, after crons are registered:

1. `ScheduleManager.register_webhooks()` iterates over all skills where `trigger == "webhook"`.
2. For each skill, check `triggers.yaml` — if the `trigger-id` is already registered, skip.
3. If new, call `RemoteTrigger` via the Claude SDK with the skill's `trigger-id`.
4. The SDK returns an inbound webhook URL. Store the mapping `trigger_id → {skill_name, webhook_url}` in `triggers.yaml`.

### Firing flow

When an inbound webhook fires, the Claude SDK delivers a `tool_use` event:

```json
{
  "type": "tool_use",
  "name": "RemoteTriggerFired",
  "input": {
    "trigger_id": "new-crm-lead",
    "payload": { ... }
  }
}
```

The orchestrator:
1. Looks up `trigger_id` in `triggers.yaml` to find the skill name.
2. Constructs a normalized `Event` with `source="webhook"`, `skill_name=<skill>`, `payload=<raw webhook payload>`.
3. Dispatches the subagent directly (no intent routing needed).

### Skill uninstall

- On skill uninstall: remove the entry from `triggers.yaml`. (The SDK does not require an explicit deregistration call for webhooks in v1 — the URL becomes inactive when the trigger-id is no longer acknowledged.)

---

## Schedule Registry Files

### `~/.claudeclaw/config/schedules.yaml`

Tracks all registered cron schedules. Written and read exclusively by `ScheduleManager`.

```yaml
# schedules.yaml
erp-invoices:
  cron_id: cron_abc123
  schedule: "0 0 28 * *"
  registered_at: "2026-03-25T10:00:00Z"

daily-backup:
  cron_id: cron_def456
  schedule: "0 3 * * *"
  registered_at: "2026-03-25T10:00:01Z"
```

### `~/.claudeclaw/config/triggers.yaml`

Tracks all registered webhook triggers.

```yaml
# triggers.yaml
new-crm-lead:
  skill_name: crm-followup
  webhook_url: "https://hooks.anthropic.com/rt/xyz789"
  registered_at: "2026-03-25T10:00:02Z"

payment-received:
  skill_name: payment-handler
  webhook_url: "https://hooks.anthropic.com/rt/abc000"
  registered_at: "2026-03-25T10:00:03Z"
```

---

## Orchestrator Startup Sequence

With Plan 3 applied, the orchestrator startup order becomes:

```
1. Load settings
2. Load all skills via SkillLoader / SkillRegistry        (Plan 1)
3. Register crons via ScheduleManager.register_crons()    (Plan 3)
4. Register webhooks via ScheduleManager.register_webhooks() (Plan 3)
5. Start channel adapters (Telegram, CLI, etc.)           (Plan 2+)
6. Enter event loop
```

The scheduler must be initialized before channels so that scheduled events can be received as soon as the loop starts.

---

## ScheduleManager Interface

Module: `claudeclaw/scheduling/manager.py`

```python
class ScheduleManager:
    def __init__(self, sdk_client, settings: Settings): ...

    async def register_crons(self, skills: list[Skill]) -> None:
        """Register all cron skills with the SDK. Idempotent."""
        ...

    async def register_webhooks(self, skills: list[Skill]) -> None:
        """Register all webhook skills with the SDK. Idempotent."""
        ...

    async def handle_tool_use_event(self, event: dict) -> Event | None:
        """
        Given a raw SDK tool_use event dict, return a normalized Event
        if it matches a known cron or webhook trigger, else return None.
        """
        ...

    async def deregister_skill(self, skill_name: str) -> None:
        """Remove cron/webhook registration for a skill (used on uninstall)."""
        ...
```

The `handle_tool_use_event` method is called by the orchestrator's main event loop whenever the SDK yields a `tool_use` block. If the block is `CronFired` or `RemoteTriggerFired`, this method resolves the skill name and returns a normalized `Event`. Otherwise it returns `None` and the orchestrator processes the block normally.

---

## Normalized Event (Scheduling Sources)

The `Event` dataclass (from Plan 1, `claudeclaw/core/event.py`) is extended with scheduling-specific sources:

```python
@dataclass
class Event:
    source: str          # "cli" | "telegram" | "cron" | "webhook"
    skill_name: str | None   # pre-resolved for cron/webhook; None for channel events
    text: str | None     # human message text (None for scheduled events)
    payload: dict        # raw data (fired_at, webhook body, etc.)
    channel_reply_fn: Callable | None  # None for headless scheduled events
```

When `skill_name` is pre-populated, the orchestrator skips intent routing and dispatches the skill directly. When `channel_reply_fn` is `None`, the subagent's response is written to the execution log only (unless the skill declares `autonomy: notify`, in which case the orchestrator routes the response to a configured notification channel).

---

## CLI Additions

Two new subcommands under `claudeclaw schedule`:

### `claudeclaw schedule list`

Prints all registered cron and webhook schedules.

```
$ claudeclaw schedule list

CRON SCHEDULES
  erp-invoices      "0 0 28 * *"    cron_abc123
  daily-backup      "0 3 * * *"     cron_def456

WEBHOOK TRIGGERS
  new-crm-lead      skill: crm-followup    https://hooks.anthropic.com/rt/xyz789
  payment-received  skill: payment-handler https://hooks.anthropic.com/rt/abc000
```

### `claudeclaw schedule run <skill>`

Manually fires a scheduled skill immediately, bypassing the cron timer. Useful for testing.

```
$ claudeclaw schedule run erp-invoices
[2026-03-25 10:15:00] Firing erp-invoices manually...
[2026-03-25 10:15:04] Done. Result: Invoices sent to 12 clients.
```

This command constructs a synthetic `Event` with `source="manual"` and the skill name pre-populated, then dispatches it through the normal subagent path.

---

## Dependencies on Plan 1

The following Plan 1 components are prerequisites:

| Component | Used by Plan 3 |
|---|---|
| `SkillLoader` | Reads `trigger`, `schedule`, `trigger-id` frontmatter fields |
| `SkillRegistry` | Provides the list of skills to scan at startup |
| `Event` dataclass | Extended with `source="cron"/"webhook"/"manual"` and `skill_name` |
| `Orchestrator` | Modified startup sequence; receives `handle_tool_use_event` hook |
| `Settings` | Provides `config_dir` for schedules.yaml and triggers.yaml |

---

## Out of Scope for Plan 3

- Timezone handling (all crons are UTC)
- Schedule pause / resume via CLI
- Complex cron DSL (5-field standard cron only — no `@daily`, `@reboot`, etc.)
- Webhook authentication / signature verification (v2)
- Per-skill webhook payload schema validation (v2)
- Rate limiting of webhook calls (v2)
- Retry logic for failed scheduled skill runs (v2)
