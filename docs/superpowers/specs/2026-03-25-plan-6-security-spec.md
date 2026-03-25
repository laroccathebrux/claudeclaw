# ClaudeClaw — Plan 6 Sub-Spec: Security — OpenShell + Hardening

**Date:** 2026-03-25
**Status:** Draft
**Author:** Alessandro Silveira
**Plan:** 6 of N
**Depends on:** Plan 1 (CredentialStore, SubagentDispatcher, SkillManifest), Plan 5 (plugin install flow)

---

## Overview

Plan 6 hardens the ClaudeClaw runtime with four complementary security improvements:

1. **OpenShell** — a cross-platform sandboxed shell execution layer that enforces `shell-policy` from skill frontmatter
2. **SubagentDispatcher update** — injects a custom `OpenShellTool` in place of the default `bash` tool based on the skill's declared policy
3. **Plugin signature verification** — stub that checks trusted publishers before `claudeclaw plugin install` proceeds
4. **PBKDF2 per-installation salt** — replaces Plan 1's fixed salt with a randomly generated per-installation salt, with migration logic for existing credential stores

An additional minor item covers **OAuth token refresh** wired into the pre-dispatch path.

---

## 1. OpenShell

### Purpose

OpenShell is a sandboxed shell execution layer used by both **OpenClaw** and **NemoClaw** (Nvidia). They share the same `OpenShell` interface. All shell command execution from subagents routes through this layer — nothing reaches the OS shell directly.

### Policy model

The `shell-policy` field in each skill's frontmatter determines which commands OpenShell permits:

| Policy | Behavior |
|---|---|
| `none` | No shell access. Any call to `execute()` is immediately rejected (blocked=True, no subprocess). The SubagentDispatcher does not inject any bash tool at all for this policy. |
| `read-only` | Only commands matching the read-only allowlist are permitted. Write and exec commands are rejected. |
| `restricted` | Only commands matching the per-installation allowlist at `~/.claudeclaw/config/shell-allowlist.yaml` are permitted. All others are rejected. |
| `full` | Unrestricted execution. Not recommended for marketplace skills. |

### Module: `claudeclaw/security/openshell.py`

#### Classes

```python
@dataclass
class ShellResult:
    stdout: str
    stderr: str
    exit_code: int
    blocked: bool          # True when policy rejected the command without executing it


class OpenShell:
    def __init__(self, policy: str):
        ...

    def execute(self, command: str, timeout: int = 30) -> ShellResult:
        """
        Validate command against the active policy, then execute via subprocess
        if allowed. Returns ShellResult. Never raises on block — sets blocked=True
        and returns immediately.
        """
```

#### Policy enforcement logic

**`none`:**
Return `ShellResult(stdout="", stderr="Shell access denied by policy 'none'", exit_code=1, blocked=True)` immediately.

**`read-only`:**
Parse the leading token(s) of the command string (handles pipes, redirects, shell operators). Reject if any token or compound command attempts a write or exec operation. The read-only allowlist is a hardcoded set of safe command prefixes:

```
ls, cat, head, tail, find, grep, rg, awk, sed (read-only forms), echo, pwd, whoami,
wc, sort, uniq, cut, diff, stat, file, which, type, env, printenv, date, du, df,
less, more, strings, hexdump, xxd
```

Any command not matching one of these prefixes (or any command containing shell write operators `>`, `>>`, `|>`, `;`, `&&`, `||` followed by non-read commands) is rejected.

Implementation note: the check is conservative. A command is permitted only if the primary command token appears in the allowlist AND the command contains no write-side operators that introduce a non-allowlisted secondary command. When in doubt, reject.

**`restricted`:**
Load `~/.claudeclaw/config/shell-allowlist.yaml` (see format below). The command's primary token must appear in the `allowed_commands` list. If the file does not exist, reject all commands (fail safe).

**`full`:**
No validation. Execute directly via subprocess.

#### Subprocess execution

For all permitted policies, execution uses `subprocess.run` with:
- `shell=True` on Windows (PowerShell restricted execution policy for `restricted` mode)
- `shell=True` with a custom restricted PATH on macOS/Linux (`restricted` mode strips the PATH to only directories in the allowlist's `allowed_paths` field; defaults to `/usr/bin:/bin`)
- `timeout=timeout` (default 30 seconds)
- `capture_output=True`
- `text=True`

On `subprocess.TimeoutExpired`, return `ShellResult(stdout="", stderr="Command timed out", exit_code=124, blocked=False)`.

#### Platform-specific behavior

**macOS/Linux — `restricted` mode:**
```python
import os
env = os.environ.copy()
env["PATH"] = config.get("allowed_paths", "/usr/bin:/bin")
subprocess.run(command, shell=True, env=env, ...)
```

**Windows — `restricted` mode:**
```python
# Wrap in PowerShell with constrained language mode
powershell_cmd = f'powershell.exe -ExecutionPolicy Restricted -Command "{command}"'
subprocess.run(powershell_cmd, shell=True, ...)
```

### Shell allowlist configuration file

Path: `~/.claudeclaw/config/shell-allowlist.yaml`

```yaml
# ClaudeClaw restricted shell allowlist
# Commands not listed here are blocked when shell-policy: restricted

allowed_commands:
  - ls
  - cat
  - grep
  - python
  - pip
  - git

allowed_paths: "/usr/local/bin:/usr/bin:/bin"
```

If this file does not exist when `restricted` policy is active, OpenShell rejects all commands and logs a warning directing the user to create it.

---

## 2. SubagentDispatcher Update

### Purpose

The dispatcher must replace the Claude SDK's default `bash` tool with an `OpenShellTool` that routes through OpenShell when the skill declares a shell policy.

### Behavior by policy

| `shell-policy` | Tool injected |
|---|---|
| `none` | No bash tool injected. The tool list for the subagent does not include any shell tool. |
| `read-only` | `OpenShellTool(policy="read-only")` replaces the default bash tool |
| `restricted` | `OpenShellTool(policy="restricted")` replaces the default bash tool |
| `full` | `OpenShellTool(policy="full")` replaces the default bash tool (or default bash tool may be used as-is) |

### `OpenShellTool`

`OpenShellTool` is a Claude SDK-compatible tool definition (a callable or tool spec) that wraps `OpenShell.execute()`. It presents the same interface to the subagent as the standard bash tool but internally routes through the policy layer.

```python
# claudeclaw/security/openshell.py

class OpenShellTool:
    """
    A Claude SDK tool that wraps OpenShell for injection into subagent dispatch.
    Presents as a bash-compatible tool to the subagent.
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

### Dispatcher injection point

In `claudeclaw/subagent/dispatch.py`, the `SubagentDispatcher.dispatch()` method already constructs the tool list for the subagent. Plan 6 adds:

```python
def _build_tools(self, skill: SkillManifest) -> list:
    tools = []
    # ... existing tool building ...

    policy = skill.shell_policy
    if policy == "none":
        pass  # do not add any shell tool
    else:
        tools.append(OpenShellTool(policy=policy))

    return tools
```

---

## 3. Plugin Signature Verification

### Purpose

Before installing a plugin via `claudeclaw plugin install <name>`, verify that the package comes from a trusted publisher. Plan 6 implements a stub — a hardcoded list of trusted publisher namespaces — as the foundation for full PKI in a later plan.

### Module: `claudeclaw/security/signature.py`

```python
TRUSTED_PUBLISHERS = {
    "claudeclaw-plugin-gmail",
    "claudeclaw-plugin-telegram",
    "claudeclaw-plugin-slack",
    "claudeclaw-plugin-postgres",
    "claudeclaw-plugin-whatsapp",
}


def verify_plugin(package_name: str, version: str) -> bool:
    """
    Verify that a plugin package is from a trusted publisher.

    Plan 6 stub: checks against a hardcoded trusted publisher list.
    Returns True if trusted, False if unverified.
    Logs a warning for unverified packages and prompts user confirmation.

    Full PKI verification is out of scope for Plan 6.
    """
```

### Integration with plugin install CLI

In `claudeclaw/cli.py`, the `plugin install` command calls `verify_plugin()` before `pip install`:

```
1. Call verify_plugin(package_name, version="latest")
2. If returns False:
   - Print warning: "WARNING: Package '{name}' is not in the ClaudeClaw trusted publisher list."
   - Prompt: "Install anyway? [y/N]"
   - If user answers N (default): abort
   - If user answers Y: proceed with pip install
3. If returns True: proceed silently
```

---

## 4. PBKDF2 Per-Installation Salt

### Problem

Plan 1 used a hardcoded salt `b"claudeclaw-salt-v1"` in `claudeclaw/auth/keyring.py`. A fixed salt means that two installations with the same master password produce the same derived key, weakening the PBKDF2 protection.

### Solution

On first run, generate a random 32-byte salt and store it at `~/.claudeclaw/config/keystore-salt`. Subsequent runs load this salt. The salt file is plaintext — salt is not a secret; its purpose is uniqueness.

### Changes to `claudeclaw/auth/keyring.py`

```python
SALT_FILE_NAME = "keystore-salt"

def _load_or_create_salt(config_dir: Path) -> bytes:
    salt_path = config_dir / SALT_FILE_NAME
    if salt_path.exists():
        return bytes.fromhex(salt_path.read_text().strip())
    salt = os.urandom(32)
    salt_path.write_text(salt.hex())
    return salt


def _derive_key(master_password: str, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=480_000)
    return base64.urlsafe_b64encode(kdf.derive(master_password.encode()))
```

The `_FileBackend.__init__` receives the salt from `_load_or_create_salt()` instead of using the hardcoded constant.

### Migration from fixed salt

When `_FileBackend` initializes, if it detects an existing `credentials.enc` file but no `keystore-salt` file, it assumes the credential store was created with the old fixed salt. It:

1. Attempts to decrypt with the old fixed salt `b"claudeclaw-salt-v1"`
2. If successful: decrypts all credentials, generates a new random salt, re-encrypts the store with the new salt, writes `keystore-salt`
3. If decryption fails with the old salt: assumes the file uses a new salt (should not happen) or is corrupted — raises a descriptive error

```python
def _migrate_if_needed(self, config_dir: Path, master_password: str):
    """Migrate credential store from fixed salt to per-installation salt."""
    cred_file = config_dir / "credentials.enc"
    salt_file = config_dir / SALT_FILE_NAME

    if cred_file.exists() and not salt_file.exists():
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
        except Exception:
            raise CredentialMigrationError(
                "Found credentials.enc without keystore-salt. "
                "Migration from fixed salt failed — check your master password."
            )
        new_salt = os.urandom(32)
        salt_file.write_text(new_salt.hex())
        new_key = _derive_key(master_password, new_salt)
        new_fernet = Fernet(new_key)
        cred_file.write_bytes(new_fernet.encrypt(json.dumps(data).encode()))
```

---

## 5. OAuth Token Refresh

### Purpose

Ensure the Claude OAuth token is valid before each subagent dispatch. If the token is expiring within 5 minutes, refresh it proactively.

### Changes to `claudeclaw/auth/oauth.py`

```python
class AuthManager:
    def is_token_expiring(self, within_seconds: int = 300) -> bool:
        """Return True if the stored token expires within `within_seconds`."""

    def refresh_token(self) -> bool:
        """
        Attempt to refresh the OAuth token using the stored refresh token.
        Returns True on success, False on failure.
        Stub in Plan 6: same implementation status as Plan 1's _exchange_code.
        """
```

### Integration with SubagentDispatcher

In `dispatch.py`, before constructing the subagent:

```python
if self._auth.is_token_expiring():
    refreshed = self._auth.refresh_token()
    if not refreshed:
        raise AuthError("OAuth token is expiring and refresh failed. Run 'claudeclaw login' to re-authenticate.")
```

---

## 6. Scope Boundaries

### In scope for Plan 6

- `OpenShell` class with `execute()` and `ShellResult`
- All four policy modes: `none`, `read-only`, `restricted`, `full`
- Shell allowlist YAML config
- `OpenShellTool` wrapper for SubagentDispatcher injection
- `verify_plugin()` stub with hardcoded trusted publisher list
- Per-installation PBKDF2 salt: generate, store, load
- Migration from fixed salt to per-installation salt
- `AuthManager.refresh_token()` stub wired to pre-dispatch path

### Out of scope for Plan 6

- Full PKI infrastructure and certificate chains for plugin signing
- Sandboxed filesystem (chroot / container isolation)
- Network isolation for subagents
- Audit log of all blocked shell commands (beyond in-memory logging)
- OpenShell integration with NemoClaw (interface compatibility is the goal; NemoClaw integration is a separate concern)
