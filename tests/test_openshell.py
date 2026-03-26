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
