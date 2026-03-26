# tests/test_plugin_manager.py
import json
import pytest
from pathlib import Path
from claudeclaw.plugins.manager import PluginManifest, parse_manifest
import importlib.metadata
from unittest.mock import patch, MagicMock
from claudeclaw.plugins.manager import (
    install, list_plugins, uninstall, _plugins_registry_path
)


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
