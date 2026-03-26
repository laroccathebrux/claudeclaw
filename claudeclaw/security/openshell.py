# claudeclaw/security/openshell.py
from __future__ import annotations

import subprocess
from dataclasses import dataclass

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
