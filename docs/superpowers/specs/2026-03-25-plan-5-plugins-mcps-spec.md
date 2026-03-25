# ClaudeClaw — Plan 5 Sub-Spec: Plugins + MCPs

**Date:** 2026-03-25
**Status:** Draft
**Author:** Alessandro Silveira
**Spec reference:** `docs/superpowers/specs/2026-03-24-claudeclaw-design.md`

---

## Overview

Plan 5 delivers two coupled systems: the **MCP configuration layer** (how MCPs are declared, stored, and injected into subagent invocations) and the **plugin system** (how third-party packages bundle MCPs, skills, and auth handlers for one-command installation). It also completes the security model by replacing the Plan 1 plaintext credential injection with proper environment variable injection via the Claude SDK.

**Dependencies on Plan 1:** `CredentialStore` (auth/keyring.py), `SubagentDispatcher` (subagent/dispatch.py), `SkillManifest` with `mcps`, `mcps_agent`, and `credentials` fields already parsed by skills/loader.py.

---

## 1. MCP System

### 1.1 Concept

MCPs (Model Context Protocol servers) extend the subagent's tool set at the protocol level. They are external processes that the Claude SDK connects to at dispatch time. ClaudeClaw manages which MCPs are available to which subagents through a central configuration file and scope rules.

### 1.2 Configuration Storage

MCP configurations are stored in `~/.claudeclaw/config/mcps.yaml`.

**Schema:**

```yaml
mcps:
  - name: filesystem
    command: npx
    args: ["-y", "@modelcontextprotocol/server-filesystem", "/home/user"]
    env: {}
    scope: global

  - name: postgres
    command: npx
    args: ["-y", "@modelcontextprotocol/server-postgres"]
    env:
      POSTGRES_URL: "postgresql://localhost:5432/mydb"
    scope: agent
```

**Field definitions:**

| Field | Type | Required | Description |
|---|---|---|---|
| `name` | `str` | yes | Unique identifier; used in skill frontmatter `mcps` / `mcps_agent` lists |
| `command` | `str` | yes | Executable to launch the MCP server |
| `args` | `list[str]` | no | Arguments passed to the command |
| `env` | `dict[str, str]` | no | Environment variables for the MCP server process (non-secret values only) |
| `scope` | `"global" \| "agent"` | yes | `global` = available to all subagents; `agent` = per-skill opt-in only |

### 1.3 Scope Rules

- **Global MCPs** (`scope: global`): injected into every subagent call automatically. Intended for infrastructure-level tools like `filesystem`, `browser`, `computer-use`.
- **Per-agent MCPs** (`scope: agent`): only injected when the skill's frontmatter lists that MCP name under `mcps` or `mcps_agent`. Intended for service-specific tools like `postgres`, `gmail`, `whatsapp`.

### 1.4 MCP Resolution Logic

At dispatch time, the orchestrator calls `resolve_mcps(skill)` which returns the list of `MCPConfig` objects to inject:

```python
def resolve_mcps(skill: SkillManifest) -> list[MCPConfig]:
    all_mcps = load_mcps()
    resolved = []
    # Always include global MCPs
    resolved.extend(m for m in all_mcps if m.scope == "global")
    # Add per-agent MCPs declared in skill frontmatter
    agent_names = set((skill.mcps or []) + (skill.mcps_agent or []))
    resolved.extend(m for m in all_mcps if m.scope == "agent" and m.name in agent_names)
    return resolved
```

### 1.5 MCP CLI Commands

```bash
claudeclaw mcp add <name> --command <cmd> [--args <arg1> <arg2> ...] [--env KEY=VALUE ...] [--scope global|agent]
claudeclaw mcp list
claudeclaw mcp remove <name>
```

`mcp add` appends to `~/.claudeclaw/config/mcps.yaml`. `mcp remove` removes by name. `mcp list` prints a table of all configured MCPs with their scope.

### 1.6 Implementation Module

**`claudeclaw/mcps/config.py`** — sole owner of `mcps.yaml` read/write:

```python
class MCPConfig:
    name: str
    command: str
    args: list[str]
    env: dict[str, str]
    scope: Literal["global", "agent"]

def load_mcps() -> list[MCPConfig]: ...
def save_mcps(mcps: list[MCPConfig]) -> None: ...
def add_mcp(config: MCPConfig) -> None: ...
def remove_mcp(name: str) -> None: ...
def resolve_mcps(skill: SkillManifest) -> list[MCPConfig]: ...
```

### 1.7 SubagentDispatcher Update

`SubagentDispatcher.dispatch()` in `claudeclaw/subagent/dispatch.py` is updated to:

1. Call `resolve_mcps(skill)` to get the list of active MCPs.
2. Convert each `MCPConfig` to the `MCPServerStdio` (or equivalent) format expected by the Anthropic SDK.
3. Pass the resulting list as the `mcp_servers` parameter of the Claude SDK `messages.create()` call.

```python
# pseudocode — exact SDK parameter name may vary
mcp_servers = [
    {"type": "stdio", "command": m.command, "args": m.args, "env": m.env}
    for m in resolve_mcps(skill)
]
client.messages.create(..., mcp_servers=mcp_servers)
```

---

## 2. Credential Injection Update

### 2.1 Problem with Plan 1 Approach

Plan 1 simplified credential handling by injecting credential values as plaintext into `_build_system_prompt()`. This leaks secrets into the system prompt string, which may appear in logs, error traces, or SDK debug output.

### 2.2 Plan 5 Solution: Environment Variable Injection

The design spec states: *"The orchestrator fetches them from Keyring and injects them as environment variables into the subagent at dispatch time."*

Plan 5 implements this correctly:

1. The skill's `credentials` list contains Keyring key names (e.g., `["erp-user", "erp-password"]`).
2. `SubagentDispatcher.dispatch()` fetches each credential value from `CredentialStore`.
3. Values are placed in an `env` dict with uppercased, hyphen-to-underscore key names:
   - `erp-user` → `ERP_USER`
   - `erp-password` → `ERP_PASSWORD`
   - `email-token` → `EMAIL_TOKEN`
4. The `env` dict is passed to the Claude SDK call via the appropriate SDK parameter.
5. The system prompt no longer contains any credential values.

**Key name normalization rule:**

```python
def credential_key_to_env_var(key: str) -> str:
    return key.upper().replace("-", "_")
```

### 2.3 Subagent Access

The skill's natural language instructions reference credentials by their env var name:

```markdown
Use the ERP_USER and ERP_PASSWORD environment variables to authenticate
with the ERP system at the URL provided in ERP_URL.
```

The subagent reads these via standard environment variable access in any tool it calls. The values are never in the prompt text.

---

## 3. Plugin System

### 3.1 Concept

A plugin is a **PyPI-compatible Python package** with the naming convention `claudeclaw-plugin-<name>`. Installing a plugin with one command registers its MCPs, copies its skill templates, and records its metadata.

```bash
claudeclaw plugin install gmail
# Equivalent to:
# pip install claudeclaw-plugin-gmail
# + read manifest + register MCPs + copy skills
```

### 3.2 Plugin Manifest

Every plugin package must include a `claudeclaw_plugin.json` at its package root.

**Schema:**

```json
{
  "name": "gmail",
  "version": "1.0.0",
  "description": "Gmail MCP integration with skill templates",
  "mcps": [
    {
      "name": "gmail",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-gmail"],
      "env": {},
      "scope": "agent"
    }
  ],
  "skills": [
    "skills/email-monitor.md",
    "skills/email-reply.md"
  ],
  "auth_handler": "claudeclaw_plugin_gmail.auth.GmailOAuthHandler"
}
```

**Field definitions:**

| Field | Type | Required | Description |
|---|---|---|---|
| `name` | `str` | yes | Plugin name (matches PyPI suffix) |
| `version` | `str` | yes | Semver version string |
| `description` | `str` | yes | One-line description |
| `mcps` | `list[MCPConfig]` | no | MCP configs to register in `mcps.yaml` |
| `skills` | `list[str]` | no | Relative paths to `.md` skill files within the package |
| `auth_handler` | `str` | no | Dotted Python path to an OAuth handler class (stub in Plan 5) |

### 3.3 Plugin Registry File

Installed plugins are tracked in `~/.claudeclaw/config/plugins.yaml`:

```yaml
plugins:
  - name: gmail
    version: "1.0.0"
    package: claudeclaw-plugin-gmail
    installed_at: "2026-03-25T10:00:00"
    mcps: [gmail]
    skills: [email-monitor, email-reply]
```

### 3.4 Plugin Manager

**`claudeclaw/plugins/manager.py`** owns all plugin lifecycle operations:

```python
def install(name: str) -> None:
    """
    1. pip install claudeclaw-plugin-{name}
    2. Locate claudeclaw_plugin.json in the installed package
    3. Parse manifest (validate with pydantic)
    4. Register each MCP from manifest.mcps via add_mcp()
    5. Copy each skill .md to ~/.claudeclaw/skills/
    6. Append entry to ~/.claudeclaw/config/plugins.yaml
    7. Print confirmation
    """

def list_plugins() -> list[PluginRecord]: ...

def uninstall(name: str) -> None:
    """
    1. Load plugin record from plugins.yaml
    2. Remove each registered MCP via remove_mcp()
    3. Delete copied skill .md files from ~/.claudeclaw/skills/
    4. Remove entry from plugins.yaml
    5. pip uninstall claudeclaw-plugin-{name} -y
    """
```

### 3.5 Manifest Discovery

After `pip install`, the manifest is located using `importlib.resources` or `importlib.metadata`:

```python
import importlib.resources as pkg_resources
import importlib.metadata as metadata

# Strategy: find the installed package directory, then read claudeclaw_plugin.json
dist = metadata.distribution(f"claudeclaw-plugin-{name}")
package_path = Path(dist.locate_file("."))
manifest_path = package_path / "claudeclaw_plugin.json"
```

### 3.6 Plugin Signature Verification (Stub)

Plan 5 includes a stub for signature verification. The `install()` function will call `_verify_signature(name, package_path)` which logs a warning and returns `True` in Plan 5. Full implementation (GPG signature check against the ClaudeClaw public key registry) is deferred to Plan 6 (Security).

### 3.7 Plugin CLI Commands

```bash
claudeclaw plugin install <name>
claudeclaw plugin list
claudeclaw plugin uninstall <name>
```

`plugin list` prints a table: name, version, installed date, MCP count, skill count.

---

## 4. Data Models

```python
# claudeclaw/mcps/config.py
from pydantic import BaseModel
from typing import Literal

class MCPConfig(BaseModel):
    name: str
    command: str
    args: list[str] = []
    env: dict[str, str] = {}
    scope: Literal["global", "agent"] = "agent"


# claudeclaw/plugins/manager.py
from pydantic import BaseModel
from datetime import datetime

class PluginManifest(BaseModel):
    name: str
    version: str
    description: str
    mcps: list[MCPConfig] = []
    skills: list[str] = []
    auth_handler: str | None = None

class PluginRecord(BaseModel):
    name: str
    version: str
    package: str
    installed_at: datetime
    mcps: list[str] = []
    skills: list[str] = []
```

---

## 5. Out of Scope for Plan 5

- **Plugin signature verification** (Plan 6 — Security): full GPG check against central key registry
- **OAuth handler execution**: `auth_handler` field is parsed and stored but the handler class is not instantiated or called in Plan 5
- **Plugin marketplace registry**: Plan 5 installs directly from PyPI using the `claudeclaw-plugin-<name>` naming convention; a central search index is a future concern
- **MCP credential rotation**: MCPs with credential env vars use static values from `mcps.yaml`; dynamic credential injection for MCPs is a future concern

---

## 6. File Map

```
claudeclaw/
├── mcps/
│   ├── __init__.py
│   └── config.py               ← MCPConfig model, load/save/add/remove/resolve
├── plugins/
│   ├── __init__.py
│   └── manager.py              ← PluginManifest, PluginRecord, install/list/uninstall
├── subagent/
│   └── dispatch.py             ← UPDATED: inject MCPs + env var credentials
└── cli.py                      ← UPDATED: mcp and plugin command groups

tests/
├── test_mcp_config.py
├── test_credential_injection.py
├── test_plugin_manager.py
└── test_mcp_cli.py
```
