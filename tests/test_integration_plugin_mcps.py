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
        body="Follow up with leads.",
        mcps_agent=["crm-api"],
        credentials=[],
    )

    import json as _json
    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.stdout = _json.dumps({"result": "done", "stop_reason": "end_turn"})
    mock_proc.stderr = ""

    dispatcher = SubagentDispatcher()
    with patch("claudeclaw.subagent.dispatch.subprocess.run", return_value=mock_proc) as mock_run:
        dispatcher.dispatch(skill=skill, user_message="follow up with leads", credentials={})

    cmd = mock_run.call_args.args[0]
    assert "--mcp-config" in cmd
    mcp_json = cmd[cmd.index("--mcp-config") + 1]
    mcp_servers = _json.loads(mcp_json)
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
