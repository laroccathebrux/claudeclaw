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
            installed_at="2026-03-25T00:00:00+00:00", mcps=["gmail"], skills=["email-monitor"],
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
