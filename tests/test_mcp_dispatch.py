# tests/test_mcp_dispatch.py
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


def test_dispatch_passes_mcp_servers_to_sdk(tmp_path, monkeypatch, skill_with_agent_mcp):
    monkeypatch.setenv("CLAUDECLAW_HOME", str(tmp_path))
    (tmp_path / "config").mkdir(parents=True, exist_ok=True)
    save_mcps([
        MCPConfig(name="filesystem", command="npx", args=["-y", "@mcp/fs"], scope="global"),
        MCPConfig(name="postgres", command="npx", args=["-y", "@mcp/pg"], scope="agent"),
    ])

    dispatcher = SubagentDispatcher()
    mock_response = MagicMock(content=[MagicMock(text="done")], stop_reason="end_turn")

    with patch.object(dispatcher._client.messages, "create", return_value=mock_response) as mock_create:
        dispatcher.dispatch(skill=skill_with_agent_mcp, user_message="run task", credentials={})

    call_kwargs = mock_create.call_args.kwargs
    mcp_servers = call_kwargs.get("mcp_servers") or call_kwargs.get("tools", [])
    # Both filesystem (global) and postgres (declared) should be present
    assert len(mcp_servers) == 2


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
    mock_response = MagicMock(content=[MagicMock(text="ok")], stop_reason="end_turn")

    with patch.object(dispatcher._client.messages, "create", return_value=mock_response) as mock_create:
        dispatcher.dispatch(skill=skill, user_message="go", credentials={})

    call_kwargs = mock_create.call_args.kwargs
    mcp_servers = call_kwargs.get("mcp_servers", [])
    assert mcp_servers == []
