# ClaudeClaw — Plan 5: Plugins + MCPs

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the MCP configuration layer (mcps.yaml, scope resolution, SDK injection), replace Plan 1's plaintext credential injection with proper environment variable injection, and build the plugin system (install/list/uninstall via PyPI packages with `claudeclaw_plugin.json` manifests).

**Architecture:** A new `claudeclaw/mcps/` module owns MCP config read/write and resolution. A new `claudeclaw/plugins/` module owns plugin lifecycle. `SubagentDispatcher` is updated to inject resolved MCPs and credential env vars into the Claude SDK call. The CLI gains `mcp` and `plugin` command groups.

**Tech Stack:** Python 3.11+, `anthropic` SDK, `click` (CLI), `pydantic` (models), `pyyaml` (config), `pytest` (tests), `subprocess` / `importlib.metadata` (plugin installation)

**Spec reference:** `docs/superpowers/specs/2026-03-25-plan-5-plugins-mcps-spec.md`

---

## File Map

```
claudeclaw/                         ← package root
├── claudeclaw/
│   ├── mcps/
│   │   ├── __init__.py             ← NEW
│   │   └── config.py               ← NEW: MCPConfig model, load/save/add/remove/resolve_mcps
│   ├── plugins/
│   │   ├── __init__.py             ← NEW
│   │   └── manager.py              ← NEW: PluginManifest, PluginRecord, install/list/uninstall
│   ├── subagent/
│   │   └── dispatch.py             ← UPDATED: inject MCPs + env var credentials
│   └── cli.py                      ← UPDATED: mcp add/list/remove + plugin install/list/uninstall
└── tests/
    ├── test_mcp_config.py          ← NEW
    ├── test_credential_injection.py← NEW
    ├── test_plugin_manager.py      ← NEW
    └── test_mcp_cli.py             ← NEW
```

---

## Task 1: MCP Config Module

**Files:**
- Create: `claudeclaw/mcps/__init__.py`
- Create: `claudeclaw/mcps/config.py`
- Create: `tests/test_mcp_config.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_mcp_config.py
import pytest
from pathlib import Path
from claudeclaw.mcps.config import MCPConfig, load_mcps, save_mcps, add_mcp, remove_mcp, resolve_mcps
from claudeclaw.skills.loader import SkillManifest


@pytest.fixture
def mcp_env(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDECLAW_HOME", str(tmp_path))
    (tmp_path / "config").mkdir(parents=True, exist_ok=True)
    return tmp_path


def test_load_empty_returns_empty_list(mcp_env):
    assert load_mcps() == []


def test_add_and_load_mcp(mcp_env):
    cfg = MCPConfig(name="filesystem", command="npx", args=["-y", "@mcp/fs"], scope="global")
    add_mcp(cfg)
    mcps = load_mcps()
    assert len(mcps) == 1
    assert mcps[0].name == "filesystem"
    assert mcps[0].scope == "global"


def test_add_duplicate_raises(mcp_env):
    cfg = MCPConfig(name="filesystem", command="npx", args=[], scope="global")
    add_mcp(cfg)
    with pytest.raises(ValueError, match="already exists"):
        add_mcp(cfg)


def test_remove_mcp(mcp_env):
    add_mcp(MCPConfig(name="postgres", command="npx", args=[], scope="agent"))
    remove_mcp("postgres")
    assert load_mcps() == []


def test_remove_nonexistent_raises(mcp_env):
    with pytest.raises(KeyError):
        remove_mcp("does-not-exist")


def test_resolve_mcps_global_always_included(mcp_env):
    add_mcp(MCPConfig(name="filesystem", command="npx", args=[], scope="global"))
    skill = SkillManifest(name="test", description="t", trigger="on-demand",
                          autonomy="ask", shell_policy="none")
    result = resolve_mcps(skill)
    assert any(m.name == "filesystem" for m in result)


def test_resolve_mcps_agent_only_when_declared(mcp_env):
    add_mcp(MCPConfig(name="postgres", command="npx", args=[], scope="agent"))
    skill_without = SkillManifest(name="test", description="t", trigger="on-demand",
                                  autonomy="ask", shell_policy="none")
    skill_with = SkillManifest(name="test", description="t", trigger="on-demand",
                               autonomy="ask", shell_policy="none", mcps_agent=["postgres"])
    assert not any(m.name == "postgres" for m in resolve_mcps(skill_without))
    assert any(m.name == "postgres" for m in resolve_mcps(skill_with))


def test_resolve_mcps_via_mcps_field(mcp_env):
    add_mcp(MCPConfig(name="gmail", command="npx", args=[], scope="agent"))
    skill = SkillManifest(name="test", description="t", trigger="on-demand",
                          autonomy="ask", shell_policy="none", mcps=["gmail"])
    assert any(m.name == "gmail" for m in resolve_mcps(skill))
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_mcp_config.py -v
```

Expected: `ImportError` — `claudeclaw.mcps.config` does not exist yet.

- [ ] **Step 3: Create `claudeclaw/mcps/__init__.py`**

```python
# claudeclaw/mcps/__init__.py
```

- [ ] **Step 4: Implement `claudeclaw/mcps/config.py`**

```python
# claudeclaw/mcps/config.py
from __future__ import annotations

from pathlib import Path
from typing import Literal, Optional, TYPE_CHECKING

import yaml
from pydantic import BaseModel

from claudeclaw.config.settings import get_settings

if TYPE_CHECKING:
    from claudeclaw.skills.loader import SkillManifest


class MCPConfig(BaseModel):
    name: str
    command: str
    args: list[str] = []
    env: dict[str, str] = {}
    scope: Literal["global", "agent"] = "agent"


def _mcps_path() -> Path:
    return get_settings().config_dir / "mcps.yaml"


def load_mcps() -> list[MCPConfig]:
    path = _mcps_path()
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text()) or {}
    return [MCPConfig(**item) for item in data.get("mcps", [])]


def save_mcps(mcps: list[MCPConfig]) -> None:
    path = _mcps_path()
    path.write_text(yaml.dump({"mcps": [m.model_dump() for m in mcps]}, default_flow_style=False))


def add_mcp(config: MCPConfig) -> None:
    mcps = load_mcps()
    if any(m.name == config.name for m in mcps):
        raise ValueError(f"MCP '{config.name}' already exists. Use remove first.")
    mcps.append(config)
    save_mcps(mcps)


def remove_mcp(name: str) -> None:
    mcps = load_mcps()
    remaining = [m for m in mcps if m.name != name]
    if len(remaining) == len(mcps):
        raise KeyError(f"MCP '{name}' not found.")
    save_mcps(remaining)


def resolve_mcps(skill: "SkillManifest") -> list[MCPConfig]:
    """Return MCPs to inject for this skill: all globals + declared agent MCPs."""
    all_mcps = load_mcps()
    agent_names: set[str] = set((skill.mcps or []) + (skill.mcps_agent or []))
    resolved = []
    for m in all_mcps:
        if m.scope == "global":
            resolved.append(m)
        elif m.scope == "agent" and m.name in agent_names:
            resolved.append(m)
    return resolved
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
pytest tests/test_mcp_config.py -v
```

Expected: all tests PASSED.

- [ ] **Step 6: Commit**

```bash
git add claudeclaw/mcps/__init__.py claudeclaw/mcps/config.py tests/test_mcp_config.py
git commit -m "feat: MCP config module — load/save/add/remove/resolve mcps.yaml"
```

---

## Task 2: Update SubagentDispatcher — Inject MCPs into SDK Call

**Files:**
- Update: `claudeclaw/subagent/dispatch.py`
- Create: `tests/test_mcp_dispatch.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_mcp_dispatch.py
import pytest
from unittest.mock import MagicMock, patch
from claudeclaw.mcps.config import MCPConfig, save_mcps
from claudeclaw.subagent.dispatch import SubagentDispatcher
from claudeclaw.skills.loader import SkillManifest


@pytest.fixture
def dispatcher():
    return SubagentDispatcher()


@pytest.fixture
def skill_with_agent_mcp():
    return SkillManifest(
        name="test-skill",
        description="test",
        trigger="on-demand",
        autonomy="ask",
        shell_policy="none",
        mcps_agent=["postgres"],
        credentials=[],
    )


def test_dispatch_passes_mcp_servers_to_sdk(tmp_path, monkeypatch, dispatcher, skill_with_agent_mcp):
    monkeypatch.setenv("CLAUDECLAW_HOME", str(tmp_path))
    (tmp_path / "config").mkdir(parents=True, exist_ok=True)
    save_mcps([
        MCPConfig(name="filesystem", command="npx", args=["-y", "@mcp/fs"], scope="global"),
        MCPConfig(name="postgres", command="npx", args=["-y", "@mcp/pg"], scope="agent"),
    ])

    mock_client = MagicMock()
    mock_client.messages.create.return_value = MagicMock(content=[MagicMock(text="done")])

    with patch("claudeclaw.subagent.dispatch.anthropic.Anthropic", return_value=mock_client):
        dispatcher.dispatch(skill=skill_with_agent_mcp, user_message="run task", credentials={})

    call_kwargs = mock_client.messages.create.call_args.kwargs
    mcp_servers = call_kwargs.get("mcp_servers") or call_kwargs.get("tools", [])
    # Both filesystem (global) and postgres (declared) should be present
    server_names = [s.get("name") or s.get("command", "") for s in mcp_servers]
    assert len(mcp_servers) == 2


def test_dispatch_excludes_undeclared_agent_mcp(tmp_path, monkeypatch, dispatcher):
    monkeypatch.setenv("CLAUDECLAW_HOME", str(tmp_path))
    (tmp_path / "config").mkdir(parents=True, exist_ok=True)
    save_mcps([
        MCPConfig(name="gmail", command="npx", args=[], scope="agent"),
    ])
    skill = SkillManifest(
        name="bare-skill", description="t", trigger="on-demand",
        autonomy="ask", shell_policy="none", credentials=[],
    )

    mock_client = MagicMock()
    mock_client.messages.create.return_value = MagicMock(content=[MagicMock(text="ok")])

    with patch("claudeclaw.subagent.dispatch.anthropic.Anthropic", return_value=mock_client):
        dispatcher.dispatch(skill=skill, user_message="go", credentials={})

    call_kwargs = mock_client.messages.create.call_args.kwargs
    mcp_servers = call_kwargs.get("mcp_servers", [])
    assert mcp_servers == []
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_mcp_dispatch.py -v
```

Expected: tests fail because `dispatch()` does not yet pass `mcp_servers`.

- [ ] **Step 3: Update `SubagentDispatcher.dispatch()` to inject MCPs**

In `claudeclaw/subagent/dispatch.py`, import `resolve_mcps` and build the `mcp_servers` list:

```python
from claudeclaw.mcps.config import resolve_mcps, MCPConfig

# Inside dispatch():
mcp_configs = resolve_mcps(skill)
mcp_servers = [
    {
        "type": "stdio",
        "command": m.command,
        "args": m.args,
        "env": m.env,
    }
    for m in mcp_configs
]

# Pass to SDK call:
response = client.messages.create(
    ...,
    mcp_servers=mcp_servers if mcp_servers else [],
)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_mcp_dispatch.py -v
```

Expected: all tests PASSED.

- [ ] **Step 5: Run full test suite to verify no regressions**

```bash
pytest tests/ -v
```

Expected: all previously passing tests still pass.

- [ ] **Step 6: Commit**

```bash
git add claudeclaw/subagent/dispatch.py tests/test_mcp_dispatch.py
git commit -m "feat: inject resolved MCPs into Claude SDK subagent call"
```

---

## Task 3: Credential Injection Update — Env Vars Instead of Plaintext

**Files:**
- Update: `claudeclaw/subagent/dispatch.py`
- Create: `tests/test_credential_injection.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_credential_injection.py
import pytest
from unittest.mock import MagicMock, patch
from claudeclaw.subagent.dispatch import SubagentDispatcher, credential_key_to_env_var
from claudeclaw.skills.loader import SkillManifest


def test_key_to_env_var_normalization():
    assert credential_key_to_env_var("erp-user") == "ERP_USER"
    assert credential_key_to_env_var("erp-password") == "ERP_PASSWORD"
    assert credential_key_to_env_var("email-token") == "EMAIL_TOKEN"
    assert credential_key_to_env_var("simple") == "SIMPLE"


def test_credentials_injected_as_env_vars_not_in_prompt(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDECLAW_HOME", str(tmp_path))
    (tmp_path / "config").mkdir(parents=True, exist_ok=True)

    skill = SkillManifest(
        name="erp-skill",
        description="ERP task",
        trigger="on-demand",
        autonomy="autonomous",
        shell_policy="none",
        credentials=["erp-user", "erp-password"],
    )
    credentials = {"erp-user": "alice", "erp-password": "s3cr3t"}

    dispatcher = SubagentDispatcher()
    mock_client = MagicMock()
    mock_client.messages.create.return_value = MagicMock(content=[MagicMock(text="done")])

    with patch("claudeclaw.subagent.dispatch.anthropic.Anthropic", return_value=mock_client):
        dispatcher.dispatch(skill=skill, user_message="run", credentials=credentials)

    call_kwargs = mock_client.messages.create.call_args.kwargs

    # Env vars must be present in the call
    env = call_kwargs.get("env") or {}
    assert env.get("ERP_USER") == "alice"
    assert env.get("ERP_PASSWORD") == "s3cr3t"

    # Secret values must NOT appear in the system prompt
    system_prompt = call_kwargs.get("system", "")
    assert "alice" not in system_prompt
    assert "s3cr3t" not in system_prompt


def test_missing_credential_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDECLAW_HOME", str(tmp_path))
    (tmp_path / "config").mkdir(parents=True, exist_ok=True)

    skill = SkillManifest(
        name="needs-cred",
        description="needs a credential",
        trigger="on-demand",
        autonomy="ask",
        shell_policy="none",
        credentials=["missing-key"],
    )

    dispatcher = SubagentDispatcher()
    with pytest.raises(ValueError, match="missing-key"):
        dispatcher.dispatch(skill=skill, user_message="run", credentials={})
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_credential_injection.py -v
```

Expected: `ImportError` or assertion failures — `credential_key_to_env_var` does not exist yet and credentials may still be in the prompt.

- [ ] **Step 3: Add `credential_key_to_env_var` and update credential injection in `dispatch.py`**

```python
# In claudeclaw/subagent/dispatch.py

def credential_key_to_env_var(key: str) -> str:
    """Normalize a Keyring key name to an environment variable name."""
    return key.upper().replace("-", "_")


# Inside SubagentDispatcher.dispatch():
# Build env dict from credentials — validate all are present
env: dict[str, str] = {}
for key in (skill.credentials or []):
    value = credentials.get(key)
    if value is None:
        raise ValueError(
            f"Credential '{key}' declared in skill '{skill.name}' but not provided. "
            "Ensure it is stored in the credential store."
        )
    env[credential_key_to_env_var(key)] = value

# Remove any plaintext credential injection from _build_system_prompt()
# Pass env to SDK call:
response = client.messages.create(
    ...,
    env=env if env else {},
)
```

Also update `_build_system_prompt()` to remove any credential injection that was added in Plan 1.

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_credential_injection.py -v
```

Expected: all 3 tests PASSED.

- [ ] **Step 5: Run full test suite**

```bash
pytest tests/ -v
```

Expected: all previously passing tests still pass.

- [ ] **Step 6: Commit**

```bash
git add claudeclaw/subagent/dispatch.py tests/test_credential_injection.py
git commit -m "feat: inject credentials as env vars instead of plaintext in system prompt"
```

---

## Task 4: CLI — `mcp` Command Group

**Files:**
- Update: `claudeclaw/cli.py`
- Create: `tests/test_mcp_cli.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_mcp_cli.py
import pytest
from click.testing import CliRunner
from claudeclaw.cli import main


@pytest.fixture
def runner():
    return CliRunner()


def test_mcp_list_empty(runner, tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDECLAW_HOME", str(tmp_path))
    (tmp_path / "config").mkdir(parents=True, exist_ok=True)
    result = runner.invoke(main, ["mcp", "list"])
    assert result.exit_code == 0
    assert "No MCPs" in result.output or result.output.strip() == "" or "name" in result.output.lower()


def test_mcp_add_and_list(runner, tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDECLAW_HOME", str(tmp_path))
    (tmp_path / "config").mkdir(parents=True, exist_ok=True)
    result = runner.invoke(main, [
        "mcp", "add", "filesystem",
        "--command", "npx",
        "--args", "-y", "@mcp/fs",
        "--scope", "global",
    ])
    assert result.exit_code == 0, result.output

    result = runner.invoke(main, ["mcp", "list"])
    assert "filesystem" in result.output
    assert "global" in result.output


def test_mcp_remove(runner, tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDECLAW_HOME", str(tmp_path))
    (tmp_path / "config").mkdir(parents=True, exist_ok=True)
    runner.invoke(main, ["mcp", "add", "postgres", "--command", "npx", "--scope", "agent"])
    result = runner.invoke(main, ["mcp", "remove", "postgres"])
    assert result.exit_code == 0
    result = runner.invoke(main, ["mcp", "list"])
    assert "postgres" not in result.output


def test_mcp_add_duplicate_shows_error(runner, tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDECLAW_HOME", str(tmp_path))
    (tmp_path / "config").mkdir(parents=True, exist_ok=True)
    runner.invoke(main, ["mcp", "add", "filesystem", "--command", "npx", "--scope", "global"])
    result = runner.invoke(main, ["mcp", "add", "filesystem", "--command", "npx", "--scope", "global"])
    assert result.exit_code != 0 or "already exists" in result.output


def test_mcp_remove_nonexistent_shows_error(runner, tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDECLAW_HOME", str(tmp_path))
    (tmp_path / "config").mkdir(parents=True, exist_ok=True)
    result = runner.invoke(main, ["mcp", "remove", "does-not-exist"])
    assert result.exit_code != 0 or "not found" in result.output.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_mcp_cli.py -v
```

Expected: `UsageError` or similar — `mcp` command group does not exist yet.

- [ ] **Step 3: Add `mcp` command group to `claudeclaw/cli.py`**

```python
# In claudeclaw/cli.py — add after existing command groups

import click
from claudeclaw.mcps.config import MCPConfig, load_mcps, add_mcp, remove_mcp


@main.group()
def mcp():
    """Manage MCP server configurations."""
    pass


@mcp.command("add")
@click.argument("name")
@click.option("--command", required=True, help="Executable to launch the MCP server")
@click.option("--args", multiple=True, help="Arguments for the MCP server command")
@click.option("--env", multiple=True, help="Environment variables as KEY=VALUE pairs")
@click.option("--scope", type=click.Choice(["global", "agent"]), default="agent",
              show_default=True, help="global = all subagents; agent = per-skill opt-in")
def mcp_add(name, command, args, env, scope):
    """Register a new MCP server configuration."""
    env_dict = {}
    for item in env:
        if "=" not in item:
            raise click.BadParameter(f"env must be KEY=VALUE, got: {item}")
        k, v = item.split("=", 1)
        env_dict[k] = v
    try:
        add_mcp(MCPConfig(name=name, command=command, args=list(args), env=env_dict, scope=scope))
        click.echo(f"MCP '{name}' registered (scope: {scope}).")
    except ValueError as e:
        raise click.ClickException(str(e))


@mcp.command("list")
def mcp_list():
    """List all configured MCP servers."""
    mcps = load_mcps()
    if not mcps:
        click.echo("No MCPs configured. Use 'claudeclaw mcp add' to register one.")
        return
    click.echo(f"{'NAME':<20} {'SCOPE':<10} {'COMMAND'}")
    click.echo("-" * 50)
    for m in mcps:
        click.echo(f"{m.name:<20} {m.scope:<10} {m.command} {' '.join(m.args)}")


@mcp.command("remove")
@click.argument("name")
def mcp_remove(name):
    """Remove a registered MCP server."""
    try:
        remove_mcp(name)
        click.echo(f"MCP '{name}' removed.")
    except KeyError as e:
        raise click.ClickException(str(e))
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_mcp_cli.py -v
```

Expected: all tests PASSED.

- [ ] **Step 5: Commit**

```bash
git add claudeclaw/cli.py tests/test_mcp_cli.py
git commit -m "feat: CLI mcp add/list/remove commands"
```

---

## Task 5: Plugin Manifest Parser

**Files:**
- Create: `claudeclaw/plugins/__init__.py`
- Create: `claudeclaw/plugins/manager.py` (manifest model + parser only)
- Create: `tests/test_plugin_manager.py` (manifest parsing tests)

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_plugin_manager.py
import json
import pytest
from pathlib import Path
from claudeclaw.plugins.manager import PluginManifest, parse_manifest


@pytest.fixture
def mock_manifest_path(tmp_path):
    data = {
        "name": "gmail",
        "version": "1.0.0",
        "description": "Gmail MCP integration",
        "mcps": [
            {
                "name": "gmail",
                "command": "npx",
                "args": ["-y", "@mcp/gmail"],
                "env": {},
                "scope": "agent",
            }
        ],
        "skills": ["skills/email-monitor.md"],
        "auth_handler": "claudeclaw_plugin_gmail.auth.GmailOAuthHandler",
    }
    path = tmp_path / "claudeclaw_plugin.json"
    path.write_text(json.dumps(data))
    return path


def test_parse_manifest_valid(mock_manifest_path):
    manifest = parse_manifest(mock_manifest_path)
    assert manifest.name == "gmail"
    assert manifest.version == "1.0.0"
    assert len(manifest.mcps) == 1
    assert manifest.mcps[0].name == "gmail"
    assert manifest.skills == ["skills/email-monitor.md"]
    assert manifest.auth_handler == "claudeclaw_plugin_gmail.auth.GmailOAuthHandler"


def test_parse_manifest_minimal(tmp_path):
    data = {"name": "minimal", "version": "0.1.0", "description": "minimal plugin"}
    path = tmp_path / "claudeclaw_plugin.json"
    path.write_text(json.dumps(data))
    manifest = parse_manifest(path)
    assert manifest.name == "minimal"
    assert manifest.mcps == []
    assert manifest.skills == []
    assert manifest.auth_handler is None


def test_parse_manifest_missing_required_field(tmp_path):
    data = {"version": "1.0.0", "description": "missing name"}
    path = tmp_path / "claudeclaw_plugin.json"
    path.write_text(json.dumps(data))
    with pytest.raises(Exception):
        parse_manifest(path)


def test_parse_manifest_file_not_found(tmp_path):
    with pytest.raises(FileNotFoundError):
        parse_manifest(tmp_path / "nonexistent.json")
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_plugin_manager.py -v
```

Expected: `ImportError` — module does not exist yet.

- [ ] **Step 3: Create `claudeclaw/plugins/__init__.py`**

```python
# claudeclaw/plugins/__init__.py
```

- [ ] **Step 4: Implement manifest model and parser in `claudeclaw/plugins/manager.py`**

```python
# claudeclaw/plugins/manager.py
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel

from claudeclaw.config.settings import get_settings
from claudeclaw.mcps.config import MCPConfig


class PluginManifest(BaseModel):
    name: str
    version: str
    description: str
    mcps: list[MCPConfig] = []
    skills: list[str] = []
    auth_handler: Optional[str] = None


class PluginRecord(BaseModel):
    name: str
    version: str
    package: str
    installed_at: datetime
    mcps: list[str] = []
    skills: list[str] = []


def parse_manifest(path: Path) -> PluginManifest:
    """Parse a claudeclaw_plugin.json file into a PluginManifest."""
    if not path.exists():
        raise FileNotFoundError(f"Plugin manifest not found: {path}")
    data = json.loads(path.read_text())
    return PluginManifest(**data)
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
pytest tests/test_plugin_manager.py -v
```

Expected: all 4 tests PASSED.

- [ ] **Step 6: Commit**

```bash
git add claudeclaw/plugins/__init__.py claudeclaw/plugins/manager.py tests/test_plugin_manager.py
git commit -m "feat: plugin manifest model and parser"
```

---

## Task 6: Plugin Manager — Install / List / Uninstall

**Files:**
- Update: `claudeclaw/plugins/manager.py`
- Update: `tests/test_plugin_manager.py`

- [ ] **Step 1: Write the failing tests for install/list/uninstall**

Append to `tests/test_plugin_manager.py`:

```python
# Additional tests — append to tests/test_plugin_manager.py
import importlib.metadata
from unittest.mock import patch, MagicMock
from claudeclaw.plugins.manager import (
    install, list_plugins, uninstall, _plugins_registry_path
)


@pytest.fixture
def plugin_env(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDECLAW_HOME", str(tmp_path))
    (tmp_path / "config").mkdir(parents=True, exist_ok=True)
    (tmp_path / "skills").mkdir(parents=True, exist_ok=True)
    return tmp_path


def _make_mock_dist(tmp_path, manifest_data: dict):
    """Create a mock distribution that returns the tmp_path as package root."""
    pkg_dir = tmp_path / "claudeclaw_plugin_testpkg"
    pkg_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = pkg_dir / "claudeclaw_plugin.json"
    manifest_path.write_text(json.dumps(manifest_data))

    # Minimal skill file
    for skill_rel in manifest_data.get("skills", []):
        skill_path = pkg_dir / skill_rel
        skill_path.parent.mkdir(parents=True, exist_ok=True)
        skill_path.write_text("---\nname: test-email\ndescription: email\ntrigger: on-demand\nautonomy: ask\nshell-policy: none\n---\nDo nothing.")

    mock_dist = MagicMock()
    mock_dist.locate_file.return_value = pkg_dir
    return mock_dist, manifest_path


def test_install_registers_mcps_and_copies_skills(plugin_env):
    manifest_data = {
        "name": "testpkg",
        "version": "1.0.0",
        "description": "test plugin",
        "mcps": [{"name": "testpkg-mcp", "command": "npx", "args": [], "env": {}, "scope": "agent"}],
        "skills": ["skills/email-monitor.md"],
    }
    mock_dist, _ = _make_mock_dist(plugin_env, manifest_data)

    with patch("claudeclaw.plugins.manager.subprocess.run") as mock_run, \
         patch("claudeclaw.plugins.manager.importlib.metadata.distribution", return_value=mock_dist):
        mock_run.return_value = MagicMock(returncode=0)
        install("testpkg")

    from claudeclaw.mcps.config import load_mcps
    mcps = load_mcps()
    assert any(m.name == "testpkg-mcp" for m in mcps)

    skill_dest = plugin_env / "skills" / "email-monitor.md"
    assert skill_dest.exists()

    records = list_plugins()
    assert any(r.name == "testpkg" for r in records)


def test_install_pip_failure_raises(plugin_env):
    with patch("claudeclaw.plugins.manager.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1, stderr="error: package not found")
        with pytest.raises(RuntimeError, match="pip install"):
            install("nonexistent-plugin")


def test_list_plugins_empty(plugin_env):
    assert list_plugins() == []


def test_uninstall_removes_mcps_and_skills(plugin_env):
    manifest_data = {
        "name": "testpkg",
        "version": "1.0.0",
        "description": "test plugin",
        "mcps": [{"name": "testpkg-mcp", "command": "npx", "args": [], "env": {}, "scope": "agent"}],
        "skills": ["skills/email-monitor.md"],
    }
    mock_dist, _ = _make_mock_dist(plugin_env, manifest_data)

    with patch("claudeclaw.plugins.manager.subprocess.run") as mock_run, \
         patch("claudeclaw.plugins.manager.importlib.metadata.distribution", return_value=mock_dist):
        mock_run.return_value = MagicMock(returncode=0)
        install("testpkg")

    with patch("claudeclaw.plugins.manager.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        uninstall("testpkg")

    from claudeclaw.mcps.config import load_mcps
    assert not any(m.name == "testpkg-mcp" for m in load_mcps())
    assert not (plugin_env / "skills" / "email-monitor.md").exists()
    assert list_plugins() == []
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_plugin_manager.py::test_install_registers_mcps_and_copies_skills -v
pytest tests/test_plugin_manager.py::test_uninstall_removes_mcps_and_skills -v
```

Expected: `ImportError` for `install`, `list_plugins`, `uninstall`.

- [ ] **Step 3: Implement install/list/uninstall in `claudeclaw/plugins/manager.py`**

Append to the existing `manager.py`:

```python
# Append to claudeclaw/plugins/manager.py
import importlib.metadata
import shutil
import subprocess
import sys
from datetime import timezone


def _plugins_registry_path() -> Path:
    return get_settings().config_dir / "plugins.yaml"


def _load_registry() -> list[PluginRecord]:
    path = _plugins_registry_path()
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text()) or {}
    return [PluginRecord(**item) for item in data.get("plugins", [])]


def _save_registry(records: list[PluginRecord]) -> None:
    path = _plugins_registry_path()
    path.write_text(
        yaml.dump(
            {"plugins": [r.model_dump(mode="json") for r in records]},
            default_flow_style=False,
        )
    )


def _verify_signature(name: str, package_path: Path) -> bool:
    """Stub: signature verification deferred to Plan 6 (Security)."""
    import warnings
    warnings.warn(
        f"Plugin '{name}' signature not verified (Plan 6). Install at your own risk.",
        stacklevel=3,
    )
    return True


def install(name: str) -> None:
    """Install a ClaudeClaw plugin from PyPI."""
    package_name = f"claudeclaw-plugin-{name}"

    # 1. pip install
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", package_name],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"pip install {package_name} failed:\n{result.stderr}")

    # 2. Locate manifest
    dist = importlib.metadata.distribution(package_name)
    package_path = Path(dist.locate_file("."))
    manifest_path = package_path / "claudeclaw_plugin.json"
    manifest = parse_manifest(manifest_path)

    # 3. Signature check (stub)
    _verify_signature(name, package_path)

    # 4. Register MCPs
    from claudeclaw.mcps.config import add_mcp, load_mcps
    existing_names = {m.name for m in load_mcps()}
    for mcp_cfg in manifest.mcps:
        if mcp_cfg.name not in existing_names:
            add_mcp(mcp_cfg)

    # 5. Copy skill files
    skills_dir = get_settings().skills_dir
    copied_skills: list[str] = []
    for skill_rel in manifest.skills:
        src = package_path / skill_rel
        dest = skills_dir / Path(skill_rel).name
        if src.exists():
            shutil.copy2(src, dest)
            copied_skills.append(Path(skill_rel).stem)

    # 6. Record in registry
    records = _load_registry()
    records.append(PluginRecord(
        name=manifest.name,
        version=manifest.version,
        package=package_name,
        installed_at=datetime.now(tz=timezone.utc),
        mcps=[m.name for m in manifest.mcps],
        skills=copied_skills,
    ))
    _save_registry(records)

    print(f"Plugin '{name}' installed (v{manifest.version}). "
          f"MCPs: {len(manifest.mcps)}, Skills: {len(copied_skills)}.")


def list_plugins() -> list[PluginRecord]:
    """Return all installed plugins."""
    return _load_registry()


def uninstall(name: str) -> None:
    """Uninstall a ClaudeClaw plugin."""
    records = _load_registry()
    record = next((r for r in records if r.name == name), None)
    if record is None:
        raise KeyError(f"Plugin '{name}' is not installed.")

    # 1. Remove MCPs
    from claudeclaw.mcps.config import remove_mcp
    for mcp_name in record.mcps:
        try:
            remove_mcp(mcp_name)
        except KeyError:
            pass

    # 2. Remove skill files
    skills_dir = get_settings().skills_dir
    for skill_stem in record.skills:
        skill_file = skills_dir / f"{skill_stem}.md"
        if skill_file.exists():
            skill_file.unlink()

    # 3. Update registry
    _save_registry([r for r in records if r.name != name])

    # 4. pip uninstall
    subprocess.run(
        [sys.executable, "-m", "pip", "uninstall", record.package, "-y"],
        capture_output=True,
    )

    print(f"Plugin '{name}' uninstalled.")
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_plugin_manager.py -v
```

Expected: all tests PASSED.

- [ ] **Step 5: Commit**

```bash
git add claudeclaw/plugins/manager.py tests/test_plugin_manager.py
git commit -m "feat: plugin manager — install/list/uninstall with MCPs, skills, and registry"
```

---

## Task 7: CLI — `plugin` Command Group

**Files:**
- Update: `claudeclaw/cli.py`
- Create: `tests/test_plugin_cli.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_plugin_cli.py
import pytest
from click.testing import CliRunner
from unittest.mock import patch, MagicMock
from claudeclaw.cli import main
from claudeclaw.plugins.manager import PluginRecord
from datetime import datetime, timezone


@pytest.fixture
def runner():
    return CliRunner()


def test_plugin_install_calls_manager(runner, tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDECLAW_HOME", str(tmp_path))
    (tmp_path / "config").mkdir(parents=True, exist_ok=True)
    with patch("claudeclaw.cli.plugin_install_manager") as mock_install:
        result = runner.invoke(main, ["plugin", "install", "gmail"])
        assert result.exit_code == 0 or "gmail" in result.output
        mock_install.assert_called_once_with("gmail")


def test_plugin_list_empty(runner, tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDECLAW_HOME", str(tmp_path))
    (tmp_path / "config").mkdir(parents=True, exist_ok=True)
    with patch("claudeclaw.cli.list_plugins", return_value=[]):
        result = runner.invoke(main, ["plugin", "list"])
    assert result.exit_code == 0
    assert "No plugins" in result.output or result.output.strip() == "" or "name" in result.output.lower()


def test_plugin_list_shows_installed(runner, tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDECLAW_HOME", str(tmp_path))
    (tmp_path / "config").mkdir(parents=True, exist_ok=True)
    records = [
        PluginRecord(
            name="gmail", version="1.0.0", package="claudeclaw-plugin-gmail",
            installed_at=datetime(2026, 3, 25, tzinfo=timezone.utc), mcps=["gmail"], skills=["email-monitor"],
        )
    ]
    with patch("claudeclaw.cli.list_plugins", return_value=records):
        result = runner.invoke(main, ["plugin", "list"])
    assert "gmail" in result.output
    assert "1.0.0" in result.output


def test_plugin_uninstall_calls_manager(runner, tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDECLAW_HOME", str(tmp_path))
    (tmp_path / "config").mkdir(parents=True, exist_ok=True)
    with patch("claudeclaw.cli.plugin_uninstall_manager") as mock_uninstall:
        result = runner.invoke(main, ["plugin", "uninstall", "gmail"])
        mock_uninstall.assert_called_once_with("gmail")
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_plugin_cli.py -v
```

Expected: failures because `plugin` command group and aliased imports do not exist.

- [ ] **Step 3: Add `plugin` command group to `claudeclaw/cli.py`**

```python
# In claudeclaw/cli.py — add these imports near the top
from claudeclaw.plugins.manager import (
    install as plugin_install_manager,
    list_plugins,
    uninstall as plugin_uninstall_manager,
)


@main.group()
def plugin():
    """Manage ClaudeClaw plugins."""
    pass


@plugin.command("install")
@click.argument("name")
def plugin_install(name):
    """Install a plugin from PyPI (claudeclaw-plugin-<name>)."""
    try:
        plugin_install_manager(name)
    except RuntimeError as e:
        raise click.ClickException(str(e))


@plugin.command("list")
def plugin_list():
    """List installed plugins."""
    records = list_plugins()
    if not records:
        click.echo("No plugins installed. Use 'claudeclaw plugin install <name>'.")
        return
    click.echo(f"{'NAME':<20} {'VERSION':<10} {'MCPS':<6} {'SKILLS':<8} {'INSTALLED'}")
    click.echo("-" * 65)
    for r in records:
        installed = r.installed_at.strftime("%Y-%m-%d") if r.installed_at else "?"
        click.echo(f"{r.name:<20} {r.version:<10} {len(r.mcps):<6} {len(r.skills):<8} {installed}")


@plugin.command("uninstall")
@click.argument("name")
def plugin_uninstall(name):
    """Uninstall a plugin and remove its MCPs and skills."""
    try:
        plugin_uninstall_manager(name)
    except KeyError as e:
        raise click.ClickException(str(e))
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_plugin_cli.py -v
```

Expected: all tests PASSED.

- [ ] **Step 5: Run full test suite**

```bash
pytest tests/ -v
```

Expected: all tests PASSED with no regressions.

- [ ] **Step 6: Commit**

```bash
git add claudeclaw/cli.py tests/test_plugin_cli.py
git commit -m "feat: CLI plugin install/list/uninstall commands"
```

---

## Task 8: Integration Verification — Mock Plugin End-to-End

**Files:**
- Create: `tests/test_integration_plugin_mcps.py`

This task verifies the full chain: install a mock plugin → its MCPs are registered → a skill that declares the MCP receives it at dispatch time. No real `pip install` is performed; the subprocess call is mocked.

- [ ] **Step 1: Write the integration test**

```python
# tests/test_integration_plugin_mcps.py
"""
Integration test: install mock plugin → verify MCP registered → verify MCP injected at dispatch.
"""
import json
import pytest
import shutil
import importlib.metadata
from pathlib import Path
from unittest.mock import patch, MagicMock

from claudeclaw.plugins.manager import install, list_plugins, uninstall
from claudeclaw.mcps.config import load_mcps, save_mcps
from claudeclaw.subagent.dispatch import SubagentDispatcher
from claudeclaw.skills.loader import SkillManifest


@pytest.fixture
def integration_env(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDECLAW_HOME", str(tmp_path))
    (tmp_path / "config").mkdir(parents=True, exist_ok=True)
    (tmp_path / "skills").mkdir(parents=True, exist_ok=True)
    return tmp_path


@pytest.fixture
def mock_plugin_package(tmp_path):
    """Create a fake installed package directory with manifest + skill file."""
    pkg_dir = tmp_path / "claudeclaw_plugin_crm"
    (pkg_dir / "skills").mkdir(parents=True)
    manifest = {
        "name": "crm",
        "version": "2.0.0",
        "description": "CRM integration plugin",
        "mcps": [
            {
                "name": "crm-api",
                "command": "node",
                "args": ["./crm-mcp-server.js"],
                "env": {"CRM_BASE_URL": "https://crm.example.com"},
                "scope": "agent",
            }
        ],
        "skills": ["skills/crm-followup.md"],
    }
    (pkg_dir / "claudeclaw_plugin.json").write_text(json.dumps(manifest))
    (pkg_dir / "skills" / "crm-followup.md").write_text(
        "---\nname: crm-followup\ndescription: CRM follow-up\ntrigger: on-demand\n"
        "autonomy: ask\nshell-policy: none\nmcps_agent: [crm-api]\n---\nFollow up with leads."
    )
    mock_dist = MagicMock()
    mock_dist.locate_file.return_value = pkg_dir
    return mock_dist


def test_full_install_to_dispatch_chain(integration_env, mock_plugin_package):
    """Install mock plugin → MCP registered → skill dispatched with MCP injected."""

    # Step 1: Install mock plugin
    with patch("claudeclaw.plugins.manager.subprocess.run") as mock_run, \
         patch("claudeclaw.plugins.manager.importlib.metadata.distribution",
               return_value=mock_plugin_package):
        mock_run.return_value = MagicMock(returncode=0)
        install("crm")

    # Step 2: Verify MCP registered
    mcps = load_mcps()
    assert any(m.name == "crm-api" for m in mcps), "crm-api MCP should be registered"

    # Step 3: Verify skill copied
    skill_path = integration_env / "skills" / "crm-followup.md"
    assert skill_path.exists(), "crm-followup.md should be copied to skills dir"

    # Step 4: Verify plugin in registry
    records = list_plugins()
    assert any(r.name == "crm" for r in records)

    # Step 5: Dispatch a skill that declares crm-api and verify MCP is injected
    skill = SkillManifest(
        name="crm-followup",
        description="CRM follow-up",
        trigger="on-demand",
        autonomy="ask",
        shell_policy="none",
        mcps_agent=["crm-api"],
        credentials=[],
    )

    mock_client = MagicMock()
    mock_client.messages.create.return_value = MagicMock(content=[MagicMock(text="done")])

    dispatcher = SubagentDispatcher()
    with patch("claudeclaw.subagent.dispatch.anthropic.Anthropic", return_value=mock_client):
        dispatcher.dispatch(skill=skill, user_message="follow up with leads", credentials={})

    call_kwargs = mock_client.messages.create.call_args.kwargs
    mcp_servers = call_kwargs.get("mcp_servers", [])
    assert len(mcp_servers) == 1, f"Expected 1 MCP server, got {len(mcp_servers)}"
    assert mcp_servers[0]["command"] == "node"


def test_uninstall_cleans_up_completely(integration_env, mock_plugin_package):
    """Uninstall plugin → MCP removed, skill removed, registry cleared."""

    with patch("claudeclaw.plugins.manager.subprocess.run") as mock_run, \
         patch("claudeclaw.plugins.manager.importlib.metadata.distribution",
               return_value=mock_plugin_package):
        mock_run.return_value = MagicMock(returncode=0)
        install("crm")

    with patch("claudeclaw.plugins.manager.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        uninstall("crm")

    assert not any(m.name == "crm-api" for m in load_mcps())
    assert not (integration_env / "skills" / "crm-followup.md").exists()
    assert list_plugins() == []
```

- [ ] **Step 2: Run integration tests**

```bash
pytest tests/test_integration_plugin_mcps.py -v
```

Expected: all integration tests PASSED.

- [ ] **Step 3: Run full test suite one final time**

```bash
pytest tests/ -v
```

Expected: all tests PASSED. Zero failures. Zero errors.

- [ ] **Step 4: Final commit**

```bash
git add tests/test_integration_plugin_mcps.py
git commit -m "test: integration — mock plugin install to MCP dispatch chain"
```

---

## Summary

After all 8 tasks, the following is in place:

| Feature | Module | Status |
|---|---|---|
| MCP config read/write | `claudeclaw/mcps/config.py` | Done |
| MCP scope resolution | `claudeclaw/mcps/config.py::resolve_mcps` | Done |
| MCPs injected into SDK call | `claudeclaw/subagent/dispatch.py` | Done |
| Credential env var injection | `claudeclaw/subagent/dispatch.py` | Done |
| Plugin manifest parser | `claudeclaw/plugins/manager.py` | Done |
| Plugin install/list/uninstall | `claudeclaw/plugins/manager.py` | Done |
| CLI: `mcp add/list/remove` | `claudeclaw/cli.py` | Done |
| CLI: `plugin install/list/uninstall` | `claudeclaw/cli.py` | Done |
| Integration verified | `tests/test_integration_plugin_mcps.py` | Done |

**Deferred to Plan 6 (Security):**
- Plugin signature verification (currently a stub that warns and returns `True`)
- OAuth handler execution from `auth_handler` manifest field
