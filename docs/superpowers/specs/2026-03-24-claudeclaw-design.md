# ClaudeClaw — Design Specification

**Date:** 2026-03-24
**Status:** Draft
**Author:** Alessandro Silveira

---

## Vision

ClaudeClaw is an installable autonomous agent system powered by the Claude SDK. It runs as a persistent daemon on any computer (macOS, Windows, Linux/VPS) and can be trained to perform tasks that a human employee would do. Each learned task becomes a **skill** — a markdown file (`.md`) following the same format as Claude Code skills. Users interact with the agent via messaging channels (Telegram, WhatsApp, Slack) or a local web UI, and the agent can also act autonomously on a schedule or in response to external events.

---

## Core Design Principles

1. **Skills as `.md` files** — every capability is a markdown file with frontmatter + instructions, identical to Claude Code skills. No code required to create a skill.
2. **Claude account = everything you need** — no API keys, no configuration. Log in with your claude.ai account and the system works immediately within your plan's limits.
3. **Cross-platform** — runs on macOS, Windows, and Linux (including headless VPS).
4. **Hierarchical ecosystem** — skills and plugins flow from local → team → public marketplace.
5. **Security by declaration** — every skill declares exactly what it can access. Nothing is implicit.

---

## System Architecture

### Layer Overview

```
┌─────────────────────────────────────────────────────────┐
│  INPUTS                                                  │
│  Channels: Telegram · WhatsApp · Slack · Web UI · CLI   │
│  Triggers: Claude Cron · Remote Trigger (webhook)        │
└───────────────────────┬─────────────────────────────────┘
                        │ normalized message or trigger event
┌───────────────────────▼─────────────────────────────────┐
│  ORCHESTRATOR AGENT  (daemon, always-on)                 │
│  Claude SDK · intent routing · permission check          │
│  credential injection · subagent dispatch · response     │
└───────────────────────┬─────────────────────────────────┘
                        │ dispatch subagent + loaded skill
┌───────────────────────▼─────────────────────────────────┐
│  SUBAGENTS  (Claude SDK instances)                       │
│  Each subagent loads one skill .md and has only the      │
│  tools, MCPs, and credentials declared in that skill.    │
└───────────────────────┬─────────────────────────────────┘
                        │ uses
┌───────────────────────▼─────────────────────────────────┐
│  PLUGINS & MCPs                                          │
│  Global MCPs: filesystem · browser · computer-use       │
│  Per-agent MCPs: postgres · gmail · whatsapp · etc.      │
│  Plugins: MCP + skill templates + auth abstraction       │
└───────────────────────┬─────────────────────────────────┘
                        │ protected by
┌───────────────────────▼─────────────────────────────────┐
│  SECURITY                                                │
│  Native Permissions · OpenShell · Keyring                │
└───────────────────────┬─────────────────────────────────┘
                        │ loaded from
┌───────────────────────▼─────────────────────────────────┐
│  SKILL ECOSYSTEM                                         │
│  Local (~/.claudeclaw/skills/) · Team (git) · Marketplace│
└─────────────────────────────────────────────────────────┘
```

---

## Components

### 1. Orchestrator Agent

The orchestrator is the always-running daemon process. It is itself a Claude SDK agent with a system prompt that defines its routing behavior.

**Responsibilities:**
- Normalize incoming messages from all channel adapters into a standard event format
- Understand user intent via Claude SDK
- Select the appropriate skill based on intent
- Verify permissions for the selected skill
- Fetch credentials from Keyring and inject them as environment variables into the subagent
- Dispatch the subagent with the skill loaded
- Collect the result and route the response back to the originating channel
- Maintain conversation memory and execution history
- Manage the cron schedule registry and remote trigger registrations
- Monitor plan usage and apply rate limiting behavior

**Started via:**
```bash
claudeclaw start          # foreground
claudeclaw start --daemon # background daemon
```

---

### 2. Channel Adapters

Pluggable adapters that normalize external messages into a standard internal event. Each adapter is configured independently.

| Channel | Adapter |
|---|---|
| Telegram | python-telegram-bot |
| WhatsApp | Twilio API |
| Slack | slack-bolt |
| Web UI | FastAPI + localhost:3000 |
| CLI | Click / stdin |

**Configuration:**
```bash
claudeclaw channel add telegram --token <BOT_TOKEN>
claudeclaw channel add slack --token <SLACK_TOKEN>
```

Channel tokens are stored in the Keyring, not in config files.

---

### 3. Scheduling: Claude Cron + Remote Triggers

ClaudeClaw implements scheduling using the `CronCreate` and `RemoteTrigger` tools from the Claude SDK tool protocol. These are SDK-level tools called programmatically by the orchestrator — not a dependency on the Claude Code CLI. ClaudeClaw is the only runtime; it calls these tools directly via the SDK.

**Claude Cron** — skills declare a cron expression in their frontmatter. The orchestrator registers and manages the schedule by calling `CronCreate` via the SDK at startup and whenever a new skill is installed.

**Remote Triggers** — skills can declare a webhook trigger. The orchestrator calls `RemoteTrigger` via the SDK to register an inbound webhook endpoint for that skill.

Both mechanisms converge at the orchestrator the same way a channel message does — as a normalized event that selects and dispatches a skill.

```yaml
# cron example
trigger: cron
schedule: "0 0 28 * *"    # monthly, 28th at midnight

# remote trigger example
trigger: webhook
trigger-id: new-crm-lead
```

---

### 4. Subagents

Each task runs as an isolated Claude SDK agent invocation. The orchestrator dispatches a subagent by:

1. Loading the skill's `.md` file as the system prompt
2. Injecting only the tools, MCPs, and credentials declared in the skill's frontmatter
3. Running the subagent with those constraints

Subagents are stateless — they receive their full context at dispatch time and return a result. State between invocations is managed by the orchestrator.

---

### 5. Skills

A skill is a `.md` file with YAML frontmatter and natural language instructions. This is identical in format to Claude Code skills.

**Frontmatter schema:**
```yaml
---
name: string                    # unique identifier
description: string             # one-line description for routing

# Activation
trigger: cron | webhook | on-demand
schedule: "cron expression"     # only for trigger: cron
trigger-id: string              # only for trigger: webhook

# Autonomy
autonomy: ask | notify | autonomous
# ask        = always ask before acting
# notify     = act and then notify
# autonomous = act silently, only contact on error

# Capabilities
plugins: [list of plugin names]          # high-level abstractions
mcps: [list of MCP names]                # low-level tool protocols
mcps_agent: [list of agent-specific MCPs]# MCPs only this agent uses
tools: [list of specific tools]          # other specific tools
credentials: [list of keyring key names] # credential references

# Security
shell-policy: none | read-only | restricted | full
# none       = no shell access
# read-only  = can read filesystem, no execution
# restricted = OpenShell filtered execution
# full       = unrestricted (not recommended for marketplace skills)
---

# Skill instructions (natural language)
...
```

**Native skills** (bundled with ClaudeClaw):
- `agent-creator.md` — wizard that creates a new agent end-to-end
- `pop.md` — Procedimento Operacional Padrão: maps a single function and generates a skill
- `skill-installer.md` — installs skills and plugins from the marketplace

---

### 6. Plugins

A plugin is a **PyPI-compatible Python package** installable via `claudeclaw plugin install`. The package follows a standard ClaudeClaw plugin manifest and bundles:
- One or more MCP server configurations (JSON, registered into `~/.claudeclaw/config/mcps.yaml`)
- Skill templates (pre-built `.md` files copied to `~/.claudeclaw/skills/`)
- Authentication handlers (OAuth flows, token refresh logic executed by the orchestrator)
- Utility Python modules loaded only by the orchestrator, never directly exposed to skill subagents

```bash
claudeclaw plugin install gmail
# 1. pip-installs claudeclaw-plugin-gmail from the marketplace registry
# 2. Registers gmail MCP config into mcps.yaml
# 3. Copies email skill templates to ~/.claudeclaw/skills/
# 4. Registers OAuth handler with the orchestrator
```

The marketplace registry is a central index (similar to PyPI) that maps plugin names to package distributions. Plugins are published by the community and signed; ClaudeClaw verifies signatures before installation.

Skills interact with plugin capabilities through declared MCPs and tools — they never call plugin Python code directly.

---

### 7. MCPs (Model Context Protocol)

MCPs extend the subagent's tool set at the protocol level.

**Scope:**

- **Global MCPs** — configured once, available to all agents:
  ```bash
  claudeclaw mcp add filesystem
  claudeclaw mcp add browser
  ```

- **Per-agent MCPs** — declared in the skill's frontmatter under `mcps_agent`. The orchestrator configures these only for the specified agent's subagent invocations.

MCP configurations are stored in `~/.claudeclaw/config/mcps.yaml`. Credentials required by MCPs are stored in the Keyring.

---

### 8. Security

Three complementary layers:

**Layer 1 — Claude Native Permissions**
The orchestrator only injects tools and MCPs that are explicitly declared in the skill's frontmatter. A skill that declares `tools: [crm-api]` cannot access the filesystem, the shell, or any other tool, regardless of what the skill's instructions ask for.

**Layer 2 — OpenShell**
All shell command execution is routed through OpenShell, a sandboxed shell environment compatible with OpenClaw and NemoClaw. The `shell-policy` field in the skill frontmatter defines the sandbox policy. This layer is cross-platform.

**Layer 3 — Keyring**
All credentials (OAuth tokens, API keys, usernames, passwords) are stored in the OS-native secret store:
- macOS → Keychain
- Windows → Windows Credential Manager
- Linux (GUI) → libsecret / GNOME Keyring
- Linux (headless VPS) → encrypted file protected by a master password set at install time

Skills never receive credentials directly. The orchestrator fetches them from Keyring and injects them as environment variables into the subagent at dispatch time.

---

### 9. Authentication — Claude Account

ClaudeClaw uses the same OAuth mechanism as Claude Code. No API key is required.

```bash
claudeclaw login    # opens browser → authenticate with claude.ai account
```

The OAuth token is stored in the Keyring. Token refresh is handled automatically.

**Plan-aware behavior:**

| Plan | Orchestrator behavior |
|---|---|
| Free | Conservative: all skills default to `ask`, cron max 1/day |
| Pro | Standard: autonomy as configured, standard cron frequency |
| Max | Full: parallel subagent dispatch, high-frequency crons |

**Usage tracking:** The orchestrator tracks token consumption locally, incrementing a counter per subagent invocation. It does not poll the Claude API for usage — it estimates from its own dispatch log. The 80% threshold is calculated against known plan limits (stored in a local config updated at login when the plan is detected from the OAuth token claims). Thresholds are configurable via `~/.claudeclaw/config/limits.yaml`.

When approaching plan limits:
1. Notify user via active channel ("80% of daily limit used")
2. Downgrade autonomous skills to notify mode
3. Pause non-critical cron schedules

---

### 10. Agent Creator

A native skill (`agent-creator.md`) that conducts a wizard conversation to create a fully configured agent from a natural language description.

**Trigger:** The orchestrator recognizes agent-creation intent from natural language (e.g., "I need someone to help me with...", "Create an agent that...", "I want to automate...") and dispatches the Agent Creator skill.

**Wizard flow:**
```
1. Understand the task → "What do you need the agent to do?"
2. Identify systems needed → "Which systems does it need to access?"
3. Collect credentials → stored in Keyring (password input masked)
4. Configure schedule → "How often should it run?"
5. Set autonomy level → "Should it ask before acting?"
6. Generate skill .md → written to ~/.claudeclaw/skills/
7. Register cron/trigger → via CronCreate or RemoteTrigger
8. Confirm → "Your agent is ready. First run: [date/time]"
```

All wizard interaction happens through the same channel the user initiated from (Telegram, Slack, etc.).

---

### 11. POP — Procedimento Operacional Padrão

A native skill (`pop.md`) for mapping and automating a single function. Lighter than Agent Creator — used when the user wants to teach the agent one specific operation rather than create a full agent.

**Use case:** "Teach the agent how to generate a monthly report from this spreadsheet."

---

## End-to-End Example Flow

> User installs ClaudeClaw on a VPS, logs in with Claude account, connects Telegram. Sends: "I need someone to help with invoice emission in my ERP. Every month I need to issue invoices and email them to clients."

```
1. Telegram adapter receives message
2. Orchestrator receives normalized event
3. Claude SDK identifies intent: agent creation
4. Orchestrator dispatches agent-creator.md subagent
5. Agent Creator conducts wizard via Telegram:
   - "What ERP system do you use?" → [user answers]
   - "What's the ERP URL?" → [user answers]
   - "ERP username?" → [stored in Keyring as erp-user]
   - "ERP password?" → [stored in Keyring as erp-password]
   - "Which email do you send from?" → [user answers]
   - "Email password / app token?" → [stored in Keyring as email-token]
   - "Which day of month should invoices be sent?" → 28th
   - "Should it run without asking you first?" → Yes
6. Agent Creator generates: erp-invoices.md
7. Registers cron: "0 0 28 * *"
8. Responds via Telegram: "Invoice agent ready. First run: March 28."
```

---

## Skill Ecosystem

```
Local:       ~/.claudeclaw/skills/*.md          (user's own skills)
Team:        private git repo                   (shared within org)
Marketplace: claudeclaw install <skill-name>    (public registry)

Plugin Local:      ~/.claudeclaw/plugins/
Plugin Marketplace: claudeclaw plugin install <name>
```

**CLI commands:**
```bash
claudeclaw install crm-followup       # install skill from marketplace
claudeclaw plugin install gmail       # install plugin from marketplace
claudeclaw skills list                # list installed skills
claudeclaw agents list                # list configured agents
claudeclaw agents run erp-invoices    # manual trigger
claudeclaw mcp list                   # list configured MCPs
```

---

## Installation

```bash
pip install claudeclaw
claudeclaw login                      # OAuth with claude.ai
claudeclaw channel add telegram --token <TOKEN>
claudeclaw start --daemon             # start orchestrator
```

On headless Linux VPS, first-time setup prompts for a master password used to encrypt the credential store (replaces GUI Keyring).

---

## Out of Scope (v1)

- Skill code execution (all skills are `.md` instructions, no Python in skills)
- Multi-user / multi-tenant (one Claude account per installation)
- Self-hosted marketplace (v1 uses central registry)
- Mobile app interface
- Voice channel adapters
