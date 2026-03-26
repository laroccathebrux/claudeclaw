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
