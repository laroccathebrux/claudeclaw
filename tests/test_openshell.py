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
