# ClaudeClaw — Plan 6: Security — OpenShell + Hardening

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Harden the ClaudeClaw runtime with a cross-platform sandboxed shell execution layer (OpenShell), enforce `shell-policy` from skill frontmatter in subagent dispatch, add plugin signature verification, replace the fixed PBKDF2 salt with a per-installation random salt (with migration), and wire OAuth token refresh before subagent dispatch.

**Architecture:** `OpenShell` sits between the Claude SDK subagent's bash tool and the OS subprocess. `SubagentDispatcher` injects `OpenShellTool(policy=...)` in place of the default bash tool based on the skill's declared `shell-policy`. A signature verification stub guards `claudeclaw plugin install`. The `_FileBackend` in the keyring module loads or generates a per-installation salt at `~/.claudeclaw/config/keystore-salt` and auto-migrates credentials encrypted with Plan 1's fixed salt. `AuthManager.refresh_token()` is wired into the pre-dispatch path.

**Tech Stack:** Python 3.11+, `anthropic` SDK, `subprocess` (stdlib), `pyyaml` (allowlist config), `cryptography` (PBKDF2 + Fernet), `pytest` (tests)

**Spec reference:** `docs/superpowers/specs/2026-03-25-plan-6-security-spec.md`

---

## File Map

```
claudeclaw/
├── claudeclaw/
│   ├── security/
│   │   ├── __init__.py                  ← new
│   │   ├── openshell.py                 ← new: OpenShell, OpenShellTool, ShellResult
│   │   └── signature.py                 ← new: verify_plugin() stub
│   ├── auth/
│   │   ├── keyring.py                   ← modify: per-installation salt + migration
│   │   └── oauth.py                     ← modify: AuthManager.refresh_token()
│   └── subagent/
│       └── dispatch.py                  ← modify: inject OpenShellTool by policy
└── tests/
    ├── test_openshell.py                ← new
    ├── test_signature.py                ← new
    ├── test_keyring_salt.py             ← new
    └── test_dispatch_openshell.py       ← new
```

Config files (created at runtime, not in the repo):
```
~/.claudeclaw/config/keystore-salt          ← 32-byte hex salt, generated at first run
~/.claudeclaw/config/shell-allowlist.yaml   ← restricted mode command allowlist
```

---

## Task 1: OpenShell Core — `execute()` with Policy Enforcement

**Files:**
- Create: `claudeclaw/security/__init__.py`
- Create: `claudeclaw/security/openshell.py`
- Create: `tests/test_openshell.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_openshell.py
import pytest
from claudeclaw.security.openshell import OpenShell, ShellResult


def test_shell_result_is_dataclass():
    r = ShellResult(stdout="out", stderr="err", exit_code=0, blocked=False)
    assert r.stdout == "out"
    assert r.blocked is False


def test_policy_none_blocks_all_commands():
    shell = OpenShell(policy="none")
    result = shell.execute("ls -la")
    assert result.blocked is True
    assert result.exit_code == 1
    assert result.stdout == ""
    assert "none" in result.stderr


def test_policy_full_executes_command():
    shell = OpenShell(policy="full")
    result = shell.execute("echo hello")
    assert result.blocked is False
    assert result.exit_code == 0
    assert "hello" in result.stdout


def test_policy_full_captures_stderr():
    shell = OpenShell(policy="full")
    result = shell.execute("ls /path/that/definitely/does/not/exist/ever")
    assert result.blocked is False
    assert result.exit_code != 0


def test_policy_full_respects_timeout(monkeypatch):
    shell = OpenShell(policy="full")
    result = shell.execute("sleep 10", timeout=1)
    assert result.blocked is False
    assert result.exit_code == 124
    assert "timed out" in result.stderr.lower()


def test_invalid_policy_raises():
    with pytest.raises(ValueError, match="policy"):
        OpenShell(policy="unknown-policy")
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_openshell.py -v
```

Expected: `ImportError` — module does not exist yet.

- [ ] **Step 3: Implement `OpenShell` and `ShellResult`**

```python
# claudeclaw/security/__init__.py
# (empty)
```

```python
# claudeclaw/security/openshell.py
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from typing import Optional

VALID_POLICIES = {"none", "read-only", "restricted", "full"}

READ_ONLY_COMMANDS = {
    "ls", "cat", "head", "tail", "find", "grep", "rg", "awk", "sed",
    "echo", "pwd", "whoami", "wc", "sort", "uniq", "cut", "diff", "stat",
    "file", "which", "type", "env", "printenv", "date", "du", "df",
    "less", "more", "strings", "hexdump", "xxd",
}


@dataclass
class ShellResult:
    stdout: str
    stderr: str
    exit_code: int
    blocked: bool


class OpenShell:
    """
    Cross-platform sandboxed shell execution layer.
    Compatible with OpenClaw and NemoClaw — they share this interface.
    """

    def __init__(self, policy: str):
        if policy not in VALID_POLICIES:
            raise ValueError(
                f"Invalid shell policy '{policy}'. Must be one of {VALID_POLICIES}"
            )
        self._policy = policy

    def execute(self, command: str, timeout: int = 30) -> ShellResult:
        if self._policy == "none":
            return ShellResult(
                stdout="",
                stderr=f"Shell access denied by policy 'none'",
                exit_code=1,
                blocked=True,
            )

        if self._policy == "read-only":
            if not self._is_read_only(command):
                return ShellResult(
                    stdout="",
                    stderr=f"Command blocked by read-only policy: '{command}'",
                    exit_code=1,
                    blocked=True,
                )

        if self._policy == "restricted":
            if not self._is_restricted_allowed(command):
                return ShellResult(
                    stdout="",
                    stderr=f"Command blocked by restricted policy: '{command}'",
                    exit_code=1,
                    blocked=True,
                )

        return self._run(command, timeout)

    def _is_read_only(self, command: str) -> bool:
        """Return True only if the primary command token is in the read-only allowlist."""
        token = command.strip().split()[0] if command.strip() else ""
        return token in READ_ONLY_COMMANDS

    def _is_restricted_allowed(self, command: str) -> bool:
        """Return True if the primary command token is in the per-installation allowlist."""
        import os
        import yaml
        from pathlib import Path

        home = Path(os.environ.get("CLAUDECLAW_HOME", Path.home() / ".claudeclaw"))
        allowlist_path = home / "config" / "shell-allowlist.yaml"

        if not allowlist_path.exists():
            return False  # fail safe: reject all if no allowlist configured

        try:
            config = yaml.safe_load(allowlist_path.read_text()) or {}
        except Exception:
            return False

        allowed = set(config.get("allowed_commands", []))
        token = command.strip().split()[0] if command.strip() else ""
        return token in allowed

    def _run(self, command: str, timeout: int) -> ShellResult:
        import os
        import platform

        env = None

        if self._policy == "restricted" and platform.system() != "Windows":
            import yaml
            from pathlib import Path
            home = Path(os.environ.get("CLAUDECLAW_HOME", Path.home() / ".claudeclaw"))
            allowlist_path = home / "config" / "shell-allowlist.yaml"
            allowed_paths = "/usr/bin:/bin"
            if allowlist_path.exists():
                try:
                    cfg = yaml.safe_load(allowlist_path.read_text()) or {}
                    allowed_paths = cfg.get("allowed_paths", allowed_paths)
                except Exception:
                    pass
            env = os.environ.copy()
            env["PATH"] = allowed_paths

        if self._policy == "restricted" and platform.system() == "Windows":
            command = f'powershell.exe -ExecutionPolicy Restricted -Command "{command}"'

        try:
            proc = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=env,
            )
            return ShellResult(
                stdout=proc.stdout,
                stderr=proc.stderr,
                exit_code=proc.returncode,
                blocked=False,
            )
        except subprocess.TimeoutExpired:
            return ShellResult(
                stdout="",
                stderr=f"Command timed out after {timeout}s",
                exit_code=124,
                blocked=False,
            )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_openshell.py -v
```

Expected: 6 PASSED.

- [ ] **Step 5: Commit**

```bash
git add claudeclaw/security/__init__.py claudeclaw/security/openshell.py tests/test_openshell.py
git commit -m "feat(security): OpenShell — sandboxed shell execution with none/read-only/restricted/full policies"
```

---

## Task 2: Read-Only Command Detection

**Files:**
- Modify: `tests/test_openshell.py` (extend with read-only tests)

- [ ] **Step 1: Write the failing tests**

```python
# Append to tests/test_openshell.py

def test_read_only_allows_ls():
    shell = OpenShell(policy="read-only")
    result = shell.execute("ls /tmp")
    assert result.blocked is False


def test_read_only_allows_cat(tmp_path):
    f = tmp_path / "hello.txt"
    f.write_text("world")
    shell = OpenShell(policy="read-only")
    result = shell.execute(f"cat {f}")
    assert result.blocked is False
    assert "world" in result.stdout


def test_read_only_blocks_rm():
    shell = OpenShell(policy="read-only")
    result = shell.execute("rm -rf /tmp/something")
    assert result.blocked is True
    assert result.exit_code == 1


def test_read_only_blocks_python():
    shell = OpenShell(policy="read-only")
    result = shell.execute("python -c 'print(1)'")
    assert result.blocked is True


def test_read_only_blocks_touch():
    shell = OpenShell(policy="read-only")
    result = shell.execute("touch /tmp/testfile")
    assert result.blocked is True


def test_read_only_blocks_mkdir():
    shell = OpenShell(policy="read-only")
    result = shell.execute("mkdir /tmp/newdir")
    assert result.blocked is True


def test_read_only_allows_grep():
    shell = OpenShell(policy="read-only")
    result = shell.execute("grep -r pattern /tmp")
    # grep may find nothing, but it should not be blocked
    assert result.blocked is False


def test_read_only_empty_command_blocked():
    shell = OpenShell(policy="read-only")
    result = shell.execute("")
    assert result.blocked is True
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_openshell.py -v -k "read_only"
```

Expected: Most tests pass already from Task 1's implementation, but `test_read_only_empty_command_blocked` fails — `_is_read_only("")` returns `False` but empty string should be blocked.

- [ ] **Step 3: Fix edge case for empty commands in `_is_read_only`**

The `_is_read_only` method already returns `False` for empty token (which becomes `""`). Since `""` is not in `READ_ONLY_COMMANDS`, the method returns `False` — blocking the empty command. Verify this is already correct in the implementation from Task 1. If not, ensure that `token = ""` is not in the allowlist.

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_openshell.py -v -k "read_only"
```

Expected: 8 PASSED.

- [ ] **Step 5: Commit**

```bash
git add tests/test_openshell.py
git commit -m "test(security): extend OpenShell tests for read-only allowlist coverage"
```

---

## Task 3: Restricted Mode — Configurable Allowlist from `shell-allowlist.yaml`

**Files:**
- Modify: `tests/test_openshell.py` (extend with restricted mode tests)

- [ ] **Step 1: Write the failing tests**

```python
# Append to tests/test_openshell.py
import os


def test_restricted_no_allowlist_file_blocks_all(tmp_path, monkeypatch):
    """Without a shell-allowlist.yaml, restricted mode rejects everything."""
    monkeypatch.setenv("CLAUDECLAW_HOME", str(tmp_path))
    (tmp_path / "config").mkdir(parents=True, exist_ok=True)
    shell = OpenShell(policy="restricted")
    result = shell.execute("ls /tmp")
    assert result.blocked is True


def test_restricted_with_allowlist_permits_listed_command(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDECLAW_HOME", str(tmp_path))
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "shell-allowlist.yaml").write_text(
        "allowed_commands:\n  - ls\n  - echo\nallowed_paths: /usr/bin:/bin\n"
    )
    shell = OpenShell(policy="restricted")
    result = shell.execute("echo hello")
    assert result.blocked is False
    assert "hello" in result.stdout


def test_restricted_with_allowlist_blocks_unlisted_command(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDECLAW_HOME", str(tmp_path))
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "shell-allowlist.yaml").write_text(
        "allowed_commands:\n  - ls\nallowed_paths: /usr/bin:/bin\n"
    )
    shell = OpenShell(policy="restricted")
    result = shell.execute("python -c 'import os; os.system(\"rm -rf /\")'")
    assert result.blocked is True


def test_restricted_allowlist_corrupt_yaml_blocks_all(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDECLAW_HOME", str(tmp_path))
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "shell-allowlist.yaml").write_text("{{{{invalid yaml")
    shell = OpenShell(policy="restricted")
    result = shell.execute("ls")
    assert result.blocked is True
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_openshell.py -v -k "restricted"
```

Expected: Tests fail because `_is_restricted_allowed` uses a hardcoded path before `CLAUDECLAW_HOME` monkeypatching takes effect at module import time, or the path resolution doesn't pick up the env var correctly.

- [ ] **Step 3: Verify `_is_restricted_allowed` reads `CLAUDECLAW_HOME` at call time**

Confirm that `os.environ.get("CLAUDECLAW_HOME", ...)` is called inside `_is_restricted_allowed` at each invocation (not cached at class init). The implementation from Task 1 already does this. If tests still fail, check that `tmp_path / "config"` exists before the test writes the allowlist.

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_openshell.py -v -k "restricted"
```

Expected: 4 PASSED.

- [ ] **Step 5: Commit**

```bash
git add tests/test_openshell.py
git commit -m "test(security): restricted mode allowlist — no file blocks all, listed commands pass"
```

---

## Task 4: SubagentDispatcher Update — Inject `OpenShellTool` by Policy

**Files:**
- Create: `claudeclaw/security/openshell.py` — extend with `OpenShellTool` class (already partially present; add the wrapper)
- Modify: `claudeclaw/subagent/dispatch.py` — add `_build_tools()` integration
- Create: `tests/test_dispatch_openshell.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_dispatch_openshell.py
import pytest
from unittest.mock import MagicMock, patch
from claudeclaw.security.openshell import OpenShellTool, ShellResult


def test_openshell_tool_returns_stdout_on_success():
    tool = OpenShellTool(policy="full")
    with patch.object(tool._shell, "execute") as mock_exec:
        mock_exec.return_value = ShellResult(
            stdout="hello\n", stderr="", exit_code=0, blocked=False
        )
        result = tool("echo hello")
    assert result == "hello\n"


def test_openshell_tool_returns_blocked_message_when_blocked():
    tool = OpenShellTool(policy="none")
    result = tool("ls -la")
    assert "[BLOCKED]" in result


def test_openshell_tool_returns_exit_code_on_failure():
    tool = OpenShellTool(policy="full")
    with patch.object(tool._shell, "execute") as mock_exec:
        mock_exec.return_value = ShellResult(
            stdout="", stderr="No such file", exit_code=2, blocked=False
        )
        result = tool("cat /nonexistent")
    assert "[EXIT 2]" in result
    assert "No such file" in result


def test_dispatcher_builds_no_bash_tool_for_none_policy():
    from claudeclaw.subagent.dispatch import SubagentDispatcher
    from claudeclaw.skills.loader import SkillManifest

    dispatcher = SubagentDispatcher.__new__(SubagentDispatcher)
    skill = MagicMock(spec=SkillManifest)
    skill.shell_policy = "none"
    skill.tools = []
    skill.mcps = []
    skill.mcps_agent = []

    tools = dispatcher._build_tools(skill)
    tool_types = [type(t).__name__ for t in tools]
    assert "OpenShellTool" not in tool_types


def test_dispatcher_injects_openshell_tool_for_read_only_policy():
    from claudeclaw.subagent.dispatch import SubagentDispatcher
    from claudeclaw.skills.loader import SkillManifest
    from claudeclaw.security.openshell import OpenShellTool

    dispatcher = SubagentDispatcher.__new__(SubagentDispatcher)
    skill = MagicMock(spec=SkillManifest)
    skill.shell_policy = "read-only"
    skill.tools = []
    skill.mcps = []
    skill.mcps_agent = []

    tools = dispatcher._build_tools(skill)
    shell_tools = [t for t in tools if isinstance(t, OpenShellTool)]
    assert len(shell_tools) == 1
    assert shell_tools[0]._shell._policy == "read-only"


def test_dispatcher_injects_openshell_tool_for_restricted_policy():
    from claudeclaw.subagent.dispatch import SubagentDispatcher
    from claudeclaw.security.openshell import OpenShellTool

    dispatcher = SubagentDispatcher.__new__(SubagentDispatcher)
    skill = MagicMock()
    skill.shell_policy = "restricted"
    skill.tools = []
    skill.mcps = []
    skill.mcps_agent = []

    tools = dispatcher._build_tools(skill)
    shell_tools = [t for t in tools if isinstance(t, OpenShellTool)]
    assert len(shell_tools) == 1
    assert shell_tools[0]._shell._policy == "restricted"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_dispatch_openshell.py -v
```

Expected: `ImportError` for `OpenShellTool` (not yet defined) and `AttributeError` for `_build_tools` (not yet on dispatcher).

- [ ] **Step 3: Add `OpenShellTool` to `openshell.py`**

Append to `claudeclaw/security/openshell.py`:

```python
class OpenShellTool:
    """
    Claude SDK-compatible tool that wraps OpenShell.
    Presents as a bash-compatible tool to the subagent.
    Inject this in place of the default bash tool via SubagentDispatcher.
    """

    def __init__(self, policy: str):
        self._shell = OpenShell(policy=policy)

    def __call__(self, command: str) -> str:
        result = self._shell.execute(command)
        if result.blocked:
            return f"[BLOCKED] {result.stderr}"
        if result.exit_code != 0:
            return f"[EXIT {result.exit_code}]\n{result.stderr}"
        return result.stdout
```

- [ ] **Step 4: Add `_build_tools()` to `SubagentDispatcher` in `dispatch.py`**

In `claudeclaw/subagent/dispatch.py`, add or modify `_build_tools()`:

```python
from claudeclaw.security.openshell import OpenShellTool


def _build_tools(self, skill) -> list:
    """Build the tool list for a subagent invocation based on skill frontmatter."""
    tools = []

    # ... existing tool assembly for skill.tools, skill.mcps, skill.mcps_agent ...

    policy = getattr(skill, "shell_policy", "none")
    if policy != "none":
        tools.append(OpenShellTool(policy=policy))
    # For policy == "none": no shell tool injected at all

    return tools
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
pytest tests/test_dispatch_openshell.py -v
```

Expected: 6 PASSED.

- [ ] **Step 6: Commit**

```bash
git add claudeclaw/security/openshell.py claudeclaw/subagent/dispatch.py tests/test_dispatch_openshell.py
git commit -m "feat(security): OpenShellTool + SubagentDispatcher injects shell tool by shell-policy"
```

---

## Task 5: Plugin Signature Stub — `verify_plugin()` with Trusted Publisher Check

**Files:**
- Create: `claudeclaw/security/signature.py`
- Create: `tests/test_signature.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_signature.py
import pytest
from claudeclaw.security.signature import verify_plugin


def test_trusted_plugin_returns_true():
    assert verify_plugin("claudeclaw-plugin-gmail", "1.0.0") is True


def test_trusted_plugin_telegram_returns_true():
    assert verify_plugin("claudeclaw-plugin-telegram", "0.2.1") is True


def test_unknown_plugin_returns_false():
    assert verify_plugin("some-random-package", "1.0.0") is False


def test_unknown_plugin_with_claudeclaw_prefix_returns_false():
    # A package named claudeclaw-plugin-xyz that isn't in the trusted list
    assert verify_plugin("claudeclaw-plugin-xyz-unknown", "1.0.0") is False


def test_empty_package_name_returns_false():
    assert verify_plugin("", "1.0.0") is False


def test_version_does_not_affect_trusted_check():
    # Plan 6 stub: version is not used in the check
    assert verify_plugin("claudeclaw-plugin-gmail", "999.0.0") is True
    assert verify_plugin("claudeclaw-plugin-gmail", "") is True
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_signature.py -v
```

Expected: `ImportError` — module does not exist yet.

- [ ] **Step 3: Implement `verify_plugin()`**

```python
# claudeclaw/security/signature.py
"""
Plugin signature verification for ClaudeClaw.

Plan 6 stub: checks against a hardcoded list of trusted publisher packages.
Full PKI infrastructure is out of scope for Plan 6.
"""
import logging

logger = logging.getLogger(__name__)

TRUSTED_PUBLISHERS: set[str] = {
    "claudeclaw-plugin-gmail",
    "claudeclaw-plugin-telegram",
    "claudeclaw-plugin-slack",
    "claudeclaw-plugin-postgres",
    "claudeclaw-plugin-whatsapp",
}


def verify_plugin(package_name: str, version: str) -> bool:
    """
    Verify that a plugin package is from a trusted publisher.

    Plan 6 stub: checks against the hardcoded TRUSTED_PUBLISHERS set.
    version parameter is accepted for interface compatibility but not used in this stub.

    Returns True if the package is trusted, False otherwise.
    Logs a warning for untrusted packages.
    """
    if not package_name:
        logger.warning("verify_plugin called with empty package name — rejecting")
        return False

    if package_name in TRUSTED_PUBLISHERS:
        logger.debug("Plugin '%s' verified as trusted publisher", package_name)
        return True

    logger.warning(
        "Plugin '%s' is NOT in the ClaudeClaw trusted publisher list. "
        "Install with caution.",
        package_name,
    )
    return False
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_signature.py -v
```

Expected: 6 PASSED.

- [ ] **Step 5: Wire `verify_plugin()` into the `plugin install` CLI command**

In `claudeclaw/cli.py`, locate the `plugin install` command and add the verification step:

```python
from claudeclaw.security.signature import verify_plugin
import click

@plugin.command("install")
@click.argument("name")
def plugin_install(name: str):
    """Install a ClaudeClaw plugin from the marketplace."""
    package_name = name if name.startswith("claudeclaw-plugin-") else f"claudeclaw-plugin-{name}"

    trusted = verify_plugin(package_name, "latest")
    if not trusted:
        click.echo(
            f"WARNING: Package '{package_name}' is not in the ClaudeClaw trusted publisher list.",
            err=True,
        )
        confirmed = click.confirm("Install anyway?", default=False)
        if not confirmed:
            click.echo("Installation aborted.")
            return

    # ... existing pip install logic ...
```

- [ ] **Step 6: Commit**

```bash
git add claudeclaw/security/signature.py claudeclaw/cli.py tests/test_signature.py
git commit -m "feat(security): plugin signature verification stub with trusted publisher list"
```

---

## Task 6: PBKDF2 Per-Installation Salt — Generate, Store, Migrate

**Files:**
- Modify: `claudeclaw/auth/keyring.py`
- Create: `tests/test_keyring_salt.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_keyring_salt.py
import pytest
from pathlib import Path
from claudeclaw.auth.keyring import _load_or_create_salt, CredentialStore, CredentialMigrationError


def test_creates_salt_file_on_first_run(tmp_path):
    salt_path = tmp_path / "keystore-salt"
    assert not salt_path.exists()
    salt = _load_or_create_salt(tmp_path)
    assert salt_path.exists()
    assert len(salt) == 32


def test_loads_existing_salt_file(tmp_path):
    salt_path = tmp_path / "keystore-salt"
    original = b"\xde\xad" * 16  # 32 bytes
    salt_path.write_text(original.hex())
    loaded = _load_or_create_salt(tmp_path)
    assert loaded == original


def test_salt_is_random_across_two_installations(tmp_path):
    dir_a = tmp_path / "a"
    dir_b = tmp_path / "b"
    dir_a.mkdir()
    dir_b.mkdir()
    salt_a = _load_or_create_salt(dir_a)
    salt_b = _load_or_create_salt(dir_b)
    assert salt_a != salt_b


def test_credential_store_file_backend_uses_per_installation_salt(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDECLAW_HOME", str(tmp_path))
    store = CredentialStore(backend="file", master_password="test-secret")
    store.set("my-key", "my-value")
    salt_path = tmp_path / "config" / "keystore-salt"
    assert salt_path.exists()


def test_migration_re_encrypts_with_new_salt(tmp_path, monkeypatch):
    """
    Simulate a Plan 1 credential store (fixed salt, no keystore-salt file).
    After loading with Plan 6 CredentialStore, the store must be re-encrypted
    and a keystore-salt file must exist.
    """
    import json, base64
    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    from cryptography.hazmat.primitives import hashes

    monkeypatch.setenv("CLAUDECLAW_HOME", str(tmp_path))
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True)

    # Create old-style credentials.enc with fixed salt
    OLD_SALT = b"claudeclaw-salt-v1"
    master_pw = "migrate-me"
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=OLD_SALT, iterations=480_000)
    old_key = base64.urlsafe_b64encode(kdf.derive(master_pw.encode()))
    old_fernet = Fernet(old_key)
    old_data = {"secret-key": "secret-value"}
    (config_dir / "credentials.enc").write_bytes(
        old_fernet.encrypt(json.dumps(old_data).encode())
    )

    # No keystore-salt exists yet
    assert not (config_dir / "keystore-salt").exists()

    # Load with Plan 6 CredentialStore — should auto-migrate
    store = CredentialStore(backend="file", master_password=master_pw)

    # Migration must have written keystore-salt
    assert (config_dir / "keystore-salt").exists()

    # The value must still be retrievable
    assert store.get("secret-key") == "secret-value"


def test_migration_fails_gracefully_on_wrong_password(tmp_path, monkeypatch):
    import json, base64
    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    from cryptography.hazmat.primitives import hashes

    monkeypatch.setenv("CLAUDECLAW_HOME", str(tmp_path))
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True)

    OLD_SALT = b"claudeclaw-salt-v1"
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=OLD_SALT, iterations=480_000)
    old_key = base64.urlsafe_b64encode(kdf.derive(b"correct-password"))
    old_fernet = Fernet(old_key)
    (config_dir / "credentials.enc").write_bytes(
        old_fernet.encrypt(b'{"k": "v"}')
    )

    with pytest.raises(CredentialMigrationError):
        CredentialStore(backend="file", master_password="wrong-password")
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_keyring_salt.py -v
```

Expected: `ImportError` for `_load_or_create_salt` and `CredentialMigrationError`.

- [ ] **Step 3: Implement per-installation salt in `keyring.py`**

In `claudeclaw/auth/keyring.py`, make the following changes:

1. Remove the hardcoded `SALT = b"claudeclaw-salt-v1"` constant.
2. Add `_load_or_create_salt()` function:

```python
import os

SALT_FILE_NAME = "keystore-salt"


class CredentialMigrationError(Exception):
    pass


def _load_or_create_salt(config_dir: Path) -> bytes:
    salt_path = config_dir / SALT_FILE_NAME
    if salt_path.exists():
        return bytes.fromhex(salt_path.read_text().strip())
    salt = os.urandom(32)
    salt_path.write_text(salt.hex())
    return salt
```

3. Change `_derive_key` signature to accept `salt` as a parameter:

```python
def _derive_key(master_password: str, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=480_000)
    return base64.urlsafe_b64encode(kdf.derive(master_password.encode()))
```

4. Update `_FileBackend.__init__` to load or create the salt and call migration if needed:

```python
class _FileBackend:
    def __init__(self, path: Path, master_password: str):
        self._path = path
        config_dir = path.parent
        self._migrate_if_needed(config_dir, master_password)
        salt = _load_or_create_salt(config_dir)
        self._fernet = Fernet(_derive_key(master_password, salt))

    def _migrate_if_needed(self, config_dir: Path, master_password: str):
        cred_file = config_dir / "credentials.enc"
        salt_file = config_dir / SALT_FILE_NAME
        if not (cred_file.exists() and not salt_file.exists()):
            return  # nothing to migrate

        OLD_SALT = b"claudeclaw-salt-v1"
        try:
            old_key = base64.urlsafe_b64encode(
                PBKDF2HMAC(
                    algorithm=hashes.SHA256(), length=32,
                    salt=OLD_SALT, iterations=480_000
                ).derive(master_password.encode())
            )
            old_fernet = Fernet(old_key)
            data = json.loads(old_fernet.decrypt(cred_file.read_bytes()))
        except Exception as e:
            raise CredentialMigrationError(
                f"Found credentials.enc without keystore-salt. "
                f"Migration from fixed salt failed — check your master password. ({e})"
            ) from e

        new_salt = os.urandom(32)
        salt_file.write_text(new_salt.hex())
        new_key = _derive_key(master_password, new_salt)
        new_fernet = Fernet(new_key)
        cred_file.write_bytes(new_fernet.encrypt(json.dumps(data).encode()))
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_keyring_salt.py tests/test_keyring.py -v
```

Expected: All tests PASSED (both new salt tests and existing Plan 1 keyring tests).

- [ ] **Step 5: Commit**

```bash
git add claudeclaw/auth/keyring.py tests/test_keyring_salt.py
git commit -m "feat(security): per-installation PBKDF2 salt with migration from Plan 1 fixed salt"
```

---

## Task 7: Integration Verification — `shell-policy: none` Cannot Execute Shell Commands

**Files:**
- Create: `tests/test_integration_shell_policy.py`

This task verifies the full chain: a skill with `shell-policy: none` dispatched via `SubagentDispatcher` results in zero shell tool availability, and any OpenShell direct call with `policy="none"` is blocked without subprocess execution.

- [ ] **Step 1: Write the integration tests**

```python
# tests/test_integration_shell_policy.py
"""
Integration tests verifying that shell-policy enforcement works end-to-end:
- OpenShell with policy=none never calls subprocess
- SubagentDispatcher builds no bash tool for shell-policy: none skills
- OpenShell with policy=read-only allows safe reads, blocks writes
- OpenShellTool with policy=none returns [BLOCKED] for any input
"""
import pytest
from unittest.mock import patch, MagicMock
from claudeclaw.security.openshell import OpenShell, OpenShellTool, ShellResult


def test_none_policy_never_reaches_subprocess():
    """subprocess.run must never be called when policy is none."""
    shell = OpenShell(policy="none")
    with patch("subprocess.run") as mock_run:
        result = shell.execute("ls -la")
    mock_run.assert_not_called()
    assert result.blocked is True


def test_none_policy_tool_wrapper_returns_blocked():
    tool = OpenShellTool(policy="none")
    output = tool("rm -rf /")
    assert "[BLOCKED]" in output


def test_read_only_policy_never_reaches_subprocess_for_blocked_command():
    shell = OpenShell(policy="read-only")
    with patch("subprocess.run") as mock_run:
        result = shell.execute("rm -rf /")
    mock_run.assert_not_called()
    assert result.blocked is True


def test_dispatcher_tools_for_none_policy_skill_excludes_shell_tool():
    from claudeclaw.subagent.dispatch import SubagentDispatcher
    from claudeclaw.security.openshell import OpenShellTool

    dispatcher = SubagentDispatcher.__new__(SubagentDispatcher)
    skill = MagicMock()
    skill.shell_policy = "none"
    skill.tools = []
    skill.mcps = []
    skill.mcps_agent = []

    tools = dispatcher._build_tools(skill)
    assert not any(isinstance(t, OpenShellTool) for t in tools)


def test_dispatcher_tools_for_full_policy_skill_includes_shell_tool():
    from claudeclaw.subagent.dispatch import SubagentDispatcher
    from claudeclaw.security.openshell import OpenShellTool

    dispatcher = SubagentDispatcher.__new__(SubagentDispatcher)
    skill = MagicMock()
    skill.shell_policy = "full"
    skill.tools = []
    skill.mcps = []
    skill.mcps_agent = []

    tools = dispatcher._build_tools(skill)
    assert any(isinstance(t, OpenShellTool) for t in tools)


def test_all_policies_return_shell_result_instances():
    """Every call to execute() must return a ShellResult regardless of policy."""
    for policy in ["none", "read-only", "full"]:
        shell = OpenShell(policy=policy)
        result = shell.execute("echo test")
        assert isinstance(result, ShellResult), f"policy={policy} did not return ShellResult"
```

- [ ] **Step 2: Run all tests to verify they fail**

```bash
pytest tests/test_integration_shell_policy.py -v
```

Expected: Most pass already from previous tasks. Any that fail indicate a gap in the integration.

- [ ] **Step 3: Run the full test suite to confirm no regressions**

```bash
pytest tests/ -v
```

Expected: All tests pass. No regressions from Plan 1's test suite.

- [ ] **Step 4: Commit**

```bash
git add tests/test_integration_shell_policy.py
git commit -m "test(security): integration tests — shell-policy:none cannot execute shell commands"
```

---

## Task 8: OAuth Token Refresh Stub

**Files:**
- Modify: `claudeclaw/auth/oauth.py`
- Modify: `claudeclaw/subagent/dispatch.py`

- [ ] **Step 1: Write the failing tests**

```python
# Append to tests/test_keyring.py or create tests/test_oauth_refresh.py

# tests/test_oauth_refresh.py
import pytest
from unittest.mock import MagicMock, patch
from claudeclaw.auth.oauth import AuthManager


def test_is_token_expiring_returns_true_when_near_expiry():
    auth = AuthManager.__new__(AuthManager)
    auth._token_expiry = __import__("time").time() + 60  # 60 seconds from now
    assert auth.is_token_expiring(within_seconds=300) is True


def test_is_token_expiring_returns_false_when_not_near_expiry():
    auth = AuthManager.__new__(AuthManager)
    auth._token_expiry = __import__("time").time() + 3600  # 1 hour from now
    assert auth.is_token_expiring(within_seconds=300) is False


def test_is_token_expiring_returns_true_when_no_expiry_set():
    """If no expiry is known, treat as expiring to force refresh."""
    auth = AuthManager.__new__(AuthManager)
    auth._token_expiry = None
    assert auth.is_token_expiring(within_seconds=300) is True


def test_refresh_token_returns_false_stub():
    """Plan 6 stub: refresh_token always returns False (endpoint not implemented)."""
    auth = AuthManager.__new__(AuthManager)
    auth._token_expiry = None
    result = auth.refresh_token()
    assert result is False
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_oauth_refresh.py -v
```

Expected: `AttributeError` — `is_token_expiring` and `refresh_token` do not exist yet.

- [ ] **Step 3: Add `is_token_expiring()` and `refresh_token()` to `AuthManager`**

In `claudeclaw/auth/oauth.py`, add to the `AuthManager` class:

```python
import time

class AuthManager:
    # ... existing methods ...

    def is_token_expiring(self, within_seconds: int = 300) -> bool:
        """Return True if the stored token expires within `within_seconds`."""
        expiry = getattr(self, "_token_expiry", None)
        if expiry is None:
            return True  # unknown expiry — assume expiring
        return (expiry - time.time()) < within_seconds

    def refresh_token(self) -> bool:
        """
        Attempt to refresh the OAuth token using the stored refresh token.
        Returns True on success, False on failure.

        Plan 6 stub: refresh endpoint not yet implemented.
        Same implementation status as Plan 1's _exchange_code.
        """
        # TODO: implement refresh endpoint call in a future plan
        return False
```

- [ ] **Step 4: Wire token refresh into `SubagentDispatcher.dispatch()`**

In `claudeclaw/subagent/dispatch.py`, add at the start of the dispatch method:

```python
from claudeclaw.auth.oauth import AuthManager, AuthError

# Inside dispatch():
if hasattr(self, "_auth") and self._auth is not None:
    if self._auth.is_token_expiring():
        refreshed = self._auth.refresh_token()
        if not refreshed:
            # Log warning but continue — token may still be valid for a short time
            import logging
            logging.getLogger(__name__).warning(
                "OAuth token is expiring and refresh is not yet implemented. "
                "Run 'claudeclaw login' if authentication fails."
            )
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
pytest tests/test_oauth_refresh.py -v
```

Expected: 4 PASSED.

- [ ] **Step 6: Run full test suite**

```bash
pytest tests/ -v
```

Expected: All tests pass.

- [ ] **Step 7: Commit**

```bash
git add claudeclaw/auth/oauth.py claudeclaw/subagent/dispatch.py tests/test_oauth_refresh.py
git commit -m "feat(security): OAuth token refresh stub wired into pre-dispatch path"
```

---

## Summary

Plan 6 delivers:

| Component | File | Status after Plan 6 |
|---|---|---|
| `OpenShell` | `claudeclaw/security/openshell.py` | Working: all 4 policies enforced |
| `OpenShellTool` | `claudeclaw/security/openshell.py` | Working: SDK-compatible wrapper |
| Dispatcher tool injection | `claudeclaw/subagent/dispatch.py` | Working: policy → tool mapping |
| Plugin signature stub | `claudeclaw/security/signature.py` | Stub: hardcoded trusted list |
| Per-installation salt | `claudeclaw/auth/keyring.py` | Working: random salt + migration |
| OAuth token refresh | `claudeclaw/auth/oauth.py` | Stub: returns False, wired to dispatch |
