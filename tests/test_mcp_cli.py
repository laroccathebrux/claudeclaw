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
        "--args", "-y", "--args", "@mcp/fs",
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
