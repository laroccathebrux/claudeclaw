# tests/test_mcp_dispatch.py
import json
import pytest
from unittest.mock import MagicMock, patch
from claudeclaw.mcps.config import MCPConfig, save_mcps
from claudeclaw.subagent.dispatch import SubagentDispatcher
from claudeclaw.skills.loader import SkillManifest


@pytest.fixture
def dispatcher():
    return SubagentDispatcher()


@pytest.fixture
def skill_with_agent_mcp():
    return SkillManifest(
        name="test-skill",
        description="test",
        trigger="on-demand",
        autonomy="ask",
        shell_policy="none",
        body="",
        mcps_agent=["postgres"],
        credentials=[],
    )


def _mock_run():
    mock = MagicMock()
    mock.returncode = 0
    mock.stdout = json.dumps({"result": "done", "stop_reason": "end_turn"})
    mock.stderr = ""
    return mock


def test_dispatch_passes_mcp_servers_to_sdk(tmp_path, monkeypatch, skill_with_agent_mcp):
    monkeypatch.setenv("CLAUDECLAW_HOME", str(tmp_path))
    (tmp_path / "config").mkdir(parents=True, exist_ok=True)
    save_mcps([
        MCPConfig(name="filesystem", command="npx", args=["-y", "@mcp/fs"], scope="global"),
        MCPConfig(name="postgres", command="npx", args=["-y", "@mcp/pg"], scope="agent"),
    ])

    dispatcher = SubagentDispatcher()
    with patch("claudeclaw.subagent.dispatch.subprocess.run", return_value=_mock_run()) as mock_run:
        dispatcher.dispatch(skill=skill_with_agent_mcp, user_message="run task", credentials={})

    cmd = mock_run.call_args.args[0]
    assert "--mcp-config" in cmd
    mcp_json = cmd[cmd.index("--mcp-config") + 1]
    servers = json.loads(mcp_json)
    # Both filesystem (global) and postgres (declared) should be present
    assert len(servers) == 2


def test_dispatch_excludes_undeclared_agent_mcp(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDECLAW_HOME", str(tmp_path))
    (tmp_path / "config").mkdir(parents=True, exist_ok=True)
    save_mcps([
        MCPConfig(name="gmail", command="npx", args=[], scope="agent"),
    ])
    skill = SkillManifest(
        name="bare-skill", description="t", trigger="on-demand",
        autonomy="ask", shell_policy="none", body="", credentials=[],
    )

    dispatcher = SubagentDispatcher()
    with patch("claudeclaw.subagent.dispatch.subprocess.run", return_value=_mock_run()) as mock_run:
        dispatcher.dispatch(skill=skill, user_message="go", credentials={})

    cmd = mock_run.call_args.args[0]
    assert "--mcp-config" not in cmd
